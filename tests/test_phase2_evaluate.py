"""Phase 2.6 evaluation script tests (synthetic labelled manifest only).

The script must compute ISO/IEC 19795-1 + 30107-3 metrics from a
labelled dataset, split by subgroup/condition — and fail loudly when
no dataset exists. No real classroom data is used here, and no
metrics are fabricated: the manifest below is synthetic test input.
"""
import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)

_spec = importlib.util.spec_from_file_location(
    "evaluate_biometrics", str(Path(REPO) / "scripts/evaluate_biometrics.py"))
evaluate_biometrics = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evaluate_biometrics)


def _write_manifest(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["sample_id", "modality", "kind", "label", "score", "subgroup",
            "condition", "enrolled", "acquired", "attack_type",
            "matched_id", "true_id"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _verification_rows():
    rows = []
    # 4 genuine (high scores), 4 impostor (low scores), split by condition.
    for i, s in enumerate([0.9, 0.85, 0.8, 0.75]):
        rows.append({"sample_id": f"g{i}", "modality": "face", "kind": "verification",
                     "label": "genuine", "score": s, "subgroup": "group-a",
                     "condition": "back_row" if i < 2 else "normal",
                     "enrolled": 1, "acquired": 1})
    for i, s in enumerate([0.1, 0.15, 0.2, 0.25]):
        rows.append({"sample_id": f"i{i}", "modality": "face", "kind": "verification",
                     "label": "impostor", "score": s, "subgroup": "group-a",
                     "condition": "normal", "enrolled": 1, "acquired": 1})
    return rows


def test_missing_dataset_fails_loudly(tmp_path):
    with pytest.raises(evaluate_biometrics.DatasetError, match="not found"):
        evaluate_biometrics.evaluate(tmp_path / "no-such-set", 0.4)
    assert evaluate_biometrics.main(
        ["--dataset", str(tmp_path / "no-such-set")]) == 2


def test_missing_manifest_fails_loudly(tmp_path):
    d = tmp_path / "empty-set"
    d.mkdir()
    with pytest.raises(evaluate_biometrics.DatasetError, match="manifest.csv"):
        evaluate_biometrics.evaluate(d, 0.4)


def test_verification_metrics_on_synthetic_data(tmp_path):
    d = tmp_path / "set"
    _write_manifest(d / "manifest.csv", _verification_rows())
    report = evaluate_biometrics.evaluate(d, 0.4)
    v = report["verification"]
    assert v["fmr"] == 0.0  # no impostor >= 0.4
    assert v["fnmr"] == 0.0  # no genuine < 0.4
    assert v["eer"] == 0.0
    assert v["n_genuine"] == 4 and v["n_impostor"] == 4
    assert v["fte"] == 0.0 and v["fta"] == 0.0
    assert v["roc"] and v["det"]
    # Split by condition: back_row has 2 genuine, 0 impostor -> error entry.
    splits = report["by_subgroup_and_condition"]["verification"]["condition"]
    assert "back_row" in splits and "normal" in splits
    assert splits["normal"]["fmr"] == 0.0


def test_pad_metrics_on_synthetic_data(tmp_path):
    rows = []
    for i, s in enumerate([0.9, 0.85, 0.95]):
        rows.append({"sample_id": f"b{i}", "modality": "pad", "kind": "pad",
                     "label": "bonafide", "score": s, "subgroup": "g",
                     "condition": "normal", "enrolled": 1, "acquired": 1})
    for i, (s, atk) in enumerate([(0.1, "print"), (0.2, "replay"), (0.8, "print")]):
        rows.append({"sample_id": f"a{i}", "modality": "pad", "kind": "pad",
                     "label": "attack", "score": s, "subgroup": "g",
                     "condition": "normal", "enrolled": 1, "acquired": 1,
                     "attack_type": atk, "matched_id": "", "true_id": "s1"})
    d = tmp_path / "pad-set"
    _write_manifest(d / "manifest.csv", rows)
    report = evaluate_biometrics.evaluate(d, 0.5)
    pad = report["pad"]
    assert pad["apcer"] == pytest.approx(1 / 3)  # one of three attacks >= 0.5
    assert pad["bpcer"] == 0.0
    assert pad["apcer_by_attack_type"]["print"] == pytest.approx(0.5)
    assert pad["apcer_by_attack_type"]["replay"] == 0.0
    assert pad["iapmr"] == 0.0  # no attack matched as the genuine user


def test_identification_metrics_on_synthetic_data(tmp_path):
    rows = [
        {"sample_id": "g1", "modality": "face", "kind": "identification",
         "label": "genuine", "score": 0.9, "subgroup": "g", "condition": "normal",
         "enrolled": 1, "acquired": 1, "matched_id": "s1", "true_id": "s1"},
        {"sample_id": "g2", "modality": "face", "kind": "identification",
         "label": "genuine", "score": 0.3, "subgroup": "g", "condition": "normal",
         "enrolled": 1, "acquired": 1, "matched_id": "", "true_id": "s2"},
        {"sample_id": "i1", "modality": "face", "kind": "identification",
         "label": "impostor", "score": 0.8, "subgroup": "g", "condition": "normal",
         "enrolled": 1, "acquired": 1, "matched_id": "s1", "true_id": ""},
        {"sample_id": "i2", "modality": "face", "kind": "identification",
         "label": "impostor", "score": 0.2, "subgroup": "g", "condition": "normal",
         "enrolled": 1, "acquired": 1, "matched_id": "", "true_id": ""},
    ]
    d = tmp_path / "id-set"
    _write_manifest(d / "manifest.csv", rows)
    report = evaluate_biometrics.evaluate(d, 0.5)
    ident = report["identification"]
    assert ident["fpir"] == pytest.approx(0.5)  # one of two impostors alarmed
    assert ident["fnir"] == pytest.approx(0.5)  # one of two genuines missed


def test_main_writes_json_report(tmp_path):
    d = tmp_path / "set"
    _write_manifest(d / "manifest.csv", _verification_rows())
    out = tmp_path / "report.json"
    assert evaluate_biometrics.main(
        ["--dataset", str(d), "--output", str(out), "--threshold", "0.4"]) == 0
    assert json.loads(out.read_text())["verification"]["fmr"] == 0.0
