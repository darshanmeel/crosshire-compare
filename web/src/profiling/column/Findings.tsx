// The row of findings under a column's header (and the profile's headline): one pill per thing
// worth knowing - a bold name, then a short mono detail - green when it is good news, amber when it
// needs a look, red when it is wrong, grey when it is only a fact.
import type { ReactNode } from "react";

export type Finding = { tone?: "pos" | "warn" | "neg" | "info"; label: ReactNode; detail?: ReactNode };

export function Findings({ items, label = "Findings" }: { items: Finding[]; label?: string }) {
  if (!items.length) return null;
  return (
    <ul className="findings" aria-label={label}>
      {items.map((f, i) => (
        <li key={i} className={`finding ${f.tone ?? "info"}`}>
          <i aria-hidden="true" /><strong>{f.label}</strong>{f.detail != null && f.detail !== "" && <span className="d">{f.detail}</span>}
        </li>
      ))}
    </ul>
  );
}

/** What a column most likely holds, from its name, its type and its values - a guess the page
 *  shows as a chip next to "read as": identifier, event time, date, amount, quantity, flag,
 *  category, person name, code, free text. */
export function semantic(column: string, kind: string, distinct: number, rows: number, isKey: boolean, shape = ""): string {
  const n = column.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
  const has = (...w: string[]) => w.some((x) => new RegExp(`(^|[^a-z])${x}`).test(n));
  if (isKey || has("id", "key", "no$", "number", "code$") && distinct >= 0.9 * rows) return "identifier";
  if (kind === "boolean" || distinct === 2 && has("is", "has", "active", "flag", "enabled")) return "flag";
  if (kind === "timestamp") return "event time";
  if (kind === "date") return "date";
  if (kind === "number") {
    if (has("qty", "quantity", "count", "units", "lots?")) return "quantity";
    if (has("price", "rate", "amount", "salary", "pay", "cost", "fee", "total", "balance", "value")) return "amount";
    return "measure";
  }
  if (has("name") && distinct > 20) return "person name";
  if (shape && /^[A]+-?[9]+$/.test(shape) && distinct <= 50) return `code · ${shape}`;
  if (distinct <= 50) return "category";
  return "text";
}
