# Plate-reader evaluation on real sandbox crops

**Status: preliminary.** 19 labelled crops from 10 vehicles on one camera (cam06,
Timbavadi Gate): a 13-crop/6-vehicle development set plus a 6-crop/4-vehicle
held-out set collected afterwards. Labels were read by eye by one person. Use it to choose a
direction and to design the next, larger test, not as a final accuracy figure.

## Why this was done

The original default reader (`fast-plate-ocr`, model `cct-xs-v1-global`) read a
legible car's plate `GJ12FD3541` as `GJ12DD551`, `GJ12FD351`, `GJ22D3541`, ...
(17 different reads in 3 s, none correct) with confidences up to 0.95. Two
causes were confirmed:

- the model has **9 character slots** (`max_plate_slots: 9`), so it cannot emit
  a full 10-character Indian plate (a clean drawn `GJ01AB1234` came back as
  `GJ01AB123` at 0.94);
- it is a very small model (2 MB, 64x128 input) and stretches every plate to
  that fixed shape.

## Data

`SENTINEL_SAVE_CROPS=<dir>` makes the detector save every plate crop it hands to
the reader (plate pixels only, no video) plus `reads.csv` with the live read.
Median native crop size was about 64x30 px; many crops (39-49 px wide, night,
motion blur) are unreadable by anyone and were left out of scoring.

## Results (13 crops / 6 vehicles)

| Reader | Exact | Matcher finds it | ms/crop (CPU) |
|---|---|---|---|
| fast-plate `cct-xs-v1` (previous default) | 0/13 | 0/13 | ~11 |
| fast-plate `cct-xs-v2` (10 slots), no-stretch | 3/13 | 3/13 | ~11 |
| fast-plate `cct-s-v1` / `cct-s-v2` | 0-1/13 | 0-2/13 | ~11 |
| EasyOCR | 0/13 | 0-2/13 | 60-150 |
| RapidOCR recognition only | 3/13 | 5/13 | ~10 |
| **RapidOCR det+rec + Indian-syntax gate** (now the default) | **5/13** | **7/13** | ~670 |

"Matcher finds it" = `app/matching.py` scores the read as an exact or fuzzy
match of the true plate (weighted edit distance <= 1.0).

Integrated detector, same crops: the previous default emitted a read on 9/13
crops and **all 9 were wrong**; the RapidOCR path emitted 7/13, 5 exact and the
other 2 one character off (`YV` for `YY`), and stayed silent on the rest.

### Held-out check (collected after the engine was chosen)

6 legible crops of 4 new vehicles, plus 25 other crops (tiny, blurred, night,
or not a plate: an emblem, a wall, luggage), none seen during development:

| Reader | Exact | Matcher finds it | Reads invented from the 25 other crops |
|---|---|---|---|
| fast-plate `cct-xs-v1` (previous default) | 1/6 | 3/6 | 0 |
| **RapidOCR + syntax gate** | **6/6** | **6/6** | **0** |

Caveat: these held-out plates are the easy, crisp, 98-139 px ones; the hard
readable cases are all in the development set. Combined (19 crops): previous
default 1 exact / 3 findable; RapidOCR path 11 exact / 13 findable. Live, the
RapidOCR worker used about 5-15% of a 16-thread CPU with three cameras.

Other findings:

- the pipeline's CLAHE/unsharp enhancement did not help (slightly worse on
  several models vs the raw crop);
- cropping off the "IND" band did not help;
- averaging many frames' reads (character voting) did **not** help for
  fast-plate-ocr: its errors are systematic (it keeps dropping the same digit),
  so votes converge on the bias. The highest-confidence read per pass was
  better than the vote;
- fast-plate-ocr's confidence ranks reads usefully (rank correlation -0.55 vs
  distance-to-truth on one car) but its absolute value is overstated: no read
  at >= 0.85 was fully correct.

## What the RapidOCR path does

`ingest/detectors/anpr.py::_read_plate_rapid`: RapidOCR on the RAW crop (then a
96 px-high upscale if that fails), lines joined in reading order (two-line
plates read top then bottom), then accepted only if the text is valid Indian
syntax `AA00A(AA)0000` or becomes so by swapping OCR-confusion twins
(0/O, 1/I, 5/S, 8/B, 6/G, 2/Z) where the syntax demands the other class.
Crops narrower than 56 px are skipped. This is now the DEFAULT reader whenever
`rapidocr-onnxruntime` is installed (else the detector falls back to fast-plate-ocr);
`SENTINEL_OCR_ENGINE=fast-plate` forces the previous reader.

## Known limits

- Tiny sample, one camera, one labeller; RapidOCR was chosen after seeing these
  same crops, so its number is optimistic. A held-out check on later crops (above) came out
  6/6, but those plates were easy; keep collecting crops.
- ~60x slower per crop than fast-plate-ocr. Measure live CPU with several
  cameras before relying on it.
- Plates with a 1-digit RTO code or non-standard layouts are rejected by the
  syntax gate.
- One label (`GJ11YY2840`, a yellow commercial plate) was first misread by the
  labeller as `VY`; a crop with an ambiguous `D`/`0` was dropped. Label noise
  is a real source of error here.

## Reproduce

Collect crops: `SENTINEL_SAVE_CROPS=<dir> scripts/live-with-auth.sh`; label them
from `reads.csv` indices; score a reader by calling
`AnprDetector()._read_plate_best(crop)` per crop (set `SENTINEL_OCR_ENGINE` /
`SENTINEL_OCR_MODEL` first) and comparing with the labels via
`app.matching.score_match`.
