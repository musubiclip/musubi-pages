// Shapes of GET /api/state (pages/web.py) and the calls that change it.

export type Page = {
  handle: string
  pipeline: "clips" | "script"
  connected: boolean
  reconnect: boolean
  token_expires_at: string | null
  paused: boolean
  paused_at: string | null
  pause_reason: string | null
  status_due: boolean
  recommendable: boolean | null
  status_checked_at: string | null
  metrics: { reels: number; median_views: number | null; non_follower_share: number | null }
  counts: { draft: number; approved: number; scheduled: number; published: number }
  settings: { voice: string; window: [number, number]; daily_target: number; theme: Record<string, string> }
}

export type Draft = {
  id: number
  page: string
  kind: "clip" | "script"
  created_at: string | null
  video_url: string | null
  hook: string | null
  layer: { intro?: string; takeaway?: string; cards?: { at: number; title: string; body: string }[] } | null
  flags: string[]
  claims: string[]
  credits: { text: string; url: string | null }[]
  caption: string
  source: { name: string; url: string; permission: string; proof: string | null; instagram: string | null } | null
  note: string | null
}

export type Problem = { at: string; page: string | null; kind: string; detail: string | null; count: number }

export type State = { pages: Page[]; drafts: Draft[]; problems: Problem[] }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  const text = await r.text()
  if (!r.ok) {
    let msg = text || r.statusText
    try {
      msg = JSON.parse(text).detail ?? msg
    } catch {
      // plain text from the access check: keep it
    }
    throw new Error(String(msg))
  }
  return JSON.parse(text) as T
}

export const getState = () => call<State>("/api/state")

export const post = (path: string, body?: object) =>
  call<{ ok: true }>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  })

// --- words for the screen ---

const IST = "Asia/Kolkata"

export const when = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", {
        timeZone: IST, day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
      })
    : "never"

export const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", year: "numeric" }) : ""

export const hour = (h: number) => `${h}:00`

export const kindLabel = (kind: string) => {
  const words = kind.replace(/_/g, " ")
  return words[0].toUpperCase() + words.slice(1)
}

export const hashtags = (caption: string) => (caption.match(/#/g) ?? []).length

export type Tone = "ok" | "wait" | "pending" | "ink" | "neutral"

// One word and one tone per page: paused beats reconnect beats a due status check.
export function pageStatus(p: Page): { word: string; tone: Tone } {
  if (p.paused) return { word: "Paused", tone: "ink" }
  if (!p.connected) return { word: "Not connected", tone: "pending" }
  if (p.reconnect) return { word: "Reconnect", tone: "wait" }
  if (p.status_due) return { word: "Check due", tone: "wait" }
  return { word: "Live", tone: "ok" }
}
