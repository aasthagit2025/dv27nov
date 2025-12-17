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
st.title("📊 Survey Data Validation Automation")
st.markdown("Generates **KnowledgeExcel-compatible SPSS syntax** with Skip Logic and Frequencies.")

# Initialize state for storing rules
if 'sq_rules' not in st.session_state: st.session_state.sq_rules = []
if 'mq_rules' not in st.session_state: st.session_state.mq_rules = []
if 'string_rules' not in st.session_state: st.session_state.string_rules = []
if 'straightliner_rules' not in st.session_state: st.session_state.straightliner_rules = []
if 'all_cols' not in st.session_state: st.session_state.all_cols = []

# --- DATA LOADING ---
def load_data_file(uploaded_file):
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    if file_extension in ['.csv']:
        return pd.read_csv(uploaded_file)
    elif file_extension in ['.xlsx', '.xls']:
        return pd.read_excel(uploaded_file)
    elif file_extension in ['.sav', '.zsav']:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            tmp_path = tmp_file.name
        df = pd.read_spss(tmp_path, convert_categoricals=False)
        os.remove(tmp_path)
        return df

# --- SYNTAX GENERATORS ---
def generate_skip_spss_syntax(target_col, trigger_col, trigger_val, rule_type):
    target_clean = target_col.split('_')[0] if '_' in target_col else target_col
    filter_flag = f"Flag_{target_clean}" 
    final_error_flag = f"{FLAG_PREFIX}{target_clean}" 
    
    syntax = [
        f"* Filter logic: {target_clean} asked if {trigger_col} = {trigger_val}",
        f"IF({trigger_col} = {trigger_val}) {filter_flag}=1.",
        f"EXECUTE.\n"
    ]
    
    # Define EoO/EoC conditions based on type
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

# --- UPDATED MQ CONFIGURATION (With Skip/Filter) ---
def configure_mq_rules(all_variable_options):
    st.subheader("3. Multi-Select (MQ) Configuration")
    mq_cols = st.multiselect("Select Variables for MQ Group", st.session_state.all_cols, key='mq_batch')
    
    if st.button("Start MQ Config"):
        st.session_state.mq_batch_vars = mq_cols

    if st.session_state.get('mq_batch_vars'):
        mq_set_name = st.session_state.mq_batch_vars[0].split('_')[0]
        with st.form(f"mq_form_{mq_set_name}"):
            st.markdown(f"### ⚙️ Rule for **{mq_set_name}**")
            
            # Filter Inputs (Matching Screenshot)
            c1, c2 = st.columns(2)
            with c1:
                skip_col = st.selectbox("Filter/Trigger Variable", all_variable_options, key='mq_skip_col')
            with c2:
                skip_val = st.text_input("Filter Condition Value", "1", key='mq_skip_val')
            
            run_skip = st.checkbox("Enable Standard Skip Logic Check", key='mq_skip_enable')
            
            if st.form_submit_button("✅ Save MQ Rule"):
                st.session_state.mq_rules.append({
                    'variables': st.session_state.mq_batch_vars,
                    'run_skip': run_skip, 'trigger_col': skip_col, 'trigger_val': skip_val
                })
                st.session_state.mq_batch_vars = []
                st.rerun()

# --- UPDATED STRING CONFIGURATION (Matching Screenshot) ---
def configure_string_rules(all_variable_options):
    st.subheader("4. String/Open-End Configuration")
    string_cols = st.multiselect("Select Target Variables for String/OE", st.session_state.all_cols, key='str_batch')
    
    if st.button("Start String Config"):
        st.session_state.string_batch_vars = string_cols

    if st.session_state.get('string_batch_vars'):
        with st.form("string_form"):
            new_rules = []
            for i, col in enumerate(st.session_state.string_batch_vars):
                st.markdown(f"### ⚙️ Rule for **{col}**")
                min_len = st.number_input(f"Min Length for {col}", 1, 100, 5, key=f"slen_{i}")
                
                # Filter Inputs (Matching Screenshot)
                c1, c2 = st.columns(2)
                with c1:
                    skip_col = st.selectbox(f"Filter Variable for {col}", all_variable_options, key=f"scol_{i}")
                with c2:
                    skip_val = st.text_input(f"Filter Value for {col}", "1", key=f"sval_{i}")
                
                run_skip = st.checkbox(f"Enable Standard Skip Logic for {col}", key=f"sskip_{i}")
                
                new_rules.append({
                    'variable': col, 'min_length': min_len, 'run_skip': run_skip,
                    'trigger_col': skip_col, 'trigger_val': skip_val
                })
            
            if st.form_submit_button("✅ Save String Rules"):
                st.session_state.string_rules.extend(new_rules)
                st.session_state.string_batch_vars = []
                st.rerun()

# --- FINAL SYNTAX GENERATION (No Sum, Frequencies Only) ---
def generate_final_syntax():
    all_syntax = ["DATASET ACTIVATE ALL.\n"]
    all_flags = []

    # Process MQ Rules
    for rule in st.session_state.mq_rules:
        if rule['run_skip'] and rule['trigger_col'] != '-- Select Variable --':
            syn, flags = generate_skip_spss_syntax(rule['variables'][0], rule['trigger_col'], rule['trigger_val'], 'MQ')
            all_syntax.extend(syn); all_flags.extend(flags)

    # Process String Rules
    for rule in st.session_state.string_rules:
        if rule['run_skip'] and rule['trigger_col'] != '-- Select Variable --':
            syn, flags = generate_skip_spss_syntax(rule['variable'], rule['trigger_col'], rule['trigger_val'], 'String')
            all_syntax.extend(syn); all_flags.extend(flags)
        
        # Junk Check
        f_junk = f"{FLAG_PREFIX}{rule['variable']}_Junk"
        all_syntax.append(f"IF(~miss({rule['variable']}) & length(rtrim({rule['variable']}))<{rule['min_length']}) {f_junk}=1.")
        all_flags.append(f_junk)

    # Final Frequencies (REPLACES MASTER SUM)
    unique_flags = sorted(list(set(all_flags)))
    if unique_flags:
        all_syntax.insert(1, f"NUMERIC {' '.join(unique_flags)}.")
        all_syntax.insert(2, f"RECODE {' '.join(unique_flags)} (ELSE=0).\n")
        all_syntax.append("\n* --- VALIDATION FREQUENCIES --- *")
        all_syntax.append(f"FREQUENCIES VARIABLES={' '.join(unique_flags)} /ORDER=ANALYSIS.")
    
    return "\n".join(all_syntax)

# --- UI APP ---
uploaded_file = st.file_uploader("Upload Survey Data", type=['csv', 'xlsx', 'sav'])
if uploaded_file:
    df = load_data_file(uploaded_file)
    st.session_state.all_cols = list(df.columns)
    all_vars = ['-- Select Variable --'] + st.session_state.all_cols
    
    configure_mq_rules(all_vars)
    configure_string_rules(all_vars)
    
    if st.button("Generate Final Syntax"):
        final_code = generate_final_syntax()
        st.code(final_code, language='spss')
        st.download_button("Download Script (.sps)", final_code, "survey_validation.sps")