# 校园通知助手 v0.2 (M1+)

> 中南民族大学通知抓取 + 存储 + 预览 + 导出

## 功能

| 功能 | 说明 |
|------|------|
| 多数据源抓取 | 创新创业学院/教务处管理文件 |
| 自动日期提取 | 列表页提取，支持多种日期格式 |
| 去重 + 更新 | 重复抓取自动跳过，无日期记录自动补充 |
| 手动抓取 | 输入任意 URL，预览后决定是否保存 |
| 导出 | CSV / JSON / Markdown 三种格式 |
| 配置化 | YAML 配置数据源、超时、延迟等 |

## 快速开始

```bash
# 1. 安装依赖
pip install requests beautifulsoup4 newspaper4k pyyaml

# 2. 运行交互菜单
python main.py
```

## 使用说明

```
====================================
    校园通知助手 v0.2 (M1+)
====================================

1. 抓取所有数据源
2. 查看通知列表
3. 查看统计信息
4. 手动抓取指定URL（预览模式）
5. 导出通知
0. 退出
```

### 功能说明

**1. 抓取所有数据源**
自动抓取 `config/scuec.yaml` 中启用的数据源，支持去重和日期补充。

**4. 手动抓取（预览模式）**
```
请输入列表页 URL: https://www.scuec.edu.cn/jwc/glwj.htm
来源名称（可选）: 教务处
最大翻页数（默认 5）: 3

抓取到 13 条通知：
  1. [2026-06-16] 中南民族大学计算机课程免修认定办法
     内容预览: 第一章 总则 第一条 为适应我国大学计算机...
  ...

是否保留这些抓取结果？(y/n): y
```

**5. 导出通知**
支持三种格式：
- **CSV** — Excel 打开，最通用
- **JSON** — 开发者/API 集成
- **Markdown** — 文档分享，可读性好

导出文件保存在 `exports/` 目录。

## 配置文件

`config/scuec.yaml` 支持以下字段：

```yaml
school:
  name: 中南民族大学
  code: scuec

sources:
  - name: 创新创业学院-竞赛通知
    enabled: true           # 可禁用某个源
    list_url: https://...
    url_pattern: "..."      # 可选：URL 正则
    max_pages: 20           # 最大翻页数

crawl:
  timeout: 15               # HTTP 超时（秒）
  delay: 1                  # 请求间隔（秒，防封）
  user_agent: "CampusAssistant/1.0"

export:
  output_dir: exports
  formats: [csv, json, markdown]
```

## 项目结构

```
campus_notice_assistant/
├── main.py              # 交互式入口
├── crawl.py             # 命令行抓取入口
├── config/scuec.yaml    # 数据源配置
├── crawler/
│   ├── base.py          # 列表页解析 + 翻页发现
│   └── web_crawler.py   # 网页爬虫
├── storage/
│   ├── db.py            # SQLite 存储
│   └── models.py        # 数据模型
├── data/notices.db      # 数据库（自动创建）
└── exports/             # 导出目录（自动创建）
```

## 技术栈

- Python 3.11+
- newspaper4k — 新闻提取
- requests + BeautifulSoup — 网页抓取
- SQLite — 本地存储
- PyYAML — 配置管理

## 后续版本

- **v0.3 (M2)**：LLM 结构化提取（截止时间、通知类型）
- **v0.4 (M3)**：待办生成 + 列表
- **v0.5 (M4)**：RAG 智能问答
- **v0.6 (M5)**：Streamlit 界面整合
