"""Light, deterministic security signals for installed skills.

A skill is markdown plus optional scripts, and it can steer the agent or run code.
A malicious or careless third-party skill is a real risk (the "install a skill,
get a hidden instruction or a phone-home script" problem). This module surfaces the
two cheapest, highest-signal smells — no model, no network, no execution:

  * hidden-instruction — instruction-override / hide-from-user / prompt-extraction
    phrases in the SKILL.md body or its reference files;
  * script-network-call — an outbound network call inside the skill's scripts/.

These run on *every* skill regardless of source, because a dangerous plugin skill
is exactly the case the user most needs flagged. Signals, not proof: a hit means
"read this skill before trusting it", which is the honest thing to say.
"""

from __future__ import annotations

import re
from pathlib import Path

from skilldoctor.model import WARNING, Finding, Skill

_MAX_BYTES = 200_000  # don't slurp huge files
_MAX_FILES = 60  # per skill, per scan kind

# Instruction-manipulation phrases that almost never appear in a benign skill.
_HIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+instructions",
     "instruction override"),
    (r"disregard\s+(the\s+|all\s+|your\s+)?(previous|above|prior|instructions)",
     "instruction override"),
    (r"do\s+not\s+(tell|inform|mention\s+(this\s+)?to|alert|notify)\s+the\s+user",
     "hide from the user"),
    (r"without\s+(telling|informing|alerting|notifying)\s+the\s+user",
     "hide from the user"),
    (r"reveal\s+(your\s+)?(system\s+)?(prompt|instructions)", "prompt extraction"),
    (r"print\s+(your\s+)?(system\s+)?(prompt|instructions)", "prompt extraction"),
    (r"exfiltrat", "data exfiltration"),
]

# Outbound network / remote-exec patterns inside scripts.
_NETWORK_PATTERNS: list[tuple[str, str]] = [
    (r"curl\s+[^\n|]*\|\s*(ba)?sh", "pipes a remote script straight into a shell"),
    (r"\bcurl\s+-[a-zA-Z]*\s*https?://", "curl to a remote URL"),
    (r"\bcurl\s+https?://", "curl to a remote URL"),
    (r"\bwget\s+https?://", "wget from a remote URL"),
    (r"requests\.(get|post|put|patch|delete)\s*\(", "an HTTP request (python-requests)"),
    (r"urllib\.request", "an HTTP request (urllib)"),
    (r"http\.client\.", "an HTTP request (http.client)"),
    (r"fetch\s*\(\s*[\"'`]https?://", "a fetch() to a remote URL"),
    (r"new\s+XMLHttpRequest", "an XMLHttpRequest"),
    (r"axios\.(get|post|put|delete)", "an HTTP request (axios)"),
]

_SCRIPT_SUFFIXES = {".py", ".sh", ".bash", ".js", ".mjs", ".ts", ".rb", ".ps1"}


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _files(folder: Path, suffixes: set[str] | None) -> list[Path]:
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and (suffixes is None or p.suffix.lower() in suffixes):
            out.append(p)
        if len(out) >= _MAX_FILES:
            break
    return out


# Words that mark a phrase as being *discussed* (documentation about injection)
# rather than *issued* as a live directive — so a skill that teaches prompt-injection
# safety doesn't trip the scanner.
_DOC_MARKERS = re.compile(
    r"example|e\.g\.|such as|watch for|avoid|don'?t|never|malicious|"
    r"injection|attack|phrase|contain",
    re.IGNORECASE,
)


def _looks_like_docs(text: str, pos: int) -> bool:
    """True when the match sits on a documentation-ish line (markers, or the phrase
    is quoted/cited rather than issued). A cheap way to cut the biggest false
    positive: skills that explain prompt injection."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    line = text[start:] if end == -1 else text[start:end]
    if _DOC_MARKERS.search(line):
        return True
    before = line[: pos - start]
    return before.rstrip().endswith(('"', "'", "`", "("))


def scan_security(skill: Skill) -> list[Finding]:
    out: list[Finding] = []
    root = skill.path.parent

    # 1) hidden instructions in the body + reference files
    sources: list[tuple[str, str]] = [("SKILL.md", skill.body)]
    for ref in _files(root / "references", {".md", ".markdown", ".txt"}):
        text = _read(ref)
        if text is not None:
            sources.append((f"references/{ref.name}", text))
    for where, text in sources:
        for pattern, label in _HIDDEN_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m and not _looks_like_docs(text, m.start()):
                out.append(
                    Finding(
                        "hidden-instruction", WARNING, skill.name,
                        f"{where}: possible {label} phrase — read before trusting this skill",
                        skill.path,
                        suggestion="Open the file and confirm it's benign.",
                    )
                )
                break  # one finding per source is enough to prompt a look

    # 2) outbound network calls inside scripts/
    for script in _files(root / "scripts", _SCRIPT_SUFFIXES):
        text = _read(script)
        if text is None:
            continue
        for pattern, label in _NETWORK_PATTERNS:
            if re.search(pattern, text):
                out.append(
                    Finding(
                        "script-network-call", WARNING, skill.name,
                        f"scripts/{script.name} makes {label} — worth a look",
                        script,
                        suggestion="Audit the script; confirm the call is expected.",
                    )
                )
                break

    return out
