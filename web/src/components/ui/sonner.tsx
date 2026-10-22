import { Toaster as Sonner, type ToasterProps } from "sonner"
import { CircleAlertIcon, CircleCheckIcon, InfoIcon, Loader2Icon } from "lucide-react"

// Calm toast: ink with white text. The words carry the meaning, not a colour.
const Toaster = ({ ...props }: ToasterProps) => (
  <Sonner
    theme="light"
    className="toaster group"
    icons={{
      success: <CircleCheckIcon className="size-4 text-success" />,
      info: <InfoIcon className="size-4" />,
      warning: <CircleAlertIcon className="size-4" />,
      error: <CircleAlertIcon className="size-4" />,
      loading: <Loader2Icon className="size-4 animate-spin" />,
    }}
    style={
      {
        "--normal-bg": "var(--ink)",
        "--normal-text": "#fff",
        "--normal-border": "var(--ink)",
        "--border-radius": "10px",
        fontFamily: "var(--font-sans)",
      } as React.CSSProperties
    }
    toastOptions={{ className: "shadow-float! font-medium!" }}
    {...props}
  />
)

export { Toaster }
