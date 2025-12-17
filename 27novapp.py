# ===========================
# 27novapp.py – UPDATED (OE FIX ONLY)
# ===========================

import streamlit as st
import pandas as pd
import numpy as np
import io
import time
import os
import tempfile

FLAG_PREFIX = "xx"
st.set_page_config(layout="wide")
st.title("📊 Survey Data Validation Automation (Variable-Centric Model)")
st.markdown("Generates **KnowledgeExcel-compatible SPSS DV syntax** using Python (No VBA).")
st.markdown("---")

# ===========================
# SESSION STATE INIT
# ===========================
for key in [
    'sq_rules', 'mq_rules', 'ranking_rules',
    'string_rules', 'straightliner_rules',
    'all_cols'
]:
    if key not in st.session_state:
        st.session_state[key] = []

# ===========================
# DATA LOADING
# ===========================
def load_data_file(uploaded_file):
    ext = os.path.splitext(uploaded_file.name)[1].lower()

    if ext == ".csv":
        return pd.read_csv(uploaded_file)
    elif ext in [".xls", ".xlsx"]:
        return pd.read_excel(uploaded_file)
    elif ext in [".sav", ".zsav"]:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(uploaded_file.getbuffer())
            path = tmp.name
        df = pd.read_spss(path, convert_categoricals=False)
        os.remove(path)
        return df
    else:
        raise Exception("Unsupported file format")

# ===========================
# SKIP LOGIC GENERATOR
# ===========================
def generate_skip_spss_syntax(target_col, trigger_col, trigger_val, rule_type):
    base = target_col.split("_")[0]
    filter_flag = f"Flag_{base}"
    final_flag = f"{FLAG_PREFIX}{base}"

    syntax = []
    syntax.append(f"**************************************SKIP LOGIC FILTER FLAG: {trigger_col}={trigger_val} -> {base}")
    syntax.append(f"IF({trigger_col} = {trigger_val}) {filter_flag}=1.")
    syntax.append("EXECUTE.\n")

    if rule_type == "String":
        eoo = f"({target_col}='' | miss({target_col}))"
        eoc = f"({target_col}<>'' & ~miss({target_col}))"
    else:
        eoo = f"miss({target_col})"
        eoc = f"~miss({target_col})"

    syntax.append(f"**************************************SKIP LOGIC EoO/EoC CHECK: {target_col} -> {final_flag}")
    syntax.append(f"IF({filter_flag}=1 & {eoo}) {final_flag}=1.")
    syntax.append(f"IF(({filter_flag}<>1 | miss({filter_flag})) & {eoc}) {final_flag}=2.")
    syntax.append("EXECUTE.\n")

    return syntax, [filter_flag, final_flag]

# ===========================
# STRING / OE SYNTAX
# ===========================
def generate_string_spss_syntax(rule):
    col = rule['variable']
    syntax = []
    flags = []

    flag_junk = f"{FLAG_PREFIX}{col}_Junk"
    syntax.append(f"**************************************OE JUNK CHECK: {col}")
    syntax.append(
        f"IF(~miss({col}) & {col}<>'' & LENGTH(RTRIM({col})) < {rule['min_length']}) {flag_junk}=1."
    )
    syntax.append("EXECUTE.\n")
    flags.append(flag_junk)

    if rule['run_skip']:
        sl, fl = generate_skip_spss_syntax(
            col, rule['trigger_col'], rule['trigger_val'], "String"
        )
        syntax.extend(sl)
        flags.extend(fl)
    else:
        flag_miss = f"{FLAG_PREFIX}{col}_Miss"
        syntax.append(f"**************************************OE MANDATORY CHECK: {col}")
        syntax.append(f"IF({col}='' | miss({col})) {flag_miss}=1.")
        syntax.append("EXECUTE.\n")
        flags.append(flag_miss)

    return syntax, flags

# ===========================
# STRING / OE CONFIG UI (UPDATED)
# ===========================
def configure_string_rules(all_variable_options):
    st.subheader("4. String / Open-End (OE) Rule Configuration")

    string_cols = st.multiselect(
        "Select ALL OE / TEXT Variables (Qx_OE / TEXT)",
        st.session_state.all_cols,
        key='string_batch_select_key'
    )

    if st.button("Start / Update OE Rule Configuration"):
        st.session_state.string_batch_vars = string_cols

    st.markdown("---")

    if st.session_state.get('string_batch_vars'):
        with st.form("string_config_form"):
            new_rules = []

            for i, col in enumerate(st.session_state.string_batch_vars):
                st.markdown(f"### ⚙️ {col}")

                min_length = st.number_input(
                    "Minimum Length (Junk Check)",
                    min_value=1,
                    value=5,
                    key=f"oe_len_{i}"
                )

                run_skip = st.checkbox(
                    "Enable OE Skip Logic (EOO / EOC)",
                    key=f"oe_skip_{i}"
                )

                if run_skip:
                    st.info("Select the parent question and value that ENABLES this OE.")
                    c1, c2 = st.columns(2)
                    with c1:
                        trigger_col = st.selectbox(
                            "Parent / Controlling Question",
                            ['-- Select Variable --'] + all_variable_options,
                            key=f"oe_trig_col_{i}"
                        )
                    with c2:
                        trigger_val = st.text_input(
                            "Value that enables OE (e.g. 99)",
                            key=f"oe_trig_val_{i}"
                        )
                else:
                    trigger_col = '-- Select Variable --'
                    trigger_val = ''

                new_rules.append({
                    'variable': col,
                    'min_length': min_length,
                    'run_skip': run_skip and trigger_col != '-- Select Variable --',
                    'trigger_col': trigger_col,
                    'trigger_val': trigger_val
                })

            if st.form_submit_button("✅ Save OE Rules"):
                st.session_state.string_rules = [
                    r for r in st.session_state.string_rules
                    if r['variable'] not in st.session_state.string_batch_vars
                ] + new_rules
                st.session_state.string_batch_vars = []
                st.success("OE rules saved successfully.")
                st.rerun()

# ===========================
# MASTER SYNTAX GENERATION
# ===========================
def generate_master_spss_syntax():
    all_syntax = []
    all_flags = []

    for rule in st.session_state.string_rules:
        s, f = generate_string_spss_syntax(rule)
        all_syntax.extend(s)
        all_flags.extend(f)

    sps = []
    sps.append("*==============================================================*")
    sps.append("* PYTHON GENERATED DV SCRIPT – KNOWLEDGEEXCEL FORMAT *")
    sps.append("*==============================================================*\n")
    sps.append("DATASET ACTIVATE ALL.\n")

    if all_flags:
        sps.append(f"NUMERIC {'; '.join(sorted(set(all_flags)))}.")
        sps.append(f"RECODE {'; '.join(sorted(set(all_flags)))} (ELSE=0).")
        sps.append("EXECUTE.\n")

    sps.append("\n* --- DETAILED VALIDATION LOGIC --- *")
    sps.extend(all_syntax)

    return "\n".join(sps)

# ===========================
# MAIN APP
# ===========================
st.header("Step 1: Upload Survey Data")
uploaded_file = st.file_uploader(
    "Upload CSV / Excel / SPSS File",
    type=["csv", "xls", "xlsx", "sav", "zsav"]
)

if uploaded_file:
    df = load_data_file(uploaded_file)
    st.session_state.all_cols = sorted(df.columns.tolist())
    st.success(f"Loaded {len(df)} rows and {len(df.columns)} variables")

    configure_string_rules(st.session_state.all_cols)

    st.header("Step 3: Generate Syntax")
    if st.session_state.string_rules:
        final_syntax = generate_master_spss_syntax()
        st.download_button(
            "⬇️ Download SPSS DV Syntax",
            final_syntax,
            file_name="dv_validation_knowledgeexcel.sps",
            mime="text/plain"
        )
        st.code(final_syntax[:4000])
