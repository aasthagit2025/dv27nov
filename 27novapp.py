import streamlit as st
import pandas as pd
import numpy as np
import io
import os 
import tempfile

# --- Configuration ---
FLAG_PREFIX = "xx" 
st.set_page_config(layout="wide", page_title="Survey Data Validation")
st.title("📊 Survey Data Validation Automation")
st.markdown("---")

# 1. Initialization (Ensures all UI buttons and state work correctly)
keys = [
    'sq_rules', 'mq_rules', 'ranking_rules', 'string_rules', 'straightliner_rules', 
    'all_cols', 'var_types', 'sq_batch_vars', 'mq_batch_vars', 'oe_batch_vars', 'rank_batch_vars'
]
for k in keys:
    if k not in st.session_state:
        st.session_state[k] = [] if k != 'var_types' else {}

# --- 2. DATA LOADING & TYPE DETECTION ---

def load_data_file(uploaded_file):
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    df = None
    try:
        if file_extension == '.csv':
            df = pd.read_csv(uploaded_file, na_values=['', ' '])
        elif file_extension in ['.xlsx', '.xls']:
            df = pd.read_excel(uploaded_file)
        elif file_extension in ['.sav', '.zsav']:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp:
                tmp.write(uploaded_file.getbuffer())
                tmp_path = tmp.name
            df = pd.read_spss(tmp_path, convert_categoricals=False)
            os.remove(tmp_path)
            
        if df is not None:
            st.session_state.all_cols = list(df.columns)
            st.session_state.var_types = {
                col: 'string' if pd.api.types.is_string_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]) else 'numeric'
                for col in df.columns
            }
            return df
    except Exception as e:
        st.error(f"Error: {e}")
    return None

# --- 3. LOGIC HELPERS ---

def is_string(col):
    return st.session_state.get('var_types', {}).get(col) == 'string'

def get_missing_logic(col):
    return f"({col} = '' | miss({col}))" if is_string(col) else f"miss({col})"

def get_answered_logic(col):
    return f"({col} <> '' & ~miss({col}))" if is_string(col) else f"~miss({col})"

# --- 4. SYNTAX GENERATORS ---

def generate_sq_spss_syntax(rule):
    col = rule['variable']
    syntax = [f"* SQ Check: {col}"]
    flag = f"{FLAG_PREFIX}{col}_Rng"
    
    if not is_string(col):
        syntax.append(f"IF({get_missing_logic(col)} | ~range({col},{rule['min_val']},{rule['max_val']})) {flag}=1.")
    else:
        syntax.append(f"IF({get_missing_logic(col)}) {flag}=1.")
    
    if rule.get('trigger_col') and rule['trigger_col'] != "-- Select Variable --":
        t_col, t_val = rule['trigger_col'], rule['trigger_val']
        t_logic = f"{t_col} = '{t_val}'" if is_string(t_col) else f"{t_col} = {t_val}"
        f_flag = f"Flag_{col}"
        syntax.append(f"IF({t_logic}) {f_flag}=1.")
        syntax.append(f"IF({f_flag}=1 & {get_missing_logic(col)}) {FLAG_PREFIX}{col}_Skip=1.")
        
    syntax.append("EXECUTE.\n")
    return syntax

def generate_string_spss_syntax(rule):
    col = rule['variable']
    flag = f"{FLAG_PREFIX}{col}_Str"
    syntax = [f"* OE/String Check: {col}", f"IF({get_missing_logic(col)}) {flag}=1."]
    
    if rule.get('trigger_col') and rule['trigger_col'] != "-- Select Variable --":
        t_col, t_val = rule['trigger_col'], rule['trigger_val']
        t_logic = f"{t_col} = '{t_val}'" if is_string(t_col) else f"{t_col} = {t_val}"
        syntax.append(f"IF({t_logic} & {get_missing_logic(col)}) {flag}_Skip=1.")
        
    syntax.append("EXECUTE.\n")
    return syntax

# --- 5. UI FLOW ---

uploaded_file = st.sidebar.file_uploader("Step 1: Upload Data", type=['sav', 'xlsx', 'csv'])

if uploaded_file:
    df = load_data_file(uploaded_file)
    if df is not None:
        st.success(f"Data loaded: {len(st.session_state.all_cols)} variables detected.")
        
        tab_sq, tab_oe, tab_mq, tab_final = st.tabs(["Single Select", "OE / Strings", "Multi-Select", "Generate Syntax"])
        
        with tab_sq:
            sel_sq = st.multiselect("Select SQ Variables", st.session_state.all_cols)
            if st.button("Configure SQ"): st.session_state.sq_batch_vars = sel_sq
            
            if st.session_state.sq_batch_vars:
                with st.form("sq_form"):
                    for c in st.session_state.sq_batch_vars:
                        st.markdown(f"**{c}** ({st.session_state.var_types[c]})")
                        c1, c2, c3 = st.columns(3)
                        min_v = c1.number_input(f"Min {c}", 1, key=f"min_{c}")
                        max_v = c2.number_input(f"Max {c}", 5, key=f"max_{c}")
                        trig = c3.selectbox(f"Trigger {c}", ["-- Select Variable --"] + st.session_state.all_cols, key=f"tr_{c}")
                        trig_v = st.text_input(f"Trigger Value {c}", "1", key=f"tv_{c}")
                        if st.form_submit_button("Save SQ"):
                            st.session_state.sq_rules.append({'variable': c, 'min_val': min_v, 'max_val': max_v, 'trigger_col': trig, 'trigger_val': trig_v})

        with tab_oe:
            sel_oe = st.multiselect("Select OE/String Variables", st.session_state.all_cols)
            if st.button("Configure OE"): st.session_state.oe_batch_vars = sel_oe
            
            if st.session_state.oe_batch_vars:
                with st.form("oe_form"):
                    for c in st.session_state.oe_batch_vars:
                        trig = st.selectbox(f"Trigger for {c}", ["-- Select Variable --"] + st.session_state.all_cols, key=f"oet_{c}")
                        trig_v = st.text_input(f"Value for {c}", "1", key=f"oev_{c}")
                        if st.form_submit_button(f"Save {c}"):
                            st.session_state.string_rules.append({'variable': c, 'trigger_col': trig, 'trigger_val': trig_v})

        with tab_final:
            if st.button("Generate Final SPSS Syntax"):
                full_syntax = ["* FINAL SPSS VALIDATION SYNTAX\n"]
                for r in st.session_state.sq_rules:
                    full_syntax.extend(generate_sq_spss_syntax(r))
                for r in st.session_state.string_rules:
                    full_syntax.extend(generate_string_spss_syntax(r))
                
                st.code("\n".join(full_syntax), language="spss")
                st.download_button("Download .sps", "\n".join(full_syntax), "validation.sps")