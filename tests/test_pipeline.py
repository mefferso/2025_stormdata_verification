"""Offline tests covering temporal, spatial and evidence classification edge cases."""
from shapely.geometry import box
from src.build import eligibility, match, parse_lsrs, parse_warnings, product_timestamp, stamp
from src.validate import validate_results

def warning(ident="2025-LIX-SV-W-0001", kind="SVR", start="2025-05-01T01:00Z",
            stop="2025-05-01T02:00Z"):
    return {"id": ident, "type": kind, "issued": stamp(start),
            "expired": stamp(stop), "geom": box(-91,30,-90,31),
            "source_product": "202505010100-KLIX-WUUS54-SVRLIX", "status": "NEW",
            "ugc": "", "area_km2": 123}

def report(id="r1", event="2025-05-01T01:30Z", pub="2025-05-01T05:30Z", lat=30.5, lon=-90.5,
           typ="HAIL", mag=1.25, remark="Quarter sized hail reported near town"):
    return {"id":id,"event_group":id,"type":typ,"occurred":event,
            "disseminated":pub,"lat":lat,"lon":lon,"magnitude":mag,
            "county":"Tangipahoa","remarks":remark,"product_id":"202505010530-KLIX-NWUS54-LSRLIX"}

def run(ws,rs):
    ww=parse_warnings(ws)
    aa=match(ww,rs)
    return ww,aa

def test_product_timestamp():
    assert stamp("202505010530").hour==5
    assert product_timestamp("202505010530-KLIX-NWUS54-LSRLIX").hour==5
    assert product_timestamp("invalid") is None

def test_late_support():
    ws,aa=run([warning()], [report()])
    assert len(aa)==1
    assert ws[0]["classification"]=="first_documented_after_expiration"
    assert ws[0]["first_after_expiry_minutes"]==210
    assert ws[0]["cumulative"]["3"] is False
    assert ws[0]["cumulative"]["6"] is True

def test_pre_expiry_documentation():
    ws,_=run([warning()],[report(pub="2025-05-01T01:45Z")])
    assert ws[0]["classification"]=="documented_by_expiration"

def test_event_occurs_after_warning_cannot_count():
    ws,aa=run([warning()],[report(event="2025-05-01T02:01Z",pub="2025-05-01T03:00Z")])
    assert not aa and ws[0]["classification"]=="no_candidate_lsr"

def test_event_outside_polygon_cannot_count():
    ws,aa=run([warning()],[report(lat=35.0)])
    assert not aa and ws[0]["classification"]=="no_candidate_lsr"

def test_overlapping_warnings_must_be_reviewed():
    ws,aa=run([warning(),warning(ident="2025-LIX-SV-W-0002")],[report()])
    assert len(aa)==2 and all(a["eligibility"]=="review" for a in aa)
    assert all(w["classification"]=="needs_review" for w in ws)

def test_magnitude_and_qualitative_evidence():
    assert eligibility("SVR",report(mag=.75))=="incompatible"
    assert eligibility("SVR",report(mag=1))=="candidate"
    assert eligibility("SVR",report(typ="TSTM WND DMG",mag=None))=="review"
    assert eligibility("SVR",report(typ="TSTM WND GST",mag=58))=="candidate"

def test_flash_flood_details():
    assert eligibility("FFW",report(typ="FLASH FLOOD",remark="Flooding"))=="review"
    assert eligibility("FFW",report(typ="FLASH FLOOD",remark="Several vehicles stranded in rapid flash flooding"))=="candidate"

def test_ffw_only_association_and_tornado_lsr_exclusion():
    ffw = warning(ident="2025-LIX-FF-W-0001", kind="FFW")
    flood = report(typ="FLASH FLOOD", remark="Several vehicles stranded in rapid flash flooding")
    tornado = report(id="r2", typ="TORNADO", remark="Tornado reported in the same warning area")
    ws, aa = run([ffw], [flood, tornado])
    assert len(ws) == 1 and ws[0]["type"] == "FFW"
    assert [a["report_id"] for a in aa] == [flood["id"]]
    assert ws[0]["classification"] == "first_documented_after_expiration"

def test_svr_only_association():
    ws, aa = run([warning()], [report(), report(id="r2", typ="TORNADO")])
    assert len(aa) == 1 and aa[0]["report_id"] == "r1"
    assert ws[0]["strict_reports"] == 1

def test_missing_product_timestamp_is_not_on_time():
    ws,aa=run([warning()],[report(pub=None)])
    assert len(aa)==1 and ws[0]["classification"]=="needs_review"
    assert "associated_lsr_missing_product_timestamp" in ws[0]["flags"]

def test_early_cancellation_or_segment_end():
    ws,aa=run([warning(stop="2025-05-01T01:15Z")],[report()])
    assert not aa

def test_duplicate_source_chunks_deduplicate():
    r=report()
    assert len(parse_lsrs([r,r]))==1

def test_cross_year_event():
    ws,aa=run([warning(start="2025-12-31T23:45Z",stop="2026-01-01T00:30Z")],
              [report(event="2026-01-01T00:15Z",pub="2026-01-01T04:00Z")])
    assert len(aa)==1 and ws[0]["classification"]=="first_documented_after_expiration"

def test_tornado_warning_excluded_even_if_passed_to_parser():
    tor = warning(ident="2025-LIX-TO-W-0001", kind="TOR")
    svr = warning()
    ffw = warning(ident="2025-LIX-FF-W-0002", kind="FFW")
    parsed = parse_warnings([tor, svr, ffw])
    assert {w["type"] for w in parsed} == {"SVR", "FFW"}
    assert len(parsed) == 2

def test_validator_rejects_non_scope_warning():
    from copy import deepcopy
    from pathlib import Path
    import json
    fixture = Path(__file__).parents[1] / "site" / "data" / "results.json"
    if not fixture.exists():
        return  # CI builds archive after offline unit tests.
    data = json.loads(fixture.read_text())
    assert validate_results(data)["SVR"] > 0
    bad = deepcopy(data)
    bad["warnings"][0]["type"] = "TOR"
    import pytest
    with pytest.raises(AssertionError, match="Non SVR/FFW"):
        validate_results(bad)
