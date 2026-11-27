"""Team 5x7s for the school: one 300-dpi 5x7 of every team, zipped and emailed.

Every team on the shoot's team list is checked (group photo picked, 5x7 cropped)
so none is forgotten; a team that wasn't photographed can be skipped. The zip is
sent from Gmail with an app password (kept with Windows' own protection), or
Gmail opens a filled-in message and the zip is dragged in by hand.
"""
from __future__ import annotations

import base64
import json
import os
import re
import smtplib
import time
import zipfile
from io import BytesIO
from email.message import EmailMessage
from pathlib import Path

from . import paths

CROP = "7x5"               # the landscape 5x7 Crop cuts from a group photo
SIZE = (2100, 1500)        # 7x5 inches at 300 dpi
GMAIL_LIMIT = 25 * 1024 * 1024
SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", str(s or "")).strip(" .") or "Team"


def check(team_list: list[dict], team_photos: dict[str, str], crops_dir: str, skip: list[str]) -> list[dict]:
    """Each team: ready (with its crop file), skipped, or why not."""
    from . import orders as O
    stems = {f"{Path(img).stem}_{CROP}" for img in team_photos.values() if img}
    found = O.find_crops(Path(crops_dir), stems) if crops_dir else {}
    out = []
    for t in team_list:
        name, img = t["name"], team_photos.get(t["name"]) or ""
        row = {"name": name, "image": img, "file": "", "status": "", "why": ""}
        f = found.get(f"{Path(img).stem}_{CROP}".lower()) if img else None
        if name in skip:
            row["status"] = "skip"
        elif not img:
            row.update(status="todo", why="No group photo picked")
        elif not f:
            row.update(status="todo", why="5×7 not cropped yet" if crops_dir else "Choose the crops folder")
        else:
            row.update(status="ok", file=str(f))
        out.append(row)
    return out


def make_zip(rows: list[dict], out: Path) -> dict:
    """The ready teams' 5x7s at 300 dpi, named '01 Team name.jpg' in team order."""
    from PIL import Image, ImageOps
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    n = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:  # JPEGs don't shrink in a zip
        for r in rows:
            if r["status"] != "ok":
                continue
            n += 1
            with Image.open(r["file"]) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                size = SIZE if im.width >= im.height else (SIZE[1], SIZE[0])
                im = im.resize(size, Image.LANCZOS) if im.size != size else im
                buf = BytesIO()
                im.save(buf, "JPEG", quality=92, dpi=(300, 300), optimize=True)
            z.writestr(f"{n:02d} {safe_name(r['name'])}.jpg", buf.getvalue())
    os.replace(tmp, out)
    return {"path": str(out), "bytes": out.stat().st_size, "teams": n}


# ---------------------------------------------------------- the Gmail login --
# The app password is kept with Windows' DPAPI (only this Windows login can read
# it back). Elsewhere (development) it is only encoded, in a file only you can read.

def _mail_path() -> Path:
    return paths.data_dir() / "mail.json"


def _protect(raw: bytes) -> str:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        src = BLOB(len(raw), ctypes.cast(ctypes.create_string_buffer(raw, len(raw)), ctypes.POINTER(ctypes.c_char)))
        dst = BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), "Keeper Studio", None, None, None, 0, ctypes.byref(dst)):
            raise OSError("Windows couldn't protect the password")
        data = ctypes.string_at(dst.pbData, dst.cbData)
        ctypes.windll.kernel32.LocalFree(dst.pbData)
        return "dpapi:" + base64.b64encode(data).decode()
    return "b64:" + base64.b64encode(raw).decode()


def _unprotect(s: str) -> bytes:
    kind, _, body = (s or "").partition(":")
    data = base64.b64decode(body or "")
    if kind == "dpapi":
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        src = BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
        dst = BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)):
            raise OSError("The saved Gmail app password can't be read on this Windows login - enter it again.")
        out = ctypes.string_at(dst.pbData, dst.cbData)
        ctypes.windll.kernel32.LocalFree(dst.pbData)
        return out
    return data


def mail_settings() -> dict:
    try:
        d = json.loads(_mail_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return {"from": d.get("from", ""), "has_password": bool(d.get("password"))}


def save_mail(from_addr: str | None = None, password: str | None = None, forget: bool = False) -> dict:
    p = _mail_path()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if from_addr is not None:
        d["from"] = from_addr.strip()
    if forget:
        d.pop("password", None)
    elif password:
        d["password"] = _protect(re.sub(r"\s+", "", password).encode())  # Google shows it in groups of four
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return mail_settings()


def _login() -> tuple[str, str]:
    try:
        d = json.loads(_mail_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if not d.get("from") or not d.get("password"):
        raise ValueError("Set up your Gmail address and app password first.")
    return d["from"], _unprotect(d["password"]).decode()


def _smtp():
    user, pw = _login()
    try:
        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60)
    except OSError:
        raise ValueError("Couldn't reach Gmail - check the internet connection and try again.") from None
    try:
        s.login(user, pw)
    except smtplib.SMTPAuthenticationError:
        s.quit()
        raise ValueError("Gmail didn't accept the address and app password. Check both (the app password is the 16-letter code, not your Gmail password).") from None
    return s, user


def test_login() -> dict:
    s, user = _smtp()
    s.quit()
    return {"ok": True, "from": user}


def send(to: str, subject: str, body: str, attachment: Path) -> dict:
    to = [a.strip() for a in re.split(r"[,;]", to or "") if a.strip()]
    if not to or not all(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", a) for a in to):
        raise ValueError("Type the school's email address.")
    if attachment.stat().st_size > GMAIL_LIMIT:
        raise ValueError("The zip is over Gmail's 25 MB limit.")
    s, user = _smtp()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, ", ".join(to), subject
    msg.set_content(body)
    msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="zip", filename=attachment.name)
    try:
        s.send_message(msg)
    finally:
        s.quit()
    return {"ok": True, "to": to, "at": time.time()}


def gmail_compose_url(to: str, subject: str, body: str) -> str:
    from urllib.parse import urlencode
    return "https://mail.google.com/mail/?" + urlencode({"view": "cm", "fs": "1", "to": to, "su": subject, "body": body})
