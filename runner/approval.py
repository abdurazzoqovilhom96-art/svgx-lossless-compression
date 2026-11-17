"""Authorization gate for the real study.

A decision is recorded only from a genuine reply (chat relay via `study.py approve --reply ...` or
the interactive terminal prompt); both use `record_decision`. A decision binds the design ID and the
SHA-256 of the frozen state (protocol, configs, manifests, build). Flags, environment variables,
other projects' approvals and examples never count as a decision.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from .common import ROOT, STATE, atomic_write_json, canonical_json, read_json, say, sha256_bytes, sha256_file, utc_now

APPROVAL_FILE = "approval.json"
FREEZE_FILE = "freeze.json"
SCOPES = ("pilot", "full")
QUESTION_UZ = ("Haqiqiy SVG fayllarida tajribani boshlashga ruxsat berasizmi? "
               "To'liq tadqiqot (pilot + mustaqil tasdiqlash + yakuniy hisobotlar) yoki faqat pilot?")


class GateError(RuntimeError):
    """Real dispatch is not authorized."""


def live_state() -> Path:
    return STATE


def freeze_hash(freeze: dict) -> str:
    return sha256_bytes(canonical_json(freeze).encode("utf-8"))


def load_freeze(state_dir: Path) -> dict | None:
    return read_json(Path(state_dir) / FREEZE_FILE)


def current_bindings(freeze: dict, root: Path = ROOT) -> dict:
    """Recompute the hashes of every file bound by the freeze."""
    out = {}
    for rel in sorted(freeze.get("bound_files", {})):
        p = Path(root) / rel
        out[rel] = sha256_file(p) if p.exists() else None
    return out


def binding_mismatches(freeze: dict, root: Path = ROOT) -> list[str]:
    cur = current_bindings(freeze, root)
    return [k for k, v in freeze.get("bound_files", {}).items() if cur.get(k) != v]


_NEG = re.compile(r"\b(yo'?q|yoq|yo‘q|yo`q|rad|bekor|kerak\s+emas|ruxsat\s+bermayman|to'xtat|no|stop|decline)\b", re.I)
_POS = re.compile(r"\b(ha|xa|mayli|roziman|rozi|ruxsat\s+beraman|ruxsat\s+berildi|boshla\w*|davom\s+et\w*|yes|ok|okay|approve\w*|tasdiqlayman)\b", re.I)
_PILOT = re.compile(r"\b(faqat\s+pilot|pilot\s+only|only\s+pilot|faqat\s+pilotni|pilotni\s+o'?zi|pilot)\b", re.I)
_FULL = re.compile(r"\b(to'?liq|to‘liq|toliq|full|hammasi|butun)\b", re.I)


def parse_reply(text: str | None) -> tuple[str | None, str | None]:
    """Map a free-text reply to (decision, scope). Empty or unclear replies give (None, None)."""
    t = (text or "").strip()
    if not t:
        return None, None
    norm = t.replace("’", "'").replace("ʻ", "'").replace("‘", "'").replace("`", "'")
    neg = bool(_NEG.search(norm))
    pos = bool(_POS.search(norm)) or bool(_PILOT.search(norm)) or bool(_FULL.search(norm))
    if neg and not pos:
        return "decline", None
    if pos and not neg:
        if _PILOT.search(norm) and not _FULL.search(norm):
            return "approve", "pilot"
        return "approve", "full"
    return None, None


def record_decision(state_dir: Path, *, decision: str, scope: str | None, source: str, reply_text: str,
                    freeze: dict, test_mode: bool = False) -> dict:
    """The single internal decision operation (chat relay and terminal prompt)."""
    state_dir = Path(state_dir).resolve()
    if test_mode and state_dir == live_state().resolve():
        raise GateError("test/demo approval must never be written into live state")
    if decision not in ("approve", "decline"):
        raise GateError("noma'lum qaror")
    if decision == "approve" and scope not in SCOPES:
        raise GateError("ruxsat doirasi aniqlanmadi")
    rec = {
        "design_id": freeze["design_id"],
        "decision": decision,
        "scope": scope if decision == "approve" else None,
        "source": source,
        "reply_text": reply_text,
        "recorded_utc": utc_now(),
        "freeze_sha256": freeze_hash(freeze),
        "bound_files": dict(freeze.get("bound_files", {})),
        "test_mode": bool(test_mode),
    }
    atomic_write_json(state_dir / APPROVAL_FILE, rec)
    return rec


def load_decision(state_dir: Path) -> dict | None:
    return read_json(Path(state_dir) / APPROVAL_FILE)


def check(state_dir: Path, freeze: dict | None, split: str | None = None, root: Path = ROOT) -> tuple[bool, str, dict | None]:
    """Is a real launch for `split` authorized right now? Returns (ok, reason_uz, decision)."""
    if freeze is None:
        return False, "muzlatilgan holat (state/freeze.json) yo'q — avval prepare bajaring", None
    rec = load_decision(state_dir)
    if rec is None:
        return False, "ruxsat hali berilmagan (qaror yozilmagan)", None
    if rec.get("design_id") != freeze.get("design_id"):
        return False, "qaror boshqa dizayn uchun yozilgan", rec
    if rec.get("freeze_sha256") != freeze_hash(freeze):
        return False, "qaror muzlatilgan holat xeshiga mos emas", rec
    mism = binding_mismatches(freeze, root)
    if mism:
        return False, "muzlatilgan fayllar o'zgargan: " + ", ".join(mism[:5]), rec
    if rec.get("test_mode") and Path(state_dir).resolve() == live_state().resolve():
        return False, "jonli holatda test qarori bor — haqiqiy qaror emas", rec
    if rec.get("decision") != "approve":
        return False, "foydalanuvchi rad etgan", rec
    allowed = {"pilot": {"pilot"}, "full": {"pilot", "confirmation"}}[rec["scope"]]
    if split is not None and split not in allowed:
        return False, f"'{split}' bosqichi ruxsat doirasiga ({rec['scope']}) kirmaydi", rec
    return True, "ok", rec


def interactive_prompt(state_dir: Path, freeze: dict, summary_uz: str, input_fn=input) -> dict | None:
    """Show the Uzbek readiness summary and ask once; records the reply (terminal source)."""
    say(summary_uz)
    say("")
    say(QUESTION_UZ)
    try:
        reply = input_fn("Javobingiz (ha / faqat pilot / yo'q): ")
    except EOFError:
        reply = ""
    decision, scope = parse_reply(reply)
    if decision is None:
        say("Javob aniq emas yoki bo'sh — hech narsa ishga tushirilmadi.")
        return None
    return record_decision(state_dir, decision=decision, scope=scope, source="terminal", reply_text=reply,
                           freeze=freeze)


def is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty() and not os.environ.get("CI")
    except (AttributeError, ValueError):
        return False
