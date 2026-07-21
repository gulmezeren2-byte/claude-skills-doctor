# Changelog

## 0.1.0 — 2026-07-21

First public release.

- **Discovery-budget check** — the headline. Sums the `name` + `description`
  characters of every skill and slash-command Claude Code loads and compares them
  to the 15,000-char budget (honours `SLASH_COMMAND_TOOL_CHAR_BUDGET`). Over budget,
  Claude Code silently stops listing skills with no warning; skilldoctor makes that
  visible, with a `budget` view that lists the biggest contributors to trim.
- **Whole-system, deterministic health check** across user (`~/.claude/skills`),
  project (`.claude/skills`) and plugin skills — no model calls, no network. Catches
  the cross-skill failures a single-skill validator can't: duplicate names and
  near-identical (colliding) descriptions.
- **Per-skill checks**: invalid YAML frontmatter (which *silently* prevents
  loading), missing `name`/`description`, `name` that doesn't match its folder,
  kebab-case/length rules, over-long or angle-bracketed descriptions, `allowed-tools`
  that don't cover the body's tool use, oversized bodies, absolute paths, and
  human-facing docs left inside a skill folder.
- **Honest calibration**: lints *your own* skills fully; third-party plugin skills
  count toward the budget but are checked only for load-breaking errors, so it never
  cries wolf on skills you can't fix.
- CLI with `--json` (CI-friendly) and a non-zero exit on errors, plus `--strict`.
