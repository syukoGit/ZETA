# ZETA — AI-Powered Autonomous Trading Agent

## Overview

**ZETA** (Zero-Touch Execution & Trading Algorithm) is a fully autonomous trading agent that uses a Large Language Model (LLM) to analyze markets, make investment decisions, and execute orders on US equities through **Interactive Brokers (IBKR)**. It operates in a continuous loop: at each iteration, the LLM receives a snapshot of the account state, consults its tools (market data, memory, web/X search), then decides whether to act or observe.

ZETA also runs a periodic **review** cycle that analyzes recent runs and injects strategic directives into future trading runs.

ZETA is not a simple assistant that suggests trades — it **executes them itself**, from opportunity scanning to order placement, including risk management and continuous learning.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                        Main Loop                        │
│                        (main.py)                        │
│                                                         │
│  1. IBKR Snapshot (positions, cash, open orders)        │
│  2. LLM run call with context + tools                  │
│  3. Tool call execution (IBKR, memory, history, etc.)  │
│  4. close_run returns summary + next wait               │
│  5. Dynamic market-aware wait → back to step 1         │
│  6. Periodic review cycle                  │
└─────────────────────────────────────────────────────────┘
         │                    │                  │
         ▼                    ▼                  ▼
   ┌──────────┐      ┌──────────────┐    ┌─────────────┐
   │   IBKR   │      │  LLM (Grok)  │    │ PostgreSQL  │
   │  (TWS)   │      │  + Web/X     │    │ + pgvector  │
   └──────────┘      └──────────────┘    └─────────────┘
```

### Main Components

| Module | Role |
| ------ | ---- |
| `script/main.py` | Main loop: initializes DB, connects to IBKR, runs trading loops plus periodic reviews |
| `script/llm/llm_call.py` | Orchestrates both run and review calls, including tool loop and structured close tools |
| `script/llm/llm_provider.py` | LLM provider abstraction (abstract `LLM` class + factory with dynamic loading) |
| `script/llm/providers/grok_provider.py` | Grok (xAI) provider implementation with streaming, tool calling, and built-in web/X search |
| `script/llm/start_prompt.py` | Complete system prompt defining ZETA's run behavior (trading rules, risk management, close requirements) |
| `script/llm/review_prompt.py` | Dedicated prompt for strategic portfolio/run review mode |
| `script/llm/tools/` | Auto-discovered tool registry that the LLM can call |
| `script/ibkr/ibTools.py` | Interactive Brokers connection singleton via `ib_async` |
| `script/db/` | Database layer (SQLAlchemy + pgvector): models, sessions, repositories |
| `script/config.py` | JSON configuration file loading with hot-reload |
| `script/utils/timing.py` | Market-calendar-aware wait time calculation between iterations |

---

## Tools Available to the LLM

ZETA exposes a set of tools that the LLM can call autonomously during each iteration. Tools are auto-discovered and registered via a decorator system (`@register_tool`).

### IBKR (Interactive Brokers) Tools

| Tool | Description |
| --- | --- |
| `get_positions` | Retrieves current portfolio positions |
| `get_cash_balance` | Retrieves account cash balances |
| `get_open_trades` | Lists open orders |
| `get_quote` | Gets a real-time quote for a symbol |
| `get_history` | Retrieves historical market data (OHLCV bars) with configurable granularity |
| `get_pnl` | Retrieves account P&L (Profit & Loss) |
| `get_trade_history` | History of executed trades |
| `get_volatility_metrics` | Volatility metrics for a symbol |
| `place_order` | Places an order (Market or Limit) on a stock |
| `preview_order` | Simulates an order to evaluate cost/impact before execution |
| `modify_order` | Modifies an existing order |
| `cancel_order` | Cancels an open order |

> `place_bracket_order` and `place_oco_order` files exist, but these tools are currently not registered in the active tool registry.

### Memory Tools (Vector Database)

| Tool | Description |
| --- | --- |
| `memory_create` | Creates a new memory entry (thesis, note, insight) |
| `memory_update` | Updates an existing memory entry |
| `memory_deprecate` | Deprecates an outdated or invalidated memory |
| `memory_get_by_id` | Retrieves a memory by its identifier |
| `search_memory` | Semantic search in the vector memory (cosine similarity) |

### Utility Tools

| Tool | Description |
| --- | --- |
| `get_date_hour_utc_and_markets` | Retrieves current UTC date/time and open/closed status of tracked US exchanges |
| `close_run` | Closes the current run with a structured summary and next wait time |
| `close_review` | Closes the review with structured strategic output |

### History Tools (review mode)

| Tool | Description |
| --- | --- |
| `get_runs_to_review` | Retrieves runs executed since the last review |
| `get_run_details` | Retrieves full details of a run (messages + tool calls) |

### Native Provider Tools (Grok/xAI)

| Tool | Description |
| --- | --- |
| `web_search` | Web search with image/video understanding |
| `x_search` | X (Twitter) search with image/video understanding |

---

## Vector Memory

ZETA has a **persistent memory** stored in PostgreSQL with the **pgvector** extension. This memory allows the agent to:

- **Store** investment theses, macro observations, notes on specific stocks, lessons learned
- **Search** by semantic similarity using embeddings (default model: `intfloat/e5-large-v2`, dimension 1024)
- **Maintain** its knowledge base by deprecating memories that are outdated or contradicted by new data
- **Learn** from its mistakes by creating post-mortems after losing trades or invalidated theses

Every memory access (read/write) is **traced** and linked to the LLM message that triggered it, ensuring full auditability.

---

## Database

### Data Models

| Table | Description |
| --- | --- |
| `runs` | Each LLM loop execution (provider, model, status, timestamps) |
| `messages` | Messages exchanged during a run (system, user, assistant, tool_result) |
| `tool_calls` | Tool calls made by the LLM (name, input/output payload, status) |
| `memory_entries` | Vector memory entries (title, content, type, tags, embedding, status) |
| `memory_access_log` | Log of all memory accesses (traceability) |

Run trigger types include:

- `llm_call`
- `review`

---

## LLM Decision Loop

At each run, ZETA follows a structured process:

1. **Read snapshot** — Positions, cash, open orders retrieved directly from IBKR
2. **Inject context** — System prompt + snapshot + previous iteration report
3. **Time check** — Confirm market status via `get_date_hour_utc_and_markets`
4. **Consult memory** — Semantic search if relevant to the current decision
5. **Opportunity analysis** — Broad scan (earnings, macro, sector rotation, M&A, catalysts) via web/X search
6. **Cost discipline** — Target budget of ~$10/day in API costs; if no clear edge, switch to observe mode
7. **Risk management** — Mandatory preview before any order, respect buying power, moderate sizing by default
8. **Learning** — Update vector memory after major events
9. **Structured close** — End run via `close_run` with summary + `time_before_next_run_s`

In parallel, a periodic review cycle analyzes recent runs and ends through `close_review`.

---

## Smart Scheduling

ZETA automatically adapts its cadence based on context:

| Context | Behavior |
| --- | --- |
| **Markets open** | Uses LLM-provided wait (`time_before_next_run_s`), clamped by `min_wait_seconds` and adjusted to not exceed market close |
| **Markets closed** | Waits until next exchange open, capped by `off_hours_wait_seconds` |
| **Minimum wait** | Configurable via `min_wait_seconds` |
| **Default wait fallback** | Configurable via `default_wait_seconds` |

---

## Configuration

### Runtime config (`config.json`)

`config.json` is a local runtime file and is not versioned.

- It is loaded from the current working directory (`Path.cwd()` at runtime).
- If missing at startup, ZETA auto-generates a default `config.json`.
- Changes are hot-reloaded automatically (no restart required).
- If the file exists but is invalid, ZETA fails fast with a clear error.
- On load/reload, ZETA logs the resolved path (`Runtime config loaded/reloaded from ...`).

The versioned schema is available in `config.schema.json`.

```json
{
  "debugPrint": false,
  "dry_run": true,
  "min_wait_seconds": 60,
  "default_wait_seconds": 600,
  "off_hours_wait_seconds": 3600,
  "llm": {
    "provider": "grok",
    "model": "grok-4-1-fast-reasoning"
  },
  "review": {
    "llm": {
      "provider": "grok",
      "model": "grok-4-1-fast-reasoning"
    },
    "every_n_trades": 5
  },
  "embedding_model": "sentence-transformers/nli-bert-large",
  "ibkr": {
    "host": "127.0.0.1",
    "port": 7497,
    "clientId": 0,
    "min_cash_reserve": 0,
    "cash_reserve_currency": "BASE",
    "excluded_cash_currencies": []
  }
}
```

| Key | Description |
| --- | --- |
| `debugPrint` | Enables DEBUG level logs (color-coded in console) |
| `dry_run` | If `true`, orders are not actually sent to IBKR (simulation mode) |
| `min_wait_seconds` | Minimum time between two iterations (in seconds) |
| `default_wait_seconds` | Default wait time if the LLM does not specify a value |
| `off_hours_wait_seconds` | Maximum wait while markets are closed |
| `llm.provider` | LLM provider to use (`grok`) |
| `llm.model` | Specific LLM model |
| `review.*` | Settings for periodic strategic review loop |
| `embedding_model` | Embedding model for vector memory |
| `ibkr.*` | IBKR settings (`host`, `port`, `clientId`, `min_cash_reserve`, `cash_reserve_currency`, `excluded_cash_currencies`) |

When `get_cash_balance` is called, ZETA first excludes currencies listed in `ibkr.excluded_cash_currencies`, then subtracts `ibkr.min_cash_reserve` from the `CashBalance` of `ibkr.cash_reserve_currency` only, and clamps the result to `0`.

### Environment Variables

All environment variables are defined in a `.env` file at the project root (loaded automatically by Docker Compose and the application).

| Variable | Description |
| --- | --- |
| `LLM_API_KEY` | LLM provider API key (xAI/Grok) |
| `DATABASE_URL` | PostgreSQL connection URL (e.g., `postgresql://user:password@localhost:5432/db_name`) |
| `POSTGRES_DB` | PostgreSQL database name (used by Docker Compose) |
| `POSTGRES_USER` | PostgreSQL user (used by Docker Compose) |
| `POSTGRES_PASSWORD` | PostgreSQL password (used by Docker Compose) |
| `POSTGRES_PORT` | PostgreSQL exposed port (used by Docker Compose, default: `5432`) |

---

## Prerequisites

- **Python 3.11+**
- **Docker** (for PostgreSQL + pgvector)
- **Interactive Brokers TWS** or **IB Gateway** running on `127.0.0.1:7497`
- An **xAI (Grok)** API key

---

## Installation & Getting Started

### 1. Configure environment variables

Create a `.env` file at the project root and fill in your values:

```env
# PostgreSQL (used by Docker Compose)
POSTGRES_DB=db_name
POSTGRES_USER=user
POSTGRES_PASSWORD=change_me
POSTGRES_PORT=5432

# Application
LLM_API_KEY=your_xai_api_key
DATABASE_URL=postgresql://user:change_me@localhost:5432/db_name
```

> **Important:** The `DATABASE_URL` credentials must match the `POSTGRES_*` values.

Optional IBKR runtime connection settings are defined in `config.json` under `ibkr`.

### 2. Start the database

```bash
docker-compose up -d
```

This launches a PostgreSQL 16 container with the pgvector extension. The `vector` extension is automatically enabled via the init script (`script/db/init/init.sql`).

> **Note:** The init script only runs on the first startup (when the volume is empty). If you need to reinitialize, run `docker compose down -v` then `docker compose up -d`.

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Launch IBKR TWS / IB Gateway

Make sure TWS or IB Gateway is running and configured to accept API connections on port `7497`.

### 5. Start ZETA

```bash
cd script
python main.py
```

With this command, runtime config is read/written in `script/config.json`.

If you run ZETA from the repository root (for example `python script/main.py`), runtime config is read/written in `config.json` at repository root.

ZETA will:

1. Connect to the database and create tables if needed
2. Connect to Interactive Brokers
3. Start the main LLM call loop

---

## Dry Run Mode

By enabling `"dry_run": true` in `config.json`, ZETA operates in simulation mode:

- The IBKR connection is established but **no real orders are placed**
- Orders return a `DRY_RUN` status with details of what would have been executed
- Useful for testing LLM behavior and validating strategies without financial risk

---

## Traceability & Audit

Every ZETA action is fully traced in the database:

- **Runs**: Each loop cycle is recorded with its provider, model, status, and duration
- **Messages**: All messages (system prompt, snapshot, LLM responses) are preserved with their sequential order
- **Tool Calls**: Every tool call is logged with its input payload, result, and status
- **Memory Access**: Every read/write to the vector memory is traced back to the originating LLM message

This complete traceability allows you to **replay** and **understand** every decision made by the agent.

---

## Run Analysis Export Tool

You can export the database into a single JSON file designed for both human review and AI analysis.

Script:

```bash
python test_tools/db_export_runs.py
```

Date-filtered export:

```bash
python test_tools/db_export_runs.py --from 2026-01-01 --to 2026-02-22
```

Custom output path:

```bash
python test_tools/db_export_runs.py --output test_tools/exports/my_runs_export.json
```

By default, the script creates `test_tools/exports/runs_export_<timestamp>.json` and includes:

- `metadata` (export time, filters, row counts)
- `tables_raw` (raw rows for runs, messages, tool calls, memory logs, memory entries)
- `runs_analysis` (denormalized run-centric view: run → ordered messages → tool calls + memory access events)

Notes:

- `--from` and `--to` accept `YYYY-MM-DD` or full ISO datetime (`2026-02-22T12:00:00Z`)
- When date filters are used, run-linked tables are filtered by `runs.started_at`
- `memory_entries` are exported in full to preserve complete memory context

---

## Tech Stack

| Component | Technology |
| --- | --- |
| Language | Python 3.11+ |
| LLM | Grok (xAI) via `xai_sdk` |
| Broker | Interactive Brokers via `ib_async` |
| Database | PostgreSQL 16 + pgvector |
| ORM | SQLAlchemy |
| Embeddings | `intfloat/e5-large-v2` (default) |
| Validation | Pydantic v2 |
| Logging | `colorlog` (level-based colored logs) |
| Configuration | JSON with hot-reload |
| Containerization | Docker Compose |

---

## Additional Utilities (`test_tools/`)

- `test_tools/test_connections.py` — quick DB/IBKR/LLM connectivity checks
- `test_tools/tool_runner.py` — run one tool manually for debugging
- `test_tools/run_viewer.py` — inspect run history from the database
- `test_tools/memory_manager.py` — inspect/manage memory entries
- `test_tools/chat_grok.py` — ad-hoc Grok chat testing
- `test_tools/db_export_runs.py` — export DB runs/messages/tools/memory events to JSON

---

## Disclaimer

⚠️ **ZETA is an experimental project (POC).** Using an autonomous agent for trading carries significant financial risks. This software is provided as-is, with no warranty. Use `dry_run` mode to test before any use with real money. The author disclaims all liability for financial losses resulting from the use of this software.
