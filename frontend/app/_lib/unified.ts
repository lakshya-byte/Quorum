import { diffStats, type DiffLine } from "./diff";

export type DiffRow = { kind: "same" | "add" | "del" | "hunk"; text: string; a?: number; b?: number };
export type DiffFile = { path: string; rows: DiffRow[]; add: number; del: number };

/** Parse unified diff text (git style or plain ---/+++) into per-file rows. */
export function parseUnifiedDiff(text: string): DiffFile[] {
  const files: DiffFile[] = [];
  let cur: DiffFile | null = null;
  let a = 0;
  let b = 0;
  const start = (path: string) => {
    cur = { path, rows: [], add: 0, del: 0 };
    files.push(cur);
  };
  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    if (raw.startsWith("diff --git ")) {
      const m = raw.match(/ b\/(.+)$/);
      start(m ? m[1] : raw.slice(11));
      continue;
    }
    if (raw.startsWith("--- ")) {
      if (!cur || (cur as DiffFile).rows.length) {
        const p = raw.slice(4).replace(/^a\//, "").split("\t")[0];
        start(p === "/dev/null" ? "" : p);
      }
      continue;
    }
    if (raw.startsWith("+++ ")) {
      const p = raw.slice(4).replace(/^b\//, "").split("\t")[0];
      if (cur && p !== "/dev/null") (cur as DiffFile).path = p;
      continue;
    }
    if (/^(index |new file|deleted file|similarity|rename )/.test(raw)) continue;
    const h = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (h) {
      if (!cur) start("changes");
      a = Number(h[1]);
      b = Number(h[2]);
      (cur as unknown as DiffFile).rows.push({ kind: "hunk", text: raw });
      continue;
    }
    const f = cur as DiffFile | null;
    if (!f) continue;
    if (raw.startsWith("+")) {
      f.rows.push({ kind: "add", text: raw.slice(1), b: b++ });
      f.add++;
    } else if (raw.startsWith("-")) {
      f.rows.push({ kind: "del", text: raw.slice(1), a: a++ });
      f.del++;
    } else if (raw.startsWith(" ")) {
      f.rows.push({ kind: "same", text: raw.slice(1), a: a++, b: b++ });
    }
  }
  return files.filter((f) => f.rows.length > 0);
}

export function diffFileFromLines(path: string, lines: DiffLine[]): DiffFile {
  const s = diffStats(lines);
  return { path, rows: lines.map((l) => ({ kind: l.kind, text: l.text, a: l.a, b: l.b })), add: s.add, del: s.del };
}

/** Number of files a candidate actually changes (from its diff), falling back to the files map. */
export function changedFileCount(n: { diff?: string; files?: Record<string, string> }): number {
  if (n.diff) {
    const c = parseUnifiedDiff(n.diff).length;
    if (c) return c;
  }
  return n.files ? Object.keys(n.files).length : 0;
}
