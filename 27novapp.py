import streamlit as st
import pandas as pd
import numpy as np
import io
import time 
import os 
import tempfile

# --- Configuration ---
FLAG_PREFIX = "xx" 
st.set_page_config(layout="wide", page_title="Survey Data Validation")
st.title("📊 Survey Data Validation Automation")
st.markdown("Generates **SPSS logic syntax** with automatic variable type detection and SPSS column ordering.")
st.markdown("---")

# 1. Initialize session state for all rule types and metadata
keys = [
    'sq_rules', 'mq_rules', 'ranking_rules', 'string_rules', 'straightliner_rules', 
    'all_cols', 'var_types', 'sq_batch_vars', 'mq_batch_vars', 'oe_batch_vars', 'rank_batch_vars'
]
for k in keys:
    if k not in st.session_state:
        st.session_state[k] = [] if k != 'var_types' else {}

# --- 2. DATA LOADING & TYPE DETECTION ---

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
        
        if df is not None:
            # PRESERVE ORDER: Use df.columns directly
            st.session_state.all_cols = list(df.columns)
            # AUTO-DETECT TYPES: Record if column is string or numeric
            st.session_state.var_types = {
                col: 'string' if pd.api.types.is_string_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]) else 'numeric'
                for col in df.columns
            }
            return df
    except Exception as e:
        st.error(f"Error loading file: {e}")
    return None

# --- 3. LOGIC HELPERS (Blank vs Missing) ---

def is_string(col):
    """Checks if a column is detected as a string variable."""
    return st.session_state.get('var_types', {}).get(col) == 'string'

def get_missing_logic(col):
    """Requirement: Use blank ('') for strings and miss() for numeric."""
    if is_string(col):
        return f"({col} = '' | miss({col}))"
    return f"miss({col})"

def get_answered_logic(col):
    """Requirement: Use <> '' for strings and ~miss() for numeric."""
    if is_string(col):
        return f"({col} <> '' & ~miss({col}))"
    return f"~miss({col})"

def get_comp_logic(col, val):
    """Wraps values in quotes if the trigger column is a string type."""
    formatted_val = f"'{val}'" if is_string(col) else val
    return f"{col} = {formatted_val}"

# --- 4. SYNTAX GENERATORS ---



def generate_skip_spss_syntax(target_col, trigger_col, trigger_val, rule_type, range_min=None, range_max=None):
    """Unified Skip Logic generator using type-sensitive logic."""
    target_clean = target_col.split('_')[0] if '_' in target_col else target_col
    filter_flag = f"Flag_{target_clean}" 
    final_error_flag = f"{FLAG_PREFIX}{target_clean}" 
    syntax = []
    
    syntax.append(f"* SKIP LOGIC: {trigger_col}={trigger_val} -> {target_clean}")
    syntax.append(f"IF({get_comp_logic(trigger_col, trigger_val)}) {filter_flag}=1.")
    
    # EoO (Error of Omission)
    eoo_condition = get_missing_logic(target_col)
    if not is_string(target_col) and range_min is not None:
        eoo_condition = f"({eoo_condition} | ~range({target_col},{range_min},{range_max}))"
    
    # EoC (Error of Commission)
    eoc_condition = get_answered_logic(target_col)
    
    syntax.append(f"IF({filter_flag} = 1 & {eoo_condition}) {final_error_flag}=1.")
    syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & {eoc_condition}) {final_error_flag}=2.")
    syntax.append("EXECUTE.\n")
    return syntax, [filter_flag, final_error_flag]

def generate_sq_spss_syntax(rule):
    col = rule['variable']
    syntax, flags = [], []
    
    # 1. Standard Missing/Range Check
    if not rule.get('run_piping_check', False):
        flag_name = f"{FLAG_PREFIX}{col}_Rng"
        miss_logic = get_missing_logic(col)
        syntax.append(f"* SQ Check: {col}")
        if not is_string(col):
            syntax.append(f"IF({miss_logic} | ~range({col},{rule['min_val']},{rule['max_val']})) {flag_name}=1.")
        else:
            syntax.append(f"IF({miss_logic}) {flag_name}=1.")
        flags.append(flag_name)

    # 2. Other Specify Check
    if rule.get('other_var') and rule['other_var'] != '-- Select Variable --':
        fwd, rev = f"{FLAG_PREFIX}{col}_OtherFwd", f"{FLAG_PREFIX}{col}_OtherRev"
        syntax.append(f"IF({col}={rule['other_stub_val']} & {get_missing_logic(rule['other_var'])}) {fwd}=1.")
        syntax.append(f"IF({get_answered_logic(rule['other_var'])} & {col}<>{rule['other_stub_val']}) {rev}=1.")
        flags.extend([fwd, rev])

    # 3. Skip Logic
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
    
    syntax.append(f"COMPUTE {count_var} = {rule['count_method']}({' '.join(cols)}).")
    syntax.append(f"IF({count_var} < {rule['min_count']} & {get_answered_logic(cols[0])}) {FLAG_PREFIX}{mq_set}_Min=1.")
    if rule['max_count']:
        syntax.append(f"IF({count_var} > {rule['max_count']}) {FLAG_PREFIX}{mq_set}_Max=1.")
    
    if rule.get('exclusive_col') != 'None':
        other_cols = [c for c in cols if c != rule['exclusive_col']]
        syntax.append(f"IF({rule['exclusive_col']}=1 & SUM({' '.join(other_cols)}) > 0) {FLAG_PREFIX}{mq_set}_Excl=1.")
    
    syntax.append("EXECUTE.\n")
    return syntax, flags

def generate_string_spss_syntax(rule):
    col = rule['variable']
    syntax, flags = [], []
    flag_name = f"{FLAG_PREFIX}{col}_Str"
    
    syntax.append(f"* OE/String Check: {col}")
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
    syntax = [f"* Ranking Check: {base}"]
    flags = []
    
    for c in cols:
        f = f"{FLAG_PREFIX}{c}_Rng"
        syntax.append(f"IF({get_missing_logic(c)} | ~range({c},{rule['min_val']},{rule['max_val']})) {f}=1.")
        flags.append(f)
        
    syntax.append(f"IF(nvalid({' '.join(cols)}) <> {len(cols)}) {FLAG_PREFIX}{base}_Unq=1.")
    flags.append(f"{FLAG_PREFIX}{base}_Unq")
    syntax.append("EXECUTE.\n")
    return syntax, flags

def generate_straightliner_spss_syntax(cols):
    set_name = cols[0].split('_')[0]
    flag = f"{FLAG_PREFIX}{set_name}_StrLine"
    syntax = [
        f"COMPUTE #Min_V = MIN({' '.join(cols)}).",
        f"COMPUTE #Max_V = MAX({' '.join(cols)}).",
        f"IF(#Min_V = #Max_V & {get_answered_logic(cols[0])}) {flag}=1.",
        "DELETE VARIABLES #Min_V #Max_V.",
        "EXECUTE.\n"
    ]
    return syntax, [flag]

# --- 5. STREAMLIT UI ---

uploaded_file = st.sidebar.file_uploader("Step 1: Upload Data", type=['sav', 'xlsx', 'csv'])

if uploaded_file:
    df = load_data_file(uploaded_file)
    if df is not None:
        all_options = ["-- Select Variable --"] + st.session_state.all_cols
        
        tabs = st.tabs(["Single Select", "Multi-Select", "Ranking", "OE / Strings", "Straightlining", "Finalize"])
        
        # --- TAB: SQ ---
        with tabs[0]:
            st.subheader("SQ Rules")
            batch = st.multiselect("Batch Select SQ Variables", st.session_state.all_cols, key="sq_m")
            if st.button("Configure Selected SQ"): st.session_state.sq_batch_vars = batch
            
            if st.session_state.sq_batch_vars:
                with st.form("sq_form"):
                    for c in st.session_state.sq_batch_vars:
                        st.write(f"**Settings for {c}**")
                        col1, col2 = st.columns(2)
                        with col1:
                            min_v = st.number_input(f"Min Val for {c}", value=1, key=f"min_{c}")
                            max_v = st.number_input(f"Max Val for {c}", value=5, key=f"max_{c}")
                        with col2:
                            trig = st.selectbox(f"Trigger for {c}", all_options, key=f"trig_{c}")
                            trig_v = st.text_input(f"Trigger Value for {c}", "1", key=f"trigv_{c}")
                        
                        # Store in rule dict (Summary)
                        if st.form_submit_button("Save SQ Rules"):
                            st.session_state.sq_rules.append({
                                'variable': c, 'min_val': min_v, 'max_val': max_v,
                                'run_skip': trig != "-- Select Variable --",
                                'trigger_col': trig, 'trigger_val': trig_v
                            })
                            st.success("Rules Saved!")

        # --- TAB: MQ ---
        with tabs[1]:
            st.subheader("MQ Rules")
            mq_vars = st.multiselect("Select MQ Columns", st.session_state.all_cols, key="mq_m")
            if st.button("Add MQ Rule"):
                st.session_state.mq_rules.append({
                    'variables': mq_vars, 'min_count': 1, 'max_count': None, 
                    'count_method': 'SUM', 'exclusive_col': 'None'
                })
            st.write(st.session_state.mq_rules)

        # --- TAB: Ranking ---
        with tabs[2]:
            st.subheader("Ranking Rules")
            rank_vars = st.multiselect("Select Ranking Set", st.session_state.all_cols, key="rk_m")
            if st.button("Add Ranking Rule"):
                st.session_state.ranking_rules.append({
                    'variables': rank_vars, 'min_val': 1, 'max_val': len(rank_vars)
                })

        # --- TAB: OE / Strings ---
        with tabs[3]:
            st.subheader("Open-Ended / String Rules")
            oe_batch = st.multiselect("Select String Variables", st.session_state.all_cols, key="oe_m")
            if st.button("Configure OE"): st.session_state.oe_batch_vars = oe_batch
            
            if st.session_state.oe_batch_vars:
                with st.form("oe_form"):
                    for c in st.session_state.oe_batch_vars:
                        trig = st.selectbox(f"Trigger for {c}", all_options, key=f"oet_{c}")
                        trig_v = st.text_input(f"Trigger Value for {c}", "1", key=f"oetv_{c}")
                    if st.form_submit_button("Save OE Rules"):
                        for c in st.session_state.oe_batch_vars:
                            st.session_state.string_rules.append({
                                'variable': c, 'run_skip': trig != "-- Select Variable --",
                                'trigger_col': trig, 'trigger_val': trig_v
                            })

        # --- TAB: Straightlining ---
        with tabs[4]:
            st.subheader("Straightlining Rules")
            sl_vars = st.multiselect("Select Grid Variables", st.session_state.all_cols, key="sl_m")
            if st.button("Add SL Rule"):
                st.session_state.straightliner_rules.append({'variables': sl_vars})

        # --- TAB: Finalize ---
        with tabs[5]:
            if st.button("Generate Final SPSS Syntax"):
                master = ["* GENERATED SPSS VALIDATION SYNTAX.\n", "SET DECIMAL=DOT.\n"]
                all_flags = []
                
                for r in st.session_state.sq_rules:
                    s, f = generate_sq_spss_syntax(r); master.extend(s); all_flags.extend(f)
                for r in st.session_state.mq_rules:
                    s, f = generate_mq_spss_syntax(r); master.extend(s); all_flags.extend(f)
                for r in st.session_state.ranking_rules:
                    s, f = generate_ranking_spss_syntax(r); master.extend(s); all_flags.extend(f)
                for r in st.session_state.string_rules:
                    s, f = generate_string_spss_syntax(r); master.extend(s); all_flags.extend(f)
                for r in st.session_state.straightliner_rules:
                    s, f = generate_straightliner_spss_syntax(r['variables']); master.extend(s); all_flags.extend(f)
                
                final_syntax = "\n".join(master)
                st.code(final_syntax, language="spss")
                
                # Download
                st.download_button("Download .sps File", final_syntax, "Validation_Logic.sps")