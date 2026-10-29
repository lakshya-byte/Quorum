import Link from "next/link";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";
import Icon, { type IconName } from "./Icon";
import { cx } from "./cx";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANT: Record<Variant, string> = {
  primary: "bg-primary text-[#04120c] hover:bg-primary-strong shadow-[0_0_0_1px_rgba(16,185,129,0.4),0_6px_20px_-6px_rgba(16,185,129,0.55)]",
  secondary: "bg-surface-container-high text-on-surface border border-border-strong hover:bg-surface-bright hover:border-outline",
  ghost: "text-on-surface-variant hover:text-white hover:bg-surface-container-high",
  danger: "bg-error/10 text-error border border-error/40 hover:bg-error/20",
};
const SIZE: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5 rounded-md",
  md: "h-10 px-4 text-[14px] gap-2 rounded-lg",
  lg: "h-12 px-6 text-[15px] gap-2 rounded-lg",
};

export function buttonClass(variant: Variant = "primary", size: Size = "md", extra?: string) {
  return cx(
    "focus-ring inline-flex items-center justify-center font-semibold whitespace-nowrap select-none transition-colors duration-150",
    "disabled:opacity-50 disabled:pointer-events-none aria-disabled:opacity-50 aria-disabled:pointer-events-none",
    VARIANT[variant],
    SIZE[size],
    extra
  );
}

type Common = { variant?: Variant; size?: Size; icon?: IconName; iconRight?: IconName; loading?: boolean; className?: string; children?: ReactNode };

export function Button({ variant, size, icon, iconRight, loading, className, children, disabled, type = "button", ...rest }: Common & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type={type} disabled={disabled || loading} aria-busy={loading || undefined} className={buttonClass(variant, size, className)} {...rest}>
      {loading ? <Icon name="loader" className="animate-spin" /> : icon ? <Icon name={icon} /> : null}
      {children}
      {iconRight && !loading ? <Icon name={iconRight} /> : null}
    </button>
  );
}

export function LinkButton({
  href,
  variant,
  size,
  icon,
  iconRight,
  className,
  children,
  external,
  ...rest
}: Omit<Common, "loading"> & { href: string; external?: boolean } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  const cls = buttonClass(variant, size, className);
  const inner = (
    <>
      {icon ? <Icon name={icon} /> : null}
      {children}
      {iconRight ? <Icon name={iconRight} /> : null}
    </>
  );
  if (external) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={cls} {...rest}>
        {inner}
      </a>
    );
  }
  return (
    <Link href={href} className={cls} {...rest}>
      {inner}
    </Link>
  );
}
