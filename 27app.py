import streamlit as st
import pandas as pd
import numpy as np
import io
import os 
import tempfile
import re

# --- 1. CONFIG & SYSTEM FILTER ---
FLAG_PREFIX = "xx" 
# Variables that should never show up in any dropdown
SYSTEM_VARS = ['sys_respnum', 'status', 'duration', 'starttime', 'endtime', 'uuid', 'recordid', 'respid', 'index', 'id']

st.set_page_config(layout="wide", page_title="Survey Data Validation")
st.title("📊 Survey Data Validation Automation")
st.markdown("---")

# 2. INITIALIZE SESSION STATE
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
            # Filter system vars
            valid_cols = [c for c in df.columns if c.lower() not in SYSTEM_VARS]
            st.session_state.all_cols = valid_cols
            
            # Detect String vs Numeric
            st.session_state.var_types = {
                col: 'String' if df[col].dtype == 'object' or pd.api.types.is_string_dtype(df[col]) else 'Numeric'
                for col in valid_cols
            }
            return df
    except Exception as e:
        st.error(f"Error loading file: {e}")
    return None

def get_variable_groups():
    """
    Automatically detects groups based on underscores or common prefixes.
    Handles patterns like Q1_1, Q1_r1, A4_1, etc.
    """
    groups = {}
    for col in st.session_state.all_cols:
        # Match common patterns: prefix followed by _ or _r or _c
        match = re.match(r'^([a-zA-Z0-9]+)(_r|_c|_)?', col)
        if match:
            base = match.group(1)
            # Only group if there is actually a separator like Q1_1
            if "_" in col:
                if base not in groups: groups[base] = []
                groups[base].append(col)
    
    # Only return groups that have more than one variable
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
        
    if rule.get('trigger_col') and rule['trigger_col'] != "-- Select Variable --":
        t_col, t_val = rule['trigger_col'], rule['trigger_val']
        t_logic = f"{t_col} = '{t_val}'" if is_string(t_col) else f"{t_col} = {t_val}"
        syntax.append(f"IF({t_logic} & {get_missing_logic(col)}) {FLAG_PREFIX}{col}_Skip=1.")
    
    syntax.append("EXECUTE.\n")
    return syntax

def generate_mq_spss_syntax(rule):
    v_list = " ".join(rule['variables'])
    base = rule['group_name']
    syntax = [f"* MQ Check for {base}", f"COMPUTE {base}_Sum = SUM({v_list})."]
    syntax.append(f"IF({base}_Sum < {rule['min_count']} & {get_answered_logic(rule['variables'][0])}) {FLAG_PREFIX}{base}_Min=1.")
    syntax.append("EXECUTE.\n")
    return syntax

def generate_string_spss_syntax(rule):
    col = rule['variable']
    syntax = [f"* OE Check: {col}", f"IF({get_missing_logic(col)}) {FLAG_PREFIX}{col}_Str=1."]
    if rule.get('trigger_col') and rule['trigger_col'] != "-- Select Variable --":
        t_col, t_val = rule['trigger_col'], rule['trigger_val']
        t_logic = f"{t_col} = '{t_val}'" if is_string(t_col) else f"{t_col} = {t_val}"
        syntax.append(f"IF({t_logic} & {get_missing_logic(col)}) {FLAG_PREFIX}{col}_Skip=1.")
    syntax.append("EXECUTE.\n")
    return syntax

def generate_straightliner_spss_syntax(rule):
    v_list = " ".join(rule['variables'])
    syntax = [f"* Straightliner: {rule['group_name']}",
              f"IF(MIN({v_list}) = MAX({v_list}) & {get_answered_logic(rule['variables'][0])}) {FLAG_PREFIX}{rule['group_name']}_Str=1.",
              "EXECUTE.\n"]
    return syntax

# --- 6. UI TABS ---

uploaded_file = st.sidebar.file_uploader("Step 1: Upload Data", type=['sav', 'csv', 'xlsx'])

if uploaded_file:
    df = load_data_file(uploaded_file)
    if df is not None:
        all_options = ["-- Select Variable --"] + st.session_state.all_cols
        groups = get_variable_groups()
        
        tab_sq, tab_mq, tab_oe, tab_sl, tab_final = st.tabs(["Single Select", "Multi-Select (MQ)", "Open Ends", "Rating Grids", "Finalize"])
        
        with tab_sq:
            st.subheader("1. Single Select Settings")
            num_vars = [c for c in st.session_state.all_cols if not is_string(c)]
            sq_batch = st.multiselect("Batch Select SQ Variables", num_vars)
            if st.button("Configure SQ"): st.session_state.sq_batch_vars = sq_batch
            
            if st.session_state.sq_batch_vars:
                with st.form("sq_f"):
                    for c in st.session_state.sq_batch_vars:
                        c1, c2, c3 = st.columns(3)
                        min_v = c1.number_input(f"Min {c}", 1, key=f"min_{c}")
                        max_v = c2.number_input(f"Max {c}", 5, key=f"max_{c}")
                        trig = c3.selectbox(f"Trigger {c}", all_options, key=f"tr_{c}")
                        trig_v = st.text_input(f"Trig Value {c}", "1", key=f"tv_{c}")
                        if st.form_submit_button(f"Save {c}"):
                            st.session_state.sq_rules.append({'variable':c, 'min_val':min_v, 'max_val':max_v, 'trigger_col':trig, 'trigger_val':trig_v})

        with tab_mq:
            st.subheader("2. Multi-Select (Group Selection)")
            st.info("Choose a group prefix (like Q1 or A4) to select all related variables automatically.")
            
            sel_group = st.selectbox("Detected Groups", ["-- Select a Group --"] + list(groups.keys()), key="mq_group_sel")
            
            # Logic: If they select a group, default the multiselect to those variables
            default_mq = groups.get(sel_group, [])
            mq_vars = st.multiselect("Review/Edit Selected Variables", st.session_state.all_cols, default=default_mq)
            
            if mq_vars:
                min_c = st.number_input("Minimum selections required", 1, key="mq_min_val")
                if st.button("Add MQ Rule"):
                    g_name = sel_group if sel_group != "-- Select a Group --" else mq_vars[0]
                    st.session_state.mq_rules.append({'variables': mq_vars, 'min_count': min_c, 'group_name': g_name})
                    st.success(f"Added MQ rule for {g_name}")

        with tab_oe:
            st.subheader("3. Open Ends / Strings")
            str_vars = [c for c in st.session_state.all_cols if is_string(c)]
            oe_batch = st.multiselect("Select OE Variables", str_vars)
            if st.button("Configure OE Batch"): st.session_state.oe_batch_vars = oe_batch
            
            if st.session_state.oe_batch_vars:
                with st.form("oe_f"):
                    for c in st.session_state.oe_batch_vars:
                        trig = st.selectbox(f"Trigger {c}", all_options, key=f"oet_{c}")
                        trig_v = st.text_input(f"Value {c}", "1", key=f"oev_{c}")
                        if st.form_submit_button(f"Save {c} OE"):
                            st.session_state.string_rules.append({'variable':c, 'trigger_col':trig, 'trigger_val':trig_v})

        with tab_sl:
            st.subheader("4. Rating Grids (Straightlining)")
            st.info("Flags cases where respondents gave the same answer across a grid group.")
            sl_group = st.selectbox("Select Grid Group", ["-- Select --"] + list(groups.keys()), key="sl_group_sel")
            
            if sl_group != "-- Select --":
                st.write(f"Variables: {', '.join(groups[sl_group])}")
                if st.button(f"Add Straightliner Check for {sl_group}"):
                    st.session_state.straightliner_rules.append({'variables': groups[sl_group], 'group_name': sl_group})
                    st.success(f"Added straightlining check for {sl_group}")

        with tab_final:
            if st.button("Generate Final SPSS Syntax"):
                master = ["* GENERATED VALIDATION SYNTAX\n", "SET DECIMAL=DOT.\n"]
                for r in st.session_state.sq_rules: master.extend(generate_sq_spss_syntax(r))
                for r in st.session_state.mq_rules: master.extend(generate_mq_spss_syntax(r))
                for r in st.session_state.string_rules: master.extend(generate_string_spss_syntax(r))
                for r in st.session_state.straightliner_rules: master.extend(generate_straightliner_spss_syntax(r))
                
                final_syntax = "\n".join(master)
                st.code(final_syntax, language="spss")
                st.download_button("Download .sps File", final_syntax, "Validation_Logic.sps")