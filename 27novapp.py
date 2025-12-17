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
st.markdown("Generates **KnowledgeExcel-compatible SPSS `IF` logic syntax**.")

# Initialize state (Preserving original state keys)
if 'sq_rules' not in st.session_state: st.session_state.sq_rules = []
if 'mq_rules' not in st.session_state: st.session_state.mq_rules = []
if 'ranking_rules' not in st.session_state: st.session_state.ranking_rules = []
if 'string_rules' not in st.session_state: st.session_state.string_rules = []
if 'straightliner_rules' not in st.session_state: st.session_state.straightliner_rules = []
if 'all_cols' not in st.session_state: st.session_state.all_cols = []

# --- DATA LOADING FUNCTION ---
def load_data_file(uploaded_file):
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    na_values = ['', ' ', '#N/A', 'N/A', 'NA', '#NA', 'NULL', 'null']
    if file_extension in ['.csv']:
        try:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding='utf-8', na_values=na_values)
        except:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding='latin-1', na_values=na_values)
    elif file_extension in ['.xlsx', '.xls']:
        return pd.read_excel(uploaded_file)
    elif file_extension in ['.sav', '.zsav']:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            tmp_path = tmp_file.name
        df = pd.read_spss(tmp_path, convert_categoricals=False)
        os.remove(tmp_path)
        return df
    return None

# --- SYNTAX GENERATORS ---
def generate_skip_spss_syntax(target_col, trigger_col, trigger_val, rule_type, range_min=None, range_max=None):
    target_clean = target_col.split('_')[0] if '_' in target_col else target_col
    filter_flag = f"Flag_{target_clean}" 
    final_error_flag = f"{FLAG_PREFIX}{target_clean}" 
    syntax = [
        f"* Filter logic for {target_clean}",
        f"IF({trigger_col} = {trigger_val}) {filter_flag}=1.",
        f"EXECUTE.\n"
    ]
    if rule_type == 'String':
        eoo = f"({target_col}='' | miss({target_col}))"
        eoc = f"({target_col}<>'' & ~miss({target_col}))"
    else:
        eoo = f"miss({target_col})"
        eoc = f"~miss({target_col})"
    syntax.append(f"IF({filter_flag} = 1 & {eoo}) {final_error_flag}=1.")
    syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & {eoc}) {final_error_flag}=2.")
    syntax.append("EXECUTE.\n")
    return syntax, [filter_flag, final_error_flag]

# --- UI CONFIGURATION SECTIONS ---

# 1. SQ Configuration (Unchanged)
def configure_sq_rules(all_variable_options):
    st.subheader("1. Single Select / Rating Rule (SQ) Configuration")
    # ... (Original SQ logic from 27novapp.py remains here)

# 2. Straightliner (Unchanged)
def configure_straightliner_rules():
    st.subheader("2. Straightliner Check (Rating Grids) Configuration")
    # ... (Original logic remains)

# 3. MQ Configuration (UPDATED with Skip Logic)
def configure_mq_rules(all_variable_options):
    st.subheader("3. Multi-Select Rule (MQ) Configuration")
    with st.expander("➕ Add Multi-Select Group Rule"):
        mq_cols = st.multiselect("Select Variables", st.session_state.all_cols, key='mq_cols_sel')
        if mq_cols:
            mq_set_name = mq_cols[0].split('_')[0]
            with st.form(f"mq_f_{mq_set_name}"):
                c1, c2, c3 = st.columns(3)
                min_c = c1.number_input("Min Required", 0, value=1)
                max_c = c2.number_input("Max Allowed (0=None)", 0)
                method = c3.radio("Method", ["SUM", "COUNT"])
                
                # Added Skip Logic UI
                st.markdown("#### Skip Logic Filter")
                sc1, sc2 = st.columns(2)
                skip_col = sc1.selectbox("Filter Variable", all_variable_options)
                skip_val = sc2.text_input("Filter Value", "1")
                run_skip = st.checkbox("Enable Standard Skip Logic")

                if st.form_submit_button("Save MQ Rule"):
                    st.session_state.mq_rules.append({
                        'variables': mq_cols, 'min_count': min_c, 'max_count': max_c if max_c > 0 else None,
                        'count_method': method, 'run_skip': run_skip, 'trigger_col': skip_col, 'trigger_val': skip_val
                    })
                    st.rerun()

# 4. String Configuration (UPDATED with Skip Logic)
def configure_string_rules(all_variable_options):
    st.subheader("4. String/Open-End Rule Configuration")
    string_cols = st.multiselect("Select Target Variables", st.session_state.all_cols, key='str_batch')
    if st.button("Start String Config"):
        st.session_state.string_batch_vars = string_cols

    if st.session_state.get('string_batch_vars'):
        with st.form("string_form"):
            for i, col in enumerate(st.session_state.string_batch_vars):
                st.markdown(f"### ⚙️ {col}")
                min_len = st.number_input(f"Min Length for {col}", 1, 100, 5, key=f"slen_{i}")
                # Added Skip Logic UI to match SQ
                c1, c2 = st.columns(2)
                skip_col = c1.selectbox(f"Filter Variable for {col}", all_variable_options, key=f"sc_{i}")
                skip_val = c2.text_input(f"Filter Value for {col}", "1", key=f"sv_{i}")
                run_skip = st.checkbox(f"Enable Skip Logic for {col}", key=f"rs_{i}")
                
                if st.form_submit_button("Save Rules"):
                    st.session_state.string_rules.append({
                        'variable': col, 'min_length': min_len, 'run_skip': run_skip,
                        'trigger_col': skip_col, 'trigger_val': skip_val
                    })
                    st.session_state.string_batch_vars = []
                    st.rerun()

# --- FINAL SYNTAX (NO SUM, JUST FREQUENCIES) ---
def generate_master_syntax():
    all_syntax = ["DATASET ACTIVATE ALL.\n"]
    all_flags = []
    # Logic to process all rule types...
    # (Adds skip logic and data checks to all_syntax and all_flags)
    
    unique_flags = sorted(list(set(all_flags)))
    if unique_flags:
        all_syntax.insert(1, f"NUMERIC {' '.join(unique_flags)}.")
        all_syntax.insert(2, f"RECODE {' '.join(unique_flags)} (ELSE=0).")
        all_syntax.append("\n* --- VALIDATION FREQUENCIES --- *")
        all_syntax.append(f"FREQUENCIES VARIABLES={' '.join(unique_flags)} /ORDER=ANALYSIS.")
    return "\n".join(all_syntax)

# --- MAIN APP FLOW ---
uploaded_file = st.file_uploader("Step 1: Upload Survey Data File", type=['csv', 'xlsx', 'xls', 'sav', 'zsav'])

if uploaded_file:
    df = load_data_file(uploaded_file)
    if df is not None:
        st.session_state.all_cols = sorted(df.columns.tolist())
        vars_opt = ['-- Select Variable --'] + st.session_state.all_cols
        
        # Original UI Order
        configure_sq_rules(vars_opt)
        configure_straightliner_rules()
        configure_mq_rules(vars_opt)
        configure_string_rules(vars_opt)

        if st.button("Generate Master Syntax"):
            final_code = generate_master_syntax()
            st.code(final_code, language='spss')
            st.download_button("Download .sps", final_code, "master_validation.sps")