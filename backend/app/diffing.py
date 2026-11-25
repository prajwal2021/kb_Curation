"""Line diffs in the shape the UI renders (GitHub style)."""
from __future__ import annotations

import difflib
import re


def line_diff(old: str, new: str, context: int = 2, limit: int = 600) -> tuple[list[dict], int, int]:
    a, b = (old or "").splitlines(), (new or "").splitlines()
    out: list[dict] = []
    added = removed = 0
    for line in difflib.unified_diff(a, b, n=context, lineterm=""):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            out.append({"t": "@", "s": line})
        elif line.startswith("+"):
            added += 1
            out.append({"t": "+", "s": line[1:]})
        elif line.startswith("-"):
            removed += 1
            out.append({"t": "-", "s": line[1:]})
        else:
            out.append({"t": " ", "s": line[1:]})
    if len(out) > limit:
        out = out[:limit] + [{"t": "@", "s": f"… {len(out) - limit} more lines not shown"}]
    return out, added, removed


WORD_DIFF_CAP = 100_000   # token pairs one SequenceMatcher call may compare (~0.2 s at worst, ~150-word paragraphs)


def word_diff(old: str, new: str, limit: int = 4000) -> list[dict]:
    """Word-level diff as segments {"t": "=" | "-" | "+", "s": text}; past `limit` tokens the rest is one removal plus one addition."""
    a, b = (re.findall(r"\s+|\w+|[^\w\s]", x or "") for x in (old, new))
    out: list[dict] = []

    def put(t: str, s: str) -> None:
        if not s:
            return
        if out and out[-1]["t"] == t:
            out[-1]["s"] += s
        else:
            out.append({"t": t, "s": s})

    def ops(x: list, y: list) -> list:
        # shortcut: past WORD_DIFF_CAP pairs a block shows as one removal + one addition; SequenceMatcher can take
        # minutes on long texts with little in common. Raise the cap only with a faster diff.
        if len(x) * len(y) > WORD_DIFF_CAP:
            return [("replace", 0, len(x), 0, len(y))]
        return difflib.SequenceMatcher(None, x, y, autojunk=False).get_opcodes()

    def lines(toks: list[str]) -> list[list[str]]:
        out_, cur = [], []
        for t in toks:
            cur.append(t)
            if "\n" in t:
                out_.append(cur)
                cur = []
        return out_ + [cur] if cur else out_

    la, lb = lines(a[:limit]), lines(b[:limit])
    for op, i1, i2, j1, j2 in ops(["".join(x) for x in la], ["".join(x) for x in lb]):   # lines first, then words inside
        ta, tb = [t for x in la[i1:i2] for t in x], [t for x in lb[j1:j2] for t in x]
        if op == "equal":
            put("=", "".join(ta))
            continue
        for wop, k1, k2, m1, m2 in ops(ta, tb):
            if wop == "equal":
                put("=", "".join(ta[k1:k2]))
            else:
                put("-", "".join(ta[k1:k2]))
                put("+", "".join(tb[m1:m2]))
    put("-", "".join(a[limit:]))
    put("+", "".join(b[limit:]))
    return out


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a or "", b or "", autojunk=False).quick_ratio()
