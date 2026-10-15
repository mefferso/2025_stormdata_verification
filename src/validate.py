"""Validate report-centered published results and CSV referential integrity."""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

TYPES = {'SVR', 'FFW'}
TIMING = {'archive_confirmed', 'uncertain_correction', 'uncertain_dst', 'proxy_only', 'missing'}
ASSOCIATION = {'candidate', 'overlap_review', 'needs_review', 'unassociated'}
CLASSIFICATIONS = {'candidate_within_8', 'candidate_after_8', 'candidate_untimed', 'needs_review', 'no_candidate_lsr'}
BINS = ('0–1h', '>1–3h', '>3–8h', '>8–12h', '>12–24h', '>24–48h', '>48–72h', '>72–96h', '>96h')


def validate_results(data):
    assert data['metadata']['year'] == 2025
    warnings, reports, associations = (data[k] for k in ('warnings', 'reports', 'associations'))
    assert warnings and reports and associations, 'Empty study output'
    wids = {w['id'] for w in warnings}
    rids = {r['id'] for r in reports}
    assert len(wids) == len(warnings) and len(rids) == len(reports), 'Duplicate output IDs'
    assert all(w['type'] in TYPES and w['issued'].startswith('2025-') for w in warnings), 'Out-of-scope warning'
    assert all(w['geometry']['type'] in ('Polygon', 'MultiPolygon') and w['geometry']['coordinates'] for w in warnings)
    assert all(w['classification'] in CLASSIFICATIONS for w in warnings)
    assert all(r['phenomenon'] in TYPES and r['timing_status'] in TIMING and r['association_status'] in ASSOCIATION for r in reports)
    assert all(a['warning_id'] in wids and a['report_id'] in rids and a['eligibility'] in ('candidate', 'review') for a in associations)
    assert all(a['phenomenon'] == next(w['type'] for w in warnings if w['id'] == a['warning_id']) for a in associations)
    assert data['metadata']['associated_pairs'] == len(associations)
    assert data['metadata']['raw_text_event_rows_examined'] > 0
    assert all(r['source_url'].startswith('https://mesonet.agron.iastate.edu/') for r in reports if r.get('source_url'))
    assoc_by_report = {}
    for a in associations:
        assoc_by_report.setdefault(a['report_id'], []).append(a)
    for r in reports:
        links = assoc_by_report.get(r['id'], [])
        assert sorted(r['possible_warning_ids']) == sorted({a['warning_id'] for a in links})
        primary = [a for a in links if a['attribution'] == 'primary']
        if r['association_status'] == 'candidate':
            assert len(primary) == 1 and primary[0]['warning_id'] == r['primary_warning_id'] and primary[0]['eligibility'] == 'candidate'
            assert r['warning_issued'] and r['warning_source_url']
        else:
            assert not primary and r['primary_warning_id'] is None
        if r['timing_status'] == 'archive_confirmed':
            assert r['raw_provenance'] and r['first_issued'] == min(p['issued'] for p in r['raw_provenance'])
            assert r['earliest_source_url'] and r['earliest_source_url'].startswith('https://mesonet.agron.iastate.edu/')
        else:
            assert r['first_issued'] is None, 'Uncertain timestamp used as verified first issuance'
        delay = r['delay_minutes']
        assert delay is None or isinstance(delay, (int, float)) and math.isfinite(delay)
        if delay is not None:
            assert r['association_status'] == 'candidate' and r['timing_status'] == 'archive_confirmed'
        assert r['delay_bin'] in BINS or r['delay_bin'] is None
        assert r['delay_bin'] is None if delay is None or delay < 0 else r['delay_bin'] in BINS
    overview = data['overview']
    assert overview['warnings'] == len(warnings)
    candidates = [r for r in reports if r['association_status'] == 'candidate']
    timed = [r for r in candidates if r['delay_minutes'] is not None and r['delay_minutes'] >= 0]
    assert overview['associated_lsrs'] == len(candidates)
    assert overview['reliably_timed_lsrs'] == len(timed)
    assert overview['timing_unknown_or_pre_warning'] == len(candidates) - len(timed)
    assert overview['within_8'] + overview['beyond_8'] == len(timed)
    assert overview['within_8'] == sum(r['delay_minutes'] <= 480 for r in timed)
    assert overview['beyond_8'] == sum(r['delay_minutes'] > 480 for r in timed)
    assert overview['source_svr_lsrs'] == sum(r['source_scope_2025'] and r['phenomenon'] == 'SVR' for r in reports)
    assert overview['source_ffw_lsrs'] == sum(r['source_scope_2025'] and r['phenomenon'] == 'FFW' for r in reports)
    wc = Counter(w['classification'] for w in warnings)
    assert overview['warnings_first_within_8'] == wc['candidate_within_8']
    assert overview['warnings_first_after_8'] == wc['candidate_after_8']
    assert overview['warnings_with_candidate'] == sum(w['candidate_lsr_count'] > 0 for w in warnings)
    for phenomenon in TYPES:
        group = data['by_phenomenon'][phenomenon]
        subset = [r for r in timed if r['phenomenon'] == phenomenon]
        assert group['reliably_timed_lsrs'] == len(subset)
        assert sum(group['bins'].values()) == len(subset)
        assert set(group['bins']) == set(BINS)
        assert group['within_8'] + group['beyond_8'] == len(subset)
        assert group['source_lsrs'] == sum(r['source_scope_2025'] and r['phenomenon'] == phenomenon for r in reports)
        values = list(group['cumulative'].values())
        assert values == sorted(values) and all(0 <= x <= len(subset) for x in values)
    return Counter(w['type'] for w in warnings)


def validate_files(root):
    root = Path(root)
    data = json.loads((root / 'results.json').read_text(encoding='utf-8'))
    counts = validate_results(data)
    for filename, key in (('warnings.csv', 'warnings'), ('reports.csv', 'reports'), ('associations.csv', 'associations')):
        with (root / filename).open(newline='', encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == len(data[key]), f'{filename} row count mismatch'
        if key == 'warnings':
            assert all(row['type'] in TYPES for row in rows)
        if key == 'associations':
            assert all(row['warning_id'] in {w['id'] for w in data['warnings']} and row['report_id'] in {r['id'] for r in data['reports']} for row in rows)
    with (root / 'raw_provenance.csv').open(newline='', encoding='utf-8') as stream:
        provenance = list(csv.DictReader(stream))
    assert len(provenance) == sum(len(r['raw_provenance']) for r in data['reports'])
    assert (root / 'summary.txt').is_file()
    return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print('Validated warning types:', dict(validate_files(args.directory)))
