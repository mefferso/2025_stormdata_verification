"""Validate published research results before Pages deployment."""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

TYPES = {"SVR", "FFW"}
CLASSES = {"documented_by_expiration", "first_documented_after_expiration", "needs_review", "no_candidate_lsr"}


def validate_results(data):
    assert data["metadata"]["year"] == 2025
    warnings, reports, associations = (data[k] for k in ("warnings", "reports", "associations"))
    assert isinstance(warnings, list) and warnings, "No warnings"
    assert isinstance(reports, list) and reports, "No associated reports"
    assert isinstance(associations, list) and associations, "No associations"
    warning_ids = {w["id"] for w in warnings}
    report_ids = {r["id"] for r in reports}
    assert len(warning_ids) == len(warnings), "Duplicate warning IDs"
    assert len(report_ids) == len(reports), "Duplicate report IDs"
    assert all(w["type"] in TYPES for w in warnings), "Non SVR/FFW warning"
    assert all(w["classification"] in CLASSES for w in warnings), "Unknown classification"
    assert all(w["issued"].startswith("2025-") for w in warnings), "Warning issued outside 2025"
    assert all(w["geometry"]["type"] in ("Polygon", "MultiPolygon") and w["geometry"]["coordinates"] for w in warnings), "Missing polygon geometry"
    assert all(a["warning_id"] in warning_ids and a["report_id"] in report_ids for a in associations), "Broken association reference"
    assert all(a["eligibility"] in ("candidate", "review") for a in associations), "Invalid association eligibility"
    assert {a["report_id"] for a in associations} == report_ids, "Unassociated exported report"
    assert data["overview"]["warnings"] == len(warnings), "Warning count mismatch"
    assert data["metadata"]["associated_pairs"] == len(associations), "Association count mismatch"
    counts = Counter(w["classification"] for w in warnings)
    assert data["overview"]["documented"] == counts["documented_by_expiration"] + counts["first_documented_after_expiration"]
    assert data["overview"]["late_first"] == counts["first_documented_after_expiration"]
    assert data["overview"]["not_matched"] == counts["no_candidate_lsr"]
    for r in reports:
        delay = r.get("delay_minutes")
        assert delay is None or isinstance(delay, (int, float)) and math.isfinite(delay) and delay >= 0, "Invalid chart delay"
    for w in warnings:
        assert isinstance(w["hour_local"], int) and 0 <= w["hour_local"] < 24, "Invalid issuance hour"
        assert isinstance(w["month"], int) and 1 <= w["month"] <= 12, "Invalid month"
        assert isinstance(w["flags"], list), "Invalid flags"
        assert isinstance(w["strict_reports"], int) and w["strict_reports"] >= 0
    for value in data["overview"]["windows"].values():
        assert isinstance(value, int) and 0 <= value <= len(warnings), "Invalid chart window"
    return Counter(w["type"] for w in warnings)


def validate_files(root):
    root = Path(root)
    data = json.loads((root / "results.json").read_text(encoding="utf-8"))
    counts = validate_results(data)
    for name, key in (("warnings.csv", "warnings"), ("reports.csv", "reports"), ("associations.csv", "associations")):
        with (root / name).open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(data[key]), f"{name} row count mismatch"
        if key == "warnings":
            assert all(row["type"] in TYPES for row in rows), "TOR in warnings.csv"
    assert (root / "summary.txt").is_file()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print("Validated warning types:", dict(validate_files(args.directory)))
