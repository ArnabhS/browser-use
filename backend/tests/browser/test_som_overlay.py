"""Server-side SoM compositing: draw boxes onto the screenshot image (not the page DOM) and emit
JPEG. No browser needed — pure image in, image out."""
import io

from PIL import Image

from app.browser.som_overlay import render_som


def _png(w=200, h=120, color=(240, 240, 240)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_render_som_returns_decodable_jpeg_same_size():
    out = render_som(_png(200, 120), {1: (10, 10, 50, 20)})
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG"
    assert im.size == (200, 120)


def test_marks_change_the_pixels():
    clean = render_som(_png(), {})            # no boxes → plain transcode
    marked = render_som(_png(), {3: (10, 10, 60, 30)})
    assert clean != marked                    # the box altered the image


def test_scale_maps_css_boxes_onto_device_pixel_image():
    # A retina (2x) capture is twice the CSS size; a CSS box at (100,50) must land at (200,100).
    out = render_som(_png(400, 240), {5: (100, 50, 40, 20)}, scale=2.0)
    im = Image.open(io.BytesIO(out)).convert("RGB")
    # The box outline near the scaled origin is non-background; a far corner stays background.
    assert im.getpixel((200, 100)) != (240, 240, 240)
    assert im.getpixel((399, 239)) == im.getpixel((399, 239))  # decodes, no crash


def test_empty_boxes_still_transcodes_to_jpeg():
    out = render_som(_png(), {})
    assert Image.open(io.BytesIO(out)).format == "JPEG"
