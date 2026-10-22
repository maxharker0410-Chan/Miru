"""Windows WebView2 launcher for S.Chat, with legacy data-path compatibility."""
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit
from desktop_paths import app_support_dir, data_dir, launcher_config_path, webview_storage_dir

PORT = 5001

def _load_config():
    path = launcher_config_path()
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}

def _initial_url(config, cache_buster=None):
    token = config.get("auth_token", "")
    server = str(config.get('server_url') or '').rstrip('/')
    parsed = urlsplit(server)
    remote = server if (not config.get('local_only') and parsed.scheme in ('http','https') and parsed.hostname
        and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment) else ''
    base = remote or f'http://127.0.0.1:{PORT}'
    return f"{base}/s-chat?token={quote(token)}" if token and config.get("setup_complete", True) else f"http://127.0.0.1:{PORT}/login"

def main():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    os.chdir(root)
    os.environ["DATA_DIR"] = str(data_dir())
    data_dir().mkdir(parents=True, exist_ok=True)
    log_dir = app_support_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        stream = open(log_dir / "schat.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    with socket.socket() as check:
        check.settimeout(.3)
        if check.connect_ex(("127.0.0.1", PORT)) == 0:
            import webbrowser
            webbrowser.open(_initial_url(_load_config()))
            return 0
    import app
    threading.Thread(target=app.run_client_mode, kwargs={"port":PORT}, daemon=True).start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(100):
        try:
            with opener.open(f"http://127.0.0.1:{PORT}/api/health", timeout=1) as response:
                if json.loads(response.read()).get("service") == "s-chat":
                    break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError("S.Chat local service did not start.")
    import webview
    window = webview.create_window("S.Chat", _initial_url(_load_config()), width=1200, height=820,
        min_size=(800,540), resizable=True, text_select=True, background_color="#13111a")
    stop = threading.Event()
    def coordinate():
        while not stop.wait(.2):
            if app._open_webui_requested.is_set():
                app._open_webui_requested.clear(); window.show(); window.restore()
            if app._logout_requested.is_set():
                app._logout_requested.clear(); window.load_url(f"http://127.0.0.1:{PORT}/login")
    threading.Thread(target=coordinate, daemon=True).start()
    window.events.closing += stop.set
    storage = webview_storage_dir(); storage.mkdir(parents=True,exist_ok=True)
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(storage))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
