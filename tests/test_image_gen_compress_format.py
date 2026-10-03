# encoding:utf-8
"""
Regression tests for the image-generation skill's format-preserving compression.

``generate._compress_image`` reads the source format off the ``PIL.Image`` it
opened, but it read ``img.format`` *after* the optional downscale. ``Image.resize()``
returns a brand new image with ``.format`` set to ``None``, so any source whose
longest edge exceeded ``max_edge`` lost its format and fell through to the
``"PNG"`` default: a resized JPEG was re-encoded losslessly as PNG and
``_save_image`` then sniffed the PNG magic bytes and labelled the file ``.png``.
The user who asked for a JPEG received a PNG of the same pixels instead --
visibly wrong, and for lossy sources several times larger than the original.

The fix captures ``img.format`` before the resize, so the re-encode matches the
source format exactly as the already-correct non-resize path does.

The image is built with a smooth gradient rather than noise on purpose: PNG
re-encodes noise badly enough to exceed ``max_bytes``, which trips the
``else`` branch's JPEG fallback and would mask the defect.
"""

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "skills"
    / "image-generation"
    / "scripts"
    / "generate.py"
)
_SPEC = importlib.util.spec_from_file_location("image_gen_compress_script", _SCRIPT_PATH)
image_generation = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(image_generation)

# Small enough to keep the test fast; the ratio is what matters, not the pixels.
_SOURCE_SIZE = (320, 200)
# Below the source's longest edge, so _compress_image takes the resize branch.
_MAX_EDGE = 64


def _encode(fmt, size=_SOURCE_SIZE):
    """Build a smooth ``size`` image and return its bytes encoded as ``fmt``.

    A smooth gradient keeps the PNG re-encode well under ``max_bytes`` so the
    defect is visible instead of being masked by the JPEG fallback.
    """
    from PIL import Image

    img = Image.new("RGB", size)
    img.putdata([
        ((x * 255) // (size[0] - 1), (y * 255) // (size[1] - 1), 128)
        for y in range(size[1])
        for x in range(size[0])
    ])
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _compress(data):
    """Run _compress_image over the resize branch with the default size cap."""
    return image_generation._compress_image(data, max_bytes=4 * 1024 * 1024, max_edge=_MAX_EDGE)


class TestCompressKeepsSourceFormat(unittest.TestCase):
    """A downscale must not silently change the output format."""

    def setUp(self):
        # Skip if Pillow is not available in the test environment.
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")

    def test_resized_jpeg_stays_jpeg(self):
        """A JPEG past max_edge comes back as a JPEG, not a PNG."""
        from PIL import Image

        out = _compress(_encode("JPEG"))

        self.assertEqual(Image.open(io.BytesIO(out)).format, "JPEG")

    def test_resized_jpeg_is_not_re_encoded_as_png(self):
        """The JPEG branch is taken, so the bytes carry JPEG magic.

        Without the fix the source format is lost and the lossless PNG encoder
        runs instead, so the payload starts with the PNG signature.
        """
        out = _compress(_encode("JPEG"))

        self.assertEqual(out[:3], b"\xff\xd8\xff")

    def test_resized_webp_stays_webp(self):
        """WebP is not a PNG either; it kept its own format before the resize."""
        from PIL import Image

        out = _compress(_encode("WEBP"))

        self.assertEqual(Image.open(io.BytesIO(out)).format, "WEBP")

    def test_png_source_stays_png(self):
        """The PNG default was already correct for PNG input; keep it that way."""
        from PIL import Image

        out = _compress(_encode("PNG"))

        self.assertEqual(Image.open(io.BytesIO(out)).format, "PNG")

    def test_output_extension_matches_source_format(self):
        """_save_image's magic-byte sniffing must agree with the format.

        This is the user-visible half of the defect: the file was handed back
        with a .png extension even though the request was for a JPEG.
        """
        for fmt, expected_ext in (("JPEG", ".jpg"), ("WEBP", ".webp"), ("PNG", ".png")):
            with self.subTest(fmt=fmt):
                out_dir = tempfile.mkdtemp()
                path = image_generation._save_image(_compress(_encode(fmt)), out_dir)
                self.assertTrue(
                    path.endswith(expected_ext),
                    f"{fmt} source saved as {os.path.basename(path)}, expected {expected_ext}",
                )

    def test_small_image_without_resize_is_unchanged(self):
        """Below max_edge the bytes are returned untouched, as before."""
        data = _encode("JPEG", size=(32, 20))

        self.assertIs(
            image_generation._compress_image(data, max_bytes=4 * 1024 * 1024, max_edge=_MAX_EDGE),
            data,
        )


if __name__ == "__main__":
    unittest.main()
