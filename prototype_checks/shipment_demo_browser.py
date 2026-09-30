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
            assert page.locator("[data-date-group]").count() == 2
            assert page.locator("[data-date-group]").evaluate_all("(ns)=>ns.map(n=>n.dataset.dateGroup)") == ["2026-10-02","2026-10-04"]
            colors = page.locator('[data-date-group="2026-10-02"] [data-cluster]').evaluate_all("(ns)=>ns.map(n=>getComputedStyle(n).borderTopColor)")
            assert colors[0] == colors[1]
            page.locator("#sort-date").select_option("desc")
            assert page.locator("[data-date-group]").evaluate_all("(ns)=>ns.map(n=>n.dataset.dateGroup)") == ["2026-10-04","2026-10-02"]
            page.locator("#sort-date").select_option("asc")
            assert page.locator("#method-demo-novosibirsk-PVZ").is_disabled()
            assert page.locator("#method-demo-novosibirsk-SC").is_disabled()
            assert page.locator("#method-demo-novosibirsk-DIRECT").is_enabled()
            assert "KGT" in page.evaluate("ShipmentDemo.compatibility('demo-novosibirsk','PVZ')")
            page.screenshot(path=str(ARTIFACTS / "shipments-desktop.png"), full_page=True)
            checks.append("same delivery date same color; date sorting; KGT blocks incompatible demo points")
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
            page.evaluate("()=>{window.savedSet=Storage.prototype.setItem;Storage.prototype.setItem=function(){throw new Error('Synthetic quota failure');};}")
            page.locator("#pack-39439").fill("5")
            page.wait_for_function("!document.getElementById('retry-39439').hidden")
            assert page.locator("#pack-39439").input_value() == "5"
            assert page.locator("#confirm-39439").is_disabled()
            assert page.evaluate("ShipmentDemo.getState().manual['39439'].value") == 2
            page.evaluate("()=>{Storage.prototype.setItem=window.savedSet;}")
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

            page.set_viewport_size({"width":1440,"height":1050})
            # Local readiness is insufficient for creation: need accepted content + a slot.
            page.locator("#create-demo-moscow").click()
            assert "проверка всего состава" in page.locator("#feedback").inner_text()
            assert not page.locator("#review-dialog").is_visible()
            page.locator("#method-demo-moscow-PVZ").click()
            page.locator("#seller-demo-moscow").select_option("")
            page.locator("#find-demo-moscow").click()
            page.locator("#slot-search").click()
            assert "действующий склад" in page.locator("#slot-result").inner_text()
            page.locator("#slots-dialog").press("Escape")
            page.locator("#seller-demo-moscow").select_option("demo-seller-2")
            checks.append("creation needs accepted evidence and slot; crossdock requires seller warehouse")

            def search_for(cluster, scenario="normal"):
                page.locator(f"#find-{cluster}").click()
                page.locator("#slots-body .doc-note summary").click()
                page.locator("#slot-scenario").select_option(scenario)
                page.locator("#slot-search").click()
                page.wait_for_function("document.getElementById('slot-search')&&!document.getElementById('slot-search').disabled")
            search_for("demo-moscow","empty")
            assert "Нет окон" in page.locator("#slot-result").inner_text()
            assert page.locator("#slots-apply").is_disabled()
            page.locator("#slot-to").fill("2026-10-05")
            page.locator("#slot-to").dispatch_event("change")
            # Collapsed native disclosure does not stop select_option.
            page.locator("#slots-body .doc-note summary").click()
            page.locator("#slot-scenario").select_option("normal")
            page.locator("#slot-search").click()
            page.wait_for_function("document.querySelectorAll('[data-slot-index]').length===8")
            page.screenshot(path=str(ARTIFACTS / "shipment-slots.png"), full_page=True)
            page.locator('[data-slot-index="6"]').click()
            page.locator("#slots-apply").click()
            state = page.evaluate("ShipmentDemo.getState()")
            assert state["config"]["demo-moscow"]["slot"]["day"] == "2026-10-05"
            assert page.locator('[data-cluster="demo-moscow"]').get_attribute("data-day") == "2026-10-05"
            assert page.locator("[data-date-group]").evaluate_all("(ns)=>ns.map(n=>n.dataset.dateGroup)") == ["2026-10-02","2026-10-04","2026-10-05"]
            page.locator("#method-demo-moscow-SC").click()
            assert page.evaluate("ShipmentDemo.getState().config['demo-moscow'].slot") is None
            assert page.evaluate("ShipmentDemo.getState().config['demo-moscow'].evidence") is None
            checks.append("empty windows retain desired date; extended search; explicit slot selection regrouping; route invalidates evidence")

            search_for("demo-moscow")
            page.locator("#slot-storage").select_option("demo-storage-alt-demo-moscow")
            assert page.locator("[data-slot-index]").count() == 0
            page.locator("#slot-search").click()
            page.wait_for_function("document.querySelectorAll('[data-slot-index]').length===8")
            page.locator('[data-slot-index="0"]').click()
            page.locator("#slots-apply").click()
            assert page.evaluate("ShipmentDemo.getState().config['demo-moscow'].evidence.storageId") == "demo-storage-alt-demo-moscow"
            # A failed local save must not silently report that selection was committed.
            search_for("demo-rostov","partial")
            assert "Принят не весь состав" in page.locator("#slot-result").inner_text()
            assert page.locator("#slots-apply").is_disabled()
            draft = page.evaluate("ShipmentDemo.getState().config['demo-rostov'].evidence.draftId")
            page.locator("#slots-dialog").press("Escape")
            page.locator("#create-demo-rostov").click()
            assert not page.locator("#review-dialog").is_visible()
            search_for("demo-rostov","rate")
            assert "429" in page.locator("#slot-result").inner_text()
            assert page.evaluate("ShipmentDemo.getState().config['demo-rostov'].evidence.draftId") == draft
            page.locator("#slots-dialog").press("Escape")
            checks.append("storage warehouse comes from accepted demo response; partial content blocks creation; rate limit preserves known draft")


            # Leaving a pending lookup must discard its late response.
            previous_evidence = page.evaluate("ShipmentDemo.getState().config['demo-rostov'].evidence")
            page.locator("#find-demo-rostov").click()
            page.locator("#slot-search").click()
            page.locator("#slots-dialog").press("Escape")
            page.wait_for_timeout(700)
            assert page.evaluate("ShipmentDemo.getState().config['demo-rostov'].evidence") == previous_evidence
            checks.append("closing pending search discards late response")
            search_for("demo-rostov")
            page.locator('[data-slot-index="0"]').click()
            page.locator("#slots-apply").click()
            page.locator("#scheduled-demo-rostov").check()
            page.locator("#date-demo-rostov").fill("2026-10-02")
            page.locator("#date-demo-rostov").dispatch_event("change")
            page.locator("#time-demo-rostov").fill("11:00")
            page.locator("#time-demo-rostov").dispatch_event("change")
            page.locator("#create-demo-rostov").click()
            assert "раньше окна" in page.locator("#feedback").inner_text()
            page.locator("#date-demo-rostov").fill("2026-10-01")
            page.locator("#date-demo-rostov").dispatch_event("change")
            page.locator("#create-demo-rostov").click()
            assert page.locator("#review-dialog").is_visible()
            page.locator("#review-confirm").click()
            page.wait_for_function("ShipmentDemo.getState().config['demo-rostov'].creation?.status==='SCHEDULED'")
            page.wait_for_timeout(750)
            assert page.locator("#date-demo-rostov").is_disabled()
            assert page.locator('#create-demo-rostov').is_disabled()
            page.locator('[data-cancel-job="demo-rostov"]').click()
            assert page.evaluate("ShipmentDemo.getState().config['demo-rostov'].creation") is None
            assert page.locator("#date-demo-rostov").is_enabled()
            checks.append("request creation is separate from shipment date; before-slot validation; scheduled demo job is cancelable")

            page.locator("#creation-outcome").select_option("unknown")
            page.locator("#create-demo-moscow").click()
            page.locator("#review-confirm").click()
            assert page.locator("#create-demo-moscow").is_disabled()
            page.wait_for_function("ShipmentDemo.getState().config['demo-moscow'].creation?.status==='UNKNOWN'")
            assert page.locator("#create-demo-moscow").is_disabled()
            page.reload()
            assert page.locator("#create-demo-moscow").is_disabled()
            page.locator('[data-status="demo-moscow"]').click()
            assert page.evaluate("ShipmentDemo.getState().config['demo-moscow'].creation.status") == "SUCCESS"
            page.locator("#logistics-demo-moscow").click()
            assert page.locator("#logistics-body .checklist li").count() == 6
            page.locator("#logistics-dialog").press("Escape")
            checks.append("busy prevents duplicate create; unknown outcome survives reload; check status without retry; post-create requirements")

            search_for("demo-novosibirsk")
            page.locator('[data-slot-index="0"]').click()
            page.locator("#slots-apply").click()
            assert page.evaluate("ShipmentDemo.getState().config['demo-novosibirsk'].slot.from").endswith("+07:00")
            page.locator(".demo-tools summary").click()
            page.locator("#creation-outcome").select_option("slot_lost")
            page.locator("#create-demo-novosibirsk").click()
            page.locator("#review-confirm").click()
            page.wait_for_function("ShipmentDemo.getState().config['demo-novosibirsk'].creation?.status==='FAILED'")
            assert page.evaluate("ShipmentDemo.getState().config['demo-novosibirsk'].slot") is None
            assert page.locator("#find-demo-novosibirsk").is_enabled()
            assert "Окно недоступно" in page.locator('[data-cluster="demo-novosibirsk"]').inner_text()
            search_for("demo-novosibirsk")
            page.locator('[data-slot-index="0"]').click()
            page.locator("#slots-apply").click()
            page.locator("#creation-outcome").select_option("success")
            page.locator("#create-demo-novosibirsk").click()
            page.locator("#review-confirm").click()
            page.wait_for_function("ShipmentDemo.getState().config['demo-novosibirsk'].creation?.status==='SUCCESS'")
            checks.append("point timezone preserved; lost window clears selection; new search and successful demo creation")
            # Inspection at mobile size after statuses and selected windows have changed.
            for width in (320,390,720,1024,1440):
                page.set_viewport_size({"width":width,"height":950})
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"), width
            page.set_viewport_size({"width":390,"height":900})
            page.screenshot(path=str(ARTIFACTS / "shipment-configured-narrow.png"), full_page=True)

            state = page.evaluate("ShipmentDemo.getState()")
            state["quantities"] = {f"{c}|{sku}":0 for c,skus in [
                ("demo-moscow",["1783408913","1783432877"]),
                ("demo-rostov",["1783408913","1783432877"]),
                ("demo-novosibirsk",["1783408913","1783432877","demo-kgt-01"]),
                ("demo-kazan",["1784511149","1783408913"]),
                ("demo-ekaterinburg",["1784511180","1783432877"])
            ] for sku in skus}
            page.evaluate("(s)=>ShipmentDemo.replaceForTest(s)",state)
            assert page.locator("[data-cluster]").count() == 0
            assert page.locator(".empty").is_visible()
            assert page.locator("#prepare").is_disabled()
            checks.append("no-ready empty state; zero differs from unknown")
            # The handoff is a standalone file, so exercise file:// offline.
            offline = browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow")
            offline.set_offline(True)
            file_page = offline.new_page()
            file_page.on("pageerror", lambda e: errors.append(str(e)))
            file_page.on("request", lambda r: external.append(r.url) if not r.url.startswith("file:") else None)
            file_page.goto((ROOT / PAGE).as_uri())
            assert file_page.locator("[data-cluster]").count() == 3
            file_page.locator("#fix-plan").click()
            file_page.locator("#pack-39439").fill("5")
            file_page.locator("#pack-39439").press("Enter")
            file_page.wait_for_function("ShipmentDemo.getState().manual['39439']?.value===5")
            file_page.locator("#confirm-39439").click()
            file_page.locator("#repair-done").click()
            file_page.reload()
            assert file_page.locator("[data-cluster]").count() == 4
            assert file_page.evaluate("ShipmentDemo.getState().manual['39439'].value") == 5
            offline.close()
            checks.append("standalone file opens offline and retains manual packs after reload")
            assert not errors,errors
            assert not external,external
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    result={"status":"passed","checks":checks,"screenshots":5,"browser_errors":errors,"external_requests":external}
    (ARTIFACTS / "verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))
    for name in ("shipments-desktop.png", "manual-pack.png", "shipments-narrow.png", "shipment-slots.png", "shipment-configured-narrow.png"):
        encoded=base64.b64encode((ARTIFACTS / name).read_bytes()).decode()
        for offset in range(0,len(encoded),4000):
            print(f"SCREENSHOT|{name}|{offset:09d}|{encoded[offset:offset+4000]}")

if __name__=="__main__":
    main()
