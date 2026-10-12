import { t, getLang } from '../../i18n'
import type { ArtifactShown } from '../../store/artifactStore'

function locale(): string {
  return getLang() === 'en' ? 'en-US' : 'zh-CN'
}

function dayStart(ts: number): number {
  const d = new Date(ts * 1000)
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/** "Today" / "Yesterday" with the date beside it; older days are just the date. */
export function dayLabel(ts: number): { primary: string; secondary: string } {
  const d = new Date(ts * 1000)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const diff = Math.round((today - dayStart(ts)) / 86400000)
  const opts: Intl.DateTimeFormatOptions =
    d.getFullYear() === now.getFullYear()
      ? { month: 'long', day: 'numeric', weekday: 'short' }
      : { year: 'numeric', month: 'long', day: 'numeric' }
  const date = d.toLocaleDateString(locale(), opts)
  if (diff === 0) return { primary: t('artifacts_today'), secondary: date }
  if (diff === 1) return { primary: t('artifacts_yesterday'), secondary: date }
  return { primary: date, secondary: '' }
}

export function dateTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString(locale(), {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

/** Under a day label the time is enough; in the pinned section the day is not implied. */
export function cardTime(item: ArtifactShown): string {
  const d = new Date(item.updated_at * 1000)
  if (!item.pinned_at || dayStart(item.updated_at) === dayStart(Date.now() / 1000)) {
    return d.toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  return d.toLocaleDateString(locale(), { month: 'short', day: 'numeric' })
}

/** The extension shown on a placeholder, at most five letters. */
export function extOf(name: string): string {
  const i = (name || '').lastIndexOf('.')
  return i > 0 ? name.slice(i + 1).toUpperCase().slice(0, 5) : ''
}

/** Pinned files share one section on top; the rest are grouped by day. */
export function sectionKey(item: ArtifactShown): string {
  return item.pinned_at ? 'pinned' : String(dayStart(item.updated_at))
}
