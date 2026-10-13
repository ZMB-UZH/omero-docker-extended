# AI Agent Web Research Stack

All agents must use the repo-local Crawl4AI reader for public web research.
Search providers discover URLs; they do not replace reading the actual source.
This developer tool is separate from OMERO and requires no cloud account.

## Core Pattern

1. Search the repo, local docs, and user-provided links first.
2. Prefer official docs, release notes, source repositories, standards pages, and issue trackers.
3. Use bounded public-web discovery to find the smallest set of relevant sources.
4. Read selected sources through `crawl4ai-research`, extracting only needed sections.
5. Use interactive browser diagnostics to understand extraction failures,
   not as a substitute reader. Restore Crawl4AI before dependent research.
6. Audit source quality, dates, and contradictions before making claims.
7. Reuse sessions, cache results, and back off instead of hammering a site.

## Safe Defaults

- Bias toward free, built-in, open-source, or self-hostable tooling when the task allows.
- Prefer deterministic browser control and repeatable extraction over one-off manual wandering.
- The reader uses a fresh headless browser, verified HTTPS, and robots checks.
- Keep URLs, dates, versions, and access times with your notes so later answers stay traceable.

## Install And Use

Use Linux with Python 3.14 for the qualified dependency lock. Install once:

```bash
python3 tools/crawl4ai_research.py setup
python3 tools/cocoindex_agent_search.py index --allow-dirty-index
python3 tools/agent_preflight.py begin --query "<task>" --research-url "<public-source>"
```

Later source reads use `python3 tools/crawl4ai_research.py read "<url>"` with
optional `--selector` and `--max-chars`. Output identifies the source, final URL,
access time, HTTP status, full-text digest and any truncation. Read further
relevant sections when truncated; never label an excerpt a complete review.
Each invocation retains a private receipt directory with the requested scope,
native URL, status, success, errors, full extracted text and provider version.
The native capture is hashed and written before validation; denied, empty and
failed results remain available without being accepted as research. Process
failures and timeouts receive separate diagnostics, never invented native results.
Known challenge pages fail closed. Review every extract for the requested
subject and reject navigation-only or otherwise wrong-scope content; no status
code or automatic check can establish semantic completeness.
Registry/account APIs still supply structured metadata and authenticated
repository operations. PDF processing and authenticated browser profiles are
not part of this reader's qualified surface.

`AGENT_CRAWL4AI_HOME` or XDG data paths hold isolated environments, packages,
Chromium and cache outside the checkout. Environment identities include the
Python version and both hash-pinned dependency and build-tool locks. Installation is explicit;
reads do not download packages or modify global MCP configuration. Missing Linux
browser libraries must be installed using the official Playwright instructions,
not by weakening browser checks. No production container or deployment env is changed.
Full captures stay in owner-only `receipts/read-*` directories under that same
external home. They are not uploaded, indexed or copied into the repository.

## Enforcement And Evidence

`tools/agent_preflight.py` is shared by Codex, Copilot, Cursor, Gemini, Claude,
and future adapters. It loads Caveman, executes a current-index CocoIndex query,
and reads declared research URLs through Crawl4AI. Failure leaves an incomplete
receipt; `check` rejects missing, failed, expired, and changed-policy receipts.
Receipts stay under XDG state paths and contain hashes rather than source text,
queries, host details or credentials. Run `begin` for each new task; reuse its
receipt during that task, not as proof of unrelated research.

The repository pre-commit gate checks every local commit, independent of the editor
or author name: Git cannot identify AI activity from a normal user identity.
Install the tracked configuration in development clones, preserving existing hooks
under the repository approval rules. Agent publication uses the official GitHub
connector, which does not run local hooks; agents must run the same `check` explicitly
before its first write. Native hooks are additional reinforcement, not a substitute.
Every harness inherits these requirements. CI validates the canonical rules,
adapter inheritance, hook wiring, badge order and gate failure cases. Future
adapters must be added to those contract tests before being described as supported.

No repository can inspect an agent's private reasoning or prevent an external
client from deliberately ignoring instructions or bypassing local hooks.
Execution receipts prove tool execution, not that a model reasoned correctly.
Caveman is a mandatory instruction overlay, not an executable compressor.
Never forge evidence, use `--no-verify`, or silently replace a failed tool.

## Qualification

Run `python3 -m pytest -q tests/test_agent_preflight.py tests/test_crawl4ai_research.py`
and the existing agent, CocoIndex, Caveman and README contract suites. For a
runtime change, provision a fresh external environment and read official HTTPS
documentation on Linux. Test real browser extraction, denied/empty/error results,
truncation, timeouts, credential isolation and the gate's refusal paths. Reuse
unchanged receipts; do not recrawl sites merely to inflate a test count.

The base Crawl4AI distribution requires NLTK even though this reader exposes no
model training/loading APIs. The reader pins upstream NLTK source at
`b417a98a9497b4a27067043e35e64c388e060686`, which contains the merged model-path
fixes absent from the released PyPI package. Installation verifies the archive
hash, uses a separately hash-pinned build backend and permits source builds only
for this dependency. Each read verifies installed direct-source provenance and
retains it in the native evidence. The upstream version remains `3.10.3`; it is
not relabeled to evade version-based advisories. Both locks remain scanner inputs.
OSV's requirements parser omits direct-source requirements, so the matching
`crawl4ai-source/nltk.cdx.xml` inventory explicitly includes NLTK's real version,
archive URL and digest. The raw audit retains version-based findings. Keep the
inventory, runtime provenance and lock aligned; an empty report without the
source component is incomplete, not a clean scan.

The reviewed source exception is restricted to that inventory directory and
the exact archive hash in `crawl4ai-source/review.toml`. It does not cover the
PyPI release, any other package, or a future advisory. The source guard checks
both dependency locks, the inventory and native OSV configuration before the
scan may use the exception. A separate unfiltered native scan retains the raw
finding and must match the reviewed advisory. Changed inputs, extra findings,
missing evidence or the review deadline fail closed. Replace the source pin
with a qualified upstream release and remove the exception when available;
never extend its deadline without a new review and explicit authorization.
Qualify the upstream model-artifact, transition-parser, tagger and maxent-save
regression suites, then verify real Crawl4AI extraction before changing this pin.
Do not enable NLP, LLM or PDF extras or claim that isolation alone fixes an
upstream advisory. Retain and investigate any version-only scanner finding.

## Hard Boundaries

- Do not bypass CAPTCHAs, paywalls, rate limits, bot checks, geo blocks, login walls, or access controls.
- Do not rotate identities, scrape against explicit denial signals, or simulate evasive traffic.
- Do not paste PATs, passwords, cookies, or internal-only URLs into public-web tools.
- If a site requires authentication or human verification, stop and ask for a permitted session or alternate source.
- Do not expose this CLI as a remote URL-fetching service. Public-address checks
  are input validation, not DNS pinning or a network sandbox. Use an unprivileged
  development account and do not point the crawler at production administration.

## Upstream References

- [Crawl4AI 0.9.4 release](https://github.com/unclecode/crawl4ai/releases/tag/v0.9.4)
- [Tagged changelog](https://github.com/unclecode/crawl4ai/blob/v0.9.4/CHANGELOG.md)
- [Installation](https://docs.crawl4ai.com/core/installation/)
- [Browser and crawler configuration](https://docs.crawl4ai.com/core/browser-crawler-config/)
- [License and attribution](https://github.com/unclecode/crawl4ai/blob/v0.9.4/LICENSE)

This product includes software developed by UncleCode (<https://x.com/unclecode>)
as part of the Crawl4AI project (<https://github.com/unclecode/crawl4ai>).

Use the repo-local skills `web-discovery`, `site-extract`, `browser-fallback`, `source-audit`, and `compliance-and-rate-limit` to apply this stack in small, auditable steps.
