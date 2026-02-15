# ZETA — AI-Powered Autonomous Trading Agent

## Overview

**ZETA** (Zero-Touch Execution & Trading Algorithm) is a fully autonomous trading agent that uses a Large Language Model (LLM) to analyze markets, make investment decisions, and execute orders on US equities through **Interactive Brokers (IBKR)**. It operates in a continuous loop: at each iteration, the LLM receives a snapshot of the account state, consults its tools (market data, memory, web/X search), then decides whether to act or observe.

ZETA is not a simple assistant that suggests trades — it **executes them itself**, from opportunity scanning to order placement, including risk management and continuous learning.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                        Main Loop                        │
│                        (main.py)                        │
│                                                         │
│  1. IBKR Snapshot (positions, cash, open orders)        │
│  2. LLM call with context + tools                      │
│  3. Tool call execution (IBKR, memory, etc.)           │
│  4. JSON response (decisions, watchlist, scheduling)    │
│  5. Dynamic wait → back to step 1                      │
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
| `script/main.py` | Main loop: initializes the database, connects to IBKR, runs LLM calls in a loop with dynamic delay |
| `script/llm/llm_call.py` | Orchestrates a complete LLM call: injects the system prompt, IBKR snapshot, previous report, then manages the tool call loop (up to 20 iterations) |
| `script/llm/llm_provider.py` | LLM provider abstraction (abstract `LLM` class + factory with dynamic loading) |
| `script/llm/providers/grok_provider.py` | Grok (xAI) provider implementation with streaming, tool calling, and built-in web/X search |
| `script/llm/start_prompt.py` | Complete system prompt defining ZETA's behavior (trading rules, risk management, JSON output format) |
| `script/llm/tools/` | Auto-discovered tool registry that the LLM can call |
| `script/ibkr/ibTools.py` | Interactive Brokers connection singleton via `ib_async` |
| `script/db/` | Database layer (SQLAlchemy + pgvector): models, sessions, repositories |
| `script/config.py` | JSON configuration file loading with hot-reload |
| `script/utils/timing.py` | Market hours management and wait time calculation between iterations |

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
| `place_bracket_order` | Places a bracket order (entry + take profit + stop loss) |
| `place_oco_order` | Places an OCO (One-Cancels-Other) order |

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
| `get_date_and_hour` | Retrieves the current UTC date and time |

### Native Provider Tools (Grok/xAI)

| Tool | Description |
| --- | --- |
| `web_search` | Web search with image/video understanding |
| `x_search` | X (Twitter) search with image/video understanding |

---

## Vector Memory

ZETA has a **persistent memory** stored in PostgreSQL with the **pgvector** extension. This memory allows the agent to:

- **Store** investment theses, macro observations, notes on specific stocks, lessons learned
- **Search** by semantic similarity using embeddings (model: `sentence-transformers/nli-bert-large`, dimension 1536)
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
| `memory_access_logs` | Log of all memory accesses (traceability) |

---

## LLM Decision Loop

At each iteration, ZETA follows a structured process:

1. **Read snapshot** — Positions, cash, open orders retrieved directly from IBKR
2. **Inject context** — System prompt + snapshot + previous iteration report
3. **Time check** — Confirm market status (open/closed) via the `get_date_and_hour` tool
4. **Consult memory** — Semantic search if relevant to the current decision
5. **Opportunity analysis** — Broad scan (earnings, macro, sector rotation, M&A, catalysts) via web/X search
6. **Cost discipline** — Target budget of ~$10/day in API costs; if no clear edge, switch to observe mode
7. **Risk management** — Mandatory preview before any order, respect buying power, moderate sizing by default
8. **Learning** — Update vector memory after major events

### Output Format

The LLM returns a structured JSON object:

```json
{
  "summary": "Analysis and actions summary",
  "watchlist": ["AAPL", "NVDA", "TSLA"],
  "rules": ["Active rules for this session"],
  "decisions": [
    {
      "sym": "AAPL",
      "act": "BUY",
      "qty": 5,
      "ord": "LMT",
      "px": 185.50,
      "why": "Detailed reason for the decision"
    }
  ],
  "nextChecks": ["Items to check at the next iteration"],
  "timeBeforeNextRun": 300
}
```

---

## Smart Scheduling

ZETA automatically adapts its cadence based on context:

| Context | Behavior |
| --- | --- |
| **During market hours** (13:00 - 21:30 UTC) | The LLM chooses `timeBeforeNextRun` between 1 and 900 seconds based on urgency |
| **Outside market hours** | Fixed wait of 1 hour (3600 seconds) |
| **Minimum wait** | 60 seconds (configurable via `min_wait_seconds`) |
| **Default wait** | 900 seconds (configurable via `default_wait_seconds`) |

---

## Configuration

### `config.json`

```json
{
  "debugPrint": true,
  "dry_run": false,
  "min_wait_seconds": 60,
  "default_wait_seconds": 900,
  "llm": {
    "provider": "grok",
    "model": "grok-4-fast-reasoning"
  },
  "embedding_model": "sentence-transformers/nli-bert-large"
}
```

| Key | Description |
| --- | --- |
| `debugPrint` | Enables DEBUG level logs (color-coded in console) |
| `dry_run` | If `true`, orders are not actually sent to IBKR (simulation mode) |
| `min_wait_seconds` | Minimum time between two iterations (in seconds) |
| `default_wait_seconds` | Default wait time if the LLM does not specify a value |
| `llm.provider` | LLM provider to use (`grok`) |
| `llm.model` | Specific LLM model |
| `embedding_model` | Embedding model for vector memory |

### Environment Variables

| Variable | Description |
| --- | --- |
| `LLM_API_KEY` | LLM provider API key (xAI/Grok) |
| `DATABASE_URL` | PostgreSQL connection URL (e.g., `postgresql://zeta:zeta_password@localhost:5432/zeta`) |

---

## Prerequisites

- **Python 3.11+**
- **Docker** (for PostgreSQL + pgvector)
- **Interactive Brokers TWS** or **IB Gateway** running on `127.0.0.1:7497`
- An **xAI (Grok)** API key

---

## Installation & Getting Started

### 1. Start the database

```bash
docker-compose up -d
```

This launches a PostgreSQL 16 container with the pgvector extension, configured with:

- Database: `database_name`
- User: `username`
- Password: `password`
- Port: `5432`

### 2. Configure environment variables

Create a `.env` file at the project root:

```env
LLM_API_KEY=your_xai_api_key
DATABASE_URL=postgresql://username:password@localhost:5432/database_name
```

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

## Tech Stack

| Component | Technology |
| --- | --- |
| Language | Python 3.11+ |
| LLM | Grok (xAI) via `xai_sdk` |
| Broker | Interactive Brokers via `ib_async` |
| Database | PostgreSQL 16 + pgvector |
| ORM | SQLAlchemy |
| Embeddings | `sentence-transformers/nli-bert-large` |
| Validation | Pydantic v2 |
| Logging | `colorlog` (level-based colored logs) |
| Configuration | JSON with hot-reload |
| Containerization | Docker Compose |

---

## Disclaimer

⚠️ **ZETA is an experimental project (POC).** Using an autonomous agent for trading carries significant financial risks. This software is provided as-is, with no warranty. Use `dry_run` mode to test before any use with real money. The author disclaims all liability for financial losses resulting from the use of this software.
