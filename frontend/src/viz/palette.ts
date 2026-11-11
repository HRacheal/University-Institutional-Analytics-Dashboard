// Chart tokens: the validated reference palette (dataviz skill, references/palette.md), light and dark selected
// separately. Categorical slots are assigned in FIXED order by entity (never by rank) and never cycled; charts with more
// series than slots fold the remainder into "Other". Status colours are reserved for state and always ship with a label.
export type Mode = "light" | "dark";

export const CATEGORICAL: Record<Mode, string[]> = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};

export const STATUS = { good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b" } as const;

export const CHROME: Record<Mode, { surface: string; page: string; ink: string; ink2: string; muted: string; grid: string; axis: string; band: string }> = {
  light: { surface: "#fcfcfb", page: "#f9f9f7", ink: "#0b0b0b", ink2: "#52514e", muted: "#898781", grid: "#e1e0d9", axis: "#c3c2b7", band: "#cde2fb" },
  dark: { surface: "#1a1a19", page: "#0d0d0d", ink: "#f0efec", ink2: "#c3c2b7", muted: "#898781", grid: "#2c2c2a", axis: "#383835", band: "#1c3a5e" },
};

/** Sequential blue ramp (ordinal use starts at step 250 on light / ends at 600 on dark). */
export const SEQ_BLUE = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95"];

export const fmtInt = (v: unknown) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : v == null ? "—" : String(v));
export const fmtPct = (v: unknown, d = 1) => (typeof v === "number" ? `${v.toFixed(d)}%` : "—");
export const fmtNum = (v: unknown, d = 2) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }) : "—");
export const fmtProb = (v: unknown) => (typeof v === "number" ? `${(100 * v).toFixed(1)}%` : "—");
export const nice = (s: string | null | undefined) =>
  !s ? "—" : s.replace(/_/g, " ").toLowerCase().replace(/(^|\s)\S/g, (c) => c.toUpperCase());
