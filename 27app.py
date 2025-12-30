import streamlit as st
import pandas as pd
import numpy as np
import io
import os 
import tempfile
import re

# --- 1. CONFIG & SYSTEM FILTER ---
FLAG_PREFIX = "xx" 
SYSTEM_VARS = ['sys_respnum', 'status', 'duration', 'starttime', 'endtime', 'uuid', 'recordid', 'respid', 'index', 'id', 'status_code']

st.set_page_config(layout="wide", page_title="Survey Data Validation")
st.title("📊 Survey Data Validation Automation")
st.markdown("---")

# 2. INITIALIZE SESSION STATE (The key to "Moving Ahead")
keys = [
    'sq_rules', 'mq_rules', 'ranking_rules', 'string_rules', 'straightliner_rules', 
    'all_cols', 'var_types', 'sq_batch_vars', 'mq_batch_vars', 'oe_batch_vars', 'rank_batch_vars'
]
for k in keys:
    if k not in st.session_state:
        st.session_state[k] = [] if k != 'var_types' else {}

# --- 3. DATA LOADING & SMART GROUPING ---

def load_data_file(uploaded_file):
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
            valid_cols = [c for c in df.columns if c.lower() not in SYSTEM_VARS]
            st.session_state.all_cols = valid_cols
            st.session_state.var_types = {
                col: 'String' if df[col].dtype == 'object' or pd.api.types.is_string_dtype(df[col]) else 'Numeric'
                for col in valid_cols
            }
            return df
    except Exception as e:
        st.error(f"Error loading file: {e}")
    return None

def get_variable_groups():
    """Detects groups like Q1_1, Q1_2, A4_r1, etc."""
    groups = {}
    for col in st.session_state.all_cols:
        # Matches prefix before underscore (e.g., 'Q1' from 'Q1_1')
        match = re.match(r'^([a-zA-Z0-9]+)_', col)
        if match:
            base = match.group(1)
            if base not in groups: groups[base] = []
            groups[base].append(col)
    return {k: v for k, v in groups.items() if len(v) > 1}

# --- 4. LOGIC HELPERS ---

def is_string(col):
    return st.session_state.var_types.get(col) == 'String'

def get_missing_logic(col):
    return f"({col} = '' | miss({col}))" if is_string(col) else f"miss({col})"

def get_answered_logic(col):
    return f"({col} <> '' & ~miss({col}))" if is_string(col) else f"~miss({col})"

# --- 5. SYNTAX GENERATORS ---

def generate_sq_spss_syntax(rule):
    col = rule['variable']
    syntax = [f"* SQ Check: {col}", f"IF({get_missing_logic(col)} | ~range({col},{rule['min_val']},{rule['max_val']})) {FLAG_PREFIX}{col}_Rng=1."]
    if rule.get('trig') and rule['trig'] != "-- Select Variable --":
        t_logic = f"{rule['trig']} = '{rule['trig_v']}'" if is_string(rule['trig']) else f"{rule['trig']} = {rule['trig_v']}"
        syntax.append(f"IF({t_logic} & {get_missing_logic(col)}) {FLAG_PREFIX}{col}_Skip=1.")
    return syntax + ["EXECUTE.\n"]

def generate_mq_spss_syntax(rule):
    v_list = " ".join(rule['variables'])
    base = rule['group_name']
    return [f"* MQ Check: {base}", f"COMPUTE {base}_Sum = SUM({v_list}).", 
            f"IF({base}_Sum < {rule['min_c']} & {get_answered_logic(rule['variables'][0])}) {FLAG_PREFIX}{base}_Min=1.", "EXECUTE.\n"]

def generate_string_spss_syntax(rule):
    col = rule['variable']
    syntax = [f"* OE Check: {col}", f"IF({get_missing_logic(col)}) {FLAG_PREFIX}{col}_Str=1."]
    if rule.get('trig') and rule['trig'] != "-- Select Variable --":
        t_logic = f"{rule['trig']} = '{rule['trig_v']}'" if is_string(rule['trig']) else f"{rule['trig']} = {rule['trig_v']}"
        syntax.append(f"IF({t_logic} & {get_missing_logic(col)}) {FLAG_PREFIX}{col}_Skip=1.")
    return syntax + ["EXECUTE.\n"]

def generate_straightliner_spss_syntax(rule):
    v_list = " ".join(rule['variables'])
    return [f"* Straightliner: {rule['group_name']}",
            f"IF(MIN({v_list}) = MAX({v_list}) & {get_answered_logic(rule['variables'][0])}) {FLAG_PREFIX}{rule['group_name']}_Str=1.",
            "EXECUTE.\n"]

# --- 6. UI TABS ---

uploaded_file = st.sidebar.file_uploader("Step 1: Upload Data", type=['sav', 'csv', 'xlsx'])

if uploaded_file:
    df = load_data_file(uploaded_file)
    if df is not None:
        groups = get_variable_groups()
        all_opts = ["-- Select Variable --"] + st.session_state.all_cols
        
        tab_sq, tab_mq, tab_oe, tab_sl, tab_final = st.tabs(["Single Select", "Multi-Select (MQ)", "Open Ends", "Rating Grids", "Finalize"])
        
        with tab_sq:
            st.subheader("Single Select (Numeric)")
            sel_sq = st.multiselect("Select SQ Variables", [c for c in st.session_state.all_cols if not is_string(c)])
            if st.button("Configure SQ"): st.session_state.sq_batch_vars = sel_sq
            
            if st.session_state.sq_batch_vars:
                with st.form("sq_f"):
                    for c in st.session_state.sq_batch_vars:
                        c1, c2, c3 = st.columns(3)
                        min_v = c1.number_input(f"Min {c}", 1, key=f"mi_{c}")
                        max_v = c2.number_input(f"Max {c}", 5, key=f"ma_{c}")
                        trig = c3.selectbox(f"Trigger {c}", all_opts, key=f"tr_{c}")
                        trig_v = st.text_input(f"Trig Val {c}", "1", key=f"tv_{c}")
                        if st.form_submit_button(f"Save {c}"):
                            st.session_state.sq_rules.append({'variable':c, 'min_val':min_v, 'max_val':max_v, 'trig':trig, 'trig_v':trig_v})

        with tab_mq:
            st.subheader("Multi-Select (Group Logic)")
            sel_g = st.selectbox("Select a Group (Q1, A4, etc.)", ["-- Select --"] + list(groups.keys()))
            mq_vars = st.multiselect("Variables", st.session_state.all_cols, default=groups.get(sel_g, []))
            if mq_vars:
                min_c = st.number_input("Min required", 1)
                if st.button("Add MQ Rule"):
                    st.session_state.mq_rules.append({'variables': mq_vars, 'min_c': min_c, 'group_name': sel_g if sel_g != "-- Select --" else mq_vars[0]})
                    st.success("Rule added!")

        with tab_oe:
            st.subheader("Open Ends (Strings)")
            sel_oe = st.multiselect("Select OE Variables", [c for c in st.session_state.all_cols if is_string(c)])
            if st.button("Configure OE"): st.session_state.oe_batch_vars = sel_oe
            
            if st.session_state.oe_batch_vars:
                with st.form("oe_f"):
                    for c in st.session_state.oe_batch_vars:
                        trig = st.selectbox(f"Trigger {c}", all_opts, key=f"ot_{c}")
                        trig_v = st.text_input(f"Trig Val {c}", "1", key=f"ov_{c}")
                        if st.form_submit_button(f"Save OE {c}"):
                            st.session_state.string_rules.append({'variable':c, 'trig':trig, 'trig_v':trig_v})

        with tab_sl:
            st.subheader("Straightlining")
            sl_g = st.selectbox("Select Rating Grid Group", ["-- Select --"] + list(groups.keys()))
            if sl_g != "-- Select --" and st.button(f"Add Straightliner for {sl_g}"):
                st.session_state.straightliner_rules.append({'variables': groups[sl_g], 'group_name': sl_g})

        with tab_final:
            if st.button("Generate Final SPSS Syntax"):
                full = ["* FINAL SYNTAX\n", "SET DECIMAL=DOT.\n"]
                for r in st.session_state.sq_rules: full.extend(generate_sq_spss_syntax(r))
                for r in st.session_state.mq_rules: full.extend(generate_mq_spss_syntax(r))
                for r in st.session_state.string_rules: full.extend(generate_string_spss_syntax(r))
                for r in st.session_state.straightliner_rules: full.extend(generate_straightliner_spss_syntax(r))
                st.code("\n".join(full), language="spss")
                st.download_button("Download .sps", "\n".join(full), "Validation.sps")