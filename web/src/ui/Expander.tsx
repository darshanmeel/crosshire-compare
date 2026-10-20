import { useState, type ReactNode } from "react";

/** A <details> that opens in place. `open` is how it starts; `onToggle` hears each change, so a
 *  caller can keep the state and hand it back when the fold is drawn again. */
export function Expander({ title, open = false, onToggle, children }:
  { title: ReactNode; open?: boolean; onToggle?: (open: boolean) => void; children: ReactNode }) {
  const [shown, setShown] = useState(open);
  return (
    <details className="expander" open={shown} onToggle={(e) => {
      const now = (e.target as HTMLDetailsElement).open;
      setShown(now);
      if (now !== shown) onToggle?.(now);
    }}>
      <summary>{title}</summary>
      {shown && <div className="expander-body">{children}</div>}
    </details>
  );
}
