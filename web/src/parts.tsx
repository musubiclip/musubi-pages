import type { ReactNode } from "react"

import type { Tone } from "@/api"

export const toneDot: Record<Tone, string> = {
  ok: "bg-success",
  wait: "bg-brand",
  pending: "bg-background ring-[1.5px] ring-input ring-inset",
  ink: "bg-foreground",
  neutral: "bg-dim",
}

export function Header({ title, lede, children }: { title: ReactNode; lede?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[1.75rem] leading-tight font-bold tracking-[-0.02em] break-words md:text-[2rem]">{title}</h1>
        {lede && <div className="mt-2 max-w-[46em] text-base text-muted-foreground">{lede}</div>}
      </div>
      {children}
    </div>
  )
}

// Small capital label over a block of facts.
export function Label11({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <p id={id} className="mb-1.5 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
      {children}
    </p>
  )
}

export function Empty({ icon, title, line }: { icon: ReactNode; title: string; line: string }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border bg-card px-6 py-14 text-center shadow-card">
      <div className="grid size-12 place-items-center rounded-full bg-success-soft [&_svg]:size-6">{icon}</div>
      <p className="text-lg font-semibold">{title}</p>
      <p className="max-w-sm text-muted-foreground">{line}</p>
    </div>
  )
}
