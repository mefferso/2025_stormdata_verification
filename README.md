# LIX storm report timing dashboard

**2025 WFO New Orleans/Baton Rouge (LIX)** research dashboard for severe thunderstorm (SVR) and flash flood (FFW) warnings and Local Storm Reports (LSRs).

**Published dashboard:** https://mefferso.github.io/2025_stormdata_verification/

## Research question

How long after an **original warning issuance** did its candidate supporting LSR first appear in the available IEM archived `LSRLIX` text products? The dashboard emphasizes reports published within the first eight hours and those published later, including several days afterward. This is a documentation timing study, not official NWS warning verification or evidence of when a forecaster received information.

## Data and definitions

- Original 2025 SVR and FFW warning episodes and polygons come from the IEM warning GIS archive. Warning IDs include original issuance time, because VTEC event tracking numbers can be reused.
- Event details come from IEM LSR GeoJSON. Repeated source records for the same event, type, location, and county or parish are collapsed. Tornado reports are outside this study.
- First publication time comes from the earliest exact matching `LSRLIX` row in IEM's archived raw text products, downloaded month by month. The archive ZIP entry index, product link, and SHA-256 of the product text are exported. The GeoJSON `product_id` may point to a later summary; it is shown as a proxy and never substituted for an unconfirmed first issuance.
- Candidate association requires an LSR event inside a warning polygon during its valid period and a conservative event type and impact screen. Overlapping candidate warnings receive no primary attribution. Uncertain corrections, missing raw matches, and ambiguous local times remain visible but are excluded from reliable delay percentages.
- The denominator for the 8-hour percentages is **uniquely attributed candidate LSRs with a confirmed first text product and a nonnegative original-issuance-to-publication interval**. Distinct warnings are counted separately from reports.

See [methodology](site/methodology.html) for detailed definitions, source links, and limitations.

## Build and publish

GitHub Actions builds the data from public archives on each push or manual dispatch, runs Python and JavaScript checks, bundles pinned Plotly, Leaflet, and Leaflet.markercluster libraries, publishes the static site to GitHub Pages, and tests the published page in Chromium. Manual dispatch offers a `refresh` option to ignore cached archive slices.

Locally with Python 3.12:

```sh
pip install -r requirements.txt
python -m pytest tests -q
python -m src.build --cache .cache/iem --output site
python -m src.validate site/data
node tests/test_frontend.cjs
```

Serve `site/` with a static file server. The data in `site/data/` are generated from real archive records; no sample records are used as published results.

## What the dashboard includes

A full-year overview with explicit denominators; non-overlapping delay bins and cumulative percentages by phenomenon; long-delay counts beyond 24, 48, 72, and 96 hours; searchable LSR and warning explorers; raw-product provenance and source links; a clustered map whose report shapes distinguish SVR and FFW; CSV downloads and chart export.

## Limits

IEM is an archive, not a guarantee that every original NWS dissemination is present. The earliest product found there does not prove the true first release or when forecasters knew about the event. Initial warning polygons may miss later changes. Automated candidate screens need human review, especially qualitative wind damage and flash flood impact. A warning with no candidate LSR is not necessarily unverified.

Credit Iowa Environmental Mesonet / Iowa State University for IEM datasets and the issuing NWS office for products.
