# Code Review Agent

> AI-powered automated code review tool. Integrates with GitLab / GitHub webhooks, supports multiple LLM providers, and delivers review results via instant messaging (DingTalk, WeCom, Feishu bot, or custom webhook) with optional Feishu private DM relay.

> **⚠️ Fork notice:** This project is a fork of [AI-Codereview-Gitlab](https://github.com/sunmh207/AI-Codereview-Gitlab) (Apache-2.0) by [sunmh207](https://github.com/sunmh207). We've since added GitHub webhook support, a structured review engine with line-number resolution, async worker queue, SQLite persistence, event-driven notifications, configurable prompt routing, diff-aware context windows, and more. See the [Acknowledgments](#acknowledgments) section for details.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![CI](https://github.com/phoenine/code-reviewer/actions/workflows/build.yml/badge.svg)](https://github.com/phoenine/code-reviewer/actions/workflows/build.yml)

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick Start (Docker)](#quick-start-docker)
- [Manual Setup](#manual-setup)
- [Configuration](#configuration)
- [Webhook Setup](#webhook-setup)
  - [GitLab](#gitlab)
  - [GitHub](#github)
- [Notification Channels](#notification-channels)
- [Review Engine](#review-engine)
  - [Prompt Routing](#prompt-routing)
  - [Review Styles](#review-styles)
  - [Context Window](#context-window)
  - [Token Budget Management](#token-budget-management)
- [Dashboard](#dashboard)
- [Feishu Relay (Optional)](#feishu-relay-optional)
- [Development](#development)
- [License](#license)
- [Acknowledgments](#acknowledgments)

---

## Features

- **Multi-LLM Support** — DeepSeek, OpenAI, Anthropic Claude, Qwen, ZhipuAI, Ollama (bring your own key)
- **Platform Integration** — GitLab & GitHub webhook (Merge Request / Pull Request / Push)
- **Structured Review Engine** — LLM outputs structured JSON with score, risk level, merge advice, and per-comment line references
- **Line Number Resolution** — Comments are automatically mapped to diff line numbers for precise code references
- **Context Window** — Fetches surrounding code from the repository for smarter review (configurable depth)
- **Token Budget Management** — Diff-first, context-second token allocation ensures review fits within model limits
- **Per-Project Prompt Routing** — Domain-specific review rules via YAML configuration
- **Instant Notifications** — Results delivered to DingTalk, WeCom, Feishu bot, or custom webhook
- **Feishu Private DM Relay** — Optional companion service for delivering review results as Feishu private messages
- **Async Processing** — ThreadPoolExecutor-based worker queue prevents webhook timeouts
- **Review History** — SQLite-backed persistence with dedup, queried via dashboard API
- **Rich Dashboard** — React + Vite frontend with review history, project statistics, developer analytics
- **Review Styles** — Professional, Concise, Strict, Sarcastic, Gentle, Humorous (Jinja2-templated prompts)
- **Docker Ready** — One-command deployment via docker compose

---

## Architecture

```
┌──────────────┐     Webhook      ┌─────────────────────────────────────┐
│  GitLab /     │ ──────────────► │  code-reviewer (Flask + React + TS)  │
│  GitHub       │                 │  :5001 → Docker :25001              │
│               │                 │                                     │
│               │ ◄────────────── │  Review notes posted via API        │
│               │                 └──────────┬──────────────────────────┘
│               │                            │
└──────────────┘                            │ EXTRA_WEBHOOK (optional)
                                            ▼
                                     ┌──────────────┐
                                     │ feishu-relay  │
                                     │ (FastAPI)     │
                                     │ :8090         │
                                     └──────┬───────┘
                                            │
                                            ▼
                                     ┌──────────────┐
                                     │   Feishu IM   │
                                     │  (private DM) │
                                     └──────────────┘
```

**Internal review pipeline (async):**

```
Webhook → Flask route → ThreadPool queue → Worker thread
  ├─ Parse diff (hunk-level parsing)
  ├─ Filter by extension, skip binary/deleted
  ├─ Build context window (fetch surrounding code from repo)
  ├─ Select prompt (per-project routing)
  ├─ Call LLM with token-budgeted input
  ├─ Parse structured JSON result
  ├─ Resolve line numbers (map comments to diff lines)
  ├─ Post comment back to MR/PR/commit
  ├─ Fire event → save to SQLite + send IM notification
  └─ (Optional) Extra webhook → feishu-relay → private DM
```

---

## Quick Start (Docker)

**Prerequisites:** Docker & Docker Compose

```bash
# 1. Clone
git clone https://github.com/phoenine/code-reviewer.git
cd code-reviewer

# 2. Configure environment
cp conf/.env.dist conf/.env
# Edit conf/.env — set LLM_PROVIDER, API keys, GITLAB_ACCESS_TOKEN, etc.

# (Optional) feishu-relay
cp feishu-relay/.env.example feishu-relay/.env
cp feishu-relay/config/git_user_to_name.json.example feishu-relay/config/git_user_to_name.json
cp feishu-relay/config/feishu_open_ids.json.example feishu-relay/config/feishu_open_ids.json

# 3. Start both services
docker compose -f deployment/docker-compose.yml up -d --build
```

**Verify:**
- API: `http://<your-server-ip>:25001/health` — returns `{"status": "ok"}`
- Dashboard: `http://<your-server-ip>:25001`
- Feishu Relay health: `http://<your-server-ip>:8090/health`

---

## Manual Setup

**Prerequisites:** Python 3.10+, Node.js 18+

```bash
# 1. Clone
git clone https://github.com/phoenine/code-reviewer.git
cd code-reviewer

# 2. Python backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp conf/.env.dist conf/.env
# Edit conf/.env with your API keys

# 4. Start API
python api.py                        # Flask on :5001

# 5. (Another terminal) Frontend dev
cd frontend
npm install
npm run dev                          # Vite dev server on :5173
```

The Vite dev server proxies `/api/*` to `http://127.0.0.1:5001`.

For production frontend build:
```bash
cd frontend
npm run build                        # Outputs to frontend/dist/
# Flask serves the built files at /
```

---

## Configuration

All configuration lives in `conf/.env`. Copy from the template:

```bash
cp conf/.env.dist conf/.env
```

### LLM Provider

| Variable | Description | Example |
|----------|-------------|---------|
| `LLM_PROVIDER` | LLM backend | `deepseek`, `openai`, `anthropic`, `qwen`, `zhipuai`, `ollama` |
| `DEEPSEEK_API_KEY` | DeepSeek API key | `sk-...` |
| `DEEPSEEK_API_BASE_URL` | DeepSeek API endpoint | `https://api.deepseek.com` |
| `DEEPSEEK_API_MODEL` | DeepSeek model | `deepseek-chat` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |
| `OPENAI_API_MODEL` | OpenAI model | `gpt-4o-mini` |
| `ANTHROPIC_API_KEY` | Anthropic API key | `sk-...` |
| `ANTHROPIC_API_MODEL` | Anthropic model | `claude-sonnet-4-5-20250929` |
| `ANTHROPIC_MAX_TOKENS` | Anthropic max output tokens | `4096` |
| `QWEN_API_KEY` | Qwen API key | `sk-...` |
| `QWEN_API_MODEL` | Qwen model | `qwen-coder-plus` |
| `ZHIPUAI_API_KEY` | ZhipuAI API key | `...` |
| `ZHIPUAI_API_MODEL` | ZhipuAI model | `GLM-4-Flash` |
| `OLLAMA_API_BASE_URL` | Ollama endpoint | `http://host.docker.internal:11434` |
| `OLLAMA_API_MODEL` | Ollama model | `deepseek-r1:latest` |

### Platform Access

| Variable | Description | Example |
|----------|-------------|---------|
| `GITLAB_URL` | GitLab instance URL (optional — auto-detected from webhook) | `https://gitlab.example.com` |
| `GITLAB_ACCESS_TOKEN` | GitLab personal/project access token | `glpat-...` |
| `GITLAB_WEBHOOK_SECRET` | Optional: verify X-Gitlab-Token header | — |
| `GITHUB_ACCESS_TOKEN` | GitHub personal access token | `github_pat_...` |
| `GITHUB_WEBHOOK_SECRET` | Optional: verify X-Hub-Signature-256 header | — |

### Review Options

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPPORTED_EXTENSIONS` | `.java,.py,.ts,.tsx,.js,.html,.scss,.sql,.yaml,.yml,.sh,.go,.json` | File extensions to review |
| `REVIEW_STYLE` | `professional` | Review personality: `professional`, `concise`, `strict`, `sarcastic`, `gentle`, `humorous` |
| `REVIEW_MAX_TOKENS` | `10000` | Max tokens per review (diff + context) |
| `PUSH_REVIEW_ENABLED` | `1` | Enable review on push events |
| `MERGE_REVIEW_ONLY_PROTECTED_BRANCHES_ENABLED` | `0` | Only review MRs targeting protected branches |
| `HTTP_TIMEOUT_SECONDS` | `10` | HTTP request timeout |

### Context Window

| Variable | Default | Description |
|----------|---------|-------------|
| `REVIEW_CONTEXT_ENABLED` | `1` | Enable fetching surrounding code from repo |
| `REVIEW_CONTEXT_LINES` | `40` | Lines of context around each hunk |
| `REVIEW_CONTEXT_MAX_FILES` | `20` | Max files to fetch context for |
| `REVIEW_CONTEXT_MAX_CHARS_PER_FILE` | `12000` | Max chars per file context |
| `REVIEW_CONTEXT_MAX_TOTAL_CHARS` | `50000` | Max total context chars across all files |
| `REVIEW_CONTEXT_TOKEN_RATIO` | `0.30` | Proportion of token budget reserved for context |
| `REVIEW_DIFF_TOKEN_RATIO` | `0.65` | Proportion of token budget reserved for diff |
| `REVIEW_PROMPT_RESERVED_TOKENS` | `1000` | Tokens reserved for system prompt and overhead |

### Async Worker

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKER_MAX_WORKERS` | `4` | Thread pool size for webhook processing |
| `WORKER_MAX_QUEUE_SIZE` | `64` | Max queued webhook requests (returns 503 when full) |

### Dashboard

| Variable | Default | Description |
|----------|---------|-------------|
| `DASHBOARD_USER` | `admin` | Dashboard basic auth username |
| `DASHBOARD_PASSWORD` | `your-dashboard-password` | Dashboard basic auth password |

### Notification Channels

| Variable | Default | Description |
|----------|---------|-------------|
| `DINGTALK_ENABLED` | `0` | Enable DingTalk notifications |
| `DINGTALK_WEBHOOK_URL` | — | DingTalk robot webhook URL |
| `DINGTALK_SECRET_ENABLED` | `0` | Enable HMAC signing for DingTalk |
| `DINGTALK_SECRET` | — | DingTalk HMAC secret |
| `WECOM_ENABLED` | `0` | Enable WeCom notifications |
| `WECOM_WEBHOOK_URL` | — | WeCom robot webhook URL |
| `FEISHU_ENABLED` | `0` | Enable Feishu bot notifications |
| `FEISHU_WEBHOOK_URL` | — | Feishu bot webhook URL |
| `EXTRA_WEBHOOK_ENABLED` | `0` | Enable custom webhook (e.g. feishu-relay) |
| `EXTRA_WEBHOOK_URL` | — | Custom webhook URL |

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_PORT` | `5001` | Flask server port (Docker maps to :25001) |
| `TZ` | `Asia/Shanghai` | Timezone |
| `LOG_FILE` | `log/app.log` | Log file path |
| `LOG_LEVEL` | `DEBUG` | Log level |

---

## Webhook Setup

### GitLab

1. **Create an access token** — In GitLab: Settings → Access Tokens → create a token with `api` scope. Set it as `GITLAB_ACCESS_TOKEN` in `.env`.

2. **Configure the webhook** — In your GitLab project: Settings → Webhooks:

   | Field | Value |
   |-------|-------|
   | URL | `http://your-server-ip:25001/review/webhook` |
   | Secret Token | (optional) — set as `GITLAB_WEBHOOK_SECRET` in `.env` |
   | Trigger | **Push events** & **Merge request events** only |

### GitHub

1. **Create a personal access token** — GitHub: Settings → Developer settings → Personal access tokens → `Fine-grained tokens` with `Contents: read` and `Pull requests: read & write`. Set as `GITHUB_ACCESS_TOKEN` in `.env`.

2. **Configure the webhook** — In your GitHub repository: Settings → Webhooks → Add webhook:

   | Field | Value |
   |-------|-------|
   | Payload URL | `http://your-server-ip:25001/review/webhook` |
   | Content type | `application/json` |
   | Secret | (optional) — set as `GITHUB_WEBHOOK_SECRET` in `.env` |
   | Events | **Pull requests** & **Pushes** |

> **Note:** Only `push`, `pull_request` (GitHub) / `merge_request` (GitLab) events are supported.

---

## Notification Channels

Configure in `conf/.env`:

| Channel | Enable | Required Config |
|---------|--------|-----------------|
| **DingTalk** | `DINGTALK_ENABLED=1` | `DINGTALK_WEBHOOK_URL` |
| **WeCom** | `WECOM_ENABLED=1` | `WECOM_WEBHOOK_URL` |
| **Feishu Bot** | `FEISHU_ENABLED=1` | `FEISHU_WEBHOOK_URL` |
| **Custom Webhook** | `EXTRA_WEBHOOK_ENABLED=1` | `EXTRA_WEBHOOK_URL` |

When using Docker, the internal `feishu-relay` service is available at `http://feishu-relay:8090/notify`.

---

## Review Engine

### Prompt Routing

The review engine selects prompts based on the GitLab/GitHub project. Configuration lives in `conf/prompt_templates.yml`:

```yaml
prompt_routing:
  default: code_review_prompt_generic
  groups:
    your-org/your-repo: code_review_prompt_product_default
  projects:
    code-reviewer: code_review_prompt_generic
```

Routing hierarchy: **project match** → **group match** → **default**. The engine normalizes URLs, paths, and names to find the best match.

The template file uses Jinja2 for rendering. The `{{ style }}` variable is injected automatically based on the `REVIEW_STYLE` setting.

### Review Styles

| Style | Description |
|-------|-------------|
| `professional` 🎩 | Formal, thorough, detail-oriented |
| `concise` 📝 | Brief but impactful — gets straight to the point |
| `strict` ⚠️ | High standards, no leniency |
| `sarcastic` 😈 | Sharp and brutally honest |
| `gentle` 🌸 | Soft suggestions, encouraging tone |
| `humorous` 🤪 | Funny comments that make fixing bugs less painful |

Styles are implemented as Jinja2 template variables rendered through `conf/prompt_templates.yml`. The base system prompt contains style-aware sections.

### Context Window

When enabled (default), the review engine fetches surrounding code from the GitLab/GitHub repository around each diff hunk. This provides the LLM with:

- Function/method signatures surrounding the change
- Import statements and dependencies
- Related code patterns for consistency checking

The context window is smartly merged: overlapping ranges are combined, and token budgets prevent context from crowding out the actual diff.

### Token Budget Management

The engine allocates tokens in three tiers:

1. **Diff** (default 65%) — the primary review content
2. **Context** (default 30%) — surrounding code from the repository
3. **Reserved** (default 1000 tokens) — system prompt and overhead

Unused diff budget rolls over to context. If the diff already exceeds budget, context is omitted entirely. This ensures the LLM always sees the diff, even for large changes.

### Structured Output

The LLM is prompted to return a strict JSON structure:

```json
{
  "summary": "Overall review conclusion",
  "score": 85,
  "risk_level": "high|medium|low",
  "merge_advice": "建议合并|修复后合并|不建议合并",
  "comments": [
    {
      "path": "src/app.py",
      "severity": "high|medium|low|info",
      "category": "correctness|compatibility|security|performance|maintainability|test",
      "content": "Issue description and suggestion",
      "existing_code": "1-5 line code snippet from diff"
    }
  ]
}
```

After parsing, the engine attempts to resolve each comment to specific line numbers in the diff by matching the `existing_code` snippet against hunk content. Comments are then rendered as formatted Markdown and posted back to the MR/PR.

---

## Dashboard

The dashboard is a React + Vite single-page application served by Flask. It supports:

- **Overview** — Summary cards (total reviews, average score, projects, developers)
- **Review History** — Filterable list of MR and Push reviews with time range
- **Developer Analytics** — Per-developer statistics and score trends
- **Project Statistics** — Per-project review volume and quality trends

API endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /api/dashboard/summary` | Dashboard overview |
| `GET /api/dashboard/reviews` | Review list (MR + Push), supports `author`, `project_name`, `start`, `end` filters |
| `GET /api/dashboard/members` | Developer statistics |
| `GET /api/dashboard/filter-options` | Available authors and project names for filters |

Dashboard is protected by HTTP basic auth using `DASHBOARD_USER` and `DASHBOARD_PASSWORD` from `.env`.

---

## Feishu Relay (Optional)

**feishu-relay** is a companion service that forwards review notifications to individual Feishu users via private messages.

It maps Git usernames → Chinese names → Feishu Open IDs, then sends the review result as a Feishu interactive card directly to the committer's DM.

### Configuration

```bash
cp feishu-relay/.env.example feishu-relay/.env
# Edit FEISHU_APP_ID, FEISHU_APP_SECRET

cp feishu-relay/config/git_user_to_name.json.example feishu-relay/config/git_user_to_name.json
cp feishu-relay/config/feishu_open_ids.json.example feishu-relay/config/feishu_open_ids.json
# Edit the JSON mapping files with your team's info
```

Then in `conf/.env` of the main code-reviewer, point the extra webhook to the relay:

```
EXTRA_WEBHOOK_ENABLED=1
EXTRA_WEBHOOK_URL=http://feishu-relay:8090/notify
```

In Docker, this is pre-configured via the compose environment variable.

---

## Development

### Backend

```bash
source .venv/bin/activate
python api.py        # Flask on :5001 (with startup config check & DB init)
```

The entry point (`api.py`) performs a startup configuration check (validates env vars, tests LLM connectivity) and initializes the SQLite database before starting the server.

### Frontend

```bash
cd frontend
npm install
npm run dev          # Vite on :5173, proxies /api/* to :5001
npm run build        # Production build → frontend/dist/
```

### Project Structure

```
code-reviewer/
├── api.py                         # Flask entry point (config check + DB init + server)
├── biz/                           # Core business logic
│   ├── api/                       # Flask routes & app factory
│   │   └── routes/                # Route blueprints
│   │       ├── home.py            # Health check & SPA fallback
│   │       ├── dashboard.py       # Dashboard REST API
│   │       └── webhook.py         # Webhook receiver (GitLab + GitHub)
│   ├── context/                   # Review context window
│   │   └── window.py              # Surrounding-code extraction from repo
│   ├── diff/                      # Diff processing pipeline
│   │   ├── parser.py              # GitLab/GitHub diff → Diff model
│   │   ├── filter.py              # Extension/binary/deleted filtering
│   │   ├── hunk.py                # Hunk-level diff line parsing
│   │   └── resolver.py            # Line number resolution for comments
│   ├── entity/                    # Data entities for persistence
│   │   └── review_entity.py       # MRReviewEntity, PushReviewEntity
│   ├── event/                     # Event-driven notification system
│   │   └── event_manager.py       # blinker signals + IM/SQLite handlers
│   ├── llm/                       # LLM provider abstraction
│   │   ├── factory.py             # Provider factory
│   │   ├── types.py               # LLM types
│   │   └── client/                # Provider implementations
│   │       ├── base.py            # Abstract base client
│   │       ├── deepseek.py        # DeepSeek
│   │       ├── openai.py          # OpenAI
│   │       ├── anthropic.py       # Anthropic Claude
│   │       ├── qwen.py            # Qwen
│   │       ├── zhipuai.py         # ZhipuAI
│   │       └── ollama_client.py   # Ollama
│   ├── model/                     # Domain models (dataclasses)
│   │   ├── diff.py                # Diff model
│   │   ├── review_context.py      # ContextBlock, FileContext, ReviewContext
│   │   └── review_comment.py      # ReviewComment, ReviewResult
│   ├── platforms/                 # Platform webhook handlers
│   │   ├── gitlab/                # GitLab MR/Push handlers
│   │   └── github/                # GitHub PR/Push handlers
│   ├── queue/                     # Async worker queue
│   │   └── worker.py              # ThreadPoolExecutor-based async processing
│   ├── service/                   # Business services
│   │   └── review_service.py      # SQLite persistence with retry & dedup
│   └── utils/                     # Utilities
│       ├── code_reviewer.py       # Core review engine (prompt, LLM call, budget)
│       ├── code_parser.py         # Code parsing helpers
│       ├── config_checker.py      # Startup configuration validator
│       ├── dir_util.py            # Directory utilities
│       ├── im/                    # IM notification clients
│       │   ├── notifier.py        # Unified notification dispatcher
│       │   ├── dingtalk.py        # DingTalk
│       │   ├── wecom.py           # WeCom
│       │   ├── feishu.py          # Feishu bot
│       │   └── webhook.py         # Custom webhook
│       ├── log.py                 # Logging setup
│       ├── queue.py               # Queue mechanism (semaphore + executor)
│       ├── review_renderer.py     # Review result → Markdown renderer
│       ├── review_result_parser.py # LLM JSON output parser
│       └── token_util.py          # Token counting/truncation (tiktoken)
├── conf/                          # Configuration
│   ├── .env.dist                  # Environment template
│   └── prompt_templates.yml       # Jinja2 prompt templates + routing
├── deployment/                    # Docker & CI
│   ├── docker-compose.yml         # Both services
│   └── Dockerfile                 # code-reviewer image
├── feishu-relay/                  # Optional Feishu DM relay
│   ├── Dockerfile
│   ├── .env.example
│   ├── app/main.py                # FastAPI app
│   └── config/                    # User mapping files
├── frontend/                      # React + Vite dashboard
│   ├── src/
│   │   ├── App.tsx                # Main dashboard component
│   │   ├── main.tsx               # Entry point
│   │   ├── api/                   # API client modules
│   │   ├── components/            # UI components
│   │   └── types/                 # TypeScript type definitions
│   ├── index.html
│   ├── package.json
│   └── tsconfig.json
├── tests/                         # Pytest test suite
│   ├── test_code_reviewer.py
│   ├── test_dashboard_api.py
│   ├── test_diff_parser_filter.py
│   ├── test_platform_file_content.py
│   ├── test_review_context.py
│   ├── test_review_result_and_resolver.py
│   └── test_worker_push.py
└── requirements.txt
```

---

## License

This project is licensed under the Apache License 2.0 — see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- Based on [AI-Codereview-Gitlab](https://github.com/sunmh207/AI-Codereview-Gitlab) by sunmh207 (Apache-2.0)
- Built with [Flask](https://flask.palletsprojects.com/), [FastAPI](https://fastapi.tiangolo.com/), [React](https://react.dev/), [Vite](https://vitejs.dev/)
- Prompt rendering: [Jinja2](https://jinja.palletsprojects.com/)
- Event system: [blinker](https://github.com/jek/blinker)
- UI components from [Highcharts](https://www.highcharts.com/) & [DevExtreme](https://js.devexpress.com/)
