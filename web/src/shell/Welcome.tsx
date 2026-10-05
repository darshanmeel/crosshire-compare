import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Meta } from "../api/client";
import { getForm, setForm } from "../sources/formStore";
import { pickOf, type Tag } from "../sources/types";
import { Button } from "../ui/kit";
import type { Page } from "./usePage";
import { setView } from "./view";

const COPY = {
  Compare: {
    eyebrow: "CSV, JSON, Parquet or a database table, either side",
    h: <>Two tables, <em>every difference.</em></>,
    lede: <>Read by DuckDB, paired in one table, compared row by row on a key you choose - or let <strong>Auto</strong> work the whole thing out.</>,
    how: [
      [<strong>Load A and B.</strong>, <> Upload a file, point at a path on this machine, or pick a database table. Big file? Cut it down under <em>Rows to read</em> first.</>],
      [<strong>Pair the columns.</strong>, " Auto matches by name, then by the values themselves, detects numbers, dates and booleans, and suggests a key."],
      [<strong>Compare.</strong>, " Every differing cell, the one-sided rows, and a standalone HTML report you can attach to a ticket."],
    ],
  },
  Profiling: {
    eyebrow: "CSV, JSON, Parquet or a database table",
    h: <>One table, <em>every column.</em></>,
    lede: <>Read by DuckDB once: which column identifies a row, what stands out, the statistics of every column, its outliers, shapes and dependencies, and its most and least frequent values.</>,
    how: [
      [<strong>Load a table.</strong>, " A file on this machine, an upload, or a database table - cut it down under Rows to read if it is big."],
      [<strong>Profile.</strong>, " Every column measured; with no single-column key, pairs, threes and fours are tried."],
      [<strong>Read it.</strong>, " Key candidates, what stands out, and one page per column - then profile.csv or the six files to a folder."],
    ],
  },
} as const;

/** Read the sample file(s) through the same path flow a person uses: the form filled, Load sent. */
function useTryExample(meta?: Meta) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (tags: [Tag, string, "A" | "B"][]) => {
      for (const [tag, name, file] of tags) {
        setForm(tag, { how: "path", folder: "", path: meta!.examples![file], name });
        const f = getForm(tag);
        await api.send("POST", `/api/sources/${tag}/load`, { ...pickOf(f), name: f.name, where: f.where, order_by: f.order_by,
          desc: f.desc, limit: f.limit, column_names: f.column_names, snapshot: f.snapshot });
        qc.invalidateQueries({ queryKey: ["sources"] });
        qc.invalidateQueries({ queryKey: ["preview", tag] });
      }
    },
  });
}

/** The empty state: shown only while nothing is loaded on the page. */
export function Welcome({ page, meta, setPage }: { page: Page; meta?: Meta; setPage: (p: Page) => void }) {
  const c = COPY[page];
  const ex = useTryExample(meta);
  const [err, setErr] = useState("");
  const tryIt = () => ex.mutate(page === "Compare" ? [["A", "HR", "A"], ["B", "Payroll", "B"]] : [["P", "HR", "A"]],
    { onSuccess: () => setErr(""), onError: (e) => setErr(e instanceof ApiError ? e.detail : String(e)) });
  return (
    <section className="hero" aria-label="Welcome">
      <div>
        <span className="eyebrow accent">{meta?.app_name} · {c.eyebrow}</span>
        <h1>{c.h}</h1>
        <p>{c.lede}</p>
        <div className="row">
          {meta?.examples && (
            <Button variant="primary" icon="play" disabled={ex.isPending} onClick={tryIt}>
              {ex.isPending ? "Reading the example…" : page === "Compare" ? "Try the HR vs Payroll example" : "Try it on hr_employees.csv"}
            </Button>
          )}
          {page === "Compare"
            ? <Button onClick={() => setView({ view: "config" })}>Run from a saved config</Button>
            : <Button onClick={() => setPage("Compare")}>Compare two tables instead</Button>}
        </div>
        {err && <div className="note error">{err}</div>}
      </div>
      <ol className="how">
        {c.how.map(([b, rest], i) => <li key={i}><span className="n">{i + 1}</span><span>{b}{rest}</span></li>)}
      </ol>
    </section>
  );
}
