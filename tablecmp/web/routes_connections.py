"""The Connections manager's routes. The rule: a password, token or key passphrase goes in and
never comes out. Left blank on a save, the written one stays - the stored secret, a ${NAME}
reference, or the one typed this session."""
from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import connections as cx
from .. import databases as db
from ..connforms import SECRET_EXTRAS
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/connections")


class ConnIn(BaseModel):
    kind: str
    host: str = ""
    port: int | None = None
    database: str = ""
    schema_: str = Field("", alias="schema")
    user: str = ""
    password: str | None = None
    save_password: bool = False
    extra: dict[str, str] = Field(default_factory=dict)
    timeout: int = cx.DEFAULT_TIMEOUT

    model_config = {"populate_by_name": True}


class ConnTest(ConnIn):
    name: str


class ImportIn(BaseModel):
    text: str
    filename: str = "the file"
    keep_passwords: bool = False


def _password_state(c: cx.Connection, ws: Workspace) -> str:
    if c.source in ("env", "shared"):
        return c.source
    if c.is_folder:
        return "folder"
    if c.kind == "snowflake" and cx.needs_no_password(c):
        return "key file"
    if c.password:
        return "saved"
    return "session" if c.name in ws.passwords else "asked"


def _row(c: cx.Connection, ws: Workspace) -> dict:
    return {"name": c.name, "kind": c.kind, "label": c.label, "where": c.where, "source": c.source,
            "origin_file": c.origin_file, "is_folder": c.is_folder, "editable": c.source == "file",
            "password": _password_state(c, ws)}


def _shown(value: str) -> str:
    """A secret as the form may show it: a ${NAME} reference as written, anything else blank."""
    return value if cx.has_env_ref(value) else ""


def _changed(cur: cx.Connection | None, body: ConnIn) -> bool:
    """Is this save a different login from the stored one? A password typed for the old one is not kept."""
    return cur is None or (cur.kind, cur.host, cur.port, cur.user) != (body.kind, body.host.strip(), body.port, body.user.strip())


def _forget(ws: Workspace, name: str) -> None:
    ws.passwords.pop(name, None)
    ws.passwords.pop(cx.passphrase_key(name), None)


def _build(name: str, body: ConnIn, ws: Workspace) -> tuple[cx.Connection, dict[str, str]]:
    """The connection to save, and the secrets to hold in the session instead of the file
    (the password, and a key passphrase, under the keys cx.resolve reads)."""
    cur = cx.stored_as_written().get(name)
    held = {} if _changed(cur, body) else ws.passwords
    typed = body.password or None
    extra = {k: v for k, v in body.extra.items() if v != "" or k not in SECRET_EXTRAS}
    for k in SECRET_EXTRAS:                       # a secret extra left blank keeps the written one
        if not body.extra.get(k) and cur and cur.extra.get(k):
            extra[k] = cur.extra[k]
    if body.kind == "databricks" and extra.get("token") and not cx.has_env_ref(extra["token"]):
        if body.extra.get("token"):               # the token is its password: typed now, it is the typed one
            typed = extra["token"]
        body_token = extra.pop("token")
    else:
        body_token = None
    pw = body_token or typed or (cur.password if cur else None) or held.get(name)
    keep = body.save_password or body.kind in cx.PATH_KINDS
    session = {}
    phrase = extra.get("private_key_pwd")
    if not keep and phrase and not cx.has_env_ref(phrase) and body.extra.get("private_key_pwd"):
        session[cx.passphrase_key(name)] = extra.pop("private_key_pwd")    # not written to the file
    elif not extra.get("private_key_pwd") and held.get(cx.passphrase_key(name)):
        session[cx.passphrase_key(name)] = held[cx.passphrase_key(name)]
    if not keep and (typed or held.get(name)):
        session[name] = typed or held[name]
    c = cx.Connection(name=name, kind=body.kind, host=body.host.strip(), port=body.port,
                      database=body.database.strip(), schema=body.schema_.strip(), user=body.user.strip(),
                      password=pw if keep else None, extra=extra, timeout=body.timeout)
    return c, session


def _plain(exc: Exception) -> str:
    """An error as a sentence, with every secret this store knows blanked."""
    return cx.redact(str(exc), cx.known_secrets())


@router.get("")
def list_connections(ws: Workspace = Depends(workspace)) -> list[dict]:
    try:
        conns = cx.load_all()
    except ValueError as exc:
        raise HTTPException(400, _plain(exc)) from exc
    return [_row(c, ws) for _, c in sorted(conns.items())]


@router.get("/export")
def export() -> Response:
    try:
        stored = cx.stored_as_written().values()      # as written: a ${NAME} stays a reference
    except ValueError as exc:
        raise HTTPException(400, _plain(exc)) from exc
    mine = []
    for c in stored:
        extra = {k: ("" if k in SECRET_EXTRAS and not cx.has_env_ref(v) else v) for k, v in c.extra.items()}
        keep = c.password if cx.has_env_ref(c.password) else None
        mine.append(replace(c, extra=extra, password=keep))
    return Response(cx.dump_connections(mine, yaml_out=True, passwords=True), media_type="text/yaml",
                    headers={"Content-Disposition": 'attachment; filename="connections.yml"'})


@router.get("/{name}")
def get_connection(name: str, ws: Workspace = Depends(workspace)) -> dict:
    cur = cx.stored_as_written().get(name)
    if cur is None:
        raise HTTPException(404, f"No saved connection called {name}.")
    extra = {k: (_shown(v) if k in SECRET_EXTRAS else v) for k, v in cur.extra.items()}
    return {"name": cur.name, "kind": cur.kind, "host": cur.host, "port": cur.port, "database": cur.database,
            "schema": cur.schema, "user": cur.user, "timeout": cur.timeout, "extra": extra,
            "password_ref": _shown(cur.password or ""), "has_password": bool(cur.password),
            "save_password": bool(cur.password)}


@router.put("/{name}")
def save_connection(name: str, body: ConnIn, ws: Workspace = Depends(workspace)) -> dict:
    c, session = _build(name, body, ws)
    try:
        cx.save(c)
    except ValueError as exc:
        raise HTTPException(400, _plain(exc)) from exc
    _forget(ws, name)
    ws.passwords.update(session)
    return {"saved": name}


@router.delete("/{name}")
def delete_connection(name: str, ws: Workspace = Depends(workspace)) -> dict:
    cx.delete(name)
    _forget(ws, name)
    return {"deleted": name}


@router.delete("/{name}/password")
def forget_password(name: str, ws: Workspace = Depends(workspace)) -> dict:
    """Let go of the password (and key passphrase) typed this session, so it can be typed again."""
    _forget(ws, name)
    return {"ok": True}


@router.post("/test")
def test_connection(body: ConnTest, ws: Workspace = Depends(workspace)) -> dict:
    c, session = _build(body.name, body, ws)
    if body.name in session:
        c = replace(c, password=session[body.name])
    phrase = session.get(cx.passphrase_key(body.name))
    if phrase:
        c = replace(c, extra={**c.extra, "private_key_pwd": phrase})
    c = cx.expanded(c)
    secrets = cx.known_secrets([c.password or "", *(c.extra.get(k, "") for k in SECRET_EXTRAS), *ws.passwords.values(),
                                  *session.values()])
    r = db.test(c, secrets)                       # the secrets go in at the first redaction, so none is left half blanked
    return {"ok": r.ok, "message": cx.redact(r.message, secrets), "seconds": r.seconds}


@router.post("/import/preview")
def import_preview(body: ImportIn) -> list[dict]:
    try:
        found = cx.parse_connections(body.text, body.filename, expand=False)
    except ValueError as exc:
        raise HTTPException(400, _plain(exc)) from exc
    have = cx.stored_as_written()
    return [{"name": n, "label": c.label, "where": c.where, "replaces": n in have} for n, c in found.items()]


@router.post("/import")
def import_file(body: ImportIn) -> dict:
    try:
        found = cx.parse_connections(body.text, body.filename, expand=False)
    except ValueError as exc:
        raise HTTPException(400, _plain(exc)) from exc
    for c in found.values():                       # a literal password goes, a ${NAME} stays
        if not body.keep_passwords and c.password and not cx.has_env_ref(c.password):
            c.password = None
    return {"names": cx.import_connections(found.values(), passwords=True)}
