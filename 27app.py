import streamlit as st
import pandas as pd
import numpy as np
import io
import os 
import tempfile
import re

# --- 1. CONFIGURATION & SYSTEM FILTER ---
FLAG_PREFIX = "xx" 
# Variables that should never show up in any dropdown
SYSTEM_VARS = ['sys_respnum', 'status', 'duration', 'starttime', 'endtime', 'uuid', 'recordid', 'respid', 'index', 'id', 'status_code']

st.set_page_config(layout="wide", page_title="Survey Data Validation")
st.title("📊 Survey Data Validation Automation")
st.markdown("---")

# 2. INITIALIZE SESSION STATE (Fixed to prevent reset loops)
if 'sq_rules' not in st.session_state: st.session_state.sq_rules = []
if 'mq_rules' not in st.session_state: st.session_state.mq_rules = []
if 'string_rules' not in st.session_state: st.session_state.string_rules = []
if 'straightliner_rules' not in st.session_state: st.session_state.straightliner_rules = []
if 'all_cols' not in st.session_state: st.session_state.all_cols = []
if 'var_types' not in st.session_state: st.session_state.var_types = {}
if 'sq_batch_vars' not in st.session_state: st.session_state.sq_batch_vars = []
if 'oe_batch_vars' not in st.session_state: st.session_state.oe_batch_vars = []

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
            # Filter system variables
            valid_cols = [c for c in df.columns if c.lower() not in SYSTEM_VARS]
            st.session_state.all_cols = valid_cols
            
            # Auto-Detect Types: String vs Numeric
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
    syntax = [f"* SQ Check: {col}"]
    flag = f"{FLAG_PREFIX}{col}_Rng"
    if not is_string(col):
        syntax.append(f"IF({get_missing_logic(col)} | ~range({col},{rule['min_val']},{rule['max_val']})) {flag}=1.")
    else:
        syntax.append(f"IF({get_missing_logic(col)}) {flag}=1.")
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
        
        tab_sq, tab_mq, tab_oe, tab_sl, tab_final = st.tabs(["Single Select (SQ)", "Multi-Select (MQ)", "Open Ends (OE)", "Rating Grids", "Finalize"])
        
        with tab_sq:
            st.subheader("Configure Single Select Questions")
            num_vars = [c for c in st.session_state.all_cols if not is_string(c)]
            sq_sel = st.multiselect("Select Variables to Configure", num_vars, key="sq_multi")
            if st.button("Configure Selected SQ"):
                st.session_state.sq_batch_vars = sq_sel

            if st.session_state.sq_batch_vars:
                with st.form("sq_form"):
                    for c in st.session_state.sq_batch_vars:
                        st.markdown(f"**Settings for {c}**")
                        c1, c2, c3 = st.columns(3)
                        mi = c1.number_input(f"Min Valid {c}", 1, key=f"mi_{c}")
                        ma = c2.number_input(f"Max Valid {c}", 5, key=f"ma_{c}")
                        tr = c3.selectbox(f"Trigger {c}", all_opts, key=f"tr_{c}")
                        tv = st.text_input(f"Value {c}", "1", key=f"tv_{c}")
                        if st.form_submit_button(f"Save {c} Rule"):
                            st.session_state.sq_rules.append({'variable':c, 'min_val':mi, 'max_val':ma, 'trig':tr, 'trig_v':tv})
                            st.toast(f"Saved {c}")

        with tab_mq:
            st.subheader("Multi-Select Grouping")
            mq_g = st.selectbox("Select Group (Q1, A4, etc.)", ["-- Select --"] + list(groups.keys()), key="mq_g_sel")
            mq_v = st.multiselect("Confirm Variables", st.session_state.all_cols, default=groups.get(mq_g, []))
            if mq_v:
                min_c = st.number_input("Min selections required", 1, key="mq_min_val")
                if st.button("Add MQ Rule"):
                    st.session_state.mq_rules.append({'variables': mq_v, 'min_c': min_c, 'group_name': mq_g if mq_g != "-- Select --" else mq_v[0]})
                    st.success("MQ Rule Added")

        with tab_oe:
            st.subheader("Open Ended Configuration")
            str_vars = [c for c in st.session_state.all_cols if is_string(c)]
            oe_sel = st.multiselect("Select Variables", str_vars, key="oe_multi")
            if st.button("Configure Selected OE"):
                st.session_state.oe_batch_vars = oe_sel

            if st.session_state.oe_batch_vars:
                with st.form("oe_form"):
                    for c in st.session_state.oe_batch_vars:
                        st.markdown(f"**OE Trigger for {c}**")
                        tr = st.selectbox(f"Trigger {c}", all_options, key=f"oet_{c}")
                        tv = st.text_input(f"Value {c}", "1", key=f"oev_{c}")
                        if st.form_submit_button(f"Save OE {c}"):
                            st.session_state.string_rules.append({'variable':c, 'trig':tr, 'trig_v':tv})
                            st.toast(f"Saved {c}")

        with tab_sl:
            st.subheader("Straightlining")
            sl_g = st.selectbox("Select Grid Group", ["-- Select --"] + list(groups.keys()), key="sl_g_sel")
            if sl_g != "-- Select --" and st.button(f"Add Straightliner Check for {sl_g}"):
                st.session_state.straightliner_rules.append({'variables': groups[sl_g], 'group_name': sl_g})
                st.success(f"Added {sl_g}")

        with tab_final:
            if st.button("Generate Final SPSS Syntax"):
                master = ["* FINAL SYNTAX\n", "SET DECIMAL=DOT.\n"]
                for r in st.session_state.sq_rules: master.extend(generate_sq_spss_syntax(r))
                for r in st.session_state.mq_rules: master.extend(generate_mq_spss_syntax(r))
                for r in st.session_state.string_rules: master.extend(generate_string_spss_syntax(r))
                for r in st.session_state.straightliner_rules: master.extend(generate_straightliner_spss_syntax(r))
                
                final_text = "\n".join(master)
                st.code(final_text, language="spss")
                st.download_button("Download .sps", final_text, "SurveyValidation.sps")