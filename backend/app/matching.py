"""Plate normalization and matching — the ONLY place these rules live.

Contract rules (docs/CONTRACT.md), extended by docs/CONTRACT_ADDENDUM.md:
- normalize(p) = uppercase, strip everything except A-Z0-9.
- exact match: normalized strings equal (match_confidence = 1.0).
- fuzzy match (confusion-tolerant matcher): weighted edit distance where a
  substitution between an OCR confusion pair (0/O, 1/I, 5/S, 8/B, 6/G, 2/Z)
  costs 0.25 and any other edit costs 1.0; total distance <= 1.0 is a fuzzy
  match. This is a strict superset of the base contract rule (Levenshtein 1
  OR a single OCR-confusion substitution).
- canonicalize(): after normalize, attempt to repair the string into Indian
  plate syntax ^([A-Z]{2})(\\d{1,2})([A-Z]{1,3})(\\d{4})$ by resolving
  confusion characters positionally (a digit in a letter slot becomes its
  letter twin and vice versa). Partial / nonstandard plates are tolerated:
  when the string cannot be unambiguously repaired it is returned normalized,
  unchanged. Canonical forms are used as a matching signal only — stored
  plates are NEVER silently rewritten, and any non-exact match is flagged
  fuzzy with an explicit confidence.
"""
import re
from dataclasses import dataclass

_NORMALIZE_RE = re.compile(r"[^A-Z0-9]")

# Indian plate syntax: state code, RTO code, series letters, 4-digit number.
_PLATE_SYNTAX_RE = re.compile(r"^([A-Z]{2})(\d{1,2})([A-Z]{1,3})(\d{4})$")

# OCR confusion twins (bidirectional, digit <-> letter).
_DIGIT_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "6": "G", "2": "Z"}
_LETTER_TO_DIGIT = {v: k for k, v in _DIGIT_TO_LETTER.items()}
_CONFUSION_PAIRS = frozenset(
    frozenset(pair) for pair in _DIGIT_TO_LETTER.items()
)

# Weighted-edit-distance parameters (see docs/CONTRACT_ADDENDUM.md).
CONFUSION_COST = 0.25
FUZZY_DISTANCE_THRESHOLD = 1.0
_CONFIDENCE_SLOPE = 0.28  # confidence = 1 - 0.28 * distance (0.93 for one confusion)


def normalize(plate: str | None) -> str:
    if not plate:
        return ""
    return _NORMALIZE_RE.sub("", plate.upper())


# ---------------------------------------------------------------------------
# Canonicalization (Indian plate syntax repair)
# ---------------------------------------------------------------------------

def _coerce_letters(segment: str) -> str | None:
    out = []
    for ch in segment:
        if ch.isalpha():
            out.append(ch)
        elif ch in _DIGIT_TO_LETTER:
            out.append(_DIGIT_TO_LETTER[ch])
        else:
            return None
    return "".join(out)


def _coerce_digits(segment: str) -> str | None:
    out = []
    for ch in segment:
        if ch.isdigit():
            out.append(ch)
        elif ch in _LETTER_TO_DIGIT:
            out.append(_LETTER_TO_DIGIT[ch])
        else:
            return None
    return "".join(out)


def canonicalize(plate: str | None) -> str:
    """normalize(), then try to repair into Indian plate syntax by swapping
    OCR-confusion twins where the syntax demands the other character class.
    Partial / nonstandard plates come back normalized but otherwise unchanged.
    """
    norm = normalize(plate)
    if not norm or _PLATE_SYNTAX_RE.match(norm):
        return norm
    # Syntax bounds: 2 + (1..2) + (1..3) + 4 characters.
    if not 8 <= len(norm) <= 11:
        return norm
    state = _coerce_letters(norm[:2])
    number = _coerce_digits(norm[-4:])
    if state is None or number is None:
        return norm
    middle = norm[2:-4]
    for rto_len in (2, 1):  # prefer the common 2-digit RTO code
        series_len = len(middle) - rto_len
        if not 1 <= series_len <= 3:
            continue
        rto = _coerce_digits(middle[:rto_len])
        series = _coerce_letters(middle[rto_len:])
        if rto is not None and series is not None:
            return state + rto + series + number
    return norm


# ---------------------------------------------------------------------------
# Weighted edit distance + scored matching
# ---------------------------------------------------------------------------

def weighted_edit_distance(a: str, b: str) -> float:
    """Levenshtein DP where substituting between an OCR confusion pair costs
    CONFUSION_COST (0.25) and every other edit (sub/ins/del) costs 1.0."""
    la, lb = len(a), len(b)
    if la == 0:
        return float(lb)
    if lb == 0:
        return float(la)
    prev = [float(j) for j in range(lb + 1)]
    for i in range(1, la + 1):
        ca = a[i - 1]
        cur = [float(i)]
        for j in range(1, lb + 1):
            cb = b[j - 1]
            if ca == cb:
                sub = prev[j - 1]
            elif frozenset((ca, cb)) in _CONFUSION_PAIRS:
                sub = prev[j - 1] + CONFUSION_COST
            else:
                sub = prev[j - 1] + 1.0
            cur.append(min(prev[j] + 1.0, cur[j - 1] + 1.0, sub))
        prev = cur
    return prev[lb]


@dataclass(frozen=True)
class MatchScore:
    match_type: str  # "exact" | "fuzzy"
    distance: float  # weighted edit distance actually used for scoring
    confidence: float  # 0-1; exact = 1.0


def _confidence(distance: float) -> float:
    return max(0.0, round(1.0 - _CONFIDENCE_SLOPE * distance, 2))


def score_match(candidate: str | None, target: str | None) -> MatchScore | None:
    """Score two plates (any formatting). Returns None when they don't match.

    exact  -> normalized forms equal, confidence 1.0.
    fuzzy  -> weighted edit distance <= 1.0 (canonical-form equality counts as
              a single confusion-weight step), confidence = 1 - 0.28*distance.
    Fuzzy results are ALWAYS flagged — distinct plates are never auto-merged.
    """
    cn, tn = normalize(candidate), normalize(target)
    if not cn or not tn:
        return None
    if cn == tn:
        return MatchScore("exact", 0.0, 1.0)
    distance = weighted_edit_distance(cn, tn)
    if canonicalize(cn) == canonicalize(tn):
        # A pure positional confusion repair maps both reads to the same
        # canonical plate — score it as one confusion-weight step at most.
        distance = min(distance, CONFUSION_COST)
    if distance <= FUZZY_DISTANCE_THRESHOLD:
        return MatchScore("fuzzy", distance, _confidence(distance))
    return None


def match_plates(candidate: str, target: str) -> str | None:
    """Back-compat wrapper: 'exact', 'fuzzy', or None."""
    score = score_match(candidate, target)
    return score.match_type if score is not None else None


def find_watchlist_match(plate: str, entries) -> tuple[object | None, str | None, float | None]:
    """Match a plate against watchlist entries (entries carry a normalized
    `.plate`). An exact match anywhere in the list beats any fuzzy match;
    among fuzzy matches the lowest weighted distance wins.

    Returns (entry, match_type, match_confidence) — (None, None, None) when
    nothing matches.
    """
    best_entry = None
    best_score: MatchScore | None = None
    for entry in entries:
        score = score_match(plate, entry.plate)
        if score is None:
            continue
        if score.match_type == "exact":
            return entry, "exact", 1.0
        if best_score is None or score.distance < best_score.distance:
            best_score, best_entry = score, entry
    if best_score is None:
        return None, None, None
    return best_entry, "fuzzy", best_score.confidence
