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

# Initialize state for storing final, configured rules
if 'sq_rules' not in st.session_state:
    st.session_state.sq_rules = []
if 'mq_rules' not in st.session_state:
    st.session_state.mq_rules = []
if 'ranking_rules' not in st.session_state:
    st.session_state.ranking_rules = []
if 'string_rules' not in st.session_state:
    st.session_state.string_rules = []
if 'straightliner_rules' not in st.session_state: 
    st.session_state.straightliner_rules = []
if 'all_cols' not in st.session_state:
    st.session_state.all_cols = []
    
# --- DATA LOADING FUNCTION ---
def load_data_file(uploaded_file):
    """Reads data from CSV, Excel, or SPSS data files, handling different formats."""
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

# --- CORE UTILITY FUNCTIONS ---

def generate_sq_spss_syntax(rule):
    col = rule['variable']
    target_clean = col.split('_')[0] if '_' in col else col
    filter_flag = f"Flag_{target_clean}" 
    final_error_flag = f"{FLAG_PREFIX}{col}" 
    
    syntax = []
    # Missing/Range Check (Always runs for SQ)
    flag_rng = f"{FLAG_PREFIX}{col}_Rng"
    syntax.append(f"**************************************SQ Missing/Range Check: {col} (Range: {rule['min_val']} to {rule['max_val']})")
    syntax.append(f"IF(miss({col}) | ~range({col},{rule['min_val']},{rule['max_val']})) {flag_rng}=1.")
    syntax.append(f"EXECUTE.\n")

    if rule['run_skip'] and rule['trigger_col'] != '-- Select Variable --':
        syntax.append(f"**************************************SKIP LOGIC: {rule['trigger_col']}={rule['trigger_val']} -> {col}")
        syntax.append(f"IF({rule['trigger_col']} = {rule['trigger_val']}) {filter_flag}=1.")
        syntax.append(f"EXECUTE.\n")
        syntax.append(f"IF({filter_flag} = 1 & miss({col})) {final_error_flag}=1.")
        syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & ~miss({col})) {final_error_flag}=2.")
        syntax.append("EXECUTE.\n")
    
    generated_flags = [flag_rng]
    if rule['run_skip']: generated_flags.extend([filter_flag, final_error_flag])
    
    return syntax, generated_flags

def generate_string_spss_syntax(rule):
    """Updated OE syntax generator to handle Skip Logic correctly."""
    col = rule['variable']
    target_clean = col.split('_')[0] if '_' in col else col
    filter_flag = f"Flag_{target_clean}" 
    final_error_flag = f"{FLAG_PREFIX}{col}"
    
    syntax = []
    # Junk Check (Length)
    flag_junk = f"{FLAG_PREFIX}{col}_Junk"
    syntax.append(f"**************************************OE Length/Junk Check: {col}")
    syntax.append(f"IF(~miss({col}) & {col}<>'' & LENGTH(RTRIM({col})) < {rule['min_length']}) {flag_junk}=1.")
    syntax.append(f"EXECUTE.\n")

    if rule.get('run_skip') and rule['trigger_col'] != '-- Select Variable --':
        syntax.append(f"**************************************OE SKIP LOGIC: {rule['trigger_col']}={rule['trigger_val']} -> {col}")
        syntax.append(f"IF({rule['trigger_col']} = {rule['trigger_val']}) {filter_flag}=1.")
        syntax.append(f"EXECUTE.\n")
        # EoO (1): Triggered but empty
        syntax.append(f"IF({filter_flag} = 1 & ({col}='' | miss({col}))) {final_error_flag}=1.")
        # EoC (2): Not triggered but has content
        syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & ({col}<>'' & ~miss({col}))) {final_error_flag}=2.")
        syntax.append("EXECUTE.\n")
    else:
        # Standard Mandatory Check
        flag_miss = f"{FLAG_PREFIX}{col}_Miss"
        syntax.append(f"IF({col}='' | miss({col})) {flag_miss}=1.")
        syntax.append(f"EXECUTE.\n")

    return syntax, [flag_junk, filter_flag, final_error_flag] if rule.get('run_skip') else [flag_junk, f"{FLAG_PREFIX}{col}_Miss"]

# --- (Rest of MQ, Ranking, Straightliner functions remain identical to your 27novapp.py) ---
def generate_mq_spss_syntax(rule):
    cols = rule['variables']
    mq_set_name = cols[0].split('_')[0] if '_' in cols[0] else "MQ_Set"
    count_var = f"{mq_set_name}_Count"
    syntax = []
    syntax.append(f"**************************************MQ Check: {mq_set_name}")
    syntax.append(f"COMPUTE {count_var} = ANY(1, {' '.join(cols)}).") 
    syntax.append(f"IF({count_var} < {rule['min_count']}) {FLAG_PREFIX}{mq_set_name}_Min=1.")
    if rule['max_count']:
        syntax.append(f"IF({count_var} > {rule['max_count']}) {FLAG_PREFIX}{mq_set_name}_Max=1.")
    syntax.append("EXECUTE.\n")
    return syntax, [count_var]

def generate_ranking_spss_syntax(rule):
    cols = rule['variables']
    set_name = cols[0].split('_')[0] if '_' in cols[0] else "Rank_Set"
    syntax = [f"**************************************Ranking Check: {set_name}"]
    for c in cols:
        syntax.append(f"IF(miss({c}) | ~range({c},{rule['min_val']},{rule['max_val']})) {FLAG_PREFIX}{c}_Rng=1.")
    syntax.append("EXECUTE.\n")
    return syntax, [f"{FLAG_PREFIX}{c}_Rng" for c in cols]

def generate_straightliner_spss_syntax(rule):
    cols = rule['variables']
    set_name = cols[0].split('_')[0] if '_' in cols[0] else "SL_Set"
    syntax = [f"**************************************Straightliner Check: {set_name}",
              f"IF(MIN({' '.join(cols)}) = MAX({' '.join(cols)}) & ~miss({cols[0]})) {FLAG_PREFIX}{set_name}_Str=1.",
              "EXECUTE.\n"]
    return syntax, [f"{FLAG_PREFIX}{set_name}_Str"]

# --- UI LOGIC ---

uploaded_file = st.file_uploader("Upload Survey Data", type=['csv', 'xlsx', 'sav'])

if uploaded_file:
    df_raw = load_data_file(uploaded_file)
    st.session_state.all_cols = list(df_raw.columns)
    all_variable_options = ['-- Select Variable --'] + st.session_state.all_cols

    # --- STEP 2: CONFIGURATION ---
    st.header("Step 2: Configure Rules")
    
    # --- SQ SECTION (UNCHANGED) ---
    st.subheader("1. Single Select / Rating Rule (SQ)")
    sq_cols = st.multiselect("Select SQ Variables", st.session_state.all_cols, key='sq_ms')
    if st.button("Configure SQ Selection"):
        st.session_state.sq_batch_vars = sq_cols
    
    if st.session_state.get('sq_batch_vars'):
        with st.form("sq_batch_form"):
            new_rules = []
            for i, col in enumerate(st.session_state.sq_batch_vars):
                st.markdown(f"#### ⚙️ Configuration for: **{col}**")
                c1, c2 = st.columns(2)
                min_v = c1.number_input("Min Value", 1, 1000, 1, key=f"sq_min_{i}")
                max_v = c2.number_input("Max Value", 1, 1000, 5, key=f"sq_max_{i}")
                c3, c4 = st.columns(2)
                trig_col = c3.selectbox("Filter Variable (Optional)", all_variable_options, key=f"sq_trig_{i}")
                trig_val = c4.text_input("Filter Value", "1", key=f"sq_val_{i}")
                run_skip = st.checkbox("Enable Skip Logic (EoO/EoC)", value=False, key=f"sq_skip_{i}")
                new_rules.append({'variable': col, 'min_val': min_v, 'max_val': max_v, 'run_skip': run_skip, 'trigger_col': trig_col, 'trigger_val': trig_val})
            if st.form_submit_button("Add SQ Rules to Queue"):
                st.session_state.sq_rules.extend(new_rules)
                st.session_state.sq_batch_vars = []
                st.rerun()

    # --- MQ SECTION (UNCHANGED) ---
    st.subheader("2. Multi-Select Rule (MQ)")
    # (Existing MQ form logic from your 27novapp.py)
    mq_cols = st.multiselect("Select MQ Variables", st.session_state.all_cols, key='mq_ms')
    if st.button("Add MQ Rule"):
        if mq_cols:
            st.session_state.mq_rules.append({'variables': mq_cols, 'min_count': 1, 'max_count': None})

    # --- OE SECTION (FIXED AS REQUESTED) ---
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
                min_l = c1.number_input("Min Characters", 0, 500, 5, key=f"oe_len_{i}")
                trig_col = c2.selectbox("Filter Variable", all_variable_options, key=f"oe_trig_{i}")
                trig_val = c3.text_input("Filter Value", "1", key=f"oe_val_{i}")
                run_skip = st.checkbox("Enable Skip Logic (EoO/EoC)", value=False, key=f"oe_skip_{i}")
                new_oe_rules.append({'variable': col, 'min_length': min_l, 'run_skip': run_skip, 'trigger_col': trig_col, 'trigger_val': trig_val})
            if st.form_submit_button("Add OE Rules to Queue"):
                st.session_state.string_rules.extend(new_oe_rules)
                st.session_state.oe_batch_vars = []
                st.rerun()

    # --- (Rest of Ranking and Straightliner UI remain identical) ---
    # ...