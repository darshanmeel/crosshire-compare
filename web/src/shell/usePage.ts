import { useEffect, useState } from "react";

export type Page = "Compare" | "Profiling";
const read = (): Page => (location.hash === "#profiling" ? "Profiling" : "Compare");

export function usePage(): [Page, (p: Page) => void] {
  const [page, setPage] = useState<Page>(read);
  useEffect(() => {
    const on = () => setPage(read());
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return [page, (p) => { location.hash = p === "Profiling" ? "#profiling" : ""; setPage(p); }];
}
