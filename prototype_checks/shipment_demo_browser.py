"""Disposable shipment prototype acceptance; no production API or Ozon calls."""
import base64
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[1]
ARTIFACTS = ROOT / "test-artifacts/shipment-demo"
PAGE = "deliverables/sklad-ozon-shipments-demo.html"

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors, external, checks = [], [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width":1440,"height":1050}, locale="ru-RU", timezone_id="Europe/Moscow")
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            def block(route):
                if not route.request.url.startswith("http://127.0.0.1:"):
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            page.route("**/*", block)
            page.goto(f"http://127.0.0.1:{server.server_port}/{PAGE}")
            assert page.locator("[data-cluster]").count() == 3
            assert page.evaluate("ShipmentDemo.readyNames()") == ["Москва","Ростов-на-Дону","Новосибирск"]
            assert page.locator("#none-demo-moscow").is_checked()
            data = page.evaluate("ShipmentDemo.exportSettings()")
            assert data["requests"][0]["create_at"] is None
            assert data["requests"][0]["automatic_launch"] is False
            assert data["real_requests_created"] is False
            page.screenshot(path=str(ARTIFACTS / "shipments-desktop.png"), full_page=True)
            checks.append("only ready clusters; no-date means manual launch")

            page.locator("#scheduled-demo-moscow").check()
            page.locator("#date-demo-moscow").fill("2026-10-03")
            page.locator("#date-demo-moscow").dispatch_event("change")
            page.locator("#time-demo-moscow").fill("10:45")
            page.locator("#time-demo-moscow").dispatch_event("change")
            page.reload()
            assert page.locator("#scheduled-demo-moscow").is_checked()
            assert page.locator("#date-demo-moscow").input_value() == "2026-10-03"
            assert page.locator("#time-demo-moscow").input_value() == "10:45"
            data = page.evaluate("ShipmentDemo.exportSettings()")
            assert data["requests"][0]["create_at"] == "2026-10-03T10:45:00+03:00"
            assert data["timezone"] == "Europe/Moscow"
            page.locator("#date-demo-moscow").fill("2026-09-29")
            page.locator("#date-demo-moscow").dispatch_event("change")
            page.locator("#prepare").click()
            assert page.locator("#schedule-error-demo-moscow").is_visible()
            assert not page.locator("#review-dialog").is_visible()
            assert page.locator("#date-demo-moscow").evaluate("(n)=>document.activeElement===n")
            page.locator("#none-demo-moscow").check()
            checks.append("schedule persists; Moscow timezone; past dates rejected")

            page.locator("#fix-plan").click()
            page.locator("#pack-39439").fill("0")
            assert page.locator("#pack-error-39439").is_visible()
            assert page.locator("#confirm-39439").is_disabled()
            page.locator("#pack-39439").fill("6")
            page.wait_for_function("ShipmentDemo.getState().manual['39439']?.value===6")
            assert page.locator("#pack-source-39439").inner_text() == "Ручная"
            assert "Казань" not in page.evaluate("ShipmentDemo.readyNames()")
            page.locator("#confirm-39439").click()
            assert "Казань" not in page.evaluate("ShipmentDemo.readyNames()")
            assert "не кратно 6" in page.locator('[data-reason="demo-kazan|1784511149"]').inner_text()
            assert page.locator('[data-quantity="demo-kazan|1784511149"]').input_value() == "10"
            page.locator("#pack-39439").fill("5")
            page.wait_for_function("ShipmentDemo.getState().manual['39439']?.value===5")
            assert page.locator("#confirm-39439").is_enabled()
            assert page.evaluate("ShipmentDemo.getState().manual['39439'].confirmedPlan") is None
            page.screenshot(path=str(ARTIFACTS / "manual-pack.png"), full_page=True)
            page.locator("#confirm-39439").click()
            assert "Казань" in page.evaluate("ShipmentDemo.readyNames()")
            page.locator("#confirm-51916").click()
            assert "Екатеринбург" in page.evaluate("ShipmentDemo.readyNames()")
            page.locator("#repair-done").click()
            assert page.locator("[data-cluster]").count() == 5
            page.reload()
            assert page.locator("[data-cluster]").count() == 5
            assert page.evaluate("ShipmentDemo.getState().manual['39439'].confirmedPlan") == "demo-plan-1"
            checks.append("manual pack autosave and provenance; confirmation; no rounding; reload")

            page.locator('[data-composition="demo-kazan"] summary').click()
            assert page.locator('[data-cluster="demo-kazan"]').evaluate("(n)=>n.classList.contains('is-open')")
            page.locator('[data-cluster="demo-kazan"] [data-edit-pack="39439"]').click()
            page.locator("#pack-39439").fill("2")
            page.wait_for_function("ShipmentDemo.getState().manual['39439'].value===2")
            assert "Казань" not in page.evaluate("ShipmentDemo.readyNames()")
            page.locator("#repair-dialog").press("Escape")
            assert not page.locator("#repair-dialog").is_visible()
            assert page.locator("#fix-plan").evaluate("(n)=>document.activeElement===n")
            checks.append("pack changes invalidate readiness; Escape restores usable focus")

            page.locator("#fix-plan").click()
            page.evaluate("window.savedSet=Storage.prototype.setItem;Storage.prototype.setItem=function(){throw new Error('Synthetic quota failure');}")
            page.locator("#pack-39439").fill("5")
            page.wait_for_function("!document.getElementById('retry-39439').hidden")
            assert page.locator("#pack-39439").input_value() == "5"
            assert page.locator("#confirm-39439").is_disabled()
            assert page.evaluate("ShipmentDemo.getState().manual['39439'].value") == 2
            page.evaluate("Storage.prototype.setItem=window.savedSet")
            page.locator("#retry-39439").click()
            assert page.evaluate("ShipmentDemo.getState().manual['39439'].value") == 5
            page.locator("#confirm-39439").click()
            page.locator("#repair-done").click()
            checks.append("save failure keeps draft and old value; retry required")

            page.locator("#select-all").check()
            page.locator("#prepare").click()
            assert page.locator("#review-body .review-line").count() == 5
            page.locator("#review-cancel").click()
            assert page.locator("#prepare").evaluate("(n)=>document.activeElement===n")
            page.locator("#prepare").click()
            page.locator("#review-confirm").click()
            assert "Реальные заявки не созданы" in page.locator("#feedback").inner_text()
            checks.append("exact selected scope; review/cancel; honest demo result")
            with page.expect_download() as d:
                page.locator("#export-settings").click()
            d.value.save_as(str(ARTIFACTS / "example-settings.json"))
            payload = json.loads((ARTIFACTS / "example-settings.json").read_text())
            assert len(payload["requests"]) == 5
            assert payload["real_requests_created"] is False
            page.locator(".demo-tools summary").click()
            with page.expect_download() as d:
                page.locator("#download-html").click()
            d.value.save_as(str(ARTIFACTS / "downloaded-demo.html"))
            assert "<!doctype html>" in (ARTIFACTS / "downloaded-demo.html").read_text()
            checks.append("JSON and standalone HTML download")
            page.locator("#new-plan").click()
            page.locator("#scenario-confirm").click()
            assert page.locator("[data-cluster]").count() == 3
            assert page.evaluate("ShipmentDemo.getState().manual['39439'].value") == 5
            assert "Казань" not in page.evaluate("ShipmentDemo.readyNames()")
            assert "Екатеринбург" not in page.evaluate("ShipmentDemo.readyNames()")
            checks.append("new plan retains pack values and requires fresh confirmations")

            for width in (320,390,720,1024,1440):
                page.set_viewport_size({"width":width,"height":950})
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"), width
                page.locator("#fix-plan").click()
                assert page.locator("#repair-dialog").evaluate("(n)=>{const r=n.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1}"), width
                page.locator("#repair-dialog").press("Escape")
            page.set_viewport_size({"width":390,"height":900})
            page.emulate_media(reduced_motion="reduce")
            page.screenshot(path=str(ARTIFACTS / "shipments-narrow.png"), full_page=True)
            checks.append("320/390/720/1024/1440 reflow; modal bounds; reduced motion")
            state = page.evaluate("ShipmentDemo.getState()")
            state["quantities"] = {f"{c}|{sku}":0 for c,skus in [
                ("demo-moscow",["1783408913","1783432877"]),
                ("demo-rostov",["1783408913","1783432877"]),
                ("demo-novosibirsk",["1783408913","1783432877"]),
                ("demo-kazan",["1784511149","1783408913"]),
                ("demo-ekaterinburg",["1784511180","1783432877"])
            ] for sku in skus}
            page.evaluate("(s)=>ShipmentDemo.replaceForTest(s)",state)
            assert page.locator("[data-cluster]").count() == 0
            assert page.locator(".empty").is_visible()
            assert page.locator("#prepare").is_disabled()
            checks.append("no-ready empty state; zero differs from unknown")
            assert not errors,errors
            assert not external,external
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    result={"status":"passed","checks":checks,"screenshots":3,"browser_errors":errors,"external_requests":external}
    (ARTIFACTS / "verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))
    for name in ("shipments-desktop.png", "manual-pack.png", "shipments-narrow.png"):
        encoded=base64.b64encode((ARTIFACTS / name).read_bytes()).decode()
        for offset in range(0,len(encoded),4000):
            print(f"SCREENSHOT|{name}|{offset:09d}|{encoded[offset:offset+4000]}")

if __name__=="__main__":
    main()
