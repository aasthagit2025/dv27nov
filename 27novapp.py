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

# Initialize state
for key in ['sq_rules', 'mq_rules', 'ranking_rules', 'string_rules', 'straightliner_rules', 'all_cols']:
    if key not in st.session_state:
        st.session_state[key] = []

# --- DATA LOADING ---
def load_data_file(uploaded_file):
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    na_values = ['', ' ', '#N/A', 'N/A', 'NA', '#NA', 'NULL', 'null']
    if file_extension in ['.csv']:
        try:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding='utf-8', na_values=na_values, keep_default_na=True)
        except:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding='latin-1', na_values=na_values, keep_default_na=True)
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

def generate_string_spss_syntax(rule):
    """Updated OE syntax generator: Adds Skip/Filter Logic."""
    col = rule['variable']
    target_clean = col.split('_')[0] if '_' in col else col
    filter_flag = f"Flag_{target_clean}" 
    final_error_flag = f"{FLAG_PREFIX}{col}"
    
    syntax = []
    # Length Check
    flag_junk = f"{FLAG_PREFIX}{col}_Junk"
    syntax.append(f"**************************************OE Length Check: {col}")
    syntax.append(f"IF(~miss({col}) & {col}<>'' & LENGTH(RTRIM({col})) < {rule['min_len']}) {flag_junk}=1.")
    
    # Filter/Skip Logic
    if rule.get('run_skip') and rule['trigger_col'] != '-- Select Variable --':
        syntax.append(f"IF({rule['trigger_col']} = {rule['trigger_val']}) {filter_flag}=1.")
        # Error of Omission (1): Triggered but empty
        syntax.append(f"IF({filter_flag} = 1 & ({col}='' | miss({col}))) {final_error_flag}=1.")
        # Error of Commission (2): Not triggered but has text
        syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & ({col}<>'' & ~miss({col}))) {final_error_flag}=2.")
    else:
        # Standard mandatory check
        flag_miss = f"{FLAG_PREFIX}{col}_Miss"
        syntax.append(f"IF({col}='' | miss({col})) {flag_miss}=1.")
    
    syntax.append("EXECUTE.\n")
    return syntax, [flag_junk, filter_flag, final_error_flag]

# --- UI LOGIC ---

uploaded_file = st.file_uploader("Upload Data", type=['csv', 'xlsx', 'sav'])

if uploaded_file:
    df = load_data_file(uploaded_file)
    if df is not None:
        st.session_state.all_cols = list(df.columns)
        all_options = ['-- Select Variable --'] + st.session_state.all_cols

        # (SQ and MQ sections remain exactly as in your 27novapp.py)

        # 3. Open-Ended (OE) / String Rule
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
                        'variable': col, 'min_len': min_l, 
                        'trigger_col': t_col, 'trigger_val': t_val, 'run_skip': run_sk
                    })
                if st.form_submit_button("Add OE Rules to Queue"):
                    st.session_state.string_rules.extend(new_oe_rules)
                    st.session_state.oe_batch_vars = []
                    st.rerun()

        # (Straightliner, Ranking, and Master Syntax Generation remain as in your 27novapp.py)