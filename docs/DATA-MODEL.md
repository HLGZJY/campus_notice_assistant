# 数据模型设计

## 1. SQLite 表结构

### 1.1 notices（通知表）

```sql
CREATE TABLE notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,           -- 通知详情页 URL（去重依据）
    source TEXT NOT NULL,               -- 来源：scuec/cxcy
    title TEXT NOT NULL,                -- 原始标题
    raw_content TEXT,                   -- 原始正文
    published_at TEXT,                  -- 发布时间（ISO 8601）
    crawled_at TEXT NOT NULL,           -- 抓取时间
    status TEXT DEFAULT 'raw',          -- raw/extracted/partial/failed
    -- 结构化提取结果（M2 提取后填充）
    notice_type TEXT,                   -- competition/lecture/registration/...
    target_audience TEXT,               -- 面向对象
    signup_method TEXT,                 -- 报名方式（QQ群/邮箱/扫码描述，自由文本）
    signup_url TEXT,                    -- 报名网页链接（仅当有真实 URL）
    location TEXT,                      -- 地点
    location_type TEXT,                 -- online/offline/hybrid
    deadline TEXT,                      -- 截止时间（ISO 8601，解析器重算）
    deadline_raw TEXT,                  -- 截止时间原文片段（可溯源/校验）
    key_dates_json TEXT,                -- 其他重要时间点（JSON 数组）
    summary TEXT,                       -- 摘要
    extracted_at TEXT                   -- 提取时间
);

CREATE INDEX idx_notices_status ON notices(status);
CREATE INDEX idx_notices_deadline ON notices(deadline);
CREATE INDEX idx_notices_type ON notices(notice_type);
```

### 1.2 todos（待办表）

```sql
CREATE TABLE todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id INTEGER NOT NULL,          -- 关联通知
    action TEXT NOT NULL,                -- 待办内容，如"提交数学建模报名表"
    due_at TEXT,                         -- 截止时间
    status TEXT DEFAULT 'pending',       -- pending/done/skipped
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (notice_id) REFERENCES notices(id)
);

CREATE INDEX idx_todos_status ON todos(status);
CREATE INDEX idx_todos_due ON todos(due_at);
```

### 1.3 crawl_log（抓取日志）

```sql
CREATE TABLE crawl_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    url TEXT,
    status TEXT NOT NULL,               -- success/failed
    error TEXT,
    crawled_at TEXT NOT NULL
);
```

## 2. Pydantic 模型

### 2.1 通知提取结果

```python
from pydantic import BaseModel
from typing import Literal, Optional

# 通知类型枚举（10 类）
NoticeType = Literal[
    "competition",   # 竞赛
    "lecture",       # 讲座
    "registration",  # 报名/培训/选课
    "scholarship",   # 奖学金
    "administrative",# 行政事务（放假/注册/缴费）
    "recruitment",   # 招聘/实习
    "policy",        # 政策/资讯
    "result",        # 结果公示
    "news",          # 动态/新闻
    "other",         # 其他
]

class KeyDate(BaseModel):
    """一个重要的日期/时间点（如报名截止、初赛、决赛）。"""
    label: str             # 时间点含义，如"报名截止""初赛"
    date_raw: str          # 原文时间片段，如"5月23日12:00-17:00"
    datetime: str | None   # 规范化 ISO 8601（后处理填充）

class NoticeExtraction(BaseModel):
    """LLM 结构化提取输出"""
    notice_type: NoticeType
    title: str
    target_audience: str | None = None
    signup_method: str | None = None   # 报名方式自由文本（QQ群/邮箱/扫码）
    signup_url: str | None = None      # 报名网页链接（仅当有真实 URL）
    location: str | None = None
    location_type: Literal["online", "offline", "hybrid"] | None = None
    deadline_raw: str | None = None    # 截止时间原文片段（防幻觉/可校验）
    deadline: str | None = None        # ISO 8601（Python 解析器以 deadline_raw 重算为准）
    key_dates: list[KeyDate] = []
    summary: str | None = None
```

> **设计要点**
> - `deadline_raw` + `deadline` 双字段：LLM 只负责从原文中定位时间片段，
>   年份推断与 ISO 规范化由 `core/date_utils.py` 的解析器完成（比 LLM 直接
>   输出 ISO 更可靠，且可校验防幻觉）。无年份时用 `published_at` 年份，早于
>   发布日则用下一年。
> - `signup_method` 为自由文本：真实通知里 QQ 群号、邮箱、扫码占绝大多数，
>   URL 是少数，所以单独一个 URL 字段不够。
> - 状态三态：`extracted`（行动型且有行动字段）/ `partial`（政策/新闻/结果公示等
>   非行动型，无行动字段）/ `failed`（LLM 调用本身失败）。
> - 行动型类型 = competition/lecture/registration/scholarship/administrative/recruitment；
>   非行动型 = policy/result/news/other。

### 2.2 待办项

```python
class TodoItem(BaseModel):
    """单条待办"""
    action: str           # 待办内容
    due_at: str | None    # 截止时间
    priority: str = "normal"  # high/normal/low

class TodoList(BaseModel):
    """待办清单"""
    items: list[TodoItem]
```

### 2.3 通知卡片（前端展示）

```python
class NoticeCard(BaseModel):
    """前端展示用"""
    id: int
    title: str
    notice_type: str
    deadline: str | None
    location: str | None
    target_audience: str | None
    signup_method: str | None
    signup_url: str | None
    summary: str
    published_at: str | None
    source: str
    url: str
```

## 3. 向量库结构（Chroma）

```python
collection = chroma_client.create_collection(
    name="notices",
    metadata={"hnsw:space": "cosine"}
)

# 每条文档：
{
    "id": "notice_{notice_id}_chunk_{chunk_idx}",
    "embedding": [...],  # 384 维
    "document": "通知正文片段",
    "metadata": {
        "notice_id": 123,
        "title": "通知标题",
        "notice_type": "competition",
        "source": "scuec/cxcy"
    }
}
```

## 4. ER 关系

```mermaid
erDiagram
    notices ||--o{ todos : "生成"
    notices ||--o{ crawl_log : "记录"
    notices {
        int id PK
        string url UK
        string title
        string notice_type
        string deadline
        string status
    }
    todos {
        int id PK
        int notice_id FK
        string action
        string due_at
        string status
    }
    crawl_log {
        int id PK
        string source
        string url
        string status
    }
```
