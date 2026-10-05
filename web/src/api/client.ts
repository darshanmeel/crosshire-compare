export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(detail); }
}

async function parse<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new ApiError(r.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const type = r.headers.get("Content-Type") ?? "";
  return (type.includes("json") ? r.json() : r.text()) as Promise<T>;
}

export const api = {
  get: <T>(path: string) => fetch(path, { credentials: "same-origin" }).then((r) => parse<T>(r)),
  send: <T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown) =>
    fetch(path, {
      method, credentials: "same-origin",
      headers: { "X-Compare": "1", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then((r) => parse<T>(r)),
  upload: <T>(path: string, file: Blob) =>
    fetch(path, {
      method: "POST", credentials: "same-origin",
      headers: { "X-Compare": "1", "Content-Type": "application/octet-stream" }, body: file,
    }).then((r) => parse<T>(r)),
};

export type LogEntry = { id: string; at: string; kind: string; label: string; state: "running" | "done" | "error"; seconds: number | null; lines: string[]; page: string; slot?: string };
export type Meta = {
  app_name: string; tagline: string; theme: string; mode?: "light" | "dark"; kinds: Record<string, string>; form: FormSpec; filepick: boolean;
  examples?: { A: string; B: string } | null;     // the sample pair's paths, when it is installed beside the app
};
export type FormSpec = {
  fields: Record<string, string[]>; extras: Record<string, string[]>; labels: Record<string, string>;
  password_label: Record<string, string>; secret_extras: string[]; host_label: Record<string, string>;
  default_ports: Record<string, number>; default_timeout: number; cap_default: number;
};
