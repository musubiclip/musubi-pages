import * as React from "react"
import { cn } from "cn"

import { field } from "@/components/ui/input"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(field, "flex field-sizing-content min-h-24 py-2.5 leading-relaxed", className)}
      {...props}
    />
  )
}

export { Textarea }
