# 使用者提供的圖片角色

八張原圖依檔名末尾 (1)–(8) 對應 idle、blink、talking、thinking、happy、sad、surprised、sleeping。
原檔為 1254×1254 RGBA PNG，直接複製，未重繪、裁切或修改像素。
角色素材不因存放於本專案而自動取得程式碼的 Apache-2.0 授權。

啟動此開發分支的 Miru 後，展開桌寵工具列，按「圖片」切換。
按「Live2D」可切回；選擇記錄於本機。首次開啟仍使用 Live2D。
圖片角色的縮放、位置保存與 Live2D 分開。拖曳、點擊穿透的 Windows 實機效果待驗證。

預覽：`/assets/companion/portrait/preview.html`，提供七種姿勢按鈕及待機眨眼。
從專案根目錄執行 `python -m http.server 8787` 也可在相同路徑預覽，不需 API Key。

待機每四秒閉眼約 140ms。說話圖有不同手勢，因此顯示固定姿勢，不高速切回待機，亦不表示嘴型同步。
目前沒有走路圖；左右走路狀態退回待機。此素材不是 Live2D 或骨架模型。
原圖髮絲與腿部輪廓有少量去背殘留，亮色背景較明顯；原始素材保持不變。
