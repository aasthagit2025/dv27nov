import streamlit as st
import pandas as pd
import numpy as np
import io
import os 
import tempfile
import re

# --- 1. CONFIG & SYSTEM FILTER ---
FLAG_PREFIX = "xx" 
# These variables will be hidden from all selection dropdowns
SYSTEM_VARS = ['sys_respnum', 'status', 'duration', 'starttime', 'endtime', 'uuid', 'recordid', 'respid', 'index', 'id', 'status_code']

st.set_page_config(layout="wide", page_title="Survey Data Validation")
st.title("📊 Survey Data Validation Automation")
st.markdown("---")

# --- 2. INITIALIZE SESSION STATE ---
# We use a robust initialization to prevent data loss when switching tabs
if 'sq_rules' not in st.session_state: st.session_state.sq_rules = []
if 'mq_rules' not in st.session_state: st.session_state.mq_rules = []
if 'string_rules' not in st.session_state: st.session_state.string_rules = []
if 'straightliner_rules' not in st.session_state: st.session_state.straightliner_rules = []
if 'all_cols' not in st.session_state: st.session_state.all_cols = []
if 'var_types' not in st.session_state: st.session_state.var_types = {}

# --- 3. DATA LOADING & SMART GROUPING ---

def load_data_file(uploaded_file):
    """Robust loader for SPSS, CSV, and Excel"""
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    df = None
    try:
        if file_extension == '.csv':
            df = pd.read_csv(uploaded_file, na_values=['', ' ', 'N/A'])
        elif file_extension in ['.xlsx', '.xls']:
            df = pd.read_excel(uploaded_file)
        elif file_extension in ['.sav', '.zsav']:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp:
                tmp.write(uploaded_file.getbuffer())
                df = pd.read_spss(tmp.name, convert_categoricals=False)
            os.remove(tmp.name)
            
        if df is not None:
            # Filter system vars
            valid_cols = [c for c in df.columns if c.lower() not in SYSTEM_VARS]
            st.session_state.all_cols = valid_cols
            
            # Detect String vs Numeric for logic automation
            st.session_state.var_types = {
                col: 'String' if df[col].dtype == 'object' or pd.api.types.is_string_dtype(df[col]) else 'Numeric'
                for col in valid_cols
            }
            return df
    except Exception as e:
        st.error(f"Error loading file: {e}")
    return None

def get_variable_groups():
    """Finds prefixes like Q1, A4 for Q1_1, A4_r1..."""
    groups = {}
    for col in st.session_state.all_cols:
        if "_" in col:
            base = col.split("_")[0]
            if base not in groups: groups[base] = []
            groups[base].append(col)
    return {k: v for k, v in groups.items() if len(v) > 1}

# --- 4. SYNTAX GENERATORS ---

def get_missing_logic(col):
    """Returns SPSS missing check based on data type"""
    is_str = st.session_state.var_types.get(col) == 'String'
    return f"({col} = '' | miss({col}))" if is_str else f"miss({col})"

def generate_sq_syntax(rule):
    col = rule['var']
    syntax = [f"* SQ Check: {col}"]
    # Standard range check for numeric variables
    syntax.append(f"IF({get_missing_logic(col)} | ~range({col},{rule['min']},{rule['max']})) {FLAG_PREFIX}{col}_Rng=1.")
    if rule['trig'] != "-- Select Variable --":
        t_logic = f"{rule['trig']} = '{rule['tr_v']}'" if st.session_state.var_types.get(rule['trig']) == 'String' else f"{rule['trig']} = {rule['tr_v']}"
        syntax.append(f"IF({t_logic} & {get_missing_logic(col)}) {FLAG_PREFIX}{col}_Skip=1.")
    return syntax + ["EXECUTE.\n"]

def generate_oe_syntax(rule):
    col = rule['var']
    # OE check flags empty strings or missing values
    syntax = [f"* OE Check: {col}", f"IF({get_missing_logic(col)}) {FLAG_PREFIX}{col}_Str=1."]
    if rule['trig'] != "-- Select Variable --":
        t_logic = f"{rule['trig']} = '{rule['tr_v']}'" if st.session_state.var_types.get(rule['trig']) == 'String' else f"{rule['trig']} = {rule['tr_v']}"
        syntax.append(f"IF({t_logic} & {get_missing_logic(col)}) {FLAG_PREFIX}{col}_Skip=1.")
    return syntax + ["EXECUTE.\n"]

# --- 5. MAIN UI ---

uploaded_file = st.sidebar.file_uploader("Upload Data", type=['sav', 'csv', 'xlsx'])

if uploaded_file:
    df = load_data_file(uploaded_file)
    if df is not None:
        groups = get_variable_groups()
        all_opts = ["-- Select Variable --"] + st.session_state.all_cols
        
        tab_sq, tab_mq, tab_oe, tab_sl, tab_final = st.tabs(["Single Select", "Multi-Select", "Open Ends", "Rating Grids", "Finalize"])
        
        with tab_sq:
            st.subheader("1. Single Select Rules")
            num_vars = [c for c in st.session_state.all_cols if st.session_state.var_types.get(c) == 'Numeric']
            # Direct rule addition without problematic "batch" buttons
            with st.expander("Add New SQ Rule"):
                col = st.selectbox("Select Variable", num_vars, key="sq_v")
                c1, c2 = st.columns(2)
                mi = c1.number_input("Min Valid", 1, key="sq_mi")
                ma = c2.number_input("Max Valid", 5, key="sq_ma")
                tr = st.selectbox("Trigger (Optional)", all_opts, key="sq_tr")
                tv = st.text_input("Trigger Value", "1", key="sq_tv")
                if st.button("Save SQ Rule"):
                    st.session_state.sq_rules.append({'var': col, 'min': mi, 'max': ma, 'trig': tr, 'tr_v': tv})
                    st.success(f"Added {col}")

        with tab_mq:
            st.subheader("2. Multi-Select (Group Logic)")
            sel_g = st.selectbox("Select Prefix Group (e.g. Q1, A4)", ["-- Select --"] + list(groups.keys()))
            mq_vars = st.multiselect("Active Variables", st.session_state.all_cols, default=groups.get(sel_g, []))
            if mq_vars:
                min_c = st.number_input("Min selections required", 1)
                if st.button("Add MQ Rule"):
                    st.session_state.mq_rules.append({'vars': mq_vars, 'min': min_c, 'name': sel_g if sel_g != "-- Select --" else mq_vars[0]})
                    st.success("MQ Rule Added")

        with tab_oe:
            st.subheader("3. Open Ends (String Checks)")
            str_vars = [c for c in st.session_state.all_cols if st.session_state.var_types.get(c) == 'String']
            with st.expander("Add New OE Rule"):
                col = st.selectbox("Select OE Variable", str_vars, key="oe_v")
                tr = st.selectbox("Trigger (Optional)", all_opts, key="oe_tr")
                tv = st.text_input("Trigger Value", "1", key="oe_tv")
                if st.button("Save OE Rule"):
                    st.session_state.string_rules.append({'var': col, 'trig': tr, 'tr_v': tv})
                    st.success(f"Added {col}")

        with tab_sl:
            st.subheader("4. Rating Grids (Straightlining)")
            sl_g = st.selectbox("Select Grid Prefix", ["-- Select --"] + list(groups.keys()), key="sl_sel")
            if sl_g != "-- Select --" and st.button(f"Add Straightliner for {sl_g}"):
                st.session_state.straightliner_rules.append({'vars': groups[sl_g], 'name': sl_g})
                st.success(f"Straightlining rule for {sl_g} added.")

        with tab_final:
            st.subheader("5. Review & Export")
            if st.button("Generate SPSS Syntax"):
                syntax = ["* SURVEY VALIDATION SCRIPT\n", "SET DECIMAL=DOT.\n"]
                for r in st.session_state.sq_rules: syntax.extend(generate_sq_syntax(r))
                for r in st.session_state.string_rules: syntax.extend(generate_oe_syntax(r))
                # MQ Logic
                for r in st.session_state.mq_rules:
                    v_list = " ".join(r['vars'])
                    syntax.append(f"COMPUTE {r['name']}_Sum = SUM({v_list}).")
                    syntax.append(f"IF({r['name']}_Sum < {r['min']}) {FLAG_PREFIX}{r['name']}_Min=1.")
                # Straightliner Logic
                for r in st.session_state.straightliner_rules:
                    v_list = " ".join(r['vars'])
                    syntax.append(f"IF(MIN({v_list}) = MAX({v_list}) & ~miss({r['vars'][0]})) {FLAG_PREFIX}{r['name']}_Str=1.")
                
                final_code = "\n".join(syntax + ["EXECUTE."])
                st.code(final_code, language="spss")
                st.download_button("Download .sps", final_code, "Validation.sps")

            if st.button("🗑️ Clear All Rules"):
                st.session_state.sq_rules = []
                st.session_state.mq_rules = []
                st.session_state.string_rules = []
                st.session_state.straightliner_rules = []
                st.rerun()