import { errorText } from "../api/client";
import { marks } from "../ui/marks";
import { ErrorNote } from "../ui/kit";

/** A view that could not be built, said in the server's sentence. */
export function Failed({ error }: { error: unknown }) {
  return <ErrorNote>{marks(errorText(error))}</ErrorNote>;
}
