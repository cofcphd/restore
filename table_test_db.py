"""Isoleret lag til læs/skriv-test mod app_test.simple_form_entries."""

import os
import re
import uuid
from contextlib import contextmanager
from urllib.parse import urlparse

from databricks import sql
from databricks.sdk.core import Config

from auth import get_user_token

CREATE_SCHEMA_SQL = "CREATE SCHEMA IF NOT EXISTS app_test"
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS app_test.simple_form_entries (
  id STRING,
  field_1 STRING,
  field_2 STRING,
  field_3 STRING,
  field_4 STRING,
  field_5 STRING,
  created_at TIMESTAMP
)
"""
INSERT_SQL = """
INSERT INTO app_test.simple_form_entries
  (id, field_1, field_2, field_3, field_4, field_5, created_at)
VALUES (?, ?, ?, ?, ?, ?, current_timestamp())
"""
SELECT_SQL = """
SELECT id, field_1, field_2, field_3, field_4, field_5, created_at
FROM app_test.simple_form_entries
ORDER BY created_at DESC
"""


WAREHOUSE_PATH_PATTERN = re.compile(r"^/sql/1\.0/warehouses/[A-Za-z0-9_-]+$")


def _mask_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return f"{value[:2]}...{value[-2:]}"
    return f"{value[:6]}...{value[-4:]}"


def _normalize_http_path(value: str) -> str:
    if value.startswith("/sql/1.0/warehouses/"):
        return value
    if "/sql/1.0/warehouses/" in value:
        parsed = urlparse(value)
        if parsed.path.startswith("/sql/1.0/warehouses/"):
            return parsed.path
    return f"/sql/1.0/warehouses/{value}"


def _warehouse_http_path() -> str:
    for key in (
        "DATABRICKS_WAREHOUSE_HTTP_PATH",
        "DATABRICKS_HTTP_PATH",
        "SQL_WAREHOUSE_HTTP_PATH",
        "DATABRICKS_WAREHOUSE_ID",
        "WAREHOUSE_ID",
    ):
        value = (os.environ.get(key) or "").strip()
        if value:
            return _normalize_http_path(value)

    raise ValueError("Mangler SQL warehouse. Tjek App resources og app.yaml env.")


def _server_hostname() -> str:
    host = (os.environ.get("DATABRICKS_SERVER_HOSTNAME") or "").strip()
    if host:
        return host.split("/")[0]
    host = (os.environ.get("DATABRICKS_HOST") or "").strip()
    if not host:
        host = (Config().host or "").strip()
    if not host:
        raise ValueError("Mangler Databricks server hostname env-var.")
    if host.startswith(("http://", "https://")):
        parsed = urlparse(host)
        if parsed.hostname:
            return parsed.hostname
        raise ValueError(f"Ugyldig Databricks host: {host}")
    return host.split("/")[0]


@contextmanager
def _connection(headers):
    token = get_user_token(headers)
    if not token:
        raise ValueError(
            "Mangler x-forwarded-access-token. Tjek at User authorization er slået til, "
            "at appen har sql scope, og at appen er åbnet via Databricks Apps UI."
        )
    conn = sql.connect(
        server_hostname=_server_hostname(),
        http_path=_warehouse_http_path(),
        access_token=token,
    )
    try:
        yield conn
    finally:
        conn.close()


def ensure_table(headers) -> None:
    with _connection(headers) as conn:
        with conn.cursor() as cursor:
            cursor.execute(CREATE_SCHEMA_SQL)
            cursor.execute(CREATE_TABLE_SQL)


def save_entry(headers, field_1: str, field_2: str, field_3: str, field_4: str, field_5: str) -> str:
    ensure_table(headers)
    row_id = str(uuid.uuid4())
    with _connection(headers) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                INSERT_SQL,
                (row_id, field_1, field_2, field_3, field_4, field_5),
            )
    return row_id


def load_entries(headers) -> list[dict]:
    ensure_table(headers)
    with _connection(headers) as conn:
        with conn.cursor() as cursor:
            cursor.execute(SELECT_SQL)
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def test_databricks_connection(headers) -> dict:
    status = {
        "headers_present": bool(headers),
        "has_x_forwarded_access_token": bool(get_user_token(headers or {})),
        "server_hostname_found": False,
        "server_hostname": None,
        "warehouse_env": {
            "DATABRICKS_WAREHOUSE_HTTP_PATH": False,
            "DATABRICKS_HTTP_PATH": False,
            "DATABRICKS_WAREHOUSE_ID": False,
            "WAREHOUSE_ID": False,
        },
        "resolved_http_path": None,
        "http_path_format_ok": False,
        "warehouse_id_preview": None,
        "select_1_ok": False,
        "error_type": None,
        "error_message": None,
    }

    for key in status["warehouse_env"]:
        status["warehouse_env"][key] = bool((os.environ.get(key) or "").strip())

    try:
        server_hostname = _server_hostname()
        status["server_hostname_found"] = True
        status["server_hostname"] = server_hostname

        http_path = _warehouse_http_path()
        status["resolved_http_path"] = http_path
        status["http_path_format_ok"] = bool(WAREHOUSE_PATH_PATTERN.match(http_path))
        warehouse_id = http_path.rsplit("/", 1)[-1] if "/" in http_path else http_path
        status["warehouse_id_preview"] = _mask_value(warehouse_id)

        token = get_user_token(headers or {})
        if not token:
            raise ValueError(
                "Mangler x-forwarded-access-token. Tjek at User authorization er slået til, "
                "at appen har sql scope, og at appen er åbnet via Databricks Apps UI."
            )

        conn = sql.connect(
            server_hostname=server_hostname,
            http_path=http_path,
            access_token=token,
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                status["select_1_ok"] = True
        finally:
            conn.close()
    except Exception as err:  # noqa: BLE001 - debug helper should catch all failures
        status["error_type"] = type(err).__name__
        status["error_message"] = str(err)

    return status
