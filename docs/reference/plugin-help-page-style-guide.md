# Plugin Help Page Style Guide

This guide is the canonical pattern for user-facing help pages in OMERO Docker
Extended plugins. AI Agents must load it before creating or rewriting plugin
help pages, help templates, help screenshots, or route-level help copy.

The current reference implementation is:

- `omeroweb_tools/templates/omeroweb_tools/help.html`
- `omeroweb_tools/static/omeroweb_tools/styles.css`
- `omeroweb_tools/tests/frontend/enhanced_search_help.browser.vitest.mjs`

## Purpose

Plugin help is for end users completing work in the browser. It is not an
administrator runbook, developer note, changelog, marketing page, or system
architecture explanation.

Help pages must:

- explain only the workflow visible to the user;
- stay compact enough to scan beside the actual plugin page;
- use exact interface screenshots when screenshots are present;
- avoid Docker, database, server, environment, log, and code details;
- avoid credentials, personal data, internal hostnames, and installation-specific
  object assumptions.

## Page Structure

Use one help page per plugin surface. For grouped tool pages, the page title is
the group title and each tool gets a collapsible tool section.

Required structure for HTML help pages:

1. top-level page container matching the plugin's existing admin-tools layout;
2. back or close control above the title;
3. `h1` page title;
4. one or more tool sections;
5. compact workflow panels inside each tool section;
6. a final `Troubleshooting` panel when useful.

For Tools help, the required labels are:

- page title: `Tools help`;
- first tool section heading: `Enhanced search`;
- final section heading: `Troubleshooting`.

Use `h1` for the page title, `h2` for each tool section, and `h3` for panels
inside a tool section. Do not skip heading levels for visual reasons.

## Back And Close Controls

Keep the back control visually identical to the source plugin's existing back
link. For Tools help this means:

- use an `<a>` element, not a `<button>`;
- keep `class="admin-tools-back-link"`;
- keep the left arrow text in the same position and style;
- keep the parent page URL in `href` so the element remains a normal link when
  JavaScript is unavailable;
- when the help page is opened from a help icon in a separate browser window,
  attach a click handler that calls `event.preventDefault()` and then
  `window.close()`.

Do not add a new button reset class, custom padding, custom border, or custom
font to the back control unless the source plugin already uses that class.

## Collapsible Tool Sections

Collapsible tool sections are for grouping help by tool, not for hiding every
small panel independently.

Required behavior:

- default state is expanded;
- no persisted state in local storage, session storage, cookies, or the
  database;
- `aria-expanded="true"` by default;
- the controlled body uses `aria-hidden="true"` only while collapsed;
- expansion and collapse use the same smooth max-height and opacity pattern as
  the Enhanced search page;
- the arrow direction follows the shared Enhanced search section toggle exactly:
  the expanded state keeps the unrotated horizontal indicator, and the
  collapsed state uses the existing 90-degree indicator.

Use the existing `tools-search-section-toggle` and
`tools-search-section-toggle__indicator` classes for the arrow and button
alignment. Do not add tool-help-specific arrow direction overrides unless the
shared toggle contract changes at the same time.

## Copy Rules

Write for users who already opened the plugin and need to finish a task.

Required copy style:

- short headings;
- short bullet lists;
- action verbs first;
- no implementation language;
- no admin-only terms unless the plugin itself is admin-only;
- no repeated explanations of the same control;
- no promises about data that depends on permissions or index state.

Use visible UI labels exactly as they appear in the interface, including
capitalization. If a label changes, update the help copy and screenshots in the
same change.

## Screenshot Rules

Screenshots must be exact captures from the real interface or deterministic
preview of the same templates and CSS. Do not create illustrative mockups.

Required screenshot rules:

- crop rectangles consistently;
- keep the full blue border of captured panels visible;
- place each screenshot below its related text, inside the same section;
- use high-DPI captures so text and controls remain sharp;
- show realistic state when practical, but do not assume pre-existing user data
  in tests;
- do not show credentials, tokens, personal data, private hostnames, or unrelated
  browser chrome.

If a screenshot uses live data for a one-time documentation refresh, the help
page must not depend on that object existing. Regression tests must use
deterministic fixtures or static assets tracked in the repository.

## Visual Rules

Help pages must follow the plugin's existing visual system.

Required visual rules:

- no nested cards;
- screenshots below text, not inline beside long text;
- consistent font sizes and line heights with the parent plugin;
- consistent panel border widths, colors, and spacing;
- `Troubleshooting` uses the established orange highlight;
- controls keep the same alignment, arrow style, and focus treatment as their
  source plugin;
- page text must not overlap or overflow at supported desktop widths.

For Enhanced search help, the first-level tool section sits below `Tools help`
with a visible gap, and its panels remain inside that section.

## Registration And References

When adding or moving a help page:

1. register the Django route and template explicitly;
2. update the nearest plugin doc;
3. update `docs/index.md`;
4. update `docs/reference/service-endpoints.md` when routes change;
5. add or update a focused template contract test;
6. add or update a browser preview test for layout-sensitive behavior.

Agent-facing routing for plugin help work must point back to this document from
`AGENTS.md` and `docs/reference/ai-agent-context-routing.md`.

## Verification

Minimum verification for help-page changes:

```bash
python3 tools/lint_docs_structure.py
npx --yes markdownlint-cli2@0.23.1 <changed markdown files>
ruff check <changed python tests>
ruff format --check <changed python tests>
python3 -m unittest -v tests/test_repository_documentation_regressions.py
python3 -m pytest <changed plugin test lane> -v -p no:cacheprovider -W error
```

For HTML, CSS, JavaScript, screenshots, or collapsible behavior, also run the
frontend preview lane from `.agents/skills/frontend-preview/SKILL.md`.

After rebuilding or redeploying a live OMERO.web container, verify that the help
route does not raise a Django error and that focused installed-container tests
still pass.
