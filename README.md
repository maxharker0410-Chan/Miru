# S. Chat

S. Chat 是可自訂故事世界、角色與場景的互動角色扮演應用。目前提供 Windows 故事測試版。你可以編輯世界觀、開場旁白、每位角色的個性與背景，加入場景背景和角色立繪，再指定各場景的在場角色和下一站。

遊玩時，場景背景會隨故事路線自動切換；同一場景可讓多名角色一起登場。導演模型選擇當回合說話的角色和是否進入下一場景，每名角色分別產生台詞，僅收到自己的私有記憶與公開對話。每個故事及遊玩紀錄以目前登入使用者為單位儲存，重開可接續。

## Windows 測試

1. 到 [Actions](https://github.com/maxharker0410-Chan/Miru/actions/workflows/windows-companion.yml) 打開最新成功的 **S. Chat Windows test build**。
2. 在該執行頁面的 **Artifacts** 下載 `S.Chat-Windows-x64-…`，完整解壓縮後執行 `S.Chat.exe`。請先關閉舊版 Miru。
3. 使用原本登入資料；故事模式只使用聊天模型 API。尚未設定時，提供 OpenAI 相容服務的 Base URL、模型 ID 與 API Key。
4. 建立故事，新增角色和場景；場景可上傳 PNG、JPG、WebP 背景，角色適合使用透明 PNG 立繪。勾選在場角色及下一場景，儲存後開始遊玩。

這是可測試的開發版，Windows x64 與 WebView2 Runtime 為執行條件。角色與背景圖片需由作者提供；目前不會自行生成美術素材。角色對話會消耗所設定模型服務的 API 額度。故事檔案保存在原有本機使用者資料路徑的 `s_chat` 子目錄。

原始 Miru 的程式與授權資訊保留在專案中；請參見 [原始 README](docs/UPSTREAM_MIRU_README.md)、[LICENSE](LICENSE) 與 [第三方聲明](THIRD_PARTY_NOTICES.md)。S. Chat 與原 Miru 為不同的產品方向，部分內部相容元件暫時仍沿用原名稱，以便讀取既有登入與模型設定。
