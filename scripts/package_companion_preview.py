"""Build an offline, double-clickable portrait preview (not a desktop installer)."""
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def build(output: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    portrait = root / "assets/companion/portrait"
    html = (portrait / "preview.html").read_text(encoding="utf-8")
    html = html.replace("../../../../assets/js/companion/sprite-adapter.js", "sprite-adapter.js")
    html = html.replace("base:'./'", "base:'images/'")
    html = html.replace("<title>角色素材預覽</title>", "<title>Miru 圖片角色離線測試</title>")
    html = html.replace('<nav id="controls"></nav>', '''<nav id="controls"></nav>
<nav aria-label="背景顏色">
<button onclick="document.body.style.background='#f2eaf7';document.body.style.color='#30243e'">淺色背景</button>
<button onclick="document.body.style.background='#242333';document.body.style.color='white'">深色背景</button>
</nav>''')
    instructions = """Miru 圖片角色離線測試

1. 在 ZIP 檔按右鍵 → 全部解壓縮。
2. 開啟解壓後的資料夾，雙擊 index.html（使用 Edge 或 Chrome）。
3. 等待約四秒，確認待機角色會眨眼。
4. 依序按思考、說話、開心、難過、驚訝、睡眠。
5. 切換淺色／深色背景，確認沒有黑色方框；原圖邊緣有少量去背殘留。
6. 關閉頁面再開啟，確認圖片仍正常。也可中斷網路後重開測試。

請完整解壓，不要只把 index.html 移出資料夾。
本包只測試圖片、眨眼與姿勢切換，不含聊天、語音、桌面透明視窗或房間移動。
說話是固定抬手姿勢，沒有嘴型同步；睡眠需手動按待機離開。
不需要 API Key、Python 或其他安裝，也不讀寫已安裝 Miru 的設定或對話。
這不是 Miru 安裝程式，不會更新已安裝的桌寵。

原始角色圖片由使用者提供，保持像素不變。
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("index.html", html)
        archive.writestr("README.txt", instructions.encode("utf-8-sig"))
        archive.write(root / "assets/js/companion/sprite-adapter.js", "sprite-adapter.js")
        for name in ("idle", "blink", "talking", "thinking", "happy", "sad", "surprised", "sleeping"):
            archive.write(portrait / f"{name}.png", f"images/{name}.png")
        archive.write(root / "LICENSE", "LICENSE")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    build(parser.parse_args().output)
