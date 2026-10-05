// web/src/sources/NoteLine.tsx
import { marks } from "../ui/marks";
import type { Note } from "./types";

export function NoteLine({ note }: { note: Note }) {
  return note.tone === "caption"
    ? <p className="caption">{marks(note.text)}</p>
    : <div className={`note ${note.tone}`}>{marks(note.text)}</div>;
}
