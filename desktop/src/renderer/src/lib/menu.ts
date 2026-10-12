// The nav rail's menu: the built-in one, or the one the user arranged
// (GET /api/menu). The web console reads the same document, so a page only
// one client has is skipped by the other, never dropped. Mirrors the web
// console's core/menu.js.
import {
  MessageSquare,
  Users,
  BookOpen,
  Brain,
  Zap,
  Radio,
  Clock,
  Settings,
  ScrollText,
  Globe,
  Link,
  ChartLine,
  Gauge,
  Table,
  FileText,
  Book,
  Image,
  Film,
  Music,
  Code,
  Calendar,
  Star,
  Bookmark,
  Folder,
  Box,
  Rocket,
  Flag,
  Heart,
  Terminal,
  House,
  ShoppingCart,
  Mail,
  Layers,
  Bot,
  Pen,
  Search,
  type LucideIcon,
} from 'lucide-react'
import { t } from '../i18n'
import { iconFor } from './fileKind'
import type { FileKind, MenuDoc, MenuGroup, MenuItem } from '../types'

/** The pages of this app a menu can lead to, by the view name the document uses. */
export const MENU_BUILTINS: Record<string, { path: string; labelKey: string; icon: LucideIcon }> = {
  chat: { path: '/', labelKey: 'menu_chat', icon: MessageSquare },
  artifacts: { path: '/artifacts', labelKey: 'menu_artifacts', icon: Layers },
  agents: { path: '/agents', labelKey: 'menu_agents', icon: Users },
  knowledge: { path: '/knowledge', labelKey: 'menu_knowledge', icon: BookOpen },
  memory: { path: '/memory', labelKey: 'menu_memory', icon: Brain },
  skills: { path: '/skills', labelKey: 'menu_skills', icon: Zap },
  channels: { path: '/channels', labelKey: 'menu_channels', icon: Radio },
  tasks: { path: '/tasks', labelKey: 'menu_tasks', icon: Clock },
  config: { path: '/settings', labelKey: 'menu_settings', icon: Settings },
  logs: { path: '/logs', labelKey: 'menu_logs', icon: ScrollText },
}

// The built-in menu. Until the user saves one the rail draws it flat, in this
// order. The document is shared with the web console, so it keeps every page
// the console has, footer ones included.
export const MENU_DEFAULT: { id: string; views: string[] }[] = [
  { id: 'chat', views: ['chat', 'artifacts'] },
  { id: 'manage', views: ['agents', 'knowledge', 'memory', 'skills', 'channels', 'tasks', 'config'] },
  { id: 'monitor', views: ['logs'] },
]

export const MENU_GROUP_LABELS: Record<string, string> = {
  chat: 'nav_chat',
  manage: 'nav_manage',
  monitor: 'nav_monitor',
}

/** Pages a menu must always lead to; mirrors REQUIRED_VIEWS in channel/web/api/menu.py. */
export const MENU_REQUIRED = new Set(['chat', 'config'])

/** Artifacts that can be a page of the menu; mirrors MENU_KINDS in channel/web/api/menu.py. */
export const MENU_KINDS: ReadonlySet<FileKind> = new Set<FileKind>(['html', 'markdown'])

/** Pages the built-in menu carries: they can be hidden, never removed. */
export const MENU_DEFAULT_VIEWS = new Set(MENU_DEFAULT.flatMap((g) => g.views))

/** Built-in pages that start hidden; mirrors MENU_DEFAULT_HIDDEN in the web console. */
const MENU_DEFAULT_HIDDEN: ReadonlySet<string> = new Set(['artifacts'])

/**
 * Pages this app keeps in the rail's footer menu rather than in the menu. The
 * entry stays in the document, untouched, for the web console; here neither
 * the rail nor the editor shows it.
 */
const MENU_FOOTER_VIEWS: ReadonlySet<string> = new Set(['logs'])

export function isFooterItem(item: MenuItem): boolean {
  return item.type === 'builtin' && MENU_FOOTER_VIEWS.has(item.view || '')
}

// Icons a user can give an entry. Only the names travel in the document; the
// web console maps the same names to its own icon set.
export const MENU_ICONS: Record<string, LucideIcon> = {
  globe: Globe,
  link: Link,
  chart: ChartLine,
  gauge: Gauge,
  table: Table,
  file: FileText,
  book: Book,
  image: Image,
  video: Film,
  music: Music,
  code: Code,
  calendar: Calendar,
  star: Star,
  bookmark: Bookmark,
  folder: Folder,
  box: Box,
  rocket: Rocket,
  flag: Flag,
  heart: Heart,
  bolt: Zap,
  brain: Brain,
  clock: Clock,
  terminal: Terminal,
  home: House,
  cart: ShoppingCart,
  mail: Mail,
  layers: Layers,
  robot: Bot,
  pen: Pen,
  search: Search,
}

export const MENU_TITLE_MAX = 40

export function builtinItem(view: string): MenuItem {
  return { id: view, type: 'builtin', view, title: '', icon: '', hidden: false }
}

function defaultItem(view: string): MenuItem {
  return { ...builtinItem(view), hidden: MENU_DEFAULT_HIDDEN.has(view) }
}

/** The built-in menu as a document. */
export function defaultMenu(): MenuDoc {
  return { groups: MENU_DEFAULT.map((g) => ({ id: g.id, title: '', items: g.views.map(defaultItem) })) }
}

/** The menu to draw: the saved one, plus any built-in page this version added since. */
export function mergeMenu(saved: MenuDoc | null): MenuDoc {
  if (!saved || !Array.isArray(saved.groups) || !saved.groups.length) return defaultMenu()
  const doc: MenuDoc = {
    groups: saved.groups.map((g) => ({
      id: g.id,
      title: g.title || '',
      items: (g.items || []).map((i) => ({ ...i })),
    })),
  }
  const present = new Set<string>()
  doc.groups.forEach((g) => g.items.forEach((i) => i.type === 'builtin' && i.view && present.add(i.view)))
  for (const def of MENU_DEFAULT) {
    for (const view of def.views) {
      if (present.has(view)) continue
      const home = doc.groups.find((g) => g.id === def.id) || doc.groups[doc.groups.length - 1]
      home.items.push(defaultItem(view))
    }
  }
  return doc
}

export function findItem(doc: MenuDoc, id: string): { group: MenuGroup; item: MenuItem } | null {
  for (const group of doc.groups) {
    const item = group.items.find((i) => i.id === id)
    if (item) return { group, item }
  }
  return null
}

export function groupLabel(group: MenuGroup): string {
  if (group.title) return group.title
  return MENU_GROUP_LABELS[group.id] ? t(MENU_GROUP_LABELS[group.id]) : t('menu_group_untitled')
}

export function itemLabel(item: MenuItem): string {
  if (item.title) return item.title
  if (item.type !== 'builtin' || !item.view) return ''
  const builtin = MENU_BUILTINS[item.view]
  if (builtin) return t(builtin.labelKey)
  // A page only the web console has, named if this app knows what it is.
  const key = `menu_${item.view}`
  return t(key) === key ? item.view : t(key)
}

export function itemIcon(item: MenuItem): LucideIcon {
  if (item.icon && MENU_ICONS[item.icon]) return MENU_ICONS[item.icon]
  if (item.type === 'builtin') return (item.view && MENU_BUILTINS[item.view]?.icon) || Folder
  if (item.type === 'url') return Globe
  return iconFor(item.file?.kind || 'file')
}

/** Whether the rail draws the entry: hidden pages, footer pages and pages only the web console has are skipped. */
export function itemShows(item: MenuItem): boolean {
  if (item.type !== 'builtin') return true
  return !!item.view && !!MENU_BUILTINS[item.view] && !item.hidden && !isFooterItem(item)
}

/** Where an entry leads inside the app. */
export function itemRoute(item: MenuItem): string {
  if (item.type === 'builtin') return (item.view && MENU_BUILTINS[item.view]?.path) || '/'
  return `/m/${encodeURIComponent(item.id)}`
}

export function newMenuId(prefix: string): string {
  return prefix + Math.random().toString(36).slice(2, 10)
}
