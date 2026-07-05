"""Observation extraction over raw CDP: runs the SAME funnel-input JS as the Playwright path
(app.observation.extract.EXTRACT_JS) via Runtime.evaluate instead of page.evaluate, so the downstream
funnel is byte-for-byte identical. Covers the main frame plus DIRECT child iframes (an isolated world
per frame, offset by the iframe's box — same math as the Playwright _extract_child_frames)."""
from __future__ import annotations

from app.observation.extract import EXTRACT_JS
from app.observation.raw import PageMeta, RawElement

# Child-frame guards (mirror the Playwright path): skip tracking pixels / hidden frames, cap the count.
_MAX_CHILD_FRAMES = 12
_MIN_FRAME_SIZE = 40.0


class CDPEvalError(RuntimeError):
    """A Runtime.evaluate that returned an uncaught JS exception."""


async def eval_json(client, session_id: str, expression: str, *, await_promise: bool = True):
    """Evaluate a JS expression in the page and return its value (returnByValue)."""
    result = await client.send.Runtime.evaluate(
        params={"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
        session_id=session_id,
    )
    details = result.get("exceptionDetails")
    if details:
        raise CDPEvalError(str(details.get("text", "Runtime.evaluate raised")))
    return result["result"].get("value")


async def extract_cdp(client, session_id: str) -> tuple[list[RawElement], PageMeta]:
    """Run EXTRACT_JS in the main frame + direct child iframes; build the (RawElement[], PageMeta) the
    funnel expects with all coordinates in main-viewport space."""
    data = await eval_json(client, session_id, f"({EXTRACT_JS})()")
    raw = [RawElement(**e) for e in data["elements"]]
    meta = PageMeta(
        url=data["url"], title=data["title"],
        viewport_width=data["viewport_width"], viewport_height=data["viewport_height"],
        scroll_x=data["scroll_x"], scroll_y=data["scroll_y"],
    )
    raw.extend(await extract_child_frames_cdp(client, session_id, meta))
    return raw, meta


async def _direct_child_frame_ids(client, session_id: str) -> list[str]:
    tree = await client.send.Page.getFrameTree(session_id=session_id)
    return [ch["frame"]["id"] for ch in (tree["frameTree"].get("childFrames") or [])]


async def extract_child_frames_cdp(client, session_id: str, meta: PageMeta) -> list[RawElement]:
    """Run EXTRACT_JS inside each DIRECT child iframe (HubSpot/Typeform/Stripe embeds, etc.) via an
    isolated world, offsetting every element by the iframe's box so its coordinates are main-viewport
    coordinates. A trusted click/type then lands inside the frame with no further routing. Same-origin
    frames always work; a cross-origin OOPIF whose isolated world can't be reached is skipped (never
    fatal). Deeper-than-one nesting is not offset-accumulated — direct children cover embedded forms."""
    out: list[RawElement] = []
    try:
        await client.send.DOM.getDocument(params={"depth": 1, "pierce": True}, session_id=session_id)
        frame_ids = await _direct_child_frame_ids(client, session_id)
    except Exception:
        return out
    extracted = 0
    for fid in frame_ids:
        if extracted >= _MAX_CHILD_FRAMES:
            break
        try:
            owner = await client.send.DOM.getFrameOwner(params={"frameId": fid}, session_id=session_id)
            box = await client.send.DOM.getBoxModel(
                params={"backendNodeId": owner["backendNodeId"]}, session_id=session_id
            )
        except Exception:
            continue
        model = box["model"]
        dx, dy = model["content"][0], model["content"][1]  # content quad top-left
        bw, bh = model["width"], model["height"]
        if bw < _MIN_FRAME_SIZE or bh < _MIN_FRAME_SIZE:
            continue
        try:
            world = await client.send.Page.createIsolatedWorld(
                params={"frameId": fid}, session_id=session_id
            )
            result = await client.send.Runtime.evaluate(
                params={"expression": f"({EXTRACT_JS})()", "returnByValue": True,
                        "awaitPromise": True, "contextId": world["executionContextId"]},
                session_id=session_id,
            )
            if result.get("exceptionDetails"):
                continue
            data = result["result"].get("value")
        except Exception:
            continue
        if not data:
            continue
        extracted += 1
        # Sites shrink embeds with CSS transform: scale(…) — the rendered box differs from the frame's
        # own layout width, so map through the ratio (unscaled → 1.0). Mirrors the Playwright path.
        fw, fh = data["viewport_width"], data["viewport_height"]
        sx = bw / fw if fw else 1.0
        sy = bh / fh if fh else 1.0
        for e in data["elements"]:
            e["x"] = e["x"] * sx + dx
            e["y"] = e["y"] * sy + dy
            e["width"] *= sx
            e["height"] *= sy
            e["in_viewport"] = bool(e["in_viewport"]) and (
                e["x"] + e["width"] > 0 and e["y"] + e["height"] > 0
                and e["x"] < meta.viewport_width and e["y"] < meta.viewport_height
            )
            out.append(RawElement(**e))
    return out
