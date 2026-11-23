#!/usr/bin/env python3
"""Calibrate biometric thresholds and report ISO metrics (Phase 2.6).

Reads a LABELLED classroom dataset and outputs ISO/IEC 19795-1
(verification / identification) and ISO/IEC 30107-3 (PAD) metrics,
split by subgroup and condition.

There is NO labelled classroom set bundled with this repo, and this
script does NOT fabricate one: it takes ``--dataset`` as input and
fails loudly (exit 2) when the dataset or its manifest is missing.
No calibration on real classroom data was possible in the Phase 2 run
— the thresholds in ``worker/config.py`` remain uncalibrated starting
points until this script is run on real data.

Dataset format
--------------
``<dataset>/manifest.csv`` with one row per scored attempt:

=============  ============================================================
column         meaning
=============  ============================================================
sample_id      unique id for the attempt
modality       ``face`` | ``voice`` | ``pad``
kind           ``verification`` | ``identification`` | ``pad``
label          verification: ``genuine`` | ``impostor``;
               identification: ``genuine`` (in gallery) | ``impostor``
               (not enrolled); pad: ``bonafide`` | ``attack``
attack_type    pad only: ``print`` | ``replay`` | ``mask`` | ...
score          float; higher = more likely genuine / a match.
               For identification, the score of the top-1 candidate.
matched_id     identification only: predicted student id (empty if none)
true_id        identification only: true student id (empty if impostor)
subgroup       e.g. ``female`` / ``male`` / age band — for split reporting
condition      e.g. ``back_row`` / ``glasses`` / ``low_light`` / ``normal``
enrolled       ``1`` if enrolment succeeded, ``0`` if it failed (FTE)
acquired       ``1`` if a sample was acquired, ``0`` if not (FTA)
=============  ============================================================

Metrics (all computed from the labelled scores, never invented)
---------------------------------------------------------------
* ISO/IEC 19795-1: ROC / DET points, FMR, FNMR, EER, FPIR, FNIR, FTE, FTA.
* ISO/IEC 30107-3: APCER (attack presentation classification error
  rate), BPCER (bonafide presentation classification error rate),
  IAPMR (impostor attack presentation match rate — attack samples
  that would also match as the genuine user; requires
  ``matched_id == true_id`` on attack rows, reported as ``null`` when
  the manifest lacks those columns).
* Every metric is also reported per ``subgroup`` and per ``condition``.

Usage::

    python scripts/evaluate_biometrics.py --dataset data/classroom-set \\
        --output reports/biometrics-2026-11-22.json --threshold 0.40

References: ISO/IEC 19795-1 (biometric performance testing),
ISO/IEC 30107-3 (PAD testing), ArcFace https://arxiv.org/abs/1801.07698,
AdaFace https://arxiv.org/abs/2204.00964.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REQUIRED_COLUMNS = {
    "sample_id",
    "modality",
    "kind",
    "label",
    "score",
    "subgroup",
    "condition",
    "enrolled",
    "acquired",
}


class DatasetError(Exception):
    """The labelled dataset is missing or malformed — fail loudly."""


def load_manifest(dataset_dir: Path) -> List[Dict[str, Any]]:
    """Load and validate ``manifest.csv``. Raises DatasetError."""
    if not dataset_dir.is_dir():
        raise DatasetError(
            f"dataset directory not found: {dataset_dir}. No labelled "
            "classroom set is bundled with this repo — provide one with "
            "--dataset (see scripts/evaluate_biometrics.py docstring for "
            "the manifest format). No metrics were computed."
        )
    manifest = dataset_dir / "manifest.csv"
    if not manifest.is_file():
        raise DatasetError(
            f"manifest.csv not found in {dataset_dir}. Expected columns: "
            f"{sorted(REQUIRED_COLUMNS)}."
        )
    with open(manifest, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise DatasetError(f"manifest.csv in {dataset_dir} has no rows.")
    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise DatasetError(f"manifest.csv is missing columns: {sorted(missing)}")
    parsed = []
    for i, row in enumerate(rows, start=2):
        try:
            score = float(row["score"])
            enrolled = int(row["enrolled"])
            acquired = int(row["acquired"])
        except (TypeError, ValueError) as exc:
            raise DatasetError(f"manifest.csv line {i}: bad numeric value: {exc}") from exc
        parsed.append({**row, "score": score, "enrolled": enrolled, "acquired": acquired})
    return parsed


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def _fmr_fnmr(genuine: List[float], impostor: List[float], threshold: float) -> Tuple[float, float]:
    """FMR = impostors at/above threshold; FNMR = genuines below threshold."""
    fmr = sum(1 for s in impostor if s >= threshold) / len(impostor) if impostor else 0.0
    fnmr = sum(1 for s in genuine if s < threshold) / len(genuine) if genuine else 0.0
    return fmr, fnmr


def _eer(genuine: List[float], impostor: List[float]) -> Tuple[float, float]:
    """Equal error rate: threshold where FMR == FNMR (linear scan)."""
    if not genuine or not impostor:
        return 0.0, 0.0
    candidates = sorted(set(genuine) | set(impostor))
    best = (1.0, candidates[0])
    for t in candidates:
        fmr, fnmr = _fmr_fnmr(genuine, impostor, t)
        err = abs(fmr - fnmr)
        if err < best[0]:
            best = (err, t)
    t = best[1]
    fmr, fnmr = _fmr_fnmr(genuine, impostor, t)
    return (fmr + fnmr) / 2.0, t


def _roc_det(
    genuine: List[float], impostor: List[float]
) -> Tuple[List[Dict[str, float]], List[Dict[str, float]]]:
    """ROC (TMR vs FMR) and DET (FNMR vs FMR) points over thresholds."""
    thresholds = sorted(set(genuine) | set(impostor), reverse=True)
    roc, det = [], []
    for t in thresholds:
        fmr, fnmr = _fmr_fnmr(genuine, impostor, t)
        roc.append({"threshold": t, "fmr": fmr, "tmr": 1.0 - fnmr})
        det.append({"threshold": t, "fmr": fmr, "fnmr": fnmr})
    return roc, det


def verification_metrics(rows: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    genuine = [r["score"] for r in rows if r["label"] == "genuine"]
    impostor = [r["score"] for r in rows if r["label"] == "impostor"]
    if not genuine or not impostor:
        raise DatasetError(
            "verification metrics need both 'genuine' and 'impostor' rows; "
            f"got {len(genuine)} genuine, {len(impostor)} impostor."
        )
    fmr, fnmr = _fmr_fnmr(genuine, impostor, threshold)
    eer, eer_threshold = _eer(genuine, impostor)
    roc, det = _roc_det(genuine, impostor)
    n = len(rows)
    fte = 1.0 - (sum(r["enrolled"] for r in rows) / n) if n else 0.0
    fta = 1.0 - (sum(r["acquired"] for r in rows) / n) if n else 0.0
    return {
        "n_genuine": len(genuine),
        "n_impostor": len(impostor),
        "threshold": threshold,
        "fmr": fmr,
        "fnmr": fnmr,
        "eer": eer,
        "eer_threshold": eer_threshold,
        "fte": fte,
        "fta": fta,
        "roc": roc,
        "det": det,
    }


def identification_metrics(rows: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    """FPIR / FNIR at rank 1 (ISO/IEC 19795-1 closed/open-set terms).

    FPIR: impostor queries (not enrolled) whose top-1 score is at/above
    threshold — a false alarm. FNIR: genuine queries whose top-1 is
    either below threshold or the wrong identity.
    """
    genuine = [r for r in rows if r["label"] == "genuine"]
    impostor = [r for r in rows if r["label"] == "impostor"]
    if not genuine or not impostor:
        raise DatasetError(
            "identification metrics need both 'genuine' and 'impostor' rows; "
            f"got {len(genuine)} genuine, {len(impostor)} impostor."
        )
    fpir = (
        (sum(1 for r in impostor if r["score"] >= threshold) / len(impostor)) if impostor else 0.0
    )
    fnir = (
        (
            sum(
                1
                for r in genuine
                if r["score"] < threshold or (r.get("matched_id") or "") != (r.get("true_id") or "")
            )
            / len(genuine)
        )
        if genuine
        else 0.0
    )
    return {
        "n_genuine": len(genuine),
        "n_impostor": len(impostor),
        "threshold": threshold,
        "fpir": fpir,
        "fnir": fnir,
    }


def pad_metrics(rows: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    """APCER / BPCER (ISO/IEC 30107-3) + IAPMR when match info exists.

    Scores are liveness scores (higher = more likely bonafide): an
    attack at/above threshold is an APCER error; a bonafide below
    threshold is a BPCER error.
    """
    bonafide = [r for r in rows if r["label"] == "bonafide"]
    attacks = [r for r in rows if r["label"] == "attack"]
    if not bonafide or not attacks:
        raise DatasetError(
            "PAD metrics need both 'bonafide' and 'attack' rows; "
            f"got {len(bonafide)} bonafide, {len(attacks)} attack."
        )
    apcer = (sum(1 for r in attacks if r["score"] >= threshold) / len(attacks)) if attacks else 0.0
    bpcer = (
        (sum(1 for r in bonafide if r["score"] < threshold) / len(bonafide)) if bonafide else 0.0
    )
    by_attack: Dict[str, float] = {}
    for attack_type in sorted({r.get("attack_type") or "unknown" for r in attacks}):
        subset = [r for r in attacks if (r.get("attack_type") or "unknown") == attack_type]
        by_attack[attack_type] = (
            sum(1 for r in subset if r["score"] >= threshold) / len(subset) if subset else 0.0
        )
    # IAPMR: attacks that ALSO match as the genuine user. Needs
    # matched_id/true_id columns; null when unavailable.
    iapmr: Optional[float] = None
    if attacks and "matched_id" in attacks[0] and "true_id" in attacks[0]:
        matched = [
            r
            for r in attacks
            if r["score"] >= threshold
            and (r.get("matched_id") or "") == (r.get("true_id") or "")
            and r.get("true_id")
        ]
        iapmr = len(matched) / len(attacks) if attacks else 0.0
    return {
        "n_bonafide": len(bonafide),
        "n_attack": len(attacks),
        "threshold": threshold,
        "apcer": apcer,
        "bpcer": bpcer,
        "apcer_by_attack_type": by_attack,
        "iapmr": iapmr,
    }


def _split_report(rows: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    """Per-subgroup and per-condition metrics for one kind of rows."""
    if not rows:
        return {}
    kind = rows[0]["kind"]
    out: Dict[str, Any] = {}
    for dim in ("subgroup", "condition"):
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            groups[str(r.get(dim) or "unknown")].append(r)
        out[dim] = {}
        for name, subset in sorted(groups.items()):
            try:
                if kind == "verification":
                    out[dim][name] = verification_metrics(subset, threshold)
                elif kind == "identification":
                    out[dim][name] = identification_metrics(subset, threshold)
                elif kind == "pad":
                    out[dim][name] = pad_metrics(subset, threshold)
            except DatasetError as exc:
                out[dim][name] = {"error": str(exc)}
    return out


def evaluate(dataset_dir: Path, threshold: float) -> Dict[str, Any]:
    rows = load_manifest(dataset_dir)
    report: Dict[str, Any] = {
        "dataset": str(dataset_dir),
        "threshold": threshold,
        "n_rows": len(rows),
        "note": "Thresholds are calibrated on THIS dataset only; do not "
        "generalise to other classrooms without re-running.",
    }
    by_kind: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)
    for kind, subset in sorted(by_kind.items()):
        if kind == "verification":
            report["verification"] = verification_metrics(subset, threshold)
        elif kind == "identification":
            report["identification"] = identification_metrics(subset, threshold)
        elif kind == "pad":
            report["pad"] = pad_metrics(subset, threshold)
        else:
            raise DatasetError(f"unknown kind in manifest: {kind!r}")
        report.setdefault("by_subgroup_and_condition", {})[kind] = _split_report(subset, threshold)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", required=True, help="labelled classroom dataset directory (manifest.csv)"
    )
    parser.add_argument("--output", default=None, help="JSON report path (default: stdout only)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.40,
        help="operating threshold for the reported point metrics",
    )
    args = parser.parse_args(argv)
    try:
        report = evaluate(Path(args.dataset), args.threshold)
    except DatasetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
