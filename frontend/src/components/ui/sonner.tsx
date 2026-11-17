"use client"

import { useSyncExternalStore } from "react"
import { Toaster as Sonner, type ToasterProps } from "sonner"
import { CircleCheckIcon, InfoIcon, TriangleAlertIcon, OctagonXIcon, Loader2Icon } from "lucide-react"

// The app's theme is the `dark` class on <html> (index.html or a toggle), never the viewer's OS setting.
const subscribeToDocumentTheme = (onChange: () => void) => {
  const observer = new MutationObserver(onChange)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] })
  return () => observer.disconnect()
}

const getDocumentTheme = (): ToasterProps["theme"] =>
  document.documentElement.classList.contains("dark") ? "dark" : "light"

const getServerTheme = (): ToasterProps["theme"] => "light"

const Toaster = ({ ...props }: ToasterProps) => {
  const theme = useSyncExternalStore(subscribeToDocumentTheme, getDocumentTheme, getServerTheme)

  return (
    <Sonner
      theme={theme}
      // Top-centre, pushed below the 56px sticky header: toasts never sit on top of the page's action
      // buttons (bottom of the page) or the mobile bottom nav, and the header stays clickable.
      position="top-center"
      offset={{ top: 68 }}
      mobileOffset={{ top: 68, left: 12, right: 12 }}
      closeButton
      duration={4500}
      visibleToasts={3}
      className="toaster group"
      icons={{
        success: (
          <CircleCheckIcon className="size-4" />
        ),
        info: (
          <InfoIcon className="size-4" />
        ),
        warning: (
          <TriangleAlertIcon className="size-4" />
        ),
        error: (
          <OctagonXIcon className="size-4" />
        ),
        loading: (
          <Loader2Icon className="size-4 animate-spin" />
        ),
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "cn-toast",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
