# Miru 手機圖片角色測試版

這個獨立 Android APK 使用 `assets/companion/portrait` 的 21 張去背 PNG（三套服裝），無須 Live2D SDK。適用於 Android 8.0 以上；在 Vivo X300 Pro 上仍須由使用者安裝測試。它不會取代既有 Miru 電腦版，也不提供房間場景。

## 安裝及操作

1. 到 GitHub Actions 的 **Android Portrait APK** 成功執行紀錄，下載 `MiruPortrait-debug-apk`，解壓縮後在手機安裝 `app-debug.apk`。Android 可能要求允許從檔案管理員安裝應用程式。
2. 開啟「Miru 圖片角色」。按「設為桌面動態桌布」並確認套用，或按「顯示浮動角色」並在系統設定中允許顯示在其他應用程式上層。浮動角色可拖曳，點一下可返回操作頁；從通知或操作頁可關閉浮動角色。
3. 按「一般服／居家服／外出服」換裝；或在訊息欄輸入「換居家服」、「換外出服」、「換一般服」，單純輸入「換衣服」會依序切換，無需先設定 Miru 服務。九種表情測試按鈕遇到缺圖會使用同服裝的替代姿勢。一般及外出待機可眨眼；居家待機沒有閉眼圖。Android 桌面啟動器不一定把桌布觸控事件傳給動態桌布；若點桌布沒有反應，使用浮動角色或開啟應用程式進入聊天。
4. 若要聊天，輸入**手機可以連線**的 Miru 服務網址，必要時填存取權杖。必須由你自己執行／提供 Miru 後端；單有圖片、ChatGPT Plus 訂閱或 APK，無法產生 AI 回覆。手機的 `127.0.0.1` 不是電腦的服務；請使用可用的 HTTPS 網址，或在同一個 Wi-Fi 上使用電腦區域網路 IP。HTTP 不會傳送權杖。

聊天送到既有 Miru 的 `POST /api/chat`，JSON 為 `{"text":"…","sync":true}`；回覆取自 `reply`。服務網址與權杖只保存在這個應用程式的私有儲存空間。建置使用 GitHub Actions 的 Android SDK 和倉庫中現有的 Gradle wrapper；本機建置指令為 `bash miru-mobile/android/gradlew -p mobile-portrait/android assembleDebug`。

測試版 APK 使用 Android debug 簽章。每次 GitHub 建置的簽章可能不同；若更新安裝時顯示「與已安裝應用程式衝突」，先移除舊版「Miru 圖片角色」再安裝新版（舊版的服裝選擇和服務網址會清除）。後續正式發佈應另行簽章與安全檢查。
