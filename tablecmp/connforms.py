"""The connection form, kind by kind: which boxes it has and what they are called. Both pages
draw the form from this - nothing here imports a UI."""
from __future__ import annotations

from .connections import DEFAULT_PORTS, DEFAULT_TIMEOUT

EXTRAS = {"snowflake": ["warehouse", "role", "authenticator", "private_key_file", "private_key_pwd"], "databricks": ["http_path", "token", "catalog"],
          "oracle": ["service_name"], "mssql": [], "postgresql": [], "duckdb": [], "folder": []}
FIELDS = {"snowflake": ["host", "user", "password", "database", "schema"],
          "databricks": ["host", "schema"], "mssql": ["host", "port", "database", "user", "password"],
          "oracle": ["host", "port", "user", "password"], "postgresql": ["host", "port", "database", "user", "password"],
          "duckdb": ["host"], "folder": ["host"]}
LABELS = {"host": "Host", "port": "Port", "database": "Database", "schema": "Schema", "user": "User",
          "password": "Password", "warehouse": "Warehouse", "role": "Role", "authenticator": "Authenticator (optional)",
          "http_path": "HTTP path", "token": "Access token", "catalog": "Catalog", "service_name": "Service name",
          "private_key_file": "Private key file (key-pair login, optional)",
          "private_key_pwd": "Private key passphrase (optional)"}
PASSWORD_LABEL = {"snowflake": "Password - or paste the private key (PEM)"}
SECRET_EXTRAS = {"token", "private_key_pwd"}
HOST_LABEL = {"snowflake": "Account", "databricks": "Server hostname", "mssql": "Server", "duckdb": "File path",
              "folder": "Folder path"}
CAP_DEFAULT = 1_000_000


def form_spec() -> dict:
    return {"fields": FIELDS, "extras": EXTRAS, "labels": LABELS, "password_label": PASSWORD_LABEL,
            "secret_extras": sorted(SECRET_EXTRAS), "host_label": HOST_LABEL,
            "default_ports": DEFAULT_PORTS, "default_timeout": DEFAULT_TIMEOUT, "cap_default": CAP_DEFAULT}
