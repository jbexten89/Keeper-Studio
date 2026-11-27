"""Opens Keeper Studio: starts the local server and shows it in a desktop window.

The window is pywebview (Microsoft Edge WebView2 on Windows). If pywebview is
not installed, the app opens in the default browser instead, minus native
file dialogs.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from . import paths, server


def _unblock_downloaded_files() -> None:
    """Remove Windows' "downloaded from the internet" mark from the app's DLLs.

    Windows tags every file extracted from a downloaded ZIP. The .NET loader
    behind the app window (pythonnet) refuses tagged DLLs and the app dies with
    "Failed to resolve Python.Runtime.Loader.Initialize". Deleting the tag (an
    NTFS alternate data stream) is what right-click > Properties > Unblock does.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    root = paths.bundle_dir()
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.lower().endswith((".dll", ".pyd", ".exe")):
                try:
                    os.remove(os.path.join(folder, name) + ":Zone.Identifier")
                except OSError:
                    pass


def _open_in_browser(url: str, reason: str | None = None) -> int:
    import webbrowser
    if reason:
        try:
            (paths.data_dir() / "window-error.txt").write_text(reason, encoding="utf-8")
        except OSError:
            pass
    webbrowser.open(url + ("?fallback=1" if reason else ""))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


def _selftest() -> int:
    """Load config and models and plan a crop on a blank frame; used by CI."""
    lines = []
    try:
        import numpy as np
        from photocropper import detectors

        from . import engine
        cfg = engine.config()
        lines.append(f"config: {paths.config_path()}")
        lines.append(f"model exists: {Path(cfg.detector['model_path']).is_file()}")
        det = detectors.build(cfg.detector["name"], cfg.detector)
        det.detect(np.zeros((240, 320, 3), dtype=np.uint8))
        det.close()
        ui = paths.bundle_dir() / "ui"
        page = (ui / "index.html").read_text(encoding="utf-8")
        import re as _re
        needed = [ui / m for m in _re.findall(r'(?:src|href)="/ui/([^"?]+)', page)]
        missing = [str(f) for f in needed if not f.is_file()]
        lines.append(f"ui files: {len(needed) - len(missing)} of {len(needed)}")
        if missing:
            raise FileNotFoundError(", ".join(missing))
        import webview  # noqa: F401
        lines.append("pywebview: ok")
        if os.name == "nt":
            import clr  # noqa: F401  (loads pythonnet / .NET, which the window needs)
            lines.append("pythonnet: ok")
        lines.append("sizes: " + ", ".join(s["name"] for s in engine.sizes(cfg)))
        from . import order_routes
        cat = order_routes.catalog()
        lines.append(f"prices: {len(cat.products)} products from {cat.source}")
        if cat.warnings:
            raise ValueError("; ".join(cat.warnings))
        # Meridian's files are bundled and their checker runs inside the app.
        import tempfile
        from PIL import Image
        from . import meridian
        with tempfile.TemporaryDirectory() as d:
            Image.new("RGB", (1500, 2100)).save(os.path.join(d, "IMG_1_5x7.JPG"))
            plan = {"groups": [{"group": "5x7", "items": [{"file": "IMG_1_5x7", "item": "5x7", "qty": 1, "for": ["Test"], "why": ""}]}]}
            rows, _ = meridian.plan_rows(plan, cat, {"account_email": "test@example.com"}, "Selftest", lambda it: "IMG_1_5x7.JPG")
            meridian.write_csv(rows, os.path.join(d, "o.csv"))
            chk = meridian.check(os.path.join(d, "o.csv"), d)
            if not chk["ok"]:
                raise ValueError("Meridian checker: " + chk["report"])
        lines.append(f"meridian: {len(meridian.products())} products, checker ok")
        # PDF exports work inside the app.
        from . import reports
        with tempfile.TemporaryDirectory() as d:
            t = reports.table("Envelope,Team,Athlete,5x7\n1,U10,Test,1\nTOTAL,1 athlete,,1\n", "pull")
            out = reports.pdf(t, os.path.join(d, "t.pdf"), "Pull sheet", "Selftest")
            if not open(out, "rb").read(5) == b"%PDF-":
                raise ValueError("PDF export failed")
        lines.append("reports: pdf ok")
        lines.append("OK")
        code = 0
    except Exception as exc:
        lines.append(f"FAILED: {type(exc).__name__}: {exc}")
        code = 1
    (paths.app_dir() / "selftest-result.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code


def _be_a_good_neighbour() -> None:
    """Run below normal priority on Windows.

    Checking framing and exporting keep every CPU core busy for minutes. At
    normal priority that makes the whole PC sluggish; just below normal, the
    work still uses all the idle CPU but whatever you click elsewhere wins.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass


def main() -> int:
    _unblock_downloaded_files()
    _be_a_good_neighbour()
    if "--selftest" in sys.argv:
        return _selftest()

    port = 0
    for a in sys.argv:
        if a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    httpd = server.serve(port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    if "--browser" in sys.argv or os.environ.get("KS_BROWSER"):
        print(f"Keeper Studio running at {url}")
        return _open_in_browser(url)

    try:
        import webview
        if os.name == "nt":
            import clr  # noqa: F401  fail here, not halfway through opening the window
    except Exception as exc:
        import traceback
        return _open_in_browser(url, traceback.format_exc())

    window = webview.create_window(
        "Keeper Studio", url, width=1560, height=980, min_size=(1100, 720),
        background_color="#07080A", text_select=False,
    )

    def dialogs(kind: str, **opts):
        initial = opts.get("initial") or ""
        if kind == "folder":
            res = window.create_file_dialog(webview.FOLDER_DIALOG, directory=initial)
        elif kind == "save":
            res = window.create_file_dialog(
                webview.SAVE_DIALOG, directory=initial, save_filename=opts.get("filename") or "",
                file_types=tuple(opts.get("types") or ()),
            )
        else:
            res = window.create_file_dialog(
                webview.OPEN_DIALOG, directory=initial, allow_multiple=bool(opts.get("multiple")),
                file_types=tuple(opts.get("types") or ("All files (*.*)",)),
            )
        if not res:
            return None
        return [res] if isinstance(res, str) else list(res)

    server.dialogs = dialogs

    def on_drop(e):
        try:
            files = e.get("dataTransfer", {}).get("files", [])
            found = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
            if found:
                import json
                window.evaluate_js(f"window.KS_onDropPaths && window.KS_onDropPaths({json.dumps(found)})")
        except Exception:
            pass

    def on_loaded():
        try:
            from webview.dom import DOMEventHandler
            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
            window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
        except Exception:
            pass

    window.events.loaded += on_loaded
    try:
        webview.start(private_mode=False, storage_path=str(paths.data_dir() / "webview"))
    except Exception:
        import traceback
        server.dialogs = None
        return _open_in_browser(url, traceback.format_exc())
    try:
        from . import order_routes
        order_routes.on_app_close()  # back up the order book and finish any folder orders files
    except Exception:
        pass
    httpd.shutdown()
    return 0
