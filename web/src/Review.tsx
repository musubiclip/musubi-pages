import { useId, useState } from "react"
import { Check, CircleAlert, CircleCheck, ExternalLink, VideoOff, X } from "lucide-react"
import { cn } from "cn"

import { hashtags, when, type Draft, type Page } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Empty, Header, Label11 } from "@/parts"

type Act = (d: Draft, path: string, body: object, done: string) => Promise<void>

const MAX_CHARS = 2200
const MAX_TAGS = 5

export function Review({ pages, drafts, act }: { pages: Page[]; drafts: Draft[]; act: Act }) {
  const groups = pages.map((p) => ({ page: p, drafts: drafts.filter((d) => d.page === p.handle) }))
    .filter((g) => g.drafts.length)
  const n = drafts.length
  return (
    <>
      <Header
        title="Review"
        lede={n ? `${n} ${n === 1 ? "draft" : "drafts"} across ${groups.length} ${groups.length === 1 ? "page" : "pages"}. Approve, edit the caption, or reject with a reason.`
          : undefined}
      />
      {n === 0 ? (
        <Empty icon={<CircleCheck />} title="Nothing to review"
          line="New drafts show up here as the pipelines cut them. Come back after the next run." />
      ) : (
        <div className="flex flex-col gap-10">
          {groups.map(({ page, drafts }) => (
            <section key={page.handle} aria-labelledby={`g-${page.handle}`} className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <h2 id={`g-${page.handle}`} className="text-lg font-semibold tracking-[-0.01em]">@{page.handle}</h2>
                <Badge variant="plain">{page.pipeline === "clips" ? "Clip pipeline" : "Script pipeline"}</Badge>
                <div className="flex flex-1 items-center gap-3 text-sm max-sm:basis-full">
                  <span className="text-muted-foreground">{drafts.length} to review</span>
                  <a href={`#/page/${page.handle}`} className="ml-auto font-medium underline underline-offset-4 hover:text-muted-foreground">
                    Page details
                  </a>
                </div>
              </div>
              {drafts.map((d) => <DraftCard key={d.id} d={d} act={act} />)}
            </section>
          ))}
        </div>
      )}
    </>
  )
}

function DraftCard({ d, act }: { d: Draft; act: Act }) {
  const [caption, setCaption] = useState(d.caption)
  const id = useId()
  const chars = caption.length
  const tags = hashtags(caption)
  const empty = !caption.trim()
  const blocked = empty || chars > MAX_CHARS || tags > MAX_TAGS
  const cards = d.layer?.cards ?? []

  return (
    <Card className="gap-0 p-0">
      <article aria-labelledby={`${id}-hook`} className="grid gap-5 p-4 sm:p-5 md:grid-cols-[270px_minmax(0,1fr)] md:gap-7">
        <div className="md:sticky md:top-5 md:self-start">
          {d.video_url ? (
            <video src={d.video_url} controls preload="metadata" playsInline
              aria-label={`Reel for @${d.page}: ${d.hook ?? "no hook"}`}
              className="aspect-[9/16] w-full rounded-[10px] bg-foreground object-cover" />
          ) : (
            <div className="grid aspect-[9/16] w-full place-items-center rounded-[10px] bg-muted text-muted-foreground">
              <span className="flex flex-col items-center gap-2 text-sm"><VideoOff aria-hidden="true" /> No video file</span>
            </div>
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-6">
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="plain">{({ script: "Script reel", montage: "Montage", rapidfire: "Rapid fire" } as Record<string, string>)[d.kind] ?? "Clip"}</Badge>
              <span className="tnum">#{d.id}</span>
              {d.created_at && <span>· made {when(d.created_at)}</span>}
            </div>
            <h3 id={`${id}-hook`} className="text-[1.375rem] leading-snug font-bold tracking-[-0.015em] text-balance md:text-2xl">
              {d.hook || <span className="text-muted-foreground">No hook</span>}
            </h3>
            {d.flags.length > 0 && (
              <ul className="flex flex-col gap-1.5" aria-label="Restricted topic flags">
                {d.flags.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm font-medium">
                    <Badge variant="ink" className="mt-px">Flag</Badge>
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {d.layer && (
            <div>
              <Label11>Original layer</Label11>
              <dl className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
                <dt className="text-muted-foreground">Intro</dt>
                <dd>{d.layer.intro}</dd>
                <dt className="text-muted-foreground">Takeaway</dt>
                <dd>{d.layer.takeaway}</dd>
              </dl>
              {cards.length > 0 && (
                <ul className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3" aria-label="Context cards">
                  {cards.map((c, i) => (
                    <li key={i} className="rounded-[10px] border bg-background px-3 py-2 text-[13px] leading-snug">
                      <span className="font-semibold">{c.title}</span>
                      <span className="block text-muted-foreground">{c.body}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {d.claims.length > 0 && (
            <div>
              <Label11>Claims to check</Label11>
              <ol className="list-decimal space-y-1 pl-5 text-sm marker:font-semibold marker:text-muted-foreground">
                {d.claims.map((c, i) => <li key={i} className="pl-1">{c}</li>)}
              </ol>
            </div>
          )}

          <div className="grid gap-x-6 gap-y-5 text-sm sm:grid-cols-2">
            {d.credits.length > 0 && (
              <div className="min-w-0">
                <Label11>Credits</Label11>
                <ul className="space-y-1">
                  {d.credits.map((c, i) => (
                    <li key={i} className="break-words">
                      {c.url ? (
                        <a href={c.url} target="_blank" rel="noreferrer" className="underline underline-offset-4 hover:text-muted-foreground">
                          {c.text}
                        </a>
                      ) : c.text}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(d.source || d.note || d.kind === "clip") && <div className="min-w-0">
              <Label11>{d.source ? "Source" : "Permission"}</Label11>
              {d.source ? (
                <div className="space-y-1">
                  <p>
                    <a href={d.source.url} target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-4">{d.source.name}</a>
                    <span className="text-muted-foreground"> · {d.source.permission}</span>
                  </p>
                  <p className="flex flex-wrap gap-x-4 gap-y-1">
                    {d.source.proof && <Ext href={d.source.proof}>Proof</Ext>}
                    {d.source.instagram && <Ext href={d.source.instagram}>Check they have not posted it</Ext>}
                  </p>
                </div>
              ) : d.note ? (
                <p>One off video: <span className="text-muted-foreground">{d.note}</span></p>
              ) : (
                <p className="text-muted-foreground">No source recorded</p>
              )}
            </div>}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-caption`}>Caption</Label>
            <Textarea id={`${id}-caption`} value={caption} onChange={(e) => setCaption(e.target.value)}
              aria-describedby={`${id}-count`} aria-invalid={blocked || undefined} className="min-h-40" />
            <div id={`${id}-count`} className="tnum flex flex-wrap justify-between gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-live="polite">
              <Counter over={chars > MAX_CHARS}>{chars} / {MAX_CHARS} characters</Counter>
              <Counter over={tags > MAX_TAGS}>{tags} / {MAX_TAGS} hashtags</Counter>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t pt-5">
            <Button disabled={blocked} className="max-sm:flex-1"
              onClick={() => act(d, "approve", { caption }, `Approved for @${d.page}`)}>
              <Check aria-hidden="true" /> Approve
            </Button>
            <RejectDialog d={d} act={act} />
            {empty && <span className="text-xs font-semibold">Add a caption to approve</span>}
          </div>
        </div>
      </article>
    </Card>
  )
}

function Counter({ over, children }: { over: boolean; children: React.ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1", over && "font-bold text-foreground")}>
      {over && <CircleAlert className="size-3.5" aria-hidden="true" />}
      {children}
      {over && " (over the limit)"}
    </span>
  )
}

function Ext({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium underline underline-offset-4 hover:text-muted-foreground">
      {children} <ExternalLink className="size-3.5" aria-hidden="true" />
    </a>
  )
}

function RejectDialog({ d, act }: { d: Draft; act: Act }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")
  const id = useId()
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!reason.trim()) return
    setOpen(false)
    act(d, "reject", { reason }, `Rejected #${d.id}`)
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" className="max-sm:flex-1"><X aria-hidden="true" /> Reject</Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-5">
          <DialogHeader>
            <DialogTitle>Reject this {d.kind === "script" ? "reel" : "clip"}?</DialogTitle>
            <DialogDescription>It will not be posted. The reason is saved with it, so later batches can improve.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor={`${id}-reason`}>Reason</Label>
            <Textarea id={`${id}-reason`} value={reason} onChange={(e) => setReason(e.target.value)} required
              placeholder="Off topic, weak hook, wrong facts" className="min-h-24" />
          </div>
          <DialogFooter>
            <DialogClose asChild><Button type="button" variant="ghost">Cancel</Button></DialogClose>
            <Button type="submit" variant="destructive" disabled={!reason.trim()}>Reject {d.kind === "script" ? "reel" : "clip"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
