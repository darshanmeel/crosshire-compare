// The redesign's icon set (design/icons.tsx): inline stroke SVGs on currentColor. <Icon name="check" />
// renders 14 px, size="sm" 12 px. Decorative by default; pass `label` when the icon is the only content of a control.
import type { SVGProps } from "react";

const PATHS = {
  check: ["M5 12l5 5L20 7", 3],
  chevron: ["M6 9l6 6 6-6", 2.2],
  arrow: ["M5 12h14M13 6l6 6-6 6", 2],
  arrowl: ["M19 12H5M11 6l-6 6 6 6", 2],
  swap: ["M4 8h13l-3-3M20 16H7l3 3", 1.8],
  key: ["M10.8 12.2L21 2m-3 3l3 3m-6 0l2 2", 2, "<circle cx='7.5' cy='15.5' r='4.5'/>"],
  plug: ["M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0V8zM12 18v4", 1.8],
  search: ["M20 20l-3.5-3.5", 2, "<circle cx='11' cy='11' r='7'/>"],
  download: ["M12 3v12m-5-5l5 5 5-5M4 21h16", 2],
  upload: ["M12 17V5m-5 5l5-5 5 5M4 21h16", 2],
  sparkle: ["M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4zM5 17l.8 2 2 .8-2 .8L5 22l-.8-2-2-.8 2-.8zM19 15l.6 1.6 1.6.6-1.6.6L19 19.4l-.6-1.6-1.6-.6 1.6-.6z", 1.8],
  table: ["M3 5h18v14H3zM3 10h18M9 5v14", 2],
  plus: ["M12 5v14M5 12h14", 2.2],
  x: ["M6 6l12 12M18 6L6 18", 2.2],
  folder: ["M3 7h6l2 2h10v10H3z", 1.8],
  file: ["M6 2h8l4 4v16H6zM14 2v4h4", 1.8],
  play: ["M7 4l12 8-12 8z", 2],
  db: ["M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3", 1.8, "<ellipse cx='12' cy='5' rx='8' ry='3'/>"],
  zip: ["M6 2h8l4 4v16H6zM10 6h2M10 9h2M10 12h2M10 15h2", 1.8],
  refresh: ["M20 11a8 8 0 0 0-14.5-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.5 4.5L20 16m0 4v-4h-4", 1.8],
} as const satisfies Record<string, readonly [string, number] | readonly [string, number, string]>;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = "md", label, ...rest }:
  { name: IconName; size?: "md" | "sm"; label?: string } & Omit<SVGProps<SVGSVGElement>, "name">) {
  const [d, width, extra] = PATHS[name] as readonly [string, number, string?];
  const px = size === "sm" ? 12 : 14;
  return (
    <svg
      className={size === "sm" ? "icon sm" : "icon"} width={px} height={px} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={width} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden={label ? undefined : true} role={label ? "img" : undefined} aria-label={label}
      {...rest}
    >
      {extra ? <g dangerouslySetInnerHTML={{ __html: extra }} /> : null}
      <path d={d} />
    </svg>
  );
}
