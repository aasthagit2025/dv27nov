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

# --- CORE UTILITY FUNCTIONS (SYNTAX GENERATION) ---

def generate_skip_spss_syntax(target_col, trigger_col, trigger_val, rule_type, range_min=None, range_max=None):
    """
    Generates detailed SPSS syntax for Skip Logic (Error of Omission/Commission).
    FIXED: Uses target_col for final flag naming to support OE/Rating grids.
    """
    target_clean = target_col.split('_')[0] if '_' in target_col else target_col
    filter_flag = f"Flag_{target_clean}" 
    final_error_flag = f"{FLAG_PREFIX}{target_col}" # Corrected: Uses full col name
    
    syntax = []
    syntax.append(f"**************************************SKIP LOGIC FILTER FLAG: {trigger_col}={trigger_val} -> {target_clean}")
    syntax.append(f"IF({trigger_col} = {trigger_val}) {filter_flag}=1.")
    syntax.append(f"EXECUTE.\n") 
    
    if rule_type == 'SQ' and range_min is not None and range_max is not None:
        eoo_condition = f"(miss({target_col}) | ~range({target_col},{range_min},{range_max}))"
        eoc_condition = f"~miss({target_col})" 
    elif rule_type == 'String':
        # Specific condition for Open-Ended/Text fields
        eoo_condition = f"({target_col}='' | miss({target_col}))"
        eoc_condition = f"({target_col}<>'' & ~miss({target_col}))" 
    else:
        eoo_condition = f"miss({target_col})"
        eoc_condition = f"~miss({target_col})" 
        
    syntax.append(f"**************************************SKIP LOGIC EoO/EoC CHECK: {target_col} -> {final_error_flag}")
    syntax.append(f"* EoO (1): Trigger Met, Target Missing. IF({filter_flag}=1 & {eoo_condition}) {final_error_flag}=1.")
    syntax.append(f"IF({filter_flag} = 1 & {eoo_condition}) {final_error_flag}=1.")
    syntax.append(f"* EoC (2): Trigger Not Met, Target Answered. IF({filter_flag}<>1 & {eoc_condition}) {final_error_flag}=2.")
    syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & {eoc_condition}) {final_error_flag}=2.")
    syntax.append("EXECUTE.\n")
    
    return syntax, [filter_flag, final_error_flag]

def generate_other_specify_spss_syntax(main_col, other_col, other_stub_val):
    target_clean = main_col.split('_')[0] if '_' in main_col else main_col
    flag_name_fwd = f"{FLAG_PREFIX}{target_clean}_OtherFwd"
    flag_name_rev = f"{FLAG_PREFIX}{target_clean}_OtherRev"
    syntax = []
    syntax.append(f"**************************************OTHER SPECIFY Check: {main_col}")
    syntax.append(f"IF({main_col}={other_stub_val} & ({other_col}='' | miss({other_col}))) {flag_name_fwd}=1.")
    syntax.append(f"IF((~miss({other_col}) & {other_col}<>'') & {main_col}<>{other_stub_val}) {flag_name_rev}=1.")
    syntax.append(f"EXECUTE.\n")
    return syntax, [flag_name_fwd, flag_name_rev]

def generate_piping_spss_syntax(target_col, overall_skip_filter_flag, piping_source_col, piping_stub_val):
    flag_col = f"{FLAG_PREFIX}{target_col}" 
    syntax = []
    syntax.append(f"**************************************PIPING Check: {target_col}")
    syntax.append(f"IF(({overall_skip_filter_flag}=1) & ({piping_source_col}={piping_stub_val}) & {target_col}<>{piping_stub_val}) {flag_col}=1.")
    eoc_condition = f"({overall_skip_filter_flag}<>1 | miss({overall_skip_filter_flag}) | {piping_source_col}<>{piping_stub_val} | miss({piping_source_col})) & ~miss({target_col})"
    syntax.append(f"IF({eoc_condition}) {flag_col}=2.")
    syntax.append("EXECUTE.\n")
    return syntax, [flag_col]

def generate_straightliner_spss_syntax(cols):
    set_name = cols[0].split('_')[0] if cols else 'Rating_Set'
    flag_name = f"{FLAG_PREFIX}{set_name}_MaxStr"
    syntax = [f"**************************************STRAIGHTLINER: {set_name}",
              f"COMPUTE #Min_Val = MIN({' '.join(cols)}).",
              f"COMPUTE #Max_Val = MAX({' '.join(cols)}).",
              f"IF(#Min_Val = #Max_Val & ~miss({cols[0]})) {flag_name}=1.",
              f"EXECUTE.\nDELETE VARIABLES #Min_Val #Max_Val.\nEXECUTE.\n"]
    return syntax, [flag_name]

# --- RULE GENERATORS BY TYPE ---

def generate_sq_spss_syntax(rule):
    col = rule['variable']
    target_clean = col.split('_')[0] if '_' in col else col
    filter_flag = f"Flag_{target_clean}" 
    syntax, generated_flags = [], []

    if not rule['run_piping_check']:
        flag_rng = f"{FLAG_PREFIX}{col}_Rng"
        syntax.append(f"IF(miss({col}) | ~range({col},{rule['min_val']},{rule['max_val']})) {flag_rng}=1.")
        generated_flags.append(flag_rng)
    
    if rule.get('other_var') and rule['other_var'] != '-- Select Variable --':
        o_syn, o_flg = generate_other_specify_spss_syntax(col, rule['other_var'], rule['other_stub_val'])
        syntax.extend(o_syn); generated_flags.extend(o_flg)

    if (rule['run_skip'] or rule['run_piping_check']) and rule['trigger_col'] != '-- Select Variable --':
        syntax.append(f"IF({rule['trigger_col']} = {rule['trigger_val']}) {filter_flag}=1.\nEXECUTE.\n")
        generated_flags.append(filter_flag)
        if rule['run_piping_check']:
            p_syn, p_flg = generate_piping_spss_syntax(col, filter_flag, rule['piping_source_col'], rule['piping_stub_val'])
            syntax.extend(p_syn); generated_flags.extend(p_flg)
        elif rule['run_skip']:
            s_syn, s_flg = generate_skip_spss_syntax(col, rule['trigger_col'], rule['trigger_val'], 'SQ', rule['min_val'], rule['max_val'])
            syntax.extend(s_syn); generated_flags.extend(s_flg)
    return syntax, generated_flags

def generate_string_spss_syntax(rule):
    """Detailed SPSS syntax for OE (String) logic."""
    col = rule['variable']
    syntax, generated_flags = [], []

    if rule['min_length'] > 0:
        flag_junk = f"{FLAG_PREFIX}{col}_Junk"
        syntax.append(f"**************************************String Junk Check: {col}")
        syntax.append(f"IF(~miss({col}) & {col}<>'' & LENGTH(RTRIM({col})) < {rule['min_length']}) {flag_junk}=1.")
        generated_flags.append(flag_junk)
    
    if rule['run_skip'] and rule['trigger_col'] != '-- Select Variable --':
        s_syn, s_flg = generate_skip_spss_syntax(col, rule['trigger_col'], rule['trigger_val'], 'String')
        syntax.extend(s_syn); generated_flags.extend(s_flg)
    else:
        flag_miss = f"{FLAG_PREFIX}{col}_Miss"
        syntax.append(f"IF({col}='' | miss({col})) {flag_miss}=1.")
        generated_flags.append(flag_miss)
    
    return syntax, generated_flags

def generate_mq_spss_syntax(rule):
    cols = rule['variables']
    mq_set = cols[0].split('_')[0]
    mq_sum = f"{mq_set}_Count"
    syntax, generated_flags = [], [mq_sum]
    syntax.append(f"COMPUTE {mq_sum} = {rule['count_method']}({' '.join(cols)}).")
    
    flag_min = f"{FLAG_PREFIX}{mq_set}_Min"
    syntax.append(f"IF({mq_sum} < {rule['min_count']} & ~miss({cols[0]})) {flag_min}=1.")
    generated_flags.append(flag_min)
    
    if rule.get('run_skip') and rule['trigger_col'] != '-- Select Variable --':
        s_syn, s_flg = generate_skip_spss_syntax(mq_set, rule['trigger_col'], rule['trigger_val'], 'MQ')
        syntax.extend(s_syn); generated_flags.extend(s_flg)
    return syntax, generated_flags

# --- BATCH UI CONFIGURATIONS ---

def configure_sq_rules(all_variable_options):
    st.subheader("1. Single Select / Rating Rule (SQ) Configuration")
    sq_cols = st.multiselect("Select SQ Variables", st.session_state.all_cols, key='sq_ms')
    if st.button("Configure SQ Selection"): st.session_state.sq_batch_vars = sq_cols
    
    if st.session_state.get('sq_batch_vars'):
        with st.form("sq_form"):
            new_rules = []
            for i, col in enumerate(st.session_state.sq_batch_vars):
                st.markdown(f"#### ⚙️ {col}")
                c1, c2 = st.columns(2)
                min_v = c1.number_input("Min", 1, value=1, key=f"sq_min_{i}")
                max_v = c2.number_input("Max", 1, value=5, key=f"sq_max_{i}")
                
                c3, c4 = st.columns(2)
                trig_col = c3.selectbox("Filter Variable", all_variable_options, key=f"sq_trig_{i}")
                trig_val = c4.text_input("Filter Value", "1", key=f"sq_val_{i}")
                
                run_skip = st.checkbox("Enable Skip Logic (EoO/EoC)", key=f"sq_skip_{i}")
                new_rules.append({'variable': col, 'min_val': min_v, 'max_val': max_v, 'run_skip': run_skip, 'trigger_col': trig_col, 'trigger_val': trig_val, 'run_piping_check': False})
            
            if st.form_submit_button("Save SQ Rules"):
                st.session_state.sq_rules = [r for r in st.session_state.sq_rules if r['variable'] not in sq_cols] + new_rules
                st.session_state.sq_batch_vars = []
                st.rerun()

def configure_string_rules(all_variable_options):
    st.subheader("2. Open-Ended (OE) / String Rule Configuration")
    oe_cols = st.multiselect("Select OE/Text Variables", st.session_state.all_cols, key='oe_ms')
    if st.button("Configure OE Selection"): st.session_state.string_batch_vars = oe_cols
    
    if st.session_state.get('string_batch_vars'):
        with st.form("oe_form"):
            new_rules = []
            for i, col in enumerate(st.session_state.string_batch_vars):
                st.markdown(f"#### ⚙️ {col}")
                min_l = st.number_input("Min Length (Junk Check)", 0, value=5, key=f"oe_len_{i}")
                
                st.markdown("**Skip Logic (EoO/EoC)**")
                c1, c2 = st.columns(2)
                trig_col = c1.selectbox("Filter Variable", all_variable_options, key=f"oe_trig_{i}")
                trig_val = c2.text_input("Filter Value", "1", key=f"oe_val_{i}")
                run_skip = st.checkbox("Enable Skip Logic", key=f"oe_skip_{i}")
                
                new_rules.append({'variable': col, 'min_length': min_l, 'run_skip': run_skip, 'trigger_col': trig_col, 'trigger_val': trig_val})
            
            if st.form_submit_button("Save OE Rules"):
                st.session_state.string_rules = [r for r in st.session_state.string_rules if r['variable'] not in oe_cols] + new_rules
                st.session_state.string_batch_vars = []
                st.rerun()

# --- MASTER SYNTAX GENERATION ---

def generate_master_spss_syntax():
    all_syntax, all_flags = [], []
    for r in st.session_state.sq_rules:
        s, f = generate_sq_spss_syntax(r)
        all_syntax.append(s); all_flags.extend(f)
    for r in st.session_state.string_rules:
        s, f = generate_string_spss_syntax(r)
        all_syntax.append(s); all_flags.extend(f)
    for r in st.session_state.mq_rules:
        s, f = generate_mq_spss_syntax(r)
        all_syntax.append(s); all_flags.extend(f)
    for r in st.session_state.straightliner_rules:
        s, f = generate_straightliner_spss_syntax(r['variables'])
        all_syntax.append(s); all_flags.extend(f)

    unique_flags = sorted(list(set(all_flags)))
    sps = ["* PYTHON-GENERATED DATA VALIDATION SCRIPT *", "DATASET ACTIVATE ALL."]
    
    num_flags = [f for f in unique_flags if not f.endswith('_Count')]
    if num_flags:
        sps.append(f"NUMERIC {'; '.join(num_flags)}.\nRECODE {'; '.join(num_flags)} (ELSE=0).\nEXECUTE.")
    
    sps.append("\n".join([line for block in all_syntax for line in block]))
    
    for f in unique_flags:
        if f.startswith(FLAG_PREFIX) and not f.endswith('_Count'):
            if any(x in f for x in ['_Rng', '_Miss', '_Junk', '_Min', '_MaxStr']):
                sps.append(f"VALUE LABELS {f} 0 'Pass' 1 'Fail'.")
            else:
                sps.append(f"VALUE LABELS {f} 0 'Pass' 1 'EoO (Missing)' 2 'EoC (Should be skip)'.")
    
    return "\n".join(sps)

# --- MAIN APP ---

uploaded_file = st.file_uploader("Upload Data", type=['csv', 'xlsx', 'sav'])
if uploaded_file:
    df_raw = load_data_file(uploaded_file)
    st.session_state.all_cols = sorted(df_raw.columns.tolist())
    opts = ['-- Select Variable --'] + st.session_state.all_cols
    
    configure_sq_rules(opts)
    configure_string_rules(opts)
    
    if st.sidebar.button("Clear Rules"): 
        st.session_state.sq_rules = []; st.session_state.string_rules = []
        st.rerun()

    if st.session_state.sq_rules or st.session_state.string_rules:
        st.header("Step 3: Download Syntax")
        master_sps = generate_master_spss_syntax()
        st.download_button("Download .sps", master_sps, "validation.sps")
        st.code(master_sps[:1000] + "...", language='spss')