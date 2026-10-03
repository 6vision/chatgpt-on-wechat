import React from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ExternalLink, FileX, Link2Off, Loader2 } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import FilePreview from '../components/FilePreview'
import { useMenuStore } from '../store/menuStore'
import { findItem, itemLabel } from '../lib/menu'
import type { MenuItem, WorkspaceEntry } from '../types'

const Empty: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="h-full flex flex-col items-center justify-center gap-3 px-6 text-center text-content-tertiary text-[13px]">
    {children}
  </div>
)

/** What an entry opens in the browser: the link, or the artifact's rendered page. */
function externalTarget(item: MenuItem | null): string {
  if (!item || item.type === 'builtin') return ''
  if (item.type === 'url') return item.url || ''
  const file = item.file
  if (!file?.exists) return ''
  return file.preview_url ? apiClient.getPreviewUrl(file.preview_url) : apiClient.getFileUrl(file.raw_url)
}

function asEntry(item: MenuItem): WorkspaceEntry | null {
  const file = item.file
  if (!file?.exists) return null
  return {
    name: file.file_name,
    path: item.path || '',
    abs_path: item.path,
    is_dir: false,
    kind: file.kind,
    previewable: !!file.previewable,
    size: 0,
    mtime: 0,
    raw_url: file.raw_url,
    preview_url: file.preview_url,
  }
}

function useCurrentItem(id: string): MenuItem | null {
  const doc = useMenuStore((s) => s.doc)
  const found = findItem(doc, id)
  return found && found.item.type !== 'builtin' ? found.item : null
}

/** Titlebar button for the page on screen: open it outside the app. */
export const CustomPageActions: React.FC = () => {
  const { pathname } = useLocation()
  const match = pathname.match(/^\/m\/(.+)$/)
  const target = externalTarget(useCurrentItem(match ? decodeURIComponent(match[1]) : ''))
  if (!target) return null
  return (
    <button
      onClick={() => window.open(target, '_blank', 'noopener,noreferrer')}
      title={t('menu_open_external')}
      className="titlebar-no-drag inline-flex items-center justify-center w-7 h-7 rounded-btn text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer transition-colors"
    >
      <ExternalLink size={15} />
    </button>
  )
}

/** A page the user put in the menu (/m/:id): a web page or an artifact, shown in place. */
const CustomPage: React.FC = () => {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const loaded = useMenuStore((s) => s.loaded)
  const item = useCurrentItem(id)

  if (!item) {
    return (
      <Empty>
        {loaded ? (
          <>
            <Link2Off size={26} className="opacity-40" />
            <span>{t('menu_page_missing')}</span>
            <button
              onClick={() => navigate('/')}
              className="px-3 py-1.5 rounded-btn border border-default hover:border-accent hover:text-accent cursor-pointer transition-colors"
            >
              {t('menu_back_chat')}
            </button>
          </>
        ) : (
          <Loader2 size={20} className="animate-spin" />
        )}
      </Empty>
    )
  }

  if (item.type === 'url') {
    return (
      <iframe
        key={item.url}
        src={item.url}
        title={itemLabel(item)}
        className="flex-1 w-full h-full border-0 bg-white"
        // The page keeps its own origin; the sandbox only withholds what an
        // embedded site has no business doing to the app around it, such as
        // navigating the window away.
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-modals allow-downloads"
        referrerPolicy="no-referrer"
      />
    )
  }

  const entry = asEntry(item)
  if (!entry) {
    return (
      <Empty>
        <FileX size={26} className="opacity-40" />
        <span>{t('menu_file_missing')}</span>
      </Empty>
    )
  }
  return (
    <div className="flex-1 min-h-0 overflow-auto">
      {entry.kind === 'html' ? (
        <FilePreview file={entry} />
      ) : (
        // A document reads as a page: a centred column with room around it.
        <div className="max-w-[880px] mx-auto px-8 py-6">
          <FilePreview file={entry} />
        </div>
      )}
    </div>
  )
}

export default CustomPage
