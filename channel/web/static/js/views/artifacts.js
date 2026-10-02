/* Artifacts view: every file the conversations produced, newest first,
   grouped by day. Selecting one previews it beside the timeline, and the
   preview can lead back to the turn in the conversation that last wrote it.

   These are classic scripts sharing one global scope; see
   channel/web/README.md before changing the load order. Uses workspace.js
   (wsRenderPreview, wsIconClass, wsFormatSize), chat/timeline.js (the glide
   and flash), views/sessions.js (switchSession) and views/agents.js (the
   roster), all at call time only. */

const ART_PAGE_SIZE = 48;
const ART_SCOPE_KEY = 'cow_artifacts_scope';
const ART_TEXT_KINDS = new Set(['markdown', 'code', 'text', 'csv']);
// Only the head of a text file is drawn on its card; past this size the fetch
// costs more than the glimpse is worth.
const ART_TEXT_THUMB_MAX = 512 * 1024;
const ART_TEXT_THUMB_CHARS = 2400;

let artItems = [];
let artHasMore = false;
let artLoading = false;
let artLoadFailed = false;
let artLoadToken = 0;
let artKind = '';
let artQuery = '';
let artScope = localStorage.getItem(ART_SCOPE_KEY) || 'all';
let artSelected = null;
let artPendingFocus = null;
let artSearchTimer = null;
let artThumbObserver = null;
let artPageObserver = null;
let artToastTimer = null;
let artPreviewToken = 0;
let artInited = false;

function toggleArtifactsView() {
    navigateTo(currentView === 'artifacts' ? 'chat' : 'artifacts');
}

/** Called by navigateTo on every entry into the view. */
function loadArtifactsView() {
    _artInit();
    if (!agentCatalog.length) {
        loadAgentCatalog().then(() => { _artRenderScope(); _artRenderAll(); }).catch(() => {});
    }
    _artRenderScope();
    artReload();
}

/** Open the view on one file, e.g. from a file card in the conversation. */
function openArtifactsFor(meta) {
    if (meta && !meta.origin && currentView === 'chat') {
        // A file just produced live: it belongs to the session's latest turn.
        meta = Object.assign({}, meta, { origin: { session_id: sessionId, agent_id: activeAgentId, turn_seq: null } });
    }
    artPendingFocus = meta || null;
    if (currentView === 'artifacts') {
        _artApplyPendingFocus();
        return;
    }
    navigateTo('artifacts');
}

/** Language switch: day labels, times and empty states are built in JS. */
function rerenderArtifactsView() {
    _artRenderScope();
    _artRenderAll();
    if (artSelected) _artRenderPreviewChrome(artSelected);
}

// =====================================================================
// Setup
// =====================================================================
function _artInit() {
    if (artInited) return;
    artInited = true;

    document.querySelectorAll('#view-artifacts .art-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            if (artKind === chip.dataset.artKind) return;
            artKind = chip.dataset.artKind;
            _artSyncChips();
            artReload();
        });
    });

    const input = document.getElementById('art-search-input');
    input.addEventListener('input', () => {
        clearTimeout(artSearchTimer);
        artSearchTimer = setTimeout(() => {
            const q = input.value.trim();
            if (q === artQuery) return;
            artQuery = q;
            artReload();
        }, 220);
    });
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && input.value) {
            e.stopPropagation();
            input.value = '';
            input.dispatchEvent(new Event('input'));
        }
    });

    const list = document.getElementById('art-list');
    list.addEventListener('click', (e) => {
        const act = e.target.closest('[data-art-act]');
        if (act) {
            e.stopPropagation();
            _artRunAction(act.dataset.artAct, _artItemOf(act));
            return;
        }
        const reset = e.target.closest('[data-art-reset]');
        if (reset) {
            _artResetFilters();
            return;
        }
        if (e.target.closest('[data-art-retry]')) {
            artReload();
            return;
        }
        if (e.target.closest('[data-art-start]')) {
            navigateTo('chat');
            return;
        }
        const card = e.target.closest('.art-card');
        if (card) artSelect(_artItemOf(card));
    });
    list.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const card = e.target.closest('.art-card');
        if (!card || e.target !== card) return;
        e.preventDefault();
        artSelect(_artItemOf(card));
    });

    // Cards draw their thumbnails only once they come near the viewport.
    const scroller = document.getElementById('art-scroll');
    artThumbObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            artThumbObserver.unobserve(entry.target);
            _artMountThumb(entry.target);
        });
    }, { root: scroller, rootMargin: '320px 0px' });
    artPageObserver = new IntersectionObserver((entries) => {
        if (entries.some(en => en.isIntersecting)) _artLoadMore();
    }, { root: scroller, rootMargin: '600px 0px' });
    artPageObserver.observe(document.getElementById('art-sentinel'));

    // Page and document thumbnails are a full-size render scaled down to the
    // card, so they need the card's width in px.
    new ResizeObserver(_artSyncThumbWidth).observe(list);

    document.addEventListener('keydown', _artOnKey);

    // Leaving the view must not leave a video talking in the background.
    const view = document.getElementById('view-artifacts');
    new MutationObserver(() => {
        if (view.classList.contains('active')) return;
        view.querySelectorAll('video, audio').forEach(m => { try { m.pause(); } catch (_) {} });
    }).observe(view, { attributes: true, attributeFilter: ['class'] });
}

function _artSyncChips() {
    document.querySelectorAll('#view-artifacts .art-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.artKind === artKind);
    });
}

function _artSyncThumbWidth() {
    const list = document.getElementById('art-list');
    const thumb = list && list.querySelector('.art-thumb');
    if (thumb && thumb.offsetWidth) list.style.setProperty('--art-tw', String(thumb.offsetWidth));
}

function _artMultiAgent() {
    return agentCatalog.length > 1;
}

function _artRenderScope() {
    const el = document.getElementById('art-scope-select');
    if (!el) return;
    const multi = _artMultiAgent();
    el.classList.toggle('hidden', !multi);
    if (!multi) {
        artScope = 'all';
        return;
    }
    if (artScope !== 'all' && !agentCatalog.some(a => a.id === artScope)) artScope = 'all';
    const options = [{ value: 'all', label: t('artifacts_scope_all') }].concat(
        agentCatalog.map(a => ({ value: a.id, label: a.name || a.id, agent: a }))
    );
    initDropdown(el, options, artScope, (value) => {
        artScope = value;
        try { localStorage.setItem(ART_SCOPE_KEY, value); } catch (_) {}
        artReload();
    }, { withAvatar: true });
}

function _artResetFilters() {
    artKind = '';
    artQuery = '';
    const input = document.getElementById('art-search-input');
    if (input) input.value = '';
    _artSyncChips();
    artReload();
}

// =====================================================================
// Data
// =====================================================================
function _artFetch(params) {
    const qs = new URLSearchParams(Object.assign({ scope: artScope }, params));
    return fetch(`/api/artifacts?${qs.toString()}`)
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') throw new Error(data.message || 'Request failed');
            return data;
        });
}

function artReload() {
    const token = ++artLoadToken;
    artItems = [];
    artHasMore = false;
    artLoading = true;
    artLoadFailed = false;
    _artRenderSkeleton();
    _artFetch({ kind: artKind, q: artQuery, offset: 0, limit: ART_PAGE_SIZE })
        .then(data => {
            if (token !== artLoadToken) return;
            artItems = data.items || [];
            artHasMore = !!data.has_more;
            _artRenderAll();
            _artApplyPendingFocus();
        })
        .catch(() => {
            if (token !== artLoadToken) return;
            artLoadFailed = true;
            _artRenderAll();
        })
        .finally(() => {
            if (token === artLoadToken) artLoading = false;
        });
}

function _artLoadMore() {
    if (artLoading || !artHasMore || artLoadFailed) return;
    const token = artLoadToken;
    artLoading = true;
    _artSetSentinelBusy(true);
    _artFetch({ kind: artKind, q: artQuery, offset: artItems.length, limit: ART_PAGE_SIZE })
        .then(data => {
            if (token !== artLoadToken) return;
            const known = new Set(artItems.map(i => i.id));
            const fresh = (data.items || []).filter(i => !known.has(i.id));
            artItems = artItems.concat(fresh);
            artHasMore = !!data.has_more;
            _artAppendCards(fresh);
        })
        .catch(() => { if (token === artLoadToken) artHasMore = false; })
        .finally(() => {
            if (token !== artLoadToken) return;
            artLoading = false;
            _artSetSentinelBusy(false);
        });
}

function _artItemOf(el) {
    const card = el && el.closest('.art-card');
    if (!card) return null;
    const id = Number(card.dataset.artId);
    return artItems.find(i => i.id === id) || null;
}

/** A file that was never indexed, opened from a conversation's file card. */
function _artItemFromMeta(meta) {
    const name = meta.file_name || meta.name || (meta.abs_path || '').split('/').pop();
    const kind = meta.kind || wsKindOf(name);
    return {
        id: null,
        file_name: name,
        abs_path: meta.abs_path || '',
        rel_path: meta.rel_path || meta.path || name,
        kind: kind,
        size: meta.size || 0,
        raw_url: meta.raw_url || '',
        preview_url: meta.preview_url || '',
        previewable: meta.previewable !== false,
        exists: true,
        can_jump: false,
        origin: meta.origin || null,
    };
}

async function _artApplyPendingFocus() {
    const meta = artPendingFocus;
    if (!meta) return;
    artPendingFocus = null;
    const path = meta.abs_path || '';
    let item = path ? artItems.find(i => i.abs_path === path) : null;
    if (!item && path) {
        // Indexed but outside the current filters or page: look it up across
        // every Agent so the file still opens.
        try {
            const data = await _artFetch({ scope: 'all', path: path, limit: 1 });
            item = (data.items || [])[0] || null;
        } catch (_) { /* fall through to the bare file */ }
    }
    artSelect(item || _artItemFromMeta(meta), { reveal: true });
}

// =====================================================================
// Timeline rendering
// =====================================================================
function _artLocale() {
    if (currentLang === 'en') return 'en-US';
    return currentLang === 'zh-Hant' ? 'zh-TW' : 'zh-CN';
}

function _artDayStart(ts) {
    const d = new Date(ts * 1000);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function _artDayLabel(ts) {
    const d = new Date(ts * 1000);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const diff = Math.round((today - _artDayStart(ts)) / 86400000);
    const opts = d.getFullYear() === now.getFullYear()
        ? { month: 'long', day: 'numeric', weekday: 'short' }
        : { year: 'numeric', month: 'long', day: 'numeric' };
    const date = d.toLocaleDateString(_artLocale(), opts);
    if (diff === 0) return { primary: t('artifacts_today'), secondary: date };
    if (diff === 1) return { primary: t('artifacts_yesterday'), secondary: date };
    return { primary: date, secondary: '' };
}

function _artTime(ts) {
    return new Date(ts * 1000).toLocaleTimeString(_artLocale(), { hour: '2-digit', minute: '2-digit', hour12: false });
}

function _artDateTime(ts) {
    return new Date(ts * 1000).toLocaleString(_artLocale(), {
        year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
    });
}

function _artExt(name) {
    const i = (name || '').lastIndexOf('.');
    return i > 0 ? name.slice(i + 1).toUpperCase().slice(0, 5) : '';
}

function _artFiltered() {
    return !!(artKind || artQuery);
}

function _artRenderSkeleton() {
    const list = document.getElementById('art-list');
    if (!list) return;
    // Repainting the same skeleton on every keystroke of a search would blink.
    if (list.querySelector('.art-day') && !list.querySelector('.art-skel')) {
        list.classList.add('is-refreshing');
        return;
    }
    const cards = Array.from({ length: 8 }, () =>
        `<div class="art-skel-card"><div class="art-skel-thumb"></div><div class="art-skel-line"></div><div class="art-skel-line short"></div></div>`
    ).join('');
    list.innerHTML = `<div class="art-skel"><div class="art-skel-day"></div><div class="art-grid">${cards}</div></div>`;
}

function _artRenderAll() {
    const list = document.getElementById('art-list');
    if (!list || !artInited) return;
    list.classList.remove('is-refreshing');
    if (artLoadFailed) {
        list.innerHTML = `<div class="art-state">
            <i class="fas fa-triangle-exclamation art-state-icon"></i>
            <div class="art-state-title">${escapeHtml(t('artifacts_load_failed'))}</div>
            <button class="art-link-btn" data-art-retry>${escapeHtml(t('artifacts_retry'))}</button>
        </div>`;
        return;
    }
    if (!artItems.length) {
        list.innerHTML = _artFiltered() ? _artNoMatchHTML() : _artEmptyHTML();
        return;
    }
    list.innerHTML = '';
    _artAppendCards(artItems);
    if (artSelected && artSelected.id != null) _artMarkSelected(artSelected.id);
}

function _artEmptyHTML() {
    return `<div class="art-empty">
        <div class="art-empty-art" aria-hidden="true">
            <span class="art-empty-tile art-empty-tile-1"><i class="fas fa-file-lines"></i></span>
            <span class="art-empty-tile art-empty-tile-2"><i class="fas fa-image"></i></span>
            <span class="art-empty-tile art-empty-tile-3"><i class="fas fa-code"></i></span>
        </div>
        <div class="art-empty-title">${escapeHtml(t('artifacts_empty_title'))}</div>
        <div class="art-empty-desc">${escapeHtml(t('artifacts_empty_desc'))}</div>
        <button class="art-empty-btn" data-art-start>
            <i class="fas fa-message"></i><span>${escapeHtml(t('artifacts_empty_action'))}</span>
        </button>
    </div>`;
}

function _artNoMatchHTML() {
    return `<div class="art-state">
        <i class="fas fa-magnifying-glass art-state-icon"></i>
        <div class="art-state-title">${escapeHtml(t('artifacts_no_match'))}</div>
        <button class="art-link-btn" data-art-reset>${escapeHtml(t('artifacts_clear_filters'))}</button>
    </div>`;
}

/** Append cards to the timeline, continuing the last day's grid if it matches. */
function _artAppendCards(items) {
    const list = document.getElementById('art-list');
    if (!list || !items.length) return;
    let section = list.lastElementChild && list.lastElementChild.classList.contains('art-day')
        ? list.lastElementChild : null;
    items.forEach(item => {
        const day = String(_artDayStart(item.updated_at));
        if (!section || section.dataset.day !== day) {
            const label = _artDayLabel(item.updated_at);
            section = document.createElement('section');
            section.className = 'art-day';
            section.dataset.day = day;
            section.innerHTML = `<div class="art-day-label">
                <span class="art-day-primary">${escapeHtml(label.primary)}</span>
                ${label.secondary ? `<span class="art-day-secondary">${escapeHtml(label.secondary)}</span>` : ''}
            </div><div class="art-grid"></div>`;
            list.appendChild(section);
        }
        const grid = section.querySelector('.art-grid');
        grid.insertAdjacentHTML('beforeend', _artCardHTML(item));
        const card = grid.lastElementChild;
        artThumbObserver.observe(card);
    });
    _artSyncThumbWidth();
}

function _artCardHTML(item) {
    const name = item.file_name || '';
    const kind = item.kind || 'file';
    const ext = _artExt(name);
    const session = item.session_id
        ? escapeHtml(item.session_title || t('artifacts_untitled'))
        : '';
    const face = _artMultiAgent() && artScope === 'all'
        ? `<span class="art-card-face">${agentAvatarHTML(findAgent(item.agent_id), 16)}</span>` : '';
    const tools = [
        item.can_jump ? `<button class="art-tool" data-art-act="jump" data-tip-float data-tooltip="${escapeHtml(t('artifacts_jump'))}" data-tooltip-pos="bottom"><i class="fas fa-message"></i></button>` : '',
        item.exists ? `<button class="art-tool" data-art-act="download" data-tip-float data-tooltip="${escapeHtml(t('ws_download'))}" data-tooltip-pos="bottom"><i class="fas fa-download"></i></button>` : '',
    ].join('');
    return `<div class="art-card${item.exists ? '' : ' is-missing'}" data-art-id="${item.id}" tabindex="0">
        <div class="art-thumb art-kind-${escapeHtml(kind)}">
            <div class="art-ph">
                <i class="fas ${item.exists ? (WS_KIND_ICONS[kind] || WS_KIND_ICONS.file) : 'fa-file-circle-xmark'}"></i>
                ${item.exists ? (ext ? `<span class="art-ph-ext">${escapeHtml(ext)}</span>` : '')
                    : `<span class="art-ph-ext">${escapeHtml(t('artifacts_missing'))}</span>`}
            </div>
            ${kind === 'video' && item.exists ? '<span class="art-play"><i class="fas fa-play"></i></span>' : ''}
            ${tools ? `<div class="art-tools">${tools}</div>` : ''}
        </div>
        <div class="art-card-name" title="${escapeHtml(item.rel_path || name)}">
            <i class="${wsIconClass(kind)}"></i><span>${escapeHtml(name)}</span>
        </div>
        <div class="art-card-meta">
            <span class="art-card-time">${escapeHtml(_artTime(item.updated_at))}</span>
            ${session ? `<span class="art-card-dot"></span>${face}<span class="art-card-session">${session}</span>` : ''}
        </div>
    </div>`;
}

/** Draw the thumbnail once the card is near the viewport. */
function _artMountThumb(card) {
    const item = _artItemOf(card);
    const thumb = card.querySelector('.art-thumb');
    if (!item || !thumb || !item.exists) return;
    const done = () => thumb.classList.add('is-loaded');
    // Media sits over the placeholder, which shows through until it has loaded.
    const place = (node) => thumb.querySelector('.art-ph').after(node);

    if (item.kind === 'image') {
        const img = document.createElement('img');
        img.className = 'art-media';
        img.alt = '';
        img.decoding = 'async';
        img.onload = done;
        img.onerror = () => img.remove();
        img.src = item.raw_url;
        place(img);
    } else if (item.kind === 'video') {
        const video = document.createElement('video');
        video.className = 'art-media';
        video.muted = true;
        video.playsInline = true;
        video.preload = 'metadata';
        video.onloadeddata = done;
        video.onerror = () => video.remove();
        video.src = `${item.raw_url}#t=0.1`;
        place(video);
    } else if (item.kind === 'html' && item.preview_url) {
        const frame = document.createElement('div');
        frame.className = 'art-frame';
        const iframe = document.createElement('iframe');
        // Opaque origin, and nothing that could act on its own: the thumbnail
        // only has to paint.
        iframe.setAttribute('sandbox', 'allow-scripts');
        iframe.setAttribute('scrolling', 'no');
        iframe.setAttribute('aria-hidden', 'true');
        iframe.tabIndex = -1;
        iframe.onload = done;
        iframe.src = item.preview_url;
        frame.appendChild(iframe);
        place(frame);
    } else if (ART_TEXT_KINDS.has(item.kind) && item.preview_url && item.size <= ART_TEXT_THUMB_MAX) {
        fetch(item.preview_url)
            .then(r => (r.ok ? r.text() : Promise.reject()))
            .then(text => {
                const head = text.slice(0, ART_TEXT_THUMB_CHARS);
                if (!head.trim()) return;
                const paper = document.createElement('div');
                paper.className = 'art-paper';
                if (item.kind === 'markdown') {
                    paper.innerHTML = `<div class="art-paper-page msg-content">${renderMarkdown(head)}</div>`;
                    // A thumbnail is a picture of the text; nothing in it should load or link.
                    paper.querySelectorAll('img, video, audio, iframe').forEach(n => n.remove());
                } else {
                    paper.innerHTML = `<pre class="art-paper-page art-paper-mono">${escapeHtml(head.split('\n').slice(0, 60).join('\n'))}</pre>`;
                }
                place(paper);
                done();
            })
            .catch(() => {});
    }
}

function _artSetSentinelBusy(busy) {
    const s = document.getElementById('art-sentinel');
    if (s) s.innerHTML = busy ? '<i class="fas fa-circle-notch fa-spin"></i>' : '';
}

function _artMarkSelected(id) {
    document.querySelectorAll('#art-list .art-card.is-selected').forEach(c => c.classList.remove('is-selected'));
    if (id == null) return null;
    const card = document.querySelector(`#art-list .art-card[data-art-id="${CSS.escape(String(id))}"]`);
    if (card) card.classList.add('is-selected');
    return card;
}

// =====================================================================
// Preview pane
// =====================================================================
function artSelect(item, opts) {
    if (!item) return;
    opts = opts || {};
    const sameFile = artSelected && artSelected.id === item.id && item.id != null
        && !document.getElementById('art-preview').classList.contains('hidden');
    artSelected = item;
    const card = _artMarkSelected(item.id);
    if (card && opts.reveal) card.scrollIntoView({ block: 'center', behavior: 'smooth' });
    else if (card) card.scrollIntoView({ block: 'nearest' });
    _artOpenPane();
    _artRenderPreviewChrome(item);
    if (!sameFile) _artRenderPreviewBody(item);
}

function _artOpenPane() {
    const pane = document.getElementById('art-preview');
    const shell = pane.parentElement;
    pane.classList.remove('hidden');
    pane.setAttribute('aria-hidden', 'false');
    shell.classList.add('has-preview');
    requestAnimationFrame(_artSyncThumbWidth);
}

function artClosePreview() {
    const pane = document.getElementById('art-preview');
    if (!pane) return;
    artPreviewToken++;
    pane.classList.add('hidden');
    pane.setAttribute('aria-hidden', 'true');
    pane.parentElement.classList.remove('has-preview');
    document.getElementById('art-preview-body').innerHTML = '';
    _artMarkSelected(null);
    artSelected = null;
    requestAnimationFrame(_artSyncThumbWidth);
}

function _artRenderPreviewChrome(item) {
    document.getElementById('art-preview-name').textContent = item.file_name || '';
    const pathEl = document.getElementById('art-preview-path');
    pathEl.textContent = item.rel_path || '';
    pathEl.title = item.abs_path || '';

    const jump = document.getElementById('art-btn-jump');
    jump.classList.toggle('hidden', item.id == null);
    jump.classList.toggle('is-disabled', !item.can_jump);
    jump.setAttribute('data-tooltip', t(item.can_jump ? 'artifacts_jump' : 'artifacts_jump_unavailable'));
    // A file opened from a conversation but not in the index (removed earlier,
    // or never picked up) can be put back from here.
    document.getElementById('art-btn-add').classList.toggle('hidden',
        !(item.id == null && item.exists && item.origin && item.origin.session_id));
    document.getElementById('art-btn-external').classList.toggle('hidden', !item.exists);
    document.getElementById('art-btn-reveal').classList.toggle('hidden', !item.exists || !wsCanReveal());
    document.getElementById('art-btn-download').classList.toggle('hidden', !item.exists);
    document.getElementById('art-btn-remove').classList.toggle('hidden', item.id == null);

    const parts = [];
    if (item.agent_id && _artMultiAgent()) {
        const agent = findAgent(item.agent_id);
        parts.push(`<span class="art-meta-item">${agentAvatarHTML(agent, 16)}<span>${escapeHtml((agent && agent.name) || item.agent_name || item.agent_id)}</span></span>`);
    }
    if (item.session_id) {
        const title = escapeHtml(item.session_title || t('artifacts_untitled'));
        parts.push(item.can_jump
            ? `<button class="art-meta-item art-meta-link" onclick="artJumpToSelected()"><i class="fas fa-message"></i><span>${title}</span></button>`
            : `<span class="art-meta-item"><i class="fas fa-message"></i><span>${title}</span></span>`);
    }
    if (item.updated_at) parts.push(`<span class="art-meta-item">${escapeHtml(_artDateTime(item.updated_at))}</span>`);
    if (item.size) parts.push(`<span class="art-meta-item">${escapeHtml(wsFormatSize(item.size))}</span>`);
    const meta = document.getElementById('art-preview-meta');
    meta.innerHTML = parts.join('');
    meta.classList.toggle('hidden', !parts.length);
}

function _artRenderPreviewBody(item) {
    const token = ++artPreviewToken;
    const body = document.getElementById('art-preview-body');
    body.querySelectorAll('video, audio').forEach(m => { try { m.pause(); } catch (_) {} });
    body.innerHTML = '';
    // Each file renders into a fresh stage, so a slow text fetch for the
    // previous selection lands in a detached node instead of over this one.
    const stage = document.createElement('div');
    stage.className = 'art-preview-stage';
    body.appendChild(stage);
    if (!item.exists) {
        stage.innerHTML = `<div class="workspace-empty">
            <i class="fas fa-file-circle-xmark"></i>
            <span>${escapeHtml(t('artifacts_missing'))}</span>
        </div>`;
        return;
    }
    Promise.resolve(wsRenderPreview(item, stage)).catch(() => {
        if (token === artPreviewToken) {
            stage.innerHTML = `<div class="workspace-empty"><i class="fas fa-triangle-exclamation"></i><span>${escapeHtml(t('ws_preview_failed'))}</span></div>`;
        }
    });
}

function artOpenSelectedExternally() {
    const item = artSelected;
    if (item && item.exists) window.open(item.preview_url || item.raw_url, '_blank', 'noopener');
}

function artRevealSelected() {
    const item = artSelected;
    if (!item || !item.exists || !item.abs_path) return;
    wsRevealPath(item.abs_path).catch(err => _artToast(err.message || t('ws_reveal_failed')));
}

function artDownloadSelected() {
    _artRunAction('download', artSelected);
}

function artRemoveSelected() {
    _artRunAction('remove', artSelected);
}

function artJumpToSelected() {
    _artRunAction('jump', artSelected);
}

function artAddSelected() {
    _artAdd(artSelected);
}

function _artRunAction(action, item) {
    if (!item) return;
    if (action === 'download') {
        if (item.exists && item.raw_url) wsTriggerDownload(item.raw_url, item.file_name);
    } else if (action === 'jump') {
        if (item.can_jump) artJumpToSource(item);
    } else if (action === 'remove') {
        _artConfirmRemove(item);
    }
}

function _artConfirmRemove(item) {
    if (item.id == null) return;
    showConfirmDialog({
        title: t('artifacts_remove_title'),
        message: t('artifacts_remove_confirm').replace('{name}', item.file_name || ''),
        okText: t('artifacts_remove_ok'),
        cancelText: t('channels_cancel'),
        onConfirm: () => _artRemove(item),
    });
}

function _artAdd(item) {
    if (!item || item.id != null || !item.origin) return;
    const btn = document.getElementById('art-btn-add');
    btn.classList.add('ws-btn-busy');
    fetch('/api/artifacts/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            path: item.abs_path,
            session_id: item.origin.session_id,
            agent_id: item.origin.agent_id || '',
            turn_seq: item.origin.turn_seq,
        }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success' || !data.item) throw new Error(data.message || 'Request failed');
            _artToast(t('artifacts_added'));
            // The file lands at the top of the timeline; reload so it shows up
            // where it belongs under the current filters, and keep it open.
            artPendingFocus = { abs_path: data.item.abs_path };
            artSelected = data.item;
            _artRenderPreviewChrome(data.item);
            artReload();
        })
        .catch(err => _artToast(err.message || t('artifacts_load_failed')))
        .finally(() => btn.classList.remove('ws-btn-busy'));
}

function _artRemove(item) {
    if (item.id == null) return;
    fetch('/api/artifacts/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: item.id, agent_id: item.agent_id }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') throw new Error(data.message || 'Request failed');
            const index = artItems.findIndex(i => i.id === item.id);
            const next = artItems[index + 1] || artItems[index - 1] || null;
            artItems = artItems.filter(i => i.id !== item.id);
            const card = document.querySelector(`#art-list .art-card[data-art-id="${CSS.escape(String(item.id))}"]`);
            if (card) {
                const section = card.closest('.art-day');
                card.remove();
                if (section && !section.querySelector('.art-card')) section.remove();
            }
            if (!artItems.length) _artRenderAll();
            if (artSelected && artSelected.id === item.id) {
                if (next) artSelect(next);
                else artClosePreview();
            }
            _artToast(t('artifacts_removed'));
        })
        .catch(err => _artToast(err.message || t('artifacts_load_failed')));
}

function _artToast(text) {
    let el = document.getElementById('art-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'art-toast';
        el.className = 'art-toast';
        document.getElementById('view-artifacts').appendChild(el);
    }
    el.textContent = text;
    el.classList.add('show');
    clearTimeout(artToastTimer);
    artToastTimer = setTimeout(() => el.classList.remove('show'), 2400);
}

function _artOnKey(e) {
    if (currentView !== 'artifacts' || !artSelected) return;
    const tag = (e.target && e.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target && e.target.isContentEditable)) return;
    const confirmOverlay = document.getElementById('confirm-dialog-overlay');
    if (confirmOverlay && !confirmOverlay.classList.contains('hidden')) return;
    if (e.key === 'Escape') {
        artClosePreview();
        return;
    }
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const index = artItems.findIndex(i => i.id === artSelected.id);
    if (index === -1) return;
    const next = artItems[index + (e.key === 'ArrowRight' ? 1 : -1)];
    if (!next) return;
    e.preventDefault();
    artSelect(next);
}

// =====================================================================
// Back to the conversation
// =====================================================================
/**
 * Open the conversation that last wrote the file and glide to the turn: its
 * file card when the turn shows one, the question that started it otherwise.
 * The conversation may belong to another Agent, and the turn may sit in a
 * history page that isn't loaded yet.
 */
async function artJumpToSource(item) {
    if (!item || !item.can_jump) return;
    switchSession(item.session_id, item.agent_id);
    if (sessionId !== item.session_id) return;  // an unsaved edit held the switch
    await _timelineWaitHistoryIdle();
    if (sessionId !== item.session_id) return;

    let target = _artFindInChat(item);
    if (!target && item.turn_seq != null && !_timelineFindBubble(item.turn_seq) && historyHasMore) {
        await loadHistory(historyPage + 1, item.turn_seq);
        if (sessionId !== item.session_id) return;
        target = _artFindInChat(item);
    }
    if (target) {
        // Land the file a third of the way down, so the reply around it shows.
        _timelineGlideTo(target, Math.round(messagesDiv.clientHeight * 0.3));
    } else if (item.turn_seq != null) {
        target = _timelineFindBubble(item.turn_seq);
        if (target) _timelineGlideTo(target);
    }
}

/** The element in the turn's reply that shows this file, if any. */
function _artFindInChat(item) {
    if (item.turn_seq == null) return null;
    const start = _timelineFindBubble(item.turn_seq);
    if (!start) return null;
    const path = item.abs_path || '';
    for (let el = start.nextElementSibling; el && !el.classList.contains('user-message-group'); el = el.nextElementSibling) {
        const list = el.querySelector(`.file-card-list[data-artifact-path="${CSS.escape(path)}"]`);
        if (list) return list.querySelector('.file-card') || list;
        const media = Array.from(el.querySelectorAll('img[src], video[src], audio[src]'))
            .find(m => _artSrcPath(m.getAttribute('src')) === path);
        if (media) return media;
    }
    return null;
}

function _artSrcPath(src) {
    if (!src || src.indexOf('path=') === -1) return '';
    try {
        return new URL(src, location.origin).searchParams.get('path') || '';
    } catch (_) {
        return '';
    }
}
