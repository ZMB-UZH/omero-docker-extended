"""Resolve explicit instruction inheritance for policy-retention assertions.

Raw entrypoint size/link checks remain separate. Conditional policy is expanded
here for validation only, never as an agent startup context bundle.
"""

from pathlib import Path

from tools.agent_context_policy import AGENT_ADAPTER_LINKS, TASK_CONTRACT_PATH
from tools.lint_docs_structure import _relative_link_destinations


def read_instruction_contract(repo_root: Path, relative_path: str) -> str:
    """Read a policy surface and only its declared canonical policy references.

    Inputs: fixture root and repository-relative path. Output: inherited policy;
    missing declarations or targets raise rather than silently dropping rules.
    """
    text = (repo_root / relative_path).read_text(encoding="utf-8")
    if relative_path in AGENT_ADAPTER_LINKS:
        link = f"[AGENTS.md]({AGENT_ADAPTER_LINKS[relative_path]})"
        if (
            link not in text
            or AGENT_ADAPTER_LINKS[relative_path]
            not in _relative_link_destinations(text)
            or "mandatory shared policy" not in text
        ):
            raise AssertionError(f"{relative_path} does not require AGENTS.md")
        text += "\n" + read_instruction_contract(repo_root, "AGENTS.md")
    elif relative_path == "AGENTS.md":
        if TASK_CONTRACT_PATH not in _relative_link_destinations(text):
            raise AssertionError("AGENTS.md does not link its task contracts")
        text += "\n" + (repo_root / TASK_CONTRACT_PATH).read_text(encoding="utf-8")
    return text
