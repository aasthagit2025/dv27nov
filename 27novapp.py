# =========================
# DV VALIDATION APP – FINAL (OE FIX INCLUDED)
# =========================

import streamlit as st
import pandas as pd
import numpy as np
import os
import time
import tempfile

FLAG_PREFIX = "xx"

st.set_page_config(layout="wide")
st.title("📊 Survey Data Validation Automation")
st.markdown("Generates **KnowledgeExcel-compatible SPSS DV syntax** using a **variable-centric UI** (No VBA).")
st.markdown("---")

# ---------------- STATE INIT ----------------
for k in [
    'sq_rules','mq_rules','ranking_rules','string_rules',
    'straightliner_rules','all_cols'
]:
    if k not in st.session_state:
        st.session_state[k] = []

# ---------------- DATA LOADER ----------------
def load_data(uploaded):
    ext = os.path.splitext(uploaded.name)[1].lower()
    if ext == ".csv":
        return pd.read_csv(uploaded)
    elif ext in [".xls",".xlsx"]:
        return pd.read_excel(uploaded)
    elif ext in [".sav",".zsav"]:
        with tempfile.NamedTemporaryFile(delete=False,suffix=ext) as f:
            f.write(uploaded.getbuffer())
            path = f.name
        df = pd.read_spss(path,convert_categoricals=False)
        os.remove(path)
        return df
    else:
        raise Exception("Unsupported file format")

# ---------------- SKIP LOGIC (KE FORMAT) ----------------
def generate_skip_spss_syntax(target, trigger_col, trigger_val, rule_type):
    base = target.split("_")[0]
    filter_flag = f"Flag_{base}"
    final_flag = f"{FLAG_PREFIX}{base}"

    syntax = []
    syntax.append(f"**************************************SKIP LOGIC FILTER FLAG: {trigger_col}={trigger_val} -> {base}")
    syntax.append(f"IF({trigger_col}={trigger_val}) {filter_flag}=1.")
    syntax.append("EXECUTE.\n")

    if rule_type == "String":
        eoo = f"({target}='' | miss({target}))"
        eoc = f"({target}<>'' & ~miss({target}))"
    else:
        eoo = f"miss({target})"
        eoc = f"~miss({target})"

    syntax.append(f"**************************************SKIP LOGIC EoO/EoC CHECK: {target} -> {final_flag}")
    syntax.append(f"IF({filter_flag}=1 & {eoo}) {final_flag}=1.")
    syntax.append(f"IF(({filter_flag}<>1 | miss({filter_flag})) & {eoc}) {final_flag}=2.")
    syntax.append("EXECUTE.\n")

    return syntax,[filter_flag,final_flag]

# ---------------- STRING / OE SYNTAX ----------------
def generate_string_spss(rule):
    col = rule['variable']
    syntax=[]
    flags=[]

    # Junk check
    flag_junk = f"{FLAG_PREFIX}{col}_Junk"
    syntax.append(f"**************************************OE JUNK CHECK: {col}")
    syntax.append(f"IF(~miss({col}) & {col}<>'' & LENGTH(RTRIM({col}))<{rule['min_length']}) {flag_junk}=1.")
    syntax.append("EXECUTE.\n")
    flags.append(flag_junk)

    # OE Skip Logic
    if rule['run_skip']:
        sl,fl = generate_skip_spss_syntax(
            col,rule['trigger_col'],rule['trigger_val'],'String'
        )
        syntax.extend(sl)
        flags.extend(fl)
    else:
        flag_miss = f"{FLAG_PREFIX}{col}_Miss"
        syntax.append(f"**************************************OE MANDATORY CHECK: {col}")
        syntax.append(f"IF({col}='' | miss({col})) {flag_miss}=1.")
        syntax.append("EXECUTE.\n")
        flags.append(flag_miss)

    return syntax,flags

# ---------------- STRING CONFIG UI (UPDATED) ----------------
def configure_string_rules(all_vars):
    st.subheader("4️⃣ Open-End / OE Validation")

    oe_vars = st.multiselect(
        "Select OE / TEXT Variables",
        st.session_state.all_cols,
        key="oe_batch"
    )

    if not oe_vars:
        return

    with st.form("oe_form"):
        new_rules=[]
        for i,col in enumerate(oe_vars):
            st.markdown(f"### ⚙️ {col}")

            min_len = st.number_input(
                "Minimum Length (Junk Check)",
                min_value=1,value=5,
                key=f"oe_len_{i}"
            )

            run_skip = st.checkbox(
                "Enable OE Skip Logic (Controlled Question)",
                key=f"oe_skip_{i}"
            )

            if run_skip:
                c1,c2 = st.columns(2)
                with c1:
                    trig_col = st.selectbox(
                        "Parent / Controlling Question",
                        ['-- Select --']+all_vars,
                        key=f"oe_trig_col_{i}"
                    )
                with c2:
                    trig_val = st.text_input(
                        "Value that ENABLES OE (e.g. 99)",
                        key=f"oe_trig_val_{i}"
                    )
            else:
                trig_col='-- Select --'
                trig_val=''

            new_rules.append({
                'variable':col,
                'min_length':min_len,
                'run_skip':run_skip and trig_col!='-- Select --',
                'trigger_col':trig_col,
                'trigger_val':trig_val
            })

        if st.form_submit_button("✅ Save OE Rules"):
            st.session_state.string_rules.extend(new_rules)
            st.success("OE rules saved")
            st.rerun()

# ---------------- MASTER SYNTAX ----------------
def generate_master():
    all_syntax=[]
    all_flags=[]

    for r in st.session_state.string_rules:
        s,f=generate_string_spss(r)
        all_syntax.extend(s)
        all_flags.extend(f)

    sps=[]
    sps.append("*============================================================*")
    sps.append("* PYTHON GENERATED DV SCRIPT – KNOWLEDGEEXCEL FORMAT *")
    sps.append("*============================================================*\n")
    sps.append("DATASET ACTIVATE ALL.\n")

    if all_flags:
        sps.append(f"NUMERIC {'; '.join(sorted(set(all_flags)))}.")
        sps.append(f"RECODE {'; '.join(sorted(set(all_flags)))} (ELSE=0).")
        sps.append("EXECUTE.\n")

    sps.append("\n* --- VALIDATION LOGIC --- *")
    sps.extend(all_syntax)

    return "\n".join(sps)

# ---------------- MAIN APP ----------------
st.header("Step 1: Upload Survey Data")
uploaded = st.file_uploader("Upload CSV / Excel / SPSS",type=["csv","xls","xlsx","sav","zsav"])

if uploaded:
    df = load_data(uploaded)
    st.session_state.all_cols = sorted(df.columns.tolist())
    st.success(f"Loaded {len(df)} rows, {len(df.columns)} columns")

    configure_string_rules(st.session_state.all_cols)

    st.header("Step 3: Generate Syntax")
    if st.session_state.string_rules:
        final_sps = generate_master()
        st.download_button(
            "⬇️ Download SPSS DV Syntax",
            final_sps,
            file_name="dv_validation_knowledgeexcel.sps",
            mime="text/plain"
        )
        st.code(final_sps[:3000])
