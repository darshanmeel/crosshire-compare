import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { ConnectionsDrawer } from "./ConnectionsDrawer";
import type { Meta } from "../api/client";

const META: Meta = {
  app_name: "X", tagline: "", theme: "aurora", filepick: false,
  kinds: { postgresql: "PostgreSQL", folder: "Folder", databricks: "Databricks" },
  form: {
    fields: { postgresql: ["host", "port", "database", "user", "password"], folder: ["host"], databricks: ["host", "schema"] },
    extras: { postgresql: [], folder: [], databricks: ["http_path", "token", "catalog"] },
    labels: { host: "Host", port: "Port", database: "Database", user: "User", password: "Password", schema: "Schema", http_path: "HTTP path", token: "Access token", catalog: "Catalog" },
    password_label: {}, secret_extras: ["token", "private_key_pwd"], host_label: { folder: "Folder path", databricks: "Server hostname" },
    default_ports: { postgresql: 5432 }, default_timeout: 600, cap_default: 1000000,
  },
};

const ROWS = [
  { name: "PG", kind: "postgresql", label: "PostgreSQL", where: "db.local/hr", source: "file", origin_file: "", is_folder: false, editable: true, password: "saved" },
  { name: "TEAM", kind: "postgresql", label: "PostgreSQL", where: "t/hr", source: "shared", origin_file: "C:/x/team.yml", is_folder: false, editable: false, password: "shared" },
  { name: "HELD", kind: "postgresql", label: "PostgreSQL", where: "h/hr", source: "file", origin_file: "", is_folder: false, editable: true, password: "session" },
];
const PG = { name: "PG", kind: "postgresql", host: "db.local", port: 5432, database: "hr", schema: "", user: "me", timeout: 600, extra: {}, password_ref: "${PG_PW}", has_password: true, save_password: true };

type Calls = [string, RequestInit | undefined][];
function server(calls: Calls, test = { ok: true, message: "OK - me · 0.1 s", seconds: 0.1 }) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
    if (url === "/api/connections" && !init?.method) return json(ROWS);
    if (url === "/api/connections/PG" && !init?.method) return json(PG);
    if (url === "/api/connections/test") return json(test);
    if (url === "/api/connections/import/preview") return json([{ name: "NEWDB", label: "PostgreSQL", where: "n/db", replaces: false }]);
    if (url === "/api/connections/import") return json({ names: ["NEWDB"] });
    if (url.startsWith("/api/connections/") && init?.method === "PUT") return json({ saved: "X" });
    return json({});
  });
}
const sent = (calls: Calls, url: string, method: string) => {
  const c = calls.find(([u, i]) => u === url && i?.method === method);
  return c && JSON.parse((c[1]!.body as string) ?? "null");
};

function mount(qc = new QueryClient(), onClose = vi.fn()) {
  render(<QueryClientProvider client={qc}><ConnectionsDrawer meta={META} onClose={onClose} /></QueryClientProvider>);
  return onClose;
}
const form = () => screen.getByRole("form");

test("the drawer is a dialog called Connections; Esc and the × close it", async () => {
  vi.stubGlobal("fetch", server([]));
  const onClose = mount();
  expect(screen.getByRole("dialog", { name: "Connections" })).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalledTimes(2);
});

test("each saved connection is a card with its kind, status, URI and where its password lives; a shared one has no Edit", async () => {
  vi.stubGlobal("fetch", server([]));
  mount();
  const list = await screen.findByRole("list", { name: "Saved connections" });
  const pg = within(list).getByRole("listitem", { name: "PG" });
  expect(within(pg).getByText("db.local/hr")).toBeInTheDocument();
  expect(within(pg).getByText("Not tested")).toBeInTheDocument();
  expect(within(pg).getByText(/password saved/)).toBeInTheDocument();
  const team = within(list).getByRole("listitem", { name: "TEAM" });
  expect(within(team).getByText(/from team.yml · read-only/)).toBeInTheDocument();
  expect(within(team).queryByRole("button", { name: /Edit/ })).toBeNull();
  expect(screen.getByText("COMPARE_CONNECTIONS")).toBeInTheDocument();
  expect(screen.getByText("COMPARE_DATA_DIR")).toBeInTheDocument();
});

test("Test on a card tests the saved connection and its pill says Connected or Failed", async () => {
  const calls: Calls = [];
  vi.stubGlobal("fetch", server(calls, { ok: false, message: "password authentication failed", seconds: 0.1 }));
  mount();
  const pg = await screen.findByRole("listitem", { name: "PG" });
  await userEvent.click(within(pg).getByRole("button", { name: "Test PG" }));
  expect(await within(pg).findByText("Failed")).toBeInTheDocument();
  expect(within(pg).getByText("password authentication failed")).toBeInTheDocument();
  expect(sent(calls, "/api/connections/test", "POST")).toMatchObject({ name: "PG", host: "db.local", password: "${PG_PW}" });
});

test("a password held this session can be forgotten from its card", async () => {
  const calls: Calls = [];
  vi.stubGlobal("fetch", server(calls));
  mount();
  const held = await screen.findByRole("listitem", { name: "HELD" });
  await userEvent.click(within(held).getByRole("button", { name: "Forget the password" }));
  await waitFor(() => expect(calls.some(([u, i]) => u === "/api/connections/HELD/password" && i?.method === "DELETE")).toBe(true));
});

test("a folder has a path and nothing else", async () => {
  vi.stubGlobal("fetch", server([]));
  mount();
  await userEvent.selectOptions(await screen.findByLabelText("Driver"), "folder");
  expect(screen.getByLabelText("Folder path")).toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "Where the password lives" })).toBeNull();
  expect(screen.queryByLabelText(/timeout/i)).toBeNull();
});

test("a folder saved here is offered under Path on disk at once", async () => {
  vi.stubGlobal("fetch", server([]));
  const qc = new QueryClient();
  qc.setQueryData(["folders"], []);                      // what Path on disk read before the save
  mount(qc);
  await userEvent.selectOptions(await screen.findByLabelText("Driver"), "folder");
  await userEvent.type(within(form()).getByLabelText("Name"), "DATA");
  await userEvent.type(screen.getByLabelText("Folder path"), "D:/data");
  await userEvent.click(within(form()).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(qc.getQueryState(["folders"])?.isInvalidated).toBe(true));
});

test("Edit fills the form; a ${NAME} reference shows as the variable and Save sends it back as written", async () => {
  const calls: Calls = [];
  vi.stubGlobal("fetch", server(calls));
  mount();
  const pg = await screen.findByRole("listitem", { name: "PG" });
  await userEvent.click(within(pg).getByRole("button", { name: "Edit PG" }));
  expect(await screen.findByRole("form", { name: "Edit PG" })).toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText("Password")).toHaveValue("PG_PW"));
  expect(within(screen.getByRole("group", { name: "Where the password lives" })).getByRole("button", { name: "Environment variable" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(form()).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(sent(calls, "/api/connections/PG", "PUT")).toBeTruthy());
  expect(sent(calls, "/api/connections/PG", "PUT")).toMatchObject({ kind: "postgresql", host: "db.local", port: 5432, password: "${PG_PW}", save_password: true });
  const put = calls.find(([u, i]) => u === "/api/connections/PG" && i?.method === "PUT")!;
  expect((put[1]!.headers as Record<string, string>)["X-Compare"]).toBe("1");
});

test("where the password lives decides save_password: the session keeps it off disk, the file writes it", async () => {
  const calls: Calls = [];
  vi.stubGlobal("fetch", server(calls));
  mount();
  await userEvent.type(within(await screen.findByRole("form")).getByLabelText("Name"), "N1");
  await userEvent.type(screen.getByLabelText("Password"), "pw-typed");
  expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
  await userEvent.click(within(form()).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(sent(calls, "/api/connections/N1", "PUT")).toMatchObject({ password: "pw-typed", save_password: false }));
  await userEvent.click(await screen.findByRole("button", { name: "New connection" }));
  await userEvent.type(within(screen.getByRole("form", { name: "Add a connection" })).getByLabelText("Name"), "N2");
  await userEvent.click(screen.getByRole("button", { name: "In the file" }));
  await userEvent.type(screen.getByLabelText("Password"), "pw2");
  await userEvent.click(within(form()).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(sent(calls, "/api/connections/N2", "PUT")).toMatchObject({ password: "pw2", save_password: true }));
});

test("Test connection shows what the server said and marks the card", async () => {
  vi.stubGlobal("fetch", server([]));
  mount();
  const pg = await screen.findByRole("listitem", { name: "PG" });
  await userEvent.click(within(pg).getByRole("button", { name: "Edit PG" }));
  await screen.findByRole("form", { name: "Edit PG" });
  await userEvent.click(screen.getByRole("button", { name: "Test connection" }));
  expect(await screen.findByText(/OK - me/)).toBeInTheDocument();
  expect(within(pg).getByText("Connected")).toBeInTheDocument();
});

test("Delete removes the connection being edited", async () => {
  const calls: Calls = [];
  vi.stubGlobal("fetch", server(calls));
  mount();
  await userEvent.click(within(await screen.findByRole("listitem", { name: "PG" })).getByRole("button", { name: "Edit PG" }));
  await userEvent.click(await within(await screen.findByRole("form", { name: "Edit PG" })).findByRole("button", { name: "Delete" }));
  await waitFor(() => expect(calls.some(([u, i]) => u === "/api/connections/PG" && i?.method === "DELETE")).toBe(true));
  expect(await screen.findByRole("form", { name: "Add a connection" })).toBeInTheDocument();
});

test("a connections file is previewed, then added; mine can be downloaded without passwords", async () => {
  const calls: Calls = [];
  vi.stubGlobal("fetch", server(calls));
  mount();
  await screen.findByRole("list", { name: "Saved connections" });
  const file = new File(["- {name: NEWDB, kind: postgresql}"], "team.yml", { type: "text/yaml" });
  await userEvent.upload(screen.getByLabelText("Connections file"), file);
  expect(await screen.findByText("NEWDB")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Add 1 connection" }));
  expect(await screen.findByText("Saved NEWDB")).toBeInTheDocument();
  expect(sent(calls, "/api/connections/import", "POST")).toMatchObject({ filename: "team.yml", keep_passwords: false });
  expect(screen.getByRole("link", { name: /Download mine/ })).toHaveAttribute("href", "/api/connections/export");
});
