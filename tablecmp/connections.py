"""Named database connections, the way Airflow keeps them: a name, a kind, where it is.

Made in the sidebar, kept in connections.json in the user's home folder (never in the repo),
and overridable one by one with COMPARE_CONN_<NAME>=<uri>. The URI form is Airflow's:

    snowflake://USER:PASS@ACCOUNT/DB/SCHEMA?warehouse=WH&role=R
    databricks://token:TOKEN@host/?http_path=/sql/1.0/warehouses/x&catalog=c&schema=s
    mssql://user:pass@server:1433/db
    oracle://user:pass@host:1521/?service_name=X
    postgresql://user:pass@host:5432/db
    duckdb:///C:/data/sample.duckdb

For duckdb the path is everything after ``duckdb:///`` exactly as written, so
``duckdb:///examples/sample.duckdb`` is relative to the working folder.

Windows upper-cases environment variable names, so ``COMPARE_CONN_prod`` arrives as
``COMPARE_CONN_PROD``. An env connection therefore overrides a file connection whose name
matches ignoring case, and takes the file's spelling; a name the file does not know is used
as the environment hands it over.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

KINDS = {"snowflake": "Snowflake", "databricks": "Databricks", "mssql": "SQL Server",
         "oracle": "Oracle", "postgresql": "Postgres", "duckdb": "DuckDB file"}
DEFAULT_PORTS = {"mssql": 1433, "oracle": 1521, "postgresql": 5432}
DEFAULT_TIMEOUT = 600
ENV_PREFIX = "COMPARE_CONN_"
NAME_OK = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class Connection:
    name: str
    kind: str
    host: str = ""                  # account (Snowflake), host, server - or the file path (duckdb)
    port: int | None = None
    database: str = ""
    schema: str = ""
    user: str = ""
    password: str | None = None     # None: not saved - asked for in the session
    extra: dict[str, str] = field(default_factory=dict)
    timeout: int = DEFAULT_TIMEOUT  # query timeout in seconds
    source: str = "file"            # file | env

    @property
    def label(self) -> str:
        return KINDS.get(self.kind, self.kind)

    @property
    def where(self) -> str:
        """One line for lists: host and database, never a credential."""
        if self.kind == "duckdb":
            return self.host
        bits = [self.host + (f":{self.port}" if self.port else "")]
        if self.database:
            bits.append(self.database + (f".{self.schema}" if self.schema else ""))
        for k in ("warehouse", "http_path", "service_name"):
            if self.extra.get(k):
                bits.append(self.extra[k])
        return " - ".join(b for b in bits if b)


class PasswordNeeded(Exception):
    def __init__(self, name: str):
        super().__init__(f"Connection {name} has no saved password")
        self.name = name


# ---- URI form -------------------------------------------------------------------------

def to_uri(c: Connection) -> str:
    if c.kind == "duckdb":
        return "duckdb:///" + c.host
    auth = quote(c.user, safe="") if c.user else ""
    if c.password is not None:
        auth += ":" + quote(c.password, safe="")
    netloc = (auth + "@" if auth else "") + c.host + (f":{c.port}" if c.port else "")
    path = "/" + "/".join(quote(p, safe="") for p in (c.database, c.schema) if p)
    # safe="/" keeps http_path readable; parse_qsl reads either spelling back the same way
    query = urlencode({k: v for k, v in c.extra.items() if v}, safe="/")
    if c.timeout != DEFAULT_TIMEOUT:
        query += ("&" if query else "") + f"timeout={c.timeout}"
    return f"{c.kind}://{netloc}{path}" + (f"?{query}" if query else "")


def _split_netloc(netloc: str) -> tuple[str, str | None, str, int | None]:
    """user, password, host, port - by hand, so the host keeps its case (urlsplit lowercases
    it) and a bad port is a clear ValueError rather than a surprise later."""
    auth, _, hostport = netloc.rpartition("@")
    user, password = "", None
    if auth:
        u, sep, p = auth.partition(":")
        user = unquote(u)
        password = unquote(p) if sep else None
    host, port = hostport, None
    if hostport.startswith("["):                       # IPv6 literal
        end = hostport.find("]")
        host, rest = hostport[:end + 1], hostport[end + 1:]
        if rest.startswith(":") and rest[1:]:
            port = _port(rest[1:])
    elif ":" in hostport:
        host, _, p = hostport.rpartition(":")
        port = _port(p) if p else None
    return user, password, host, port


def _port(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"Port {text!r} in the connection URI is not a number") from None


def from_uri(name: str, uri: str) -> Connection:
    uri = uri.strip()
    scheme, sep, rest = uri.partition(":")
    kind = scheme.lower() if sep else ""
    if kind not in KINDS:
        raise ValueError(f"Unknown connection kind {scheme!r} - one of {', '.join(KINDS)}")
    if kind == "duckdb":
        if rest.startswith("///"):
            rest = rest[3:]
        elif rest.startswith("//"):
            rest = rest[2:]
        return Connection(name=name, kind=kind, host=rest)
    u = urlsplit(uri)
    user, password, host, port = _split_netloc(u.netloc)
    parts = [unquote(p) for p in u.path.split("/") if p]
    extra = dict(parse_qsl(u.query, keep_blank_values=False))
    timeout = extra.pop("timeout", None)
    try:
        timeout = int(timeout) if timeout is not None else DEFAULT_TIMEOUT
    except ValueError:
        raise ValueError(f"timeout={timeout!r} in the connection URI is not a number") from None
    return Connection(name=name, kind=kind, host=host, port=port,
                      database=parts[0] if parts else "", schema=parts[1] if len(parts) > 1 else "",
                      user=user, password=password, extra=extra, timeout=timeout)


# ---- the store ------------------------------------------------------------------------

def store_path() -> Path:
    given = os.environ.get("COMPARE_CONNECTIONS", "").strip()
    return Path(given).expanduser() if given else Path.home() / ".crosshire-compare" / "connections.json"


_FIELDS = tuple(Connection.__dataclass_fields__)


def _read_file() -> dict[str, Connection]:
    path = store_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError(f"{path} is not a valid connections file: {e}") from None
    out: dict[str, Connection] = {}
    for rec in raw.get("connections", []) if isinstance(raw, dict) else []:
        if not isinstance(rec, dict) or not rec.get("name") or not rec.get("kind"):
            continue
        rec = {k: v for k, v in rec.items() if k in _FIELDS}
        rec.setdefault("password", None)
        rec["extra"] = dict(rec.get("extra") or {})
        rec["source"] = "file"
        out[rec["name"]] = Connection(**rec)
    return out


def _write_file(conns: dict[str, Connection]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    records = []
    for c in conns.values():
        if c.source == "env":
            continue
        rec = asdict(c)
        rec.pop("source", None)
        if rec.get("password") is None:
            rec.pop("password", None)
        records.append(rec)
    text = json.dumps({"version": 1, "connections": records}, indent=2) + "\n"
    # mkstemp opens the temp file 0o600; the rename makes the new content appear whole
    fd, tmp = tempfile.mkstemp(prefix=".connections-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def env_connections() -> dict[str, Connection]:
    """Every COMPARE_CONN_<NAME>=<uri> in the environment, named <NAME>; a bad URI is skipped."""
    out: dict[str, Connection] = {}
    for key, val in os.environ.items():
        if key.startswith(ENV_PREFIX) and val.strip():
            name = key[len(ENV_PREFIX):]
            if not name:
                continue
            try:
                c = from_uri(name, val.strip())
            except ValueError:
                continue
            c.source = "env"
            out[name] = c
    return out


def load_all() -> dict[str, Connection]:
    """File connections, then the environment on top: same name (ignoring case) wins for env."""
    conns = _read_file()
    by_fold = {n.casefold(): n for n in conns}
    for name, c in env_connections().items():
        spelt = by_fold.get(name.casefold(), name)
        c.name = spelt
        conns[spelt] = c
    return conns


def save(c: Connection) -> None:
    if not NAME_OK.match(c.name or ""):
        raise ValueError("A connection name is letters, digits, _ and - only")
    if c.kind not in KINDS:
        raise ValueError(f"Unknown connection kind {c.kind!r}")
    conns = _read_file()
    c.source = "file"
    conns[c.name] = c
    _write_file(conns)


def delete(name: str) -> None:
    conns = _read_file()
    conns.pop(name, None)
    _write_file(conns)


def resolve(name: str, passwords: dict[str, str] | None = None) -> Connection:
    """The connection with a password: saved, or typed this session, else PasswordNeeded."""
    conns = load_all()
    if name not in conns:
        raise KeyError(f"No connection called {name}")
    c = conns[name]
    if c.password is None and c.kind != "duckdb":
        typed = (passwords or {}).get(name)
        if not typed:
            raise PasswordNeeded(name)
        c = Connection(**{**asdict(c), "password": typed})
    return c


# ---- redaction ------------------------------------------------------------------------

_SECRET_KV = re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api_key)\b[\"']?\s*[=:]\s*\S+")
_SECRET_AUTH = re.compile(r"(?i)authorization[\"']?\s*:\s*\S+(\s+\S+)?")
_SECRET_URI = re.compile(r"(\w+://[^:/@\s]+:)[^@\s]+(@)")


def redact(text: str) -> str:
    """Driver messages with every password, token and user:pass@ blanked."""
    text = _SECRET_URI.sub(r"\1***\2", str(text))
    text = _SECRET_AUTH.sub("authorization: ***", text)
    return _SECRET_KV.sub(lambda m: m.group(1) + "=***", text)
