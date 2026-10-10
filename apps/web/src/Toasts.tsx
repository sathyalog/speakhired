import { dismiss, useToasts } from "./toast";

const ICON = {
  warning: "M12 9v4m0 4h.01M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  error: "M12 8v5m0 3h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
  info: "M12 11v5m0-8h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
} as const;
const STYLE = {
  warning: "border-warning/60 [--tone:var(--color-warning)]",
  error: "border-error/60 [--tone:var(--color-error)]",
  info: "border-info/60 [--tone:var(--color-info)]",
} as const;

/** Floating notice tiles, bottom right. Each one counts down and disappears after 10 seconds. */
export function Toasts() {
  const toasts = useToasts();
  return (
    <div className="toast toast-end toast-bottom z-50 max-w-sm" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} role="status" className={`relative w-80 overflow-hidden rounded-box border bg-base-100 p-4 pr-10 text-left shadow-lg ${STYLE[t.tone]}`}>
          <div className="flex gap-3">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--tone)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="mt-0.5 shrink-0"><path d={ICON[t.tone]} /></svg>
            <div><div className="font-medium leading-snug">{t.title}</div><p className="mt-0.5 text-sm text-base-content/70">{t.body}</p></div>
          </div>
          <button className="btn btn-ghost btn-xs btn-circle absolute right-2 top-2" aria-label="Dismiss" onClick={() => dismiss(t.id)}>✕</button>
          <span className="toast-timer absolute inset-x-0 bottom-0 h-1 origin-left" style={{ background: "var(--tone)", animationDuration: `${t.ttl}ms` }} />
        </div>
      ))}
    </div>
  );
}
