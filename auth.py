"""User identity via Databricks Apps on-behalf-of authorization."""

from __future__ import annotations

import os
from dataclasses import dataclass

from databricks.sdk import WorkspaceClient
import streamlit as st


def restore_admin_group() -> str:
    return os.environ.get("RESTORE_ADMIN_GROUP", "admins")


@dataclass(frozen=True)
class CurrentUser:
    user_name: str
    display_name: str
    groups: list[str]


def _header(headers, name: str) -> str | None:
    """Case-insensitive header lookup."""
    value = headers.get(name)
    if value:
        return value
    lower = name.lower()
    for key, val in headers.items():
        if key.lower() == lower:
            return val
    return None


def get_user_token() -> str | None:
    return _header(st.context.headers, "x-forwarded-access-token")


def get_user_client() -> WorkspaceClient:
    token = get_user_token()
    if not token:
        raise ValueError(
            "Mangler x-forwarded-access-token. Aktivér on-behalf-of user authorization "
            "på appen og genstart den fuldt (stop + start)."
        )
    return WorkspaceClient(
        host=os.environ.get("DATABRICKS_HOST"),
        token=token,
        auth_type="pat",
    )


def _group_names(me) -> list[str]:
    return sorted(
        {
            g.display
            for g in (me.groups or [])
            if getattr(g, "display", None)
        }
    )


def get_current_user() -> CurrentUser:
    w = get_user_client()
    me = w.current_user.me()
    user_name = me.user_name or ""
    display_name = me.display_name or user_name or "Ukendt bruger"
    return CurrentUser(
        user_name=user_name,
        display_name=display_name,
        groups=_group_names(me),
    )


def get_user_groups(user: CurrentUser | None = None) -> list[str]:
    if user is None:
        user = get_current_user()
    return user.groups


def is_restore_admin(user: CurrentUser | None = None) -> bool:
    if user is None:
        user = get_current_user()
    admin_group = restore_admin_group().lower()
    return admin_group in {g.lower() for g in user.groups}
