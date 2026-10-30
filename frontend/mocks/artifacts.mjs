// Programmatic images for the mock backend: no external assets. A tiny PNG encoder (zlib) and a 5x7
// bitmap font draw "before" and "after" screenshots of a basic React todo app at 375/768/1280 widths.

import zlib from "node:zlib";

const FONT = {
  A: "01110,10001,10001,11111,10001,10001,10001", B: "11110,10001,10001,11110,10001,10001,11110", C: "01110,10001,10000,10000,10000,10001,01110",
  D: "11110,10001,10001,10001,10001,10001,11110", E: "11111,10000,10000,11110,10000,10000,11111", F: "11111,10000,10000,11110,10000,10000,10000",
  G: "01110,10001,10000,10111,10001,10001,01111", H: "10001,10001,10001,11111,10001,10001,10001", I: "01110,00100,00100,00100,00100,00100,01110",
  J: "00111,00010,00010,00010,00010,10010,01100", K: "10001,10010,10100,11000,10100,10010,10001", L: "10000,10000,10000,10000,10000,10000,11111",
  M: "10001,11011,10101,10101,10001,10001,10001", N: "10001,11001,10101,10011,10001,10001,10001", O: "01110,10001,10001,10001,10001,10001,01110",
  P: "11110,10001,10001,11110,10000,10000,10000", Q: "01110,10001,10001,10001,10101,10010,01101", R: "11110,10001,10001,11110,10100,10010,10001",
  S: "01111,10000,10000,01110,00001,00001,11110", T: "11111,00100,00100,00100,00100,00100,00100", U: "10001,10001,10001,10001,10001,10001,01110",
  V: "10001,10001,10001,10001,10001,01010,00100", W: "10001,10001,10001,10101,10101,11011,10001", X: "10001,10001,01010,00100,01010,10001,10001",
  Y: "10001,10001,01010,00100,00100,00100,00100", Z: "11111,00001,00010,00100,01000,10000,11111",
  0: "01110,10001,10011,10101,11001,10001,01110", 1: "00100,01100,00100,00100,00100,00100,01110", 2: "01110,10001,00001,00010,00100,01000,11111",
  3: "11110,00001,00001,01110,00001,00001,11110", 4: "00010,00110,01010,10010,11111,00010,00010", 5: "11111,10000,11110,00001,00001,10001,01110",
  6: "00110,01000,10000,11110,10001,10001,01110", 7: "11111,00001,00010,00100,01000,01000,01000", 8: "01110,10001,10001,01110,10001,10001,01110",
  9: "01110,10001,10001,01111,00001,00010,01100",
  ".": "00000,00000,00000,00000,00000,00000,00100", ",": "00000,00000,00000,00000,00100,00100,01000", "-": "00000,00000,00000,11111,00000,00000,00000",
  ":": "00000,00100,00000,00000,00000,00100,00000", "!": "00100,00100,00100,00100,00100,00000,00100", "+": "00000,00100,00100,11111,00100,00100,00000",
  "'": "00100,00100,01000,00000,00000,00000,00000", "/": "00001,00001,00010,00100,01000,10000,10000", "?": "01110,10001,00001,00010,00100,00000,00100",
};

const crcTable = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
const crc32 = (buf) => {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
};
const chunk = (type, data) => {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
};

class Canvas {
  constructor(w, h, bg) {
    this.w = w;
    this.h = h;
    this.px = Buffer.alloc(w * h * 3);
    this.rect(0, 0, w, h, bg);
  }
  rect(x, y, w, h, color) {
    const [r, g, b] = color;
    const x0 = Math.max(0, Math.round(x));
    const y0 = Math.max(0, Math.round(y));
    const x1 = Math.min(this.w, Math.round(x + w));
    const y1 = Math.min(this.h, Math.round(y + h));
    for (let j = y0; j < y1; j++) for (let i = x0; i < x1; i++) {
      const o = (j * this.w + i) * 3;
      this.px[o] = r;
      this.px[o + 1] = g;
      this.px[o + 2] = b;
    }
  }
  /** rect with a 1px border */
  box(x, y, w, h, fill, line) {
    this.rect(x, y, w, h, line);
    this.rect(x + 1, y + 1, w - 2, h - 2, fill);
  }
  text(str, x, y, scale, color) {
    let cx = x;
    for (const ch of String(str).toUpperCase()) {
      const g = FONT[ch];
      if (g) {
        g.split(",").forEach((row, j) => {
          for (let i = 0; i < 5; i++) if (row[i] === "1") this.rect(cx + i * scale, y + j * scale, scale, scale, color);
        });
      }
      cx += 6 * scale;
    }
    return cx;
  }
  png() {
    const raw = Buffer.alloc((this.w * 3 + 1) * this.h);
    for (let j = 0; j < this.h; j++) {
      raw[j * (this.w * 3 + 1)] = 0;
      this.px.copy(raw, j * (this.w * 3 + 1) + 1, j * this.w * 3, (j + 1) * this.w * 3);
    }
    const ihdr = Buffer.alloc(13);
    ihdr.writeUInt32BE(this.w, 0);
    ihdr.writeUInt32BE(this.h, 4);
    ihdr[8] = 8;
    ihdr[9] = 2;
    return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
  }
}

const ITEMS = ["BUY GROCERIES", "WRITE THE QUARTERLY REPORT", "BOOK DENTIST", "REPLY TO PRIYA"];

/** A basic todo page, before (default styles, overflowing table at 375) or after (cards, spacing, contrast). */
export function todoShot(width, phase) {
  const w = width;
  const h = Math.round(width <= 375 ? 640 : width <= 768 ? 560 : 520);
  const s = width <= 375 ? 2 : 2;
  if (phase === "before") {
    const c = new Canvas(w, h, [255, 255, 255]);
    c.text("MY TODOS", 8, 10, 3, [0, 0, 0]);
    c.rect(8, 44, w - 16, 1, [120, 120, 120]);
    c.box(8, 60, Math.min(w - 16, 200), 22, [255, 255, 255], [118, 118, 118]);
    c.box(Math.min(w - 16, 200) + 14, 60, 38, 22, [239, 239, 239], [118, 118, 118]);
    c.text("ADD", Math.min(w - 16, 200) + 20, 66, 1, [0, 0, 0]);
    ITEMS.forEach((it, i) => {
      const y = 104 + i * 30;
      c.box(8, y, 12, 12, [255, 255, 255], [118, 118, 118]);
      c.text(it, 28, y + 2, s, [0, 0, 0]);
      // the table is 900px wide in the original CSS: its columns run off the right edge on small screens
      c.rect(w - 36, y - 2, 36, 18, [239, 239, 239]);
      c.text("DEL", w - 30, y + 3, 1, [0, 0, 0]);
    });
    if (w <= 768) c.rect(w - 6, 0, 6, h, [230, 90, 90]); // overflow marker: content continues past the viewport
    return c.png();
  }
  const bg = [15, 18, 28];
  const card = [24, 29, 44];
  const line = [48, 56, 80];
  const accent = [16, 185, 129];
  const c = new Canvas(w, h, bg);
  const pad = w <= 375 ? 16 : 40;
  const cw = Math.min(w - pad * 2, 640);
  const x0 = Math.round((w - cw) / 2);
  c.text("MY TODOS", x0, 28, 4, [235, 240, 250]);
  c.text("4 OPEN, 0 DONE", x0, 68, 2, [150, 162, 185]);
  c.box(x0, 96, cw, 44, card, line);
  c.text("ADD A TASK", x0 + 14, 112, 2, [150, 162, 185]);
  c.rect(x0 + cw - 78, 104, 66, 28, accent);
  c.text("ADD", x0 + cw - 62, 112, 2, [4, 18, 12]);
  ITEMS.forEach((it, i) => {
    const y = 156 + i * 62;
    c.box(x0, y, cw, 52, card, line);
    c.box(x0 + 14, y + 16, 20, 20, bg, accent);
    c.text(w <= 375 && it.length > 14 ? it.slice(0, 13) + "." : it, x0 + 48, y + 19, 2, [235, 240, 250]);
    c.text("DELETE", x0 + cw - 74, y + 19, 2, [150, 162, 185]);
  });
  return c.png();
}

export function logText(name) {
  const logs = {
    "build.log": "> react-todo@0.1.0 build\n> vite build\n\nvite v5.4.0 building for production...\ntransforming...\n12 modules transformed.\ndist/index.html          0.46 kB\ndist/assets/index.css    3.91 kB\ndist/assets/index.js   144.20 kB\nbuilt in 1.84s\n",
    "overflow-r1.log": "ui_overflow round 1\nviewport 1280: scrollWidth 1280 <= 1280  ok\nviewport 768: scrollWidth 768 <= 768  ok\nviewport 375: scrollWidth 612 > 375  FAIL\n  offender: table.todos (width 612px) overflows by 237px\n",
    "smoke.log": "smoke: add todo, complete it, delete it\nbefore: pass (3 steps)\nafter: pass (3 steps)\n",
    "tests.log": "Ran 13 tests in 0.041s\n\nOK\nbaseline: 13 passed, 0 failed\nnow:      13 passed, 0 failed\n",
    "spec.log": "tests/test_bulk_tiers.py written by the spec agent\non the original code: 4 failed, 0 passed  (expected: must fail first)\non the final code:    4 passed\n",
    "characterization.log": "tests/test_characterization.py (generated against the ORIGINAL)\non the original: 14 passed\non the refactor:  14 passed\npublic API surface: 7 exported symbols, 0 removed, 0 changed signature\n",
    "links.log": "docs link check: 9 links, 9 ok, 0 broken\n",
  };
  return logs[name] || "no output\n";
}

export function axeReport(phase) {
  return JSON.stringify(
    {
      tool: "axe-core",
      phase,
      violations: phase === "before" ? [{ id: "color-contrast", impact: "serious", nodes: 4 }, { id: "label", impact: "critical", nodes: 1 }] : [{ id: "color-contrast", impact: "serious", nodes: 1 }],
      counts: { total: phase === "before" ? 5 : 1 },
    },
    null,
    2
  );
}
