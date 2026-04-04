# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ZETA** (Zero-Touch Execution & Trading Algorithm) is a fully autonomous AI-powered trading agent for US equities using Interactive Brokers. An LLM (Grok/xAI) continuously receives live market snapshots and account state, uses tools to analyze opportunities, and autonomously executes orders.

## Running the Agent

```bash
# Start PostgreSQL (required first)
docker-compose up -d

# Run the trading agent (from script/ directory or root)
cd script && python main.py
```

Prerequisites: Python 3.12+, Docker, Interactive Brokers TWS/IB Gateway running on port 7497 or 4002, `.env` with `LLM_API_KEY` and `DATABASE_URL`.

**Dry run mode** (no real orders): set `dry_run: true` in `config.yaml`.

## Debugging Utilities (`test_tools/`)

```bash
python test_tools/test_connections.py    # Verify IBKR + DB connectivity
python test_tools/tool_runner.py         # Execute a single tool in isolation
python test_tools/run_viewer.py          # Inspect run history from DB
python test_tools/chat_with_llm.py       # Ad-hoc LLM chat for prompt testing
python test_tools/memory_manager.py      # Inspect/manage vector memory entries
python test_tools/db_export_runs.py      # Export DB to JSON (--from/--to date args)
```

## Architecture

### Main Loop (`script/main.py`)

Each iteration:
1. **Phase resolution** — determine current execution phase (e.g., MARKET_SESSION, OPENING_WINDOW) based on time, market status, and VIX
2. **LLM trading run** — build context (live IBKR snapshot + last review/run), call Grok with tools, execute tool calls concurrently (max 10 in flight) until `close_run` is called
3. **Periodic review** — every N runs (phase-configurable), run a separate LLM call to analyze performance and update strategy
4. **Wait** — sleep for LLM-specified duration clamped to phase `[min, max]` interval

### LLM Layer (`script/llm/`)

- **`llm_call.py`** — Orchestrates trading and review loops; handles tool dispatch
- **`context_builder.py`** — Fetches live IBKR/DB data concurrently via `asyncio.gather()`, renders `prompts/context.txt` template with `{{variable}}` substitution; failed fetches default to `"N/A"`
- **`prompt.py`** — Loads prompts from `prompts/` (git-ignored); per-phase prompt files override defaults via `config.yaml`
- **`llm_provider.py`** — Abstract provider interface + factory; currently only Grok implemented
- **`tools/`** — Auto-discovered by decorator; split into `ibkr/`, `memory/`, `utils/`, `history/`

### Tool Registration

Tools are registered with a decorator and automatically discovered:

```python
@register_tool(
    "tool_name",
    description="...",
    args_model=PydanticModel,
    run=True,   # available in trading runs
    review=False  # available in review runs
)
async def tool_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"result": ...}
```

Per-phase tool disabling is configured in `config.yaml` under `phases.<PHASE>.tools.disable`.

### Phase Resolution (`script/phase_resolver.py`)

Priority order (highest first):
1. `HIGH_VOLATILITY` — market open + VIX above threshold
2. `OPENING_WINDOW` — within N minutes after market open
3. `CLOSING_WINDOW` — within N minutes before market close
4. `MARKET_SESSION` — market open, outside windows
5. `PRE_MARKET` — configured UTC pre-market window
6. `OFF_MARKET_SHORT` — < 6 hours to next open
7. `OFF_MARKET_LONG` — > 6 hours to next open

### Database (`script/db/`)

PostgreSQL 16 + pgvector. Key models in `models.py`:
- `Run` / `Review` — each LLM decision cycle, with status, duration, summary
- `Message` — every message exchanged with the LLM (ordered by `sequence_index`)
- `ToolCall` — every tool invocation with args and result
- `Memory` — vector embeddings (1024-D, `intfloat/e5-large-v2`) for semantic search
- `MemoryAccessLog` — audit trail linking memory reads/writes to specific messages

Accessed via repository pattern: `script/db/repositories/`.

### IBKR Integration (`script/ibkr/`)

- **`ibTools.py`** — Singleton (`IBTools.get_instance()`); wraps `ib_async` with retry logic; use `async with ibtools.guarded():` for all requests
- **`watchdog.py`** — Background health monitoring with auto-reconnection
- **`contracts.py`** — Contract qualification with in-memory caching

## Configuration

**`config.yaml`** (hot-reloaded via `watchdog`, git-ignored):
- `dry_run` — simulation mode
- `llm.model` — LLM model ID
- `ibkr.cash_reserve` — minimum cash to preserve
- `phases.<PHASE>.run_interval` — `{min, max}` wait seconds
- `phases.<PHASE>.review.runs_before_review` — how often reviews trigger
- `phases.<PHASE>.tools.disable` — list of tool names to disable
- `phases.<PHASE>.prompt_file` — override default prompt file
- `phase_config` — time windows and VIX thresholds for phase resolution

**`.env`** (git-ignored): `LLM_API_KEY`, `DATABASE_URL`, `POSTGRES_*`

## Key Conventions

- All I/O is `async`/`await`; `nest_asyncio` is applied at startup
- Config accessed via `config()` singleton; Pydantic V2 validates all models
- `script/` is on the Python path (configured in `.vscode/settings.json`), so imports are relative to `script/`
- Prompts live in `prompts/` (git-ignored); `context.txt` is the shared context template
- Code formatter: Black (tab size 4)
