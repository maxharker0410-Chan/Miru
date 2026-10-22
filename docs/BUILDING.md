# 建置 S.Chat

## 本機 Web

使用 Python 3.12，建立虛擬環境後安裝：

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-server.txt
.venv/Scripts/python app.py
```

服務預設只監聽 `127.0.0.1:5001`。現有伺服器登入仍使用原邀請碼；首次本機帳號請從 Windows 版選擇「本機遊玩」。不會自動建立 API Key。

設定 `DATA_DIR` 可使用原資料根目錄，包含 `users/<uid>/s_chat/` 及 `_admin/ai_config.json`。Windows 繼續使用 `%LOCALAPPDATA%/Miru/`，保留原 config、模型與故事。先備份資料再升級；不要把私人資料加入 Git。

## Windows

```powershell
./build_windows.ps1
```

或在已安裝依賴的環境執行 `python -m PyInstaller schat_windows.spec --noconfirm`。輸出 `dist/S.Chat/` 必須整個保留，不能只複製 EXE。需要系統 WebView2。關閉主視窗會結束本機服務；最小化可繼續運行。

## 測試

```powershell
python -m pytest -q
node --test tests/schat_library_checks.cjs tests/schat_speech_checks.cjs
```

GitHub Actions「S.Chat Windows」執行測試、建置並產生 Windows artifact；不部署或合併。

## 配對手機服務

`scripts/serve_mobile.py --state-dir <既有配對狀態目錄> --port 5086` 保留原手機配對與資料。外部連線需要原來的 HTTPS 轉送；臨時連線需提供服務的電腦保持開機。PWA 安裝不是獨立雲端主機。
