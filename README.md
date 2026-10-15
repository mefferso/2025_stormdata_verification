# LIX Storm Report & Warning Analysis

**2025 WFO New Orleans/Baton Rouge (LIX)** retrospective analysis of severe thunderstorm and flash flood warnings and archived Local Storm Reports.

**Live URL (published via GitHub Pages):** https://mefferso.github.io/2025_stormdata_verification/

## Purpose

How much of our severe weather picture appears in *source-linked LSR products* after warnings have expired? This is documentation research **not official NWS warning verification**. The dashboard never uses sample or invented statistics as actual results. If ingest fails, publication fails and the site displays an explicit missing-data notice.

## Data

- Warning storm-based polygons and VTEC metadata: IEM warning GIS shapefile service (LIX, SV.W/FF.W, issued in 2025).
- Local Storm Reports: IEM LSR GeoJSON service, up-to-31-day occurrence-time chunks from 2024-12-29 through 2026-01-04.
- Report occurrence: IEM LSR \`valid\`; product-linked proxy time: 12-digit prefix of IEM GeoJSON \`product_id\`. **Critical:** the GeoJSON may prefer a *later summary product ID*, not the first dissemination. Product-linked time is not actual forecaster receipt time. See [methodology](site/methodology.html).

Candidate documentation requires an LSR point covered by an applicable warning polygon and its **event occurrence** within valid time. Candidate classes: SVR → hail >=1.0" or thunderstorm gust >=58 mph; FFW → FLASH FLOOD with substantive remarks. Qualitative wind damage, sparse flash flood reports, overlapping warnings, missing product times and incomplete magnitudes remain subject to manual review. All classification labels are **research screens**.

## Build

GitHub Actions on push or manual dispatch fetches source archives, runs offline and generated-data tests, bundles pinned Leaflet and Plotly assets, creates JSON / CSV / summary outputs, publishes the static dashboard to Pages, and runs a Chromium smoke test against the published site. Check [Actions](https://github.com/mefferso/2025_stormdata_verification/actions). Manual dispatch has a **refresh** option to disregard cached archive slices.

Locally, with Python 3.12:

    pip install -r requirements.txt
    python -m pytest tests -q
    python -m src.build --cache .cache/iem --output site

Run a static file server in \`site/\` to browse. Files in \`site/data\` are created only from downloaded actual archives and are not hand-filled.

## User interface

Full-year overview with denominators; source-product lag distribution and cumulative lag curve; warning-type and time-of-day views; sortable/searchable/filterable warning explorer; detailed chronology and source links; Leaflet map with OpenStreetMap and Esri Light Gray Canvas fallback; CSV data downloads, filtered CSV and Plotly SVG/PNG chart exports.

## QC and known limits

See [methodology](site/methodology.html), which details the source, limitation and each metric. IEM is not a complete official record. Initial warning polygons may miss later updates or early cancellation effects. A report can be known before its product was issued. One event may have multiple corrections. Ambiguous shared reports are **not** counted as strict evidence for every warning. A missing candidate report is **not** an unverified warning.

The pipeline refuses to produce a valid dashboard if there are zero warnings, zero LSRs, or no usable source-product timestamps. It does **not** guarantee original first LSR issuance because the IEM GeoJSON may choose a later summary product.

## License and data citation

Code is provided for internal research and educational reuse. Credit Iowa Environmental Mesonet / Iowa State University for IEM-derived datasets, and the issuing NWS office for products.
