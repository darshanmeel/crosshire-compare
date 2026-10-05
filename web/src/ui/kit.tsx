// The redesign's shared pieces (design/COMPONENTS.md), on the classes in styles.css. Each is a thin
// wrapper over a real control: buttons are <button>, toggles say aria-pressed, groups say role="group".
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Icon, type IconName } from "./icons";

const fmt = new Intl.NumberFormat("en-US");
/** A number with thousands separators; anything else as it is. */
export const num = (n: number | string | null | undefined) => (typeof n === "number" ? fmt.format(n) : n ?? "");

/** `part` of `whole` as a percentage, two decimals - but never 0 or 100 when it is neither: 6 rows
 *  of 629,424 read 0.001 and 99.999, with as many decimals as that takes (up to 6). The page's
 *  twin of tablecmp.results.pct_text. */
export function pctText(part: number, whole: number) {
  if (!whole) return "0.00";
  const pct = (part / whole) * 100;
  if (!(part > 0 && part < whole) || (pct >= 0.005 && pct <= 99.995)) return pct.toFixed(2);
  const d = Math.min(6, -Math.floor(Math.log10(Math.min(pct, 100 - pct)))), f = 10 ** d;
  return ((pct < 50 ? Math.ceil(pct * f) : Math.floor(pct * f)) / f).toFixed(d).replace(/0+$/, "");
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "dark" | "ghost"; size?: "sm" | "md" | "lg"; icon?: IconName; iconAfter?: IconName; count?: number | string;
};
export function Button({ variant = "default", size = "md", icon, iconAfter, count, className, children, type = "button", ...rest }: BtnProps) {
  const cls = ["btn", variant !== "default" && variant, size !== "md" && size, className].filter(Boolean).join(" ");
  return (
    <button type={type} className={cls} {...rest}>
      {icon && <Icon name={icon} />}{children}{count !== undefined && <span className="count">{count}</span>}{iconAfter && <Icon name={iconAfter} />}
    </button>
  );
}

export function LinkButton({ icon, iconAfter, className, children, type = "button", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { icon?: IconName; iconAfter?: IconName }) {
  return <button type={type} className={["link-btn", className].filter(Boolean).join(" ")} {...rest}>{icon && <Icon name={icon} size="sm" />}{children}{iconAfter && <Icon name={iconAfter} size="sm" />}</button>;
}

export type Tone = "ok" | "warn" | "idle" | "run" | "neg";
export function Pill({ tone = "idle", dot = true, children, ...rest }: { tone?: Tone; dot?: boolean; children: ReactNode; role?: string; "aria-live"?: "polite" }) {
  return <span className={`pill ${tone}`} {...rest}>{dot && <i />}{children}</span>;
}

export function Chip({ tone, icon, children, title }: { tone?: "key" | "a" | "b" | "neg" | "pos" | "warn"; icon?: IconName; children: ReactNode; title?: string }) {
  return <span className={tone ? `chip ${tone}` : "chip"} title={title}>{tone === "key" && !icon ? <Icon name="key" size="sm" /> : icon && <Icon name={icon} size="sm" />}{children}</span>;
}

export type SegOption<T extends string> = { label: ReactNode; value: T; icon?: IconName; disabled?: boolean; title?: string };
/** A segmented control: one <button aria-pressed> per option inside role="group". */
export function Seg<T extends string>({ options, value, onChange, mini, label, className }: { options: SegOption<T>[]; value: T; onChange: (v: T) => void; mini?: boolean; label: string; className?: string }) {
  return (
    <div className={["seg", mini && "mini", className].filter(Boolean).join(" ")} role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} className={o.value === value ? "on" : undefined}
          disabled={o.disabled} title={o.title} onClick={() => o.value !== value && onChange(o.value)}>
          {o.icon && <Icon name={o.icon} size="sm" />}{o.label}
        </button>
      ))}
    </div>
  );
}

export function SideBadge({ side }: { side: "a" | "b" | "k" | "A" | "B" | "P" }) {
  const s = side.toLowerCase() === "p" ? "k" : side.toLowerCase();
  return <span className={`side-badge ${s}`} aria-hidden="true">{s === "k" ? "T" : s.toUpperCase()}</span>;
}

/** A section of the page: mono numeral eyebrow, title, grey sub-line, actions on the right. */
export function Section({ n, title, sub, actions, id, children }: { n?: string; title: ReactNode; sub?: ReactNode; actions?: ReactNode; id?: string; children?: ReactNode }) {
  return (
    <section className="sec" id={id} aria-label={typeof title === "string" ? title : undefined}>
      <div className="sec-head">
        {n && <span className="eyebrow accent">{n}</span>}
        <h2>{title}</h2>
        {sub && <span className="sub">{sub}</span>}
        {actions && <div className="actions">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function Card({ head, foot, children, className, ...rest }: { head?: ReactNode; foot?: ReactNode; children?: ReactNode; className?: string; role?: string; "aria-label"?: string }) {
  return (
    <div className={["card", className].filter(Boolean).join(" ")} {...rest}>
      {head && <div className="card-head">{head}</div>}
      {children}
      {foot && <div className="card-foot">{foot}</div>}
    </div>
  );
}

export function Panel({ title, sub, actions, foot, note, children, className }: { title?: ReactNode; sub?: ReactNode; actions?: ReactNode; foot?: ReactNode; note?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div className={["panel", className].filter(Boolean).join(" ")}>
      {(title || actions) && (
        <div className="panel-head">{title && <h3>{title}</h3>}{sub && <span className="sub">{sub}</span>}{actions && <div className="actions">{actions}</div>}</div>
      )}
      {note && <div className="panel-note">{note}</div>}
      {children}
      {foot && <div className="panel-foot">{foot}</div>}
    </div>
  );
}

export function Tile({ label, value, small }: { label: string; value: ReactNode; small?: ReactNode }) {
  return <div className="tile"><span className="eyebrow">{label}</span><span className="v">{value}{small && <> <small>{small}</small></>}</span></div>;
}

export function Callout({ tone, icon, children, onDismiss }: { tone?: "warn" | "pos" | "neg"; icon?: IconName; children: ReactNode; onDismiss?: () => void }) {
  return (
    <div className={tone ? `callout ${tone}` : "callout"}>
      {icon && <Icon name={icon} />}
      <div className="grow">{children}</div>
      {onDismiss && <button type="button" className="link-btn" onClick={onDismiss} aria-label="Dismiss"><Icon name="x" size="sm" /></button>}
    </div>
  );
}

/** Match % in green at 100, light green at 95 or more, amber below; plain accent otherwise. */
export function Bar({ pct, tone, label }: { pct: number; tone?: "accent" | "ok" | "good" | "warn" | "match"; label?: ReactNode }) {
  const t = tone === "match" ? (pct >= 100 ? "ok" : pct >= 95 ? "good" : "warn") : tone === "accent" ? undefined : tone;
  const w = Math.max(0, Math.min(100, pct));
  const bar = <span className="bar" role="presentation"><i className={t} style={{ width: `${w}%` }} /></span>;
  return label === undefined ? bar : <span className="barcell">{bar}<span className="v">{label}</span></span>;
}

export function DiffCell({ a, b }: { a: ReactNode; b: ReactNode }) {
  return <span className="diff"><span className="a">{a}</span><Icon name="arrow" size="sm" /><span className="b">{b}</span></span>;
}

export type TabItem<T extends string> = { label: ReactNode; value: T; count?: number | string };
/** Results tabs: a tablist of buttons, the chosen one aria-selected. */
export function Tabs<T extends string>({ items, value, onChange, label }: { items: TabItem<T>[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((t) => (
        <button key={t.value} type="button" role="tab" aria-selected={t.value === value} className={t.value === value ? "on" : undefined} onClick={() => onChange(t.value)}>
          {t.label}{t.count !== undefined && <span className="count">{typeof t.count === "number" ? num(t.count) : t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function OutcomeBar({ segments, sub }: { segments: { label: ReactNode; n: number; cls: "c-full" | "c-diff" | "c-onlya" | "c-onlyb" }[]; sub?: ReactNode }) {
  const total = segments.reduce((s, x) => s + x.n, 0) || 1;
  return (
    <div className="outcome">
      <div className="head"><span className="eyebrow">Row outcome</span>{sub && <span className="sub">{sub}</span>}</div>
      <div className="stack" role="img" aria-label={segments.map((s) => `${typeof s.label === "string" ? s.label : ""} ${num(s.n)}`).join(", ")}>
        {segments.filter((s) => s.n > 0).map((s, i) => <span key={i} className={s.cls} style={{ width: `${(100 * s.n) / total}%`, minWidth: 3 }} />)}
      </div>
      <ul className="legend">{segments.map((s, i) => <li key={i}><i className={s.cls} />{s.label} <strong>{num(s.n)}</strong></li>)}</ul>
    </div>
  );
}

/** A dashed drop area with a "choose a file" link over a hidden file input. */
export function Dropzone({ accept, onFile, title, hint, label }: { accept?: string; onFile: (f: File) => void; title: ReactNode; hint?: ReactNode; label: string }) {
  const [over, setOver] = useState(false);
  return (
    <div className={over ? "drop over" : "drop"}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) onFile(f); }}>
      <Icon name="upload" />
      <div>{title}</div>
      <div className="or">or <label className="pick">choose a file<input type="file" accept={accept} aria-label={label} onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }} /></label>{hint && <> · {hint}</>}</div>
    </div>
  );
}

/** A right-hand panel over the page: Esc and × close it, focus moves into it and back out, and
 *  the page behind is inert while it is open, so Tab and a screen reader stay inside. */
export function Drawer({ title, onClose, wide, children }: { title: ReactNode; onClose: () => void; wide?: boolean; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;            // a caller's inline arrow must not refocus the drawer each render
  useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const behind = [...(ref.current?.parentElement?.children ?? [])]
      .filter((el): el is HTMLElement => el instanceof HTMLElement && el !== ref.current && !el.classList.contains("drawer-scrim") && !el.inert);
    behind.forEach((el) => { el.inert = true; });
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") close.current(); };
    addEventListener("keydown", key);
    return () => { behind.forEach((el) => { el.inert = false; }); removeEventListener("keydown", key); back?.focus?.(); };
  }, []);
  return (
    <>
      <div className="drawer-scrim" aria-hidden="true" onClick={onClose} />
      <div ref={ref} className={wide ? "drawer wide" : "drawer"} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} tabIndex={-1}>
        <header><h2>{title}</h2><button type="button" className="icon-btn x" onClick={onClose} aria-label="Close"><Icon name="x" /></button></header>
        {children}
      </div>
    </>
  );
}

export function StatGrid({ stats }: { stats: { label: string; value: ReactNode; sub?: ReactNode }[] }) {
  return <div className="stat-grid">{stats.map((s) => <div key={s.label} className="stat"><span className="eyebrow">{s.label}</span><span className="v">{s.value}</span>{s.sub && <span className="caption">{s.sub}</span>}</div>)}</div>;
}
