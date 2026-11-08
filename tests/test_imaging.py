"""Tests for image fitting."""

import io

from PIL import Image
import pytest

from custom_components.remart.imaging import fit_to_frame, make_preview

from .conftest import png_bytes


def _size(jpeg: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(jpeg)) as image:
        assert image.format == "JPEG"
        return image.size


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ((1600, 900), (1600, 900)),  # already 16:9
        ((1000, 1000), (1778, 1000)),  # square → pillarbox
        ((900, 1600), (2844, 1600)),  # portrait → pillarbox
        ((2000, 500), (2000, 1125)),  # panorama → letterbox
        ((8000, 4500), (3840, 2160)),  # larger than 4K → scaled down
        ((3000, 6000), (3840, 2160)),  # tall and huge
    ],
)
def test_fit_to_frame_is_16_9(src, expected) -> None:
    """Output is always 16:9 and at most 4K wide."""
    assert _size(fit_to_frame(png_bytes(*src))) == expected


def test_fit_keeps_image_centered_on_black() -> None:
    """Padding is black; the image itself stays in the middle."""
    jpeg = fit_to_frame(png_bytes(1000, 1000, (250, 250, 250)))
    with Image.open(io.BytesIO(jpeg)) as image:
        assert max(image.getpixel((5, 500))) < 20
        assert min(image.getpixel((889, 500))) > 230


def test_preview_is_small() -> None:
    """The preview fits in 640 px."""
    preview = make_preview(fit_to_frame(png_bytes(4000, 2250)))
    assert max(_size(preview)) == 640
