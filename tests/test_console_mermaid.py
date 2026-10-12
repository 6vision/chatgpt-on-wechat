# encoding:utf-8
"""The Web console previews ```mermaid fences as diagrams on demand (#3221).

The pipeline is browser JS, so these tests pin the static contract.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "channel" / "web"
VENDOR = WEB / "static" / "vendor" / "mermaid" / "mermaid.min.js"
CDN_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"
SRI_HASH = "sha384-EOXBFmc3gx5mb+vn0vPvvGqACToJD24hhacX5Yx+8NUUQrHIle/Qi5Bg9o3zKwW2"


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def _console_js():
    from conftest import console_js

    return console_js()


def test_mermaid_is_fetched_from_pinned_cdn_not_vendored():
    # Review decision on #3221: the ~3.5MB build is not carried in-tree;
    # it is fetched at runtime from a version-pinned URL instead.
    assert not VENDOR.exists()
    js = _console_js()
    assert f"const MERMAID_CDN_URL = '{CDN_URL}';" in js
    assert "script.src = MERMAID_CDN_URL;" in js
    readme = _read("channel/web/static/vendor/README.md")
    assert CDN_URL in readme, "the CDN source must be registered in the vendor manifest"
    assert "11.17.2" in readme


def test_cdn_load_is_sri_verified():
    # A pinned version alone does not protect against a tampered CDN: the
    # subresource integrity hash pins the exact build, and the README
    # manifest carries the same hash so a mismatch is visible in review.
    js = _console_js()
    match = re.search(r"const MERMAID_SRI_HASH = '(sha384-[^']+)';", js)
    assert match, "the CDN loader must define a subresource integrity hash"
    assert match.group(1) == SRI_HASH
    assert "script.integrity = MERMAID_SRI_HASH;" in js
    assert "script.crossOrigin = 'anonymous';" in js  # SRI requires CORS
    readme = _read("channel/web/static/vendor/README.md")
    assert SRI_HASH in readme


def _function_body(js, name):
    start = js.index(f"function {name}(")
    end = js.index("\n}\n", start)
    return js[start:end]


def test_mermaid_is_only_loaded_by_a_preview_click():
    page = _read("channel/web/chat.html")
    assert not re.search(r"<script[^>]*mermaid", page)
    js = _console_js()
    # Fences start as plain code blocks in code view.
    assert 'data-mermaid="idle" data-mermaid-mode="code"' in js
    assert "escapeHtml(token.content)" in js
    # The per-render hook only installs the switch and renders blocks already
    # marked pending; it never starts the download for idle blocks.
    hook = _function_body(js, "renderMermaidBlocks")
    assert "ensureMermaidLoaded" not in hook
    assert '.mermaid-block[data-mermaid="pending"]' in hook
    assert "ensureMermaidLoaded()" in _function_body(js, "_loadAndRenderMermaid")
    preview = _function_body(js, "_previewMermaidBlock")
    assert "block.dataset.mermaid = 'pending'" in preview
    assert "_previewMermaidBlock(block)" in _function_body(js, "_installMermaidToolbar")
    theme = _read("channel/web/static/js/core/theme.js")
    assert 'data-mermaid="done"' in _function_body(theme, "rerenderMermaidDiagrams")


def test_renderer_is_strict_and_theme_aware():
    js = _console_js()
    assert "securityLevel: 'strict'" in js  # no HTML labels, no callbacks
    assert "startOnLoad: false" in js
    assert "suppressErrorRendering: true" in js  # no mermaid error graphic
    assert "classList.contains('dark') ? 'dark' : 'default'" in js


def test_invalid_syntax_or_failed_load_falls_back_to_code_view():
    js = _console_js()
    invalid = _function_body(js, "_markMermaidInvalid")
    assert "block.dataset.mermaid = 'invalid'" in invalid
    assert "block.dataset.mermaidMode = 'code'" in invalid
    assert "_mermaidLoadPromise = null" in js  # a failed load can be retried
    assert "renderMermaidBlocks(root)" in js  # hooked into applyHighlighting


def test_preview_controls_only_show_on_a_rendered_diagram():
    js = _console_js()
    assert 'data-mermaid-view="chart"' in js and 'data-mermaid-view="code"' in js
    for action in ("in", "out", "reset"):
        assert f'data-mermaid-zoom="{action}"' in js
    assert "requestFullscreen" in js and "classList.toggle('mermaid-fullscreen')" in js
    css = _read("channel/web/static/css/markdown.css")
    done = '.mermaid-block[data-mermaid-mode="chart"][data-mermaid="done"]'
    assert f"{done} .mermaid-chart-tools" in css
    assert f"{done} .code-copy-btn" in css
    assert ".mermaid-block.mermaid-fullscreen" in css
    i18n = _read("channel/web/static/js/core/i18n.js")
    assert i18n.count("mermaid_preview:") == 3
