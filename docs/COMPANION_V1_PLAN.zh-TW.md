# 互動角色助手 V1 改造藍圖

> 狀態：規劃中  
> 基底：[`kiyotakali/Miru`](https://github.com/kiyotakali/Miru)  
> 目標平台：Windows 桌面版優先；Android 與多裝置同步延後  
> 工作分支：`develop/companion-v1`

## 1. 專案目標

以 Miru 的記憶、主動陪伴、情緒與裝置同步能力為核心，改造成可替換角色、能在房間場景活動、支援文字與語音互動的個人 AI 角色助手。

第一版的重點是「真的能在 Windows 上穩定使用」，而不是一次完成所有平台：

- 角色可顯示 Idle、Blink、Talk、Look Around、Walk 與基本情緒。
- 角色可在房間的可行走區域內移動。
- 可輸入文字並取得回答。
- 語音輸入與語音播放採可替換介面。
- 長期記憶、日誌與主動關懷仍由 Miru Core 提供。
- 螢幕觀察、麥克風與主動開口必須由使用者明確啟用。
- 不假裝 ChatGPT Plus 可直接當作程式 API；模型來源需明確標示為 API 或本機模型。

## 2. V1 範圍

### 本期要做

1. Windows 開發與啟動流程。
2. 保留 Miru Core，先建立可替換的 Character Adapter。
3. 建立單一房間場景與可行走區域。
4. 建立角色動畫狀態機。
5. 串接文字對話、基本語音輸入／輸出。
6. 建立隱私開關與清楚的模型費用提示。
7. 建立可測試、可回復、可逐步合併的改造流程。

### 本期暫不做

- Android 正式版。
- 公開雲端服務與多人帳號。
- 複雜換裝商城。
- 多房間地圖。
- 自動控制電腦或代替使用者執行高風險操作。
- 疾病、醫療或財務判斷用途。

## 3. 模組處理決策

### 保留

| 模組 | 用途 |
|---|---|
| `memory.py`、`core_memory.py`、`memory_router.py` | 長期記憶與記憶路由 |
| `journal.py`、`daily_patterns.py` | 日誌與生活模式 |
| `attention_engine.py`、`care_engine.py` | 主動陪伴與關懷判斷 |
| `miru_emotion.py` | 情緒狀態 |
| `screen_analyzer.py`、`vision.py` | 經授權後的螢幕理解 |
| `device_manager.py`、`sync_backend.py`、`sse.py` | 裝置與即時同步基礎 |
| `ai_config.py`、`model_library.py` | 模型設定與供應商切換 |
| `storage.py`、既有測試 | 資料保存與回歸保護 |

### 修改

| 模組 | 改造方向 |
|---|---|
| `character.py` | 抽離人格資料與畫面角色控制 |
| `renderer.py` | 加入 Character Adapter 與動畫事件 |
| `templates/pet.html` | 改為房間場景、角色層、對話層 |
| `src-tauri/`、`windows/`、`windows_launcher.py` | Windows 視窗、透明層與啟動流程 |
| `soul.md`、Prompt 組合 | 改為自己的角色設定，保留可配置能力 |
| 設定頁 | 加入模型、語音、螢幕觀察與主動陪伴開關 |

### 第一版停用或延後

下列功能先保留原始碼，不在 V1 主要流程啟用：

- 公開 Landing Page。
- 公開註冊與多人管理介面。
- Android Wallpaper／行動版完整流程。
- 對外 Server Sync 部署。
- 與房間互動無關的示範頁與實驗頁。

### 新增

- `companion/character_adapter/`：角色渲染器統一介面。
- `companion/animation/`：Idle／Walk／Talk／Emotion 狀態機。
- `companion/room/`：房間場景、可行走區域與互動點。
- `companion/voice/`：STT／TTS 可替換介面。
- `companion/privacy/`：感知權限與資料清除控制。
- `assets/companion/`：自有角色與房間素材；不得放入未授權 Live2D 範例模型。

## 4. 角色技術策略

先建立統一介面，不把核心綁死在單一動畫工具：

```text
Miru Core
   ↓ emotion / action / speech events
Character Adapter
   ├─ Existing Live2D Adapter
   ├─ DragonBones Adapter
   └─ Sprite/GIF Adapter
```

V1 可先使用現有 Live2D 路徑驗證事件與桌面視窗，再接入自己的 DragonBones 或其他角色格式。角色素材需求至少包含：

- Idle／呼吸
- Blink／微笑
- Look Around
- Talk
- Walk Left／Right
- Happy／Sad／Surprised／Thinking
- Enter／Exit 或 Sleep

所有動作必須維持同一角色比例、錨點與畫面尺度。

## 5. 模型與費用原則

- ChatGPT Plus 訂閱不能直接當作本程式的 OpenAI API 額度。
- 支援 OpenAI-compatible API 時，畫面必須清楚說明可能產生額外費用。
- 本機模型列為可選方案，不承諾所有功能都能在 RTX 3060 Ti 8GB 上達到雲端模型速度與品質。
- API Key 不得提交到 GitHub；只允許放在本機環境變數或安全設定儲存區。
- `.env.example` 只能提供欄位名稱與說明，不放真實密鑰。

## 6. 隱私與安全底線

- 螢幕截圖預設關閉。
- 麥克風預設關閉。
- 主動陪伴可暫停並能設定安靜時段。
- 影像與語音資料的保存位置必須可見。
- 提供「刪除本次對話」、「刪除記憶」及「完全停止感知」入口。
- 日誌不得輸出 API Key、密碼或完整敏感畫面內容。
- 自動更新與多裝置同步在啟用前需再次確認。

## 7. 開發階段

### Phase 0：基準確認

- 在 Windows 安裝並啟動原始 Miru。
- 記錄 Python、Node、Rust、WebView2 與 Live2D 依賴。
- 執行原始測試，保存可運作基準。
- 驗證目前公開原始碼未包含的 Live2D 元件與模型。

### Phase 1：角色抽象與品牌隔離

- 建立 Character Adapter。
- 將 Miru 品牌與角色資源從核心邏輯解耦。
- 保留 Apache-2.0、原作者聲明與第三方授權。
- 建立自己的角色設定檔，不直接覆寫原始人格資料。

### Phase 2：房間與移動

- 單一房間背景。
- 可行走區域與碰撞邊界。
- 點擊移動與閒置巡走。
- 家具互動點與簡單動作切換。

### Phase 3：文字與語音

- 房間內文字聊天面板。
- 按鍵說話的 STT。
- 可中止的 TTS。
- Talk 動畫與音訊播放同步。

### Phase 4：記憶與主動陪伴

- 驗證記憶新增、搜尋、修改與刪除。
- 調整 Attention Engine，避免過度打擾。
- 將情緒狀態映射到角色表情與動作。
- 加入安靜時段、工作模式與隱私模式。

### Phase 5：Windows 打包

- 建立可重複的 Windows Build。
- 新機器安裝測試。
- 錯誤日誌與復原流程。
- 完成 V1 使用說明與授權清單。

## 8. V1 驗收條件

- Windows 啟動、關閉與重新啟動不會損壞資料。
- 角色能在房間內 Idle、Walk、Talk 並切換至少 4 種情緒。
- 文字聊天可用；模型未設定時提供明確說明而不是假裝成功。
- 語音功能無權限時能正常降級為文字。
- 記憶可查看、修改與刪除。
- 螢幕觀察、麥克風與主動陪伴均可完全關閉。
- 測試不包含真實 API Key、私人對話或未授權角色素材。
- 發布包保留 `LICENSE` 與 `THIRD_PARTY_NOTICES.md`。

## 9. Git 工作方式

- `main`：保持可回復的穩定版本。
- `develop/companion-v1`：V1 整合分支。
- 每一階段使用獨立 feature branch 與 Pull Request。
- 尚未在 Windows 實機驗證的變更，不直接合併到 `main`。
- 定期從原作者 upstream 同步安全修正，避免直接覆蓋自己的角色層。

## 10. 下一步

1. 在 Windows 跑通未修改的 Miru。
2. 確認 Live2D SDK／模型授權與本機路徑。
3. 建立 Character Adapter 最小介面。
4. 決定 V1 第一個可用角色格式：Live2D、DragonBones 或 Sprite。
5. 將角色規格、房間規格與動畫清單轉成可直接製作的素材表。
