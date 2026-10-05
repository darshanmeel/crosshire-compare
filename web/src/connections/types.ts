import type { QueryClient } from "@tanstack/react-query";
import type { FormSpec } from "../api/client";

export type ConnRow = { name: string; kind: string; label: string; where: string; source: "file" | "env" | "shared"; origin_file: string; is_folder: boolean; editable: boolean; password: "env" | "shared" | "folder" | "key file" | "saved" | "session" | "asked" };
export type ConnForm = { name: string; kind: string; host: string; port: number | null; database: string; schema: string; user: string; timeout: number; extra: Record<string, string>; password_ref: string; has_password: boolean; save_password: boolean };
export type Tested = { ok: boolean; message: string };
/** Where a password lives: written in the connections file, held for this session only, or read from an environment variable. */
export type PwWhere = "file" | "session" | "env";
export const NEW = "New connection";

export function passwordText(r: ConnRow): string {
  switch (r.password) {
    case "env": return "env · read-only";
    case "shared": return `from ${r.origin_file.split(/[\\/]/).pop()} · read-only`;
    case "folder": return "pick files under Path on disk";
    case "key file": return "private key file";
    case "saved": return "password saved";
    case "session": return "password held this session";
    default: return "password asked each session";
  }
}

/** `${NAME}` -> NAME; anything else -> null. */
export const envName = (v: string | undefined) => /^\$\{([^}]+)\}$/.exec((v ?? "").trim())?.[1] ?? null;

/** What PUT /api/connections/{name} and POST /test take, from the form's boxes. */
export function connBody(f: FormSpec, v: Record<string, string>, where: PwWhere) {
  const kind = v.kind;
  const isFolder = kind === "folder";
  return {
    kind, host: v.host ?? "", port: v.port ? Number(v.port) : (f.default_ports[kind] ?? null), database: v.database ?? "",
    schema: v.schema ?? "", user: v.user ?? "", password: v.password || null, save_password: isFolder || where !== "session",
    extra: Object.fromEntries((f.extras[kind] ?? []).map((e) => [e, v[e] ?? ""])), timeout: Number(v.timeout || f.default_timeout),
  };
}

/** A saved connection's own form as a test body: blank secrets keep the written (or held) ones on the server. */
export function savedBody(c: ConnForm) {
  return { kind: c.kind, host: c.host, port: c.port, database: c.database, schema: c.schema, user: c.user,
           password: c.password_ref || null, save_password: c.save_password, extra: c.extra, timeout: c.timeout };
}

/** After a save, delete or import: every list built from the connections, the folders Path on disk offers too. */
export function refreshConnections(qc: QueryClient) {
  for (const key of ["connections", "connection", "folders", "folder-files"]) qc.invalidateQueries({ queryKey: [key] });
}
