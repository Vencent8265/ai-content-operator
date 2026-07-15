# AI Content Operator

> 基于多 Agent 协同的 AI 知识内容运营系统  
> 覆盖：内容生成 → 审核 → 多平台发布 → 数据回收 → 投流决策 → 复盘迭代 全闭环

## 架构

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  内容生成    │ →  │  审核推送    │ →  │  发布执行    │ →  │  数据回收    │
│  Agent      │    │  (微信通知)   │    │  Agent      │    │  Agent      │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                               │
                                                               ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  管理后台    │ ←  │  投流决策    │ ←  │  复盘总结    │ ←  │  数据看板    │
│  (Web)      │    │  Agent      │    │  Agent      │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

## 版本路线

| 版本 | 状态 | 核心能力 |
|------|------|---------|
| MVP | 🚧 开发中 | 单平台，审核→发布→复盘 |
| v2 | 📋 计划中 | 多Agent协同，模型混合路由 |
| v3 | 📋 计划中 | 数据驱动增长，A/B测试 |
| v4 | 📋 计划中 | 多平台矩阵，管理后台 |

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/Vencent8265/ai-content-operator.git
cd ai-content-operator

# 2. 安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 配置
cp .env.example .env
# 编辑 .env 填入 API Key

# 4. 运行测试
pytest tests/ -v
```

## 项目结构

```
src/
├── agents/          # Agent 实现（每个Agent一个文件）
├── tools/           # 平台发布工具、数据抓取
│   └── platforms/   # 各平台适配器插件
├── workflows/       # LangGraph workflow 定义
├── models/          # 模型适配层（统一接口）
├── contracts/       # Agent 间 JSON Schema 契约
├── cron/            # 定时任务脚本
└── utils/           # 公共工具
```

## 技术栈

- **Agent 框架**: LangGraph + Hermes Agent
- **模型接入**: DeepSeek, 通义千问（可替换）
- **数据存储**: SQLite（MVP）→ PostgreSQL（生产）
- **管理后台**: FastAPI + Streamlit（计划）
- **定时任务**: Hermes Cron

## License

MIT
