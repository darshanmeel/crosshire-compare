import { useState } from "react";
import { Icon } from "../ui/icons";

/** Light or dark: the choice is kept in this browser; with none kept the page follows the system. */
export function ModeToggle() {
  const [mode, setMode] = useState(document.documentElement.getAttribute("data-fs-mode") ?? "light");
  const flip = () => {
    const next = mode === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-fs-mode", next);
    try { localStorage.setItem("fs-mode", next); } catch { /* storage blocked: this visit only */ }
    setMode(next);
  };
  // On a phone it is a sun / moon icon (styles.css); its name stays "Dark".
  return (
    <button type="button" className="btn mode-toggle" onClick={flip} aria-pressed={mode === "dark"} aria-label="Dark"
            title={`Switch to the ${mode === "dark" ? "light" : "dark"} look`}>
      <span className="ph-only"><Icon name={mode === "dark" ? "sun" : "moon"} /></span><span className="ph-hide">Dark</span>
    </button>
  );
}
