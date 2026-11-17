import { isValidElement } from "react"
import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/*
 * VIDHI buttons. Each shape has one job, so a person can tell at a glance what a button will do:
 *   default     the main action on a screen: a luminous disc with a thin orbiting edge
 *   outline     a second action: a cut-corner plate with a fine two-tone edge
 *   secondary   the same plate, for lists of equal choices
 *   ghost       the quiet action: a lamp that glows when you reach for it
 *   destructive deleting or ending something: an ember-red plate, so it is never clicked by accident
 */
const buttonVariants = cva(
  "group/button relative inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap text-sm outline-none select-none disabled:pointer-events-none disabled:opacity-60 aria-invalid:ring-3 aria-invalid:ring-destructive/30 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "btn-orbit rounded-full focus-visible:ring-4 focus-visible:ring-primary/40",
        outline: "btn-plate",
        secondary: "btn-plate",
        ghost: "btn-lamp rounded-full",
        destructive: "btn-ember",
        link: "rounded-sm text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3",
        xs: "h-7 px-3 text-xs [&_svg:not([class*='size-'])]:size-3.5",
        sm: "h-8 px-3.5 text-[0.85rem] [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-11 px-6 text-base [&_svg:not([class*='size-'])]:size-5",
        icon: "size-9",
        "icon-xs": "size-7 [&_svg:not([class*='size-'])]:size-3.5",
        "icon-sm": "size-8",
        "icon-lg": "size-11",
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
  nativeButton,
  render,
  loading = false,
  disabled,
  children,
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants> & { loading?: boolean }) {
  return (
    <ButtonPrimitive
      data-slot="button"
      render={render}
      // Native unless render swaps in a non-<button> element (e.g. <Link/>).
      nativeButton={
        nativeButton ??
        (render == null || (isValidElement(render) && render.type === "button"))
      }
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    >
      {loading && <span className="spinner-ring size-4" aria-hidden="true" />}
      {children as React.ReactNode}
    </ButtonPrimitive>
  )
}

export { Button, buttonVariants }
