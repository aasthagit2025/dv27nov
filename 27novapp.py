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

# Initialize state for storing final, configured rules
for key in ['sq_rules', 'mq_rules', 'ranking_rules', 'string_rules', 'straightliner_rules', 'all_cols', 'sq_batch_vars', 'oe_batch_vars']:
    if key not in st.session_state:
        st.session_state[key] = []

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
            raise Exception(f"Failed to read SPSS file: {e}")
    return None

# --- CORE SYNTAX GENERATORS (ORIGINAL LOGIC) ---

def generate_skip_spss_syntax(target_col, trigger_col, trigger_val, rule_type, range_min=None, range_max=None):
    """Generates detailed SPSS syntax for Skip Logic (Error of Omission/Commission)."""
    target_clean = target_col.split('_')[0] if '_' in target_col else target_col
    filter_flag, final_error_flag = f"Flag_{target_clean}", f"{FLAG_PREFIX}{target_clean}" 
    
    syntax = [f"**************************************SKIP LOGIC FILTER: {trigger_col}={trigger_val}",
              f"IF({trigger_col} = {trigger_val}) {filter_flag}=1.", "EXECUTE.\n"]
    
    if rule_type == 'SQ' and range_min is not None:
        eoo, eoc = f"(miss({target_col}) | ~range({target_col},{range_min},{range_max}))", f"~miss({target_col})"
    elif rule_type == 'String':
        eoo, eoc = f"({target_col}='' | miss({target_col}))", f"({target_col}<>'' & ~miss({target_col}))"
    else:
        eoo, eoc = f"miss({target_col})", f"~miss({target_col})"
        
    syntax.extend([f"IF({filter_flag} = 1 & {eoo}) {final_error_flag}=1.",
                   f"IF(({filter_flag} <> 1 | miss({filter_flag})) & {eoc}) {final_error_flag}=2.", "EXECUTE.\n"])
    return syntax, [filter_flag, final_error_flag]

def generate_other_specify_spss_syntax(main_col, other_col, other_stub_val):
    """Generates syntax for Other-Specify checks."""
    main_clean = main_col.split('_')[0] if '_' in main_col else main_col
    fwd, rev = f"{FLAG_PREFIX}{main_clean}_OtherFwd", f"{FLAG_PREFIX}{main_clean}_OtherRev"
    return [f"IF({main_col}={other_stub_val} & ({other_col}='' | miss({other_col}))) {fwd}=1.",
            f"IF(~miss({other_col}) & {other_col}<>'' & {main_col}<>{other_stub_val}) {rev}=1.", "EXECUTE.\n"], [fwd, rev]

def generate_piping_spss_syntax(target_col, filter_flag, source_col, stub_val):
    """Generates syntax for Rating Piping checks."""
    flag = f"{FLAG_PREFIX}{target_col}"
    eoc_cond = f"({filter_flag}<>1 | miss({filter_flag}) | {source_col}<>{stub_val} | miss({source_col})) & ~miss({target_col})"
    return [f"IF(({filter_flag}=1) & ({source_col}={stub_val}) & {target_col}<>{stub_val}) {flag}=1.",
            f"IF({eoc_cond}) {flag}=2.", "EXECUTE.\n"], [flag]

def generate_sq_spss_syntax(rule):
    """Consolidated SQ syntax generator handling Range, Other, Skip, and Piping."""
    col = rule['variable']
    syntax, flags = [], []
    if not rule['run_piping_check']:
        f_rng = f"{FLAG_PREFIX}{col}_Rng"
        syntax.append(f"IF(miss({col}) | ~range({col},{rule['min_val']},{rule['max_val']})) {f_rng}=1.")
        flags.append(f_rng)
    if rule.get('other_var') and rule['other_var'] != '-- Select Variable --':
        s, f = generate_other_specify_spss_syntax(col, rule['other_var'], rule['other_stub_val'])
        syntax.extend(s); flags.extend(f)
    if (rule['run_skip'] or rule['run_piping_check']) and rule['trigger_col'] != '-- Select Variable --':
        target_clean = col.split('_')[0] if '_' in col else col
        filter_flag = f"Flag_{target_clean}"
        syntax.append(f"IF({rule['trigger_col']} = {rule['trigger_val']}) {filter_flag}=1.")
        flags.append(filter_flag)
        if rule['run_piping_check']:
            s, f = generate_piping_spss_syntax(col, filter_flag, rule['piping_source_col'], rule['piping_stub_val'])
            syntax.extend(s); flags.extend(f)
        else:
            s, f = generate_skip_spss_syntax(col, rule['trigger_col'], rule['trigger_val'], 'SQ', rule['min_val'], rule['max_val'])
            syntax.extend(s); flags.extend(f)
    return syntax, flags

def generate_mq_spss_syntax(rule):
    """Generates detailed SPSS syntax for a Multi-Select check."""
    cols = rule['variables']
    mq_set = cols[0].split('_')[0] if cols else 'MQ'
    mq_sum = f"{mq_set}_Count"
    syntax = [f"COMPUTE {mq_sum} = SUM({' '.join(cols)}).", f"IF({mq_sum} < {rule['min_count']}) {FLAG_PREFIX}{mq_set}_Min=1."]
    flags = [mq_sum, f"{FLAG_PREFIX}{mq_set}_Min"]
    if rule['run_skip']:
        s, f = generate_skip_spss_syntax(mq_set, rule['trigger_col'], rule['trigger_val'], 'MQ')
        syntax.extend(s); flags.extend(f)
    return syntax, flags

def generate_string_spss_syntax(rule):
    """UPDATED: OE syntax with length check and Skip logic."""
    col = rule['variable']
    f_junk = f"{FLAG_PREFIX}{col}_Junk"
    syntax = [f"IF(~miss({col}) & {col}<>'' & LENGTH(RTRIM({col})) < {rule['min_len']}) {f_junk}=1."]
    flags = [f_junk]
    if rule.get('run_skip') and rule['trigger_col'] != '-- Select Variable --':
        s, f = generate_skip_spss_syntax(col, rule['trigger_col'], rule['trigger_val'], 'String')
        syntax.extend(s); flags.extend(f)
    return syntax, flags

# --- UI LOGIC ---

uploaded_file = st.file_uploader("Upload Data", type=['csv', 'xlsx', 'sav'])
if uploaded_file:
    df = load_data_file(uploaded_file)
    st.session_state.all_cols = list(df.columns)
    all_opts = ['-- Select Variable --'] + st.session_state.all_cols

    # 1. SQ Section
    st.subheader("1. Single Select / Rating (SQ)")
    sq_sel = st.multiselect("Select SQ Variables", st.session_state.all_cols)
    if st.button("Configure SQ"): st.session_state.sq_batch_vars = sq_sel
    if st.session_state.sq_batch_vars:
        with st.form("sq_form"):
            for i, col in enumerate(st.session_state.sq_batch_vars):
                st.markdown(f"**{col}**")
                c1, c2, c3, c4 = st.columns(4)
                mi = c1.number_input("Min", 1, value=1, key=f"sq_mi_{i}")
                ma = c2.number_input("Max", 1, value=5, key=f"sq_ma_{i}")
                tc = c3.selectbox("Filter Var", all_opts, key=f"sq_tc_{i}")
                tv = c4.text_input("Val", "1", key=f"sq_tv_{i}")
                st.session_state.sq_rules.append({'variable': col, 'min_val': mi, 'max_val': ma, 'trigger_col': tc, 'trigger_val': tv, 'run_skip': True, 'run_piping_check': False, 'required_stubs': []})
            if st.form_submit_button("Save SQ"): st.rerun()

    # 3. OE Section
    st.subheader("3. Open-Ended (OE)")
    oe_sel = st.multiselect("Select OE Variables", st.session_state.all_cols)
    if st.button("Configure OE"): st.session_state.oe_batch_vars = oe_sel
    if st.session_state.oe_batch_vars:
        with st.form("oe_form"):
            for i, col in enumerate(st.session_state.oe_batch_vars):
                c1, c2, c3 = st.columns(3)
                ml = c1.number_input("Min Len", 0, value=5, key=f"oe_l_{i}")
                tc = c2.selectbox("Filter Var", all_opts, key=f"oe_tc_{i}")
                tv = c3.text_input("Val", "1", key=f"oe_tv_{i}")
                st.session_state.string_rules.append({'variable': col, 'min_len': ml, 'trigger_col': tc, 'trigger_val': tv, 'run_skip': True})
            if st.form_submit_button("Save OE"): st.rerun()

    # --- MASTER SYNTAX GENERATION ---
    if st.button("🚀 GENERATE MASTER SPSS SYNTAX"):
        master = []
        for r in st.session_state.sq_rules:
            s, _ = generate_sq_spss_syntax(r); master.extend(s)
        for r in st.session_state.string_rules:
            s, _ = generate_string_spss_syntax(r); master.extend(s)
        st.download_button("Download .sps", "\n".join(master), "Validation.sps")