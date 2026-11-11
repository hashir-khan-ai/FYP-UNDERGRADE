"""Versioned prompt registry loader.

Prompts live under ``prompts/``. Both layouts used by the project docs are
supported:

* ``prompts/<version>/<step>.txt`` (current Phase 1 layout)
* ``prompts/<step>/<version>.md`` (PLAN.md layout)

The selected ``PROMPT_VERSION`` is part of the LLM cache key and audit record.
"""

from pathlib import Path

from src.config import settings

PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "prompts"


class PromptNotFoundError(FileNotFoundError):
    """Raised when a requested prompt version/step does not exist."""


def load_prompt(step: str, version: str | None = None) -> str:
    """Load and return the prompt text for ``step``.

    Args:
        step: Prompt name, for example ``answer``.
        version: Version tag; defaults to ``settings.PROMPT_VERSION``.

    Raises:
        PromptNotFoundError: if no supported prompt file exists.
    """
    selected = version or settings.PROMPT_VERSION
    candidates = [
        PROMPTS_ROOT / selected / f"{step}.txt",
        PROMPTS_ROOT / selected / f"{step}.md",
        PROMPTS_ROOT / step / f"{selected}.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip() + "\n"
    tried = ", ".join(str(path.relative_to(PROMPTS_ROOT)) for path in candidates)
    raise PromptNotFoundError(f"Prompt '{step}' version '{selected}' not found. Tried: {tried}")


__all__ = ["PromptNotFoundError", "PROMPTS_ROOT", "load_prompt"]
