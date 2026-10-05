// web/src/sources/useSources.ts
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SourcesBody } from "./types";

export function useSources() {
  return useQuery({ queryKey: ["sources"], queryFn: () => api.get<SourcesBody>("/api/sources") });
}
