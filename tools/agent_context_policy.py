"""Single-source policy for agent context surfaces and retrieval limits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextRoutingLimits:
    """Numeric retrieval limits that keep agent context small and predictable."""

    first_pass_task_files: int
    refine_loop_limit: int
    escalation_round_files: int
    hard_stop_task_files: int

    def required_tokens(self) -> tuple[str, ...]:
        """Return the doc tokens that encode the routing policy."""
        return (
            f"Open at most {self.first_pass_task_files} task-specific files in the first pass",
            f"Run at most {self.refine_loop_limit} refine loops",
            f"Add at most {self.escalation_round_files} more files per escalation round",
            f"If you have opened {self.hard_stop_task_files} task-specific files",
        )


@dataclass(frozen=True)
class ContextSurfaceContract:
    """Compactness and routing expectations for agent-facing context surfaces."""

    required_tokens: tuple[str, ...]
    max_nonempty_lines: int | None = None


CONTEXT_ROUTING_LIMITS = ContextRoutingLimits(
    first_pass_task_files=4,
    refine_loop_limit=2,
    escalation_round_files=3,
    hard_stop_task_files=8,
)


CONTEXT_SURFACE_CONTRACTS: dict[str, ContextSurfaceContract] = {
    "AGENTS.md": ContextSurfaceContract(
        max_nonempty_lines=110,
        required_tokens=(
            "Single-session rule",
            "AI agent <>",
            "separate agent session",
            "docs/reference/ai-agent-context-routing.md",
            "docs/reference/ai-agent-runtime-playbook.md",
            "docs/reference/ai-agent-skills.md",
            "python3 -m ruff check .",
            "python3 -m ruff format --check .",
            "numeric caps",
        ),
    ),
    "CLAUDE.md": ContextSurfaceContract(
        max_nonempty_lines=60,
        required_tokens=(
            "Single-session rule",
            "AI agent <>",
            "separate agent session",
            "docs/reference/ai-agent-context-routing.md",
            "docs/reference/ai-agent-runtime-playbook.md",
            "docs/reference/ai-agent-skills.md",
            "numeric caps",
        ),
    ),
    "GEMINI.md": ContextSurfaceContract(
        max_nonempty_lines=25,
        required_tokens=(
            "Single-session rule",
            "AI agent <>",
            "separate agent session",
            "docs/reference/ai-agent-context-routing.md",
            "docs/reference/ai-agent-runtime-playbook.md",
            "numeric caps",
        ),
    ),
    ".github/copilot-instructions.md": ContextSurfaceContract(
        max_nonempty_lines=30,
        required_tokens=(
            "Single-session rule",
            "AI agent <>",
            "separate agent session",
            "docs/reference/ai-agent-context-routing.md",
            "docs/reference/ai-agent-runtime-playbook.md",
            "numeric caps",
        ),
    ),
    ".cursor/rules/00-omero-core.mdc": ContextSurfaceContract(
        max_nonempty_lines=15,
        required_tokens=(
            "separate agent session",
            "AI agent <>",
            "docs/reference/ai-agent-context-routing.md",
            "numeric caps",
        ),
    ),
    "docs/reference/ai-agent-context-routing.md": ContextSurfaceContract(
        max_nonempty_lines=80,
        required_tokens=(
            "## Numeric caps",
            "CI-validated by `python3 tools/lint_docs_structure.py`",
            *CONTEXT_ROUTING_LIMITS.required_tokens(),
        ),
    ),
    ".agents/skills/context-budget/SKILL.md": ContextSurfaceContract(
        max_nonempty_lines=30,
        required_tokens=(
            "lower token usage",
            "CI-validated",
            *CONTEXT_ROUTING_LIMITS.required_tokens(),
        ),
    ),
}
