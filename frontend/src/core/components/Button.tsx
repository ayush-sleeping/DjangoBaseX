/**
 * Buttons (FRONTEND_PLATFORM § 13). Token variants only: a variant is a fill and its foreground,
 * never a palette colour, so dark mode and a re-brand reach every button at once.
 */
import type { ButtonHTMLAttributes, ComponentType, ReactNode, SVGProps } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive" | "link";
export type ButtonSize = "sm" | "md";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-foreground hover:bg-primary/90",
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border",
  ghost: "text-foreground hover:bg-accent hover:text-accent-foreground",
  destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
  link: "text-foreground underline underline-offset-4 hover:text-muted-foreground",
};
const SIZE: Record<ButtonSize, string> = {
  sm: "h-8 px-2.5 text-sm",
  md: "h-(--control-h) px-3 text-sm",
};
const BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50";

export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md", extra = ""): string {
  return [BASE, VARIANT[variant], variant === "link" ? "" : SIZE[size], extra].filter(Boolean).join(" ");
}

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shown instead of children while true; the button is disabled. */
  pending?: boolean;
  pendingLabel?: ReactNode;
};

export function Button({ variant, size, pending, pendingLabel, className, children, disabled, type, ...rest }: ButtonProps) {
  return (
    <button
      type={type ?? "button"}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
      className={buttonClass(variant, size, className)}
      {...rest}
    >
      {pending && pendingLabel ? pendingLabel : children}
    </button>
  );
}

type Icon = ComponentType<SVGProps<SVGSVGElement>>;

/** An icon-only button. `label` is required: it is the accessible name and the tooltip. */
export function IconButton({
  icon: IconComponent,
  label,
  variant = "ghost",
  className,
  ...rest
}: Omit<ButtonProps, "children" | "aria-label"> & { icon: Icon; label: string }) {
  return (
    <Button variant={variant} size="sm" aria-label={label} title={label} className={`w-8 px-0 ${className ?? ""}`} {...rest}>
      <IconComponent aria-hidden className="size-4" />
    </Button>
  );
}
