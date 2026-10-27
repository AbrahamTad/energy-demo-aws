import type { CSSProperties } from "react";

const paths = {
  bolt: "m13 2-9 12h7l-1 8 10-12h-7l1-8Z",
  home: "m3 10 9-7 9 7v10H3V10Zm6 10v-7h6v7",
  chart: "M4 3v17h17M8 15v-4m5 4V7m5 8v-5",
  user: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-2a8 8 0 0 1 16 0v2",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1",
  moon: "M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z",
  wind: "M3 8h12a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M3 16h5a3 3 0 1 1-3 3",
  water: "M12 2C9 7 4 11 4 15a8 8 0 0 0 16 0c0-4-5-8-8-13Zm-4 14a4 4 0 0 0 4 4",
  battery: "M3 7h16v10H3V7Zm18 3v4M7 10v4m4-4v4m4-4v4",
  leaf: "M20 3C6 2 2 9 6 15s14 3 14-12ZM4 21 15 10",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  shield: "m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4Zm-4 10 3 3 5-6",
  menu: "M4 6h16M4 12h16M4 18h16",
  close: "m6 6 12 12M6 18 18 6",
  refresh:
    "M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
  check: "m5 12 4 4L19 6",
  logout: "M9 4H4v16h5m4-4 4-4-4-4M9 12h12",
  mail: "M3 5h18v14H3V5Zm0 0 9 8 9-8",
} as const;

export type IconName = keyof typeof paths;
export function Icon({
  name,
  size = 20,
  style,
}: {
  name: IconName;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      <path d={paths[name]} />
    </svg>
  );
}
