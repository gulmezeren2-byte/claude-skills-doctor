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
from collections.abc import Callable

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
from skilldoctor.security import scan_security

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
# Taken from the frontmatter reference table at code.claude.com/docs/en/skills
# (re-checked 2026-07-31), plus the keys the agentskills.io standard and Anthropic's
# own bundled plugin skills use, which the Claude Code table does not list.
ALLOWED_FRONTMATTER = frozenset(
    {
        # documented in the Claude Code frontmatter table
        "name",
        "description",
        "when_to_use",
        "argument-hint",
        "arguments",
        "disable-model-invocation",
        "user-invocable",
        "allowed-tools",
        "disallowed-tools",
        "model",
        "effort",
        "context",
        "agent",
        "background",
        "hooks",
        "paths",
        "shell",
        # not in that table, but shipped by real skills in the wild
        "license",
        "metadata",
        "compatibility",
        "version",
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


def _is_text(value: object) -> bool:
    """True only for a non-blank string. YAML happily yields None/int/list where a
    string was meant (`description:` with nothing after it gives None)."""
    return isinstance(value, str) and bool(value.strip())


def _as_key(key: object) -> str:
    """Render a frontmatter key for display. YAML keys are not always strings."""
    return key if isinstance(key, str) else repr(key)


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
    elif not _is_text(fm.get("name")):
        out.append(
            Finding("empty-name", ERROR, t,
                    "`name` is present but empty (or not text) — the skill can't load", p,
                    suggestion=f"Set `name: {skill.folder_name}`.")
        )
    if "description" not in fm:
        out.append(
            Finding("missing-description", ERROR, t, "frontmatter has no `description`", p)
        )
    elif not _is_text(fm.get("description")):
        out.append(
            Finding("empty-description", ERROR, t,
                    "`description` is present but empty (or not text) — Claude has nothing "
                    "to route on, so the skill can never trigger", p,
                    suggestion="Describe what the skill does and when to use it.")
        )

    # YAML 1.1 reads bare on/off/yes/no/true/false as booleans, so `on:` becomes the
    # key True — a classic footgun that makes a key silently not the key you wrote.
    bool_keys = [k for k in fm if isinstance(k, bool)]
    if bool_keys:
        out.append(
            Finding("yaml-truthy-key", WARNING, t,
                    f"a frontmatter key parsed as the boolean {bool_keys[0]!r} — YAML reads "
                    "bare on/off/yes/no/true/false as booleans, not as key names", p,
                    suggestion='Quote the key, e.g. `"on":`, or rename it.')
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
                    suggestion=f"Set `name: {skill.folder_name}` or rename the folder.",
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

    # Keys are whatever YAML produced — they are not guaranteed to be strings
    # (`on:` becomes True, `1:` becomes 1), so render before sorting or joining.
    unexpected = {_as_key(k) for k in fm} - ALLOWED_FRONTMATTER
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
                        f"{doc} inside the skill folder — skills are for agents, not humans", p,
                        suggestion=f"Move {doc} out of the skill folder.")
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


# A markdown link that points at another .md file: "](something.md)" / "...md#anchor)".
_MD_LINK_RE = re.compile(r"\]\([^)]*\.md(?:[)#])")


def check_reference_chain(skill: Skill) -> list[Finding]:
    """references/ should stay one level deep. If a reference file links onward to
    another .md, the agent may preview it only partially and miss instructions."""
    refdir = skill.path.parent / "references"
    if not refdir.is_dir():
        return []
    for md in sorted(refdir.rglob("*.md")):
        try:
            if md.stat().st_size > 200_000:
                continue
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _MD_LINK_RE.search(text):
            return [
                Finding(
                    "reference-chain", WARNING, skill.name,
                    f"references/{md.name} links onward to another .md — keep references "
                    "one level deep so the agent doesn't miss nested instructions",
                    skill.path,
                    suggestion="Link deep files directly from SKILL.md, or inline the content.",
                )
            ]
    return []


# --------------------------------------------------------------------------- #
# system-wide budget check
# --------------------------------------------------------------------------- #
def check_description_cap(skill: Skill) -> list[Finding]:
    """The per-entry cap: exact, model-independent, and applied whatever the budget.

    Claude Code truncates one entry's combined `description` + `when_to_use` at 1,536
    characters in the listing. Nothing warns you. Everything past the cut is text
    Claude never sees when deciding whether this skill fits the request — and since
    an agent routes on the description rather than the body, losing the end of it is
    a behavioural change, not a cosmetic one.
    """
    text = skill.listing_text
    cap = _budget.PER_ENTRY_CAP
    if len(text) <= cap:
        return []
    over = len(text) - cap
    return [
        Finding(
            "description-capped", WARNING, skill.name,
            f"description{' + when_to_use' if skill.when_to_use else ''} is "
            f"{len(text)} chars — the listing truncates each entry at {cap}, so the "
            f"last {over} chars never reach Claude.",
            suggestion="Put the matching keywords first and move the detail into the "
            "skill body, which loads only when the skill runs and costs nothing here.",
        )
    ]


def check_budget(
    skills: list[Skill], commands: list[SlashCommand], limit: _budget.Budget | int
) -> list[Finding]:
    """The listing-wide budget.

    Stated carefully, because describing this failure wrongly teaches the wrong fix:
    the listing always keeps every skill *name*. What overflow drops is the
    *description*, starting with the skills you invoke least — so a rarely-used skill
    silently becomes a name with nothing for Claude to match on.
    """
    budget = limit if isinstance(limit, _budget.Budget) else _budget.Budget(
        int(limit), "caller", exact=True
    )
    used = _budget.total_discovery_cost(skills, commands)
    # an estimated limit should not be quoted as though it were measured
    how = f"{budget.chars}" if budget.exact else f"~{budget.chars} ({budget.source})"

    if used > budget.chars:
        over = used - budget.chars
        return [
            Finding(
                "budget-exceeded", ERROR, "budget",
                f"skills + commands use ~{used} listing chars against {how} — over by "
                f"{over}. Names still list, but Claude Code drops descriptions to fit, "
                "starting with the skills you invoke least, and does not warn in normal "
                "use.",
                suggestion="Run `skilldoctor budget` for the biggest contributors, trim "
                f"~{over} chars, set low-priority entries to \"name-only\" in "
                "skillOverrides, or raise skillListingBudgetFraction.",
            )
        ]
    if used >= budget.chars * _budget.WARN_RATIO:
        return [
            Finding(
                "budget-near", WARNING, "budget",
                f"skills + commands use ~{used} listing chars against {how} "
                f"({int(used / budget.chars * 100)}%) — nearing the point where "
                "descriptions start being dropped.",
            )
        ]
    return []


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def _safe(
    skill: Skill, fn: Callable[..., list[Finding]], *args: object
) -> list[Finding]:
    """Run one check over one skill, converting an unexpected failure into a finding.

    One odd skill on disk must never take down the whole report — the other 30 skills
    still deserve their answer, and a traceback would also break the `--json` contract.
    """
    try:
        return fn(skill, *args)
    except Exception as exc:  # noqa: BLE001 - deliberate last-resort guard
        return [
            Finding(
                "internal-error", WARNING, skill.name,
                f"skilldoctor could not finish checking this skill: "
                f"{type(exc).__name__}: {exc}",
                skill.path,
                suggestion="Please report this at "
                "https://github.com/gulmezeren2-byte/claude-skills-doctor/issues",
            )
        ]


def check_all(
    skills: list[Skill],
    commands: list[SlashCommand],
    limit: _budget.Budget | int,
    include_info: bool = True,
) -> Report:
    findings: list[Finding] = []
    for s in skills:
        full = s.source != SOURCE_PLUGIN
        findings.extend(_safe(s, check_skill, full))
        # security signals run on every skill — a dangerous third-party skill is
        # exactly the case worth flagging.
        findings.extend(_safe(s, scan_security))
        # the per-entry cap applies to every listed skill, plugin or not: a plugin
        # skill whose description is cut still costs you a skill Claude can't match
        findings.extend(_safe(s, check_description_cap))
        if full:
            findings.extend(_safe(s, check_reference_chain))
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
        budget_limit=int(limit),
        budget_source=limit.source if isinstance(limit, _budget.Budget) else "",
        budget_exact=limit.exact if isinstance(limit, _budget.Budget) else True,
    )
