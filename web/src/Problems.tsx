import { ShieldCheck } from "lucide-react"

import { kindLabel, when, type Problem } from "@/api"
import { Card } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Empty, Header } from "@/parts"

export function Problems({ problems }: { problems: Problem[] }) {
  return (
    <>
      <Header title="Problems" lede="The last 7 days, newest first. A repeat shows once, with how many times it happened." />
      {problems.length === 0 ? (
        <Empty icon={<ShieldCheck />} title="No problems this week" line="Failed clips, skipped videos and publishing errors show up here." />
      ) : (
        <Card className="gap-0 py-0">
          <Table className="max-md:hidden">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-36 pl-5">When</TableHead>
                <TableHead className="w-40">Page</TableHead>
                <TableHead className="w-44">Kind</TableHead>
                <TableHead>Detail</TableHead>
                <TableHead className="w-20 pr-5 text-right">Count</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {problems.map((p, i) => (
                <TableRow key={i}>
                  <TableCell className="tnum pl-5 whitespace-nowrap text-muted-foreground">{when(p.at)}</TableCell>
                  <TableCell className="whitespace-nowrap">{p.page ? `@${p.page}` : "All pages"}</TableCell>
                  <TableCell className="font-semibold whitespace-nowrap">{kindLabel(p.kind)}</TableCell>
                  <TableCell className="break-words [overflow-wrap:anywhere]">{p.detail || "No detail"}</TableCell>
                  <TableCell className="tnum pr-5 text-right font-semibold">{p.count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <ul className="divide-y md:hidden">
            {problems.map((p, i) => (
              <li key={i} className="flex flex-col gap-1 px-4 py-3.5 text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-semibold">{kindLabel(p.kind)}</span>
                  <span className="tnum shrink-0 text-xs text-muted-foreground">
                    {when(p.at)}{p.count > 1 && <span className="ml-2 font-semibold text-foreground">{p.count} times</span>}
                  </span>
                </div>
                <span className="text-muted-foreground">{p.page ? `@${p.page}` : "All pages"}</span>
                <span className="[overflow-wrap:anywhere]">{p.detail || "No detail"}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  )
}
