import { createContext, useContext } from "react";
import type { Mode } from "./viz/palette";
import { CATEGORICAL, CHROME } from "./viz/palette";

export const ModeContext = createContext<{ mode: Mode; setMode: (m: Mode) => void }>({ mode: "light", setMode: () => {} });

export function useViz() {
  const { mode } = useContext(ModeContext);
  return { mode, series: CATEGORICAL[mode], chrome: CHROME[mode] };
}

export function initialMode(): Mode {
  try {
    const saved = localStorage.getItem("uiad-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* storage unavailable */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function saveMode(m: Mode) {
  try { localStorage.setItem("uiad-theme", m); } catch { /* storage unavailable */ }
}
