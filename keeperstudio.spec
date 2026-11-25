from pathlib import Path
# PyInstaller spec for Keeper Studio.
#
# Build on Windows (PyInstaller does not cross-compile):
#   Build.bat            or, by hand:
#   .venv\Scripts\pyinstaller keeperstudio.spec
#
# Result: dist\Keeper Studio\Keeper Studio.exe. config.yaml, models\ and luts\
# are copied beside the exe afterwards (Build.bat and the GitHub workflow do it)
# so framing stays editable without a rebuild, exactly like PhotoCropper.

import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

# mediapipe ships binary graphs and tflite models as package data.
mediapipe_data = collect_data_files("mediapipe")
mediapipe_libs = collect_dynamic_libs("mediapipe")

# rembg + onnxruntime (cut-out) and pywebview (the window) must be collected
# whole; pillow-heif carries native libraries.
extra_datas, extra_bins, extra_hidden = [], [], []
for pkg in ("rembg", "onnxruntime", "webview", "pillow_heif", "clr_loader", "pythonnet"):
    try:  # pythonnet/clr_loader drive WebView2 on Windows only
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    extra_datas += d; extra_bins += b; extra_hidden += h

# These read their own version from package metadata at import time.
metadata = []
for pkg in ("pymatting", "numba", "llvmlite", "scipy", "rembg", "onnxruntime", "numpy", "tqdm", "pooch", "pywebview"):
    try:
        metadata += copy_metadata(pkg)
    except Exception:
        pass

a = Analysis(
    ["run_studio.py"],
    pathex=[],
    binaries=mediapipe_libs + extra_bins,
    datas=[
        ("keeperstudio/ui/index.html", "ui"),
        ("assets/keeper-studio.ico", "assets"),
        *[(str(f), "keeperstudio/meridian") for f in Path("keeperstudio/meridian").iterdir() if f.suffix in (".csv", ".py", ".md")],
        *mediapipe_data, *extra_datas, *metadata,
    ],
    hiddenimports=[
        "mediapipe",
        "photocropper.detectors.mediapipe_mesh",
        "photocropper.pose",
        "photocropper.segment",
        "photocropper.composite",
        "photoextractor.core",
        *collect_submodules("numpy"),
        *extra_hidden,
    ],
    hookspath=[],
    runtime_hooks=[],
    # PhotoCropper's own Qt windows are not used by Keeper Studio.
    excludes=["PySide6", "photocropper.gui", "photocropper.adjust", "photocropper.composite_gui", "photoextractor.gui"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="Keeper Studio", console=False, icon="assets/keeper-studio.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Keeper Studio")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Keeper Studio.app", icon=None, bundle_identifier="com.jbexten.keeperstudio")
