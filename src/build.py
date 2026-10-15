"""IEM-based LIX storm warning / LSR retrospective research pipeline.

Strict matches are spatially and temporally consistent *candidate documentation*;
they are emphatically NOT official NWS warning verification.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import re
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import shapefile
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union

UTC = timezone.utc
CHICAGO = ZoneInfo("America/Chicago")
BASE = "https://mesonet.agron.iastate.edu"
KINDS = {"TO": "TOR", "SV": "SVR", "FF": "FFW"}
WINDOWS = (1, 3, 6, 12, 24, 48)
USER_AGENT = "LIX-2025-Stormdata-Research/1.0 (GitHub: mefferso/2025_stormdata_verification)"


def stamp(v):
    """Normalize archived timestamps to UTC, or return None."""
    if v is None or str(v).strip() in ("", "None", "nan", "NaT"):
        return None
    s = str(v).strip()
    try:
        if re.fullmatch(r"\d{12}", s):
            return datetime.strptime(s, "%Y%m%d%H%M").replace(tzinfo=UTC)
        if re.fullmatch(r"\d{14}", s):
            return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        t = pd.to_datetime(s, utc=True, errors="coerce")
        if pd.isna(t):
            return None
        return t.to_pydatetime().astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def iso(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z") if dt else None


def local(dt):
    return dt.astimezone(CHICAGO).strftime("%Y-%m-%d %I:%M %p %Z") if dt else None


def digest(*vals):
    return hashlib.sha1("|".join(str(x) for x in vals).encode("utf-8")).hexdigest()[:14]


def get_bytes(session, url, params, cached, refresh=False):
    """Explicit cache preserves reproducibility; reject unsuccessful archives."""
    cached = Path(cached)
    if cached.exists() and not refresh:
        return cached.read_bytes()
    for n in range(4):
        try:
            r = session.get(url, params=params, timeout=65)
            r.raise_for_status()
            if len(r.content) < 20:
                raise ValueError("Suspiciously empty archive response")
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(r.content)
            print("Fetched", r.url, len(r.content), "bytes", flush=True)
            return r.content
        except (requests.RequestException, ValueError) as e:
            if n == 3:
                raise RuntimeError(f"Could not retrieve source {url}: {e}") from e
            time.sleep(3 * (n + 1))
    raise AssertionError("unreachable")


def warning_rows(session, cache, refresh):
    """Read IEM zipped shapefile; source offers polygons and metadata."""
    seen = set()
    for month in (1, 4, 7, 10):
        start = datetime(2025, month, 1, tzinfo=UTC)
        end = datetime(2026, 1, 1, tzinfo=UTC) if month == 10 else datetime(2025, month + 3, 1, tzinfo=UTC)
        params = {"accept": "shapefile", "sts": iso(start), "ets": iso(end),
                  "wfo": "LIX", "limitps": "1",
                  "phenomena": "TO,SV,FF", "significance": "W,W,W"}
        data = get_bytes(session, f"{BASE}/cgi-bin/request/gis/watchwarn.py",
                         params, Path(cache) / f"warnings_quarter_{month:02}.zip", refresh)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            member = next((x for x in z.namelist() if x.lower().endswith(".shp")), None)
            if member is None:
                raise ValueError("IEM warning ZIP lacks a .shp file")
            prefix = member[:-4]
            siblings = {x.lower(): x for x in z.namelist()}
            def payload(ext):
                key = (prefix + ext).lower()
                return io.BytesIO(z.read(siblings[key]))
            reader = shapefile.Reader(shp=payload(".shp"), shx=payload(".shx"),
                                      dbf=payload(".dbf"))
            cols = [f[0] for f in reader.fields[1:]]
            for rec in reader.iterShapeRecords():
                row = dict(zip(cols, rec.record, strict=True))
                # Archive may contain a few unexpected county-based rows.
                if str(row.get("GTYPE", "")).upper() != "P":
                    continue
                if row.get("PHENOM") not in KINDS or row.get("SIG") != "W":
                    continue
                geom = shape(rec.shape.__geo_interface__)
                if geom.is_empty or not geom.is_valid:
                    geom = geom.buffer(0)
                if geom.is_empty:
                    continue
                issue = stamp(row.get("INIT_ISS") or row.get("ISSUED"))
                endtime = stamp(row.get("POLY_END") or row.get("EXPIRED"))
                if not issue or not endtime or endtime < issue:
                    continue
                event_year = int(row.get("VTEC_YR") or issue.year)
                if issue.year != 2025:
                    continue
                ident = f"{event_year}-LIX-{row['PHENOM']}-W-{int(row['ETN']):04d}"
                fingerprint = (ident, geom.wkb_hex, iso(issue), iso(endtime))
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                yield {"id": ident, "type": KINDS[row["PHENOM"]],
                       "issued": issue, "expired": endtime, "geom": geom,
                       "source_product": row.get("PROD_ID") or "",
                       "status": row.get("STATUS") or "",
                       "ugc": str(row.get("NWS_UGC") or ""),
                       "area_km2": row.get("AREA_KM2") or None}


def parse_warnings(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[r["id"]].append(r)
    result = []
    for ident, parts in sorted(groups.items()):
        issued = min(x["issued"] for x in parts)
        expires = max(x["expired"] for x in parts)
        if expires <= issued:
            continue
        geom = unary_union([p["geom"] for p in parts])
        flags = []
        if len(parts) > 1:
            flags.append("multiple_polygon_records__review_validity")
        if any(p["expired"] != expires for p in parts):
            flags.append("mixed_polygon_expiration__review")
        simplified = geom.simplify(0.002, preserve_topology=True)
        result.append({
            "id": ident, "type": parts[0]["type"],
            "issued": iso(issued), "expired": iso(expires),
            "issued_local": local(issued), "expired_local": local(expires),
            "month": issued.astimezone(CHICAGO).month,
            "hour_local": issued.astimezone(CHICAGO).hour,
            "ugc": ", ".join(sorted({p["ugc"] for p in parts if p["ugc"]})),
            "geometry": mapping(simplified),
            "_geom": geom,
            "_segments": [{"start": p["issued"], "end": p["expired"], "geom": p["geom"]}
                          for p in parts],
            "source_product": next((p["source_product"] for p in parts if p["source_product"]), ""),
            "source_url": f"{BASE}/vtec/?year={issued.year}&wfo=KLIX&phenomena={ident.split('-')[2]}&significance=W&eventid={int(ident[-4:])}",
            "flags": flags,
        })
    return result


def product_timestamp(product_id):
    """IEM product IDs start YYYYMMDDHHMM; this is a text-product timestamp proxy.

    LSR GeoJSON may use product_id_summary in preference to product_id;
    hence the proxy may be a later summary, NOT necessarily first transmission.
    """
    if not product_id:
        return None
    m = re.match(r"^(\d{12})", str(product_id))
    return stamp(m.group(1)) if m else None


def lsr_rows(session, cache, refresh):
    # Fetch occurrence-time windows across BOTH boundaries; GeoJSON capped at 10k.
    # Use <=31-day chunks: LIX storm-report volumes are far below IEM's 10,000-record cap.
    begin = datetime(2024, 12, 29, tzinfo=UTC)
    end = datetime(2026, 1, 4, tzinfo=UTC)
    day = begin
    while day < end:
        nxt = min(day + timedelta(days=31), end)
        params = {"wfos": "LIX", "sts": iso(day)[:16] + "Z",
                  "ets": iso(nxt)[:16] + "Z"}
        key = f"lsr_{day:%Y%m%d}.json"
        payload = get_bytes(session, f"{BASE}/geojson/lsr.geojson",
                            params, Path(cache) / key, refresh)
        obj = json.loads(payload)
        features = obj.get("features", [])
        if len(features) >= 10000:
            raise ValueError(f"IEM 10,000-report cap reached for {day:%Y-%m-%d}")
        for feat in features:
            props = feat.get("properties") or {}
            coords = (feat.get("geometry") or {}).get("coordinates") or []
            lat = props.get("lat")
            lon = props.get("lon")
            if len(coords) >= 2:
                lon, lat = coords[:2]
            event = stamp(props.get("valid"))
            if not event:
                continue
            product = str(props.get("product_id") or "")
            publication = product_timestamp(product)
            flag = []
            if not product or not publication:
                flag.append("no_product_timestamp")
            if publication and publication < event - timedelta(minutes=5):
                flag.append("product_before_occurrence__invalid")
                publication = None
            if publication and publication > event + timedelta(days=31):
                flag.append("product_timestamp_unreasonably_late")
                publication = None
            try:
                lat, lon = float(lat), float(lon)
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    lat, lon = None, None
            except (ValueError, TypeError):
                lat, lon = None, None
            if lat is None or lon is None:
                flag.append("missing_coordinates")
            typ = str(props.get("typetext") or props.get("type") or "").upper().strip()
            mag = props.get("magf", props.get("magnitude"))
            try:
                mag = float(mag)
                if not math.isfinite(mag):
                    mag = None
            except (ValueError, TypeError):
                mag = None
            remark = str(props.get("remark") or "").strip()
            city = str(props.get("city") or "")
            county = str(props.get("county") or "")
            rid = digest(iso(event), lat, lon, typ, mag, county, remark, product)
            # Key for potential same-event corrections: exact type/location/time,
            # but do not auto-suppress corrected reports without provenance.
            group = digest(iso(event), lat, lon, typ, county)
            yield {"id": rid, "event_group": group, "type": typ,
                   "occurred": iso(event), "disseminated": iso(publication),
                   "lat": lat, "lon": lon, "magnitude": mag,
                   "units": props.get("unit"), "qualifier": props.get("qualifier"),
                   "county": county, "state": props.get("state"),
                   "city": city, "source": props.get("source"), "remarks": remark,
                   "product_id": product,
                   "source_url": f"{BASE}/p.php?pid={product}" if product else None,
                   "flags": flag}

        day = nxt

def parse_lsrs(rows):
    reports = {}
    for r in rows:
        # Adjacent 7-day source calls can contain shared boundary rows.
        reports.setdefault(r["id"], r)
    return sorted(reports.values(), key=lambda r: r["occurred"])


def eligibility(kind, report):
    """Strict candidate vs manual-review vs incompatible; never official verification."""
    typ = report["type"]
    mag = report["magnitude"]
    if kind == "TOR":
        return "candidate" if typ == "TORNADO" else "incompatible"
    if kind == "SVR":
        if typ == "HAIL":
            return "candidate" if mag is not None and mag >= 1.0 else "review" if mag is None else "incompatible"
        if typ in ("TSTM WND GST", "THUNDERSTORM WIND GUST", "TSTM WIND GST"):
            return "candidate" if mag is not None and mag >= 58 else "review" if mag is None else "incompatible"
        if typ in ("TSTM WND DMG", "THUNDERSTORM WIND DAMAGE", "TSTM WIND DMG"):
            return "review"
        return "incompatible"
    if kind == "FFW":
        # Flash flood reports can still be sparse or unverifiable. The research
        # treats typed FLASH FLOOD reports as candidate documentation ONLY.
        if typ == "FLASH FLOOD":
            return "review" if len(report["remarks"].strip()) < 25 else "candidate"
        return "incompatible"
    return "incompatible"


def match(warnings, reports):
    associations = []
    indexed = defaultdict(list)
    for w in warnings:
        indexed[w["id"]] = []
    for r in reports:
        if r["lat"] is None or not r["disseminated"]:
            # Missing publication time must not silently count as timely/late.
            pass
        if r["lat"] is None:
            continue
        point = Point(r["lon"], r["lat"])
        occurred = stamp(r["occurred"])
        candidates = []
        for w in warnings:
            # Compare occurrence, NOT dissemination, against warning validity.
            if occurred < stamp(w["issued"]) or occurred > stamp(w["expired"]):
                continue
            if not any(s["start"] <= occurred <= s["end"] and s["geom"].covers(point)
                       for s in w["_segments"]):
                continue
            q = eligibility(w["type"], r)
            if q != "incompatible":
                candidates.append((w, q))
        overlap = len(candidates) > 1
        for w, q in candidates:
            status = "review" if overlap else q
            assoc = {"warning_id": w["id"], "report_id": r["id"],
                     "event_group": r["event_group"], "eligibility": status,
                     "overlap": overlap, "occurred": r["occurred"],
                     "disseminated": r["disseminated"],
                     "report_type": r["type"], "county": r["county"],
                     "source_product": r["product_id"]}
            associations.append(assoc)
            indexed[w["id"]].append(assoc)
    for w in warnings:
        aa = indexed[w["id"]]
        strict = [a for a in aa if a["eligibility"] == "candidate" and a["disseminated"]]
        missing_time = any(a["eligibility"] in ("candidate", "review") and not a["disseminated"] for a in aa)
        first = min((stamp(a["disseminated"]) for a in strict), default=None)
        expiry = stamp(w["expired"])
        groups = {a["event_group"] for a in strict}
        w["associated_reports"] = len(aa)
        w["strict_reports"] = len(strict)
        w["unique_events"] = len(groups)
        w["review_reports"] = sum(a["eligibility"] == "review" for a in aa)
        w["first_lsr"] = iso(first)
        w["first_lsr_local"] = local(first)
        w["first_after_expiry_minutes"] = round((first - expiry).total_seconds()/60, 1) if first else None
        w["classification"] = (
            "documented_by_expiration" if first and first <= expiry else
            "first_documented_after_expiration" if first else
            "needs_review" if aa else "no_candidate_lsr"
        )
        if missing_time:
            w["flags"].append("associated_lsr_missing_product_timestamp")
        if any(a["overlap"] for a in aa):
            w["flags"].append("report_overlaps_multiple_warnings__withheld")
        if any(a["eligibility"] == "review" for a in aa):
            w["flags"].append("potential_reports_require_review")
        w["cumulative"] = {
            str(n): bool(first and first <= expiry + timedelta(hours=n))
            for n in WINDOWS
        }
    return associations


def export(warnings, reports, associations, output):
    out = Path(output)
    (out / "data").mkdir(parents=True, exist_ok=True)
    # Never serialize private Shapely objects.
    for w in warnings:
        w.pop("_geom", None)
        w.pop("_segments", None)
    relevant_ids = {a["report_id"] for a in associations}
    matched = [r for r in reports if r["id"] in relevant_ids]
    eligible_ids = {a["report_id"] for a in associations if a["eligibility"] == "candidate"}
    delays = []
    for r in matched:
        event, pub = stamp(r["occurred"]), stamp(r["disseminated"])
        if pub and event and pub >= event and r["id"] in eligible_ids:
            delay = (pub - event).total_seconds() / 60
            delays.append(round(delay, 1))
        else:
            delay = None
        r["delay_minutes"] = round(delay, 1) if delay is not None else None
    total = len(warnings)
    documented = sum(bool(w["first_lsr"]) for w in warnings)
    late = sum(w["classification"] == "first_documented_after_expiration" for w in warnings)
    review = sum(w["classification"] == "needs_review" for w in warnings)
    counts = Counter(w["classification"] for w in warnings)
    overview = {
        "warnings": total,
        "documented": documented,
        "late_first": late,
        "not_matched": counts["no_candidate_lsr"],
        "needs_review": review,
        "median_delay_minutes": round(float(pd.Series(delays).median()), 1) if delays else None,
        "late_percent_of_documented": round(100*late/documented, 1) if documented else None,
        "windows": {str(n): sum(w["cumulative"][str(n)] for w in warnings) for n in WINDOWS},
    }
    output_data = {
        "metadata": {
            "year": 2025, "office": "LIX", "generated_utc": iso(datetime.now(UTC)),
            "method": "Conservative point-in-issuance-polygon and occurrence-in-validity screening",
            "warnings_source": f"{BASE}/request/gis/watchwarn.phtml",
            "reports_source": f"{BASE}/geojson/lsr.geojson",
            "publication_caveat": "IEM GeoJSON product_id can favor a later summary product. The timestamp is a PRODUCT-LINKED PROXY, not confirmed first issuance or forecaster receipt.",
            "warning_archive_rows": total,
            "lsr_records_downloaded": len(reports),
            "lsr_records_spatially_and_temporally_associated": len(matched),
            "associated_pairs": len(associations),
            "cumulative_denominator": total,
        },
        "overview": overview, "warnings": warnings,
        "reports": matched, "associations": associations,
        "unassociated_report_count": len(reports) - len(matched),
    }
    if not warnings:
        raise RuntimeError("No warning records; refusing to build an empty dashboard")
    if not reports:
        raise RuntimeError("No IEM LSR records; refusing to publish an empty analysis")
    if not any(r["disseminated"] for r in reports):
        raise RuntimeError("No LSR publication proxy timestamps; cannot analyze delay")
    (out / "data" / "results.json").write_text(
        json.dumps(output_data, separators=(",", ":"), default=str), encoding="utf-8")
    for filename, objects in (
        ("warnings.csv", warnings), ("reports.csv", matched),
        ("associations.csv", associations)):
        table = pd.DataFrame([{k: v for k, v in obj.items() if k not in ("geometry", "cumulative", "flags")}
                              | ({"flags": ";".join(obj.get("flags", []))}
                                 if "flags" in obj else {})
                              for obj in objects])
        table.to_csv(out / "data" / filename, index=False)
    summary = [
        "# LIX 2025: preliminary source-linked LSR documentation analysis",
        f"Generated: {output_data['metadata']['generated_utc']}",
        f"Warnings: {total}",
        f"Warnings with strictly matched, timestamped candidate LSR: {documented}",
        f"Of those, first source-linked publication after expiry: {late}",
        f"No matching candidate/review LSR in this source: {overview['not_matched']}",
        f"Warnings requiring manual review with no strict candidate: {review}",
        f"Median occurrence-to-product-linked-time delay (strict report records): {overview['median_delay_minutes']} minutes",
        f"Percent late first among source-documented: {overview['late_percent_of_documented']}%",
        "",
        "Not official warning verification. Does not prove a report was unknown to forecasters or follow-up was performed.",
        "IMPORTANT: IEM LSR GeoJSON product_id may reference a later summary rather than the first LSR product.",
        "No LSR identified is NOT synonymous with an unverified warning.",
        "See methodology.html for limitations and exact rules.",
    ]
    (out / "data" / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(json.dumps(overview, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default=".cache/iem")
    parser.add_argument("--output", default="site")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    session.headers["Accept"] = "application/json, */*"
    print("Fetching 2025 IEM warning polygons...", flush=True)
    warnings = parse_warnings(warning_rows(session, args.cache, args.refresh))
    print("Warning events:", len(warnings), flush=True)
    print("Fetching IEM LSR GeoJSON and product-linked time proxies...", flush=True)
    reports = parse_lsrs(lsr_rows(session, args.cache, args.refresh))
    print("LSR records:", len(reports), flush=True)
    associations = match(warnings, reports)
    export(warnings, reports, associations, args.output)


if __name__ == "__main__":
    main()
