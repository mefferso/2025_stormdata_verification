"""Report-level timing, attribution, and provenance regression tests."""
import io
import json
import warnings
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from shapely.geometry import box

from src.build import parse_warnings, stamp
from src.lsr_text import parse_archive, reconcile
from src.research import associate, consolidate_reports, delay_bin, eligibility, summarize
from src.validate import validate_results


def warning(etn='2025-LIX-SV-W-0001', kind='SVR', issued='2025-05-01T01:00Z', expired='2025-05-01T02:00Z'):
    return {'id': etn, 'type': kind, 'issued': stamp(issued), 'expired': stamp(expired),
            'initial_expiration': stamp(expired), 'geom': box(-91, 30, -90, 31),
            'source_product': '202505010100-KLIX-WUUS54-SVRLIX', 'status': 'NEW',
            'ugc': '', 'area_km2': 123}


def report(ident='source-1', kind='HAIL', occurred='2025-05-01T01:30:00Z',
           magnitude=1.25, remarks='Quarter sized hail near town', lat=30.5, lon=-90.5,
           product='202505010930-KLIX-NWUS54-LSRLIX'):
    return {'id': ident, 'event_group': ident, 'type': kind, 'occurred': occurred,
            'disseminated': '2025-05-01T09:30:00Z', 'lat': lat, 'lon': lon,
            'magnitude': magnitude, 'county': 'Tangipahoa', 'city': 'Town',
            'remarks': remarks, 'product_id': product, 'source_url': 'https://mesonet.agron.iastate.edu/p.php?pid='+product,
            'flags': []}


def raw_entry(kind='HAIL', issued='2025-05-01T09:30:00Z', remarks='Quarter sized hail near town'):
    return {'event_local': '04/30/2025 0830 PM', 'type': kind, 'county': 'tangipahoa',
            'lat': 30.5, 'lon': -90.5, 'issued': issued,
            'product_id': '202505010930-KLIX-NWUS54-LSRLIX',
            'source_url': 'https://mesonet.agron.iastate.edu/p.php?pid=202505010930-KLIX-NWUS54-LSRLIX',
            'archive_month': '202505', 'archive_entry': 0, 'text_sha256': 'a'*64,
            'remarks': remarks, 'magnitude_text': 'M1.25 IN'}


def test_reused_etn_becomes_two_warning_episodes():
    first = warning(etn='2025-LIX-FF-W-0002', kind='FFW', issued='2025-03-15T19:10Z', expired='2025-03-15T21:03Z')
    later = warning(etn='2025-LIX-FF-W-0002', kind='FFW', issued='2025-03-29T23:22Z', expired='2025-03-30T00:17Z')
    parsed = parse_warnings([first, later])
    assert len(parsed) == 2 and len({w['id'] for w in parsed}) == 2
    assert all(w['vtec_id'] == '2025-LIX-FF-W-0002' for w in parsed)
    assert parsed[0]['issued'] == '2025-03-15T19:10:00Z'
    assert parsed[1]['issued'] == '2025-03-29T23:22:00Z'


def test_geojson_repeats_count_once_and_tornado_excluded():
    old = report()
    later = report(ident='source-2', product='202505020930-KLIX-NWUS54-LSRLIX')
    tornado = report(ident='tor', kind='TORNADO')
    records = consolidate_reports([old, later, tornado])
    assert len(records) == 1
    assert records[0]['source_record_count'] == 2
    assert len(records[0]['source_product_ids']) == 2
    assert records[0]['phenomenon'] == 'SVR'


def test_earliest_raw_product_overrides_later_geojson_proxy():
    records = consolidate_reports([report()])
    early = raw_entry(issued='2025-05-01T02:30:00Z')
    reconcile(records, [raw_entry(), early])
    r = records[0]
    assert r['timing_status'] == 'archive_confirmed'
    assert r['first_issued'] == '2025-05-01T02:30:00Z'
    assert r['proxy_issued'] == '2025-05-01T09:30:00Z'
    assert 'geojson_links_later_product' in r['flags']


def test_cross_type_correction_is_uncertain():
    records = consolidate_reports([report(kind='TSTM WND GST', magnitude=58)])
    reconcile(records, [raw_entry(kind='MARINE TSTM WIND', issued='2025-05-01T02:30:00Z'),
                        raw_entry(kind='TSTM WND GST')])
    assert records[0]['timing_status'] == 'uncertain_correction'
    assert records[0]['first_issued'] is None


def test_fall_back_local_time_is_flagged_for_review():
    records = consolidate_reports([report(occurred='2025-11-02T06:30:00Z')])
    raw = raw_entry(issued='2025-11-02T08:00:00Z')
    raw['event_local'] = '11/02/2025 0130 AM'
    reconcile(records, [raw])
    assert records[0]['timing_status'] == 'uncertain_dst'
    assert records[0]['first_issued'] is None


def test_duplicate_zip_filenames_preserve_distinct_product_texts():
    def product(event):
        return (f'123\nNWUS54 KLIX 010930\nLSRLIX\n\nPreliminary Local Storm Report\n'
                '..TIME...   ...EVENT...      ...CITY LOCATION...     ...LAT.LON...\n'
                f'0830 PM     {event:<16}Town                    30.50N 90.50W\n'
                '04/30/2025  M1.25 IN         Tangipahoa        LA   Public\n'
                '            Reported near town.\n&&\n$$\n').encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            z.writestr('LSRLIX_202505010930.txt', product('Hail'))
            z.writestr('LSRLIX_202505010930.txt', product('Tstm Wnd Gst'))
    entries = parse_archive(stream.getvalue(), '202505')
    assert len(entries) == 2 and {e['type'] for e in entries} == {'HAIL', 'TSTM WND GST'}
    assert len({e['text_sha256'] for e in entries}) == 2


def test_qualification_requires_specific_flood_impact():
    generic = report(kind='FLASH FLOOD', remarks='Flooding across the parish', magnitude=None)
    specific = report(kind='FLASH FLOOD', remarks='Vehicles stranded on Highway 68 by high water', magnitude=None)
    assert eligibility('FFW', generic) == 'review'
    assert eligibility('FFW', specific) == 'candidate'
    assert eligibility('SVR', report(kind='TORNADO')) == 'incompatible'


def test_report_delay_bins_have_no_overlap_at_eight_hours():
    assert delay_bin(0) == '0–1h'
    assert delay_bin(60) == '0–1h'
    assert delay_bin(61) == '>1–3h'
    assert delay_bin(480) == '>3–8h'
    assert delay_bin(481) == '>8–12h'
    assert delay_bin(5760) == '>72–96h'
    assert delay_bin(5761) == '>96h'
    assert delay_bin(-1) is None


def test_overlap_never_double_counts_primary_report():
    warnings_ = parse_warnings([warning(), warning(etn='2025-LIX-SV-W-0002')])
    records = consolidate_reports([report()])
    reconcile(records, [raw_entry()])
    pairs = associate(warnings_, records)
    assert len(pairs) == 2
    assert records[0]['association_status'] == 'overlap_review'
    assert records[0]['primary_warning_id'] is None
    assert all(p['attribution'] == 'review' for p in pairs)


def test_occurrence_and_polygon_screen_and_eight_hour_issuance_clock():
    w = parse_warnings([warning()])
    records = consolidate_reports([report(), report(ident='outside', lat=35.0)])
    reconcile(records, [raw_entry(issued='2025-05-01T09:00:00Z')])
    pairs = associate(w, records)
    assert len(pairs) == 1
    primary = next(r for r in records if r['association_status'] == 'candidate')
    assert primary['delay_minutes'] == 480
    assert primary['delay_bin'] == '>3–8h'
    summary = summarize(w, records, pairs, 1, '2026-10-15T00:00:00Z')
    assert summary['overview']['within_8'] == 1 and summary['overview']['beyond_8'] == 0
    assert summary['overview']['warnings_first_within_8'] == 1


def test_generated_output_integrity_when_available():
    fixture = Path(__file__).parents[1] / 'site' / 'data' / 'results.json'
    if not fixture.exists():
        pytest.skip('Generated archive not built yet')
    data = json.loads(fixture.read_text())
    if 'by_phenomenon' not in data:
        pytest.skip('Retired local output schema')
    assert sum(validate_results(data).values()) == data['overview']['warnings']
    bad = deepcopy(data)
    bad['associations'][0]['report_id'] = 'missing'
    with pytest.raises(AssertionError):
        validate_results(bad)
