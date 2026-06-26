"""Prompt builder node for the LangGraph review pipeline.

Loads the versioned review prompt template from disk (cached after first load)
and exposes :func:`build_hunk_prompt` for use by the ``llm_reviewer`` node.

The node itself acts as a validation pass-through: it verifies the template
file is loadable and returns an empty state update.
"""

from __future__ import annotations

import functools
from pathlib import Path

import structlog

from src.agent.models import DiffHunk, RepoContext
from src.agent.state import ReviewState

log = structlog.get_logger()

# Path to the versioned prompt template, relative to this file
_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "review_hunk_v1.txt"


@functools.lru_cache(maxsize=1)
def _load_template() -> tuple[str, str]:
    """Load and parse the review prompt template from disk.

    The result is cached so the file is only read once per process.

    Returns:
        A ``(system_prompt, user_prompt_template)`` tuple where the user
        prompt template still contains ``{placeholder}`` fields.

    Raises:
        ValueError: If the prompt file does not exist or cannot be parsed.
    """
    if not _PROMPT_FILE.exists():
        raise ValueError(
            f"Prompt template not found: {_PROMPT_FILE}. "
            "Ensure 'src/agent/prompts/review_hunk_v1.txt' is present."
        )

    raw = _PROMPT_FILE.read_text(encoding="utf-8")

    # Template format:
    #   SYSTEM:\n<system text>\n\nUSER:\n<user template>
    if "\nUSER:\n" not in raw:
        raise ValueError(
            "Prompt template is malformed: expected a '\\nUSER:\\n' separator "
            f"between SYSTEM and USER sections. File: {_PROMPT_FILE}"
        )

    parts = raw.split("\nUSER:\n", maxsplit=1)
    system_section = parts[0]
    user_template = parts[1]

    # Strip the leading "SYSTEM:\n" marker
    if system_section.startswith("SYSTEM:\n"):
        system_section = system_section[len("SYSTEM:\n"):]

    return system_section.strip(), user_template.strip()


def build_hunk_prompt(hunk: DiffHunk, context: RepoContext) -> tuple[str, str]:
    """Assemble the system and user prompts for a single diff hunk.

    Fills all ``{placeholder}`` fields in the cached template using data
    from the hunk and repository context.

    Args:
        hunk: The :class:`~src.agent.models.DiffHunk` to review.
        context: Repository-level context for the review.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to an
        :class:`~src.agent.llm_backend.LLMBackend`.
    """
    system_prompt, user_template = _load_template()

    # Build a readable file-tree string (one path per line, indented)
    file_tree_str = (
        "\n    ".join(context.file_tree[:50])  # cap at 50 entries
        if context.file_tree
        else "(not available)"
    )

    user_prompt = user_template.format(
        file_path=hunk.file_path,
        language=hunk.language or "Unknown",
        hunk_header=hunk.hunk_header,
        hunk_content=hunk.content,
        readme_excerpt=context.readme_excerpt or "(no README available)",
        file_tree=file_tree_str,
    )

    return system_prompt, user_prompt


async def prompt_builder(state: ReviewState) -> dict[str, object]:
    """LangGraph node: validate the prompt template and pass state through.

    This node ensures the prompt template file is readable and well-formed
    before any LLM calls are made.  The actual per-hunk prompt assembly
    happens inside the ``llm_reviewer`` node via :func:`build_hunk_prompt`.

    Args:
        state: The current :class:`~src.agent.state.ReviewState`.

    Returns:
        An empty dict (no state fields are modified by this node).

    Raises:
        ValueError: If the prompt template cannot be loaded.
    """
    # This call will raise if the template is missing or malformed.
    # LRU-cache means the file is only read once across the pipeline run.
    system_prompt, _ = _load_template()

    log.info(
        "prompt_builder.template_loaded",
        template_file=str(_PROMPT_FILE),
        system_prompt_chars=len(system_prompt),
    )

    return {}
