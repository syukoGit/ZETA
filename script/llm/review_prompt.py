from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROMPTS_DIR = _PROJECT_ROOT / "prompts"
_REVIEW_PROMPT_FILE = _PROMPTS_DIR / "review_prompt.txt"


def _load_review_prompt() -> str:
    try:
        content = _REVIEW_PROMPT_FILE.read_text(encoding="utf-8")
        if content:
            return content
    except FileNotFoundError:
        pass
    return "You are ZETA Review Engine. Analyze and end only via close_review."


REVIEW_PROMPT = _load_review_prompt()