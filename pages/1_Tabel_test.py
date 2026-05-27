import streamlit as st

from auth import get_user_token
from table_test_db import load_entries, save_entry, test_databricks_connection

st.title("Tabel-test")
st.caption("Simpel læs/skriv-test mod `app_test.simple_form_entries`.")

headers = st.context.headers
if not get_user_token(headers):
    st.warning(
        "Mangler x-forwarded-access-token. Tjek at User authorization er slået til, at appen "
        "har sql scope, og at appen er åbnet via Databricks Apps UI."
    )

field_1 = st.text_input("Felt 1")
field_2 = st.text_input("Felt 2")
field_3 = st.text_input("Felt 3")
field_4 = st.text_input("Felt 4")
field_5 = st.text_input("Felt 5")

col_save, col_load, col_test = st.columns(3)

if col_save.button("Gem", type="primary", use_container_width=True):
    try:
        row_id = save_entry(headers, field_1, field_2, field_3, field_4, field_5)
        st.success(f"Gemt med id `{row_id}`.")
    except Exception as err:
        st.error("Kunne ikke gemme i Databricks.")
        st.exception(err)

if col_load.button("Indlæs", use_container_width=True):
    try:
        rows = load_entries(headers)
        st.session_state["table_test_rows"] = rows
        st.success(f"Indlæste {len(rows)} række(r).")
    except Exception as err:
        st.error("Kunne ikke indlæse fra Databricks.")
        st.exception(err)

if col_test.button("Test Databricks forbindelse", use_container_width=True):
    result = test_databricks_connection(headers)
    st.session_state["table_test_connection_result"] = result
    st.json(result)
    if result.get("select_1_ok"):
        st.success("Forbindelse OK: SELECT 1 lykkedes.")
    else:
        error_type = result.get("error_type") or "UkendtFejl"
        error_message = result.get("error_message") or "Ingen fejlbesked."
        st.error(f"Forbindelsestest fejlede: {error_type}: {error_message}")

st.markdown("### Gemte rækker")
rows = st.session_state.get("table_test_rows")
if rows is None:
    st.info('Tryk "Indlæs" for at hente data fra tabellen.')
elif not rows:
    st.info("Tabellen er tom.")
else:
    st.dataframe(rows, use_container_width=True)
