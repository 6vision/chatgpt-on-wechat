import base64
import io
import os
import shutil
import pytest
from agent.tools.vision.vision import Vision


def test_compressed_jpeg_has_matching_data_url_mime(tmp_path, monkeypatch):
    image = pytest.importorskip('PIL.Image')
    original = tmp_path / 'original.png'
    converted = tmp_path / 'compressed.jpg'
    image.new('RGB', (2, 2), 'red').save(original)
    image.new('RGB', (2, 2), 'red').save(converted)
    monkeypatch.setattr(Vision, '_maybe_compress', staticmethod(lambda path: str(converted)))
    url = Vision()._build_image_content(str(original))['image_url']['url']
    header, data = url.split(',', 1)
    assert header == 'data:image/jpeg;base64'
    assert image.open(io.BytesIO(base64.b64decode(data))).format == 'JPEG'
    assert not converted.exists()
    assert original.exists()


@pytest.mark.skipif(shutil.which('sips') is None, reason='Native macOS sips unavailable')
def test_native_png_compression_produces_jpeg_bytes_and_mime(tmp_path):
    image = pytest.importorskip('PIL.Image')
    original = tmp_path / 'noise.png'
    image.frombytes('RGB', (650, 650), os.urandom(650 * 650 * 3)).save(original)
    assert original.stat().st_size > 1048576
    before = original.read_bytes()
    url = Vision()._build_image_content(str(original))['image_url']['url']
    header, data = url.split(',', 1)
    assert header == 'data:image/jpeg;base64'
    decoded = image.open(io.BytesIO(base64.b64decode(data)))
    assert decoded.format == 'JPEG'
    assert original.read_bytes() == before
