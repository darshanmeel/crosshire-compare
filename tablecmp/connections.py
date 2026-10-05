"""Named database connections, the way Airflow keeps them: a name, a kind, where it is.

Made in the sidebar, kept in connections.json in the user's home folder (never in the repo),
and overridable one by one with COMPARE_CONN_<NAME>=<uri>. The URI form is Airflow's:

    snowflake://USER:PASS@ACCOUNT/DB/SCHEMA?warehouse=WH&role=R
    snowflake://USER@ACCOUNT/DB/SCHEMA?warehouse=WH&private_key_file=C:/keys/rsa_key.p8
    databricks://token:TOKEN@host/?http_path=/sql/1.0/warehouses/x&catalog=c&schema=s
    mssql://user:pass@server:1433/db
    oracle://user:pass@host:1521/?service_name=X
    postgresql://user:pass@host:5432/db
    duckdb:///C:/data/sample.duckdb
    folder:///D:/exports/hr

For duckdb and folder the path is everything after ``duckdb:///`` exactly as written, so
``duckdb:///examples/sample.duckdb`` is relative to the working folder. A folder is not a
database: it is where the files of a "Path on disk" side are picked from by name.

Many connections at once come from a file, JSON or YAML (see ``parse_connections``): the
store itself, or shared files named in COMPARE_CONNECTION_FILES, read-only. A value written
``${NAME}`` is read from the environment, so a shared file need hold no password.

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
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

KINDS = {"snowflake": "Snowflake", "databricks": "Databricks", "mssql": "SQL Server",
         "oracle": "Oracle", "postgresql": "Postgres", "duckdb": "DuckDB file", "folder": "Folder"}
PATH_KINDS = ("duckdb", "folder")           # the URI is a path, and there is no login
DEFAULT_PORTS = {"mssql": 1433, "oracle": 1521, "postgresql": 5432}
DEFAULT_TIMEOUT = 600
ENV_PREFIX = "COMPARE_CONN_"
FILES_ENV = "COMPARE_CONNECTION_FILES"
# what a connections file may call a field, beyond the field's own name
ALIASES = {"type": "kind", "account": "host", "server": "host", "hostname": "host", "path": "host",
           "file": "host", "folder": "host", "username": "user", "login": "user", "db": "database",
           "catalog_schema": "schema", "query_timeout": "timeout"}
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
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
    source: str = "file"            # file (the store) | shared (a file in COMPARE_CONNECTION_FILES) | env
    origin_file: str = ""           # the shared file it came from

    @property
    def is_folder(self) -> bool:
        return self.kind == "folder"

    @property
    def label(self) -> str:
        return KINDS.get(self.kind, self.kind)

    @property
    def where(self) -> str:
        """One line for lists: host and database, never a credential."""
        if self.kind in PATH_KINDS:
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
    if c.kind in PATH_KINDS:
        return f"{c.kind}:///" + c.host
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
    if kind in PATH_KINDS:
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


_FIELDS = tuple(f for f in Connection.__dataclass_fields__ if f not in ("source", "origin_file"))


def is_yaml(path: str | Path) -> bool:
    return Path(path).suffix.lower() in (".yml", ".yaml")


def _load_text(text: str, where: str) -> object:
    """JSON, else YAML - a JSON document is YAML too, but JSON's own message is the clearer one."""
    try:
        return json.loads(text)
    except ValueError as json_err:
        if text.lstrip().startswith(("{", "[")) and not is_yaml(where):
            raise ValueError(f"{where} is not a valid connections file: {json_err}") from None
    try:
        import yaml
    except ImportError:
        raise ValueError(f"{where} is YAML, which needs the PyYAML package: pip install pyyaml") from None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)       # never str(e): it quotes the offending line
        at = f" (line {mark.line + 1})" if mark is not None else ""
        raise ValueError(f"{where} is not a valid connections file{at}") from None


def has_env_ref(value: object) -> bool:
    """Is it written ``${NAME}`` - a pointer into the environment, not a secret itself?"""
    return isinstance(value, str) and bool(_ENV_REF.search(value))


def _expand(value: object) -> object:
    """``${NAME}`` read from the environment; a name not set reads as nothing."""
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    return value


def _records(raw: object) -> Iterable[tuple[str, dict]]:
    """(name, record) from any of the shapes a connections file takes:
    ``{"connections": [{name: ..}, ..]}``, ``{"connections": {NAME: {..}}}``, ``[{name: ..}]``
    or ``{NAME: {..}}`` - and a record may be a URI string."""
    if isinstance(raw, dict) and "connections" in raw:
        raw = raw["connections"]
    if raw is None:
        return
    if isinstance(raw, dict):
        items = [(str(k), v) for k, v in raw.items() if k != "version"]
    elif isinstance(raw, list):
        items = [(str(r.get("name") or "") if isinstance(r, dict) else "", r) for r in raw]
    else:
        raise ValueError("a connections file is a list of connections, or a mapping of name to connection")
    for name, rec in items:
        if isinstance(rec, str):
            rec = {"uri": rec}
        if not isinstance(rec, dict):
            raise ValueError(f"connection {name or '(no name)'} is not a mapping of its fields")
        yield (str(rec.get("name") or name), rec)


def record_to_connection(name: str, rec: dict, expand: bool = True) -> Connection:
    """One record of a connections file: its fields, by name or a usual alias (``account``,
    ``server``, ``path``, ``username``…), or a ``uri``; anything else is the kind's own (warehouse,
    role, http_path, token…). ``${NAME}`` values come from the environment when ``expand``."""
    if not name:
        raise ValueError("a connection in the file has no name")
    if not NAME_OK.match(name):
        raise ValueError(f"connection {name!r}: a name is letters, digits, _ and - only")
    val = _expand if expand else (lambda v: v)
    rec = {ALIASES.get(str(k).lower(), str(k).lower()): v for k, v in rec.items() if k != "name"}
    if rec.get("uri"):
        c = from_uri(name, str(val(rec.pop("uri"))))
    else:
        kind = str(rec.get("kind") or "").lower()
        if kind not in KINDS:
            raise ValueError(f"connection {name}: kind {rec.get('kind')!r} is not one of {', '.join(KINDS)}")
        c = Connection(name=name, kind=kind)
    for k, v in rec.items():
        if k in ("kind", "uri") or v is None:
            continue
        v = val(v)
        if k == "extra":
            c.extra.update({str(a): str(val(b)) for a, b in dict(v).items() if b not in (None, "")})
        elif k in ("port", "timeout"):
            if not expand and _ENV_REF.search(str(v)):          # kept as written, read when used
                setattr(c, k, v)
                continue
            try:
                setattr(c, k, int(v) if str(v).strip() else (None if k == "port" else DEFAULT_TIMEOUT))
            except ValueError:
                raise ValueError(f"connection {name}: {k} {v!r} is not a number") from None
        elif k == "password":
            c.password = str(v) if str(v) != "" else None
        elif k in _FIELDS:
            setattr(c, k, str(v))
        elif str(v) != "":
            c.extra[k] = str(v)
    if c.kind == "databricks" and c.extra.get("token") and c.password is None:
        c.password = c.extra["token"]
    return c


def parse_connections(text: str, where: str = "the file", expand: bool = True) -> dict[str, Connection]:
    """Every connection in a JSON or YAML connections file, by name. A bad record is a
    ValueError naming it - a file is read whole or not at all."""
    out: dict[str, Connection] = {}
    for name, rec in _records(_load_text(text, where)):
        try:
            out[name] = record_to_connection(name, rec, expand)
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from None
    return out


def _read_path(path: Path, source: str, expand: bool = True) -> dict[str, Connection]:
    if not path.exists():
        return {}
    conns = parse_connections(path.read_text(encoding="utf-8"), str(path), expand)
    for c in conns.values():
        c.source = source
        c.origin_file = str(path) if source == "shared" else ""
    return conns


def _read_file(expand: bool = True) -> dict[str, Connection]:
    """The store. Read to be written back, ``${NAME}`` stays as written - a secret the
    environment holds never lands in the file."""
    return _read_path(store_path(), "file", expand)


def stored_as_written() -> dict[str, Connection]:
    """The store with every ``${NAME}`` as written - what an edit starts from and writes back."""
    return _read_file(expand=False)


def expanded(c: Connection) -> Connection:
    """A connection with its ``${NAME}`` values read from the environment, to connect with."""
    out = Connection(**{**asdict(c), "extra": {k: str(_expand(v)) for k, v in c.extra.items()}})
    for f in ("host", "database", "schema", "user"):
        setattr(out, f, str(_expand(getattr(c, f))))
    if out.password is not None:
        out.password = str(_expand(out.password)) or None
    return out


def shared_files() -> list[Path]:
    """The read-only connections files named in COMPARE_CONNECTION_FILES (os.pathsep between them)."""
    given = os.environ.get(FILES_ENV, "")
    return [Path(p.strip()).expanduser() for p in given.split(os.pathsep) if p.strip()]


def shared_connections() -> dict[str, Connection]:
    out: dict[str, Connection] = {}
    for path in shared_files():
        out.update(_read_path(path, "shared"))
    return out


def records_of(conns: Iterable[Connection], passwords: bool = True) -> list[dict]:
    """The records a connections file holds, the password left out unless asked for."""
    out = []
    for c in conns:
        rec = asdict(c)
        rec.pop("source", None)
        rec.pop("origin_file", None)
        if rec.get("password") is None or not passwords:
            rec.pop("password", None)
        if not rec.get("extra"):
            rec.pop("extra", None)
        if rec.get("timeout") == DEFAULT_TIMEOUT:
            rec.pop("timeout", None)
        out.append({k: v for k, v in rec.items() if v not in ("", None)})
    return out


def dump_connections(conns: Iterable[Connection], yaml_out: bool = False, passwords: bool = False) -> str:
    """A connections file's text, JSON or YAML - by default with no password in it."""
    doc = {"version": 1, "connections": records_of(conns, passwords)}
    if yaml_out:
        import yaml
        return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    return json.dumps(doc, indent=2) + "\n"


def _write_file(conns: dict[str, Connection]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    text = dump_connections([c for c in conns.values() if c.source == "file"], is_yaml(path), passwords=True)
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
    """Shared files, the store over them, then the environment on top: the same name (ignoring
    case, for env) is the later one's."""
    conns = shared_connections()
    conns.update(_read_file())
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
    conns = _read_file(expand=False)
    c.source = "file"
    conns[c.name] = c
    _write_file(conns)


def delete(name: str) -> None:
    conns = _read_file(expand=False)
    conns.pop(name, None)
    _write_file(conns)


def import_connections(conns: Iterable[Connection], passwords: bool = True) -> list[str]:
    """Connections read from a file, added to the store - a name already there is replaced."""
    store = _read_file(expand=False)
    names = []
    for c in conns:
        c = Connection(**{**asdict(c), "source": "file", "origin_file": ""})
        if not passwords:
            c.password = None
        store[c.name] = c
        names.append(c.name)
    _write_file(store)
    return names


def folders() -> dict[str, Connection]:
    """The folder connections, by name: where a Path on disk side picks its file."""
    return {n: c for n, c in load_all().items() if c.is_folder}


def needs_no_password(c: Connection) -> bool:
    """DuckDB, a folder, or a Snowflake key-pair login from a key file: the key is the credential."""
    return c.kind in PATH_KINDS or (c.kind == "snowflake" and bool((c.extra.get("private_key_file") or "").strip()))


def resolve(name: str, passwords: dict[str, str] | None = None) -> Connection:
    """The connection with a password: saved, or typed this session, else PasswordNeeded."""
    conns = load_all()
    if name not in conns:
        raise KeyError(f"No connection called {name}")
    c = conns[name]
    if c.password is None and not needs_no_password(c):
        typed = (passwords or {}).get(name)
        if not typed:
            raise PasswordNeeded(name)
        c = Connection(**{**asdict(c), "password": typed})
    phrase = (passwords or {}).get(passphrase_key(name))
    if phrase and not c.extra.get("private_key_pwd"):     # a key passphrase typed, not saved
        c = Connection(**{**asdict(c), "extra": {**c.extra, "private_key_pwd": phrase}})
    return c


def passphrase_key(name: str) -> str:
    """Where a typed, unsaved key passphrase is held beside the passwords - ':' is not in a name."""
    return f"{name}:private_key_pwd"


def known_secrets(extra: Iterable[str] = ()) -> list[str]:
    """Every secret value the store holds, ${NAME} expanded, plus ``extra`` (the typed ones)."""
    out = [str(v) for v in extra]
    try:
        for c in load_all().values():
            out.append(c.password or "")
            out.extend(v for k, v in c.extra.items() if k in ("token", "private_key_pwd"))
    except Exception:                              # an unreadable store has nothing to add
        pass
    return [v for v in out if v]


# ---- redaction ------------------------------------------------------------------------

_SECRET_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S)
_VALUE = r"(\"[^\"]*\"|'[^']*'|\{[^}]*\}|\S+)"
_SECRET_KV = re.compile(r"(?i)\b(password|passwd|pwd|private_key_pwd|token|secret|api_key)\b[\"']?\s*[=:]\s*" + _VALUE)
_SECRET_AUTH = re.compile(r"(?i)authorization[\"']?\s*:\s*\S+(\s+\S+)?")
_SECRET_URI = re.compile(r"(\w+://[^:/@\s]*:)\S+@")
MIN_SECRET = 4


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Driver messages with every known secret value, password, token, private key and
    user:pass@ blanked. The known values go first, so a password with a space or an @ in it
    goes whole; the patterns are the second line for ones the server was never told."""
    text = str(text)
    for v in sorted({str(s) for s in secrets if s and len(str(s)) >= MIN_SECRET}, key=len, reverse=True):
        text = text.replace(v, "***")
    text = _SECRET_PEM.sub("***", text)
    text = _SECRET_URI.sub(r"\1***@", text)
    text = _SECRET_AUTH.sub("authorization: ***", text)
    return _SECRET_KV.sub(lambda m: m.group(1) + "=***", text)
