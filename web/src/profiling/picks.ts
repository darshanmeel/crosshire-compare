// web/src/profiling/picks.ts - the columns picked under Value frequencies. They live outside
// React's tree, so they survive the Compare | Profiling switch, and are cut back to the columns
// the profile has (state.kept_picks). The default is used once, while nothing is held.
import { useEffect, useState } from "react";

let held: string[] | null = null;

export function resetPicks() { held = null; }

export function keptPicks(options: string[], dflt: string[]): string[] {
  const have = new Set(options);
  held = (held ?? dflt).filter((c) => have.has(c));
  return held;
}

export function usePicks(options: string[], dflt: string[]): [string[], (v: string[]) => void] {
  const [picked, setPicked] = useState(() => keptPicks(options, dflt));
  const sig = options.join("\u0000");
  useEffect(() => { setPicked(keptPicks(options, dflt)); }, [sig]);
  return [picked, (v) => { held = v; setPicked(v); }];
}
