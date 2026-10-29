"use client";

import { useId, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { cx } from "./cx";

const CONTROL =
  "w-full rounded-lg border bg-surface-container-low px-3 text-[14px] text-white placeholder:text-text-subtle transition-colors focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-0 disabled:opacity-60";

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: (p: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
  className?: string;
}) {
  const id = useId();
  const descId = hint || error ? `${id}-d` : undefined;
  return (
    <div className={cx("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-[13px] font-medium text-on-surface">
        {label}
      </label>
      {children({ id, "aria-describedby": descId, "aria-invalid": error ? true : undefined })}
      {(hint || error) && (
        <p id={descId} className={cx("text-[12.5px] leading-5", error ? "text-error" : "text-on-surface-variant")}>
          {error || hint}
        </p>
      )}
    </div>
  );
}

export function Input({ className, invalid, ...rest }: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }) {
  return <input className={cx(CONTROL, "h-10", invalid ? "border-error/70" : "border-border-strong hover:border-outline", className)} {...rest} />;
}

export function Textarea({ className, invalid, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }) {
  return <textarea className={cx(CONTROL, "py-2.5 leading-6 resize-y min-h-[120px]", invalid ? "border-error/70" : "border-border-strong hover:border-outline", className)} {...rest} />;
}
