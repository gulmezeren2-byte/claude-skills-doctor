---
name: skilldoctor
description: Diagnose the Claude Code skills installed on this machine — why one never triggers, and whether Claude can see it at all. Use when the user says a skill isn't firing, isn't triggering, or is being ignored; asks to check, audit, or debug their skills; mentions the skill description budget, truncated skills, or duplicate skills; or asks whether a skill they installed is safe to trust. Runs a deterministic CLI over every installed skill at once, so it catches whole-system problems no single-file check can see.
license: MIT
---

# skilldoctor

A read-only, deterministic health check over every skill and slash-command Claude Code
loads. It answers the one question the agent cannot answer about itself: *is this skill
even visible to me?*

## Run it

```bash
uvx claude-skills-doctor                 # full check; exits non-zero if there are errors
uvx claude-skills-doctor --fix           # same, plus a concrete fix under each finding
uvx claude-skills-doctor budget          # the budget bar + the biggest descriptions to trim
uvx claude-skills-doctor --json          # machine-readable, for parsing
```

State check first: if `uvx` is missing, use `pip install claude-skills-doctor` and run
`skilldoctor` instead. The tool only reads files — it never edits a skill, and makes no
network or model calls, so it is always safe to run.

Useful flags: `--project PATH` checks a repo's `.claude/skills`; `--skills PATH` checks a
`skills/` directory you are authoring (a plugin repo); `--strict` fails on warnings too.

## The failure this exists for

Claude Code injects every skill and slash-command description into the system prompt
under one shared character budget (15,000 by default, `SLASH_COMMAND_TOOL_CHAR_BUDGET`).
Past it, some skills are **silently** left out of the prompt — no error, no warning — and
Claude is told not to use skills it wasn't shown. So the answer to "why doesn't my skill
trigger?" is often "Claude was never told it exists."

Check the budget line first. If it is over, that is the cause, and no amount of rewriting
the skill body will fix it.

## Reading the report

Findings carry a severity; only errors make the run exit non-zero.

| Finding | What it means |
|---|---|
| `budget-exceeded` | Over the shared budget — skills are being dropped silently. Trim descriptions. |
| `budget-near` | Within 20% of the cliff. One more skill may knock another one out. |
| `frontmatter-invalid` | Invalid YAML. The skill never loads at all. |
| `name-folder-mismatch` | `name` must equal the folder name. |
| `empty-description` | A bare `description:` parses as null — nothing to route on, so it can never trigger. |
| `description-collision` | Two skills describe themselves alike and compete; Claude can't pick reliably. |
| `duplicate-name` | Two skills share a `name`. Which one wins is order-dependent. |
| `hidden-instruction` | Instruction-override or hide-from-user phrasing in a skill's text. |
| `script-network-call` | A skill's script calls out to the network. |

## Fixing what it finds

1. Run it. Read the budget line before anything else.
2. If over or near budget, run `budget` to see the biggest contributors, then shorten
   those descriptions — keep *what* the skill does and *when* to use it, drop the rest.
3. Fix errors before warnings; `--fix` prints a concrete suggestion per finding.
4. Re-run to confirm the count actually dropped. Do not report it fixed without this.

Two rules when acting on the report:

- **Never edit a skill you did not author** without showing the user the finding first —
  that includes anything under `~/.claude/plugins`.
- Treat `hidden-instruction` and `script-network-call` as *read this file*, not as a
  verdict: they are pattern matches, not proof. Show the user the file and the line.

## What it does not do

It does not fix anything by itself, and it does not judge whether a skill is *good* — only
whether Claude can see it, load it, route to it, and whether it looks safe to trust. The
budget figure is each entry's name plus description: close and on the safe side, not
byte-exact.
