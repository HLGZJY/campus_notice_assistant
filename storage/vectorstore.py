"""Chroma 向量索引（M4）。

基于 langchain 的 Chroma + HuggingFaceEmbeddings/OpenAIEmbeddings fallback，
提供通知的切分、索引、增量更新和语义检索能力。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from utils.embedding import get_embeddings

logger = logging.getLogger(__name__)

DEFAULT_PERSIST_DIR = Path(__file__).parent.parent / "data" / "chroma"
COLLECTION_NAME = "notices"

# 中文-aware 切分器：优先在段落、句子、中文标点处断开，避免把单个字切碎
TEXT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    separators=["\n\n", "\n", "。", "；", "！", "？", "，", " ", ""],
)


def _doc_id(notice_id: int, chunk_idx: int) -> str:
    return f"notice_{notice_id}_chunk_{chunk_idx}"


def _split_notice(notice: dict) -> list[Document]:
    """把一条通知切分为多个 chunk，首块附加标题/类型/摘要等元信息。"""
    notice_id = notice["id"]
    title = notice.get("title") or ""
    notice_type = notice.get("notice_type") or ""
    summary = notice.get("summary") or ""
    deadline = notice.get("deadline") or ""
    raw_content = notice.get("raw_content") or ""

    header_parts = [f"标题：{title}"]
    if notice_type:
        header_parts.append(f"类型：{notice_type}")
    if summary:
        header_parts.append(f"摘要：{summary}")
    if deadline:
        header_parts.append(f"截止时间：{deadline}")
    header = "\n".join(header_parts)

    # 把 header 拼在正文前面一起切分：header 会自然落在首块，帮助检索
    text_with_header = f"{header}\n\n{raw_content}"
    docs = TEXT_SPLITTER.create_documents([text_with_header])

    result = []
    for idx, doc in enumerate(docs):
        doc.metadata.update({
            "notice_id": notice_id,
            "title": title,
            "notice_type": notice_type,
            "source": notice.get("source") or "",
            "url": notice.get("url") or "",
            "deadline": deadline,
            "published_at": notice.get("published_at") or "",
            "chunk_idx": idx,
            "status": notice.get("status") or "",
        })
        result.append(doc)
    return result


class VectorIndex:
    """通知向量索引。"""

    def __init__(
        self,
        persist_dir: Optional[Path] = None,
        collection_name: str = COLLECTION_NAME,
    ):
        self.persist_dir = persist_dir or DEFAULT_PERSIST_DIR
        self.collection_name = collection_name
        self._embedding = get_embeddings()
        self._store: Optional[Chroma] = None

    def _get_store(self, force_rebuild: bool = False) -> Chroma:
        if self._store is not None and not force_rebuild:
            return self._store

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._store = Chroma(
            persist_directory=str(self.persist_dir),
            embedding_function=self._embedding,
            collection_name=self.collection_name,
            collection_metadata={"hnsw:space": "cosine"},
        )
        return self._store

    def count(self) -> int:
        """返回当前 collection 中文档数。"""
        try:
            return self._get_store()._collection.count()
        except Exception as e:
            logger.warning(f"统计向量库失败: {e}")
            return 0

    def stats(self) -> dict:
        """返回向量库统计信息。"""
        count = self.count()
        try:
            collection = self._get_store()._collection
            # Chroma collection 的 metadata 不一定包含总通知数，这里仅返回文档数
            return {"chunks": count, "persist_dir": str(self.persist_dir)}
        except Exception as e:
            return {"chunks": count, "error": str(e)}

    def rebuild(self, notices: list[dict], dry_run: bool = False) -> dict:
        """全量重建索引：删除旧 collection，重新切分并索引所有通知。

        返回 {"notices": 通知数, "chunks": 分块数}
        """
        if dry_run:
            chunks = sum(len(_split_notice(n)) for n in notices)
            return {"notices": len(notices), "chunks": chunks, "dry_run": True}

        # 删除旧 collection（如果存在）
        self.delete_collection()
        store = self._get_store(force_rebuild=True)

        all_docs: list[Document] = []
        all_ids: list[str] = []
        for notice in notices:
            docs = _split_notice(notice)
            for idx, doc in enumerate(docs):
                all_docs.append(doc)
                all_ids.append(_doc_id(notice["id"], idx))

        if all_docs:
            store.add_documents(all_docs, ids=all_ids)
            logger.info(f"已索引 {len(notices)} 条通知，共 {len(all_docs)} 个 chunk")
        else:
            logger.info("没有可索引的通知")

        return {"notices": len(notices), "chunks": len(all_docs)}

    def add_notice(self, notice: dict) -> dict:
        """单条通知增量索引（先删除该通知旧 chunk，再添加新 chunk）。"""
        store = self._get_store()
        notice_id = notice["id"]
        self.remove_notice(notice_id)

        docs = _split_notice(notice)
        ids = [_doc_id(notice_id, idx) for idx in range(len(docs))]
        if docs:
            store.add_documents(docs, ids=ids)
        return {"notice_id": notice_id, "chunks": len(docs)}

    def remove_notice(self, notice_id: int) -> int:
        """删除某通知的所有 chunk，返回删除数量（估算）。"""
        store = self._get_store()
        try:
            # chroma where 过滤只支持字符串/数字等标量
            store.delete(where={"notice_id": notice_id})
            logger.debug(f"已删除 notice_id={notice_id} 的旧 chunk")
            return -1  # chroma delete 不直接返回数量
        except Exception as e:
            logger.warning(f"删除 notice_id={notice_id} 失败: {e}")
            return 0

    def delete_collection(self) -> None:
        """删除整个 collection（用于重建）。"""
        try:
            client = self._get_store()._client
            client.delete_collection(name=self.collection_name)
            self._store = None
            logger.info(f"已删除旧 collection: {self.collection_name}")
        except Exception as e:
            logger.warning(f"删除 collection 失败（可能不存在）: {e}")

    def search(self, query: str, k: int = 6) -> list[Document]:
        """语义检索 Top-K 文档块。"""
        store = self._get_store()
        return store.similarity_search(query, k=k)


# ---------- 便捷函数 ----------


def get_vector_index(persist_dir: Optional[Path] = None) -> VectorIndex:
    """获取默认 VectorIndex 实例。"""
    return VectorIndex(persist_dir=persist_dir)
