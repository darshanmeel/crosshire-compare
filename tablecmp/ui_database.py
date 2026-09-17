"""The Database branch of the source panel, and the Connections manager.

A database side is fetched once into a Parquet file in the work folder; from there on the
sidebar treats it like any other Parquet file. Nothing here ever shows a password: a typed
one lives in st.session_state["db_passwords"] for the session and nowhere else.
"""
from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from . import connections as cx
from . import databases as db
from . import ui_log
from .sources import Side, work_dir

EXTRAS = {"snowflake": ["warehouse", "role", "authenticator"], "databricks": ["http_path", "token", "catalog"],
          "oracle": ["service_name"], "mssql": [], "postgresql": [], "duckdb": []}
FIELDS = {"snowflake": ["host", "user", "password", "database", "schema"],
          "databricks": ["host", "schema"], "mssql": ["host", "port", "database", "user", "password"],
          "oracle": ["host", "port", "user", "password"], "postgresql": ["host", "port", "database", "user", "password"],
          "duckdb": ["host"]}
LABELS = {"host": "Host", "port": "Port", "database": "Database", "schema": "Schema", "user": "User",
          "password": "Password", "warehouse": "Warehouse", "role": "Role", "authenticator": "Authenticator (optional)",
          "http_path": "HTTP path", "token": "Access token", "catalog": "Catalog", "service_name": "Service name"}
HOST_LABEL = {"snowflake": "Account", "databricks": "Server hostname", "mssql": "Server", "duckdb": "File path"}
NEW = "New connection"
CAP_DEFAULT = 1_000_000
ALL_EXTRAS = sorted({e for es in EXTRAS.values() for e in es})


def _passwords() -> dict[str, str]:
    return st.session_state.setdefault("db_passwords", {})


def _held(tag: str):
    """(key, parquet path, what, fetched_at, rows, capped) of the fetch this side holds, or None."""
    return st.session_state.get(f"fetched_{tag}")


def _unlink_unless_loaded(tag: str, path: str) -> None:
    """A replaced fetch file goes - unless the loaded side still reads it (the sweep gets it later)."""
    side = st.session_state.get(tag)
    if path and not (side is not None and getattr(side, "csv_path", "") == path):
        Path(path).unlink(missing_ok=True)


def source_panel(tag: str) -> tuple[str, str, Side | None]:
    """Connection, table or SQL, cap, Fetch. Returns (parquet path, label, side with origin) once fetched."""
    if tag == "B" and st.session_state.pop("_same_as_A", False):
        # before any B widget exists this run - after that their state cannot be written
        for k in ("conn", "dbmode", "tbl", "sql", "cap"):
            if f"{k}_A" in st.session_state:
                st.session_state[f"{k}_B"] = st.session_state[f"{k}_A"]
    try:
        conns = cx.load_all()
    except ValueError as exc:                    # a connections file that is not valid JSON
        st.error(str(exc))
        return "", "", None
    names = sorted(conns)
    if not names:
        st.info("No connections yet - make one under **Connections** below.")
        return "", "", None
    if st.session_state.get(f"conn_{tag}") not in names:      # deleted or renamed since it was picked
        st.session_state.pop(f"conn_{tag}", None)
    name = st.selectbox("Connection", names, key=f"conn_{tag}",
                        format_func=lambda n: f"{n} · {conns[n].label} · {conns[n].where}")
    c = conns[name]
    if st.session_state.get(f"_pw_for_{tag}") != name:        # a password typed for another connection
        st.session_state.pop(f"pw_{tag}", None)
        st.session_state[f"_pw_for_{tag}"] = name
    if c.password is None and c.kind != "duckdb":
        pw = st.text_input("Password - kept for this session only", type="password", key=f"pw_{tag}")
        if pw:
            _passwords()[name] = pw
    mode = st.radio("Read", ["Table", "SQL query"], horizontal=True, key=f"dbmode_{tag}", label_visibility="collapsed")
    if mode == "Table":
        what = (st.text_input("Table", key=f"tbl_{tag}", placeholder="hr.employees") or "").strip()
        try:
            sql = db.table_sql(c.kind, what) if what else ""
        except ValueError as exc:
            st.error(str(exc))
            sql = ""
    else:
        sql = (st.text_area("SQL - SELECT or WITH only", key=f"sql_{tag}", height=110,
                            placeholder="SELECT emp_id, first_name, department, hire_date\n"
                                        "FROM hr.employees\nWHERE hire_date >= '2026-01-01'") or "").strip()
        what = "query"
    c1, c2 = st.columns([1, 1])
    st.session_state.setdefault(f"cap_{tag}", CAP_DEFAULT)
    cap = int(c1.number_input("Fetch at most (0 = all)", 0, 1_000_000_000, step=100_000, key=f"cap_{tag}"))
    if tag == "B" and st.session_state.get("how_A") == "Database":
        c2.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
        if c2.button("Same SQL as A", key="same_as_A", width="stretch",
                     help="Copy the connection, the table or SQL and the cap from side A."):
            st.session_state["_same_as_A"] = True
            st.rerun()
    key = (name, " ".join(sql.split()), cap)
    held = _held(tag)
    if held and held[0] == key and Path(held[1]).exists():
        st.caption(f"Fetched at {held[3]} - {held[4]:,} rows" + (" · capped" if held[5] else ""))
        if st.button("Fetch again", key=f"refetch_{tag}", width="stretch"):
            _unlink_unless_loaded(tag, held[1])
            st.session_state.pop(f"fetched_{tag}", None)
            st.rerun()
    else:
        if cap and sql and not db.has_order_by(sql):
            st.warning("A cap without an ORDER BY can give the two sides different rows - "
                       "add ORDER BY, or fetch everything.")
        if st.button("Fetch" if tag == "P" else f"Fetch {tag}", key=f"fetch_{tag}", type="primary",
                     width="stretch", disabled=not sql):
            done = False
            try:
                conn = cx.resolve(name, _passwords())
                path = work_dir() / f"fetch_{tag}_{int(time.time())}.parquet"
                with ui_log.running(f"Fetching from {name}…", "Fetch") as box:
                    r = db.fetch_parquet(conn, sql, str(path), cap, progress=box.write)
                    box.update(label=f"Fetched {r.rows:,} rows in {r.seconds:.1f}s", state="complete")
                if held:
                    _unlink_unless_loaded(tag, held[1])
                st.session_state[f"fetched_{tag}"] = (key, str(path), what, time.strftime("%H:%M:%S"),
                                                      r.rows, r.capped)
                done = True
            except cx.PasswordNeeded:
                st.error("Type the password above first.")
            except (db.NotReadOnly, db.DriverMissing) as exc:
                st.error(str(exc))
            except Exception as exc:                       # noqa: BLE001 - a driver's own error, redacted
                st.error("The fetch failed - " + cx.redact(exc))
            if done:
                st.rerun()
        return "", "", None
    side = Side(conn=name, database=c.kind, query=sql, fetched_at=held[3], cap=cap, capped=held[5],
                origin=db.origin_of(c, held[2] if held[2] != "query" else sql))
    return held[1], f"{name}.parquet", side


# ---- the Connections manager --------------------------------------------------------
def _seed_form(cur: cx.Connection | None) -> None:
    """Fill the form's state from the picked connection - before its widgets exist this run.
    A saved password is never put into a box."""
    kind = cur.kind if cur else "snowflake"
    st.session_state["cf_kind"] = kind
    st.session_state["cf_name"] = cur.name if cur else ""
    for f in ("host", "database", "schema", "user"):
        st.session_state[f"cf_{f}"] = getattr(cur, f, "") if cur else ""
    st.session_state["cf_port"] = int(cur.port) if cur and cur.port else int(cx.DEFAULT_PORTS.get(kind, 0))
    st.session_state["cf_password"] = ""
    st.session_state["cf_save_pw"] = bool(cur.password is not None) if cur else True
    st.session_state["cf_timeout"] = int(cur.timeout) if cur else cx.DEFAULT_TIMEOUT
    for e in ALL_EXTRAS:
        st.session_state[f"cf_{e}"] = (cur.extra.get(e, "") if cur else "")


def manager() -> None:
    with st.expander("Connections", expanded=False):
        try:
            conns = cx.load_all()
        except ValueError as exc:
            st.error(str(exc))
            return
        for n, c in sorted(conns.items()):
            pw = ("env · read-only" if c.source == "env" else
                  "password saved" if c.password is not None else "password asked each session")
            st.markdown(f"**{n}** · {c.label} · {c.where} · {pw}")
        if not conns:
            st.caption("None yet. Fill the form and press Save - or set COMPARE_CONN_<NAME>=<uri> "
                       "in the environment.")
        saved = st.session_state.pop("_conn_saved", None)
        if saved:
            st.success(f"Saved {saved}")
        editable = [n for n, c in sorted(conns.items()) if c.source == "file"]
        if st.session_state.pop("_conn_pick_reset", False) or st.session_state.get("conn_pick", NEW) not in [NEW] + editable:
            st.session_state["conn_pick"] = NEW
        pick = st.selectbox("Edit", [NEW] + editable, key="conn_pick")
        cur = conns.get(pick) if pick != NEW else None
        if st.session_state.get("_cf_pick") != pick or "cf_kind" not in st.session_state:
            _seed_form(cur)
            st.session_state["_cf_pick"] = pick
        kind = st.selectbox("Kind", list(cx.KINDS), key="cf_kind", format_func=cx.KINDS.get)
        name = st.text_input("Name", key="cf_name", help="letters, digits, _ and -")
        vals: dict[str, object] = {}
        for f in FIELDS[kind]:
            label = HOST_LABEL.get(kind, LABELS["host"]) if f == "host" else LABELS[f]
            if f == "password":
                vals[f] = st.text_input(label, type="password", key="cf_password",
                                        placeholder="unchanged" if cur and cur.password is not None else "")
            elif f == "port":
                vals[f] = st.number_input(label, 0, 65535, key="cf_port")
            else:
                vals[f] = st.text_input(label, key=f"cf_{f}")
        for e in EXTRAS[kind]:
            vals[e] = st.text_input(LABELS[e], key=f"cf_{e}", type="password" if e == "token" else "default")
        save_pw = st.checkbox("Save password", key="cf_save_pw",
                              help="Unticked: the password is asked for once per session and never written to disk.")
        timeout = int(st.number_input("Query timeout, seconds", 10, 86400, key="cf_timeout"))
        typed_pw = str(vals.pop("password", "") or "")
        password = typed_pw or (cur.password if cur else None) or _passwords().get(name.strip())
        if kind == "databricks" and vals.get("token"):
            password = str(vals["token"])
        conn = cx.Connection(name=name.strip(), kind=kind, host=str(vals.get("host", "") or ""),
                             port=int(vals["port"]) if vals.get("port") else None,
                             database=str(vals.get("database", "") or ""), schema=str(vals.get("schema", "") or ""),
                             user=str(vals.get("user", "") or ""), password=password if save_pw else None,
                             extra={e: str(vals.get(e, "")) for e in EXTRAS[kind] if vals.get(e)},
                             timeout=timeout)
        b1, b2, b3 = st.columns(3)
        if b1.button("Test", key="test_conn", width="stretch"):
            probe = cx.Connection(**{**conn.__dict__, "password": password})
            r = db.test(probe)
            st.session_state["conn_test"] = (conn.name, r.ok, r.message)
        last = st.session_state.get("conn_test")
        if last and last[0] == conn.name:
            (st.success if last[1] else st.error)(last[2])
        if b2.button("Save", key="conn_save", type="primary", width="stretch"):
            try:
                cx.save(conn)
                if not save_pw and password:
                    _passwords()[conn.name] = password
                st.session_state["_conn_saved"] = conn.name
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if cur and b3.button("Delete", key="conn_delete", width="stretch"):
            cx.delete(cur.name)
            st.session_state["_conn_pick_reset"] = True
            st.rerun()
