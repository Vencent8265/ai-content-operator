# AI Content Operator

> 一个真实在跑的 AI Agent 内容运营系统 — 从资讯聚合到自动复盘的全闭环  
> 每日自动追踪 AI 领域最新动态，写成技术文章，推送审核后发布到抖音

[![Tests](https://img.shields.io/badge/tests-103%20passed-brightgreen)](https://github.com/Vencent8265/ai-content-operator/actions)
[![Python](https://img.shields.io/badge/python-3.11-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**解决的问题：** AI 领域信息过载 — 每天有大量论文、新闻、开源项目涌现，一个人根本看不过来。这个系统自动聚合全球 AI 资讯，整理成可发布的技术文章，审核后发布，并追踪数据复盘迭代。

---

## 实际运行流程

```
09:00  ┌─ 聚合 HN + ArXiv + GitHub 最新 AI 资讯 ─┐
       │  10-15 条热点自动抓取                      │
       └──────────────────────────────────────────┘
                         │
                         ▼
       ┌─ AI 成文（DeepSeek） ────────────────────┐
       │  标题 ≤30字 / 摘要 ≤30字 / 正文 500-1000字  │
       │  带 ## ### 层级标题 / 自动合规检查         │
       └──────────────────────────────────────────┘
                         │
                         ▼
       ┌─ 封面生成（通义万相） ───────────────────┐
       │  1024×1024 科技风格封面图                  │
       └──────────────────────────────────────────┘
                         │
                         ▼
       ┌─ 推送审核 ───────────────────────────────┐
       │  → 微信 + 飞书 双平台通知                  │
       │  → 文章同时保存到 data/articles/ 本地查看   │
       └──────────────────────────────────────────┘
                         │
                    👤 人工审核
                 通过 / 驳回 / 修改
                         │
                    👤 抖音发布
                         │
20:30  ┌─ 数据回收提醒 ──────────────────────────┐
       │  → 支持自然语言输入数据                      │
       │  → 自动结构化存储                           │
       └──────────────────────────────────────────┘
                         │
21:00  ┌─ 日复盘（LLM 驱动）───────────────────────┐
       │  → 关键洞察 + 改进建议 + 风险预警            │
       │  → 推送到微信/飞书                           │
       └──────────────────────────────────────────┘
```

---

## 为什么这样设计

| 决策 | 理由 |
|------|------|
| **资讯聚合而不是选题池** | AI 领域变化太快，选题池几天就过时。从真实资讯源聚合才能保证文章有时效性 |
| **DeepSeek 主力 + 通义千问备用** | DeepSeek 性价比最高（¥0.435/1M tokens），通义千问做封面生成 |
| **ModelRouter 适配层** | 换模型 = 改配置，不碰业务代码。所有模型统一走 OpenAI 兼容接口 |
| **JSON Schema 契约** | 每个 Agent 只认契约不认实现，后续换框架（LangGraph→CrewAI）不改核心逻辑 |
| **微信 + 飞书双平台审核** | 微信推送但频率限制严重，飞书做备份。cron 输出同时推两个平台 |
| **DIY 而不用 SaaS** | 不依赖第三方内容运营平台，所有逻辑可控可改，面试时有东西讲 |

---

## 技术栈

| 层 | 技术 | 选型原因 |
|------|------|---------|
| Agent 编排 | Python 脚本 → LangGraph（v2） | MVP 用简单脚本快速验证，v2 升级状态图 |
| 定时调度 | Hermes Cron | 原生集成，无需额外部署 |
| 模型层 | DeepSeek + 通义千问 + Anthropic | 适配器模式，随时换 |
| 封面生成 | 通义万相 wanx2.0 | 中文 prompt 效果好，API 便宜 |
| 消息推送 | Hermes Gateway（微信 + 飞书） | 同一套 API 多平台推送 |
| 数据存储 | JSON 文件（MVP）→ SQLite（v2） | 先简单跑通，再持久化 |
| 测试 | pytest | 103 个测试，覆盖核心路径 |

---

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/Vencent8265/ai-content-operator.git
cd ai-content-operator

# 2. 虚拟环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，至少填 DEEPSEEK_API_KEY 和 DASHSCOPE_API_KEY

# 4. 运行测试
PYTHONPATH=. pytest tests/ -v
# 103 passed ✅

# 5. 手动跑一次完整流程
PYTHONPATH=. python3 src/cron/daily_pipeline.py --step gen
```

---

## 项目结构

```
src/
├── agents/
│   ├── content_writer.py     # AI 文章生成（支持资讯聚合模式）
│   ├── review_notifier.py    # 审核推送（微信+飞书双平台）
│   └── daily_reviewer.py     # LLM 驱动日复盘分析
├── tools/
│   ├── news_fetcher.py       # HN/ArXiv/GitHub 三源资讯聚合
│   └── data_collector.py     # 数据回收（手动模式 + 自动解析）
├── models/
│   └── adapter.py            # 模型路由适配层（换模型=改配置）
├── contracts/
│   └── schemas.py            # Agent 通信 JSON Schema 契约
├── cron/
│   └── daily_pipeline.py     # 每日自动化管线
├── utils/
│   ├── compliance_filter.py  # 内容合规检查
│   ├── cover_generator.py    # AI 封面生成（通义万相）
│   └── publish_formatter.py  # 发布卡格式化
tests/                         # 103 个测试
data/                          # 运行时数据（不入库）
  ├── articles/                #   生成的文章
  ├── covers/                  #   AI 生成的封面
  └── reports/                 #   数据报告
```

---

## 版本路线

| 版本 | 状态 | 核心能力 |
|------|------|---------|
| **MVP v2** | ✅ 运行中 | 资讯聚合→AI成文→审核→发布→数据回收→复盘 |
| **v2** | 📋 计划 | 多Agent协同 + LangGraph编排 + 模型混合路由 + 异常预警 + 投流建议 |
| **v3** | 📋 计划 | A/B测试 + 投流自动化 + 效果预测 + 三级复盘 |
| **v4** | 📋 计划 | 多平台插件化 + Web管理后台 + Docker一键部署 |

---

## 关键指标

| 指标 | 当前状态 |
|------|---------|
| 测试覆盖 | 103 个测试 / 核心路径 100% |
| 模型调用成本 | ~¥0.02 / 篇文章 |
| 单次任务耗时 | ~20 秒（聚合 5s + 成文 10s + 封面 5s） |
| 支持的资讯源 | HN / ArXiv / GitHub Trending |

---

## License

MIT
