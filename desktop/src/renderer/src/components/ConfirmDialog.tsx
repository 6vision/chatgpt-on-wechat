import React, { useEffect } from 'react'
import { t } from '../i18n'
import { Modal, Btn } from '../pages/settings/primitives'
import { useConfirmStore } from '../store/confirmStore'

/**
 * Renders whatever question `confirmStore` is currently holding.
 *
 * Mounted at the app level rather than inside any one page: an unsaved editor
 * outlives its page while the user is off on another route, and a question asked
 * then would otherwise have nothing to render it and would hang whoever is
 * awaiting the answer.
 */
const ConfirmDialog: React.FC = () => {
  const pending = useConfirmStore((s) => s.pending)
  const answer = useConfirmStore((s) => s.answer)

  // Keyboard is the fast path out of a dialog like this one.
  useEffect(() => {
    if (!pending) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') answer(false)
      else if (e.key === 'Enter') answer(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pending, answer])

  if (!pending) return null

  const message = Object.entries(pending.vars || {}).reduce(
    (text, [key, value]) => text.split(`{${key}}`).join(value),
    t(pending.msgKey),
  )

  return (
    <Modal open elevated title={t(pending.titleKey)} onClose={() => answer(false)}>
      <p className="text-sm text-content-secondary leading-relaxed">{message}</p>
      <div className="flex items-center justify-end gap-2 pt-1">
        <Btn onClick={() => answer(false)}>{t('config_cancel')}</Btn>
        <Btn variant="danger" onClick={() => answer(true)} autoFocus>
          {t(pending.okKey)}
        </Btn>
      </div>
    </Modal>
  )
}

export default ConfirmDialog
