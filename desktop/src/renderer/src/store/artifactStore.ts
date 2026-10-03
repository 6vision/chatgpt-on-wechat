import { create } from 'zustand'
import apiClient from '../api/client'
import { t } from '../i18n'
import { kindOf } from '../lib/fileKind'
import { askConfirm } from './confirmStore'
import { isMultiAgent } from './agentStore'
import { useSessionStore, sessionOwner } from './sessionStore'
import { useTimelineStore } from './timelineStore'
import type { ArtifactListItem, ArtifactOrigin, FileKind } from '../types'

const ART_PAGE_SIZE = 48
// Matches TITLE_MAX in api/artifacts.py.
export const ART_TITLE_MAX = 120
const SCOPE_KEY = 'cow_artifacts_scope'
const NOTICE_MS = 2400

export type KindFilter = '' | 'web' | 'doc' | 'image' | 'media' | 'other'

/**
 * What the view shows: a row of the index, or (id null) a file opened from a
 * conversation that the index doesn't hold, which can be put back from there.
 */
export type ArtifactShown = Omit<ArtifactListItem, 'id'> & { id: number | null; origin?: ArtifactOrigin | null }

/** What a file card in the conversation knows about the file it shows. */
interface ArtifactFocus {
  abs_path: string
  file_name?: string
  rel_path?: string
  kind?: FileKind
  size?: number
  raw_url?: string
  preview_url?: string
  previewable?: boolean
  origin?: ArtifactOrigin | null
}

interface ArtifactState {
  kind: KindFilter
  query: string
  /** 'all' or an Agent id. */
  scope: string
  items: ArtifactListItem[]
  hasMore: boolean
  /** A first page is on its way: a skeleton when nothing is shown yet, else the list dims. */
  loading: boolean
  loadingMore: boolean
  failed: boolean
  adding: boolean
  selected: ArtifactShown | null
  /** Bumped when the selection should be brought to the middle of the view. */
  revealSeq: number
  notice: { text: string; shown: boolean } | null

  setKind: (kind: KindFilter) => void
  setQuery: (query: string) => void
  setScope: (scope: string) => void
  resetFilters: () => void
  /** Drop a stored scope the roster no longer offers. Returns true when it changed. */
  fixScope: (multiAgent: boolean, agentIds: string[]) => boolean
  reload: () => Promise<void>
  loadMore: () => Promise<void>
  select: (item: ArtifactShown, reveal?: boolean) => void
  closePreview: () => void
  /** Open the view on this file once it next loads. */
  focus: (meta: ArtifactFocus) => void
  togglePin: (item: ArtifactShown) => Promise<void>
  rename: (item: ArtifactShown, raw: string) => Promise<void>
  remove: (item: ArtifactShown) => Promise<void>
  add: (item: ArtifactShown) => Promise<void>
  flash: (text: string) => void
}

/** What the view calls the file: the name the user gave it, else its file name. */
export function artName(item: Pick<ArtifactShown, 'title' | 'file_name'> | null | undefined): string {
  return (item && (item.title || item.file_name)) || ''
}

/** The server's order: pinned first (latest pin on top), then newest first. */
function sortItems(items: ArtifactListItem[]): ArtifactListItem[] {
  return [...items].sort(
    (a, b) => (b.pinned_at || 0) - (a.pinned_at || 0) || b.updated_at - a.updated_at || b.id - a.id
  )
}

function looseItem(meta: ArtifactFocus): ArtifactShown {
  const name = meta.file_name || meta.abs_path.split(/[\\/]/).pop() || ''
  return {
    id: null,
    title: '',
    file_name: name,
    abs_path: meta.abs_path,
    rel_path: meta.rel_path || name,
    kind: meta.kind || kindOf(name),
    size: meta.size || 0,
    raw_url: meta.raw_url || '',
    preview_url: meta.preview_url || '',
    previewable: meta.previewable !== false,
    exists: true,
    agent_id: meta.origin?.agent_id || '',
    agent_name: '',
    session_id: '',
    session_title: '',
    turn_seq: null,
    can_jump: false,
    source: '',
    created_at: 0,
    updated_at: 0,
    pinned_at: 0,
    origin: meta.origin || null,
  }
}

function errorText(e: unknown, fallback: string): string {
  return (e instanceof Error && e.message) || fallback
}

function ensureOk<T extends { status: string; message?: string }>(res: T): T {
  if (res.status !== 'success') throw new Error(res.message || t('artifacts_load_failed'))
  return res
}

let loadToken = 0
let pendingFocus: ArtifactFocus | null = null
let noticeTimer: ReturnType<typeof setTimeout> | undefined
// Ids with a pin request in flight, so a double click doesn't undo itself.
const pinBusy = new Set<number>()

export const useArtifactStore = create<ArtifactState>((set, get) => {
  const list = (params: { offset?: number; scope?: string; path?: string; limit?: number }) => {
    const s = get()
    return apiClient
      .listArtifacts({
        scope: params.scope || s.scope,
        kind: params.path ? '' : s.kind,
        q: params.path ? '' : s.query,
        path: params.path,
        offset: params.offset,
        limit: params.limit || ART_PAGE_SIZE,
      })
      .then(ensureOk)
  }

  /** Show `title` wherever this row appears: its list entry and the preview. */
  const applyTitle = (id: number, title: string) =>
    set((s) => ({
      items: s.items.map((i) => (i.id === id ? { ...i, title } : i)),
      selected: s.selected?.id === id ? { ...s.selected, title } : s.selected,
    }))

  const applyPendingFocus = async () => {
    const meta = pendingFocus
    if (!meta) return
    pendingFocus = null
    const path = meta.abs_path
    let item: ArtifactShown | undefined = path ? get().items.find((i) => i.abs_path === path) : undefined
    if (!item && path) {
      // Indexed but outside the current filters or page: look it up across
      // every Agent so the file still opens.
      try {
        item = (await list({ scope: 'all', path, limit: 1 })).items?.[0]
      } catch {
        /* fall through to the bare file */
      }
    }
    get().select(item || looseItem(meta), true)
  }

  return {
    kind: '',
    query: '',
    scope: localStorage.getItem(SCOPE_KEY) || 'all',
    items: [],
    hasMore: false,
    loading: false,
    loadingMore: false,
    failed: false,
    adding: false,
    selected: null,
    revealSeq: 0,
    notice: null,

    setKind: (kind) => {
      if (kind === get().kind) return
      set({ kind })
      void get().reload()
    },

    setQuery: (query) => {
      if (query === get().query) return
      set({ query })
      void get().reload()
    },

    setScope: (scope) => {
      if (scope === get().scope) return
      try {
        localStorage.setItem(SCOPE_KEY, scope)
      } catch {
        /* private mode */
      }
      set({ scope })
      void get().reload()
    },

    resetFilters: () => {
      set({ kind: '', query: '' })
      void get().reload()
    },

    fixScope: (multiAgent, agentIds) => {
      const { scope } = get()
      // An empty roster hasn't loaded yet; keep the stored scope until it has.
      if (scope === 'all' || !agentIds.length || (multiAgent && agentIds.includes(scope))) return false
      set({ scope: 'all' })
      return true
    },

    reload: async () => {
      const token = ++loadToken
      // What is shown stays up, dimmed, until the answer lands: repainting a
      // skeleton on every keystroke of a search would blink.
      set({ loading: true, loadingMore: false, failed: false, hasMore: false })
      try {
        const res = await list({ offset: 0 })
        if (token !== loadToken) return
        set({ items: res.items || [], hasMore: !!res.has_more, loading: false })
        await applyPendingFocus()
      } catch {
        if (token === loadToken) set({ items: [], failed: true, loading: false })
      }
    },

    loadMore: async () => {
      const s = get()
      if (s.loading || s.loadingMore || !s.hasMore || s.failed) return
      const token = loadToken
      set({ loadingMore: true })
      try {
        const res = await list({ offset: s.items.length })
        if (token !== loadToken) return
        set((cur) => {
          const known = new Set(cur.items.map((i) => i.id))
          const fresh = (res.items || []).filter((i) => !known.has(i.id))
          return { items: [...cur.items, ...fresh], hasMore: !!res.has_more, loadingMore: false }
        })
      } catch {
        if (token === loadToken) set({ hasMore: false, loadingMore: false })
      }
    },

    select: (item, reveal) =>
      set((s) => ({ selected: item, revealSeq: reveal ? s.revealSeq + 1 : s.revealSeq })),

    closePreview: () => set({ selected: null }),

    focus: (meta) => {
      pendingFocus = meta
    },

    togglePin: async (item) => {
      const id = item.id
      if (id == null || pinBusy.has(id)) return
      const pinned = !item.pinned_at
      pinBusy.add(id)
      try {
        const res = ensureOk(await apiClient.pinArtifact(id, item.agent_id, pinned))
        const pinnedAt = res.pinned_at || 0
        const s = get()
        const selected = s.selected?.id === id ? { ...s.selected, pinned_at: pinnedAt } : s.selected
        if (!s.items.some((i) => i.id === id)) {
          // Opened from a conversation without being in the loaded list:
          // reload so it lands in the pinned section if the filters allow.
          pendingFocus = { abs_path: item.abs_path }
          set({ selected })
          void get().reload()
        } else {
          let items = sortItems(s.items.map((i) => (i.id === id ? { ...i, pinned_at: pinnedAt } : i)))
          // Unpinned past the last loaded card: its place is on a page that
          // has not been fetched yet, which will bring it back.
          if (!pinned && s.hasMore && items[items.length - 1]?.id === id) items = items.slice(0, -1)
          set({ items, selected })
        }
        get().flash(t(pinned ? 'artifacts_pinned' : 'artifacts_unpinned'))
      } catch (e) {
        get().flash(errorText(e, t('artifacts_load_failed')))
      } finally {
        pinBusy.delete(id)
      }
    },

    rename: async (item, raw) => {
      const id = item.id
      if (id == null) return
      // Same normalisation as the server, so an unchanged name sends nothing.
      let title = raw.split(/\s+/).filter(Boolean).join(' ').slice(0, ART_TITLE_MAX)
      if (title === item.file_name) title = ''
      const before = item.title || ''
      if (title === before) return
      applyTitle(id, title)
      try {
        const res = ensureOk(await apiClient.renameArtifact(id, item.agent_id, title))
        applyTitle(id, res.title || '')
      } catch (e) {
        applyTitle(id, before)
        get().flash(errorText(e, t('artifacts_rename_failed')))
      }
    },

    remove: async (item) => {
      const id = item.id
      if (id == null) return
      const ok = await askConfirm({
        titleKey: 'artifacts_remove_title',
        msgKey: 'artifacts_remove_confirm',
        okKey: 'artifacts_remove_ok',
        vars: { name: artName(item) },
      })
      if (!ok) return
      try {
        ensureOk(await apiClient.deleteArtifact(id, item.agent_id))
        const s = get()
        const index = s.items.findIndex((i) => i.id === id)
        const next = index === -1 ? null : s.items[index + 1] || s.items[index - 1] || null
        set({
          items: s.items.filter((i) => i.id !== id),
          selected: s.selected?.id === id ? next : s.selected,
        })
        get().flash(t('artifacts_removed'))
      } catch (e) {
        get().flash(errorText(e, t('artifacts_load_failed')))
      }
    },

    add: async (item) => {
      const origin = item.origin
      if (item.id != null || !origin?.session_id || get().adding) return
      set({ adding: true })
      try {
        const res = ensureOk(
          await apiClient.addArtifact({
            path: item.abs_path,
            session_id: origin.session_id,
            agent_id: origin.agent_id || '',
            turn_seq: origin.turn_seq,
          })
        )
        if (!res.item) throw new Error(res.message || t('artifacts_load_failed'))
        get().flash(t('artifacts_added'))
        // The file lands at the top of the timeline; reload so it shows up
        // where it belongs under the current filters, and keep it open.
        pendingFocus = { abs_path: res.item.abs_path }
        set({ selected: res.item })
        void get().reload()
      } catch (e) {
        get().flash(errorText(e, t('artifacts_load_failed')))
      } finally {
        set({ adding: false })
      }
    },

    flash: (text) => {
      clearTimeout(noticeTimer)
      set({ notice: { text, shown: true } })
      // The text stays while it fades out.
      noticeTimer = setTimeout(() => set((s) => ({ notice: s.notice && { ...s.notice, shown: false } })), NOTICE_MS)
    },
  }
})

/**
 * Have the view open on a file a conversation produced, the next time it
 * loads; the caller navigates there. An origin without an Agent belongs to the
 * session's owner.
 */
export function focusProduced(file: ArtifactFocus & { origin: ArtifactOrigin }) {
  const { origin } = file
  useArtifactStore.getState().focus({
    ...file,
    origin: { ...origin, agent_id: origin.agent_id || sessionOwner(origin.session_id) },
  })
}

/**
 * Open the conversation that last wrote the file, and have the chat page glide
 * to the turn: its file card when the turn shows one, the question otherwise.
 * The conversation may belong to another Agent.
 *
 * @returns false when the switch was held (an unsaved edit the user kept).
 */
export async function openSource(item: ArtifactShown): Promise<boolean> {
  if (!item.can_jump || !item.session_id) return false
  const sessions = useSessionStore.getState()
  if (isMultiAgent() && item.agent_id) sessions.setOwner(item.session_id, item.agent_id)
  await sessions.setActive(item.session_id)
  if (useSessionStore.getState().activeId !== item.session_id) return false
  if (item.turn_seq != null) {
    useTimelineStore.getState().requestJump({ sessionId: item.session_id, seq: item.turn_seq, path: item.abs_path })
  }
  return true
}
