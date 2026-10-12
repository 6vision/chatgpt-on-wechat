import React, { createContext, useContext, useEffect, useRef, useState } from 'react'
import { Pin, MessageSquare, Download, Play, FileX } from 'lucide-react'
import { t } from '../../i18n'
import apiClient from '../../api/client'
import Tooltip from '../../components/Tooltip'
import AgentAvatar from '../../components/AgentAvatar'
import { markdownToHtml } from '../../components/Markdown'
import { iconFor, colorFor } from '../../lib/fileKind'
import { findAgent } from '../../store/agentStore'
import { artName, type ArtifactShown } from '../../store/artifactStore'
import { cardTime, extOf } from './format'

const TEXT_KINDS = new Set(['markdown', 'code', 'text', 'csv'])
// Only the head of a text file is drawn on its card; past this size the fetch
// costs more than the glimpse is worth.
const TEXT_THUMB_MAX = 512 * 1024
const TEXT_THUMB_CHARS = 2400

/** Calls back once an element comes near the timeline's viewport. */
export type NearWatcher = (el: Element, onNear: () => void) => () => void
export const NearContext = createContext<NearWatcher | null>(null)

function useNear(ref: React.RefObject<Element>): boolean {
  const watch = useContext(NearContext)
  const [near, setNear] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || near) return
    if (!watch) {
      setNear(true)
      return
    }
    return watch(el, () => setNear(true))
  }, [watch, ref, near])
  return near
}

export function downloadArtifact(item: ArtifactShown) {
  if (item.exists && item.raw_url) window.open(apiClient.getFileUrl(item.raw_url), '_blank')
}

/** The thumbnail is drawn once the card is near the viewport, over a placeholder that shows through until it has loaded. */
const Thumb: React.FC<{ item: ArtifactShown }> = ({ item }) => {
  const ref = useRef<HTMLDivElement>(null)
  const near = useNear(ref) && item.exists
  const [loaded, setLoaded] = useState(false)
  const [broken, setBroken] = useState(false)
  const [paper, setPaper] = useState<{ html?: string; text?: string } | null>(null)
  const textThumb = TEXT_KINDS.has(item.kind) && !!item.preview_url && item.size <= TEXT_THUMB_MAX

  useEffect(() => {
    if (!near || !textThumb) return
    let cancelled = false
    fetch(apiClient.getPreviewUrl(item.preview_url))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((text) => {
        const head = text.slice(0, TEXT_THUMB_CHARS)
        if (cancelled || !head.trim()) return
        if (item.kind === 'markdown') {
          // A thumbnail is a picture of the text; nothing in it should load.
          setPaper({ html: markdownToHtml(head).replace(/<img\b[^>]*>/gi, '') })
        } else {
          setPaper({ text: head.split('\n').slice(0, 60).join('\n') })
        }
        setLoaded(true)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [near, textThumb, item.kind, item.preview_url])

  const Icon = item.exists ? iconFor(item.kind) : FileX
  const ext = extOf(item.file_name)
  const done = () => setLoaded(true)

  let media: React.ReactNode = null
  if (near && !broken) {
    if (item.kind === 'image') {
      media = (
        <img
          className="art-media"
          alt=""
          decoding="async"
          draggable={false}
          src={apiClient.getFileUrl(item.raw_url)}
          onLoad={done}
          onError={() => setBroken(true)}
        />
      )
    } else if (item.kind === 'video') {
      media = (
        <video
          className="art-media"
          muted
          playsInline
          preload="metadata"
          src={`${apiClient.getFileUrl(item.raw_url)}#t=0.1`}
          onLoadedData={done}
          onError={() => setBroken(true)}
        />
      )
    } else if (item.kind === 'html' && item.preview_url) {
      media = (
        <div className="art-frame">
          {/* Opaque origin, and nothing that could act on its own: the thumbnail only has to paint. */}
          <iframe
            src={apiClient.getPreviewUrl(item.preview_url)}
            sandbox="allow-scripts"
            scrolling="no"
            tabIndex={-1}
            aria-hidden="true"
            title=""
            onLoad={done}
          />
        </div>
      )
    } else if (paper) {
      media = (
        <div className="art-paper">
          {paper.html != null ? (
            <div className="art-paper-page msg-content" dangerouslySetInnerHTML={{ __html: paper.html }} />
          ) : (
            <pre className="art-paper-page art-paper-mono">{paper.text}</pre>
          )}
        </div>
      )
    }
  }

  return (
    <div ref={ref} className={`art-thumb art-kind-${item.kind || 'file'}${loaded ? ' is-loaded' : ''}`}>
      <div className="art-ph">
        <Icon size={28} strokeWidth={1.6} />
        {item.exists ? ext && <span className="art-ph-ext">{ext}</span> : <span className="art-ph-ext">{t('artifacts_missing')}</span>}
      </div>
      {media}
      {item.kind === 'video' && item.exists && (
        <span className="art-play">
          <Play size={13} fill="currentColor" />
        </span>
      )}
    </div>
  )
}

interface ArtifactCardProps {
  item: ArtifactShown
  selected: boolean
  /** Across Agents the card says whose it is. */
  showOwner: boolean
  onSelect: (item: ArtifactShown) => void
  onPin: (item: ArtifactShown) => void
  onJump: (item: ArtifactShown) => void
}

const ArtifactCard: React.FC<ArtifactCardProps> = ({ item, selected, showOwner, onSelect, onPin, onJump }) => {
  const name = artName(item)
  const KindIcon = iconFor(item.kind)
  const agent = showOwner ? findAgent(item.agent_id) : undefined
  const tool = (label: string, onClick: () => void, children: React.ReactNode, extra = '') => (
    <Tooltip label={label} placement="bottom">
      <button
        type="button"
        className={`art-tool${extra}`}
        onClick={(e) => {
          e.stopPropagation()
          onClick()
        }}
      >
        {children}
      </button>
    </Tooltip>
  )

  return (
    <div
      className={`art-card${item.exists ? '' : ' is-missing'}${selected ? ' is-selected' : ''}`}
      data-art-id={item.id ?? undefined}
      tabIndex={0}
      onClick={() => onSelect(item)}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
          e.preventDefault()
          onSelect(item)
        }
      }}
    >
      <div className="relative">
        {/* Keyed on the write time, so a file written again repaints its thumbnail. */}
        <Thumb key={item.updated_at} item={item} />
        <div className="art-tools">
          {tool(
            t(item.pinned_at ? 'artifacts_unpin' : 'artifacts_pin'),
            () => onPin(item),
            <Pin size={13} />,
            ` art-tool-pin${item.pinned_at ? ' is-active' : ''}`
          )}
          {item.can_jump && tool(t('artifacts_jump'), () => onJump(item), <MessageSquare size={13} />)}
          {item.exists && tool(t('ws_download'), () => downloadArtifact(item), <Download size={13} />)}
        </div>
      </div>
      <div className="art-card-name" title={item.rel_path || name}>
        <KindIcon size={13} className={`shrink-0 ${item.exists ? colorFor(item.kind) : ''}`} />
        <span>{name}</span>
      </div>
      <div className="art-card-meta">
        <span className="art-card-time">{cardTime(item)}</span>
        {agent && (
          <>
            <span className="art-card-dot" />
            <AgentAvatar agent={agent} size={16} />
            <span className="truncate">{agent.name || agent.id}</span>
          </>
        )}
      </div>
    </div>
  )
}

export default React.memo(ArtifactCard)
