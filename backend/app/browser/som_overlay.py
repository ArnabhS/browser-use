"""Server-side Set-of-Marks: draw the numbered boxes onto the captured screenshot in Python instead
of injecting them into the live page DOM. This keeps the marks off the user's real browser window
(no flashing overlay) while still handing the model a marked image, and lets us emit JPEG in the
same pass (much smaller than PNG over the wire, no cost to SoM legibility)."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

# Same palette as the old in-page overlay, so the marked image looks unchanged to the model.
_COLORS = ["#E6194B", "#3CB44B", "#4363D8", "#F58231", "#911EB4", "#008080", "#F032E6", "#BFEF45"]


def _font(px: int):
    try:
        return ImageFont.load_default(size=px)  # Pillow >= 10.1 supports a sizeable default font
    except TypeError:
        return ImageFont.load_default()


def render_som(image_bytes: bytes, boxes: dict[int, tuple[float, float, float, float]],
               scale: float = 1.0, *, quality: int = 72) -> bytes:
    """Composite SoM boxes + index labels onto a screenshot and return JPEG bytes.

    `boxes` maps index -> (x, y, w, h) in CSS pixels (viewport-relative, as the funnel produces).
    `scale` is the device-pixel ratio, so marks line up with a device-pixel capture. With no boxes
    this just transcodes to JPEG.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if boxes:
        draw = ImageDraw.Draw(img)
        lw = max(1, round(2 * scale))
        font = _font(max(11, round(12 * scale)))
        lh = round(15 * scale)
        for idx, box in boxes.items():
            x, y, w, h = (v * scale for v in box)
            color = _COLORS[idx % len(_COLORS)]
            draw.rectangle([x, y, x + w, y + h], outline=color, width=lw)
            label = str(idx)
            tw = draw.textlength(label, font=font)
            ly = y - lh if y - lh >= 0 else y  # chip above the box, or inside if at the top edge
            draw.rectangle([x, ly, x + tw + 4 * scale, ly + lh], fill=color)
            draw.text((x + 2 * scale, ly), label, fill="#FFFFFF", font=font)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality)
    return out.getvalue()
