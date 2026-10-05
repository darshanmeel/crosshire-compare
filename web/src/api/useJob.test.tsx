// web/src/api/useJob.test.tsx
import { screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { json, mount } from "../setup/testkit";
import { JOB_GONE, useJob, useJobOfKind } from "./useJob";

function Follow({ id, onEnd }: { id: string; onEnd: (s: string) => void }) {
  const e = useJob(id, (x) => onEnd(x.lines.at(-1) ?? ""));
  return <p>{e?.state ?? "waiting"}</p>;
}

test("a job the server does not know ends with a sentence and is not polled again", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => { calls.push(url); return json({ detail: "No such job in this workspace." }, 404); }));
  const ended: string[] = [];
  mount(<Follow id="gone1" onEnd={(s) => ended.push(s)} />);
  expect(await screen.findByText("error")).toBeInTheDocument();
  await waitFor(() => expect(ended).toEqual([JOB_GONE]));
  await new Promise((r) => setTimeout(r, 1300));
  expect(calls.filter((u) => u === "/api/jobs/gone1")).toHaveLength(1);
});

function Resume({ onEnd }: { onEnd: () => void }) {
  const { busy, running } = useJobOfKind("Profile", "Compare", "", onEnd);
  return <p>{busy ? `busy: ${running?.label ?? "…"}` : "idle"}</p>;
}

test("a mount finds the running job of its kind in the Log and follows it", async () => {
  const mk = (state: string, kind = "Profile") =>
    ({ id: "p9", at: "10:00:00", kind, label: "Profiling…", state, seconds: null, lines: [], page: "Compare", slot: "" });
  let ended = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/log") return json({ entries: [mk("running"), { ...mk("running", "Key search"), id: "k9" }], last: {} });
    return json(mk(ended ? "done" : "running"));
  }));
  mount(<Resume onEnd={() => { ended += 1; }} />);
  expect(await screen.findByText("busy: Profiling…")).toBeInTheDocument();
});
