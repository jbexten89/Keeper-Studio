"""The local server the Keeper Studio window talks to.

Bound to 127.0.0.1 only, and every request must carry a random per-launch
token, so other web pages open on the machine cannot reach it.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, engine, jobs, library, paths
from .catalog import Catalog

TOKEN = secrets.token_urlsafe(24)
FAVICON = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#07080A"/>'
           b'<path d="M18 14h8v15l14-15h10L35 30l16 20H40L29 36l-3 3v11h-8z" fill="#D9DCE2"/><circle cx="50" cy="50" r="5" fill="#2E9BFF"/></svg>')
catalog: Catalog | None = None
dialogs = None  # set by the window: callable(kind, **opts) -> list[str] | None


def _reveal(path: str) -> None:
    p = Path(path)
    if sys.platform.startswith("win"):
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R" if p.is_file() else "", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p if p.is_dir() else p.parent)])


def _open_file(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _remember_folder(path: str) -> list[str]:
    recent = [p for p in (catalog.get("kv", "recent_folders") or []) if p != path]
    recent.insert(0, path)
    recent = recent[:8]
    catalog.put("kv", "recent_folders", recent)
    return recent


class Handler(BaseHTTPRequestHandler):
    server_version = "KeeperStudio"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet
        pass

    # ------------------------------------------------------------ helpers --
    def _send(self, code: int, body: bytes, ctype: str, cache: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _authorised(self, q: dict) -> bool:
        return self.headers.get("X-KS-Token") == TOKEN or (q.get("t") or [None])[0] == TOKEN

    # ----------------------------------------------------------------- GET --
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/favicon.ico":
            return self._send(200, FAVICON, "image/svg+xml", cache=True)
        if u.path in ("/", "/index.html"):
            html = (paths.bundle_dir() / "ui" / "index.html").read_text(encoding="utf-8")
            html = html.replace("__KS_TOKEN__", TOKEN).replace("__KS_VERSION__", __version__)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if not self._authorised(q):
            return self._send(403, b"forbidden", "text/plain")
        try:
            if u.path == "/thumb":
                data = library.thumbnail(q["p"][0], int((q.get("s") or ["400"])[0]))
                return self._send(200, data, "image/jpeg", cache=True)
            if u.path == "/preview":
                data = library.thumbnail(q["p"][0], int((q.get("s") or ["2048"])[0]), float((q.get("r") or ["0"])[0]))
                return self._send(200, data, "image/jpeg", cache=True)
            if u.path == "/graded":  # the preview with a colour preset applied, for side by side
                data = engine.graded_preview(q["p"][0], int((q.get("s") or ["2048"])[0]),
                                             float((q.get("r") or ["0"])[0]), (q.get("k") or ["standard"])[0])
                return self._send(200, data, "image/jpeg", cache=True)
            if u.path == "/full":
                data, ctype = library.full_image(q["p"][0])
                return self._send(200, data, ctype, cache=True)
            if u.path == "/file":  # an output we wrote (composite, cut-out, contact sheet)
                p = q["p"][0]
                ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(Path(p).suffix.lower(), "application/octet-stream")
                return self._send(200, Path(p).read_bytes(), ctype)
            if u.path.startswith("/api/job/"):
                job = jobs.get(u.path.rsplit("/", 1)[1])
                if not job:
                    return self._json({"error": "no such job"}, 404)
                return self._json(job.snapshot(int((q.get("since") or ["0"])[0])))
        except FileNotFoundError:
            return self._send(404, b"not found", "text/plain")
        except Exception as exc:
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        return self._send(404, b"not found", "text/plain")

    # ---------------------------------------------------------------- POST --
    def do_POST(self):
        u = urlparse(self.path)
        if not self._authorised(parse_qs(u.query)):
            return self._send(403, b"forbidden", "text/plain")
        try:
            body = self._body()
            fn = ROUTES.get(u.path)
            if fn is None:
                return self._json({"error": "unknown endpoint"}, 404)
            return self._json(fn(body))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


# ------------------------------------------------------------------ routes --

def r_hello(b):
    return {
        "version": __version__, "dialogs": dialogs is not None, "platform": sys.platform,
        "recent": [p for p in (catalog.get("kv", "recent_folders") or []) if Path(p).is_dir()],
        "data_dir": str(paths.data_dir()), "config": str(paths.config_path()),
        "heif": library.HEIF,
    }


def r_db_entries(b):
    return {"entries": catalog.entries(b["store"])}


def r_db_get(b):
    return {"value": catalog.get(b["store"], b["key"])}


def r_db_put(b):
    catalog.put_many(b["store"], [(k, v) for k, v in b["items"]])
    return {"ok": True}


def r_db_del(b):
    catalog.delete(b["store"], b["key"])
    return {"ok": True}


def r_dialog(b):
    if dialogs is None:
        return {"paths": None, "unavailable": True}
    return {"paths": dialogs(b.get("kind", "folder"), **{k: v for k, v in b.items() if k != "kind"})}


def r_open_folder(b):
    folder = Path(b["path"]).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    res = library.scan(folder)
    res["recent"] = _remember_folder(res["root"])
    return res


def r_info(b):
    return {"items": [library.info(p) for p in b["paths"]]}


def r_reveal(b):
    _reveal(b["path"])
    return {"ok": True}


def r_open_file(b):
    _open_file(b["path"])
    return {"ok": True}


def r_exists(b):
    return {"exists": {p: Path(p).exists() for p in b["paths"]}}


def r_crop_settings(b):
    if "settings" in b:
        catalog.put("settings", "crop", b["settings"])
    cfg = engine.config()
    return {
        "settings": engine.merged_settings(catalog.get("settings", "crop")),
        "defaults": engine.default_settings(cfg), "sizes": engine.sizes(cfg),
        "warnings": cfg.warnings, "config_path": str(paths.config_path()),
        "orders_name": cfg.orders_folder or "Orders",
    }


def r_crop_plan(b):
    settings = engine.with_style(engine.merged_settings(catalog.get("settings", "crop")), catalog.get("styles", b["path"]))
    return engine.plan_cached(b["path"], settings, b.get("manual"), int(b.get("seq") or 0), bool(b.get("focus")))


def r_crop_analyze(b):
    settings = engine.merged_settings(catalog.get("settings", "crop"))
    return {"job": engine.start_analyze(b["paths"], settings, b.get("manual") or {}, dict(catalog.entries("styles"))).id}


def r_crop_export(b):
    settings = engine.merged_settings(catalog.get("settings", "crop"))
    return {"job": engine.start_export_prints(b["paths"], b["out_dir"], settings, b.get("manual") or {},
                                              dict(catalog.entries("styles"))).id}


def r_crop_default_out(b):
    return {"out_dir": engine.default_output(b["paths"])}


def r_crop_rotate(b):
    path, deg = b["path"], round(max(-15.0, min(15.0, float(b.get("angle") or 0))), 2)
    if deg:
        catalog.put("rotate", path, deg)
        engine.rotations[path] = deg
    else:
        catalog.delete("rotate", path)
        engine.rotations.pop(path, None)
    return {"angle": deg}


def r_crop_rotations(b):
    return {"rotations": dict(engine.rotations)}


def r_tunables(b):
    if "values" in b:
        engine.write_tunables(b["values"])
    return {"tunables": engine.read_tunables()}


def r_export(b):
    return {"job": engine.start_library_export(b["items"], b["dest"], b.get("opts") or {}).id}


def r_job_cancel(b):
    job = jobs.get(b["id"])
    if job:
        job.cancelled = True
    return {"ok": bool(job)}


def r_comp_defaults(b):
    if "settings" in b:
        catalog.put("settings", "composite", b["settings"])
    c = dict(engine.config().composite or {})
    saved = catalog.get("settings", "composite") or {}
    return {"defaults": {
        "school": c.get("school_name", ""), "year": "", "max_per_row": int(c.get("max_per_row", 8)),
        "uppercase": bool(c.get("name_uppercase", False)), "title_font": c.get("title_font", ""),
        "teacher_font": c.get("teacher_font", c.get("title_font", "")), "name_font": c.get("name_font", ""),
        "background": "", "row_counts": "",
    }, "saved": saved}


def r_comp_order(b):
    return engine.composite_order(b.get("students", []), b.get("teachers", []), b.get("max_per_row", 8), b.get("row_counts", ""))


def r_comp_build(b):
    return {"job": engine.start_composite(b).id}


def r_cutout_status(b):
    return {"ready": engine.cutout_model_ready(), "model_dir": str(paths.rembg_model_home())}


def r_cutout_run(b):
    return {"job": engine.start_cutout(b["paths"], b["out_dir"]).id}


def r_cutout_existing(b):
    out = Path(b["out_dir"])
    return {"existing": {p: str(out / f"{Path(p).stem}.png") for p in b["paths"] if (out / f"{Path(p).stem}.png").is_file()}}


ROUTES = {
    "/api/hello": r_hello,
    "/api/db/entries": r_db_entries, "/api/db/get": r_db_get, "/api/db/put": r_db_put, "/api/db/del": r_db_del,
    "/api/dialog": r_dialog,
    "/api/library/open": r_open_folder, "/api/library/info": r_info,
    "/api/reveal": r_reveal, "/api/open-file": r_open_file, "/api/exists": r_exists,
    "/api/crop/settings": r_crop_settings, "/api/crop/plan": r_crop_plan,
    "/api/crop/analyze": r_crop_analyze, "/api/crop/export": r_crop_export,
    "/api/crop/default-out": r_crop_default_out, "/api/crop/rotate": r_crop_rotate, "/api/crop/rotations": r_crop_rotations, "/api/crop/tunables": r_tunables,
    "/api/export": r_export, "/api/job/cancel": r_job_cancel,
    "/api/composite/defaults": r_comp_defaults, "/api/composite/order": r_comp_order,
    "/api/composite/build": r_comp_build,
    "/api/cutout/status": r_cutout_status, "/api/cutout/run": r_cutout_run,
    "/api/cutout/existing": r_cutout_existing,
}


def serve(port: int = 0) -> ThreadingHTTPServer:
    global catalog
    catalog = Catalog(paths.catalog_path())
    engine.plan_store = catalog
    engine.rotations.update({k: float(v) for k, v in catalog.entries("rotate")})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="ks-server", daemon=True).start()
    return httpd
