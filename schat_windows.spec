# -*- mode: python ; coding: utf-8 -*-
"""S.Chat Windows runtime; no desktop companion, capture or remote-host tools."""
from PyInstaller.utils.hooks import collect_all
from pathlib import Path
import ssl
web_datas, web_bins, web_imports = collect_all("webview")
runtime_ca = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
runtime_datas = [(str(runtime_ca),'.')] if runtime_ca.is_file() else []
a = Analysis(["windows_launcher.py"], pathex=["."], binaries=web_bins,
    datas=[("templates","templates"),("assets","assets"),("schat-manifest.json","."),("schat-service-worker.js",".")]+web_datas+runtime_datas,
    hiddenimports=["app","auth","ai_config","desktop_paths","story_engine","story_author","story_model","sandbox","story_packages",
        "story_tracker","story_input","story_memory","world_import","world_runtime","world_settings","mobile_gateway",
        "PIL.Image","openai","flask","flask_compress","waitress","qrcode","webview.platforms.edgechromium"]+web_imports,
    excludes=["pytest","matplotlib","numpy","scipy","pandas","tkinter"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name="S.Chat",icon="assets/brand/schat.ico",console=False,upx=False)
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name="S.Chat")
