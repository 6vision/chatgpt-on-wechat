import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Pin, AlertTriangle, FileText, Image, Code, MessageSquare, Loader2 } from 'lucide-react'
import { t } from '../i18n'
import { SegTabs } from './skills/SegTabs'
import AgentScopeSelect from '../components/AgentScopeSelect'
import ArtifactCard, { NearContext, type NearWatcher } from './artifacts/ArtifactCard'
import ArtifactPreview from './artifacts/ArtifactPreview'
import { dayLabel, sectionKey } from './artifacts/format'
import { useAgentStore, selectMultiAgent } from '../store/agentStore'
import { useConfirmStore } from '../store/confirmStore'
import { useMenuStore } from '../store/menuStore'
import { useArtifactStore, openSource, type ArtifactShown, type KindFilter } from '../store/artifactStore'

const PREVIEW_WIDTH_KEY = 'cow_artifacts_preview_width'
const PREVIEW_MIN_WIDTH = 340
// Room the timeline keeps beside a widened preview pane.
const LIST_MIN_WIDTH = 360
// Below this the pane covers the timeline instead of sitting beside it.
const OVERLAY_BELOW = 760

const FILTERS: { value: KindFilter; key: string }[] = [
  { value: '', key: 'artifacts_filter_all' },
  { value: 'web', key: 'artifacts_filter_web' },
  { value: 'doc', key: 'artifacts_filter_doc' },
  { value: 'image', key: 'artifacts_filter_image' },
  { value: 'media', key: 'artifacts_filter_media' },
  { value: 'other', key: 'artifacts_filter_other' },
]

function readPaneWidth(): number | null {
  const w = parseInt(localStorage.getItem(PREVIEW_WIDTH_KEY) || '', 10)
  return w >= PREVIEW_MIN_WIDTH ? w : null
}

const Skeleton: React.FC = () => (
  <div>
    <div className="art-skel art-skel-day" />
    <div className="art-grid">
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i}>
          <div className="art-skel art-skel-thumb" />
          <div className="art-skel art-skel-line" />
          <div className="art-skel art-skel-line short" />
        </div>
      ))}
    </div>
  </div>
)

const StateNote: React.FC<{ icon: React.ReactNode; title: string; action: string; onAction: () => void }> = ({
  icon,
  title,
  action,
  onAction,
}) => (
  <div className="flex flex-col items-center gap-2.5 py-20 px-6 text-content-tertiary">
    <span className="opacity-60">{icon}</span>
    <div className="text-[13.5px] text-content-secondary">{title}</div>
    <button type="button" className="art-link-btn" onClick={onAction}>
      {action}
    </button>
  </div>
)

/**
 * Every file the conversations produced, newest first, grouped by day under a
 * section of the ones the user pinned. Selecting one previews it beside the
 * timeline, where it can be renamed (the view's name only; the file keeps its
 * own), and the preview can lead back to the turn that last wrote it.
 */
const ArtifactsPage: React.FC = () => {
  const navigate = useNavigate()
  const kind = useArtifactStore((s) => s.kind)
  const query = useArtifactStore((s) => s.query)
  const scope = useArtifactStore((s) => s.scope)
  const items = useArtifactStore((s) => s.items)
  const hasMore = useArtifactStore((s) => s.hasMore)
  const loading = useArtifactStore((s) => s.loading)
  const loadingMore = useArtifactStore((s) => s.loadingMore)
  const failed = useArtifactStore((s) => s.failed)
  const selected = useArtifactStore((s) => s.selected)
  const revealSeq = useArtifactStore((s) => s.revealSeq)
  const notice = useArtifactStore((s) => s.notice)
  const { setKind, setQuery, setScope, resetFilters, reload, select, togglePin } = useArtifactStore.getState()
  const multiAgent = useAgentStore(selectMultiAgent)
  const agentIds = useAgentStore((s) => s.agents.filter((a) => a.enabled).map((a) => a.id).join(','))

  const shellRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)

  // Every entry reloads, as the web console does: the conversations may have
  // produced files since. A stored scope the roster no longer offers falls
  // back to every Agent, here and whenever the roster changes.
  const enteredRef = useRef(false)
  useEffect(() => {
    const st = useArtifactStore.getState()
    const fixed = st.fixScope(multiAgent, agentIds ? agentIds.split(',') : [])
    if (!enteredRef.current) {
      enteredRef.current = true
      void st.reload()
    } else if (fixed) {
      void st.reload()
    }
  }, [multiAgent, agentIds])

  // The search box answers a short pause after typing, not every keystroke.
  const [draft, setDraft] = useState(query)
  useEffect(() => {
    const id = setTimeout(() => setQuery(draft.trim()), 220)
    return () => clearTimeout(id)
  }, [draft, setQuery])
  const clearFilters = () => {
    setDraft('')
    resetFilters()
  }

  // Cards draw their thumbnails only once they come near the viewport.
  const nearRef = useRef<{ io: IntersectionObserver | null; cbs: Map<Element, () => void> }>({ io: null, cbs: new Map() })
  const watchNear = useMemo<NearWatcher>(
    () => (el, onNear) => {
      const near = nearRef.current
      if (!near.io) {
        near.io = new IntersectionObserver(
          (entries) => {
            for (const entry of entries) {
              if (!entry.isIntersecting) continue
              const cb = near.cbs.get(entry.target)
              near.cbs.delete(entry.target)
              near.io?.unobserve(entry.target)
              cb?.()
            }
          },
          { root: scrollRef.current, rootMargin: '320px 0px' }
        )
      }
      near.cbs.set(el, onNear)
      near.io.observe(el)
      return () => {
        near.cbs.delete(el)
        near.io?.unobserve(el)
      }
    },
    []
  )
  useEffect(() => () => nearRef.current.io?.disconnect(), [])

  // The next page loads as the sentinel nears the viewport, and again right
  // after a page lands if the sentinel is still that close.
  const sentinelNear = useCallback(() => {
    const root = scrollRef.current
    const el = sentinelRef.current
    if (!root || !el) return false
    return el.getBoundingClientRect().top - root.getBoundingClientRect().bottom < 600
  }, [])
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((en) => en.isIntersecting)) void useArtifactStore.getState().loadMore()
      },
      { root: scrollRef.current, rootMargin: '600px 0px' }
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])
  useEffect(() => {
    if (hasMore && !loading && !loadingMore && sentinelNear()) void useArtifactStore.getState().loadMore()
  }, [items.length, hasMore, loading, loadingMore, sentinelNear])

  // Page and document thumbnails are a full-size render scaled down to the
  // card, so they need the card's width in px.
  useEffect(() => {
    const list = listRef.current
    if (!list) return
    const sync = () => {
      const thumb = list.querySelector<HTMLElement>('.art-thumb')
      if (thumb?.offsetWidth) list.style.setProperty('--art-tw', String(thumb.offsetWidth))
    }
    const ro = new ResizeObserver(sync)
    ro.observe(list)
    sync()
    return () => ro.disconnect()
  }, [])

  const [shellWidth, setShellWidth] = useState(0)
  useEffect(() => {
    const el = shellRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setShellWidth(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const overlay = shellWidth > 0 && shellWidth < OVERLAY_BELOW

  // A width the user dragged to; without one the stylesheet's default applies.
  const [paneWidth, setPaneWidth] = useState(readPaneWidth)
  const [resizing, setResizing] = useState(false)
  const paneRef = useRef<HTMLElement>(null)
  const maxPaneWidth = Math.max(PREVIEW_MIN_WIDTH, shellWidth - LIST_MIN_WIDTH)
  const startResize = (e: React.MouseEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = paneRef.current?.offsetWidth || PREVIEW_MIN_WIDTH
    const max = Math.max(PREVIEW_MIN_WIDTH, (shellRef.current?.clientWidth || 0) - LIST_MIN_WIDTH)
    let width = startWidth
    setResizing(true)
    const onMove = (ev: MouseEvent) => {
      width = Math.round(Math.min(max, Math.max(PREVIEW_MIN_WIDTH, startWidth + startX - ev.clientX)))
      setPaneWidth(width)
    }
    const onUp = () => {
      setResizing(false)
      localStorage.setItem(PREVIEW_WIDTH_KEY, String(width))
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  // Keep the selected card in view: nudged into view on an ordinary pick,
  // brought to the middle when the view was opened on it.
  const revealRef = useRef(revealSeq)
  const selectedId = selected?.id ?? null
  useEffect(() => {
    const reveal = revealSeq !== revealRef.current
    revealRef.current = revealSeq
    if (selectedId == null) return
    const frame = requestAnimationFrame(() => {
      const card = listRef.current?.querySelector(`[data-art-id="${selectedId}"]`)
      card?.scrollIntoView(reveal ? { block: 'center', behavior: 'smooth' } : { block: 'nearest' })
    })
    return () => cancelAnimationFrame(frame)
  }, [selectedId, revealSeq])

  // Esc closes the preview; the arrow keys step through the timeline.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = useArtifactStore.getState()
      if (!s.selected) return
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return
      if (useConfirmStore.getState().pending || useMenuStore.getState().editorOpen) return
      if (e.key === 'Escape') {
        s.closePreview()
        return
      }
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
      const index = s.items.findIndex((i) => i.id === s.selected?.id)
      const next = index === -1 ? undefined : s.items[index + (e.key === 'ArrowRight' ? 1 : -1)]
      if (!next) return
      e.preventDefault()
      s.select(next)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const jump = useCallback(
    async (item: ArtifactShown) => {
      if (await openSource(item)) navigate('/')
    },
    [navigate]
  )

  const sections = useMemo(() => {
    const out: { key: string; items: ArtifactShown[] }[] = []
    for (const item of items) {
      const key = sectionKey(item)
      const last = out[out.length - 1]
      if (last && last.key === key) last.items.push(item)
      else out.push({ key, items: [item] })
    }
    return out
  }, [items])

  const showOwner = multiAgent && scope === 'all'
  const filtered = !!(kind || query)

  let body: React.ReactNode
  if (failed) {
    body = (
      <StateNote
        icon={<AlertTriangle size={22} />}
        title={t('artifacts_load_failed')}
        action={t('artifacts_retry')}
        onAction={() => void reload()}
      />
    )
  } else if (!items.length) {
    if (loading) {
      body = <Skeleton />
    } else if (filtered) {
      body = (
        <StateNote
          icon={<Search size={22} />}
          title={t('artifacts_no_match')}
          action={t('artifacts_clear_filters')}
          onAction={clearFilters}
        />
      )
    } else {
      body = (
        <div className="flex flex-col items-center text-center px-6 pt-[72px] pb-12">
          <div className="art-empty-art" aria-hidden="true">
            <span className="art-empty-tile art-empty-tile-1">
              <FileText size={20} />
            </span>
            <span className="art-empty-tile art-empty-tile-2">
              <Image size={20} />
            </span>
            <span className="art-empty-tile art-empty-tile-3">
              <Code size={20} />
            </span>
          </div>
          <div className="text-[15px] font-semibold text-content">{t('artifacts_empty_title')}</div>
          <div className="max-w-[400px] mt-2 text-[13px] leading-[1.7] text-content-tertiary [text-wrap:balance]">
            {t('artifacts_empty_desc')}
          </div>
          <button
            type="button"
            onClick={() => navigate('/')}
            className="mt-[22px] inline-flex items-center gap-2 h-[34px] px-4 rounded-btn text-[13px] font-medium bg-accent text-accent-contrast hover:bg-accent-hover cursor-pointer transition-colors"
          >
            <MessageSquare size={13} />
            {t('artifacts_empty_action')}
          </button>
        </div>
      )
    }
  } else {
    body = sections.map((section) => {
      const label = section.key === 'pinned' ? null : dayLabel(section.items[0].updated_at)
      return (
        <section key={section.key} className={`art-day${section.key === 'pinned' ? ' art-pinned' : ''}`}>
          <div className="art-day-label">
            {label ? (
              <>
                <span className="art-day-primary">{label.primary}</span>
                {label.secondary && <span className="art-day-secondary">{label.secondary}</span>}
              </>
            ) : (
              <span className="art-day-primary">
                <Pin size={11} className="text-accent" />
                {t('artifacts_pinned_group')}
              </span>
            )}
          </div>
          <div className="art-grid">
            {section.items.map((item) => (
              <ArtifactCard
                key={item.id}
                item={item}
                selected={selectedId != null && item.id === selectedId}
                showOwner={showOwner}
                onSelect={select}
                onPin={togglePin}
                onJump={jump}
              />
            ))}
          </div>
        </section>
      )
    })
  }

  return (
    <div ref={shellRef} className={`art-shell${selected ? ' has-preview' : ''}`}>
      <div ref={scrollRef} className="art-scroll">
        <div className="art-inner">
          <div className="mb-5">
            <h2 className="text-xl font-bold text-content">{t('artifacts_title')}</h2>
            <p className="text-xs text-content-tertiary mt-1">{t('artifacts_desc')}</p>
          </div>

          <div className="art-toolbar">
            <div className="art-filters">
              <SegTabs
                tabs={FILTERS.map((f) => ({ value: f.value, label: t(f.key) }))}
                value={kind}
                onChange={setKind}
              />
            </div>
            <div className="art-toolbar-end">
              <AgentScopeSelect value={scope} onChange={setScope} allLabel={t('artifacts_scope_all')} />
              <label className="art-search">
                <Search size={13} className="shrink-0 text-content-tertiary" />
                <input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape' && draft) {
                      e.stopPropagation()
                      setDraft('')
                    }
                  }}
                  spellCheck={false}
                  autoComplete="off"
                  placeholder={t('artifacts_search')}
                />
              </label>
            </div>
          </div>

          <NearContext.Provider value={watchNear}>
            <div ref={listRef} className={`art-list${loading && items.length ? ' is-refreshing' : ''}`}>
              {body}
            </div>
          </NearContext.Provider>
          <div ref={sentinelRef} className="h-10 flex items-center justify-center text-content-tertiary">
            {loadingMore && <Loader2 size={15} className="animate-spin" />}
          </div>
        </div>
      </div>

      {selected && (
        <aside
          ref={paneRef}
          className={`art-preview${overlay ? ' is-overlay' : ''}`}
          style={!overlay && paneWidth ? { width: Math.min(paneWidth, maxPaneWidth) } : undefined}
        >
          {!overlay && (
            <div
              onMouseDown={startResize}
              className="absolute -left-[3px] top-0 bottom-0 w-1.5 cursor-col-resize z-20 hover:bg-accent-soft"
            />
          )}
          <ArtifactPreview item={selected} onJump={jump} resizing={resizing} />
        </aside>
      )}

      <div className={`art-toast${notice?.shown ? ' show' : ''}`} role="status">
        {notice?.text}
      </div>
    </div>
  )
}

export default ArtifactsPage
