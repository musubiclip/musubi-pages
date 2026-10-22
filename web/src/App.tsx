import { useCallback, useEffect, useState, type ReactNode } from "react"
import { CircleAlert, Inbox, Menu, RotateCw } from "lucide-react"
import { toast } from "sonner"
import { cn } from "cn"

import { getState, pageStatus, post, type Draft, type Page, type State } from "@/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { PageView } from "@/PageView"
import { toneDot } from "@/parts"
import { Problems } from "@/Problems"
import { Review } from "@/Review"

type Route = { view: "review" } | { view: "problems" } | { view: "page"; handle: string }

function parse(hash: string): Route {
  const [, view, handle] = hash.replace(/^#/, "").split("/")
  if (view === "problems") return { view }
  if (view === "page" && handle) return { view, handle: decodeURIComponent(handle) }
  return { view: "review" }
}

function useRoute() {
  const [route, setRoute] = useState(() => parse(location.hash))
  useEffect(() => {
    const on = () => {
      setRoute(parse(location.hash))
      window.scrollTo(0, 0)
    }
    addEventListener("hashchange", on)
    return () => removeEventListener("hashchange", on)
  }, [])
  return route
}

function useAppState() {
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [at, setAt] = useState<Date | null>(null)
  const refresh = useCallback(async () => {
    try {
      setState(await getState())
      setError(null)
      setAt(new Date())
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])
  useEffect(() => {
    refresh()
    const visible = () => document.visibilityState === "visible"
    const id = setInterval(() => visible() && refresh(), 30_000)
    const onShow = () => visible() && refresh()
    document.addEventListener("visibilitychange", onShow)
    return () => {
      clearInterval(id)
      document.removeEventListener("visibilitychange", onShow)
    }
  }, [refresh])
  return { state, error, at, refresh }
}

function Mark() {
  return (
    <svg viewBox="0 0 32 32" className="size-7 shrink-0" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="var(--ink)" />
      <circle cx="12.5" cy="16" r="6" fill="none" stroke="var(--blue)" strokeWidth="3" />
      <circle cx="19.5" cy="16" r="6" fill="none" stroke="var(--green)" strokeWidth="3" />
    </svg>
  )
}

function Wordmark() {
  return (
    <a href="#/" className="flex items-center gap-2.5 rounded-lg text-[17px] font-bold tracking-[-0.02em]">
      <Mark />
      <span>
        Musubi <span className="font-semibold text-muted-foreground">Pages</span>
      </span>
    </a>
  )
}

function Count({ n, strong }: { n: number; strong?: boolean }) {
  return (
    <span
      className={cn(
        "tnum ml-auto inline-grid h-5 min-w-6 place-items-center rounded-full px-1.5 text-[11.5px] font-semibold",
        strong && n > 0 ? "bg-foreground text-background" : "bg-muted text-muted-foreground",
      )}
    >
      {n}
    </span>
  )
}

function NavItem({ href, current, children }: { href: string; current: boolean; children: ReactNode }) {
  return (
    <a
      href={href}
      aria-current={current ? "page" : undefined}
      className={cn(
        "flex min-h-[38px] items-center gap-2.5 rounded-[9px] px-2.5 text-sm font-medium max-lg:min-h-11",
        current ? "bg-muted font-semibold" : "hover:bg-muted/70",
      )}
    >
      {children}
    </a>
  )
}

function Nav({ state, drafts, route, at, error }: {
  state: State | null; drafts: number; route: Route; at: Date | null; error: string | null
}) {
  return (
    <div className="flex h-full flex-col gap-1">
      <div className="px-1.5 pt-0.5 pb-4 max-lg:hidden">
        <Wordmark />
      </div>
      <nav aria-label="Main" className="flex min-h-0 flex-1 flex-col gap-1">
        <NavItem href="#/" current={route.view === "review"}>
          <Inbox className="size-[18px]" aria-hidden="true" />
          Review
          <Count n={drafts} strong />
        </NavItem>
        <p className="px-2.5 pt-4 pb-1.5 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
          Pages
        </p>
        <div className="-mx-1 flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-1">
          {state
            ? state.pages.map((p) => {
                const s = pageStatus(p)
                return (
                  <NavItem key={p.handle} href={`#/page/${p.handle}`}
                    current={route.view === "page" && route.handle === p.handle}>
                    <span className={cn("size-2 shrink-0 rounded-full", toneDot[s.tone])} aria-hidden="true" />
                    <span className="min-w-0 truncate">@{p.handle}</span>
                    <span className="ml-auto shrink-0 text-xs font-medium text-muted-foreground">{s.word}</span>
                  </NavItem>
                )
              })
            : [0, 1].map((i) => <Skeleton key={i} className="mx-2.5 my-2 h-5" />)}
        </div>
        <Separator className="my-2" />
        <NavItem href="#/problems" current={route.view === "problems"}>
          <CircleAlert className="size-[18px]" aria-hidden="true" />
          Problems
          <Count n={state?.problems.length ?? 0} />
        </NavItem>
      </nav>
      <p className="px-2.5 pt-2 text-xs text-muted-foreground" aria-live="polite">
        {error && state ? "Refresh failed, trying again" : at ? `Updated ${at.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}` : "Loading"}
      </p>
    </div>
  )
}

function Loading() {
  return (
    <div aria-busy="true" aria-label="Loading" className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Skeleton className="h-9 w-48" />
        <Skeleton className="h-5 w-80 max-w-full" />
      </div>
      {[0, 1].map((i) => (
        <Card key={i} className="grid gap-5 p-5 md:grid-cols-[270px_minmax(0,1fr)]">
          <Skeleton className="aspect-[9/16] w-full" />
          <div className="flex flex-col gap-3">
            <Skeleton className="h-7 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="mt-4 h-32 w-full" />
          </div>
        </Card>
      ))}
    </div>
  )
}

function LoadError({ message, retry }: { message: string; retry: () => void }) {
  return (
    <Card className="max-w-xl gap-3 border-foreground p-5" role="alert">
      <p className="text-base font-semibold">Could not load the pages</p>
      <p className="text-muted-foreground">{message}</p>
      <Button variant="outline" className="w-fit" onClick={retry}>
        <RotateCw aria-hidden="true" /> Try again
      </Button>
    </Card>
  )
}

export default function App() {
  const route = useRoute()
  const { state, error, at, refresh } = useAppState()
  const [hidden, setHidden] = useState<Set<number>>(new Set())
  const [menu, setMenu] = useState(false)
  useEffect(() => setMenu(false), [route])

  // Optimistic: the draft leaves the list at once and comes back if the server refuses.
  const act = useCallback(async (d: Draft, path: string, body: object, done: string) => {
    setHidden((h) => new Set(h).add(d.id))
    try {
      await post(`/api/clips/${d.id}/${path}`, body)
      toast.success(done)
      refresh()
    } catch (e) {
      setHidden((h) => {
        const next = new Set(h)
        next.delete(d.id)
        return next
      })
      toast.error((e as Error).message)
    }
  }, [refresh])

  const drafts = state?.drafts.filter((d) => !hidden.has(d.id)) ?? []
  const page: Page | undefined = route.view === "page" ? state?.pages.find((p) => p.handle === route.handle) : undefined
  const nav = <Nav state={state} drafts={drafts.length} route={route} at={at} error={error} />

  let body: ReactNode
  if (!state) body = error ? <LoadError message={error} retry={refresh} /> : <Loading />
  else if (route.view === "problems") body = <Problems problems={state.problems} />
  else if (route.view === "page")
    body = page ? (
      <PageView key={page.handle} page={page} refresh={refresh} />
    ) : (
      <LoadError message={`There is no page called @${route.handle} in pages.toml.`} retry={refresh} />
    )
  else body = <Review pages={state.pages} drafts={drafts} act={act} />

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[248px_minmax(0,1fr)] lg:gap-4 lg:p-3">
      <aside className="sticky top-3 hidden h-[calc(100dvh-1.5rem)] rounded-xl border bg-card p-3.5 shadow-card lg:block">
        {nav}
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-ground/95 px-2 backdrop-blur lg:hidden">
        <Button variant="ghost" size="icon" aria-label="Open menu" onClick={() => setMenu(true)}>
          <Menu className="size-5" />
        </Button>
        <Wordmark />
      </header>
      <Sheet open={menu} onOpenChange={setMenu}>
        <SheetContent side="left" className="w-[86%] max-w-80 gap-0 p-3.5 pt-4">
          <SheetTitle className="px-1.5 pb-4">
            <Wordmark />
          </SheetTitle>
          <SheetDescription className="sr-only">Review, pages and problems</SheetDescription>
          {nav}
        </SheetContent>
      </Sheet>

      <main className="mx-auto w-full max-w-[1080px] min-w-0 px-4 pt-6 pb-16 lg:px-6 lg:pt-5">{body}</main>
    </div>
  )
}
