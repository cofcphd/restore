"""
Restore bestillingsapp (Databricks App / Streamlit).

Påkrævede miljøvariabler:
- DATABRICKS_WAREHOUSE_ID: SQL warehouse ID
- RESTORE_REQUESTS_TABLE: UC-tabel, fx main.restore.restore_requests
- RESTORE_ADMIN_GROUP: admin-gruppe (default: admins)
- DATABRICKS_HOST: workspace host (sættes typisk af Databricks Apps)
"""

from __future__ import annotations

from datetime import date

import streamlit as st

import auth
import db

ENV_OPTIONS = ("dev", "test", "prod")
RESTORE_SCHEMA_OPTIONS = ("yes", "no")


def _init_session() -> None:
    if "page" not in st.session_state:
        st.session_state.page = "order"
    if "table_ready" not in st.session_state:
        st.session_state.table_ready = False


def _render_sidebar(user: auth.CurrentUser) -> None:
    st.sidebar.markdown(f"**{user.display_name}**")
    st.sidebar.caption(user.user_name)

    if st.sidebar.button("Bestil restore", use_container_width=True):
        st.session_state.page = "order"

    if auth.is_restore_admin(user):
        if st.sidebar.button("Til godkendelse", use_container_width=True):
            st.session_state.page = "approval"


def _validate_order_form(env: str, restore_to_new_schema: str) -> list[str]:
    errors: list[str] = []
    if env not in ENV_OPTIONS:
        errors.append("Environment skal være dev, test eller prod.")
    if restore_to_new_schema not in RESTORE_SCHEMA_OPTIONS:
        errors.append("Restore to new schema skal være yes eller no.")
    return errors


def _render_order_page(user: auth.CurrentUser) -> None:
    st.title("Bestil restore")

    with st.form("restore_order_form"):
        catalog_identifier = st.text_input(
            "Catalog identifier",
            help="Blank er tilladt",
        )
        env = st.selectbox(
            "Environment",
            options=ENV_OPTIONS,
            help="Bruges til at udlede catalog + volume",
        )
        source_schema = st.text_input(
            "Source schema",
            help="Blank betyder alle schemas",
        )
        restore_to_new_schema = st.radio(
            "Restore to new schema",
            options=RESTORE_SCHEMA_OPTIONS,
            index=1,
            horizontal=True,
        )
        use_backup_date = st.checkbox("Angiv backup date")
        backup_date_value = None
        if use_backup_date:
            backup_date_value = st.date_input(
                "Backup date",
                help="Blank betyder latest backup",
            )
        specific_tables = st.text_area(
            "Specific tables",
            help="Blank betyder alle tabeller. Ved flere tabeller: én pr. linje eller kommasepareret",
        )

        submitted = st.form_submit_button("Opret restore-bestilling")

    if not submitted:
        return

    errors = _validate_order_form(env, restore_to_new_schema)
    if errors:
        for msg in errors:
            st.error(msg)
        return

    backup_date_str = backup_date_value.isoformat() if backup_date_value else None
    tables_normalized = db.normalize_specific_tables(specific_tables)

    try:
        request_id = db.create_restore_request(
            created_by=user.user_name,
            created_by_display_name=user.display_name,
            catalog_identifier=catalog_identifier.strip() or None,
            env=env,
            source_schema=source_schema.strip() or None,
            restore_to_new_schema=restore_to_new_schema,
            backup_date=backup_date_str,
            specific_tables=tables_normalized,
        )
        st.success(f"Restore-bestilling oprettet. Request ID: `{request_id}`")
    except Exception as err:
        st.error("Kunne ikke oprette restore-bestilling.")
        st.exception(err)


def _render_approval_page(user: auth.CurrentUser) -> None:
    if not auth.is_restore_admin(user):
        st.error("Du har ikke adgang til godkendelse.")
        st.session_state.page = "order"
        st.rerun()

    st.title("Til godkendelse")

    try:
        pending = db.get_pending_restore_requests()
    except Exception as err:
        st.error("Kunne ikke hente pending restore-bestillinger.")
        st.exception(err)
        return

    if not pending:
        st.info("Ingen restore-bestillinger med status PENDING.")
        return

    for row in pending:
        request_id = row["request_id"]
        with st.expander(f"{request_id} — {row.get('env', '')} — {row.get('created_by', '')}"):
            st.write(f"**Request ID:** `{request_id}`")
            st.write(f"**Oprettet:** {row.get('created_at')}")
            st.write(f"**Oprettet af:** {row.get('created_by')}")
            st.write(f"**Environment:** {row.get('env')}")
            st.write(f"**Catalog identifier:** {row.get('catalog_identifier') or '(blank)'}")
            st.write(f"**Source schema:** {row.get('source_schema') or '(blank)'}")
            st.write(f"**Restore to new schema:** {row.get('restore_to_new_schema')}")
            st.write(f"**Backup date:** {row.get('backup_date') or '(latest)'}")
            st.write(f"**Specific tables:** {row.get('specific_tables') or '(alle)'}")
            st.write(f"**Status:** {row.get('status')}")

            col_approve, col_reject = st.columns(2)
            with col_approve:
                if st.button("Godkend", key=f"approve_{request_id}", use_container_width=True):
                    if not auth.is_restore_admin(user):
                        st.error("Kun admins kan godkende.")
                        return
                    try:
                        if db.approve_restore_request(request_id, user.user_name):
                            st.success(f"Request `{request_id}` er godkendt.")
                            st.rerun()
                        else:
                            st.warning("Requesten blev ikke opdateret (måske allerede behandlet).")
                            st.rerun()
                    except Exception as err:
                        st.error("Godkendelse fejlede.")
                        st.exception(err)
            with col_reject:
                if st.button("Afvis", key=f"reject_{request_id}", use_container_width=True):
                    if not auth.is_restore_admin(user):
                        st.error("Kun admins kan afvise.")
                        return
                    try:
                        if db.reject_restore_request(request_id, user.user_name):
                            st.success(f"Request `{request_id}` er afvist.")
                            st.rerun()
                        else:
                            st.warning("Requesten blev ikke opdateret (måske allerede behandlet).")
                            st.rerun()
                    except Exception as err:
                        st.error("Afvisning fejlede.")
                        st.exception(err)


def main() -> None:
    st.set_page_config(page_title="Restore", page_icon="🔄")
    _init_session()

    if not auth.get_user_token():
        st.error(
            "Ingen bruger-token fundet. Aktivér on-behalf-of user authorization på appen "
            "og genstart den fuldt (stop + start)."
        )
        st.stop()

    try:
        user = auth.get_current_user()
    except Exception as err:
        st.error("Kunne ikke hente brugerinformation.")
        st.exception(err)
        st.stop()

    _render_sidebar(user)

    if not st.session_state.table_ready:
        try:
            db.ensure_restore_requests_table()
            st.session_state.table_ready = True
        except Exception as err:
            st.error("Kunne ikke initialisere restore_requests-tabellen.")
            st.exception(err)
            st.stop()

    if st.session_state.page == "approval":
        _render_approval_page(user)
    else:
        _render_order_page(user)


if __name__ == "__main__":
    main()
