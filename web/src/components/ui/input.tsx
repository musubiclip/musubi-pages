import * as React from "react"
import { cn } from "cn"

// Calm field: white, strong outline, 10px corners, blue focus with a pale blue halo.
const field =
  "w-full min-w-0 rounded-[10px] border border-input bg-background px-3.5 text-[15px] text-foreground transition-[border-color,box-shadow] outline-none placeholder:text-dim focus-visible:border-brand focus-visible:shadow-[0_0_0_3px_var(--brand-soft)] focus-visible:outline-none disabled:cursor-not-allowed disabled:border-border disabled:bg-muted disabled:text-dim aria-invalid:border-foreground"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(field, "h-[42px] max-md:h-11", className)}
      {...props}
    />
  )
}

export { Input, field }
