import { expect, test, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mount } from "../setup/testkit";
import { EngineLimits, type EngineView } from "./EngineLimits";

const VIEW: EngineView = { memory: "2GB", memory_from: "default", disk: "20GB", disk_from: "default",
  machine_memory: 16 * 2 ** 30, default_memory: "2GB", default_disk: "20GB" };

test("the limits show, a change is saved with Save limits, and a refusal is said", async () => {
  const puts: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const b = JSON.parse(init.body as string);
      puts.push(b);
      if (b.memory === "10MB") return new Response(JSON.stringify({ detail: "Memory must be at least 256MB" }), { status: 422 });
      return json({ ...VIEW, ...b, memory_from: "saved", disk_from: "saved" });
    }
    return json(VIEW);
  }));
  mount(<EngineLimits />);
  const mem = await screen.findByLabelText("DuckDB memory");
  expect(mem).toHaveValue("2GB");
  expect(screen.getByLabelText("Spill to disk at most")).toHaveValue("20GB");
  expect(screen.queryByRole("button", { name: "Save limits" })).toBeNull();
  await userEvent.clear(mem);
  await userEvent.type(mem, "10MB");
  await userEvent.click(screen.getByRole("button", { name: "Save limits" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Memory must be at least 256MB");
  await userEvent.clear(mem);
  await userEvent.type(mem, "4GB");
  await userEvent.click(screen.getByRole("button", { name: "Save limits" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Save limits" })).toBeNull());
  expect(puts.at(-1)).toEqual({ memory: "4GB", disk: "20GB" });
  expect(mem).toHaveValue("4GB");
});

test("a limit fixed on the machine cannot be edited here", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ ...VIEW, memory: "8GB", memory_from: "env" })));
  mount(<EngineLimits />);
  expect(await screen.findByLabelText("DuckDB memory")).toBeDisabled();
  expect(screen.getByLabelText("Spill to disk at most")).toBeEnabled();
});
