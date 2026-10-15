"""Reconcile IEM LSR GeoJSON with archived LSRLIX text products.

The text ZIP has one entry per product, including duplicate filenames when two
products share a minute. We retain entry hashes so those are auditable.
"""
import hashlib
import io
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
CENTRAL = ZoneInfo("America/Chicago")
BASE = "https://mesonet.agron.iastate.edu"
RELEVANT_TYPES = {
    "HAIL": "SVR", "TSTM WND GST": "SVR", "TSTM WND DMG": "SVR",
    "THUNDERSTORM WIND GUST": "SVR", "THUNDERSTORM WIND DAMAGE": "SVR",
    "FLASH FLOOD": "FFW",
}
COORD = re.compile(r"(\d{2}\.\d{2})([NS])\s+(\d{2,3}\.\d{2})([EW])")
ENTRY_NAME = re.compile(r"LSRLIX_(\d{12})\.txt$")


def archive_months(end):
    """Inclusive January 2025 through the month containing `end` (UTC)."""
    year, month = 2025, 1
    while (year, month) <= (end.year, end.month):
        ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
        start = datetime(year, month, 1, tzinfo=UTC)
        stop = min(datetime(ny, nm, 1, tzinfo=UTC), end + timedelta(days=1))
        if stop > start:
            yield start, stop
        year, month = ny, nm


def parse_archive(payload, archive_name):
    """Extract event rows and their actual archived product issuance times."""
    entries = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for ordinal, info in enumerate(archive.infolist()):
            match = ENTRY_NAME.fullmatch(info.filename)
            if not match:
                continue
            issued = datetime.strptime(match.group(1), "%Y%m%d%H%M").replace(tzinfo=UTC)
            raw = archive.read(info)
            body = raw.decode("utf-8", errors="replace")
            wmo = re.search(r"(?m)^([A-Z]{4}\d{2}) KLIX \d{6}\s*$", body)
            if not wmo or "LSRLIX" not in body:
                continue
            pid = f"{match.group(1)}-KLIX-{wmo.group(1)}-LSRLIX"
            source = {
                "product_id": pid, "issued": issued.isoformat().replace("+00:00", "Z"),
                "source_url": f"{BASE}/p.php?pid={pid}",
                "archive_month": archive_name, "archive_entry": ordinal,
                "text_sha256": hashlib.sha256(raw).hexdigest(),
            }
            lines = body.splitlines()
            for pos, line in enumerate(lines[:-1]):
                if not re.match(r"^\d{4} [AP]M\s+", line):
                    continue
                following = lines[pos + 1]
                if not re.match(r"^\d{2}/\d{2}/\d{4}", following):
                    continue
                coord = COORD.search(line)
                if not coord:
                    continue
                lat = float(coord.group(1)) * (1 if coord.group(2) == "N" else -1)
                lon = float(coord.group(3)) * (1 if coord.group(4) == "E" else -1)
                event_local = following[:10] + " " + line[:7]
                kind = line[12:28].strip().upper()
                county = following[29:48].strip().lower()
                remarks = []
                for later in lines[pos + 2:]:
                    if re.match(r"^\d{4} [AP]M\s+", later) or later.strip() in ("&&", "$$"):
                        break
                    if later.startswith("            ") and later.strip():
                        remarks.append(later.strip())
                entries.append({**source, "event_local": event_local, "type": kind,
                                "county": county, "lat": lat, "lon": lon,
                                "remarks": " ".join(remarks),
                                "magnitude_text": following[12:28].strip()})
    return entries


def archive_key(event_local, kind, lat, lon, county):
    return (event_local, kind.upper(), round(lat, 2), round(lon, 2), county.lower().strip())


def report_key(report):
    if report.get("lat") is None or report.get("lon") is None:
        return None
    local = datetime.fromisoformat(report["occurred"].replace("Z", "+00:00")).astimezone(CENTRAL)
    return archive_key(local.strftime("%m/%d/%Y %I%M %p"), report["type"],
                       report["lat"], report["lon"], report["county"])


def reconcile(reports, raw_entries):
    """Mark earliest exact raw match, cross-type corrections, or uncertain proxy."""
    exact = defaultdict(list)
    place_time = defaultdict(list)
    for entry in raw_entries:
        key = archive_key(entry["event_local"], entry["type"], entry["lat"], entry["lon"], entry["county"])
        exact[key].append(entry)
        place_time[(key[0], *key[2:])].append(entry)
    for report in reports:
        key = report_key(report)
        matches = sorted(exact.get(key, []), key=lambda e: (e["issued"], e["text_sha256"])) if key else []
        related = place_time.get((key[0], *key[2:]), []) if key else []
        report["raw_provenance"] = [
            {k: entry.get(k) for k in ("product_id", "issued", "source_url", "archive_url", "archive_month", "archive_entry", "text_sha256")}
            for entry in matches
        ]
        report["observed_earliest_raw"] = matches[0]["issued"] if matches else None
        report["earliest_source_url"] = matches[0]["source_url"] if matches else None
        report["proxy_issued"] = min((pid[:12] for pid in report["source_product_ids"] if re.match(r"^\d{12}", pid)), default=None)
        if report["proxy_issued"]:
            report["proxy_issued"] = datetime.strptime(report["proxy_issued"], "%Y%m%d%H%M").replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
        conflicting = [e for e in related if e["type"] != report["type"] and
                       (not matches or e["issued"] <= matches[0]["issued"])]
        occurred_local = datetime.fromisoformat(report["occurred"].replace("Z", "+00:00")).astimezone(CENTRAL)
        ambiguous_local_hour = occurred_local.replace(fold=0).utcoffset() != occurred_local.replace(fold=1).utcoffset()
        if ambiguous_local_hour and matches:
            report["timing_status"] = "uncertain_dst"
            report["flags"].append("ambiguous_fall_back_local_event_time__review")
            report["related_product_ids"] = []
        elif conflicting:
            report["timing_status"] = "uncertain_correction"
            report["flags"].append("earlier_or_equal_cross_type_product__review")
            report["related_product_ids"] = sorted({e["product_id"] for e in conflicting})
        elif matches:
            report["timing_status"] = "archive_confirmed"
            report["related_product_ids"] = []
        else:
            report["timing_status"] = "proxy_only" if report["proxy_issued"] else "missing"
            report["related_product_ids"] = []
        report["first_issued"] = matches[0]["issued"] if report["timing_status"] == "archive_confirmed" else None
        if report["proxy_issued"] and matches and report["proxy_issued"] > matches[0]["issued"]:
            report["flags"].append("geojson_links_later_product")
        if matches and len({e["remarks"] for e in matches}) > 1:
            report["flags"].append("text_product_revision")
        report["first_raw_remarks"] = matches[0]["remarks"] if matches else None
    return reports
