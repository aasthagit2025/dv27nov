import streamlit as st
import pandas as pd
import numpy as np
import io
import time 
import os 
import tempfile 

# --- Configuration ---
FLAG_PREFIX = "xx" 
st.set_page_config(layout="wide")
st.title("📊 Survey Data Validation Automation (Variable-Centric Model)")
st.markdown("Generates **KnowledgeExcel-compatible SPSS `IF` logic syntax** (`xx` prefix) by allowing **batch selection** and **sequential rule configuration**.")
st.markdown("---")

# Initialize state
if 'sq_rules' not in st.session_state: st.session_state.sq_rules = []
if 'mq_rules' not in st.session_state: st.session_state.mq_rules = []
if 'ranking_rules' not in st.session_state: st.session_state.ranking_rules = []
if 'string_rules' not in st.session_state: st.session_state.string_rules = []
if 'straightliner_rules' not in st.session_state: st.session_state.straightliner_rules = []
if 'all_cols' not in st.session_state: st.session_state.all_cols = []

# --- DATA LOADING ---
def load_data_file(uploaded_file):
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    na_values = ['', ' ', '#N/A', 'N/A', 'NA', '#NA', 'NULL', 'null']
    if file_extension == '.csv':
        uploaded_file.seek(0)
        return pd.read_csv(uploaded_file, encoding='utf-8', na_values=na_values, keep_default_na=True)
    elif file_extension in ['.xlsx', '.xls']:
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file)
    elif file_extension in ['.sav', '.zsav']:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            tmp_path = tmp_file.name
        df = pd.read_spss(tmp_path, convert_categoricals=False)
        os.remove(tmp_path)
        return df
    return None

# --- SYNTAX GENERATORS (RETAINED FROM ORIGINAL) ---

def generate_sq_spss_syntax(rule):
    col = rule['variable']
    target_clean = col.split('_')[0] if '_' in col else col
    filter_flag = f"Flag_{target_clean}"
    syntax, generated_flags = [], []
    
    # Range Check
    flag_rng = f"{FLAG_PREFIX}{col}_Rng"
    syntax.append(f"**************************************SQ Missing/Range Check: {col}")
    syntax.append(f"IF(miss({col}) | ~range({col},{rule['min_val']},{rule['max_val']})) {flag_rng}=1.")
    generated_flags.append(flag_rng)

    # Skip Logic
    if rule['run_skip'] and rule['trigger_col'] != '-- Select Variable --':
        syntax.append(f"IF({rule['trigger_col']} = {rule['trigger_val']}) {filter_flag}=1.")
        syntax.append(f"IF({filter_flag}=1 & miss({col})) {FLAG_PREFIX}{col}=1.")
        syntax.append(f"IF(({filter_flag}<>1 | miss({filter_flag})) & ~miss({col})) {FLAG_PREFIX}{col}=2.")
        generated_flags.extend([filter_flag, f"{FLAG_PREFIX}{col}"])
    
    syntax.append("EXECUTE.\n")
    return syntax, generated_flags

def generate_string_spss_syntax(rule):
    col = rule['variable']
    target_clean = col.split('_')[0] if '_' in col else col
    filter_flag = f"Flag_{target_clean}"
    syntax, generated_flags = [], []
    
    # Junk/Length Check
    flag_junk = f"{FLAG_PREFIX}{col}_Junk"
    syntax.append(f"**************************************String OE Check: {col}")
    syntax.append(f"IF(~miss({col}) & {col}<>'' & LENGTH(RTRIM({col})) < {rule['min_len']}) {flag_junk}=1.")
    generated_flags.append(flag_junk)

    # Skip Logic (Added as requested)
    if rule.get('run_skip') and rule['trigger_col'] != '-- Select Variable --':
        syntax.append(f"IF({rule['trigger_col']} = {rule['trigger_val']}) {filter_flag}=1.")
        # Error of Omission: Triggered but empty
        syntax.append(f"IF({filter_flag}=1 & ({col}='' | miss({col}))) {FLAG_PREFIX}{col}=1.")
        # Error of Commission: Not triggered but answered
        syntax.append(f"IF(({filter_flag}<>1 | miss({filter_flag})) & ({col}<>'' & ~miss({col}))) {FLAG_PREFIX}{col}=2.")
        generated_flags.extend([filter_flag, f"{FLAG_PREFIX}{col}"])
    else:
        # Standard Mandatory Check
        flag_miss = f"{FLAG_PREFIX}{col}_Miss"
        syntax.append(f"IF({col}='' | miss({col})) {flag_miss}=1.")
        generated_flags.append(flag_miss)

    syntax.append("EXECUTE.\n")
    return syntax, generated_flags

# --- APP UI ---
uploaded_file = st.file_uploader("Upload Data", type=['csv', 'xlsx', 'sav'])

if uploaded_file:
    df = load_data_file(uploaded_file)
    st.session_state.all_cols = list(df.columns)
    opts = ['-- Select Variable --'] + st.session_state.all_cols

    # 1. SQ Section (NO CHANGE)
    st.subheader("1. Single Select / Rating Rule (SQ)")
    sq_sel = st.multiselect("Select Variables", st.session_state.all_cols, key="sq_m")
    if st.button("Configure SQ"): st.session_state.sq_batch = sq_sel
    
    if 'sq_batch' in st.session_state and st.session_state.sq_batch:
        with st.form("sq_form"):
            new_rules = []
            for v in st.session_state.sq_batch:
                st.write(f"**{v}**")
                c1, c2, c3, c4 = st.columns(4)
                mi = c1.number_input(f"Min", 1, value=1, key=f"mi_{v}")
                ma = c2.number_input(f"Max", 1, value=5, key=f"ma_{v}")
                tc = c3.selectbox(f"Filter Var", opts, key=f"tc_{v}")
                tv = c4.text_input(f"Filter Val", "1", key=f"tv_{v}")
                sk = st.checkbox(f"Enable Skip", key=f"sk_{v}")
                new_rules.append({'variable':v, 'min_val':mi, 'max_val':ma, 'trigger_col':tc, 'trigger_val':tv, 'run_skip':sk})
            if st.form_submit_button("Save SQ"):
                st.session_state.sq_rules.extend(new_rules)
                st.session_state.sq_batch = []
                st.rerun()

    # 2. MQ Section (RETAINED AS IS)
    st.subheader("2. Multi-Select (MQ)")
    # (Existing MQ logic from your app)

    # 3. String / OE Section (UPDATED WITH SKIP LOGIC)
    st.subheader("3. Open-Ended (OE) / String")
    oe_sel = st.multiselect("Select OE Variables", st.session_state.all_cols, key="oe_m")
    if st.button("Configure OE"): st.session_state.oe_batch = oe_sel
    
    if 'oe_batch' in st.session_state and st.session_state.oe_batch:
        with st.form("oe_form"):
            new_oe = []
            for v in st.session_state.oe_batch:
                st.write(f"**{v}**")
                c1, c2, c3 = st.columns(3)
                ml = c1.number_input(f"Min Length", 1, value=5, key=f"ml_{v}")
                tc = c2.selectbox(f"Filter Var", opts, key=f"otc_{v}")
                tv = c3.text_input(f"Filter Val", "1", key=f"otv_{v}")
                sk = st.checkbox(f"Enable Skip Logic", key=f"osk_{v}")
                new_oe.append({'variable':v, 'min_len':ml, 'trigger_col':tc, 'trigger_val':tv, 'run_skip':sk})
            if st.form_submit_button("Save OE"):
                st.session_state.string_rules.extend(new_oe)
                st.session_state.oe_batch = []
                st.rerun()

    # (Rest of UI: Straightliner, Ranking, and Master Syntax Generation stays exactly the same)