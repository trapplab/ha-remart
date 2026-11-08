"""Prepare images for the Frame panel."""

import io

from PIL import Image, ImageOps

from .const import MAX_WIDTH


def fit_to_frame(data: bytes, max_width: int = MAX_WIDTH) -> bytes:
    """Letterbox an image onto a black 16:9 canvas and encode it as JPEG.

    The Frame stretches anything that is not 16:9 to fill the screen, so the
    whole image is kept and padded instead of cropped. Canvases wider than
    ``max_width`` are scaled down to it. Blocking; run in the executor.
    """
    with Image.open(io.BytesIO(data)) as src:
        image = ImageOps.exif_transpose(src).convert("RGB")

    src_w, src_h = image.size
    if src_w * 9 > src_h * 16:
        dst_w, dst_h = src_w, round(src_w * 9 / 16)
    else:
        dst_w, dst_h = round(src_h * 16 / 9), src_h
    if dst_w > max_width:
        dst_w, dst_h = max_width, round(max_width * 9 / 16)

    scale = min(dst_w / src_w, dst_h / src_h)
    fit_w, fit_h = round(src_w * scale), round(src_h * scale)
    if (fit_w, fit_h) != (src_w, src_h):
        image = image.resize((fit_w, fit_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (dst_w, dst_h), (0, 0, 0))
    canvas.paste(image, ((dst_w - fit_w) // 2, (dst_h - fit_h) // 2))

    out = io.BytesIO()
    # Baseline (non-progressive) JPEG; some Frame firmwares reject progressive.
    canvas.save(out, "JPEG", quality=90, progressive=False)
    return out.getvalue()


def make_preview(jpeg: bytes, width: int = 640) -> bytes:
    """Return a small copy for the media player's entity picture. Blocking."""
    with Image.open(io.BytesIO(jpeg)) as image:
        image.thumbnail((width, width))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=80)
    return out.getvalue()
