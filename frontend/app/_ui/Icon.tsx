import type { SVGProps } from "react";

// Small stroke icon set (24x24 grid, 1.75 stroke). Inline SVG so nothing is fetched at runtime.
const P: Record<string, string> = {
  "arrow-right": "M5 12h14M13 6l6 6-6 6",
  "arrow-left": "M19 12H5M11 6l-6 6 6 6",
  "arrow-up-right": "M7 17 17 7M8 7h9v9",
  check: "m5 12.5 4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6 6 18",
  menu: "M4 7h16M4 12h16M4 17h16",
  "chevron-down": "m6 9 6 6 6-6",
  "chevron-right": "m9 6 6 6-6 6",
  play: "M7 5.5v13l11-6.5z",
  github:
    "M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21",
  slack: "M5 9h14M5 15h14M10 4 8 20M16 4l-2 16",
  key: "M15.5 8.5a3.5 3.5 0 1 1-2.1 3.2L4 21v-3l2-1v-2h2l1.9-1.9",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  external: "M14 4h6v6M20 4 10 14M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  copy: "M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1zM5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3",
  lock: "M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1zM8 11V8a4 4 0 0 1 8 0v3",
  shield: "M12 3 5 6v5.5c0 4.3 2.9 8 7 9.5 4.1-1.5 7-5.2 7-9.5V6z",
  "shield-check": "M12 3 5 6v5.5c0 4.3 2.9 8 7 9.5 4.1-1.5 7-5.2 7-9.5V6zM8.8 12l2.4 2.4 4.1-4.4",
  "git-branch": "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9",
  "git-pr": "M6 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 8v8M18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 16V9a3 3 0 0 0-3-3h-3m0 0 2.5-2.5M12 6l2.5 2.5",
  flask: "M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2.2h12.4a1.5 1.5 0 0 0 1.3-2.2L14 9V3M7.5 15h9",
  bug: "M9 7V6a3 3 0 0 1 6 0v1M8 7h8a2 2 0 0 1 2 2v4a6 6 0 0 1-12 0V9a2 2 0 0 1 2-2zM12 20v-8M3 13h3M18 13h3M4 7l3 2M20 7l-3 2M4 20l3-3M20 20l-3-3",
  crosshair: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 2v4M12 18v4M2 12h4M18 12h4",
  sparkles: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  scale: "M12 4v16M6 20h12M5 7h14M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0z",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  home: "M4 11 12 4l8 7M6 10v9a1 1 0 0 0 1 1h3v-5h4v5h3a1 1 0 0 0 1-1v-9",
  plug: "M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0zM12 16v5",
  logout: "M10 4H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4M15 8l4 4-4 4M19 12H9",
  plus: "M12 5v14M5 12h14",
  trash: "M4 7h16M10 3h4M6 7l1 13h10l1-13M10 11v6M14 11v6",
  refresh: "M20 11a8 8 0 0 0-14.5-3.5L4 9M4 4v5h5M4 13a8 8 0 0 0 14.5 3.5L20 15M20 20v-5h-5",
  alert: "M12 3 2 20h20zM12 10v4.5M12 17.5v.01",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8v.01",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  terminal: "M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM7 10l3 2.5L7 15M13 15h4",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  layers: "m12 3 9 5-9 5-9-5zM3 13l9 5 9-5M3 17.5 12 22l9-4.5",
  "check-circle": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8.5 12.2l2.5 2.5 4.5-5",
  "x-circle": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9 9l6 6M15 9l-6 6",
  ban: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM5.6 5.6l12.8 12.8",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  book: "M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 19V5M8 7h7",
  box: "M12 3 4 7v10l8 4 8-4V7zM4 7l8 4 8-4M12 11v10",
  cpu: "M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4M10 10h4v4h-4z",
  loader: "M12 3a9 9 0 1 0 9 9",
  gauge: "M4 18a9 9 0 1 1 16 0M12 14l4-5",
  split: "M6 3v6a4 4 0 0 0 4 4h4a4 4 0 0 1 4 4v4M6 3 3 6M6 3l3 3M18 21l-3-3M18 21l3-3",
  trophy: "M8 4h8v6a4 4 0 0 1-8 0zM8 6H4v1a4 4 0 0 0 4 4M16 6h4v1a4 4 0 0 1-4 4M12 14v4M8 21h8M10 18h4",
  bolt: "M13 2 4 14h7l-1 8 9-12h-7z",
  send: "M21 3 10 14M21 3l-7 18-4-7-7-4z",
  code: "m8 8-5 4 5 4M16 8l5 4-5 4M14 5l-4 14",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 21h4",
  sidebar: "M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM9 5v14",
};

export type IconName = keyof typeof P | (string & {});

export default function Icon({
  name,
  size = 16,
  className,
  strokeWidth = 1.75,
  ...rest
}: { name: IconName; size?: number; strokeWidth?: number } & Omit<SVGProps<SVGSVGElement>, "name">) {
  const d = P[name] ?? P.info;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={["shrink-0", className].filter(Boolean).join(" ")}
      {...rest}
    >
      <path d={d} />
    </svg>
  );
}
