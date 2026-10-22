import { useId, useState, type ReactNode } from "react"
import { CalendarClock, CalendarDays, ExternalLink, Film, KeyRound, Link2, Pause, Play, Send, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { day, hour, post, when, type Page, type Reel } from "@/api"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { AspectRatio } from "@/components/ui/aspect-ratio"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import { Card } from "@/components/ui/card"
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Header, Label11 } from "@/parts"

type Refresh = () => Promise<void>

async function send(path: string, body: object | undefined, done: string, refresh: Refresh) {
  try {
    await post(path, body)
    toast.success(done)
    await refresh()
    return true
  } catch (e) {
    toast.error((e as Error).message)
    return false
  }
}

export function PageView({ page: p, refresh }: { page: Page; refresh: Refresh }) {
  const base = `/api/pages/${encodeURIComponent(p.handle)}`
  const m = p.metrics
  const theme = Object.entries(p.settings.theme)
  const colours = theme.filter(([, v]) => v.startsWith("#"))
  const others = theme.filter(([, v]) => !v.startsWith("#"))
  return (
    <>
      <Header
        title={`@${p.handle}`}
        lede={
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Badge variant="plain">{p.pipeline === "clips" ? "Clip pipeline" : "Script pipeline"}</Badge>
            {p.connected && !p.reconnect && <Badge variant="ok">Connected until {day(p.token_expires_at)}</Badge>}
            {p.connected && p.reconnect && <Badge variant="wait">Reconnect, expires {day(p.token_expires_at)}</Badge>}
            {!p.connected && <Badge variant="pending">{p.token_expires_at ? `Reconnect, expired ${day(p.token_expires_at)}` : "Not connected"}</Badge>}
            {p.paused && <Badge variant="ink">Paused</Badge>}
          </div>
        }
      >
        <div className="flex flex-wrap gap-2 max-sm:w-full max-sm:[&>*]:flex-1">
          {p.pipeline === "clips" && <AddLink handle={p.handle} refresh={refresh} />}
          <Connect page={p} base={base} refresh={refresh} />
        </div>
      </Header>

      <div className="flex flex-col gap-4">
        {p.paused && (
          <Card className="flex-row flex-wrap items-center gap-4 border-foreground p-5" role="status">
            <Pause className="size-5 shrink-0" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="font-semibold">Paused since {when(p.paused_at)}</p>
              <p className="text-muted-foreground">{sentence(p.pause_reason || "no reason recorded")}. Nothing posts until you unpause.</p>
            </div>
            <Button variant="outline" className="max-sm:w-full" onClick={() => send(`${base}/unpause`, undefined, `@${p.handle} unpaused`, refresh)}>
              <Play aria-hidden="true" /> Unpause
            </Button>
          </Card>
        )}

        {p.status_due && <StatusCheck page={p} base={base} refresh={refresh} />}

        <div className="grid gap-4 sm:grid-cols-3">
          <Stat label="Reels in 28 days" value={m.reels.toLocaleString("en-IN")} note="Published through the tool" />
          <Stat label="Median views" value={m.median_views?.toLocaleString("en-IN")}
            note={m.median_views === null ? "Shows once reels have insights" : "Per reel, 7 day count when there is one"} />
          <Stat label="Non follower share"
            value={m.non_follower_share === null ? undefined : `${Math.round(m.non_follower_share * 100)}%`}
            note={m.non_follower_share === null ? "The API has not reported it yet" : "Of account views, last 28 days"} />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="gap-4">
            <CardHead title="Queue" aside={p.counts.draft > 0 && (
              <a href="#/" className="text-sm font-medium underline underline-offset-4 hover:text-muted-foreground">Review drafts</a>
            )} />
            <dl className="mx-5 grid grid-cols-2 gap-px overflow-hidden rounded-[10px] border bg-border max-sm:mx-4 sm:grid-cols-4">
              {([["Drafts", p.counts.draft], ["Approved", p.counts.approved], ["Scheduled", p.counts.scheduled],
                ["Published", p.counts.published]] as const).map(([k, v]) => (
                <div key={k} className="flex flex-col gap-0.5 bg-card px-4 py-3">
                  <dt className="text-xs text-muted-foreground">{k}</dt>
                  <dd className="tnum text-xl font-bold">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="px-5 text-sm text-muted-foreground max-sm:px-4">
              Account Status: {p.recommendable === null ? "not checked yet" : p.recommendable ? "recommendable" : "not recommendable"}
              {p.status_checked_at && `, checked ${when(p.status_checked_at)}`}
            </p>
          </Card>

          <Card className="gap-4">
            <CardHead title="Settings" aside={<span className="text-xs text-muted-foreground">Read only, from pages.toml</span>} />
            <dl className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-x-4 gap-y-3 px-5 text-sm max-sm:grid-cols-1 max-sm:gap-y-1 max-sm:px-4">
              <Row k="Voice">{p.settings.voice}</Row>
              <Row k="Posting window">{hour(p.settings.window[0])} to {hour(p.settings.window[1])} IST</Row>
              <Row k="Daily target">{p.settings.daily_target} {p.settings.daily_target === 1 ? "reel" : "reels"} a day</Row>
              <Row k="Theme colours">
                <span className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  {colours.map(([k, v]) => (
                    <span key={k} className="inline-flex items-center gap-2">
                      <span className="size-5 rounded-md border" style={{ background: v }} aria-hidden="true" />
                      <span><span className="text-muted-foreground">{k}</span> <span className="tnum">{v}</span></span>
                    </span>
                  ))}
                </span>
              </Row>
              {others.map(([k, v]) => <Row key={k} k={`Theme ${k}`}>{v}</Row>)}
            </dl>
          </Card>
        </div>

        <Reels reels={p.reels} handle={p.handle} window={p.settings.window} refresh={refresh} />
      </div>
    </>
  )
}

const TABS = [["scheduled", "Scheduled"], ["approved", "Approved"], ["published", "Published"]] as const
const KIND: Record<string, string> = { montage: "Montage", rapidfire: "Rapid fire", script: "Script reel" }

function Reels({ reels, handle, window, refresh }: { reels: Reel[]; handle: string; window: [number, number]; refresh: Refresh }) {
  const first = reels.some((r) => r.status === "scheduled") ? "scheduled" : "published"
  return (
    <Card className="gap-4">
      <Tabs defaultValue={first} className="gap-4">
        <CardHead title="Reels" aside={
          <TabsList aria-label="Reel status">
            {TABS.map(([k, label]) => (
              <TabsTrigger key={k} value={k}>
                {label} <Badge variant="plain" className="tnum ml-1">{reels.filter((r) => r.status === k).length}</Badge>
              </TabsTrigger>
            ))}
          </TabsList>
        } />
        {TABS.map(([k]) => {
          const shown = reels.filter((r) => r.status === k)
            .sort((a, b) => k === "scheduled" ? (a.scheduled_at ?? "").localeCompare(b.scheduled_at ?? "") : 0)
          return (
            <TabsContent key={k} value={k} className="animate-in px-5 fade-in duration-300 max-sm:px-4">
              {shown.length === 0 ? (
                <p className="pb-1 text-sm text-muted-foreground">No {k} reels for @{handle} yet.</p>
              ) : (
                <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
                  {shown.map((r) => <ReelTile key={r.id} r={r} window={window} refresh={refresh} />)}
                </ul>
              )}
            </TabsContent>
          )
        })}
      </Tabs>
    </Card>
  )
}

// IST wall clock parts of an instant, and back
const IST_MS = 330 * 60_000
const istParts = (iso: string | null) => {
  const d = new Date((iso ? new Date(iso).getTime() : Date.now()) + IST_MS)
  return { day: new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()), hour: d.getUTCHours(), minute: d.getUTCMinutes() }
}
const istIso = (day: Date, hour: number, minute: number) =>
  `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}T` +
  `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00+05:30`
const MINUTES = [0, 15, 30, 45]

function ReelTile({ r, window, refresh }: { r: Reel; window: [number, number]; refresh: Refresh }) {
  const at = r.status === "published" ? r.published_at : r.status === "scheduled" ? r.scheduled_at : null
  const [open, setOpen] = useState(false)
  const movable = r.status === "scheduled" || r.status === "approved"
  const start = () => {  // approved reels have no time yet: start at the next hour, inside the window
    if (r.scheduled_at) return istParts(r.scheduled_at)
    const p = istParts(null)
    const h = p.hour + 1
    if (h < window[0]) return { ...p, hour: window[0], minute: 0 }
    if (h < window[1]) return { ...p, hour: h, minute: 0 }
    return { day: new Date(p.day.getFullYear(), p.day.getMonth(), p.day.getDate() + 1), hour: window[0], minute: 0 }
  }
  const [pick, setPick] = useState(start)
  const [busy, setBusy] = useState(false)
  const hours = Array.from({ length: window[1] - window[0] }, (_, i) => window[0] + i)
  const chosen = istIso(pick.day, pick.hour, pick.minute)
  const changed = r.scheduled_at === null || new Date(chosen).getTime() !== new Date(r.scheduled_at).getTime()
  const today = istParts(null).day
  const act = async (path: string, body: object | undefined, done: string, close: boolean) => {
    setBusy(true)
    const ok = await send(`/api/clips/${r.id}/${path}`, body, done, refresh)
    setBusy(false)
    if (ok && close) setOpen(false)
  }
  return (
    <li>
      <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (o) setPick(start()) }}>
        <DialogTrigger asChild>
          <button className="group flex w-full flex-col gap-2 text-left focus-visible:outline-none">
            <AspectRatio ratio={9 / 16} className="overflow-hidden rounded-[10px] border bg-muted shadow-sm transition-all duration-300 group-hover:-translate-y-0.5 group-hover:shadow-md group-focus-visible:ring-2 group-focus-visible:ring-ring">
              {r.cover_url ? (
                <img src={r.cover_url} alt="" loading="lazy" decoding="async"
                  className="size-full object-cover transition-transform duration-500 group-hover:scale-[1.03]" />
              ) : (
                <span className="grid size-full place-items-center text-muted-foreground"><Film aria-hidden="true" /></span>
              )}
              <span className="absolute inset-0 grid place-items-center bg-foreground/0 transition-colors duration-300 group-hover:bg-foreground/20">
                <Play aria-hidden="true" className="size-9 rounded-full bg-card/90 p-2 opacity-0 shadow transition-opacity duration-300 group-hover:opacity-100" />
              </span>
            </AspectRatio>
            <span className="flex flex-col gap-1">
              <span className="line-clamp-2 text-sm leading-snug font-medium">{r.hook || `Reel #${r.id}`}</span>
              <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                <Badge variant="plain">{KIND[r.kind] ?? "Clip"}</Badge>
                {at && <span>{when(at)}</span>}
              </span>
            </span>
          </button>
        </DialogTrigger>
        <DialogContent className="max-w-[min(92vw,26rem)] gap-4">
          <DialogHeader>
            <DialogTitle className="leading-snug">{r.hook || `Reel #${r.id}`}</DialogTitle>
            <DialogDescription>
              {KIND[r.kind] ?? "Clip"} #{r.id}{at && `, ${r.status === "published" ? "posted" : "posts"} ${when(at)} IST`}
            </DialogDescription>
          </DialogHeader>
          {r.video_url ? (
            <video src={r.video_url} poster={r.cover_url ?? undefined} controls autoPlay playsInline
              className="aspect-[9/16] max-h-[60vh] w-full rounded-[10px] bg-foreground object-contain" />
          ) : <p className="text-sm text-muted-foreground">No video file.</p>}
          {movable && (
            <div className="flex flex-col gap-2">
              <Label>Post time, IST</Label>
              <div className="flex flex-wrap gap-2">
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="outline" className="flex-1 justify-start font-normal">
                      <CalendarDays aria-hidden="true" />
                      {pick.day.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-0" align="start">
                    <Calendar mode="single" selected={pick.day} disabled={{ before: today }} autoFocus
                      onSelect={(day) => day && setPick({ ...pick, day })} />
                  </PopoverContent>
                </Popover>
                <Select value={String(pick.hour)} onValueChange={(v) => setPick({ ...pick, hour: Number(v) })}>
                  <SelectTrigger className="tnum w-24" aria-label="Hour"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {hours.map((h) => <SelectItem key={h} value={String(h)} className="tnum">{hour(h)}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Select value={String(pick.minute)} onValueChange={(v) => setPick({ ...pick, minute: Number(v) })}>
                  <SelectTrigger className="tnum w-20" aria-label="Minute"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(MINUTES.includes(pick.minute) ? MINUTES : [...MINUTES, pick.minute].sort((a, b) => a - b)).map((m) => (
                      <SelectItem key={m} value={String(m)} className="tnum">:{String(m).padStart(2, "0")}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <p className="text-xs text-muted-foreground">Inside the posting window, {hour(window[0])} to {hour(window[1])}.</p>
            </div>
          )}
          <DialogFooter className="flex-row flex-wrap gap-2 sm:justify-start">
            {movable && (
              <Button disabled={busy || !changed}
                onClick={() => act("reschedule", { at: chosen }, `Reel #${r.id} ${r.status === "approved" ? "scheduled for" : "moved to"} ${when(chosen)}`, false)}>
                <CalendarClock aria-hidden="true" /> {r.status === "approved" ? "Schedule" : "Save time"}
              </Button>
            )}
            {movable && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="outline" disabled={busy}><Send aria-hidden="true" /> Post now</Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Post reel #{r.id} now?</AlertDialogTitle>
                    <AlertDialogDescription>It goes out on the publisher's next run, within a few minutes.</AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel variant="ghost">Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={() => act("post-now", undefined, `Reel #${r.id} posts on the next run`, true)}>
                      Post now
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
            {r.cover_url && (
              <Button variant="outline" asChild><a href={r.cover_url} target="_blank" rel="noreferrer">Open cover</a></Button>
            )}
            {r.permalink && (
              <Button variant="outline" asChild>
                <a href={r.permalink} target="_blank" rel="noreferrer"><ExternalLink aria-hidden="true" /> On Instagram</a>
              </Button>
            )}
            {r.status === "scheduled" && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="ghost" disabled={busy}><Trash2 aria-hidden="true" /> Remove</Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Remove reel #{r.id} from the schedule?</AlertDialogTitle>
                    <AlertDialogDescription>It won't be posted. The video stays on disk, marked as rejected.</AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel variant="ghost">Keep it</AlertDialogCancel>
                    <AlertDialogAction variant="destructive" onClick={() => act("unschedule", undefined, `Reel #${r.id} removed`, true)}>
                      Remove
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  )
}

function CardHead({ title, aside }: { title: string; aside?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 px-5 max-sm:px-4">
      <h2 className="text-base font-semibold">{title}</h2>
      {aside}
    </div>
  )
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground max-sm:mt-2 max-sm:first:mt-0">{k}</dt>
      <dd className="font-medium">{children}</dd>
    </>
  )
}

const sentence = (s: string) => s[0].toUpperCase() + s.slice(1)

function Stat({ label, value, note }: { label: string; value?: string; note: string }) {
  return (
    <Card className="gap-1 px-5 py-4">
      <Label11>{label}</Label11>
      {value === undefined ? (
        <p className="flex h-[1.9rem] items-end text-lg leading-none font-semibold text-muted-foreground">No data yet</p>
      ) : (
        <p className="tnum text-[1.9rem] leading-none font-bold tracking-[-0.02em]">{value}</p>
      )}
      <p className="mt-1.5 text-xs text-muted-foreground">{note}</p>
    </Card>
  )
}

function StatusCheck({ page: p, base, refresh }: { page: Page; base: string; refresh: Refresh }) {
  const answer = (yes: boolean) =>
    send(`${base}/status`, { recommendable: yes }, yes ? "Account Status saved" : `@${p.handle} paused`, refresh)
  return (
    <Card className="gap-4 border-[color-mix(in_oklab,var(--blue)_30%,#fff)] bg-accent p-5" role="region" aria-label="Account Status check">
      <div>
        <p className="font-semibold">Account Status check due</p>
        <p className="mt-1 text-muted-foreground">
          In the Instagram app open Settings, then Account Status, for @{p.handle}.{" "}
          {p.status_checked_at ? `Last checked ${when(p.status_checked_at)}.` : "Not checked before."}
        </p>
      </div>
      <p className="font-semibold">Can this page's content be recommended?</p>
      <div className="flex flex-wrap items-center gap-3">
        <Button className="max-sm:flex-1" onClick={() => answer(true)}>Yes</Button>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" className="max-sm:flex-1">No</Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Pause @{p.handle}?</AlertDialogTitle>
              <AlertDialogDescription>
                Instagram says this page's content cannot be recommended. Pausing stops all posting and moves scheduled
                reels back to approved. Review the last 30 days before you unpause.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel variant="ghost">Cancel</AlertDialogCancel>
              <AlertDialogAction variant="destructive" onClick={() => answer(false)}>Pause the page</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
        <span className="text-sm text-muted-foreground">No pauses the page.</span>
      </div>
    </Card>
  )
}

function Connect({ page: p, base, refresh }: { page: Page; base: string; refresh: Refresh }) {
  const [open, setOpen] = useState(false)
  const [token, setToken] = useState("")
  const [busy, setBusy] = useState(false)
  const id = useId()
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const t = token.trim()
    setToken("") // never kept around, whatever the answer
    setBusy(true)
    if (await send(`${base}/connect`, { token: t }, `@${p.handle} connected`, refresh)) setOpen(false)
    setBusy(false)
  }
  const label = p.connected ? "Reconnect" : "Connect"
  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); setToken("") }}>
      <DialogTrigger asChild>
        <Button variant={p.reconnect ? "default" : "outline"}><KeyRound aria-hidden="true" /> {label}</Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-5">
          <DialogHeader>
            <DialogTitle>{label} @{p.handle}</DialogTitle>
            <DialogDescription>Paste a long lived Instagram access token for this page. It is checked against the account before it is saved.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor={`${id}-token`}>Access token</Label>
            <Input id={`${id}-token`} type="password" value={token} onChange={(e) => setToken(e.target.value)}
              autoComplete="off" spellCheck={false} required aria-describedby={`${id}-help`} />
            <p id={`${id}-help`} className="text-[13px] text-muted-foreground">
              Generate it in the Meta app dashboard, under Instagram API setup, signed in as @{p.handle}. It is never shown again.
            </p>
          </div>
          <DialogFooter>
            <DialogClose asChild><Button type="button" variant="ghost">Cancel</Button></DialogClose>
            <Button type="submit" disabled={!token.trim() || busy}>{busy ? "Checking" : label}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function AddLink({ handle, refresh }: { handle: string; refresh: Refresh }) {
  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState("")
  const [note, setNote] = useState("")
  const [busy, setBusy] = useState(false)
  const id = useId()
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    if (await send("/api/links", { url: url.trim(), page: handle, note: note.trim() }, "Link added. It is fetched on the next run.", refresh)) {
      setOpen(false)
      setUrl("")
      setNote("")
    }
    setBusy(false)
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline"><Link2 aria-hidden="true" /> Add link</Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-5">
          <DialogHeader>
            <DialogTitle>Add a video to @{handle}</DialogTitle>
            <DialogDescription>A YouTube video from one of this page's allowed sources, or any video you have permission for.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor={`${id}-url`}>YouTube link</Label>
            <Input id={`${id}-url`} type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=" required />
          </div>
          <div className="grid gap-2">
            <Label htmlFor={`${id}-note`}>One off permission note <span className="font-normal text-muted-foreground">(optional)</span></Label>
            <Input id={`${id}-note`} value={note} onChange={(e) => setNote(e.target.value)} aria-describedby={`${id}-note-help`}
              placeholder="Guest sent it on email, 22 Oct" />
            <p id={`${id}-note-help`} className="text-[13px] text-muted-foreground">
              Only for a video outside the allowed sources: who allowed it and how.
            </p>
          </div>
          <DialogFooter>
            <DialogClose asChild><Button type="button" variant="ghost">Cancel</Button></DialogClose>
            <Button type="submit" disabled={!url.trim() || busy}>{busy ? "Adding" : "Add link"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
