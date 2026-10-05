import { ApiError } from "../api/client";
import { marks } from "../ui/marks";

/** A view that could not be built, said in the server's sentence. */
export function Failed({ error }: { error: unknown }) {
  return <div className="note error">{marks(error instanceof ApiError ? error.detail : String(error))}</div>;
}
