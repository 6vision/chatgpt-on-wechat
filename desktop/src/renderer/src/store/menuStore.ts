import { create } from 'zustand'
import apiClient from '../api/client'
import { mergeMenu } from '../lib/menu'
import type { MenuDoc, MenuItem } from '../types'

const CACHE_KEY = 'cow_menu_cache'

function readCache(): MenuDoc | null {
  try {
    const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null')
    return cached && Array.isArray(cached.groups) ? cached : null
  } catch {
    return null
  }
}

function writeCache(menu: MenuDoc | null) {
  try {
    if (menu) localStorage.setItem(CACHE_KEY, JSON.stringify(menu))
    else localStorage.removeItem(CACHE_KEY)
  } catch {
    // localStorage unavailable: the menu is fetched again next launch anyway
  }
}

interface MenuState {
  /** The menu the user saved; null while they keep the built-in one. */
  saved: MenuDoc | null
  /** What the rail draws: the saved menu merged with this version's built-in pages. */
  doc: MenuDoc
  /** The backend has answered at least once, so a missing entry really is missing. */
  loaded: boolean
  load: () => Promise<void>
  /** Save the whole menu (null restores the built-in one). Throws with the backend's reason. */
  save: (menu: MenuDoc | null) => Promise<void>
  editorOpen: boolean
  /** What the editor opens on: an entry to place in the first group, or one to point out. */
  editorIntent: EditorIntent | null
  openEditor: (intent?: EditorIntent) => void
  closeEditor: () => void
}

export interface EditorIntent {
  add?: MenuItem
  focus?: string
}

const apply = (menu: MenuDoc | null) => {
  writeCache(menu)
  return { saved: menu, doc: mergeMenu(menu), loaded: true }
}

// Drawn from the last launch's copy first, so a customised rail does not flash
// the built-in one while GET /api/menu is in flight.
const cached = readCache()

export const useMenuStore = create<MenuState>((set) => ({
  saved: cached,
  doc: mergeMenu(cached),
  loaded: false,

  load: async () => {
    try {
      const res = await apiClient.getMenu()
      if (res.status === 'success') set(apply(res.menu))
      else set({ loaded: true })
    } catch {
      // A backend without /api/menu keeps the built-in rail.
      set({ loaded: true })
    }
  },

  save: async (menu) => {
    const res = await apiClient.saveMenu(menu)
    if (res.status !== 'success') throw new Error(res.message || '')
    set(apply(res.menu))
  },

  editorOpen: false,
  editorIntent: null,
  openEditor: (intent) => set({ editorOpen: true, editorIntent: intent || null }),
  closeEditor: () => set({ editorOpen: false, editorIntent: null }),
}))
