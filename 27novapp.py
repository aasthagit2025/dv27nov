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
st.markdown("Generates **SPSS logic syntax** with automatic variable type detection and SPSS column ordering.")
st.markdown("---")

# 1. Initialize session state for all rule types and metadata
# This ensures all your original batch selection features work.
keys = [
    'sq_rules', 'mq_rules', 'ranking_rules', 'string_rules', 'straightliner_rules', 
    'all_cols', 'var_types', 'sq_batch_vars', 'mq_batch_vars', 'oe_batch_vars', 'rank_batch_vars'
]
for k in keys:
    if k not in st.session_state:
        st.session_state[k] = [] if k != 'var_types' else {}

# --- 2. DATA LOADING (FIXED SYNTAX ERROR) ---

def load_data_file(uploaded_file):
    """Reads data and automatically detects variable types and preserves SPSS order."""
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    na_values = ['', ' ', '#N/A', 'N/A', 'NA', '#NA', 'NULL', 'null']
    df = None
    
    try:
        if file_extension == '.csv':
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, encoding='utf-8', na_values=na_values)
        elif file_extension in ['.xlsx', '.xls']:
            df = pd.read_excel(uploaded_file)
        elif file_extension in ['.sav', '.zsav']:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                tmp_file.write(uploaded_file.getbuffer())
                tmp_path = tmp_file.name
            df = pd.read_spss(tmp_path, convert_categoricals=False)
            os.remove(tmp_path)
            
    except Exception as e:
        st.error(f"Error loading file: {e}")
        return None

    # This is where your error was: now outside the try/except block correctly
    if df is not None:
        # Preserve Order
        st.session_state.all_cols = list(df.columns)
        # Auto-Detect Types
        st.session_state.var_types = {
            col: 'string' if pd.api.types.is_string_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]) else 'numeric'
            for col in df.columns
        }
    return df

# --- 3. LOGIC HELPERS (Blank vs Missing) ---

def is_string(col):
    return st.session_state.get('var_types', {}).get(col) == 'string'

def get_missing_logic(col):
    """String = Blank check; Numeric = miss() check."""
    if is_string(col):
        return f"({col} = '' | miss({col}))"
    return f"miss({col})"

def get_answered_logic(col):
    if is_string(col):
        return f"({col} <> '' & ~miss({col}))"
    return f"~miss({col})"

def get_comp_logic(col, val):
    formatted_val = f"'{val}'" if is_string(col) else val
    return f"{col} = {formatted_val}"

# --- 4. SYNTAX GENERATORS (All rule types restored) ---

def generate_skip_spss_syntax(target_col, trigger_col, trigger_val, rule_type, range_min=None, range_max=None):
    target_clean = target_col.split('_')[0] if '_' in target_col else target_col
    filter_flag = f"Flag_{target_clean}" 
    final_error_flag = f"{FLAG_PREFIX}{target_clean}" 
    syntax = []
    
    syntax.append(f"* SKIP LOGIC: {trigger_col}={trigger_val} -> {target_clean}")
    syntax.append(f"IF({get_comp_logic(trigger_col, trigger_val)}) {filter_flag}=1.")
    
    eoo_condition = get_missing_logic(target_col)
    if not is_string(target_col) and range_min is not None:
        eoo_condition = f"({eoo_condition} | ~range({target_col},{range_min},{range_max}))"
    
    eoc_condition = get_answered_logic(target_col)
    
    syntax.append(f"IF({filter_flag} = 1 & {eoo_condition}) {final_error_flag}=1.")
    syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & {eoc_condition}) {final_error_flag}=2.")
    syntax.append("EXECUTE.\n")
    return syntax, [filter_flag, final_error_flag]

def generate_sq_spss_syntax(rule):
    col = rule['variable']
    syntax, flags = [], []
    flag_name = f"{FLAG_PREFIX}{col}_Rng"
    
    syntax.append(f"* SQ Check: {col}")
    if not is_string(col):
        syntax.append(f"IF({get_missing_logic(col)} | ~range({col},{rule['min_val']},{rule['max_val']})) {flag_name}=1.")
    else:
        syntax.append(f"IF({get_missing_logic(col)}) {flag_name}=1.")
    flags.append(flag_name)

    if rule.get('run_skip') and rule['trigger_col'] != '-- Select Variable --':
        s, f = generate_skip_spss_syntax(col, rule['trigger_col'], rule['trigger_val'], 'SQ', rule['min_val'], rule['max_val'])
        syntax.extend(s); flags.extend(f)

    syntax.append("EXECUTE.\n")
    return syntax, flags

def generate_mq_spss_syntax(rule):
    cols = rule['variables']
    mq_set = cols[0].split('_')[0]
    count_var = f"{mq_set}_Count"
    syntax, flags = [], [count_var]
    syntax.append(f"COMPUTE {count_var} = SUM({', '.join(cols)}).")
    syntax.append(f"IF({count_var} < {rule['min_count']} & {get_answered_logic(cols[0])}) {FLAG_PREFIX}{mq_set}_Min=1.")
    if rule['max_count']:
        syntax.append(f"IF({count_var} > {rule['max_count']}) {FLAG_PREFIX}{mq_set}_Max=1.")
    syntax.append("EXECUTE.\n")
    return syntax, flags

def generate_string_spss_syntax(rule):
    col = rule['variable']
    syntax, flags = [], []
    flag_name = f"{FLAG_PREFIX}{col}_Str"
    syntax.append(f"* OE/String: {col}")
    syntax.append(f"IF({get_missing_logic(col)}) {flag_name}=1.")
    flags.append(flag_name)
    if rule.get('run_skip') and rule['trigger_col'] != '-- Select Variable --':
        s, f = generate_skip_spss_syntax(col, rule['trigger_col'], rule['trigger_val'], 'String')
        syntax.extend(s); flags.extend(f)
    syntax.append("EXECUTE.\n")
    return syntax, flags

def generate_ranking_spss_syntax(rule):
    cols = rule['variables']
    base = cols[0].split('_')[0]
    syntax, flags = [f"* Ranking Check: {base}"], []
    for c in cols:
        f = f"{FLAG_PREFIX}{c}_Rng"
        syntax.append(f"IF({get_missing_logic(c)} | ~range({c},{rule['min_val']},{rule['max_val']})) {f}=1.")
        flags.append(f)
    syntax.append(f"IF(nvalid({', '.join(cols)}) <> {len(cols)}) {FLAG_PREFIX}{base}_Unq=1.")
    flags.append(f"{FLAG_PREFIX}{base}_Unq")
    syntax.append("EXECUTE.\n")
    return syntax, flags

def generate_straightliner_spss_syntax(cols):
    set_name = cols[0].split('_')[0]
    flag = f"{FLAG_PREFIX}{set_name}_StrLine"
    syntax = [
        f"COMPUTE #Min_V = MIN({', '.join(cols)}).",
        f"COMPUTE #Max_V = MAX({', '.join(cols)}).",
        f"IF(#Min_V = #Max_V & {get_answered_logic(cols[0])}) {flag}=1.",
        "DELETE VARIABLES #Min_V #Max_V.",
        "EXECUTE.\n"
    ]
    return syntax, [flag]

# --- 5. UI (YOUR ORIGINAL TABS & BATCH FLOW) ---

uploaded_file = st.sidebar.file_uploader("Step 1: Upload Data", type=['sav', 'xlsx', 'csv'])

if uploaded_file:
    df = load_data_file(uploaded_file)
    if df is not None:
        all_options = ["-- Select Variable --"] + st.session_state.all_cols
        
        tabs = st.tabs(["Single Select (SQ)", "Multi-Select (MQ)", "OE / Strings", "Ranking / SL", "Finalize"])
        
        with tabs[0]:
            st.subheader("SQ Configuration")
            sq_batch = st.multiselect("Batch Select SQ Variables", st.session_state.all_cols, key='sq_sel')
            if st.button("Configure Selected SQ"): st.session_state.sq_batch_vars = sq_batch
            
            if st.session_state.sq_batch_vars:
                with st.form("sq_form"):
                    for c in st.session_state.sq_batch_vars:
                        st.write(f"**Settings for {c}** ({st.session_state.var_types[c]})")
                        c1, c2, c3 = st.columns(3)
                        with c1: min_v = st.number_input(f"Min Valid {c}", 1, key=f"min_{c}")
                        with c2: max_v = st.number_input(f"Max Valid {c}", 5, key=f"max_{c}")
                        with c3: trig = st.selectbox(f"Trigger {c}", all_options, key=f"tr_{c}")
                        trig_v = st.text_input(f"Trigger Value {c}", "1", key=f"trv_{c}")
                        
                        if st.form_submit_button(f"Save {c} Rule"):
                            st.session_state.sq_rules.append({
                                'variable': c, 'min_val': min_v, 'max_val': max_v,
                                'run_skip': trig != "-- Select Variable --",
                                'trigger_col': trig, 'trigger_val': trig_v
                            })
                            st.toast(f"Saved {c}!")

        with tabs[1]:
            st.subheader("MQ Configuration")
            mq_vars = st.multiselect("Select MQ Columns", st.session_state.all_cols, key="mq_sel")
            if st.button("Add MQ Rule"):
                st.session_state.mq_rules.append({'variables': mq_vars, 'min_count': 1, 'max_count': None})
                st.success("MQ Rule Added")

        with tabs[2]:
            st.subheader("OE / String Configuration")
            oe_batch = st.multiselect("Select String Variables", st.session_state.all_cols, key='oe_sel')
            if st.button("Configure OE Batch"): st.session_state.oe_batch_vars = oe_batch
            
            if st.session_state.oe_batch_vars:
                with st.form("oe_form"):
                    for c in st.session_state.oe_batch_vars:
                        st.write(f"**OE Check for {c}**")
                        trig = st.selectbox(f"Trigger for {c}", all_options, key=f"oet_{c}")
                        trig_v = st.text_input(f"Trigger Value {c}", "1", key=f"oetv_{c}")
                        if st.form_submit_button(f"Save {c} OE"):
                            st.session_state.string_rules.append({
                                'variable': c, 'run_skip': trig != "-- Select Variable --",
                                'trigger_col': trig, 'trigger_val': trig_v
                            })
                            st.toast(f"Saved {c}!")

        with tabs[3]:
            st.subheader("Ranking & Straightlining")
            sl_vars = st.multiselect("Select Grid Variables for SL", st.session_state.all_cols, key="sl_sel")
            if st.button("Add Straightlining Rule"):
                st.session_state.straightliner_rules.append({'variables': sl_vars})
                st.success("SL Rule Added")

        with tabs[4]:
            st.subheader("Generate & Download")
            if st.button("Generate Final SPSS Syntax"):
                master = ["* GENERATED SPSS SYNTAX\n", "SET DECIMAL=DOT.\n"]
                for r in st.session_state.sq_rules:
                    s, _ = generate_sq_spss_syntax(r); master.extend(s)
                for r in st.session_state.mq_rules:
                    s, _ = generate_mq_spss_syntax(r); master.extend(s)
                for r in st.session_state.string_rules:
                    s, _ = generate_string_spss_syntax(r); master.extend(s)
                for r in st.session_state.straightliner_rules:
                    s, _ = generate_straightliner_spss_syntax(r['variables']); master.extend(s)
                
                final_syntax = "\n".join(master)
                st.code(final_syntax, language="spss")
                st.download_button("Download .sps File", final_syntax, "Validation_Logic.sps")