# 校园通知智能助手

> Campus Notice Assistant — 把校园通知变成可执行的待办清单

## 这是什么

一个能自动抓取学校各类通知网站、用 LLM 提取关键信息（截止时间、地点、报名链接、面向对象）、生成个性化待办清单的智能助手。

本项目源于 `Llama 3.1 本地 RAG` 项目的延伸，从"与单个网页对话"演进到"自动监控多来源通知 + 结构化提取 + 待办管理"。

## 核心能力

- **多来源抓取**：学校官网、学院/部门网站、教务处通知、微信公众号
- **结构化提取**：自动识别通知类型、截止时间、地点、报名链接、面向对象
- **待办生成**：把通知转成可执行的待办项，支持提醒
- **单链接分析**：粘贴任意校园通知详情链接，即时抓取、结构化、生成待办
- **学校可配置**：通用架构，通过配置文件适配不同学校

## MVP 范围

MVP 阶段先用 **中南民族大学 (scuec.edu.cn)** 验证，核心场景是 **结构化提取 + 待办生成 + 单链接分析**。

## 文档导航

| 文档                                         | 内容                         | 给谁看    |
| -------------------------------------------- | ---------------------------- | --------- |
| [docs/PRD.md](docs/PRD.md)                   | 产品需求、用户故事、功能清单 | 产品/需求 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 技术架构、模块设计、数据流   | 开发      |
| [docs/DATA-MODEL.md](docs/DATA-MODEL.md)     | 数据表结构、Pydantic 模型    | 开发      |
| [docs/ROADMAP.md](docs/ROADMAP.md)           | 开发路线图、里程碑           | 项目管理  |

## 技术栈

| 层         | 选型                                   | 说明                      |
| ---------- | -------------------------------------- | ------------------------- |
| LLM        | opencode-go (Kimi K2.7 Code)           | OpenAI 兼容接口，线上调用 |
| Embedding  | sentence-transformers/all-MiniLM-L6-v2 | 本地轻量模型，384 维      |
| 向量库     | Chroma                                 | 轻量，嵌入式              |
| Agent 框架 | OpenAI Agents SDK                      | Capstone 课程要求         |
| 前端       | Streamlit                              | MVP 快速验证              |
| 数据存储   | SQLite                                 | 轻量，单文件              |
| 抓取       | newspaper4k + BeautifulSoup            | 通用网页抓取 + 结构化提取 |

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 opencode-go API key（OPENCODE_API_KEY / OPENCODE_BASE_URL / LLM_MODEL）

# 3. 初始化数据库（自动建表、迁移）
python -c "from storage.db import get_connection; get_connection(); print('DB ready')"

# 4. 统一入口：启动 Web 应用（推荐）
streamlit run app.py
```

### Web 应用功能（`streamlit run app.py`）

| 模块 | 说明 |
|------|------|
| 📊 **总览** | 统计概览、紧急待办、最新通知、未处理提醒 |
| 📬 **通知中心** | 单链接分析 / 全部通知浏览（筛选+搜索）/ 未处理通知一键重新提取 |
| 🎯 **待办事项** | 按紧急度分组（已过期 / 本周截止 / 更晚 / 已完成），完成/跳过/恢复管理 |
| ⚙️ **设置与导出** | 抓取源管理（新增/编辑/删除）、数据管理（通知+待办 CRUD）、批量提取、抓取日志、CSV/JSON/Markdown 导出 |

### CLI 命令（依然可用）

```bash
# 抓取通知（M1）
python crawl.py                          # 用默认配置抓取
python crawl.py --list-url <URL>         # 抓取指定列表页

# 批量结构化提取（M2）
python extract.py                        # 提取所有 status=raw 的通知
python extract.py --limit 10             # 最多提取 10 条
python extract.py --status failed        # 重试提取失败的

# 待办管理（M3）
python todo.py --notice 2                # 为指定通知生成待办
python todo.py --list                    # 列出全部待办（按截止升序）
python todo.py --done 3                  # 标记完成
python todo.py --skip 3                  # 标记跳过
```

## 项目状态

- [x] 概念验证（RAG 与网页对话）— 已在 `Llama 3.1 本地 RAG` 项目完成
- [x] M1 抓取 + 存储
- [x] M2 结构化提取
- [x] M3 待办生成 + 列表
- [x] 统一 Web 应用（总览 + 通知中心 + 待办事项 + 设置与导出）
- [x] 抓取源管理（UI 新增/编辑/删除配置源）
- [x] 数据 CRUD（通知编辑/删除、待办编辑/删除、批量删除）
- [ ] M4 RAG 问答
- [ ] M5 多学校适配
- [ ] M6 主动推送提醒

## 关联项目

- [Llama 3.1 本地 RAG](../Llama%203.1%20本地%20RAG%20-%20与任意网页对话，完全离线) — 本项目的前身，验证了 RAG 与网页对话的可行性
