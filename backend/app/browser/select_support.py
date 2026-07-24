"""select_option support shared by LocalCDPSession (Playwright) and CDPSession (raw CDP).

Custom dropdown widgets (Select2, Chosen, Zoho Forms — seen live on kuhoo.com's contact form)
shrink the native <select> to 1×1px and overlay a styled sibling span[role=combobox]. A hit-test
at the target's centre therefore never returns the select, and the select is a SIBLING, not an
ancestor. SELECT_JS walks up from the hit element and adopts the container's select when it is
unambiguous (exactly one inside). No Playwright imports here — the raw-CDP backend uses it too.
"""
from __future__ import annotations

from browser_agent_contracts import ActionResult

SELECT_JS = r"""
([cx, cy, value]) => {
  const el = document.elementFromPoint(cx, cy);
  let sel = el && (el.tagName === 'SELECT' ? el : el.closest('select'));
  if (!sel && el) {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const sels = p.querySelectorAll('select');
      if (sels.length === 1) { sel = sels[0]; break; }
      if (sels.length > 1) break;
    }
  }
  if (!sel) return { err: 'no_select' };
  const want = String(value).trim().toLowerCase();
  const opt = [...sel.options].find(o => o.value === value || o.text === value)
    || [...sel.options].find(o => o.value.trim().toLowerCase() === want
                               || o.text.trim().toLowerCase() === want);
  if (!opt) return { err: 'no_option',
                     options: [...sel.options].map(o => o.text.trim()).filter(Boolean).slice(0, 20) };
  // Native prototype setter + input/change so framework-controlled selects (React et al.) see it.
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(sel, opt.value);
  sel.dispatchEvent(new Event('input', { bubbles: true }));
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  return { ok: true };
}
"""


def select_result(res: object, value: object) -> ActionResult:
    """Map SELECT_JS's return value to an ActionResult whose reason TEACHES the model the next
    move: on a widget with no native select, steer to the Click-to-open + Click-the-option path;
    on a bad value, list the real option texts so the retry can match exactly."""
    if isinstance(res, dict) and res.get("ok"):
        return ActionResult(success=True, reason=f"selected {value}")
    if isinstance(res, dict) and res.get("err") == "no_option":
        opts = ", ".join(res.get("options") or []) or "(none)"
        return ActionResult(success=False,
                            reason=f"no option matching {value!r}; the options are: {opts}")
    return ActionResult(
        success=False,
        reason="no native dropdown here — this looks like a custom dropdown widget: "
               "Click it to open the list, then Click the option you want.",
    )
