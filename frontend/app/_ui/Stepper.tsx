import Icon from "./Icon";
import { cx } from "./cx";

export function Stepper({ steps, current, onSelect }: { steps: string[]; current: number; onSelect?: (i: number) => void }) {
  return (
    <ol className="flex items-center gap-2 sm:gap-3" aria-label="Progress">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        const clickable = done && onSelect;
        const body = (
          <>
            <span
              className={cx(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-[12px] font-semibold transition-colors",
                done && "border-primary bg-primary text-[#04120c]",
                active && "border-primary text-primary bg-primary/10",
                !done && !active && "border-border-strong text-text-subtle"
              )}
            >
              {done ? <Icon name="check" size={14} strokeWidth={2.5} /> : i + 1}
            </span>
            <span className={cx("text-[13px] font-medium", active ? "text-white" : done ? "text-on-surface" : "text-text-subtle", !active && "hidden sm:inline")}>{label}</span>
          </>
        );
        return (
          <li key={label} aria-current={active ? "step" : undefined} className={cx("flex items-center gap-2 sm:gap-3", i < steps.length - 1 && "flex-1")}>
            {clickable ? (
              <button type="button" onClick={() => onSelect(i)} className="focus-ring flex items-center gap-2 rounded-md">
                {body}
              </button>
            ) : (
              <span className="flex items-center gap-2">{body}</span>
            )}
            {i < steps.length - 1 && <span aria-hidden className={cx("h-px flex-1 min-w-4", done ? "bg-primary/60" : "bg-border-strong")} />}
          </li>
        );
      })}
    </ol>
  );
}
