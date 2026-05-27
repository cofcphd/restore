"""SQL access to restore_requests via app service principal."""

from __future__ import annotations

import os
import re
import uuid
from contextlib import contextmanager
from typing import Any

from databricks import sql
from databricks.sdk.core import Config
from databricks.sdk.credentials_provider import oauth_service_principal

TABLE_PATTERN = re.compile(r"^[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$")

_table_verified = False


def _server_hostname() -> str:
    host = os.environ.get("DATABRICKS_HOST") or Config().host
    if not host:
        raise ValueError("DATABRICKS_HOST er ikke sat.")
    return host.replace("https://", "").replace("http://", "").rstrip("/")


def _http_path() -> str:
    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not warehouse_id:
        raise ValueError("DATABRICKS_WAREHOUSE_ID er ikke sat.")
    return f"/sql/1.0/warehouses/{warehouse_id}"


def get_restore_requests_table() -> str:
    table = os.environ.get("RESTORE_REQUESTS_TABLE", "").strip()
    if not table or not TABLE_PATTERN.match(table):
        raise ValueError(
            "RESTORE_REQUESTS_TABLE skal være en fuld UC-sti (catalog.schema.table), "
            "fx main.restore.restore_requests."
        )
    return table


@contextmanager
def _connection():
    cfg = Config()
    conn = sql.connect(
        server_hostname=_server_hostname(),
        http_path=_http_path(),
        credentials_provider=oauth_service_principal(cfg),
    )
    try:
        yield conn
    finally:
        conn.close()


def run_sql(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with _connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params or {})
            if not cursor.description:
                return []
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def ensure_restore_requests_table() -> None:
    global _table_verified
    if _table_verified:
        return

    table = get_restore_requests_table()
    run_sql(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            request_id STRING NOT NULL,
            created_at TIMESTAMP NOT NULL,
            created_by STRING NOT NULL,
            created_by_display_name STRING,
            catalog_identifier STRING,
            env STRING NOT NULL,
            source_schema STRING,
            restore_to_new_schema STRING NOT NULL,
            backup_date STRING,
            specific_tables STRING,
            status STRING NOT NULL,
            approved_by STRING,
            approved_at TIMESTAMP,
            rejected_by STRING,
            rejected_at TIMESTAMP,
            updated_at TIMESTAMP
        )
        USING DELTA
        """
    )
    _table_verified = True


def normalize_specific_tables(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    seen: set[str] = set()
    parts: list[str] = []
    for line in raw.replace(",", "\n").split("\n"):
        name = line.strip()
        if name and name not in seen:
            seen.add(name)
            parts.append(name)
    return "\n".join(parts) if parts else None


def create_restore_request(
    *,
    created_by: str,
    created_by_display_name: str,
    catalog_identifier: str | None,
    env: str,
    source_schema: str | None,
    restore_to_new_schema: str,
    backup_date: str | None,
    specific_tables: str | None,
) -> str:
    table = get_restore_requests_table()
    request_id = str(uuid.uuid4())

    run_sql(
        f"""
        INSERT INTO {table} (
            request_id,
            created_at,
            created_by,
            created_by_display_name,
            catalog_identifier,
            env,
            source_schema,
            restore_to_new_schema,
            backup_date,
            specific_tables,
            status,
            updated_at
        ) VALUES (
            :request_id,
            current_timestamp(),
            :created_by,
            :created_by_display_name,
            :catalog_identifier,
            :env,
            :source_schema,
            :restore_to_new_schema,
            :backup_date,
            :specific_tables,
            'PENDING',
            current_timestamp()
        )
        """,
        {
            "request_id": request_id,
            "created_by": created_by,
            "created_by_display_name": created_by_display_name,
            "catalog_identifier": catalog_identifier or None,
            "env": env,
            "source_schema": source_schema or None,
            "restore_to_new_schema": restore_to_new_schema,
            "backup_date": backup_date or None,
            "specific_tables": specific_tables,
        },
    )
    return request_id


def get_pending_restore_requests() -> list[dict[str, Any]]:
    table = get_restore_requests_table()
    return run_sql(
        f"""
        SELECT
            request_id,
            created_at,
            created_by,
            created_by_display_name,
            catalog_identifier,
            env,
            source_schema,
            restore_to_new_schema,
            backup_date,
            specific_tables,
            status
        FROM {table}
        WHERE status = 'PENDING'
        ORDER BY created_at DESC
        """
    )


def approve_restore_request(request_id: str, approved_by: str) -> bool:
    table = get_restore_requests_table()
    run_sql(
        f"""
        UPDATE {table}
        SET
            status = 'APPROVED',
            approved_by = :approved_by,
            approved_at = current_timestamp(),
            updated_at = current_timestamp()
        WHERE request_id = :request_id AND status = 'PENDING'
        """,
        {"request_id": request_id, "approved_by": approved_by},
    )
    return _has_status(request_id, table, "APPROVED")


def reject_restore_request(request_id: str, rejected_by: str) -> bool:
    table = get_restore_requests_table()
    run_sql(
        f"""
        UPDATE {table}
        SET
            status = 'REJECTED',
            rejected_by = :rejected_by,
            rejected_at = current_timestamp(),
            updated_at = current_timestamp()
        WHERE request_id = :request_id AND status = 'PENDING'
        """,
        {"request_id": request_id, "rejected_by": rejected_by},
    )
    return _has_status(request_id, table, "REJECTED")


def _has_status(request_id: str, table: str, expected_status: str) -> bool:
    result = run_sql(
        f"""
        SELECT status FROM {table}
        WHERE request_id = :request_id
        """,
        {"request_id": request_id},
    )
    return bool(result) and result[0].get("status") == expected_status
