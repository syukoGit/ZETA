import logging
from pathlib import Path


logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROMPTS_DIR = _PROJECT_ROOT / "prompts"


def get_prompt(prompt_name: str) -> str:
    base_dir = _PROMPTS_DIR.resolve()
    try:
        prompt_file = (base_dir / prompt_name).resolve()
    except OSError as exc:
        logger.error("Failed to resolve prompt file path for %s: %s", prompt_name, exc)
        return ""

    # Ensure the resolved prompt file is within the prompts directory to prevent path traversal.
    if base_dir not in prompt_file.parents:
        logger.error("Invalid prompt name outside prompts directory: %s", prompt_name)
        return ""

    try:
        content = prompt_file.read_text(encoding="utf-8")
        if content:
            return content
    except FileNotFoundError:
        logger.error("Prompt file not found: %s", prompt_file)
    except IsADirectoryError:
        logger.error("No prompt file found")
    return ""
