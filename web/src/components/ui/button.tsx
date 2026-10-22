import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"
import { Slot } from "radix-ui"

// Calm skin: 40px (44px on phones), 10px corners, semibold. Primary is ink; a destructive act is an ink outline.
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-[10px] border border-transparent text-sm font-semibold whitespace-nowrap transition-colors outline-none select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:border-border disabled:bg-muted disabled:text-dim [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-[color-mix(in_oklab,var(--ink)_86%,#fff)]",
        outline: "border-input bg-background hover:bg-muted",
        secondary: "bg-secondary text-secondary-foreground hover:bg-[color-mix(in_oklab,var(--ink)_9%,#fff)]",
        ghost: "hover:bg-muted",
        destructive: "border-foreground bg-background text-foreground hover:bg-muted",
        link: "h-auto! px-0! underline underline-offset-4 hover:text-muted-foreground",
      },
      size: {
        default: "h-10 px-4 max-md:h-11",
        sm: "h-8 rounded-lg px-3 text-[13px] max-md:h-10",
        lg: "h-11 px-5 text-[15px]",
        icon: "size-10 max-md:size-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
