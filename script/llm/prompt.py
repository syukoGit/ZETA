import logging
from pathlib import Path


logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROMPTS_DIR = _PROJECT_ROOT / "prompts"


def get_prompt(prompt_name: str) -> str:
    prompt_file = _PROMPTS_DIR / f"{prompt_name}"
    try:
        content = prompt_file.read_text(encoding="utf-8")
        if content:
            return content
    except FileNotFoundError:
        logger.error("Prompt file not found: %s", prompt_file)
    except IsADirectoryError:
        logger.error("No prompt file found")
    return ""
