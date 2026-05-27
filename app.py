import streamlit as st

from auth import get_user_client, get_user_token, group_names, is_restore_admin, RESTORE_ADMIN_GROUP

st.set_page_config(page_title="Restore", page_icon="👤")

st.title("Min Databricks profil")
st.caption("Viser display name og grupper for den bruger, der er logget ind.")

headers = st.context.headers
user_token = get_user_token(headers)
if not user_token:
    st.warning(
        "Ingen bruger-token i request. Uden `x-forwarded-access-token` vil "
        "`WorkspaceClient()` kun give appens service principal."
    )
    st.stop()

try:
    w = get_user_client(headers)
    me = w.current_user.me()

    display_name = me.display_name or me.user_name or "Ukendt bruger"
    groups = group_names(me)

    st.subheader(display_name)
    st.write(f"User name: `{me.user_name}`")

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
