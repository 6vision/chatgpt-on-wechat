import { create } from 'zustand'

export interface PendingConfirm {
  /** i18n keys for the heading and the body text. */
  titleKey: string
  msgKey: string
  /** Values for `{name}`-style placeholders in the body text. */
  vars?: Record<string, string>
  /** Label for the affirmative button; the other one is always a plain cancel. */
  okKey: string
  resolve: (ok: boolean) => void
}

interface ConfirmState {
  /**
   * Question awaiting an answer, rendered by ConfirmDialog.
   *
   * An in-app dialog rather than window.confirm: Electron serves the native one
   * synchronously off the renderer's own thread, where it swallows the result
   * and leaves the window without keyboard focus.
   */
  pending: PendingConfirm | null
  ask: (question: Omit<PendingConfirm, 'resolve'>) => Promise<boolean>
  answer: (ok: boolean) => void
}

/**
 * The app's single yes/no dialog, shared by everything that has to settle a
 * question before throwing work away (discard unsaved edits, overwrite a file
 * the agent changed underneath us).
 *
 * Kept apart from the stores that ask so that the dialog outlives them: an
 * unsaved editor survives its own page being unmounted, and a question asked
 * then would otherwise have nothing to render it and would hang whoever is
 * awaiting the answer.
 */
export const useConfirmStore = create<ConfirmState>((set, get) => ({
  pending: null,

  ask: (question) =>
    new Promise<boolean>((resolve) => {
      // Two questions can't share the dialog. Retract the older one as declined
      // so whoever is awaiting it unblocks instead of hanging forever.
      get().pending?.resolve(false)
      set({ pending: { ...question, resolve } })
    }),

  answer: (ok) => {
    const pending = get().pending
    set({ pending: null })
    pending?.resolve(ok)
  },
}))

/** Ask from outside a component, where the hook form is unavailable. */
export const askConfirm = (question: Omit<PendingConfirm, 'resolve'>): Promise<boolean> =>
  useConfirmStore.getState().ask(question)
