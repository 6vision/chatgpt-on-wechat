# Vendor assets

Third-party frontend assets bundled locally so the Web Console can run in
fully offline / air-gapped environments (no requests to cloudflare, jsdelivr,
googleapis, gstatic, etc.).

All files here are vendored copies of upstream releases. Do not edit them by
hand; re-download from the official source if upgrading.

## Manifest

| Path                                                | Source                                                                                            | Version |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------- |
| `fontawesome/css/all.min.css`                       | https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css                         | 6.4.0   |
| `fontawesome/webfonts/fa-{brands,regular,solid,v4compatibility}-*.woff2` | https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/              | 6.4.0   |
| `fonts/inter/inter-latin.woff2`                     | https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa1ZL7.woff2                  | v20     |
| `fonts/inter/inter.css`                             | Hand-written `@font-face` declaration that maps Inter weights 300-700 to the local woff2          | -       |
| `tailwind/tailwind.min.js`                          | https://cdn.tailwindcss.com (Play CDN runtime, JIT engine for the browser)                        | latest  |
| `markdown-it/markdown-it.min.js`                    | https://cdn.jsdelivr.net/npm/markdown-it@13.0.1/dist/markdown-it.min.js                           | 13.0.1  |
| `highlightjs/highlight.min.js`                      | https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js                       | 11.9.0  |
| `highlightjs/styles/github{,-dark}.min.css`         | https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/                                | 11.9.0  |
| `highlightjs/languages/{python,javascript,java,go,bash}.min.js` | https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/                  | 11.9.0  |
| `d3/d3.min.js`                                      | https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js (loaded lazily for the knowledge graph view)     | 7.x     |

## Runtime-loaded assets (not vendored)

One asset is fetched from a CDN at runtime instead of being carried in-tree
(per the review decision on #3221: mermaid is large and diagrams are an
optional feature). It is version-pinned and verified by a subresource
integrity (SRI) hash, so a tampered or silently-changed CDN build cannot run
in the console; the same hash is baked into the loader in
`static/js/core/markdown.js`. Consoles without internet access simply keep
```` ```mermaid ```` blocks as plain code blocks.

| Asset           | Source                                                        | Version | SRI (sha384)                                                                                   |
| --------------- | ------------------------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------- |
| `mermaid.min.js` | https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js | 11.17.2 | `sha384-EOXBFmc3gx5mb+vn0vPvvGqACToJD24hhacX5Yx+8NUUQrHIle/Qi5Bg9o3zKwW2` |

Notes:

- The Inter font only ships the latin subset (CJK characters fall back to the
  system sans-serif via the font-family chain in `tailwind.config`).
- Only `woff2` font files are shipped (no `ttf` fallback). woff2 is supported
  by all browsers released since 2014-2018 (Chrome 36+, Firefox 39+, Safari
  12+, Edge, Opera 26+). The only mainstream browser that lacks woff2 support
  is IE 11, which cannot run the rest of the console anyway. `all.min.css`
  still references the ttf paths as a `src:` fallback — those 404s are
  harmless and ignored by the browser once the woff2 loads.
- `tailwind.min.js` is the official Tailwind Play CDN build (an in-browser JIT
  engine). It must be served as JS to keep the existing `tailwind.config = {}`
  customization working.
- `mermaid.min.js` is the IIFE build (attaches `window.mermaid`; the ESM
  build would need an import map). MIT licensed. Mermaid fences show as code
  by default; `ensureMermaidLoaded()` in `static/js/core/markdown.js` injects
  the script only when the user clicks Preview on one, so page loads never
  download the ~3.5MB. It always renders with `securityLevel: 'strict'`
  because message content is untrusted agent output. A failed load (offline,
  blocked CDN, integrity mismatch) falls back to the code view and is retried
  on the next Preview click.
- One external script remains, in `channel/web/static/js/views/channels-wecom.js`:
  `wwcdn.weixin.qq.com/.../wecom-aibot-sdk` — Tencent requires the WeCom Bot
  SDK to be loaded from their CDN, and it is only fetched when the user opens
  the WeCom Bot QR-login flow.
