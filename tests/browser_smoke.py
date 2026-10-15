"""Run against the published Pages URL after deployment, with a real browser."""
import sys
from collections import Counter
from playwright.sync_api import sync_playwright, expect

URL = sys.argv[1] if len(sys.argv) > 1 else "https://mefferso.github.io/2025_stormdata_verification/"


def check(page):
    errors = []
    critical = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("response", lambda response: critical.append(f"{response.status} {response.url}")
            if response.status in (401, 403, 404) and any(x in response.url for x in
            ("2025_stormdata_verification", "plotly", "leaflet", "tile.openstreetmap.org", "arcgisonline")) else None)
    data = page.request.get(URL.rstrip("/") + "/data/results.json").json()
    counts = Counter(w["type"] for w in data["warnings"])
    assert set(counts) == {"SVR", "FFW"}
    total = len(data["warnings"])
    page.goto(URL, wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#tableCount")).to_contain_text(f"{total} / {total}", timeout=90000)
    assert "TOR" not in page.locator("#warningRows").inner_text()
    for chart in ("statusChart", "windowChart", "delayChart", "cumulativeChart", "typeChart", "hourChart"):
        expect(page.locator(f"#{chart} .js-plotly-plot")).to_be_visible(timeout=45000)
    assert page.locator("#typeChart .js-plotly-plot").count() == 1
    page.locator("#typeFilter").select_option("SVR")
    expect(page.locator("#tableCount")).to_contain_text(f"{counts['SVR']} / {total}")
    page.locator("#typeFilter").select_option("FFW")
    expect(page.locator("#tableCount")).to_contain_text(f"{counts['FFW']} / {total}")
    page.locator("#typeFilter").select_option("")
    first_id = page.locator("#warningRows tr[data-id]").first.get_attribute("data-id")
    page.locator("#searchFilter").fill(first_id)
    expect(page.locator("#tableCount")).to_contain_text(f"1 / {total}")
    page.locator("#warningRows tr[data-id]").first.click()
    expect(page.locator("#warningDetail h3").first).to_have_text(first_id)
    page.locator("#searchFilter").fill("")
    page.locator("#polygonToggle").uncheck()
    assert not page.evaluate("dashboardDiagnostics.map.hasLayer(dashboardDiagnostics.polygonLayer)")
    page.locator("#polygonToggle").check()
    page.locator("#reportToggle").uncheck()
    assert not page.evaluate("dashboardDiagnostics.map.hasLayer(dashboardDiagnostics.reportLayer)")
    page.locator("#reportToggle").check()
    map_counts = page.evaluate("({polygons:dashboardDiagnostics.polygonLayer.getLayers().length, reports:dashboardDiagnostics.reportLayer.getLayers().length})")
    assert map_counts["polygons"] == total and map_counts["reports"] > 0, map_counts
    assert page.locator("#map .leaflet-overlay-pane path").count() > 0
    page.locator("#resetMap").click()
    assert page.evaluate("dashboardDiagnostics.map.getBounds().isValid()")
    with page.expect_download() as download_info:
        page.locator("#filteredExport").click()
    assert download_info.value.suggested_filename == "lix-2025-filtered.csv"
    for path in ("warnings.csv", "reports.csv", "associations.csv"):
        response = page.request.get(URL.rstrip("/") + "/data/" + path)
        assert response.ok and "text" in response.headers.get("content-type", ""), path
    tile = page.locator("#map img.leaflet-tile-loaded").first
    expect(tile).to_be_visible(timeout=30000)
    assert tile.evaluate("img => img.naturalWidth > 0")
    assert not errors, errors
    assert not critical, critical
    print("Published browser smoke passed:", map_counts, "loaded tile", tile.get_attribute("src"))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    try:
        check(page)
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator("#map")).to_be_visible()
        assert page.evaluate("dashboardDiagnostics.map.getSize().x > 0")
        print("Mobile map viewport passed")
    finally:
        browser.close()
