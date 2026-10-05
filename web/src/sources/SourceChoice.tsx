// web/src/sources/SourceChoice.tsx - Upload / Path on disk / Database. It looks like the segmented
// control of the mockups but is a radiogroup of real radio inputs, so "Path on disk" stays a label a
// test (or a keyboard) can check.
import type { How, Tag } from "./types";

const HOW: [How, string][] = [["upload", "Upload"], ["path", "Path on disk"], ["database", "Database"]];

export function SourceChoice({ tag, value, onChange }: { tag: Tag; value: How; onChange: (h: How) => void }) {
  return (
    <div className="src-seg" role="radiogroup" aria-label={tag === "P" ? "Source" : `Source for ${tag}`}>
      {HOW.map(([h, label]) => (
        <label key={h} className={value === h ? "on" : undefined}>
          <input type="radio" name={`how_${tag}`} checked={value === h} onChange={() => onChange(h)} />{label}
        </label>
      ))}
    </div>
  );
}

/** A two-way choice inside a card (A table / SQL query), on the same radio-backed segmented look. */
export function RadioSeg<T extends string>({ name, label, options, value, onChange }:
  { name: string; label: string; options: [T, string][]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="src-seg" role="radiogroup" aria-label={label}>
      {options.map(([v, text]) => (
        <label key={v} className={value === v ? "on" : undefined}>
          <input type="radio" name={name} checked={value === v} onChange={() => onChange(v)} />{text}
        </label>
      ))}
    </div>
  );
}
