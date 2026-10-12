import { create } from 'zustand'
import apiClient from '../api/client'
import { t } from '../i18n'
import { isEditable } from '../lib/fileKind'
import { askConfirm } from './confirmStore'
import type { Artifact, ArtifactOrigin, WorkspaceEntry } from '../types'

const WIDTH_KEY = 'cow_workspace_width'
export const WS_MIN_WIDTH = 300
export const WS_DEFAULT_WIDTH = 440

function readWidth(): number {
  const raw = parseInt(localStorage.getItem(WIDTH_KEY) || '', 10)
  return Number.isFinite(raw) && raw >= WS_MIN_WIDTH ? raw : WS_DEFAULT_WIDTH
}

export type WorkspaceTab = 'preview' | 'files'

/**
 * State of the preview panel's text editor.
 *
 * The text itself lives in the editor component, not here: keeping it in the
 * store would re-render the whole panel on every keystroke. `dirty` is the
 * mirror the unsaved-changes guard needs, and the component only writes it when
 * the flag actually flips.
 */
export interface EditState {
  /** The file being edited; compared on save to catch a switch mid-request. */
  file: WorkspaceEntry
  /** Text the editor seeds its text area from on mount. */
  loaded: string
  /**
   * Text to compare against to decide whether anything changed. Held apart from
   * `loaded`, which the editor overwrites with work in progress when it unmounts.
   */
  baseline: string
  /** mtime the edit started from; a stale one is rejected by the backend. */
  baseMtime: number
  dirty: boolean
  saving: boolean
  error: string | null
}

interface WorkspaceState {
  open: boolean
  tab: WorkspaceTab
  width: number
  /** File currently shown in the preview tab. */
  current: WorkspaceEntry | null
  previewError: string | null
  /**
   * Set once the user closes the panel by hand. While true we stop
   * auto-opening artifacts, so the panel never fights the user.
   */
  autoOpenSuppressed: boolean
  /** Artifacts produced by the turn that is currently streaming. */
  turnArtifacts: Artifact[]
  /** Directory the files tab should jump to, with a counter so repeated
   *  requests for the same folder still trigger a reload. */
  browseDir: string | null
  browseSeq: number
  /** Session whose working dir the panel is scoped to. Passed to workspace
   *  API calls so the tree/preview resolve against the session's project. */
  sessionId: string
  /** Null unless the preview tab is showing the editor. */
  edit: EditState | null
  /**
   * Why the editor refused to open (too large, wrong encoding, read failed).
   * Shown as a banner over the preview rather than replacing it, so a file that
   * can be read but not edited is still readable.
   */
  editNotice: string | null
  dismissEditNotice: () => void

  openPanel: (tab?: WorkspaceTab) => void
  closePanel: (byUser?: boolean) => Promise<void>
  togglePanel: () => void
  setTab: (tab: WorkspaceTab) => void
  setWidth: (w: number) => void

  /** Switch the panel to a new session: drop stale file/preview state and, if
   *  open on the files tab, reload the new session's root. */
  onSessionSwitch: (sessionId: string) => void

  /** Force the files tab back to the root and reload it. Used after the project
   *  for the current session changes (select / open / new), where the session
   *  id is unchanged so onSessionSwitch would no-op. */
  reloadRoot: () => void

  /** `origin` marks a file a conversation produced, so the panel can lead to it in the artifacts view. */
  preview: (target: WorkspaceEntry | Artifact | string, opts?: { origin?: ArtifactOrigin }) => Promise<void>
  openLink: (path: string) => Promise<void>
  addTurnArtifact: (a: Artifact) => void
  resetTurnArtifacts: () => void
  maybeAutoOpen: () => void

  /**
   * Ask before an action throws away unsaved edits.
   *
   * Resolves rather than taking a retry callback, so the caller stays a single
   * straight-line block and there is no window in which the editor has been
   * half torn down.
   *
   * @returns true when it is safe to proceed - either nothing was unsaved, or
   *   the user agreed to discard it (in which case the editor is already gone).
   */
  guardUnsavedEdit: () => Promise<boolean>
  /** Load the current file's text into the editor. */
  startEdit: () => Promise<void>
  setEditDirty: (dirty: boolean) => void
  /**
   * Park the in-progress text so it survives the editor being unmounted, which
   * happens whenever the user navigates off the chat route. Called from the
   * editor's cleanup, so it must be a no-op once the edit has been ended.
   */
  stashEditText: (text: string) => void
  /** Write `content` back to disk. `force` overwrites despite a conflict. */
  saveEdit: (content: string, opts?: { keepEditing?: boolean; force?: boolean }) => Promise<void>
  cancelEdit: () => Promise<void>
}

/** Artifact and WorkspaceEntry differ only in naming; normalize to an entry. */
function toEntry(a: Artifact): WorkspaceEntry {
  return {
    name: a.file_name,
    path: a.rel_path,
    is_dir: false,
    kind: a.kind,
    previewable: a.previewable,
    size: a.size,
    mtime: 0,
    abs_path: a.abs_path,
    raw_url: a.raw_url,
    preview_url: a.preview_url,
  }
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  open: false,
  tab: 'preview',
  width: readWidth(),
  current: null,
  previewError: null,
  autoOpenSuppressed: false,
  turnArtifacts: [],
  browseDir: null,
  browseSeq: 0,
  sessionId: '',
  edit: null,
  editNotice: null,

  dismissEditNotice: () => set({ editNotice: null }),

  openPanel: (tab) => set((s) => ({ open: true, tab: tab ?? s.tab })),

  // Closing unmounts the panel, and with it the text area, so unlike the web
  // console there is nothing left to come back to - ask first.
  closePanel: async (byUser) => {
    if (!(await get().guardUnsavedEdit())) return
    set((s) => ({
      open: false,
      edit: null,
      autoOpenSuppressed: byUser ? true : s.autoOpenSuppressed,
    }))
  },

  togglePanel: () => {
    const s = get()
    if (s.open) {
      s.closePanel(true)
      return
    }
    set({ open: true, autoOpenSuppressed: false, tab: s.current ? 'preview' : 'files' })
  },

  setTab: (tab) => set({ tab }),

  setWidth: (w) => {
    const next = Math.max(WS_MIN_WIDTH, Math.round(w))
    localStorage.setItem(WIDTH_KEY, String(next))
    set({ width: next })
  },

  onSessionSwitch: (sessionId) => {
    const s = get()
    if (s.sessionId === sessionId) return
    // The tree/preview belong to the previous session's working dir; drop them.
    // Unsaved edits are settled by the guard in sessionStore, which runs before
    // the switch commits and can still be cancelled.
    set({
      sessionId,
      current: null,
      previewError: null,
      turnArtifacts: [],
      browseDir: null,
      edit: null,
    })
    // If open on the files tab, reload the new session's root immediately.
    if (s.open && s.tab === 'files') {
      set({ browseDir: '', browseSeq: get().browseSeq + 1 })
    }
  },

  reloadRoot: () => {
    // No guard here: this runs after the project binding has been committed, so
    // declining could only leave the panel out of step with the session. The
    // callers ask beforehand, while the switch can still be called off.
    // Drop stale preview/artifacts and bump the browse counter so the files
    // tab re-fetches the (new) root even when path is unchanged ('').
    set({
      current: null,
      previewError: null,
      turnArtifacts: [],
      browseDir: '',
      browseSeq: get().browseSeq + 1,
      edit: null,
    })
  },

  preview: async (target, opts) => {
    // Opening another file replaces the editor.
    if (!(await get().guardUnsavedEdit())) return

    let entry: WorkspaceEntry | null = null
    if (typeof target === 'string') {
      try {
        entry = (await apiClient.workspaceResolve(target, get().sessionId)).file
      } catch (e) {
        set({
          open: true,
          tab: 'preview',
          current: null,
          previewError: e instanceof Error ? e.message : String(e),
        })
        return
      }
    } else if ('rel_path' in target) {
      entry = toEntry(target)
    } else {
      entry = target
    }

    // Directories have nothing to render; browse into them instead.
    const browseIfDir = (e: WorkspaceEntry | null): boolean => {
      if (!e?.is_dir) return false
      set({
        open: true,
        tab: 'files',
        previewError: null,
        browseDir: e.path,
        browseSeq: get().browseSeq + 1,
      })
      return true
    }
    if (browseIfDir(entry)) return

    // Cards rebuilt from history carry only a path; fetch the signed URLs.
    if (entry && !entry.preview_url) {
      try {
        entry = (await apiClient.workspaceResolve(entry.abs_path || entry.path, get().sessionId)).file
      } catch (e) {
        set({
          open: true,
          tab: 'preview',
          current: null,
          previewError: e instanceof Error ? e.message : String(e),
        })
        return
      }
      if (browseIfDir(entry)) return
    }

    if (entry && opts?.origin) entry = { ...entry, origin: opts.origin }
    set({ open: true, tab: 'preview', current: entry, previewError: null, edit: null })
  },

  /**
   * Open a workspace file referenced by a link in a rendered message. Agent
   * links are occasionally relative to the citing document rather than to the
   * workspace root, so fall back to a filename search before giving up.
   */
  openLink: async (path) => {
    try {
      await get().preview((await apiClient.workspaceResolve(path, get().sessionId)).file)
      return
    } catch {
      /* fall through to the name search */
    }

    const name = path.split('/').pop() || path
    try {
      const { results } = await apiClient.workspaceSearch(name, 10, get().sessionId)
      const hit = (results || []).find((r) => !r.is_dir && r.name === name)
      if (hit) {
        await get().preview(hit)
        return
      }
    } catch {
      /* fall through to the error state */
    }

    set({
      open: true,
      tab: 'preview',
      current: null,
      previewError: `${t('ws_link_not_found')}: ${path}`,
    })
  },

  addTurnArtifact: (a) =>
    set((s) =>
      s.turnArtifacts.some((x) => x.abs_path === a.abs_path)
        ? s
        : { turnArtifacts: [...s.turnArtifacts, a] }
    ),

  // Called when the user sends a new message. Clearing autoOpenSuppressed here
  // means "dismissing the panel only suppresses auto-open for the current turn";
  // a fresh request re-enables auto-preview of its products.
  resetTurnArtifacts: () => set({ turnArtifacts: [], autoOpenSuppressed: false }),

  /**
   * Auto-open policy: only when the turn produced exactly one previewable
   * artifact, and only while the user hasn't dismissed the panel by hand.
   */
  maybeAutoOpen: () => {
    const { turnArtifacts, autoOpenSuppressed, preview, edit, sessionId } = get()
    const previewable = turnArtifacts.filter((a) => a.previewable)
    set({ turnArtifacts: [] })
    // Never replace an open editor: the file cards stay in the message either way.
    if (autoOpenSuppressed || edit || previewable.length !== 1) return
    // The turn just ended, so it isn't persisted with a seq yet; the Agent is
    // the session's owner, worked out when the file is taken to the artifacts view.
    preview(previewable[0], { origin: { session_id: sessionId, agent_id: '', turn_seq: null } })
  },

  guardUnsavedEdit: async () => {
    const { edit } = get()
    if (!edit?.dirty) return true
    const ok = await askConfirm({
      titleKey: 'ws_edit_discard_title',
      msgKey: 'ws_edit_discard_msg',
      okKey: 'ws_edit_discard_ok',
    })
    if (!ok) return false
    set({ edit: null })
    return true
  },

  startEdit: async () => {
    const { current, edit, sessionId } = get()
    if (edit || !current || current.is_dir || !isEditable(current.kind)) return
    // The absolute path is unambiguous, which matters for files the panel
    // reaches outside the session's workspace root (memory / knowledge assets
    // while a project is open).
    const target = current.abs_path || current.path
    let res: Awaited<ReturnType<typeof apiClient.workspaceRead>>
    try {
      res = await apiClient.workspaceRead(target, sessionId)
    } catch (e) {
      set({ editNotice: `${t('ws_edit_load_failed')}: ${e instanceof Error ? e.message : String(e)}` })
      return
    }
    // The user may have opened another file while the request was in flight.
    // Compared by path, not identity: a save or a tree refresh replaces the
    // entry with an equal-but-new object, and an identity check would then
    // abort the edit for no reason and leave the button looking dead.
    if (get().current?.path !== current.path) return
    if (res.status !== 'success' || !res.editable) {
      // Truncation is reported first: a partial read can also split a
      // multi-byte character and so come back lossy, but the size is the
      // reason the user needs to hear.
      const reason = res.status !== 'success'
        ? res.message || t('ws_edit_load_failed')
        : t(res.truncated ? 'ws_edit_too_large' : res.lossy ? 'ws_edit_encoding' : 'ws_edit_unsupported')
      set({ editNotice: reason })
      return
    }
    // A text area reports CRLF as LF in its value, so normalizing here is what
    // keeps a CRLF file from looking modified the instant it loads. It also means
    // saving rewrites the file with LF endings, as the web console does.
    const content = res.content.replace(/\r\n/g, '\n')
    set({
      open: true,
      tab: 'preview',
      previewError: null,
      editNotice: null,
      edit: {
        file: current,
        loaded: content,
        baseline: content,
        baseMtime: res.mtime,
        dirty: false,
        saving: false,
        error: null,
      },
    })
  },

  setEditDirty: (dirty) =>
    set((s) => (s.edit && s.edit.dirty !== dirty ? { edit: { ...s.edit, dirty } } : s)),

  stashEditText: (text) =>
    set((s) => (s.edit && s.edit.loaded !== text ? { edit: { ...s.edit, loaded: text } } : s)),

  saveEdit: async (content, opts) => {
    const { keepEditing = false, force = false } = opts || {}
    const { edit, sessionId } = get()
    if (!edit || edit.saving) return
    // Writing an untouched file would bump its mtime for nothing.
    if (!force && !edit.dirty) {
      if (!keepEditing) set({ edit: null })
      return
    }

    set({ edit: { ...edit, saving: true, error: null } })
    try {
      const res = await apiClient.workspaceWrite({
        path: edit.file.abs_path || edit.file.path,
        content,
        session: sessionId,
        expectedMtime: force ? null : edit.baseMtime,
      })
      // A save that landed after the user moved on must not revive the editor.
      if (get().edit?.file.path !== edit.file.path) return

      if (res.code === 'conflict') {
        set((s) => (s.edit ? { edit: { ...s.edit, saving: false } } : s))
        const overwrite = await askConfirm({
          titleKey: 'ws_edit_conflict_title',
          msgKey: 'ws_edit_conflict_msg',
          okKey: 'ws_edit_overwrite',
        })
        if (overwrite) await get().saveEdit(content, { keepEditing, force: true })
        return
      }
      if (res.status !== 'success') throw new Error(res.message || 'save failed')

      // Keep the entry's metadata in step so a later edit starts from the
      // mtime we just wrote rather than a stale one.
      const file = { ...edit.file, size: res.size ?? edit.file.size, mtime: res.mtime ?? edit.file.mtime }
      if (keepEditing) {
        set({
          current: file,
          edit: {
            ...edit,
            file,
            // Not `loaded`: the editor seeds from that on mount only, and
            // rewriting it would be a no-op here anyway.
            baseline: content,
            baseMtime: res.mtime ?? edit.baseMtime,
            dirty: false,
            saving: false,
          },
        })
      } else {
        set({ current: file, edit: null })
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      set((s) => (s.edit ? { edit: { ...s.edit, saving: false, error: message } } : s))
    }
  },

  cancelEdit: async () => {
    if (!(await get().guardUnsavedEdit())) return
    set({ edit: null })
  },
}))
