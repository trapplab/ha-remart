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


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ((1600, 900), (1600, 900)),  # already 16:9
        ((1000, 1000), (1000, 562)),  # square → top and bottom cut
        ((900, 1600), (900, 506)),  # portrait → top and bottom cut
        ((2000, 500), (889, 500)),  # panorama → sides cut
        ((8000, 4500), (3840, 2160)),  # larger than 4K → scaled down
        ((3000, 9000), (3000, 1688)),  # tall and huge, crop stays under 4K
    ],
)
def test_crop_to_frame_is_16_9(src, expected) -> None:
    """Cropped output is 16:9 too, never upscaled and at most 4K wide."""
    assert _size(fit_to_frame(png_bytes(*src), crop=True)) == expected


def test_crop_has_no_bars() -> None:
    """Cropping fills the canvas with the image, edges included."""
    jpeg = fit_to_frame(png_bytes(1000, 1000, (250, 250, 250)), crop=True)
    with Image.open(io.BytesIO(jpeg)) as image:
        w, h = image.size
        for xy in ((2, 2), (w - 3, h - 3), (w // 2, h // 2)):
            assert min(image.getpixel(xy)) > 230


def test_preview_is_small() -> None:
    """The preview fits in 640 px."""
    preview = make_preview(fit_to_frame(png_bytes(4000, 2250)))
    assert max(_size(preview)) == 640
