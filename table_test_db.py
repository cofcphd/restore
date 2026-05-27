"""Isoleret lag til læs/skriv-test mod app_test.simple_form_entries."""

import os
import uuid
from contextlib import contextmanager

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


def _warehouse_http_path() -> str:
    for key in (
        "DATABRICKS_WAREHOUSE_HTTP_PATH",
        "DATABRICKS_HTTP_PATH",
        "SQL_WAREHOUSE_HTTP_PATH",
    ):
        value = os.environ.get(key)
        if value:
            return value
    raise ValueError(
        "Mangler SQL warehouse http path. Tilføj en SQL warehouse-ressource til appen "
        "eller sæt miljøvariablen DATABRICKS_WAREHOUSE_HTTP_PATH."
    )


@contextmanager
def _connection(headers):
    token = get_user_token(headers)
    if not token:
        raise ValueError("Mangler bruger-token (x-forwarded-access-token).")
    cfg = Config()
    conn = sql.connect(
        server_hostname=cfg.host,
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
