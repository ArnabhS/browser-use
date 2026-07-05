"""Read-only page-inspection helpers behind the `search_page` / `find_elements` tools (P0-4).

The JS is shared by both browser backends (LocalCDPSession via page.evaluate, CDPSession via
Runtime.evaluate); the result dict is serialized here into the text the model reads in the tool result.
These give the agent a decisive "is X on the page?" instead of scrolling blindly — and are cheaper
than the LLM-backed `extract` for simple presence/structure checks.
"""
from __future__ import annotations

# grep the page's visible text: args = [pattern, regex, caseSensitive, maxResults, contextChars]
SEARCH_JS = r"""
([pattern, regex, caseSensitive, maxResults, contextChars]) => {
  const text = document.body ? document.body.innerText : '';
  let re;
  try {
    const src = regex ? pattern : pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    re = new RegExp(src, caseSensitive ? 'g' : 'gi');
  } catch (e) { return { error: 'bad pattern: ' + e.message }; }
  const out = []; let m;
  while ((m = re.exec(text)) !== null && out.length < maxResults) {
    const start = Math.max(0, m.index - contextChars);
    const end = Math.min(text.length, m.index + m[0].length + contextChars);
    out.push(text.slice(start, end).replace(/\s+/g, ' ').trim());
    if (m.index === re.lastIndex) re.lastIndex++;  // guard against a zero-width match looping forever
  }
  return { matches: out };
}
"""

# CSS query: args = [selector, attributes|null, maxResults, includeText]
FIND_JS = r"""
([selector, attributes, maxResults, includeText]) => {
  let els;
  try { els = document.querySelectorAll(selector); }
  catch (e) { return { error: 'bad selector: ' + e.message }; }
  const out = [];
  for (const el of els) {
    if (out.length >= maxResults) break;
    const row = { tag: el.tagName.toLowerCase() };
    if (includeText) row.text = (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120);
    if (attributes) for (const a of attributes) { const v = el.getAttribute(a); if (v != null) row[a] = v; }
    out.push(row);
  }
  return { count: els.length, results: out };
}
"""


def search_args(a: dict) -> list:
    return [str(a.get("pattern", "")), bool(a.get("regex", False)),
            bool(a.get("case_sensitive", False)), int(a.get("max_results", 25)), 60]


def find_args(a: dict) -> list:
    return [str(a.get("selector", "")), a.get("attributes"),
            int(a.get("max_results", 50)), bool(a.get("include_text", True))]


def format_search(res: dict | None) -> str:
    res = res or {}
    if res.get("error"):
        return f"search_page error: {res['error']}"
    matches = res.get("matches", [])
    if not matches:
        return "no matches on the page for that pattern"
    return "\n".join([f"{len(matches)} match(es):", *(f"  … {m} …" for m in matches)])


def format_find(res: dict | None) -> str:
    res = res or {}
    if res.get("error"):
        return f"find_elements error: {res['error']}"
    results = res.get("results", [])
    total = int(res.get("count", len(results)))
    if not results:
        return "no elements match that selector"
    lines = [f"{total} element(s) match; showing {len(results)}:"]
    for r in results:
        extra = " ".join(f"{k}={v!r}" for k, v in r.items() if k != "tag")
        lines.append(f"  {r.get('tag', '')}{(' ' + extra) if extra else ''}")
    return "\n".join(lines)
