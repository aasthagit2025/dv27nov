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
st.markdown("Generates **KnowledgeExcel-compatible SPSS `IF` logic syntax** (`xx` prefix).")
st.markdown("---")

# Initialize state (Preserving all original state keys)
if 'sq_rules' not in st.session_state: st.session_state.sq_rules = []
if 'mq_rules' not in st.session_state: st.session_state.mq_rules = []
if 'ranking_rules' not in st.session_state: st.session_state.ranking_rules = []
if 'string_rules' not in st.session_state: st.session_state.string_rules = []
if 'straightliner_rules' not in st.session_state: st.session_state.straightliner_rules = []
if 'all_cols' not in st.session_state: st.session_state.all_cols = []

# --- Restored Data Loading Function ---
def load_data_file(uploaded_file):
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    na_values = ['', ' ', '#N/A', 'N/A', 'NA', '#NA', 'NULL', 'null']
    if file_extension in ['.csv']:
        try:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding='utf-8', na_values=na_values, keep_default_na=True)
        except Exception:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding='latin-1', na_values=na_values, keep_default_na=True)
    elif file_extension in ['.xlsx', '.xls']:
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file)
    elif file_extension in ['.sav', '.zsav']:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                tmp_file.write(uploaded_file.getbuffer())
                tmp_path = tmp_file.name
            df = pd.read_spss(tmp_path, convert_categoricals=False)
            os.remove(tmp_path)
            return df
        except Exception as e:
            if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)
            raise Exception(f"Failed to read SPSS file. Error: {e}")
    else:
        raise Exception(f"Unsupported format: {file_extension}")

# --- UPDATED OE SYNTAX GENERATOR ---
def generate_string_spss_syntax(rule):
    """Generates OE syntax with length check and optional Skip/Filter logic."""
    col = rule['variable']
    # Extract base name for Flag_ variable (e.g., Q10 from Q10_OE)
    target_clean = col.split('_')[0] if '_' in col else col
    filter_flag = f"Flag_{target_clean}" 
    final_error_flag = f"{FLAG_PREFIX}{col}"
    
    syntax = []
    # 1. Junk/Length Check (Always runs)
    flag_junk = f"{FLAG_PREFIX}{col}_Junk"
    syntax.append(f"**************************************OE Length Check: {col}")
    syntax.append(f"IF(~miss({col}) & {col}<>'' & LENGTH(RTRIM({col})) < {rule['min_len']}) {flag_junk}=1.")
    
    # 2. Skip Logic or Standard Mandatory Check
    if rule.get('run_skip') and rule['trigger_col'] != '-- Select Variable --':
        syntax.append(f"**************************************OE SKIP LOGIC: {rule['trigger_col']}={rule['trigger_val']} -> {col}")
        syntax.append(f"IF({rule['trigger_col']} = {rule['trigger_val']}) {filter_flag}=1.")
        syntax.append(f"EXECUTE.\n")
        # EoO (1): Triggered but empty
        syntax.append(f"IF({filter_flag} = 1 & ({col}='' | miss({col}))) {final_error_flag}=1.")
        # EoC (2): Not triggered but has content
        syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & ({col}<>'' & ~miss({col}))) {final_error_flag}=2.")
    else:
        # Standard Mandatory Check (if skip is not enabled)
        flag_miss = f"{FLAG_PREFIX}{col}_Miss"
        syntax.append(f"**************************************OE Mandatory Check: {col}")
        syntax.append(f"IF({col}='' | miss({col})) {flag_miss}=1.")
    
    syntax.append("EXECUTE.\n")
    # Return syntax list and list of all flags created to be initialized at top of file
    created_flags = [flag_junk]
    if rule.get('run_skip'): created_flags.extend([filter_flag, final_error_flag])
    else: created_flags.append(f"{FLAG_PREFIX}{col}_Miss")
    
    return syntax, created_flags

# --- APP UI ---
uploaded_file = st.file_uploader("Upload Survey Data", type=['csv', 'xlsx', 'sav'])

if uploaded_file:
    df_raw = load_data_file(uploaded_file)
    st.session_state.all_cols = list(df_raw.columns)
    all_options = ['-- Select Variable --'] + st.session_state.all_cols

    # --- (SQ, MQ, Ranking, Straightliner UI sections remain untouched as per your request) ---

    # --- UPDATED OE CONFIGURATION SECTION ---
    st.subheader("3. Open-Ended (OE) / String Rule")
    oe_cols = st.multiselect("Select OE Variables", st.session_state.all_cols, key='oe_ms')
    if st.button("Configure OE Selection"):
        st.session_state.oe_batch_vars = oe_cols

    if st.session_state.get('oe_batch_vars'):
        with st.form("oe_batch_form"):
            new_oe_rules = []
            for i, col in enumerate(st.session_state.oe_batch_vars):
                st.markdown(f"#### ⚙️ Configuration for: **{col}**")
                c1, c2, c3 = st.columns(3)
                min_l = c1.number_input("Min Characters", 0, 500, 5, key=f"oe_l_{i}")
                t_col = c2.selectbox("Filter Variable", all_options, key=f"oe_t_{i}")
                t_val = c3.text_input("Filter Value", "1", key=f"oe_v_{i}")
                run_sk = st.checkbox("Enable Skip Logic", value=False, key=f"oe_s_{i}")
                
                new_oe_rules.append({
                    'variable': col, 
                    'min_len': min_l, 
                    'trigger_col': t_col, 
                    'trigger_val': t_val, 
                    'run_skip': run_sk
                })
            if st.form_submit_button("Add OE Rules to Queue"):
                st.session_state.string_rules.extend(new_oe_rules)
                st.session_state.oe_batch_vars = []
                st.rerun()

    # --- (Master Syntax Generation logic remains untouched) ---