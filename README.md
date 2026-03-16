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
│  1. Phase resolution (market status + volatility)       │
│  2. IBKR Snapshot (positions, cash, open orders,        │
│     index quotes from config)                           │
│  3. LLM run call with phase prompt + context + tools   │
│  4. Tool call execution (IBKR, memory, history, etc.)  │
│  5. close_run returns summary + next wait               │
│  6. Wait clamped to phase [min, max] interval          │
│  7. Periodic review (runs_before_review threshold)     │
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
| `script/llm/llm_call.py` | Orchestrates both run and review calls, including parallel tool execution and structured close tools |
| `script/llm/context_builder.py` | Builds the dynamic context user message by resolving `{{variable}}` placeholders concurrently from live data sources |
| `script/llm/prompt.py` | Loads prompt files from the `prompts/` directory via `get_prompt()`; renders `{{variable}}` templates via `render_template()` |
| `script/llm/llm_provider.py` | LLM provider abstraction (abstract `LLM` class + factory with dynamic loading) |
| `script/llm/providers/grok_provider.py` | Grok (xAI) provider implementation with streaming, tool calling, and built-in web/X search |
| `script/llm/tools/` | Auto-discovered tool registry that the LLM can call |
| `script/ibkr/ibTools.py` | Interactive Brokers connection singleton via `ib_async` |
| `script/db/` | Database layer (SQLAlchemy + pgvector): models, sessions, repositories |
| `script/config.py` | YAML configuration loading with hot-reload (via `watchdog`); defines all config models including phase structure |
| `script/phase_resolver.py` | Resolves the active execution phase based on time, market status and volatility triggers |
| `script/utils/timing.py` | Market-calendar-aware wait time calculation between iterations |

### Local prompts (not versioned)

Create these local prompt files (all are git-ignored):

**Phase prompts** — file names match the `prompt_file` key configured per phase in `config.yaml`.

**Shared context templates:**

- `prompts/context.txt` — user message template rendered at the start of every trading run. Supports `{{variable}}` placeholders (see [Context Builder](#context-builder) below).
- `prompts/review_context.txt` — user message template rendered at the start of every review run. Also supports `{{variable}}` placeholders.

**Review prompt:**

- `prompts/review_prompt.txt`

At runtime, `script/llm/prompt.py` loads the appropriate file via `get_prompt()` based on the resolved phase, and renders `{{variable}}` placeholders via `render_template()`.

---

## Context Builder

`script/llm/context_builder.py` implements a **template-based context injection** system. At the start of each run (trading and review), a prompt template file is loaded and all `{{variable}}` placeholders are resolved concurrently before the message is sent to the LLM.

### How it works

1. The template is parsed for `{{variable}}` placeholders.
2. All required fetchers are launched concurrently via `asyncio.gather`.
3. Results are substituted into the template via `render_template()`.
4. A single user message containing all live data is added to the conversation.

Fetcher failures produce `"N/A"` for that variable and are logged as errors without aborting the run.

### Available template variables

| Variable | Description |
| --- | --- |
| `{{current_phase}}` | Active execution phase name |
| `{{phase.min}}` / `{{phase.max}}` | Run interval bounds (seconds) for the current phase |
| `{{current_datetime}}` | Current UTC date and time |
| `{{market_status}}` | Open/closed status of tracked exchanges |
| `{{next_market_close}}` | Soonest market close time (UTC) |
| `{{cash_balance}}` | Current account cash balances |
| `{{positions}}` | Current portfolio positions |
| `{{open_trades}}` | Open orders |
| `{{pnl}}` | Account P&L |
| `{{quotes}}` | Index quotes (configured via `snapshot.indices`) |
| `{{runs_to_review}}` | Runs pending review (used in `review_context.txt`) |

Additional static variables can be passed directly by the caller and bypass fetching: `{{previous_summary}}` and `{{last_review}}` in run context; `{{previous_review}}` in review context.

---

## Tools Available to the LLM

ZETA exposes a set of tools that the LLM can call autonomously during each iteration. Tools are auto-discovered and registered via a decorator system (`@register_tool`).

### IBKR (Interactive Brokers) Tools

| Tool | Description |
| --- | --- |
| `get_positions` | Retrieves current portfolio positions |
| `get_cash_balance` | Retrieves account cash balances |
| `get_open_trades` | Lists open orders |
| `get_quote` | Gets a real-time or delayed quote for a symbol (stock or index). Supports automatic fallback across market data types (real-time → delayed → delayed-frozen) |
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
| `close_run` | Closes the current run with a structured summary (`trades_executed`, `run_commentary`, `time_before_next_run_s`) and proposed wait time |
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
| `messages` | Messages exchanged during a run (system, user, assistant, tool_result); ordered by `sequence_index` |
| `tool_calls` | Tool calls made by the LLM (name, input/output payload, status) |
| `memory_entries` | Vector memory entries (title, content, type, tags, embedding, status) |
| `memory_access_log` | Log of all memory accesses (traceability) |

Run trigger types include:

- `llm_call`
- `review`

---

## LLM Decision Loop

At each run, ZETA follows a structured process:

1. **Load system prompt** — Phase-specific prompt file resolved from `config.yaml` and sent as the system message
2. **Build and inject context** — `context.txt` template is rendered with live data (positions, cash, open orders, quotes, market status, phase, previous summary, last review) and added as a single user message
3. **Concurrent tool execution** — Client-side tool calls within a loop iteration are dispatched concurrently (up to `_MAX_CONCURRENT_CLIENT_TOOLS = 10` in parallel)
4. **Consult memory** — Semantic search if relevant to the current decision
5. **Opportunity analysis** — Broad scan (earnings, macro, sector rotation, M&A, catalysts) via web/X search
6. **Cost discipline** — Target budget of ~$10/day in API costs; if no clear edge, switch to observe mode
7. **Risk management** — Mandatory preview before any order, respect buying power, moderate sizing by default
8. **Learning** — Update vector memory after major events
9. **Structured close** — End run via `close_run` with summary + `time_before_next_run_s`

In parallel, a periodic review cycle loads `review_context.txt`, resolves live data (including `runs_to_review`), and ends through `close_review`.

---

## Phase-Based Execution

ZETA resolves its active **phase** at the start of every iteration and adapts its prompt, scheduling, and tool availability accordingly.

Phases are evaluated in priority order:

| Priority | Phase | Condition |
| -------- | ----- | --------- |
| 1 | `HIGH_VOLATILITY` | Market open **AND** VIX > threshold |
| 2 | `OPENING_WINDOW` | Market open, within `opening_window.window_minutes` after the earliest exchange open |
| 3 | `CLOSING_WINDOW` | Market open, within `closing_window.window_minutes` before the earliest exchange close |
| 4 | `MARKET_SESSION` | Market open, outside both windows |
| 5 | `PRE_MARKET` | Market closed, current UTC time within the `phase_config.pre_market` window |
| 6 | `OFF_MARKET_SHORT` | Market closed, next open ≤ `off_market_short_threshold_hours` away |
| 7 | `OFF_MARKET_LONG` | Market closed, next open > threshold |

Each phase defines:

- **`prompt_file`** — file loaded from `prompts/` as the LLM system prompt
- **`run_interval.min` / `run_interval.max`** — wait time (seconds) between runs; the LLM-suggested value is clamped to this range
- **`review.runs_before_review`** — number of consecutive market-open runs before triggering a strategic review
- **`tools.disable`** — list of tool names disabled for this phase

Phase-level values override `phases.default` only when explicitly set. Resolution logic lives in `script/phase_resolver.py`; scheduling in `script/utils/timing.py`.

---

## Configuration

### Runtime config (`config.yaml`)

`config.yaml` is located at the repository root. Its path is resolved at import time from `script/config.py` and is **independent of the working directory**.

- Changes are hot-reloaded automatically via `watchdog` (no restart required).
- If the file is invalid, ZETA fails fast with a clear error.
- On reload, ZETA logs the resolved path.

| Key | Description |
| --- | --- |
| `debugPrint` | Enables DEBUG level logs (color-coded in console) |
| `dry_run` | If `true`, orders are not actually sent to IBKR (simulation mode) |
| `llm.provider` | LLM provider to use (`grok`) |
| `llm.model` | Specific LLM model |
| `review.llm.*` | LLM settings for the periodic review loop |
| `embedding_model` | Embedding model for vector memory |
| `ibkr.*` | IBKR settings (`host`, `port`, `clientId`, `min_cash_reserve`, `cash_reserve_currency`, `excluded_cash_currencies`) |
| `snapshot.indices` | List of indices fetched and injected into the snapshot at the start of each run. Each entry requires `symbol` and `exchange`; `currency` defaults to `USD`. |
| `phases.default` | Default execution parameters: `run_interval.min/max`, `review.runs_before_review`, `tools.disable` |
| `phases.<PHASE>` | Per-phase overrides for `run_interval`, `review`, `tools`, and `prompt_file` (non-null values override default) |
| `phase_config.off_market_short_threshold_hours` | Hours before next open below which `OFF_MARKET_SHORT` is active (default: 6) |
| `phase_config.pre_market.start_utc` / `end_utc` | UTC time window (HH:MM) for the `PRE_MARKET` phase |
| `phase_config.opening_window.window_minutes` | Duration of the `OPENING_WINDOW` phase (minutes after market open) |
| `phase_config.closing_window.window_minutes` | Duration of the `CLOSING_WINDOW` phase (minutes before market close) |
| `phase_config.high_volatility.triggers` | Ordered list of triggers for `HIGH_VOLATILITY` (`vix_above`) |

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

- **Python 3.12+**
- **Docker** (for PostgreSQL + pgvector)
- **Interactive Brokers TWS** (port `7497`) or **IB Gateway** (port `4002`) running on `127.0.0.1`
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

Optional IBKR runtime connection settings are defined in `config.yaml` under `ibkr`.

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

Make sure TWS or IB Gateway is running and configured to accept API connections. Default ports: `7497` (TWS) or `4002` (IB Gateway). Update `ibkr.port` in `config.yaml` accordingly.

### 5. Start ZETA

```bash
cd script
python main.py
```

`config.yaml` is always loaded from the repository root regardless of the working directory (path is resolved at import time in `script/config.py`).

ZETA will:

1. Connect to the database and create tables if needed
2. Connect to Interactive Brokers
3. Start the main LLM call loop

---

## Dry Run Mode

By enabling `dry_run: true` in `config.yaml`, ZETA operates in simulation mode:

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
| Language | Python 3.12+ |
| LLM | Grok (xAI) via `xai_sdk` |
| Broker | Interactive Brokers via `ib_async` |
| Database | PostgreSQL 16 + pgvector |
| ORM | SQLAlchemy |
| Embeddings | `intfloat/e5-large-v2` (default) |
| Validation | Pydantic v2 |
| Logging | `colorlog` (level-based colored logs) |
| Configuration | YAML with hot-reload (`watchdog`) |
| Containerization | Docker Compose |

---

## Additional Utilities (`test_tools/`)

- `test_tools/test_connections.py` — quick DB/IBKR/LLM connectivity checks
- `test_tools/tool_runner.py` — run one tool manually for debugging
- `test_tools/run_viewer.py` — inspect run history from the database
- `test_tools/memory_manager.py` — inspect/manage memory entries
- `test_tools/chat_with_llm.py` — ad-hoc LLM chat testing
- `test_tools/db_export_runs.py` — export DB runs/messages/tools/memory events to JSON

---

## Disclaimer

⚠️ **ZETA is an experimental project (POC).** Using an autonomous agent for trading carries significant financial risks. This software is provided as-is, with no warranty. Use `dry_run` mode to test before any use with real money. The author disclaims all liability for financial losses resulting from the use of this software.
