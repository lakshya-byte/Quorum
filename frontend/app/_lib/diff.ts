// Small line diff based on the longest common subsequence. Fine for the
// short functions PatchLoop patches (a few hundred lines at most).

export type DiffLine = { kind: "same" | "add" | "del"; text: string; a?: number; b?: number };

export function lineDiff(before: string, after: string): DiffLine[] {
  const A = before.replace(/\n$/, "").split("\n");
  const B = after.replace(/\n$/, "").split("\n");
  const n = A.length;
  const m = B.length;
  // lcs[i][j] = LCS length of A[i..] and B[j..]
  const lcs: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = A[i] === B[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      out.push({ kind: "same", text: A[i], a: i + 1, b: j + 1 });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ kind: "del", text: A[i], a: i + 1 });
      i++;
    } else {
      out.push({ kind: "add", text: B[j], b: j + 1 });
      j++;
    }
  }
  while (i < n) out.push({ kind: "del", text: A[i], a: ++i });
  while (j < m) out.push({ kind: "add", text: B[j], b: ++j });
  return out;
}

export function diffStats(lines: DiffLine[]) {
  let add = 0;
  let del = 0;
  for (const l of lines) {
    if (l.kind === "add") add++;
    else if (l.kind === "del") del++;
  }
  return { add, del };
}
