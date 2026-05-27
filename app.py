import os

from databricks.sdk import WorkspaceClient
import streamlit as st

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


st.set_page_config(page_title="Min Databricks profil", page_icon="👤")
st.title("Min Databricks profil")

st.caption("Viser display name og grupper for den bruger, der er logget ind.")

user_token = get_user_token()
if not user_token:
    st.warning(
        "Ingen bruger-token i request. Uden `x-forwarded-access-token` vil "
        "`WorkspaceClient()` kun give appens service principal."
    )
    st.stop()

try:
    w = get_user_client()
    me = w.current_user.me()

    display_name = me.display_name or me.user_name or "Ukendt bruger"
    groups = group_names(me)

    st.subheader(display_name)
    st.write(f"Brugernavn: `{me.user_name}`")

    st.markdown("### Grupper")
    if groups:
        for group_name in groups:
            st.write(f"- {group_name}")
    else:
        st.info("Ingen grupper fundet for brugeren.")

    st.markdown("### Restore admin")
    if is_restore_admin(groups):
        st.success(f"Du er medlem af `{RESTORE_ADMIN_GROUP}`.")
    else:
        st.error(f"Du er ikke medlem af `{RESTORE_ADMIN_GROUP}`.")

except Exception as err:
    st.error("Kunne ikke hente brugerinformation fra Databricks.")
    st.exception(err)
