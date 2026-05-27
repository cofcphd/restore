"""Isoleret lag til læs/skriv-test mod app_test.simple_form_entries."""

import os
import platform
import json
import base64
import re
import uuid
from contextlib import contextmanager
from urllib.parse import urlparse
from urllib.request import Request, urlopen

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


def _normalize_access_token(raw_token: str | None) -> tuple[str | None, bool]:
    token = (raw_token or "").strip()
    if not token:
        return None, False
    bearer_prefix = "bearer "
    if token.lower().startswith(bearer_prefix):
        return token[len(bearer_prefix) :].strip(), True
    return token, False


def _decode_jwt_payload_without_verification(token: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_segment = parts[1]
    padding = "=" * (-len(payload_segment) % 4)
    try:
        decoded = base64.urlsafe_b64decode((payload_segment + padding).encode("utf-8"))
        payload = json.loads(decoded.decode("utf-8"))
    except Exception:  # noqa: BLE001 - debug helper should never crash
        return None
    return payload if isinstance(payload, dict) else None


def _token_scope_debug(token: str) -> dict:
    payload = _decode_jwt_payload_without_verification(token)
    if payload is None:
        return {
            "token_is_jwt": False,
            "token_scope_claim": None,
            "token_scopes_contains_sql": False,
            "token_audience": None,
            "token_subject_preview": None,
            "token_exp": None,
        }

    scope_claim = payload.get("scope", payload.get("scp"))
    if isinstance(scope_claim, str):
        scopes = scope_claim.split()
    elif isinstance(scope_claim, list):
        scopes = [str(item) for item in scope_claim]
    else:
        scopes = []
        scope_claim = None

    audience = payload.get("aud")
    if isinstance(audience, list):
        audience = [str(item) for item in audience[:5]]
    elif audience is not None:
        audience = str(audience)

    subject = payload.get("sub")
    subject_preview = _mask_value(str(subject)) if subject else None

    return {
        "token_is_jwt": True,
        "token_scope_claim": scope_claim,
        "token_scopes_contains_sql": any("sql" in scope.lower() for scope in scopes),
        "token_audience": audience,
        "token_subject_preview": subject_preview,
        "token_exp": payload.get("exp"),
    }


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
    token, _ = _normalize_access_token(get_user_token(headers))
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
        "databricks_sql_connector_version": getattr(sql, "__version__", "unknown"),
        "python_version": platform.python_version(),
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
        "token_present": False,
        "token_had_bearer_prefix": False,
        "token_is_jwt": False,
        "token_scope_claim": None,
        "token_scopes_contains_sql": False,
        "token_audience": None,
        "token_subject_preview": None,
        "token_exp": None,
        "warehouse_rest_status_code": None,
        "warehouse_rest_ok": False,
        "warehouse_rest_error_text": None,
        "current_user_rest_status_code": None,
        "current_user_rest_ok": False,
        "current_user_user_name": None,
        "current_user_display_name": None,
        "current_user_error_text": None,
        "select_1_ok": False,
        "error_type": None,
        "error_message": None,
        "error_repr": None,
        "error_args": None,
        "error_dict": None,
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

        raw_token = get_user_token(headers or {})
        token, had_bearer_prefix = _normalize_access_token(raw_token)
        status["token_present"] = bool(token)
        status["token_had_bearer_prefix"] = had_bearer_prefix
        if not token:
            raise ValueError(
                "Mangler x-forwarded-access-token. Tjek at User authorization er slået til, "
                "at appen har sql scope, og at appen er åbnet via Databricks Apps UI."
            )
        status.update(_token_scope_debug(token))

        current_user_url = f"https://{server_hostname}/api/2.0/preview/scim/v2/Me"
        try:
            request = Request(
                current_user_url,
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            )
            with urlopen(request, timeout=20) as response:
                status_code = getattr(response, "status", None)
                status["current_user_rest_status_code"] = status_code
                status["current_user_rest_ok"] = bool(status_code and 200 <= status_code < 300)
                payload = json.loads(response.read().decode("utf-8"))
                status["current_user_user_name"] = payload.get("userName") or payload.get("email")
                status["current_user_display_name"] = payload.get("displayName")
        except Exception as current_user_err:  # noqa: BLE001 - debug helper should catch all failures
            status["current_user_rest_status_code"] = getattr(current_user_err, "code", None)
            status["current_user_rest_ok"] = False
            status["current_user_error_text"] = str(current_user_err)[:500]

        rest_url = f"https://{server_hostname}/api/2.0/sql/warehouses/{warehouse_id}"
        try:
            request = Request(
                rest_url,
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            )
            with urlopen(request, timeout=20) as response:
                status_code = getattr(response, "status", None)
                status["warehouse_rest_status_code"] = status_code
                status["warehouse_rest_ok"] = bool(status_code and 200 <= status_code < 300)
        except Exception as rest_err:  # noqa: BLE001 - debug helper should catch all failures
            status_code = getattr(rest_err, "code", None)
            status["warehouse_rest_status_code"] = status_code
            status["warehouse_rest_ok"] = False
            status["warehouse_rest_error_text"] = str(rest_err)[:500]

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
        status["error_repr"] = repr(err)
        try:
            status["error_args"] = [str(item) for item in getattr(err, "args", ())]
        except Exception:  # noqa: BLE001
            status["error_args"] = None
        try:
            error_dict = getattr(err, "__dict__", None)
            status["error_dict"] = (
                {k: str(v) for k, v in error_dict.items()} if isinstance(error_dict, dict) else None
            )
        except Exception:  # noqa: BLE001
            status["error_dict"] = None

    return status
