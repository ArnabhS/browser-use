"""select_option vs custom dropdown widgets (Select2/Chosen/Zoho — seen live on kuhoo.com's
Zoho contact form): the native <select> is shrunk to 1×1px and overlaid by a styled sibling
span[role=combobox], so elementFromPoint never returns it and closest('select') finds nothing.
The handler must adopt the container's (unambiguous) sibling select, and the extractor must
index the open list's individual options (Select2 v4.0 renders them role=treeitem)."""
import pytest
from app.browser.local_cdp import LocalCDPSession
from browser_agent_contracts import ActionCall

pytestmark = pytest.mark.browser

# Mirrors Zoho/Select2 markup: hidden-accessible native select + styled overlay sibling.
_SELECT2_HTML = """
<html><body>
  <div id="field" style="width:400px">
    <select id="s" aria-hidden="true"
            style="position:absolute;width:1px;height:1px;clip:rect(0,0,0,0);overflow:hidden">
      <option value=""></option>
      <option value="loan">Loan enquiry</option>
      <option value="media">Media enquiry</option>
    </select>
    <span role="combobox" tabindex="0"
          style="display:block;width:380px;height:40px;border:1px solid #888">Select enquiry type</span>
  </div>
  <div id="out">idle</div>
  <script>
    document.getElementById('s').addEventListener('change',
      e => document.getElementById('out').innerText = 'sel:' + e.target.value);
  </script>
</body></html>
"""

# A fully synthetic dropdown — no native <select> anywhere.
_PURE_CUSTOM_HTML = """
<html><body>
  <div role="combobox" tabindex="0" style="width:300px;height:40px;border:1px solid #888">Pick one</div>
</body></html>
"""

# Select2 v4.0 open-state list: role=tree container with role=treeitem options.
_OPEN_LIST_HTML = """
<html><body>
  <ul role="tree" style="width:300px">
    <li role="treeitem" style="height:30px">Loan enquiry</li>
    <li role="treeitem" style="height:30px">Media enquiry</li>
  </ul>
</body></html>
"""


async def _session(html: str):
    sess = LocalCDPSession()
    await sess.start()
    await sess.page.set_content(html)
    return sess


async def test_select_option_adopts_hidden_sibling_select():
    sess = await _session(_SELECT2_HTML)
    try:
        obs = await sess.observe()
        combo = next(e for e in obs.elements if e.role == "combobox")
        res = await sess.act(ActionCall(name="select_option",
                                        args={"index": combo.index, "value": "Loan enquiry"}))
        assert res.success, res.reason
        assert await sess.page.input_value("#s") == "loan"
        assert await sess.page.inner_text("#out") == "sel:loan"  # change event reached listeners
    finally:
        await sess.stop()


async def test_select_option_matches_option_text_case_insensitively():
    sess = await _session(_SELECT2_HTML)
    try:
        obs = await sess.observe()
        combo = next(e for e in obs.elements if e.role == "combobox")
        res = await sess.act(ActionCall(name="select_option",
                                        args={"index": combo.index, "value": "loan ENQUIRY"}))
        assert res.success, res.reason
        assert await sess.page.input_value("#s") == "loan"
    finally:
        await sess.stop()


async def test_select_option_unmatched_value_reports_the_real_options():
    sess = await _session(_SELECT2_HTML)
    try:
        obs = await sess.observe()
        combo = next(e for e in obs.elements if e.role == "combobox")
        res = await sess.act(ActionCall(name="select_option",
                                        args={"index": combo.index, "value": "Refund"}))
        assert not res.success
        assert "Loan enquiry" in res.reason  # teach the model the exact option texts
    finally:
        await sess.stop()


async def test_select_option_on_pure_custom_dropdown_guides_to_click_path():
    sess = await _session(_PURE_CUSTOM_HTML)
    try:
        obs = await sess.observe()
        combo = next(e for e in obs.elements if e.role == "combobox")
        res = await sess.act(ActionCall(name="select_option",
                                        args={"index": combo.index, "value": "Anything"}))
        assert not res.success
        assert "click" in res.reason.lower()  # steer the model to Click-to-open + Click-the-option
    finally:
        await sess.stop()


async def test_open_dropdown_options_are_indexed_individually():
    sess = await _session(_OPEN_LIST_HTML)
    try:
        obs = await sess.observe()
        names = [e.name for e in obs.elements if e.role == "treeitem"]
        assert "Loan enquiry" in names and "Media enquiry" in names
    finally:
        await sess.stop()
