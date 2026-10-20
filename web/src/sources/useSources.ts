// web/src/sources/useSources.ts
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { seedForm } from "./formStore";
import type { SourcesBody, Tag } from "./types";

export function useSources() {
  return useQuery({ queryKey: ["sources"], queryFn: async () => {
    const b = await api.get<SourcesBody>("/api/sources");
    for (const tag of Object.keys(b.sides ?? {}) as Tag[]) {   // a side the server holds names its form and picks its source -
      const v = b.sides[tag];                                    // here, not in SideCard, so the Rows editor gets it too
      if (v?.loaded) seedForm(tag, { name: v.name, how: v.is_database ? "database" : v.staged ? "upload" : "path",
                                     ...(v.is_database ? { connection: v.conn } : {}) });
    }
    return b;
  } });
}
