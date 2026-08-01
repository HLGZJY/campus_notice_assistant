# 校园通知助手 v0.1 (M1)

> 中南民族大学通知抓取 + 存储 — 阶段性成果

## 功能

自动抓取学校通知网站，存入本地 SQLite 数据库：

| 来源 | 列表页 |
| ---- | ------ |
| 创新创业学院-竞赛通知 | `cxcy/scss/jstz.htm` |
| 创新创业学院-结果公示 | `cxcy/scss/jggs.htm` |
| 教务处-管理文件 | `jwc/glwj.htm` |

## 快速开始

```bash
# 1. 安装依赖（只需 requests + beautifulsoup4 + newspaper4k + pyyaml）
pip install requests beautifulsoup4 newspaper4k pyyaml

# 2. 运行交互菜单
python main.py
```

## 使用说明

运行 `python main.py` 后进入交互菜单：

```
====================================
    校园通知助手 v0.1 (M1)
====================================
 数据源: 创新创业学院 / 教务处管理文件

1. 抓取通知
2. 查看通知列表
3. 查看统计信息
0. 退出

请选择:
```

- **选 1**：抓取所有配置的数据源，支持去重（重复运行不会重复抓取）
- **选 2**：按来源分组展示通知列表（标题 + 日期）
- **选 3**：显示各来源数量、数据库大小等统计

## 项目结构

```
campus_notice_assistant/
├── main.py              # 交互式入口（本版本核心）
├── crawl.py             # 命令行抓取入口
├── config/scuec.yaml    # 数据源配置
├── crawler/
│   ├── base.py          # 列表页解析 + 翻页发现
│   └── web_crawler.py   # 网页爬虫（newspaper4k）
├── storage/
│   ├── db.py            # SQLite 存储
│   └── models.py        # 数据模型
└── data/notices.db      # 数据库文件（自动创建）
```

## 技术栈

- Python 3.11+
- newspaper4k — 新闻提取
- requests + BeautifulSoup — 网页抓取
- SQLite — 本地存储
- PyYAML — 配置管理

## 后续版本

- **v0.2 (M2)**：LLM 结构化提取（截止时间、通知类型）
- **v0.3 (M3)**：待办生成 + 列表
- **v0.4 (M4)**：RAG 智能问答
- **v0.5 (M5)**：Streamlit 界面整合
