"use client";

import { useState } from "react";
import type { DiffFile } from "../../_lib/unified";
import { Icon, cx } from "../../_ui";

/** Multi-file unified diff viewer: file list with +/- counts, one file's hunks at a time. */
export default function DiffViewer({ files, caption }: { files: DiffFile[]; caption?: string }) {
  const [sel, setSel] = useState(0);
  const idx = Math.min(sel, files.length - 1);
  const f = files[idx];
  if (!f) return <p className="text-[13px] text-on-surface-variant">No changes to show.</p>;
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-bg">
      {(caption || files.length > 1) && (
        <div className="border-b border-border bg-surface-container-low px-3 py-2 text-[12px] text-on-surface-variant">
          {caption && <div className="mb-1.5">{caption}</div>}
          {files.length > 1 && (
            <div role="tablist" aria-label="Changed files" className="flex flex-wrap gap-1.5">
              {files.map((x, i) => (
                <button
                  key={x.path + i}
                  role="tab"
                  aria-selected={i === idx}
                  onClick={() => setSel(i)}
                  className={cx(
                    "focus-ring inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-[11.5px]",
                    i === idx ? "border-primary/50 bg-primary/10 text-white" : "border-border-strong text-on-surface-variant hover:text-white"
                  )}
                >
                  <Icon name="file" size={12} />
                  {x.path}
                  <span className="text-primary">+{x.add}</span>
                  <span className="text-error">-{x.del}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 font-mono text-[12px] text-white">
        <Icon name="file" size={13} className="text-on-surface-variant" />
        {f.path}
        <span className="ml-auto text-primary">+{f.add}</span>
        <span className="text-error">-{f.del}</span>
      </div>
      <div className="overflow-x-auto" data-testid="diff-body">
        <table className="w-full border-collapse font-mono text-[12px] leading-[1.6] [font-variant-ligatures:none]">
          <tbody>
            {f.rows.map((l, i) =>
              l.kind === "hunk" ? (
                <tr key={i} className="bg-secondary/5 text-secondary">
                  <td colSpan={4} className="px-3 py-0.5">
                    {l.text}
                  </td>
                </tr>
              ) : (
                <tr key={i} className={l.kind === "add" ? "bg-primary/10 text-primary" : l.kind === "del" ? "bg-error/10 text-error" : "text-on-surface-variant"}>
                  <td className="w-9 select-none pl-2 pr-2 text-right align-top text-text-subtle">{l.a ?? ""}</td>
                  <td className="w-9 select-none border-r border-border pr-3 text-right align-top text-text-subtle">{l.b ?? ""}</td>
                  <td className="w-5 select-none pl-2 align-top">{l.kind === "add" ? "+" : l.kind === "del" ? "-" : " "}</td>
                  <td className="whitespace-pre pr-3">{l.text || " "}</td>
                </tr>
              )
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
