import os

from databricks.sdk import WorkspaceClient

RESTORE_ADMIN_GROUP = "restore-admin"


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


def get_user_token(headers) -> str | None:
    return _header(headers, "x-forwarded-access-token")


def get_user_client(headers) -> WorkspaceClient:
    token = get_user_token(headers)
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


def group_names(me) -> list[str]:
    return sorted(
        {
            g.display
            for g in (me.groups or [])
            if getattr(g, "display", None)
        }
    )


def is_restore_admin(groups: list[str]) -> bool:
    normalized = {g.lower() for g in groups}
    return RESTORE_ADMIN_GROUP.lower() in normalized
