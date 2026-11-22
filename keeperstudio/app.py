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
        ui = paths.bundle_dir() / "ui" / "index.html"
        lines.append(f"ui exists: {ui.is_file()}")
        if not ui.is_file():
            raise FileNotFoundError(ui)
        import webview  # noqa: F401
        lines.append("pywebview: ok")
        lines.append("sizes: " + ", ".join(s["name"] for s in engine.sizes(cfg)))
        lines.append("OK")
        code = 0
    except Exception as exc:
        lines.append(f"FAILED: {type(exc).__name__}: {exc}")
        code = 1
    (paths.app_dir() / "selftest-result.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()

    port = 0
    for a in sys.argv:
        if a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    httpd = server.serve(port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    if "--browser" in sys.argv or os.environ.get("KS_BROWSER"):
        import webbrowser
        print(f"Keeper Studio running at {url}")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    try:
        import webview
    except ImportError:
        import webbrowser
        webbrowser.open(url)
        while True:
            time.sleep(3600)

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
    webview.start(private_mode=False, storage_path=str(paths.data_dir() / "webview"))
    httpd.shutdown()
    return 0
