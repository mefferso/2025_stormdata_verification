"""Check the published report-first dashboard in Chromium."""
import sys
import shutil
from collections import Counter
from playwright.sync_api import sync_playwright, expect

URL = sys.argv[1] if len(sys.argv) > 1 else "https://mefferso.github.io/2025_stormdata_verification/"


def check(page):
    errors, critical = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("response", lambda response: critical.append(f"{response.status} {response.url}")
            if response.status in (401, 403, 404) and "2025_stormdata_verification" in response.url else None)
    root = URL.rstrip("/")
    data = page.request.get(root + "/data/results.json").json()
    reports, warnings = data["reports"], data["warnings"]
    report_counts = Counter(r["phenomenon"] for r in reports)
    warning_counts = Counter(w["type"] for w in warnings)
    assert set(report_counts) == set(warning_counts) == {"SVR", "FFW"}
    page.goto(URL, wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#reportCount")).to_contain_text(f"{len(reports)} / {len(reports)}", timeout=90000)
    expect(page.locator("#warningCount")).to_contain_text(f"{len(warnings)} / {len(warnings)}")
    assert page.locator("#metrics .metric").count() == 6
    for chart in ("distributionChart", "eightHourChart", "cumulativeChart", "longDelayChart", "warningChart"):
        expect(page.locator(f"#{chart}.js-plotly-plot")).to_be_visible(timeout=45000)
    page.locator("#reportType").select_option("FFW")
    expect(page.locator("#reportCount")).to_contain_text(f"{report_counts['FFW']} / {len(reports)}")
    page.locator("#reportDelay").select_option("beyond24")
    expect(page.locator("#reportCount")).to_contain_text(f"{data['by_phenomenon']['FFW']['beyond_24']} / {len(reports)}")
    page.locator("#resetReportFilters").click()
    first_id = page.locator("#reportRows tr[data-id]").first.get_attribute("data-id")
    page.locator("#reportSearch").fill(first_id)
    expect(page.locator("#reportCount")).to_contain_text(f"1 / {len(reports)}")
    page.locator("#reportRows tr[data-id]").first.click()
    expect(page.locator("#reportDetail")).to_contain_text("raw LSR text", timeout=10000)
    page.locator("#reportSearch").fill("")
    page.locator("#warningType").select_option("SVR")
    expect(page.locator("#warningCount")).to_contain_text(f"{warning_counts['SVR']} / {len(warnings)}")
    page.locator("#resetWarningFilters").click()
    page.locator("#warningRows tr[data-id]").first.click()
    expect(page.locator("#warningDetail")).to_contain_text("Original issue")
    map_counts = page.evaluate("""() => ({reports:dashboardDiagnostics.markers.size, polygons:dashboardDiagnostics.polygonLayer.getLayers().length, clustered:typeof L.markerClusterGroup === 'function', shapes:[...dashboardDiagnostics.markers.values()].map(m=>m.options.icon.options.html)})""")
    assert map_counts["reports"] > 0 and map_counts["polygons"] == len(warnings)
    assert map_counts["clustered"]
    assert any("<circle" in html for html in map_counts["shapes"])
    assert any("<path" in html for html in map_counts["shapes"])
    page.locator("#mapSVR").uncheck()
    assert page.evaluate("dashboardDiagnostics.markersLayer.getLayers().length") < map_counts["reports"]
    page.locator("#mapFFW").uncheck()
    assert page.evaluate("dashboardDiagnostics.markersLayer.getLayers().length") == 0
    page.locator("#resetMapFilters").click()
    assert page.evaluate("dashboardDiagnostics.markersLayer.getLayers().length") == map_counts["reports"]
    page.locator("#mapPolygons").check()
    assert page.evaluate("dashboardDiagnostics.map.hasLayer(dashboardDiagnostics.polygonLayer)")
    page.locator("#resetMap").click()
    assert page.evaluate("dashboardDiagnostics.map.getBounds().isValid()")
    with page.expect_download() as download_info:
        page.locator("#reportExport").click()
    assert download_info.value.suggested_filename == "lix-2025-filtered-lsrs.csv"
    for path in ("reports.csv", "warnings.csv", "associations.csv", "raw_provenance.csv", "summary.txt"):
        assert page.request.get(root + "/data/" + path).ok, path
    tile = page.locator("#map img.leaflet-tile-loaded").first
    expect(tile).to_be_visible(timeout=30000)
    assert tile.evaluate("img => img.naturalWidth > 0")
    page.evaluate("""() => { const layer = Object.values(dashboardDiagnostics.map._layers).find(item => item instanceof L.TileLayer && item._url.includes('tile.openstreetmap.org')); if (!layer) throw Error('Primary basemap missing'); layer.fire('tileerror'); layer.fire('tileerror'); }""")
    fallback = page.locator("#map img.leaflet-tile-loaded[src*='arcgisonline.com']").first
    expect(fallback).to_be_visible(timeout=30000)
    assert fallback.evaluate("img => img.naturalWidth > 0")
    assert not errors, errors
    assert not critical, critical
    print("Published browser smoke passed", {"reports": len(reports), "warnings": len(warnings)})

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path=shutil.which("chromium"), args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    try:
        check(page)
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator("#map")).to_be_visible()
        assert page.evaluate("dashboardDiagnostics.map.getSize().x > 0")
        print("Mobile map viewport passed")
    finally:
        browser.close()
