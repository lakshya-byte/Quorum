"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { artifactsApi, errorMessage, fetchArtifact, type ArtifactMeta } from "../../../_lib/api";
import { Badge, Button, Card, Icon, Skeleton, Tabs, cx } from "../../../_ui";
import { CopyButton } from "../Actions";

/** Fetch an artifact with the session token and expose it as a blob URL (images cannot carry an Authorization header). */
export function useArtifactUrl(runId: string, id: string | undefined): { url: string | null; error: string | null } {
  const [res, setRes] = useState<{ key: string; url?: string; error?: string } | null>(null);
  const key = id ? `${runId}/${id}` : "";
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    fetchArtifact(runId, id)
      .then((a) => !cancelled && setRes({ key, url: a.url }))
      .catch((e) => !cancelled && setRes({ key, error: errorMessage(e) }));
    return () => {
      cancelled = true;
    };
  }, [runId, id, key]);
  const mine = res && res.key === key ? res : null;
  return { url: mine?.url ?? null, error: mine?.error ?? null };
}

function altFor(a: ArtifactMeta | undefined, side: string): string {
  if (!a) return `${side}: screenshot not available`;
  return `${side} screenshot of ${a.label}${a.viewport ? ` at ${a.viewport} pixels wide` : ""}`;
}

function Shot({ runId, art, side, className }: { runId: string; art: ArtifactMeta | undefined; side: string; className?: string }) {
  const { url, error } = useArtifactUrl(runId, art?.id);
  if (!art) return <div className={cx("flex aspect-[3/4] items-center justify-center rounded-lg border border-dashed border-border text-[12.5px] text-on-surface-variant", className)}>No {side.toLowerCase()} screenshot</div>;
  if (error) return <div role="alert" className="rounded-lg border border-error/40 bg-error/5 p-3 text-[12.5px] text-error">{error}</div>;
  if (!url) return <Skeleton className={cx("aspect-[3/4]", className)} />;
  // eslint-disable-next-line @next/next/no-img-element -- blob URL from an authenticated fetch
  return <img src={url} alt={altFor(art, side)} className={cx("block h-auto w-full", className)} />;
}

/** Before/after frame with a draggable divider. A real range input sits on top: pointer drag and arrow keys both work. */
export function CompareFrame({ before, after, onFocusLabel }: { before: ReactNode; after: ReactNode; onFocusLabel?: string }) {
  const [pos, setPos] = useState(50);
  return (
    <div className="relative overflow-hidden rounded-lg border border-border-strong bg-bg has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-primary">
      {before}
      <div className="absolute inset-0" style={{ clipPath: `inset(0 0 0 ${pos}%)` }}>
        {after}
      </div>
      <span className="pointer-events-none absolute left-2 top-2 rounded bg-black/75 px-1.5 py-0.5 text-[11px] font-semibold text-white">Before</span>
      <span className="pointer-events-none absolute right-2 top-2 rounded bg-primary px-1.5 py-0.5 text-[11px] font-semibold text-[#04120c]">After</span>
      <div aria-hidden className="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.4)]" style={{ left: `${pos}%` }}>
        <span className="absolute left-1/2 top-1/2 flex h-8 w-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-black/30 bg-white text-[#04120c] shadow-lg">
          <Icon name="split" size={14} className="rotate-90" />
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={pos}
        onChange={(e) => setPos(Number(e.target.value))}
        aria-label={onFocusLabel || "Comparison position: drag to reveal the after screenshot"}
        aria-valuetext={`${pos}% before, ${100 - pos}% after`}
        data-testid="compare-range"
        className="absolute inset-0 h-full w-full cursor-ew-resize opacity-0"
      />
    </div>
  );
}

/** Before/after screenshots of one viewport, fetched with the session token. */
export function CompareSlider({ runId, before, after, maxWidth }: { runId: string; before: ArtifactMeta | undefined; after: ArtifactMeta | undefined; maxWidth?: number }) {
  const bUrl = useArtifactUrl(runId, before?.id);
  const aUrl = useArtifactUrl(runId, after?.id);
  const ready = bUrl.url && aUrl.url;
  return (
    <div className="mx-auto w-full" style={{ maxWidth: maxWidth ? `${maxWidth}px` : undefined }} data-testid="compare-slider">
      {ready ? (
        <CompareFrame
          before={
            // eslint-disable-next-line @next/next/no-img-element -- blob URL
            <img src={bUrl.url!} alt={altFor(before, "Before")} className="block h-auto w-full select-none" draggable={false} />
          }
          after={
            // eslint-disable-next-line @next/next/no-img-element -- blob URL
            <img src={aUrl.url!} alt={altFor(after, "After")} className="h-full w-full select-none object-cover object-top" draggable={false} />
          }
        />
      ) : bUrl.error || aUrl.error ? (
        <p role="alert" className="rounded-lg border border-error/40 bg-error/5 p-4 text-[13px] text-error">{bUrl.error || aUrl.error}</p>
      ) : (
        <Skeleton className="aspect-[3/4]" />
      )}
    </div>
  );
}

function SideBySide({ runId, before, after, maxWidth }: { runId: string; before: ArtifactMeta | undefined; after: ArtifactMeta | undefined; maxWidth?: number }) {
  return (
    <div className="mx-auto grid gap-3 sm:grid-cols-2" style={{ maxWidth: maxWidth && maxWidth <= 400 ? `${maxWidth * 2 + 12}px` : undefined }} data-testid="side-by-side">
      {[
        ["Before", before],
        ["After", after],
      ].map(([label, art]) => (
        <figure key={label as string} className="min-w-0">
          <figcaption className="mb-1.5 text-[12px] font-medium text-on-surface-variant">{label as string}</figcaption>
          <div className="overflow-hidden rounded-lg border border-border-strong">
            <Shot runId={runId} art={art as ArtifactMeta | undefined} side={label as string} />
          </div>
        </figure>
      ))}
    </div>
  );
}

/** Modal with focus trap, Escape to close and focus restored to the opener. */
export function Lightbox({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const id = useId();
  const closeCb = useRef(onClose);
  useEffect(() => {
    closeCb.current = onClose;
  });
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeCb.current();
      } else if (e.key === "Tab" && ref.current) {
        const f = [...ref.current.querySelectorAll<HTMLElement>('button, [href], input, [tabindex]:not([tabindex="-1"])')].filter((x) => !x.hasAttribute("disabled"));
        if (!f.length) return;
        const first = f[0];
        const last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      prev?.focus?.();
    };
  }, []);
  return (
    <div className="fixed inset-0 z-[90] flex items-start justify-center overflow-y-auto bg-black/80 p-3 sm:p-8" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={id} className="w-full max-w-5xl rounded-xl border border-border-strong bg-panel shadow-pop" data-testid="lightbox">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <h2 id={id} className="text-[14px] font-semibold text-white">
            {title}
          </h2>
          <button ref={closeRef} type="button" onClick={onClose} className="focus-ring inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong px-2.5 text-[13px] text-on-surface hover:bg-surface-container-high">
            <Icon name="x" size={14} />
            Close
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

const VIEWPORT_NAME: Record<number, string> = { 375: "phone", 768: "tablet", 1280: "desktop" };

function LogViewer({ runId, art }: { runId: string; art: ArtifactMeta }) {
  const [res, setRes] = useState<{ id: string; text?: string; error?: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchArtifact(runId, art.id, true)
      .then((a) => !cancelled && setRes({ id: art.id, text: a.text }))
      .catch((e) => !cancelled && setRes({ id: art.id, error: errorMessage(e) }));
    return () => {
      cancelled = true;
    };
  }, [runId, art.id]);
  const mine = res?.id === art.id ? res : null;
  if (!mine) return <Skeleton className="h-24" />;
  if (mine.error) return <p role="alert" className="text-[12.5px] text-error">{mine.error}</p>;
  return (
    <div className="flex flex-col gap-2" data-testid="log-viewer">
      <pre tabIndex={0} aria-label={`${art.label} output`} className="max-h-72 overflow-auto rounded-md border border-border bg-bg p-3 font-mono text-[12px] leading-5 text-on-surface-variant focus-visible:outline-2 focus-visible:outline-primary">
        {mine.text}
      </pre>
      <div>
        <CopyButton text={mine.text || ""} label="Copy" variant="ghost" />
      </div>
    </div>
  );
}

export default function ArtifactsGallery({ runId, artifacts, finished }: { runId: string; artifacts: ArtifactMeta[]; finished: boolean }) {
  // The live events give the list as it grows; once finished, the API list is the source of truth (also covers saved runs).
  const [fetched, setFetched] = useState<ArtifactMeta[]>([]);
  useEffect(() => {
    if (!finished) return;
    let cancelled = false;
    artifactsApi
      .list(runId)
      .then((l) => !cancelled && setFetched(l || []))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [runId, finished, artifacts.length]);
  const all = [...artifacts];
  for (const f of fetched) if (!all.some((a) => a.id === f.id)) all.push(f);

  const shots = all.filter((a) => a.kind === "screenshot");
  const files = all.filter((a) => a.kind !== "screenshot");
  const vps = [...new Set(shots.map((s) => Number(s.viewport)).filter((n) => n > 0))].sort((a, b) => a - b);
  const [vp, setVp] = useState<number | null>(null);
  const [mode, setMode] = useState<"slider" | "side">("slider");
  const [zoom, setZoom] = useState<ArtifactMeta | "compare" | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const cur = vp && vps.includes(vp) ? vp : (vps[0] ?? null);
  const pick = (phase: string) => shots.filter((s) => Number(s.viewport) === cur && s.phase === phase).slice(-1)[0];
  const before = cur ? pick("before") : undefined;
  const after = cur ? pick("after") : undefined;
  const unpaired = shots.filter((s) => !(Number(s.viewport) > 0 && (s.phase === "before" || s.phase === "after")));
  const close = () => setZoom(null);

  if (all.length === 0) return null;

  return (
    <section aria-labelledby="art-h" className="flex flex-col gap-3" data-testid="artifacts">
      <h2 id="art-h" className="flex items-center gap-2 text-[15px] font-semibold text-white">
        <Icon name="eye" size={16} className="text-primary" />
        Artifacts
        <span className="text-[12px] font-normal text-on-surface-variant">{all.length} files, no secrets (logs pass the redactor)</span>
      </h2>
      <Card className="flex flex-col gap-4 p-4 sm:p-5">
        {vps.length > 0 && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Tabs
                label="Viewport"
                value={String(cur)}
                onChange={(v) => setVp(Number(v))}
                tabs={vps.map((v) => ({ id: String(v), label: <>{v}px<span className="hidden sm:inline">{VIEWPORT_NAME[v] ? ` ${VIEWPORT_NAME[v]}` : ""}</span></> }))}
                className="border-b-0"
              />
              <div className="flex flex-wrap items-center gap-2">
                <div role="group" aria-label="Comparison view" className="inline-flex overflow-hidden rounded-md border border-border-strong">
                  {(["slider", "side"] as const).map((m) => (
                    <button
                      key={m}
                      type="button"
                      aria-pressed={mode === m}
                      onClick={() => setMode(m)}
                      className={cx("focus-ring h-8 px-3 text-[12.5px]", mode === m ? "bg-primary/15 text-white" : "text-on-surface-variant hover:text-white")}
                    >
                      {m === "slider" ? "Slider" : "Side by side"}
                    </button>
                  ))}
                </div>
                <Button size="sm" variant="secondary" icon="search" onClick={() => setZoom("compare")} data-testid="enlarge">
                  Enlarge
                </Button>
              </div>
            </div>
            <div role="tabpanel">
              {before && after ? (
                mode === "slider" ? (
                  <CompareSlider runId={runId} before={before} after={after} maxWidth={cur && cur <= 768 ? cur : undefined} />
                ) : (
                  <SideBySide runId={runId} before={before} after={after} maxWidth={cur ?? undefined} />
                )
              ) : (
                <div className="mx-auto grid gap-3 sm:grid-cols-2" style={{ maxWidth: cur && cur <= 768 ? `${cur * 2 + 12}px` : undefined }}>
                  <figure>
                    <figcaption className="mb-1.5 text-[12px] text-on-surface-variant">Before</figcaption>
                    <Shot runId={runId} art={before} side="Before" />
                  </figure>
                  <figure>
                    <figcaption className="mb-1.5 text-[12px] text-on-surface-variant">After {finished ? "" : "(not captured yet)"}</figcaption>
                    <Shot runId={runId} art={after} side="After" />
                  </figure>
                </div>
              )}
            </div>
            <p className="text-[12px] text-text-subtle">Screenshots are evidence for you. The vision score is advisory; the hard UI gates are the console, overflow, axe and smoke checks.</p>
          </div>
        )}

        {unpaired.length > 0 && (
          <ul className="grid gap-3 sm:grid-cols-3">
            {unpaired.map((a) => (
              <li key={a.id}>
                <button type="button" onClick={() => setZoom(a)} className="focus-ring block w-full overflow-hidden rounded-lg border border-border-strong text-left">
                  <Shot runId={runId} art={a} side={a.phase} />
                  <span className="block px-2 py-1.5 text-[12px] text-on-surface-variant">{a.label}</span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {files.length > 0 && (
          <div className="flex flex-col gap-2" data-testid="artifact-files">
            <h3 className="text-[12.5px] font-semibold text-white">Logs and reports</h3>
            <ul className="flex flex-col gap-1.5">
              {files.map((a) => (
                <li key={a.id} className="rounded-lg border border-border bg-surface-container-low">
                  <div className="flex flex-wrap items-center gap-2 px-3 py-2">
                    <Icon name={a.kind === "log" ? "terminal" : "file"} size={14} className="text-on-surface-variant" />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-on-surface">{a.label}</span>
                    <Badge mono>{a.kind}</Badge>
                    <button
                      type="button"
                      aria-expanded={open === a.id}
                      onClick={() => setOpen(open === a.id ? null : a.id)}
                      className="focus-ring rounded px-2 py-1 text-[12.5px] text-primary hover:underline"
                    >
                      {open === a.id ? "Hide" : "View"}
                    </button>
                  </div>
                  {open === a.id && (
                    <div className="border-t border-border p-3">
                      <LogViewer runId={runId} art={a} />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      {zoom && (
        <Lightbox title={zoom === "compare" ? `Before and after at ${cur}px` : zoom.label} onClose={close}>
          {zoom === "compare" ? (
            before && after ? (
              mode === "slider" ? (
                <CompareSlider runId={runId} before={before} after={after} maxWidth={cur && cur <= 768 ? Math.max(cur, 600) : undefined} />
              ) : (
                <SideBySide runId={runId} before={before} after={after} />
              )
            ) : (
              <p className="text-[13px] text-on-surface-variant">Both a before and an after screenshot are needed to compare.</p>
            )
          ) : (
            <Shot runId={runId} art={zoom} side={zoom.phase} />
          )}
        </Lightbox>
      )}
    </section>
  );
}
