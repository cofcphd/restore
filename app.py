from databricks.sdk import WorkspaceClient
import streamlit as st


st.set_page_config(page_title="Min Databricks profil", page_icon="👤")
st.title("Min Databricks profil")

st.caption("Viser display name og grupper for den bruger, der er logget ind.")

try:
    w = WorkspaceClient()
    me = w.current_user.me()

    display_name = me.display_name or me.user_name or "Ukendt bruger"
    st.subheader(display_name)

    groups = sorted(
        {
            g.display
            for g in (me.groups or [])
            if getattr(g, "display", None)
        }
    )

    st.markdown("### Grupper")
    if groups:
        for group_name in groups:
            st.write(f"- {group_name}")
    else:
        st.info("Ingen grupper fundet for brugeren.")

except Exception as err:
    st.error("Kunne ikke hente brugerinformation fra Databricks.")
    st.exception(err)
