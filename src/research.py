"""Report-centered LIX warning / LSR analysis. Matches are research candidates."""
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import Point

from src.lsr_text import RELEVANT_TYPES, archive_months, parse_archive, reconcile

UTC = timezone.utc
BASE = "https://mesonet.agron.iastate.edu"
THRESHOLDS = (1, 3, 8, 12, 24, 48, 72, 96)
BIN_LABELS = ("0–1h", ">1–3h", ">3–8h", ">8–12h", ">12–24h",
              ">24–48h", ">48–72h", ">72–96h", ">96h")


def parsedate(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def digest(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def consolidate_reports(source_rows):
    """Collapse exact repeated/corrected GeoJSON representations once per LSR."""
    groups = defaultdict(list)
    for report in source_rows:
        kind = RELEVANT_TYPES.get(report["type"])
        if not kind:
            continue
        occurred = parsedate(report["occurred"])
        if not occurred or not (2025 <= occurred.year <= 2026):
            continue
        if report["lat"] is None or report["lon"] is None:
            location = (report["city"].casefold().strip(), report["remarks"].casefold().strip())
        else:
            location = (round(report["lat"], 2), round(report["lon"], 2))
        key = (report["occurred"], report["type"], report["county"].casefold().strip(), *location)
        groups[key].append(report)
    result = []
    for key, rows in sorted(groups.items()):
        rows.sort(key=lambda r: (r.get("product_id") or "", r["id"]))
        representative = max(rows, key=lambda r: (len(r.get("remarks") or ""), r.get("product_id") or ""))
        report = {k: v for k, v in representative.items() if k not in ("id", "event_group", "disseminated")}
        report["id"] = digest(*key)
        report["phenomenon"] = RELEVANT_TYPES[report["type"]]
        report["source_scope_2025"] = parsedate(report["occurred"]).year == 2025
        report["source_record_count"] = len(rows)
        report["source_product_ids"] = sorted({r["product_id"] for r in rows if r.get("product_id")})
        report["source_record_ids"] = [r["id"] for r in rows]
        report["remarks_versions"] = sorted({r["remarks"] for r in rows if r.get("remarks")})
        report["flags"] = sorted({flag for row in rows for flag in row.get("flags", [])})
        if len(rows) > 1:
            report["flags"].append("geojson_repeated_or_revised_record")
        if len(report["remarks_versions"]) > 1:
            report["flags"].append("remarks_revised__review")
        result.append(report)
    return result


def fetch_raw_products(session, cache, refresh, get_bytes, through=None):
    through = through or datetime.now(UTC)
    entries = []
    for start, stop in archive_months(through):
        month = f"{start:%Y%m}"
        params = {"pil": "LSRLIX", "sdate": start.date().isoformat(),
                  "edate": stop.date().isoformat(), "limit": "9999", "fmt": "zip", "dl": "1"}
        path = Path(cache) / f"lsr_text_{month}.zip"
        # The current-month slice changes as new products arrive.
        payload = get_bytes(session, f"{BASE}/cgi-bin/afos/retrieve.py", params,
                            path, refresh or (start.year, start.month) == (through.year, through.month))
        monthly = parse_archive(payload, month)
        if len(monthly) >= 9999:
            raise ValueError(f"IEM text archive may be truncated for {month}")
        archive_url = f"{BASE}/cgi-bin/afos/retrieve.py?pil=LSRLIX&sdate={params['sdate']}&edate={params['edate']}&limit=9999&fmt=zip&dl=1"
        for entry in monthly:
            entry["archive_url"] = archive_url
        entries.extend(monthly)
    return entries, through.isoformat(timespec="seconds").replace("+00:00", "Z")


def eligibility(phenomenon, report):
    """Conservative automated support screen; never official verification."""
    typ = report["type"]
    magnitude = report.get("magnitude")
    if phenomenon == "SVR":
        if typ == "HAIL":
            return "candidate" if magnitude is not None and magnitude >= 1 else "review" if magnitude is None else "incompatible"
        if typ in ("TSTM WND GST", "THUNDERSTORM WIND GUST"):
            return "candidate" if magnitude is not None and magnitude >= 58 else "review" if magnitude is None else "incompatible"
        if typ in ("TSTM WND DMG", "THUNDERSTORM WIND DAMAGE"):
            return "review"
        return "incompatible"
    if phenomenon == "FFW":
        if typ != "FLASH FLOOD":
            return "incompatible"
        remarks = (report.get("first_raw_remarks") or report.get("remarks") or "").casefold()
        # A generic county/parish flooding statement is retained for review.
        if re.search(r"\b(?:across|throughout) (?:the )?(?:parish|county)\b", remarks) and not re.search(r"\b(?:rescue|vehicle|home|house|building|road|street|highway)\b", remarks):
            return "review"
        impact = re.search(r"\b(?:roads?|streets?|highways?|hwy|lanes?|avenues?|ave|blvd|drives?|underpass|intersection|vehicles?|cars?|trucks?|rescue|homes?|houses?|buildings?|apartments?|impassable|stranded|inundated|washout|bridges?|doors?|floorboard)\b", remarks)
        flooding = re.search(r"\b(?:flood\w*|water|inundat\w*|stranded|impassable|washout)\b", remarks)
        return "candidate" if impact and flooding else "review"
    return "incompatible"


def delay_bin(minutes):
    if minutes is None or minutes < 0 or not math.isfinite(minutes):
        return None
    hours = minutes / 60
    for limit, label in zip(THRESHOLDS, BIN_LABELS):
        if hours <= limit:
            return label
    return BIN_LABELS[-1]


def associate(warnings, reports):
    """Keep all plausible matches; assign a primary warning only if unambiguous."""
    associations = []
    warning_by_id = {w["id"]: w for w in warnings}
    by_warning = defaultdict(list)
    for report in reports:
        plausible = []
        if report["lat"] is not None and report["lon"] is not None:
            point = Point(report["lon"], report["lat"])
            occurred = parsedate(report["occurred"])
            for warning in warnings:
                if warning["type"] != report["phenomenon"]:
                    continue
                if not (parsedate(warning["issued"]) <= occurred <= parsedate(warning["expired"])):
                    continue
                if not any(seg["start"] <= occurred <= seg["end"] and seg["geom"].covers(point)
                           for seg in warning["_segments"]):
                    continue
                q = eligibility(warning["type"], report)
                if q != "incompatible":
                    plausible.append({"warning_id": warning["id"], "report_id": report["id"],
                                      "eligibility": q, "occurred": report["occurred"],
                                      "phenomenon": report["phenomenon"]})
        candidates = [a for a in plausible if a["eligibility"] == "candidate"]
        if len(candidates) == 1:
            report["association_status"] = "candidate"
            report["primary_warning_id"] = candidates[0]["warning_id"]
        elif len(candidates) > 1:
            report["association_status"] = "overlap_review"
            report["primary_warning_id"] = None
            report["flags"].append("multiple_candidate_warnings__no_primary_attribution")
        else:
            report["association_status"] = "needs_review" if plausible else "unassociated"
            report["primary_warning_id"] = None
        report["possible_warning_ids"] = sorted({a["warning_id"] for a in plausible})
        for assoc in plausible:
            assoc["attribution"] = "primary" if assoc["warning_id"] == report["primary_warning_id"] else "review"
            associations.append(assoc)
            by_warning[assoc["warning_id"]].append(assoc)
        primary = warning_by_id.get(report["primary_warning_id"])
        report["warning_issued"] = primary["issued"] if primary else None
        report["warning_source_url"] = primary["source_url"] if primary else None
        if primary and report["first_issued"]:
            report["delay_minutes"] = round((parsedate(report["first_issued"]) - parsedate(primary["issued"])).total_seconds() / 60, 1)
            if report["delay_minutes"] < 0:
                report["flags"].append("lsr_issued_before_warning")
        else:
            report["delay_minutes"] = None
        report["delay_bin"] = delay_bin(report["delay_minutes"])
    report_by_id = {r["id"]: r for r in reports}
    for warning in warnings:
        linked = by_warning[warning["id"]]
        primary = [report_by_id[a["report_id"]] for a in linked if a["attribution"] == "primary"]
        timed = [r for r in primary if r["delay_minutes"] is not None and r["delay_minutes"] >= 0]
        warning["candidate_lsr_count"] = len(primary)
        warning["review_lsr_count"] = len(linked) - len(primary)
        warning["first_supporting_lsr"] = min((r["first_issued"] for r in timed), default=None)
        warning["first_supporting_delay_minutes"] = min((r["delay_minutes"] for r in timed), default=None)
        warning["classification"] = (
            "candidate_within_8" if timed and warning["first_supporting_delay_minutes"] <= 480 else
            "candidate_after_8" if timed else
            "candidate_untimed" if primary else
            "needs_review" if linked else "no_candidate_lsr"
        )
    return associations


def summarize(warnings, reports, associations, raw_count, coverage_end):
    source = [r for r in reports if r["source_scope_2025"]]
    candidates = [r for r in reports if r["association_status"] == "candidate"]
    timed = [r for r in candidates if r["delay_minutes"] is not None and r["delay_minutes"] >= 0]
    by_phenomenon = {}
    for kind in ("SVR", "FFW"):
        subset = [r for r in candidates if r["phenomenon"] == kind]
        valid = [r for r in timed if r["phenomenon"] == kind]
        delays = sorted(r["delay_minutes"] for r in valid)
        n = len(delays)
        median = (delays[(n - 1) // 2] + delays[n // 2]) / 120 if n else None
        by_phenomenon[kind] = {
            "source_lsrs": sum(r["phenomenon"] == kind for r in source),
            "associated_lsrs": len(subset), "reliably_timed_lsrs": n,
            "timing_uncertain_or_pre_warning": len(subset) - n,
            "timing_uncertain": sum(r["delay_minutes"] is None for r in subset),
            "pre_warning": sum(r["delay_minutes"] is not None and r["delay_minutes"] < 0 for r in subset),
            "within_8": sum(r["delay_minutes"] <= 480 for r in valid),
            "beyond_8": sum(r["delay_minutes"] > 480 for r in valid),
            "beyond_24": sum(r["delay_minutes"] > 1440 for r in valid),
            "beyond_48": sum(r["delay_minutes"] > 2880 for r in valid),
            "beyond_72": sum(r["delay_minutes"] > 4320 for r in valid),
            "beyond_96": sum(r["delay_minutes"] > 5760 for r in valid),
            "median_delay_hours": round(median, 2) if median is not None else None,
            "bins": {label: sum(r["delay_bin"] == label for r in valid) for label in BIN_LABELS},
            "cumulative": {str(hour): sum(r["delay_minutes"] <= hour * 60 for r in valid) for hour in THRESHOLDS},
        }
    all_delays = sorted(r["delay_minutes"] for r in timed)
    n = len(all_delays)
    median_all = (all_delays[(n-1)//2] + all_delays[n//2]) / 120 if n else None
    counts = Counter(w["classification"] for w in warnings)
    overview = {
        "warnings": len(warnings),
        "source_svr_lsrs": by_phenomenon["SVR"]["source_lsrs"],
        "source_ffw_lsrs": by_phenomenon["FFW"]["source_lsrs"],
        "associated_lsrs": len(candidates),
        "overlap_review_lsrs": sum(r["association_status"] == "overlap_review" for r in reports),
        "other_review_lsrs": sum(r["association_status"] == "needs_review" for r in reports),
        "reliably_timed_lsrs": n,
        "timing_unknown_or_pre_warning": len(candidates) - n,
        "timing_unknown": sum(r["delay_minutes"] is None for r in candidates),
        "pre_warning": sum(r["delay_minutes"] is not None and r["delay_minutes"] < 0 for r in candidates),
        "archive_confirmed_share_of_associated": round(100 * sum(r["timing_status"] == "archive_confirmed" for r in candidates) / len(candidates), 1) if candidates else None,
        "within_8": sum(r["delay_minutes"] <= 480 for r in timed),
        "beyond_8": sum(r["delay_minutes"] > 480 for r in timed),
        "beyond_24": sum(r["delay_minutes"] > 1440 for r in timed),
        "beyond_48": sum(r["delay_minutes"] > 2880 for r in timed),
        "beyond_72": sum(r["delay_minutes"] > 4320 for r in timed),
        "beyond_96": sum(r["delay_minutes"] > 5760 for r in timed),
        "median_delay_hours": round(median_all, 2) if median_all is not None else None,
        "warnings_with_candidate": len(warnings) - counts["needs_review"] - counts["no_candidate_lsr"],
        "warnings_first_within_8": counts["candidate_within_8"],
        "warnings_first_after_8": counts["candidate_after_8"],
        "warnings_candidate_untimed": counts["candidate_untimed"],
        "warnings_needs_review": counts["needs_review"],
        "warnings_no_candidate": counts["no_candidate_lsr"],
    }
    metadata = {
        "year": 2025, "office": "LIX", "generated_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "raw_text_coverage_end_utc": coverage_end,
        "raw_text_event_rows_examined": raw_count,
        "geojson_relevant_unique_lsrs": len(reports),
        "report_unit": "Unique LSR event/type/location/county; repeated GeoJSON source records collapsed",
        "timing_method": "Earliest exact-matching LSRLIX text product timestamp in the IEM raw text archive; corrections with conflicting event types remain uncertain",
        "timing_caveat": "Archive-confirmed means earliest matching product located in IEM's available archive, not proof of forecaster receipt or completeness of all NWS products.",
        "association_method": "Occurrence inside the applicable warning segment in time and polygon, followed by conservative type/impact screening; overlapping candidates have no primary attribution.",
        "verification_caveat": "Candidate supporting LSRs are not official warning verification. Late issuance does not prove active follow-up.",
        "warning_source": f"{BASE}/request/gis/watchwarn.phtml",
        "lsr_geojson_source": f"{BASE}/geojson/lsr.geojson",
        "lsr_text_source": f"{BASE}/cgi-bin/afos/retrieve.py?pil=LSRLIX",
        "associated_pairs": len(associations),
    }
    return {"metadata": metadata, "overview": overview, "by_phenomenon": by_phenomenon,
            "warnings": warnings, "reports": reports, "associations": associations}


def export(data, output):
    root = Path(output) / "data"
    root.mkdir(parents=True, exist_ok=True)
    for warning in data["warnings"]:
        warning.pop("_geom", None)
        warning.pop("_segments", None)
    from src.validate import validate_results
    validate_results(data)
    (root / "results.json").write_text(json.dumps(data, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    columns = {
        "reports.csv": (data["reports"], ("id", "phenomenon", "type", "county", "city", "occurred", "primary_warning_id", "warning_issued", "first_issued", "proxy_issued", "timing_status", "delay_minutes", "delay_bin", "association_status", "source_url", "earliest_source_url", "remarks", "flags")),
        "warnings.csv": (data["warnings"], ("id", "type", "issued", "expired", "candidate_lsr_count", "review_lsr_count", "first_supporting_lsr", "first_supporting_delay_minutes", "classification", "source_url", "flags")),
        "associations.csv": (data["associations"], ("warning_id", "report_id", "phenomenon", "eligibility", "attribution", "occurred")),
    }
    for filename, (rows, fields) in columns.items():
        with (root / filename).open("w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: ";".join(row.get(k, [])) if isinstance(row.get(k), list) else row.get(k) for k in fields})
    with (root / "raw_provenance.csv").open("w", newline="", encoding="utf-8") as out:
        fields = ("report_id", "product_id", "issued", "source_url", "archive_url", "archive_month", "archive_entry", "text_sha256")
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for report in data["reports"]:
            for item in report["raw_provenance"]:
                writer.writerow({"report_id": report["id"], **item})
    overview = data["overview"]
    (root / "summary.txt").write_text(
        "LIX 2025 source-linked LSR reporting delay research\n"
        f"SVR-related / FFW-related source LSRs: {overview['source_svr_lsrs']} / {overview['source_ffw_lsrs']}\n"
        f"Unique candidate associated LSRs: {overview['associated_lsrs']}\n"
        f"Reliably timed: {overview['reliably_timed_lsrs']}\n"
        f"Within / beyond 8 hours: {overview['within_8']} / {overview['beyond_8']}\n"
        f"Beyond 24 / 48 / 72 / 96 hours: {overview['beyond_24']} / {overview['beyond_48']} / {overview['beyond_72']} / {overview['beyond_96']}\n"
        "These are candidate supporting LSRs, not official warning verification.\n"
        "An IEM archive-confirmed first product time is not forecaster receipt time or proof that follow-up occurred.\n",
        encoding="utf-8")
    print(json.dumps(overview, indent=2), flush=True)
