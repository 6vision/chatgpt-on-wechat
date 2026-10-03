# encoding:utf-8
"""_compress_image keeps the source format when it has to downscale."""

import importlib.util
import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

Image = pytest.importorskip("PIL.Image")

_SCRIPT = Path(__file__).parents[1] / "skills" / "image-generation" / "scripts" / "generate.py"
_SPEC = importlib.util.spec_from_file_location("image_gen_compress_script", _SCRIPT)
image_generation = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(image_generation)


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP"])
def test_resized_image_keeps_source_format(fmt):
    # A smooth gradient keeps any PNG re-encode under max_bytes, so the JPEG
    # fallback cannot mask a lost format.
    img = Image.new("RGB", (320, 200))
    img.putdata([(x * 255 // 319, y * 255 // 199, 128) for y in range(200) for x in range(320)])
    buf = io.BytesIO()
    img.save(buf, format=fmt)

    out = image_generation._compress_image(buf.getvalue(), max_bytes=4 * 1024 * 1024, max_edge=64)

    resized = Image.open(io.BytesIO(out))
    assert resized.format == fmt
    assert max(resized.size) == 64
