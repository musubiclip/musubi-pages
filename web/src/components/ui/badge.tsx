import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"
import { Slot } from "radix-ui"

// Calm status pill: ink text on a tint with a dot in the tone's colour. A status always carries its word.
const badgeVariants = cva(
  "inline-flex h-[22px] w-fit shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[11.5px] font-semibold whitespace-nowrap before:size-1.5 before:shrink-0 before:rounded-full before:content-[''] [&>svg]:size-3",
  {
    variants: {
      variant: {
        neutral: "bg-muted text-foreground before:bg-dim",
        ok: "bg-success-soft text-foreground before:bg-success-ink",
        wait: "bg-brand-soft text-foreground before:bg-brand",
        pending: "bg-background text-foreground ring-1 ring-input ring-inset before:bg-brand",
        ink: "bg-foreground text-background before:bg-background",
        plain: "bg-muted text-foreground before:hidden",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  }
)

function Badge({
  className,
  variant = "neutral",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
