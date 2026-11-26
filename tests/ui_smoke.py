"""Screen smoke test: open every tab and click through Orders in a real browser.

Runs the app's own local server with a throwaway data folder and a few
made-up photos, then drives the page with Playwright (Chromium). Any script
error on the page fails the test, so a change that breaks a screen fails the
build instead of crashing on Jamie's PC.

    pip install playwright && python -m playwright install chromium
    python tests/ui_smoke.py            (KS_CHROME=/path/to/chrome to use another browser)

Not part of `unittest discover` (it needs a browser); the build runs it separately.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="ks-ui-smoke-"))
os.environ["LOCALAPPDATA"] = str(TMP / "data")  # Windows
os.environ["XDG_DATA_HOME"] = str(TMP / "data")  # Linux
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from keeperstudio import server  # noqa: E402

STEPS: list[str] = []


def photos() -> Path:
    d = TMP / "Shoot"
    d.mkdir(parents=True)
    for i, (w, h) in enumerate([(1200, 1600)] * 5 + [(1600, 1200)]):
        im = Image.new("RGB", (w, h), (40 + i * 20, 50, 70))
        ImageDraw.Draw(im).ellipse([w // 2 - 120, h // 4, w // 2 + 120, h // 4 + 240], fill=(220, 180, 150))
        im.save(d / f"IMG_{5370 + i}.JPG", quality=85)
    return d


def api(port: int, path: str, body: dict) -> dict:
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                               headers={"X-KS-Token": server.TOKEN, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())


def seed(port: int) -> None:
    sid = api(port, "/api/orders/shoot/save", {"shoot": {"name": "Smoke Test", "date": "2026-10-04"}})["shoot"]["id"]
    for i, (team, pkg) in enumerate([("Varsity", "pkg-a"), ("Varsity", "pkg-g"), ("JV", "pkg-c"), ("JV", "pkg-g")]):
        api(port, "/api/orders/save", {"shoot_id": sid, "order": {
            "athlete": f"Kid {i + 1}", "team": team, "envelope": str(i + 1), "image": f"IMG_{5370 + i}",
            "lines": [{"product_id": pkg, "qty": 1}, {"product_id": "ac-8x10", "qty": 1}]}})
    api(port, "/api/orders/team-photo", {"shoot_id": sid, "team": "Varsity", "image": "IMG_5375"})
    api(port, "/api/orders/extra/save", {"shoot_id": sid, "order": {"kind": "School", "items": [
        {"src": "teams", "size": "8x10", "product": "Professional Prints", "counts": {"Varsity": 1, "JV": 1}, "price_cents": 0}]}})


def run() -> int:
    from playwright.sync_api import sync_playwright

    folder = photos()
    httpd = server.serve(0)
    port = httpd.server_address[1]
    seed(port)
    errors: list[str] = []
    with sync_playwright() as p:
        exe = os.environ.get("KS_CHROME")
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else p.chromium.launch()
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        pg.on("pageerror", lambda e: errors.append(f"{STEPS[-1] if STEPS else 'load'}: {e}"))
        pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
              and errors.append(f"{STEPS[-1] if STEPS else 'load'}: console: {m.text}"))

        def step(name, fn, wait=600):
            STEPS.append(name)
            fn()
            pg.wait_for_timeout(wait)

        step("open the page", lambda: pg.goto(f"http://127.0.0.1:{port}/"), 1500)
        step("open a folder", lambda: pg.evaluate(f"window.KeeperStudio.loadFolder({json.dumps(str(folder))})"), 3000)
        for k in "GECN":
            step(f"Library view {k}", lambda k=k: pg.keyboard.press(k.lower()))
        step("Library grid", lambda: pg.keyboard.press("g"))
        for n, name in [(2, "Retouch"), (3, "Crop"), (5, "Composite"), (6, "Extract"), (1, "Library")]:
            step(f"{name} tab", lambda n=n: pg.keyboard.press(f"Control+{n}"), 1200)
        step("Crop tab again", lambda: pg.keyboard.press("Control+3"), 1200)
        step("Crop: select team photos", lambda: pg.click("[data-crop='pick-teams']"))
        step("Orders tab", lambda: pg.keyboard.press("Control+4"), 1500)
        step("Orders: pick the shoot", lambda: pg.click("[data-oshoot] >> text=Smoke Test"), 1200)
        step("Orders: open an envelope", lambda: pg.click("#modView tr[data-oid]"), 800)
        step("Orders: next envelope", lambda: pg.keyboard.press("ArrowDown"))
        step("Orders: preview on", lambda: pg.keyboard.press("v"))
        step("Orders: preview off", lambda: pg.keyboard.press("v"))
        step("Orders: close envelope", lambda: pg.keyboard.press("Escape"))
        step("Orders: pick a team", lambda: pg.click("#left [data-oteam='JV']"))
        step("Orders: all teams", lambda: pg.click("#left [data-oteam='all']"))
        step("Orders: lab order", lambda: pg.click("[data-seg='ordView'] [data-v='lab']"), 1200)
        step("Orders: analysis", lambda: pg.click("[data-seg='ordView'] [data-v='an']"), 1200)
        step("Analysis: next team", lambda: pg.keyboard.press("ArrowDown"), 900)
        step("Analysis: all shoots", lambda: pg.click("[data-seg='anScope'] [data-v='all']"), 900)
        step("Analysis: hide What if", lambda: pg.click("[data-ord='wi-toggle']"))
        step("Orders: envelopes", lambda: pg.click("[data-seg='ordView'] [data-v='orders']"), 900)
        step("Orders: Shoot menu", lambda: pg.click("text=Shoot ▾"))
        step("Orders: School & other orders", lambda: pg.click(".dd-menu >> text=School & other orders…"), 1200)
        step("School & other orders: add one", lambda: pg.click("#exWin [data-x='new'][data-k='Park']"), 900)
        step("School & other orders: done", lambda: pg.click("#exWin [data-x='done']"), 900)
        step("Orders: Export menu", lambda: pg.click("text=Export ▾"))
        step("Orders: shoot summary", lambda: pg.click(".dd-menu >> text=Shoot summary"), 1500)
        step("close the summary", lambda: pg.keyboard.press("Escape"))
        step("help sheet", lambda: pg.keyboard.press("?"))
        step("close help", lambda: pg.keyboard.press("?"))
        b.close()
    httpd.shutdown()
    print("\n".join(f"  ok  {s}" for s in STEPS))
    if errors:
        print("\nScreen errors:\n" + "\n".join("  " + e for e in errors))
        return 1
    print(f"\nAll {len(STEPS)} screen steps ran without a script error.")
    return 0


if __name__ == "__main__":
    t = time.time()
    code = run()
    print(f"({time.time() - t:.0f}s)")
    sys.exit(code)
