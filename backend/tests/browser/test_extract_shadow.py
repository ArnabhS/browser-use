"""The extractor walked document.querySelectorAll('*'), which never crosses shadow boundaries — so
interactables inside an open shadow root (web components: many banking/enterprise sites, some
cookie banners) were invisible to the agent. It must pierce open shadow roots."""
import pytest

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser

_ATTACH_SHADOW = """() => {
  const host = document.getElementById('host');
  const root = host.attachShadow({mode: 'open'});
  const b = document.createElement('button');
  b.textContent = 'ShadowGo';
  b.style.cssText = 'position:absolute;top:40px;left:40px;width:90px;height:30px';
  root.appendChild(b);
  // nested shadow root, to prove recursion
  const inner = document.createElement('div');
  root.appendChild(inner);
  const r2 = inner.attachShadow({mode: 'open'});
  const b2 = document.createElement('button');
  b2.textContent = 'DeepGo';
  b2.style.cssText = 'position:absolute;top:90px;left:40px;width:90px;height:30px';
  r2.appendChild(b2);
}"""


async def test_extractor_pierces_open_shadow_dom():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content('<div id="host"></div>')
        await sess.page.evaluate(_ATTACH_SHADOW)
        obs = await sess.observe()
        names = [(e.name or "").lower() for e in obs.elements]
        assert any("shadowgo" in n for n in names)   # one level deep
        assert any("deepgo" in n for n in names)      # nested shadow root
    finally:
        await sess.stop()
