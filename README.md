# WorldCup Agent

2026 世界杯 **AI 球队对比 Agent** 后端：FastAPI 提供赛况 API、Chroma RAG 检索、百炼通义 LLM 流式报告，配合 React 前端（独立仓库）实现赛况看板 + 智能问答。

## 功能概览

| 模块 | 说明 |
|------|------|
| **赛况 API** | 今日赛程、积分榜、球队列表、赛事概览（北京时间） |
| **AI 对比** | Stats 历史数据 + RAG 球队文档 + LLM 生成对比报告 |
| **SSE 流式** | `/agent/stream` 先返回 stats/rag，再逐 token 输出报告 |
| **数据管道** | openfootball JSON → `tournament.db`、积分榜计算、JSON 快照 |
| **赔率（P2）** | mock / The Odds API，写入 `odds_snapshots` 并展示在赛程卡片 |

## 技术栈

- **Python 3.11+** · FastAPI · Pydantic Settings · structlog
- **SQLite** · `worldcup.db`（历史战绩）· `tournament.db`（赛况快照）
- **Chroma** · 球队文档向量检索（DashScope Embedding）
- **百炼通义** · OpenAI 兼容接口（`qwen-plus` 等）

## 快速开始

### 1. 环境

```bash
cd agentExample
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install chromadb openai   # 生产 RAG/LLM 需要
```

### 2. 配置

```bash
cp .env.example .env
```

开发 / 测试默认使用 `mock` 后端，无需 API Key：

```env
RAG_BACKEND=mock
LLM_BACKEND=mock
```

生产环境示例：

```env
RAG_BACKEND=chroma
LLM_BACKEND=qwen
DASHSCOPE_API_KEY=sk-...
REQUEST_TIMEOUT=30
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### 3. 数据管道（首次或更新赛况）

```bash
# 完整管道：ETL → 积分榜 → tournament.db → stats 冒烟
python scripts/pipeline.py

# 仅轻量同步赛况（适合 cron）
python scripts/sync_tournament.py

# 写入 mock 赔率
python scripts/fetch_odds.py --mock-only
# 或
python scripts/pipeline.py --fetch-odds --odds-mock
```

启用真实 RAG + LLM 后，还需重建向量：

```bash
python scripts/ingest_embeddings.py --force
```

### 4. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- 健康检查：<http://127.0.0.1:8000/health>
- OpenAPI 文档：<http://127.0.0.1:8000/docs>

### 5. 前端（可选）

前端位于同级目录 `agent-footerball-web`（Vite + React），开发时将 `/api`、`/agent` 代理到 `127.0.0.1:8000`：

```bash
cd ../agent-footerball-web
npm install
npm run dev
```

## API 一览

### 赛况

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/overview` | 赛事概览（含今日赛程 + 积分榜） |
| GET | `/api/matches/today?date=YYYY-MM-DD` | 指定日期赛程（默认北京时间「今日」） |
| GET | `/api/standings` | 小组积分榜 |
| GET | `/api/teams` | 球队列表（`?status=active` 等） |
| GET | `/api/tournament/current` | 当前赛事元信息 |
| GET | `/api/pipeline/status` | 数据管道 / 赔率同步状态 |
| GET | `/api/odds` | 赔率快照（`?match_id=` 可选） |

### Agent

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agent` | 同步对比报告 |
| POST | `/agent/stream` | SSE 流式：stats → rag → token |

请求体示例：

```json
{
  "team_a": "巴西",
  "team_b": "法国",
  "query": "谁的中场控制力更强？"
}
```

SSE 事件类型：`stats` · `rag` · `token` · `done`

## 项目结构

```
agentExample/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 环境变量
│   ├── orchestrator.py      # Agent 编排
│   ├── api/tournament.py    # 赛况 REST API
│   ├── services/            # 赛况快照、赛程逻辑
│   ├── tools/               # stats / RAG / odds / DB
│   └── llm/                 # 百炼通义客户端
├── scripts/
│   ├── pipeline.py          # 一键数据管道
│   ├── etl_worldcup.py      # openfootball → SQLite
│   ├── compute_standings.py # 积分榜计算
│   ├── sync_tournament.py   # 轻量赛况同步
│   ├── fetch_odds.py        # 赔率抓取
│   └── ingest_embeddings.py # Chroma 向量入库
├── data/                    # 赛事 JSON、teams.csv（部分生成文件已 gitignore）
├── docs/teams/              # RAG 球队 Markdown
├── skills/                  # Agent Skill 提示词
└── tests/
```

## 常用脚本

| 脚本 | 用途 |
|------|------|
| `scripts/pipeline.py` | ETL + 赛况 DB + 可选 docs/embeddings/odds |
| `scripts/sync_tournament.py` | cron 定时同步赛程与积分榜 |
| `scripts/fetch_odds.py` | 抓取赔率写入 `tournament.db` |
| `scripts/ingest_embeddings.py` | 重建 Chroma 向量（需 DashScope Key） |
| `scripts/inspect_chroma.py` | 调试向量库内容 |

## 测试

```bash
pytest tests/ -q
# 跳过较慢的 orchestrator 集成测试
pytest tests/ -q --ignore=tests/test_orchestrator.py
```

## 配置说明

完整变量见 [`.env.example`](.env.example)。重点项：

| 变量 | 默认 | 说明 |
|------|------|------|
| `RAG_BACKEND` | `mock` | `mock` \| `chroma` |
| `LLM_BACKEND` | `mock` | `mock` \| `qwen` |
| `ODDS_BACKEND` | `mock` | `mock` \| `the_odds_api` |
| `DASHSCOPE_API_KEY` | — | 百炼通义 Key |
| `ODDS_API_KEY` | — | The Odds API Key |
| `TOURNAMENT_YEAR` | `2026` | 赛事年份 |
| `CORS_ORIGINS` | localhost:5173 | 前端跨域 |

## 路线图

| 阶段 | 内容 | 状态 |
|------|------|------|
| **P0** | React 前端 + 赛况 API + SSE 问答 | ✅ |
| **P1** | ETL、`tournament.db`、pipeline、积分榜 | ✅ |
| **P2** | 赔率抓取与赛程展示 | ✅ |
| **P3** | 球队搜索、淘汰赛对阵图、移动端优化 | 待做 |
| **P4** | Docker、nginx、部署文档 | 待做 |

## 数据来源

- 赛程 / 比分： [openfootball/worldcup](https://github.com/openfootball/worldcup) 静态 JSON（`data/2026/worldcup.json`）
- 历史战绩：`data/matches.csv` + ETL 生成的 `worldcup.db`
- 球队文档：`docs/teams/*.md`（可由 `build_team_docs.py` 生成）
- 赔率：mock 或 [The Odds API](https://the-odds-api.com/)

## 免责声明

本项目中的 AI 分析与赔率数据仅供学习与参考，**不构成任何投注建议**。

## License

MIT（如仓库未指定，请自行补充 LICENSE 文件）
