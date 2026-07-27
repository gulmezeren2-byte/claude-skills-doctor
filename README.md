# claude-skills-doctor

**A doctor for your Claude Code agent skills — find the ones Claude silently can't see, before they cost you a session.**

> Install `claude-skills-doctor`, run `skilldoctor`.

You install a skill, it looks perfect, and Claude never uses it. No error, no warning. As of Claude Code 2.0.70 the combined skill + slash-command descriptions injected into the system prompt live under a **15,000-character budget** (~4,000 tokens, set by `SLASH_COMMAND_TOOL_CHAR_BUDGET`). Go over and Claude Code **just stops listing some skills** — and Claude is told not to use skills it wasn't told about. The failure is invisible from the inside. `skilldoctor` makes it visible.

```
$ skilldoctor
Discovery budget
████████████████████████████░░░░  13,120 / 15,000 chars (87%)

 severity   check                  target            detail
 error      name-folder-mismatch   pdf-tools         `name: pdf` must match the folder name `pdf-tools`
 error      frontmatter-invalid    my-skill          invalid YAML in frontmatter: mapping values are not allowed here
 warn       description-collision  review-code       description ~72% overlaps `code-review` — they may compete to trigger
 warn       budget-near            budget            skills + commands use ~13,120/15,000 discovery chars (87%) — nearing the silent-truncation cliff.

28 skill(s) · 6 command(s) · 2 error(s) · 2 warning(s)
```

## Install

```
uvx claude-skills-doctor            # run without installing
pip install claude-skills-doctor    # or install it
```

Then run `skilldoctor` (the command `claude-skills-doctor` works too).

## Use

```
skilldoctor                 # health-check every skill Claude Code can see; exits non-zero on errors
skilldoctor --fix           # show a concrete suggested fix for each finding
skilldoctor --json          # machine-readable, for CI
skilldoctor --strict        # fail on warnings too
skilldoctor budget          # the shareable view: the bar + the biggest contributors to trim
```

It scans everywhere Claude Code loads from — your user skills (`~/.claude/skills`), the project's (`.claude/skills`), and installed plugins — plus slash-commands, which share the same budget.

## Or ask Claude

It also ships as a Claude Code plugin, so the diagnosis lives where the problem shows up — you notice a skill isn't firing, you ask, and Claude checks:

```
/plugin marketplace add gulmezeren2-byte/claude-skills-doctor
/plugin install skilldoctor@skilldoctor
```

The plugin ships **one** skill and no slash command. A tool that measures the discovery budget shouldn't take two slots out of it.

## Authoring skills? Lint what you ship

`--skills` points at a `skills/` directory you're writing, so you can catch problems before publishing rather than after someone installs them:

```
skilldoctor --skills ./skills --strict        # fails on warnings too — good CI gate
```

This repo does exactly that to itself: CI runs `skilldoctor --skills ./skills --strict` against the skill it ships, and a test asserts it. If our own tool would flag our own skill, the build fails.

## What it checks

All deterministic. **No model calls, no network, no guessing** — it reads your files and reports.

- **Discovery budget** — the headline. Total skill + command description characters vs the 15,000 limit (honours `SLASH_COMMAND_TOOL_CHAR_BUDGET`). Over budget → some skills are silently unlisted.
- **Won't load** — invalid YAML frontmatter (which *silently* prevents loading), missing `name`/`description`, and `name` that doesn't match its folder (required, and the one Anthropic's own validator misses).
- **Won't route** — descriptions too thin to trigger, and descriptions written as a step-by-step how-to (which makes Claude follow the summary and skip loading the body).
- **Collisions** — two skills with the same `name`, or near-identical descriptions that compete to trigger.
- **Contract & hygiene** — `allowed-tools` that doesn't cover the tools the body actually uses, `<`/`>` in descriptions (prompt-injection risk), oversized bodies that belong in `references/`, reference chains more than one level deep, absolute paths, and human-facing docs (README/CHANGELOG) left inside a skill folder.
- **Security** — scans *every* skill (third-party plugins included) for `hidden-instruction` phrases (instruction-override / hide-from-user / prompt-extraction) in the SKILL.md and its references, and `script-network-call`s inside `scripts/`. Because "I installed a skill — is it safe?" is a real question, and a documentation-context filter keeps skills that *teach* prompt-injection safety from tripping it.

Errors make it exit non-zero, so it gates a pipeline: `skilldoctor && claude ...`. Add `--fix` to see a concrete suggested fix under each finding.

## How it's different from a skill linter

There are per-file `SKILL.md` linters and validators (and Anthropic's `skill-creator` model-evaluates **one** skill you're authoring). `claude-skills-doctor` is the complement: a **whole-system, install-time** health check across **every** skill you actually have — and the only one that measures the **cross-skill** failures a single-file linter structurally can't see: the shared discovery budget, duplicate names, and colliding descriptions. A linter checks a file; a doctor examines the whole patient.

## Honest about the numbers

The budget is measured as each skill/command's `name` + `description` characters. That's an estimate — the real budget adds minor per-entry formatting — so treat it as *close, and on the safe side*, not byte-exact. It lints *your own* skills fully; third-party plugin skills count toward the budget but are checked only for load-breakers, so it never nags about skills you can't fix. Every finding points at a file and a reason; nothing is invented.

## License

MIT
