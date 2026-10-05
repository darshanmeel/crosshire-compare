import { useState, type ReactNode } from "react";

export function Expander({ title, open = false, children }: { title: ReactNode; open?: boolean; children: ReactNode }) {
  const [shown, setShown] = useState(open);
  return (
    <details className="expander" open={shown} onToggle={(e) => setShown((e.target as HTMLDetailsElement).open)}>
      <summary>{title}</summary>
      {shown && <div className="expander-body">{children}</div>}
    </details>
  );
}
