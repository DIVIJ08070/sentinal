r"""SENTINEL plate arbiter — the "king".

A deterministic, grammar-aware decision engine that reconciles the many OCR
reads of one vehicle (across frames and/or preprocessing variants) into a
single plate, with an explainable rationale. It does not merely count votes:
it knows the Indian registration grammar and resolves each character in the
light of what that *position* must be.

Indian plate grammar:  [A-Z]{2} \d{1,2} [A-Z]{1,3} \d{4}
                        state     rto     series     number

Decision, per character position:
  1. the position's expected TYPE (letter or digit) is decided by weighted
     majority across candidates;
  2. every candidate character is coerced toward that type through the
     OCR-confusion map (digit<->letter twins) before it votes;
  3. votes are weighted by  OCR confidence (dynamic)  x  source reliability
     (static prior per engine/method);
  4. the winning character per position forms the plate; a syntax check marks
     whether the result is a well-formed registration.

Pure-Python, no dependencies, microseconds per vehicle — runs on every camera
at scale. Returns the plate plus a rationale and an aggregate confidence that
feed TrustTrace.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

# Letter<->digit confusion twins (both directions); used to coerce a character
# toward the type its position requires.
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
             "E": "3", "A": "4", "S": "5", "G": "6", "T": "7", "B": "8", "P": "8"}
_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G",
              "7": "T", "8": "B"}

_INDIAN = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{3,4}$")
# Bharat (BH) series: YY BH #### X(X).  Diplomatic: nnn CD/CC/UN nnnn.
_BH = re.compile(r"^\d{2}BH\d{4}[A-Z]{1,2}$")
_DIPLO = re.compile(r"^\d{1,3}(?:CD|CC|UN)\d{1,4}$")

# Valid Indian RTO state/UT codes — lets the king rule out an impossible state
# code (e.g. a 'GI' misread of 'GJ') instead of trusting the OCR blindly.
VALID_STATES = {
    "AP", "AR", "AS", "BR", "CG", "GA", "GJ", "HR", "HP", "JH", "JK", "KA",
    "KL", "MP", "MH", "MN", "ML", "MZ", "NL", "OD", "OR", "PB", "RJ", "SK",
    "TN", "TS", "TR", "UP", "UK", "UA", "WB", "AN", "CH", "DD", "DL", "DN",
    "LD", "PY", "LA",
}


def classify(p):
    """Which plate grammar a string fits."""
    if not p:
        return "empty"
    if _BH.match(p):
        return "bh-series"
    if _DIPLO.match(p):
        return "diplomatic"
    if _INDIAN.match(p):
        return "standard" if p[:2] in VALID_STATES else "standard-badstate"
    return "nonstandard"


def _clean(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _coerce(ch: str, want: str) -> str:
    """Coerce a character toward the wanted type ('D' digit / 'L' letter)."""
    if want == "D":
        return ch if ch.isdigit() else _TO_DIGIT.get(ch, ch)
    return ch if ch.isalpha() else _TO_LETTER.get(ch, ch)


def arbitrate(reads, engine_priors=None):
    """reads: iterable of (plate_string, confidence[, source]).
    Returns {plate, confidence, well_formed, support, rationale, candidates}.
    """
    priors = engine_priors or {}
    cands = []
    for r in reads:
        s = _clean(r[0])
        c = float(r[1]) if len(r) > 1 and r[1] is not None else 0.5
        src = r[2] if len(r) > 2 else "ocr"
        if s:
            cands.append((s, c, src))
    if not cands:
        return {"plate": None, "confidence": 0.0, "well_formed": False,
                "support": 0, "rationale": ["no reads"], "candidates": 0}

    # 0. special formats: if the reads are dominantly a BH-series or diplomatic
    # plate, do NOT force the standard grammar — those have their own structure.
    fmt_w = defaultdict(float)
    for s, c, src in cands:
        fmt_w[classify(s)] += c * priors.get(src, 1.0)
    dom_fmt = max(fmt_w, key=fmt_w.get)
    if dom_fmt in ("bh-series", "diplomatic"):
        sv = defaultdict(float)
        for s, c, src in cands:
            sv[s] += c * priors.get(src, 1.0)
        best = max(sv, key=sv.get)
        return {
            "plate": best, "confidence": round(sv[best] / sum(sv.values()), 3),
            "well_formed": classify(best) in ("bh-series", "diplomatic"),
            "format": dom_fmt, "support": len(cands), "distinct_reads": len(sv),
            "rationale": [f"special plate ({dom_fmt}) — voted without standard-grammar coercion"],
            "candidates": len(cands),
        }

    # 1. pick the dominant length, weighted by confidence x prior x count
    lw = defaultdict(float)
    for s, c, src in cands:
        lw[len(s)] += c * priors.get(src, 1.0)
    target_len = max(lw, key=lw.get)
    pool = [(s, c, src) for s, c, src in cands if len(s) == target_len]
    # fold in ±1-length reads by trimming/padding alignment from the left
    # (state code is the stable anchor) — keeps near-miss frames contributing
    for s, c, src in cands:
        if len(s) == target_len - 1:
            pool.append((s + "?", c * 0.6, src))
        elif len(s) == target_len + 1:
            pool.append((s[:target_len], c * 0.6, src))

    # 2. decide the expected TYPE per position (letter vs digit), weighted
    type_vote = [defaultdict(float) for _ in range(target_len)]
    for s, c, src in pool:
        w = c * priors.get(src, 1.0)
        for i, ch in enumerate(s):
            if ch == "?":
                continue
            type_vote[i]["D" if ch.isdigit() else "L"] += w
    want = ["D" if type_vote[i]["D"] >= type_vote[i]["L"] else "L"
            for i in range(target_len)]

    # 3. per-position weighted vote after coercing toward the wanted type
    plate_chars, rationale = [], []
    total_w = 0.0
    agree_w = 0.0
    for i in range(target_len):
        votes = defaultdict(float)
        for s, c, src in pool:
            ch = s[i] if i < len(s) else "?"
            if ch == "?":
                continue
            w = c * priors.get(src, 1.0)
            votes[_coerce(ch, want[i])] += w
        if not votes:
            plate_chars.append("?")
            continue
        best = max(votes, key=votes.get)
        plate_chars.append(best)
        pos_total = sum(votes.values())
        total_w += pos_total
        agree_w += votes[best]
        # note positions that needed coercion or were contested
        raw = Counter(s[i] for s, _, _ in pool if i < len(s) and s[i] != "?")
        if raw and raw.most_common(1)[0][0] != best:
            rationale.append(f"pos{i+1}: {dict(raw)} -> {best} (coerced to {'digit' if want[i]=='D' else 'letter'})")

    plate = "".join(plate_chars)
    # state-code wisdom: if the first two chars aren't a real RTO code, repair
    # to the closest valid one (single-char confusion) or flag it.
    state = plate[:2]
    if state not in VALID_STATES:
        fix = _nearest_state(state)
        if fix and fix != state:
            rationale.append(f"state '{state}' invalid -> '{fix}' (nearest valid RTO code)")
            plate = fix + plate[2:]
    well_formed = bool(_INDIAN.match(plate)) and plate[:2] in VALID_STATES
    confidence = round(agree_w / total_w, 3) if total_w else 0.0
    if not rationale:
        rationale.append("unanimous after grammar check")
    return {
        "plate": plate,
        "confidence": confidence,
        "well_formed": well_formed,
        "format": classify(plate),
        "support": len(pool),
        "distinct_reads": len({s for s, _, _ in cands}),
        "rationale": rationale,
        "candidates": len(cands),
    }


def _nearest_state(s):
    best, bestd = None, 99
    for v in VALID_STATES:
        d = _editdist(s, v)
        if d < bestd:
            bestd, best = d, v
    return best if bestd <= 1 else None


def cluster_reads(reads, max_dist=2):
    """Group reads of (likely) the same vehicle by string proximity.
    reads: iterable of (plate, confidence[, key]). Returns list of clusters."""
    items = [(_clean(r[0]), r) for r in reads if _clean(r[0])]
    clusters = []  # each: {"sig": canonical, "members": [...]}
    for s, r in items:
        placed = False
        for cl in clusters:
            if abs(len(s) - len(cl["sig"])) <= 1 and _editdist(s, cl["sig"]) <= max_dist:
                cl["members"].append(r)
                placed = True
                break
        if not placed:
            clusters.append({"sig": s, "members": [r]})
    return [cl["members"] for cl in clusters]


def _editdist(a, b):
    if a == b:
        return 0
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[n]
