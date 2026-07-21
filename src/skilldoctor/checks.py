"""The deterministic checks — no model calls, no network, no guessing.

Every check answers one question a Claude Code user actually hits: *will Claude
see this skill, load the right one, and be able to follow it?* Checks come in three
kinds:

  * per-skill validity (a superset of Anthropic's single-skill quick_validate,
    applied across every installed skill),
  * cross-skill (duplicate names, colliding descriptions) — things a single-skill
    validator structurally cannot see,
  * the system-wide discovery budget.

Findings carry a severity; only errors make the report `not ok`. The bias is the
one carried from the author's other tools: surface it, never invent it.
"""

from __future__ import annotations

import re
from collections import defaultdict

from skilldoctor import budget as _budget
from skilldoctor.model import (
    ERROR,
    INFO,
    SOURCE_PLUGIN,
    WARNING,
    Finding,
    Report,
    Skill,
    SlashCommand,
)

# --- spec limits (from the Agent Skills spec / Anthropic quick_validate) ---
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500

# --- skilldoctor heuristics (tunable, documented as estimates) ---
DESCRIPTION_MIN_USEFUL = 40  # shorter than this rarely routes reliably
BODY_LARGE_CHARS = 20000  # ~5k tokens: past the Level-2 activation guidance
COLLISION_THRESHOLD = 0.6  # token-set overlap at/above this = likely routing clash

_NAME_RE = re.compile(r"^[a-z0-9-]+$")
# Frontmatter keys seen in real, valid skills — including Anthropic's own official
# plugin skills, which use `version`, `argument-hint`, and `model`. Kept generous
# on purpose: the frontmatter schema is extensible, so an unknown key is a mild
# smell (possible typo), not a spec violation.
ALLOWED_FRONTMATTER = frozenset(
    {
        "name",
        "description",
        "license",
        "allowed-tools",
        "metadata",
        "compatibility",
        "disable-model-invocation",
        "version",
        "argument-hint",
        "model",
        "user-invocable",
    }
)
# The standard Claude Code tools, for the allowed-tools-vs-body contract check.
KNOWN_TOOLS = frozenset(
    {
        "Bash", "Read", "Write", "Edit", "Glob", "Grep", "Task",
        "WebFetch", "WebSearch", "NotebookEdit", "TodoWrite", "Skill",
    }
)
# A description that reads like a numbered/sequential how-to (body-skip antipattern).
_WORKFLOW_RE = re.compile(r"(step\s*\d|\b1\.\s|\bfirst,.*\bthen\b)", re.I)
# Absolute-path shapes that hurt portability.
_ABS_PATH_RE = re.compile(r"(^|[\s(`\"'])(/(Users|home|root|opt|var|etc)/|[A-Za-z]:\\)")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------- #
# per-skill checks
# --------------------------------------------------------------------------- #
def check_skill(skill: Skill, full: bool = True) -> list[Finding]:
    """Check one skill. `full` runs the quality/hygiene/naming lint; when False
    (third-party plugin skills the user can't fix), only the load-breaking checks
    run — the ones that affect the user regardless of who authored the skill."""
    out: list[Finding] = []
    t, p = skill.name, skill.path

    # A skill that can't be parsed never loads — the loudest silent failure.
    if skill.yaml_error is not None:
        out.append(Finding("frontmatter-invalid", ERROR, t, skill.yaml_error, p))
        return out  # nothing else is trustworthy once frontmatter is broken

    fm = skill.frontmatter
    if "name" not in fm:
        out.append(Finding("missing-name", ERROR, t, "frontmatter has no `name`", p))
    if "description" not in fm:
        out.append(
            Finding("missing-description", ERROR, t, "frontmatter has no `description`", p)
        )

    if not full:
        return out  # plugin skills: stop after the load-breakers

    name = fm.get("name")
    if isinstance(name, str) and name.strip():
        n = name.strip()
        if n != skill.folder_name:
            out.append(
                Finding(
                    "name-folder-mismatch", ERROR, t,
                    f"`name: {n}` must match the folder name `{skill.folder_name}`", p,
                )
            )
        if not _NAME_RE.match(n):
            out.append(
                Finding("name-format", ERROR, t,
                        f"`name` must be kebab-case (a-z, 0-9, -): {n!r}", p)
            )
        elif n.startswith("-") or n.endswith("-") or "--" in n:
            out.append(
                Finding("name-format", ERROR, t,
                        f"`name` cannot start/end with '-' or contain '--': {n!r}", p)
            )
        if len(n) > NAME_MAX:
            out.append(
                Finding("name-format", ERROR, t,
                        f"`name` is {len(n)} chars; max is {NAME_MAX}", p)
            )

    desc = fm.get("description")
    if isinstance(desc, str):
        d = desc.strip()
        if "<" in d or ">" in d:
            out.append(
                Finding("description-angle-brackets", ERROR, t,
                        "`description` must not contain '<' or '>' (prompt-injection risk)", p)
            )
        if len(d) > DESCRIPTION_MAX:
            out.append(
                Finding("description-too-long", ERROR, t,
                        f"`description` is {len(d)} chars; max is {DESCRIPTION_MAX}", p)
            )
        if 0 < len(d) < DESCRIPTION_MIN_USEFUL:
            out.append(
                Finding("description-vague", WARNING, t,
                        f"`description` is only {len(d)} chars — too thin to route reliably", p)
            )
        if _WORKFLOW_RE.search(d):
            out.append(
                Finding("description-is-workflow", WARNING, t,
                        "`description` reads like a step list; describe what/when, not how "
                        "(a how-to description makes Claude skip loading the body)", p)
            )

    compat = fm.get("compatibility")
    if isinstance(compat, str) and len(compat) > COMPATIBILITY_MAX:
        out.append(
            Finding("compatibility-too-long", WARNING, t,
                    f"`compatibility` is {len(compat)} chars; max is {COMPATIBILITY_MAX}", p)
        )

    unexpected = set(fm.keys()) - ALLOWED_FRONTMATTER
    if unexpected:
        keys = ", ".join(sorted(unexpected))
        out.append(
            Finding("unexpected-frontmatter-key", INFO, t,
                    f"frontmatter key(s) skilldoctor doesn't recognise: {keys} "
                    "(fine if intentional; check for a typo)", p)
        )

    # body hygiene
    if not skill.body.strip():
        out.append(
            Finding("body-empty", WARNING, t, "SKILL.md body has no instructions", p)
        )
    elif len(skill.body) > BODY_LARGE_CHARS:
        body_len = len(skill.body)
        out.append(
            Finding("body-too-large", WARNING, t,
                    f"SKILL.md body is {body_len} chars — move detail into references/", p)
        )

    m = _ABS_PATH_RE.search(skill.body)
    if m:
        out.append(
            Finding("absolute-path", WARNING, t,
                    "body contains an absolute path — use relative paths for portability", p)
        )

    out.extend(_check_allowed_tools(skill))

    # human-facing docs don't belong inside a skill folder
    for doc in ("README.md", "CHANGELOG.md", "INSTALL.md", "INSTALLATION.md"):
        if (skill.path.parent / doc).exists():
            out.append(
                Finding("human-docs", WARNING, t,
                        f"{doc} inside the skill folder — skills are for agents, not humans", p)
            )
    return out


def _check_allowed_tools(skill: Skill) -> list[Finding]:
    """If `allowed-tools` is declared, flag well-known tools used in the body but
    not allowed — the documented 'listed Read/Write but called Bash' contract slip.
    Conservative: only the standard tool names, only when allowed-tools is a list."""
    allowed = skill.frontmatter.get("allowed-tools")
    if not isinstance(allowed, list) or not allowed:
        return []
    allowed_set = {str(a).strip() for a in allowed}
    used = {tool for tool in KNOWN_TOOLS if re.search(rf"\b{tool}\b", skill.body)}
    missing = sorted(used - allowed_set)
    if not missing:
        return []
    return [
        Finding(
            "allowed-tools-body", WARNING, skill.name,
            f"body uses {', '.join(missing)} but `allowed-tools` doesn't list them",
            skill.path,
        )
    ]


# --------------------------------------------------------------------------- #
# cross-skill checks
# --------------------------------------------------------------------------- #
def check_duplicates(skills: list[Skill]) -> list[Finding]:
    """Two skills with the same `name` — an ambiguous, order-dependent clash."""
    by_name: dict[str, list[Skill]] = defaultdict(list)
    for s in skills:
        n = s.frontmatter.get("name")
        if isinstance(n, str) and n.strip():
            by_name[n.strip()].append(s)
    out: list[Finding] = []
    for name, group in sorted(by_name.items()):
        if len(group) > 1:
            where = ", ".join(sorted(f"{s.source}:{s.folder_name}" for s in group))
            out.append(
                Finding("duplicate-name", ERROR, name,
                        f"{len(group)} skills share `name: {name}` ({where})", group[0].path)
            )
    return out


def check_collisions(skills: list[Skill]) -> list[Finding]:
    """Near-identical descriptions route ambiguously — the agent may load the
    wrong one. Reported once per pair, worst overlap first."""
    scored = [(s, _tokens(s.description)) for s in skills if s.description.strip()]
    out: list[Finding] = []
    for i in range(len(scored)):
        for j in range(i + 1, len(scored)):
            sim = _jaccard(scored[i][1], scored[j][1])
            if sim >= COLLISION_THRESHOLD:
                a, b = scored[i][0], scored[j][0]
                out.append(
                    Finding(
                        "description-collision", WARNING, a.name,
                        f"description ~{int(sim * 100)}% overlaps `{b.name}` — "
                        "they may compete to trigger; differentiate them",
                        a.path,
                    )
                )
    return out


# --------------------------------------------------------------------------- #
# system-wide budget check
# --------------------------------------------------------------------------- #
def check_budget(
    skills: list[Skill], commands: list[SlashCommand], limit: int
) -> list[Finding]:
    used = _budget.total_discovery_cost(skills, commands)
    if used > limit:
        over = used - limit
        return [
            Finding(
                "budget-exceeded", ERROR, "budget",
                f"skills + commands use ~{used}/{limit} discovery chars — over by {over}. "
                "Claude Code silently stops listing some skills (no warning). "
                "Trim descriptions or raise SLASH_COMMAND_TOOL_CHAR_BUDGET.",
            )
        ]
    if used >= limit * _budget.WARN_RATIO:
        return [
            Finding(
                "budget-near", WARNING, "budget",
                f"skills + commands use ~{used}/{limit} discovery chars "
                f"({int(used / limit * 100)}%) — nearing the silent-truncation cliff.",
            )
        ]
    return []


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def check_all(
    skills: list[Skill],
    commands: list[SlashCommand],
    limit: int,
    include_info: bool = True,
) -> Report:
    findings: list[Finding] = []
    for s in skills:
        findings.extend(check_skill(s, full=(s.source != SOURCE_PLUGIN)))
    findings.extend(check_duplicates(skills))
    # Routing collisions are only actionable among the user's own skills.
    findings.extend(check_collisions([s for s in skills if s.source != SOURCE_PLUGIN]))
    findings.extend(check_budget(skills, commands, limit))
    if not include_info:
        findings = [f for f in findings if f.severity != INFO]
    return Report(
        findings=findings,
        skills_scanned=len(skills),
        commands_scanned=len(commands),
        budget_used=_budget.total_discovery_cost(skills, commands),
        budget_limit=limit,
    )
