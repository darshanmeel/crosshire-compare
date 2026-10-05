// web/src/profiling/column/types.ts - what every per-kind column page takes from ColumnDetail.
import type { Row } from "../frame";
import type { CastRow, Profile } from "../types";

/** One column's page below its header: `as` is what the column is read as (its own type, or a
 *  date / timestamp / number its values take - see /api/profiling/casts), `cast` its row there. */
export type ColumnViewProps = { p: Profile; column: string; made: string; st: Row; as: string; cast?: CastRow };
