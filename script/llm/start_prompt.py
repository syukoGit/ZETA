from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROMPTS_DIR = _PROJECT_ROOT / "prompts"
_START_PROMPT_FILE = _PROMPTS_DIR / "start_prompt.txt"


def _load_start_prompt() -> str:
    try:
        content = _START_PROMPT_FILE.read_text(encoding="utf-8")
        if content:
            return content
    except FileNotFoundError:
        pass
    return "You are ZETA. Execute a cautious trading run and end via close_run."


DEFAULT_START_PROMPT = _load_start_prompt()