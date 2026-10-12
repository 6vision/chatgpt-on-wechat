import { create } from 'zustand'

/** A place in a conversation to glide to once it is on screen. */
export interface JumpRequest {
  sessionId: string
  /** The turn's question. */
  seq: number
  /** A file the turn produced: the view lands on its card when the turn shows one. */
  path?: string
}

interface TimelineState {
  /** True while a message-navigator jump is loading pages or gliding; the chat
   *  page holds off its own auto-scroll and load-more so they don't fight it. */
  jumping: boolean
  setJumping: (v: boolean) => void
  /** Asked for from another page; the navigator takes it once the history has loaded. */
  pendingJump: JumpRequest | null
  requestJump: (request: JumpRequest | null) => void
}

export const useTimelineStore = create<TimelineState>((set) => ({
  jumping: false,
  setJumping: (jumping) => set({ jumping }),
  pendingJump: null,
  requestJump: (pendingJump) => set({ pendingJump }),
}))
