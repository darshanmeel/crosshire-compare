// web/src/sources/NoteLine.tsx
import { marks } from "../ui/marks";
import type { Note } from "./types";
import { ToneNote } from "../ui/kit";

export function NoteLine({ note }: { note: Note }) {
  return note.tone === "caption"
    ? <p className="caption">{marks(note.text)}</p>
    : <ToneNote tone={note.tone}>{marks(note.text)}</ToneNote>;
}
