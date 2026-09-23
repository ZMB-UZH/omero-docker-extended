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
        """Return the doc tokens that encode the routing policy.

        Inputs: none. Output: `tuple[str, ...]`.
        """
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
    max_utf8_bytes: int | None = None


CONTEXT_ROUTING_LIMITS = ContextRoutingLimits(
    first_pass_task_files=4,
    refine_loop_limit=2,
    escalation_round_files=3,
    hard_stop_task_files=8,
)


KARPATHY_BASELINE_COMMIT = "".join(
    (
        "2c606141",
        "936f1eee",
        "f17fa304",
        "3a72095b",
        "4765b9c2",
    )
)


TASK_CONTRACT_PATH = "docs/reference/ai-agent-task-contracts.md"

AGENT_ADAPTER_LINKS: dict[str, str] = {
    "CLAUDE.md": "AGENTS.md",
    "GEMINI.md": "AGENTS.md",
    ".github/copilot-instructions.md": "../AGENTS.md",
    ".cursor/rules/00-omero-core.mdc": "../../AGENTS.md",
}

CONTEXT_SURFACE_CONTRACTS: dict[str, ContextSurfaceContract] = {
    "AGENTS.md": ContextSurfaceContract(
        max_nonempty_lines=90,
        max_utf8_bytes=6500,
        required_tokens=(
            "AI Agent <>",
            "Co-authored-by: AI Agent",
            "one session",
            "exactly one object and one deletion",
            "permission never carries forward",
            "exact GitHub and Docker tags",
            "human public-safety review",
            "operator-owned",
            "current remote default branch",
            "cocoindex-code",
            ".agents/skills/cocoindex-code-search/SKILL.md",
            ".agents/skills/caveman/SKILL.md",
            "mandatory",
            "not opt-in",
            "normal prose",
            "numeric caps",
            "verification ledger",
            "stable final tree",
            "run_local_workflow_gates.py --setup --profile ci",
            "docs/reference/ai-agent-context-routing.md",
            TASK_CONTRACT_PATH,
        ),
    ),
    **{
        path: ContextSurfaceContract(
            max_nonempty_lines=18,
            max_utf8_bytes=1000,
            required_tokens=(
                f"[AGENTS.md]({link})",
                "mandatory shared policy",
                "triggers in AGENTS",
                ".agents/skills/",
                "caveman",
                "CocoIndex",
            ),
        )
        for path, link in AGENT_ADAPTER_LINKS.items()
    },
    TASK_CONTRACT_PATH: ContextSurfaceContract(
        max_utf8_bytes=24000,
        required_tokens=(
            "## Pinned Karpathy agent baseline",
            KARPATHY_BASELINE_COMMIT,
            "Compact and efficient code matters",
            "EXAMPLES.md",
            "## AI commit identity",
            "contributors?anon=1",
            "real human GitHub identities",
            "## Default-branch development rule",
            "## Destructive operations and releases",
            "## Mandatory security read order",
            "## Configuration",
            "## Documentation",
            "## Verification",
            "## CocoIndex",
            "## Runtime and sync",
            "## Verification minimum",
            "python3 -m ruff check .",
            "python3 -m ruff format --check .",
        ),
    ),
    "docs/reference/ai-agent-context-routing.md": ContextSurfaceContract(
        max_nonempty_lines=85,
        max_utf8_bytes=10500,
        required_tokens=(
            "## Numeric caps",
            "CI-validated by `python3 tools/lint_docs_structure.py`",
            "cocoindex-code-search",
            *CONTEXT_ROUTING_LIMITS.required_tokens(),
        ),
    ),
    ".agents/skills/context-budget/SKILL.md": ContextSurfaceContract(
        max_nonempty_lines=34,
        max_utf8_bytes=3300,
        required_tokens=(
            "lower token usage",
            "CI-validated",
            "cocoindex-code-search",
            "caveman",
            *CONTEXT_ROUTING_LIMITS.required_tokens(),
        ),
    ),
    ".agents/skills/caveman/SKILL.md": ContextSurfaceContract(
        max_nonempty_lines=26,
        max_utf8_bytes=4000,
        required_tokens=(
            "mandatory, not opt-in",
            "internal AI",
            "normal prose",
            "Compression never outranks correctness",
            "Required progress updates",
        ),
    ),
    ".agents/skills/cocoindex-code-search/SKILL.md": ContextSurfaceContract(
        max_utf8_bytes=6500,
        required_tokens=(
            "mandatory",
            "MCP search itself never refreshes",
            "semantic output as routing only",
            "exact",
        ),
    ),
}
