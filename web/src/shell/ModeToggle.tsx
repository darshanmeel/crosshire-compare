import { useState } from "react";

/** Light or dark: the choice is kept in this browser; with none kept the page follows the system. */
export function ModeToggle() {
  const [mode, setMode] = useState(document.documentElement.getAttribute("data-fs-mode") ?? "light");
  const flip = () => {
    const next = mode === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-fs-mode", next);
    try { localStorage.setItem("fs-mode", next); } catch { /* storage blocked: this visit only */ }
    setMode(next);
  };
  return <button type="button" className="btn" onClick={flip} aria-label="Light or dark" title={`Switch to the ${mode === "dark" ? "light" : "dark"} look`}>{mode === "dark" ? "Light" : "Dark"}</button>;
}
