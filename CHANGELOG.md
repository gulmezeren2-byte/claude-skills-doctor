# Changelog

## 0.6.0 — 2026-07-31

The headline number was stale, and stale in the direction that matters: it said you
had room when you did not.

- **The listing budget is 1% of your model's context window, not a fixed 15,000
  characters.** Claude Code scales it with the model and exposes
  `skillListingBudgetFraction` to raise it. Measured on the author's own machine, the
  same 10,990 characters of skills reads as **73% (fine)** under the old fixed number,
  **137% (over)** on a 200K-token model, and **27%** on a 1M one. A single number
  could not have been right for all three, and the one we shipped was wrong for the
  common case. `--context-window` states your model; `--budget` and
  `SLASH_COMMAND_TOOL_CHAR_BUDGET` still pin it exactly.
- **Every budget now says where it came from, and whether it is measured or
  derived.** Turning a token budget into the character count we measure means one
  assumption (~4 chars/token), and a tool about measurement honesty does not get to
  hide its own estimate. `--json` carries `source` and `exact` alongside the number.
- **New check `description-capped`.** `description` + `when_to_use` is truncated at
  **1,536 characters per entry**, regardless of budget — exact, model-independent, and
  entirely unchecked before. Everything past the cut is text Claude never sees when
  deciding whether your skill fits the request.
- **`when_to_use` counts.** It is appended to `description` in the listing, so it now
  counts toward both the per-entry cap and the shared budget. Leaving it out
  understated every skill that uses one.
- **An over-long entry now costs the cap, not its full length.** A 4,000-character
  description consumes 1,536 of the shared budget, because that is all that gets
  listed. Counting it raw overstated the total and pointed people at the wrong skill.
- **Corrected what overflow actually does.** Earlier versions said Claude Code "stops
  listing some skills". It does not: the listing always keeps every skill *name*, and
  what gets dropped is the *description*, starting with the skills you invoke least.
  Same silent failure, different fix — and a tool that describes the failure wrongly
  teaches the wrong remedy.
- Frontmatter allowlist realigned with the current Claude Code reference table:
  `when_to_use`, `effort`, `paths`, `hooks`, `agent`, `context`, `background`,
  `arguments` and `disallowed-tools` are no longer reported as unexpected.

All of the above verified against <https://code.claude.com/docs/en/skills> on
2026-07-31 rather than inferred.


## 0.5.0 — 2026-07-28

- **Ships a GitHub Action.** Checking your skills in CI is now three lines and
  needs no Python setup — the action fetches the tool itself:

  ```yaml
  - uses: gulmezeren2-byte/claude-skills-doctor@v1
    with:
      skills: ./skills
      strict: true
  ```

  Inputs: `skills`, `project`, `strict`, `budget`, `version`, `json`. With
  `json: true` the report comes back as a parseable `report` output while the step
  still fails the job on errors — the exit code stays the gate, the JSON is data.
- The action is dogfooded: CI runs it against the skill this repo ships, in both
  table and JSON modes, so a broken action fails the build rather than a user's.

## 0.4.1 — 2026-07-27

- **Fixed a crash on Windows when output is piped.** On Windows a piped stdout gets
  the legacy code page (cp1252 and friends), not UTF-8 — so the block character in the
  budget bar raised `UnicodeEncodeError` and took the whole run down. `skilldoctor | jq`
  or a CI log capture would just fail. Any non-ASCII in a finding hit the same wall: a
  skill named `ölçü`, or an em dash in a message. Output streams are now asked for UTF-8,
  and if a stream refuses, the report falls back to ASCII drawing characters rather than
  crashing. Found by installing the published build and piping it, which is the only way
  this shows up — running it straight to a terminal works fine.

## 0.4.0 — 2026-07-27

Now usable from *inside* Claude Code, and usable by skill authors.

- **`--skills PATH`** (repeatable): check a `skills/` directory you are authoring —
  a plugin repo's, say — instead of only the installed `~/.claude` and `.claude`
  locations. This is the flag skill and plugin authors need to lint what they ship
  before publishing it, in CI. Accepts either a skills root (`skills/<name>/SKILL.md`)
  or a single skill folder. Named directories are linted in full, since they're yours.
- **Ships as a Claude Code plugin.** `.claude-plugin/marketplace.json` +
  `.claude-plugin/plugin.json` and a `skilldoctor` skill, so the diagnosis is available
  where the problem actually appears: ask Claude why a skill isn't firing and it can
  check. The skill teaches the CLI, tells Claude to read the budget line first, and
  forbids editing skills the user didn't author without showing them the finding.
- **One entry, on purpose.** The plugin ships a single skill and no slash command —
  a tool that measures the discovery budget shouldn't take two slots out of it.
- Dogfood is enforced: CI runs `skilldoctor --skills ./skills --strict` against the
  skill this repo ships, and a test asserts it, so shipping a skill our own tool
  would flag fails the build.

## 0.3.0 — 2026-07-27

Hardening pass: an adversarial bug hunt against hostile-but-plausible skills found
three real defects, all fixed here, plus two silent false negatives.

**Fixed**

- **Crash on a YAML-truthy frontmatter key.** `on:` (also `yes:`, `no:`, `true:`)
  is read by YAML 1.1 as the *boolean* `True`, so the frontmatter mapping had a
  non-string key — rendering it raised `TypeError` and killed the whole run. Worse,
  under `--json` this printed a traceback and emitted **no JSON at all**, silently
  breaking any CI step parsing the output. Such keys are now rendered safely and
  reported as a new `yaml-truthy-key` warning that explains the footgun.
- **ReDoS in the security scanner.** The `curl … | sh` pattern had two quantifiers
  competing for the same run of whitespace and took **~9.6 s** on a hostile script
  (a skill could hang the very tool auditing it). Rewritten to be linear: the same
  input now takes ~13 ms, and detection is unchanged.
- **One bad skill could sink the whole report.** Each skill's checks are now
  isolated; an unexpected failure becomes an `internal-error` finding for that skill
  and the other skills still get their answer. `--json` now *always* emits valid
  JSON — even on catastrophic failure it returns `{"ok": false, "error": …}` rather
  than a traceback.

**New checks** (both were silently passing before)

- `empty-description` — a `description:` with nothing after it parses as `None`, so
  the key exists but Claude has nothing to route on and the skill can never trigger.
- `empty-name` — same shape for `name:`.

## 0.2.0 — 2026-07-23

- **Security signals** (new): scans every installed skill — including third-party
  plugins, because a dangerous plugin is exactly the case worth flagging — for two
  high-value smells, deterministically and without executing anything:
  `hidden-instruction` (instruction-override / hide-from-user / prompt-extraction
  phrases in the SKILL.md body or its reference files) and `script-network-call`
  (an outbound network call inside the skill's `scripts/`). A documentation-context
  filter keeps skills that *teach* prompt-injection safety from tripping it. This is
  the "you installed a skill — is it safe?" check the crowded skill-linters skip.
- **`--fix`**: shows a concrete suggested fix under each finding (fixes are also in
  `--json`). Covers budget-exceeded, name↔folder, human-docs, reference-chain, and
  the security findings.
- **`reference-chain`**: flags a `references/` file that links onward to another
  `.md`; the agent may preview nested files only partially and miss instructions.

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
