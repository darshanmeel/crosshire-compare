// web/src/setup/contract.test.tsx
import { act, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { vi } from "vitest";
import { SETUP_KEY, STALE_TABLE, useSetupSend, type SetupView } from "./api";
import { FrameTable } from "./FrameTable";
import { json, mount, setup } from "./testkit";

test("a measured table shows its columns and rows, nulls blank, numbers grouped", () => {
  mount(<FrameTable label="Report" frame={{ columns: ["Side", "Rows", "Note"], rows: [["HR", 3000, null]] }} />);
  expect(screen.getByRole("columnheader", { name: "Rows" })).toBeInTheDocument();
  expect(screen.getByText("3,000")).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Report" }).querySelector("td.null")).not.toBeNull();
});

test("a setup write puts the view it answers with in place, and a 409 fetches the table again", async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  const after = setup({ keys: ["emp_id"] });
  let stale = false;
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) =>
    stale ? json({ detail: STALE_TABLE }, 409) : json(init?.method === "POST" ? after : setup())));
  const { result } = renderHook(() => useSetupSend(), { wrapper });
  await act(() => result.current.mutateAsync({ path: "/cell", body: { rev: "1.a", row: 0, column: "Key", value: true } }));
  expect((qc.getQueryData(SETUP_KEY) as SetupView & { keys: string[] }).keys).toEqual(["emp_id"]);
  stale = true;
  const spy = vi.spyOn(qc, "invalidateQueries");
  await act(async () => { await result.current.mutateAsync({ path: "/cell", body: {} }).catch(() => undefined); });
  await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: SETUP_KEY }));
});
