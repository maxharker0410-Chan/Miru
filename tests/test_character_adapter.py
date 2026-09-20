import json
import shutil
import subprocess
from pathlib import Path

import pytest

import app as app_module


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_JS = ROOT / "assets" / "js" / "companion" / "character-adapter.js"
PET_HTML = ROOT / "templates" / "pet.html"


def _run_node(script: str) -> dict:
    if not shutil.which("node"):
        pytest.skip("node not available")
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_character_adapter_facade_state_lifecycle_and_normalization():
    script = r"""
const api = require('./assets/js/companion/character-adapter.js');
const calls = [];
const adapter = {
  id: 'test-renderer',
  capabilities: { focusTracking: true, transparentBackground: true },
  mount: async () => calls.push(['mount']),
  unmount: async () => calls.push(['unmount']),
  setState: async (state) => calls.push(['state', state]),
  setEmotion: async (emotion, intensity) => calls.push(['emotion', emotion, intensity]),
  lookAt: (x, y) => calls.push(['lookAt', x, y]),
  resize: (w, h) => calls.push(['resize', w, h]),
  getBounds: () => ({ left: 1, top: 2, right: 11, bottom: 22 }),
};
(async () => {
  const facade = api.createFacade(adapter);
  const firstMount = await facade.mount({});
  const secondMount = await facade.mount({});
  await facade.setState('unknown-state');
  await facade.setState('sleeping');
  await facade.setState('talking');
  await facade.setEmotion('happy', 4);
  facade.lookAt(9, -9);
  facade.resize(420, 760, {});
  const bounds = facade.getBounds();
  const firstUnmount = await facade.unmount();
  const secondUnmount = await facade.unmount();
  console.log(JSON.stringify({
    firstMount, secondMount, firstUnmount, secondUnmount,
    state: facade.getState(), bounds, calls,
    capabilities: facade.capabilities,
  }));
})();
"""
    data = _run_node(script)

    assert data["firstMount"] is True
    assert data["secondMount"] is True
    assert data["firstUnmount"] is True
    assert data["secondUnmount"] is True
    assert data["state"] == "idle"
    assert data["bounds"] == {"left": 1, "top": 2, "right": 11, "bottom": 22}
    assert data["calls"].count(["mount"]) == 1
    assert data["calls"].count(["unmount"]) == 1
    assert ["state", "idle"] in data["calls"]
    assert data["calls"].count(["state", "sleeping"]) == 2
    assert ["emotion", "happy", 1] in data["calls"]
    assert ["lookAt", 1, -1] in data["calls"]
    assert data["capabilities"]["focusTracking"] is True
    assert data["capabilities"]["motions"] is False


def test_character_adapter_failure_is_isolated():
    script = r"""
const api = require('./assets/js/companion/character-adapter.js');
const errors = [];
const facade = api.createFacade({
  id: 'broken-renderer',
  mount: async () => { throw new Error('broken'); },
}, { onError: (detail) => errors.push(detail.action) });
(async () => {
  const mounted = await facade.mount({});
  console.log(JSON.stringify({ mounted, isMounted: facade.isMounted(), errors }));
})();
"""
    data = _run_node(script)
    assert data == {"mounted": False, "isMounted": False, "errors": ["mount"]}


def test_character_adapter_is_served_and_loaded_by_pet():
    response = app_module.app.test_client().get(
        "/assets/js/companion/character-adapter.js"
    )
    assert response.status_code == 200
    assert b"MiruCharacterAdapter" in response.data

    html = PET_HTML.read_text(encoding="utf-8")
    assert '<script src="/assets/js/companion/character-adapter.js"></script>' in html
    assert "_getCharacterFacade().mount" in html
    assert "continuing with text chat" in html


def test_character_adapter_has_no_capture_permissions():
    source = ADAPTER_JS.read_text(encoding="utf-8")
    assert "getUserMedia" not in source
    assert "getDisplayMedia" not in source
    assert "mediaDevices" not in source
