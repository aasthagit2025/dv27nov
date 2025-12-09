import streamlit as st
import pandas as pd
import numpy as np
import io
import uuid # For generating unique keys

# --- Configuration ---
FLAG_PREFIX = "xx" 
st.set_page_config(layout="wide")
st.title("📊 Survey Data Validation Automation (Final Version)")
st.markdown("Generates **KnowledgeExcel-compatible SPSS `IF` logic syntax** (`xx` prefix) based on **unique rules per variable/group**.")
st.markdown("---")

# Initialize state for storing rules
if 'sq_rules' not in st.session_state:
    st.session_state.sq_rules = []
if 'mq_rules' not in st.session_state:
    st.session_state.mq_rules = []
if 'ranking_rules' not in st.session_state:
    st.session_state.ranking_rules = []
if 'string_rules' not in st.session_state:
    st.session_state.string_rules = []
if 'all_cols' not in st.session_state:
    st.session_state.all_cols = []
    
# --- CORE UTILITY FUNCTIONS (SYNTAX GENERATION) ---

def generate_skip_spss_syntax(target_col, trigger_col, trigger_val, rule_type, range_min=None, range_max=None):
    """
    Generates detailed SPSS syntax for Skip Logic (Error of Omission/Commission)
    using the two-stage process: Flag_Qx (intermediate) -> xxSL_Qx (final EoO/EoC).
    """
    target_clean = target_col.split('_')[0] if target_col else 'Target'
    flag_col = f"{FLAG_PREFIX}SL_{target_clean}"
    filter_flag = f"Flag_{target_clean}" 
    
    syntax = []
    syntax.append(f"**************************************SKIP LOGIC FILTER FLAG: {trigger_col}={trigger_val} -> {target_col}")
    syntax.append(f"IF({trigger_col} = {trigger_val}) {filter_flag}=1.")
    syntax.append(f"EXECUTE.\n")

    # Determine the EoO condition for the target variable
    eoo_condition = f"miss({target_col})"
    
    if rule_type == 'SQ' and range_min is not None and range_max is not None:
        # For SQ, include the range check in the EoO logic
        eoo_condition = f"(miss({target_col}) | ~range({target_col},{range_min},{range_max}))"
    elif rule_type in ['MQ', 'Ranking', 'String']:
        # MQ/Ranking/String typically only need a MISS check for skip logic, unless complex data structure
        # For String, check for missing or empty string
        if rule_type == 'String':
            eoo_condition = f"({target_col}='' | miss({target_col}))"
        else:
            eoo_condition = f"miss({target_col})"


    syntax.append(f"**************************************SKIP LOGIC EoO/EoC CHECK: {target_col} -> {flag_col}")
    
    # Error of Omission (EoO) - Flag=1: Trigger Met (Flag=1), Target Fails Check (Missing/Out of Range)
    syntax.append(f"COMMENT EoO (1): Trigger Met ({filter_flag}=1), Target Fails Check/Missing.")
    syntax.append(f"IF({filter_flag} = 1 & {eoo_condition}) {flag_col}=1.")
    
    # Error of Commission (EoC) - Flag=2: Trigger Not Met (Flag<>1 OR miss) AND Target Answered
    syntax.append(f"COMMENT EoC (2): Trigger Not Met ({filter_flag}<>1 | miss({filter_flag})), Target Answered.")
    syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & ~miss({target_col})) {flag_col}=2.")
    
    syntax.append("EXECUTE.\n")
    
    return syntax, [filter_flag, flag_col]


# --- Standard Check Syntax Generators ---

def generate_sq_spss_syntax(col, min_val, max_val, required_stubs_list):
    """Generates detailed SPSS syntax for a single Single Select check."""
    syntax = []
    flag_name = f"{FLAG_PREFIX}{col}_Rng"
    syntax.append(f"**************************************SQ Missing/Range Check: {col} (Range: {min_val} to {max_val})")
    syntax.append(f"IF(miss({col}) | ~range({col},{min_val},{max_val})) {flag_name}=1.")
    syntax.append(f"EXECUTE.\n")
    
    if required_stubs_list:
        stubs_str = ', '.join(map(str, required_stubs_list))
        flag_any = f"{FLAG_PREFIX}{col}_Any"
        syntax.append(f"**************************************SQ Specific Stub Check: {col} (NOT IN: {stubs_str})")
        syntax.append(f"IF(~miss({col}) & NOT(any({col}, {stubs_str}))) {flag_any}=1.")
        syntax.append(f"EXECUTE.\n")
    return syntax, [flag_name] # Returns list of flags generated

def generate_mq_spss_syntax(cols, min_count, max_count, exclusive_col, count_method):
    """Generates detailed SPSS syntax for a single Multi-Select group check."""
    syntax = []
    mq_list_str = ' '.join(cols)
    mq_set_name = cols[0].split('_')[0] if cols else 'MQ_Set'
    generated_flags = []
    
    # 1. Sum/Count Calculation
    calc_func = "SUM" if count_method == "SUM" else "COUNT"
    mq_sum_var = f"{mq_set_name}_Count"
    syntax.append(f"**************************************MQ Count Calculation for Set: {mq_set_name} (Method: {calc_func})")
    syntax.append(f"COMPUTE {mq_sum_var} = SUM({mq_list_str}).") 
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(mq_sum_var)

    # 2. Minimum Count Check
    flag_min = f"{FLAG_PREFIX}{mq_set_name}_Min"
    syntax.append(f"**************************************MQ Minimum Count Check: {mq_set_name} (Min: {min_count})")
    syntax.append(f"IF(miss({mq_sum_var}) | {mq_sum_var} < {min_count}) {flag_min}=1.")
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(flag_min)
    
    # 3. Maximum Count Check (Optional)
    if max_count and max_count > 0:
        flag_max = f"{FLAG_PREFIX}{mq_set_name}_Max"
        syntax.append(f"**************************************MQ Maximum Count Check: {mq_set_name} (Max: {max_count})")
        syntax.append(f"IF({mq_sum_var} > {max_count}) {flag_max}=1.")
        syntax.append(f"EXECUTE.\n")
        generated_flags.append(flag_max)

    # 4. Exclusive Stub Check
    if exclusive_col and exclusive_col != 'None' and exclusive_col in cols:
        flag_exclusive = f"{FLAG_PREFIX}{mq_set_name}_Exclusive"
        exclusive_value = 1 
        syntax.append(f"**************************************MQ Exclusive Stub Check: {exclusive_col}")
        syntax.append(f"IF({exclusive_col}={exclusive_value} & {mq_sum_var} > {exclusive_value}) {flag_exclusive}=1.")
        syntax.append(f"EXECUTE.\n")
        generated_flags.append(flag_exclusive)
        
    return syntax, generated_flags


def generate_ranking_spss_syntax(cols, min_rank, max_rank):
    """Generates detailed SPSS syntax for a single Ranking set check."""
    syntax = []
    rank_list_str = ' '.join(cols)
    rank_set_name = cols[0].split('_')[0] if cols else 'Rank_Set'
    generated_flags = []
    
    # Duplicate Rank Check
    flag_duplicate = f"{FLAG_PREFIX}{rank_set_name}_Dup"
    syntax.append(f"**************************************Ranking Duplicate Check: {rank_set_name}")
    syntax.append(f"COMPUTE {flag_duplicate} = 0.")
    syntax.append(f"LOOP #rank = {min_rank} TO {max_rank}.")
    syntax.append(f"  COUNT #rank_count = {rank_list_str} (#rank).")
    syntax.append(f"  IF(#rank_count > 1) {flag_duplicate}=1.")
    syntax.append(f"END LOOP.")
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(flag_duplicate)
    
    # Rank Range Check
    flag_range_name = f"{FLAG_PREFIX}{rank_set_name}_Rng"
    syntax.append(f"**************************************Ranking Range Check: {rank_set_name} (Range: {min_rank} to {max_rank})")
    syntax.append(f"COMPUTE {flag_range_name} = 0.")
    for col in cols:
        syntax.append(f"IF(~miss({col}) & ~range({col},{min_rank},{max_rank})) {flag_range_name}=1.")
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(flag_range_name)
        
    return syntax, generated_flags


def generate_string_spss_syntax(col, min_length):
    """Generates detailed SPSS syntax for a single String/Open-End check."""
    syntax = []
    generated_flags = []
    
    # Missing Data Check
    flag_missing = f"{FLAG_PREFIX}{col}_Miss"
    syntax.append(f"**************************************String Missing Check: {col}")
    syntax.append(f"IF({col}='' | miss({col})) {flag_missing}=1.")
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(flag_missing)
    
    # Junk Check
    flag_junk = f"{FLAG_PREFIX}{col}_Junk"
    syntax.append(f"**************************************String Junk Check: {col} (Length < {min_length})")
    syntax.append(f"IF(~miss({col}) & length(rtrim({col})) < {min_length}) {flag_junk}=1.")
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(flag_junk)
        
    return syntax, generated_flags

def generate_master_spss_syntax(sq_rules, mq_rules, ranking_rules, string_rules):
    """Generates the final .sps file by iterating over all stored rules."""
    all_syntax_blocks = []
    all_flag_cols = []
    
    # Process SQ Rules
    for rule in sq_rules:
        target_col = rule['variable']
        syntax, flags = generate_sq_spss_syntax(target_col, rule['min_val'], rule['max_val'], rule['stubs'])
        all_syntax_blocks.append(syntax)
        all_flag_cols.extend(flags)
        
        if rule['run_skip']:
            sl_syntax, sl_flags = generate_skip_spss_syntax(
                target_col, rule['trigger_col'], rule['trigger_val'], 'SQ', rule['min_val'], rule['max_val']
            )
            all_syntax_blocks.append(sl_syntax)
            all_flag_cols.extend(sl_flags)

    # Process MQ Rules
    for rule in mq_rules:
        syntax, flags = generate_mq_spss_syntax(
            rule['variables'], rule['min_count'], rule['max_count'], rule['exclusive_col'], rule['count_method']
        )
        all_syntax_blocks.append(syntax)
        all_flag_cols.extend(flags)
        
        if rule['run_skip']:
            target_col = rule['variables'][0] # Use the first variable as proxy
            sl_syntax, sl_flags = generate_skip_spss_syntax(
                target_col, rule['trigger_col'], rule['trigger_val'], 'MQ'
            )
            all_syntax_blocks.append(sl_syntax)
            all_flag_cols.extend(sl_flags)
            
    # Process Ranking Rules
    for rule in ranking_rules:
        syntax, flags = generate_ranking_spss_syntax(
            rule['variables'], rule['min_rank'], rule['max_rank']
        )
        all_syntax_blocks.append(syntax)
        all_flag_cols.extend(flags)
        
        if rule['run_skip']:
            target_col = rule['variables'][0] # Use the first variable as proxy
            sl_syntax, sl_flags = generate_skip_spss_syntax(
                target_col, rule['trigger_col'], rule['trigger_val'], 'Ranking'
            )
            all_syntax_blocks.append(sl_syntax)
            all_flag_cols.extend(sl_flags)

    # Process String Rules
    for rule in string_rules:
        target_col = rule['variable']
        syntax, flags = generate_string_spss_syntax(target_col, rule['min_length'])
        all_syntax_blocks.append(syntax)
        all_flag_cols.extend(flags)
        
        if rule['run_skip']:
            sl_syntax, sl_flags = generate_skip_spss_syntax(
                target_col, rule['trigger_col'], rule['trigger_val'], 'String'
            )
            all_syntax_blocks.append(sl_syntax)
            all_flag_cols.extend(sl_flags)


    # --- Master Syntax Compilation ---
    sps_content = []
    sps_content.append(f"*{'='*60}*")
    sps_content.append(f"* PYTHON-GENERATED DATA VALIDATION SCRIPT (KNOWLEDGEEXCEL FORMAT) *")
    sps_content.append(f"*{'='*60}*\n")
    sps_content.append("DATASET ACTIVATE ALL.")
    
    # 1. Insert ALL detailed validation logic
    sps_content.append("\n\n* --- 1. DETAILED VALIDATION LOGIC --- *")
    # Flatten the list of lists of syntax lines
    sps_content.append("\n".join([item for sublist in all_syntax_blocks for item in sublist]))
    
    # 2. Add Value Labels & Master Flags
    sps_content.append("\n* --- 2. VALUE LABELS & VARIABLE INITIALIZATION --- *")
    unique_flag_names = sorted(list(set(all_flag_cols)))
    
    for flag in unique_flag_names:
        if flag.startswith(f'{FLAG_PREFIX}SL_'):
            sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail: Error of Omission' 2 'Fail: Error of Commission'.")
        elif flag.startswith('Flag_'):
             sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Filter Flag (Intermediate)'.") 
        elif flag.startswith(FLAG_PREFIX):
            sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail: Data Check'.")
            
    sps_content.append("EXECUTE.\n")

    # 3. Compute a Master Reject Flag
    master_error_flags = [f for f in unique_flag_names if f.startswith(FLAG_PREFIX) or f.startswith('Flag_')]
    
    sps_content.append("\n* --- 3. MASTER REJECT COUNT COMPUTATION --- *")
    if master_error_flags:
        temp_flag_logic = []
        temp_flags = []
        
        # Only count the flags that represent a true error (xx* flags, not the intermediate Flag_Qx filter)
        error_flags_to_count = [f for f in master_error_flags if f.startswith(FLAG_PREFIX)]
        
        for flag in error_flags_to_count:
            temp_name = f"T_{flag}"
            temp_flag_logic.append(f"IF({flag}>0) {temp_name}=1.") 
            temp_flag_logic.append(f"ELSE {temp_name}=0.")
            temp_flags.append(temp_name)
        
        if temp_flags:
            sps_content.append("\n*--- Temporary Binary Flags for Counting ---*")
            sps_content.extend(temp_flag_logic)
            sps_content.append("EXECUTE.\n")

            master_flag_logic = ' + '.join(temp_flags)
            
            sps_content.append(f"COMPUTE Master_Reject_Count = SUM({master_flag_logic}).")
            sps_content.append("VARIABLE LABELS Master_Reject_Count 'Total Validation Errors (DV)'.")
            sps_content.append("EXECUTE.")

            # Cleanup and Frequencies
            sps_content.append("\nDELETE VARIABLES T_*.")
            sps_content.append("EXECUTE.")
            
            sps_content.append("\n* --- 4. VALIDATION REPORT (Frequencies) --- *")
            sps_content.append(f"FREQUENCIES VARIABLES=Master_Reject_Count {'; '.join(error_flags_to_count)} /STATISTICS=COUNT MEAN.")
        
    return "\n".join(sps_content)


def clear_all_rules():
    st.session_state.sq_rules = []
    st.session_state.mq_rules = []
    st.session_state.ranking_rules = []
    st.session_state.string_rules = []

# --- UI Rule Management Functions ---

def display_sq_rules():
    if st.session_state.sq_rules:
        st.subheader("Current SQ Rules")
        df_rules = pd.DataFrame(st.session_state.sq_rules)
        df_display = df_rules[['variable', 'min_val', 'max_val', 'run_skip', 'trigger_col', 'trigger_val']].rename(
            columns={'variable': 'Target Var', 'min_val': 'Min', 'max_val': 'Max', 
                     'run_skip': 'Skip Enabled', 'trigger_col': 'Trigger Var', 'trigger_val': 'Trigger Val'}
        )
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        st.markdown("---")

def display_mq_rules():
    if st.session_state.mq_rules:
        st.subheader("Current MQ Rules")
        df_rules = pd.DataFrame(st.session_state.mq_rules)
        df_rules['Variables'] = df_rules['variables'].apply(lambda x: f"{x[0]}... ({len(x)} vars)")
        df_display = df_rules[['Variables', 'min_count', 'max_count', 'exclusive_col', 'count_method', 'run_skip', 'trigger_col', 'trigger_val']].rename(
            columns={'min_count': 'Min Count', 'max_count': 'Max Count', 
                     'exclusive_col': 'Exclusive', 'count_method': 'Method',
                     'run_skip': 'Skip Enabled', 'trigger_col': 'Trigger Var', 'trigger_val': 'Trigger Val'}
        )
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        st.markdown("---")
        
def display_ranking_rules():
    if st.session_state.ranking_rules:
        st.subheader("Current Ranking Rules")
        df_rules = pd.DataFrame(st.session_state.ranking_rules)
        df_rules['Variables'] = df_rules['variables'].apply(lambda x: f"{x[0]}... ({len(x)} vars)")
        df_display = df_rules[['Variables', 'min_rank', 'max_rank', 'run_skip', 'trigger_col', 'trigger_val']].rename(
            columns={'min_rank': 'Min Rank', 'max_rank': 'Max Rank', 
                     'run_skip': 'Skip Enabled', 'trigger_col': 'Trigger Var', 'trigger_val': 'Trigger Val'}
        )
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        st.markdown("---")

def display_string_rules():
    if st.session_state.string_rules:
        st.subheader("Current String Rules")
        df_rules = pd.DataFrame(st.session_state.string_rules)
        df_display = df_rules[['variable', 'min_length', 'run_skip', 'trigger_col', 'trigger_val']].rename(
            columns={'variable': 'Target Var', 'min_length': 'Min Length', 
                     'run_skip': 'Skip Enabled', 'trigger_col': 'Trigger Var', 'trigger_val': 'Trigger Val'}
        )
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        st.markdown("---")

# --- STREAMLIT APPLICATION UI ---

# --- Step 1: File Upload ---
st.header("Step 1: Upload Data (.csv)")
uploaded_file = st.file_uploader("Choose a CSV File", type="csv")

if uploaded_file:
    try:
        df_raw = pd.read_csv(uploaded_file, encoding='latin-1') 
        st.success(f"Loaded {len(df_raw)} rows and {len(df_raw.columns)} columns.")
        
        if 'uuid' not in df_raw.columns:
            df_raw['uuid'] = df_raw.index.map(lambda x: f"Resp_{x+1}")
        df_raw['uuid'] = df_raw['uuid'].astype(str)
        
        st.session_state.all_cols = df_raw.columns.tolist()
        df_validated = df_raw.copy()
        
        st.markdown("---")
        st.header("Step 2: Define Validation Rules")
        st.sidebar.button("🗑️ Clear All Rules", on_click=clear_all_rules)
        st.sidebar.markdown("---")
        st.sidebar.subheader("Rule Count")
        st.sidebar.markdown(f"**SQ Rules:** {len(st.session_state.sq_rules)}")
        st.sidebar.markdown(f"**MQ Rules:** {len(st.session_state.mq_rules)}")
        st.sidebar.markdown(f"**Ranking Rules:** {len(st.session_state.ranking_rules)}")
        st.sidebar.markdown(f"**String Rules:** {len(st.session_state.string_rules)}")
        
        
        # --- Single Select / Rating Check ---
        display_sq_rules()
        with st.expander("➕ Add Single Select / Rating Rule (SQ)", expanded=True):
            with st.form("sq_form", clear_on_submit=True):
                col_sq_var, col_min, col_max = st.columns(3)
                with col_sq_var:
                    sq_col = st.selectbox("Target Variable (Qx)", st.session_state.all_cols, key=f'sq_col_{uuid.uuid4()}')
                with col_min:
                    sq_min = st.number_input("Minimum Valid Value (Range Check)", min_value=1, value=1, key=f'sq_min_{uuid.uuid4()}')
                with col_max:
                    sq_max = st.number_input("Maximum Valid Value (Range Check)", min_value=1, value=5, key=f'sq_max_{uuid.uuid4()}')
                
                sq_stubs_str = st.text_input("Specific Stubs (ANY) - Must be one of: e.g., '1, 3, 5' (Optional)", value='', help="Checks if the answer is *not* one of these values.")
                
                st.markdown("---")
                run_sq_skip = st.checkbox(f"Add Skip Logic/Piping Check (EoO/EoC)", key=f'run_sq_skip_{uuid.uuid4()}')
                
                sq_trigger_col = 'None'
                sq_trigger_val = ''
                if run_sq_skip:
                    col_c, col_d = st.columns(2)
                    with col_c:
                        sq_trigger_col = st.selectbox("Trigger Question (Q_Prev)", st.session_state.all_cols, key=f'sq_trigger_col_sl_{uuid.uuid4()}')
                    with col_d:
                        sq_trigger_val = st.text_input("Trigger Value (e.g., '1' for 'Yes')", value='1', key=f'sq_trigger_val_sl_{uuid.uuid4()}')
                
                submitted_sq = st.form_submit_button("➕ Add SQ Rule")
                if submitted_sq:
                    if sq_col:
                        required_stubs = [int(s.strip()) for s in sq_stubs_str.split(',') if s.strip().isdigit()] if sq_stubs_str else None
                        
                        st.session_state.sq_rules.append({
                            'variable': sq_col,
                            'min_val': sq_min,
                            'max_val': sq_max,
                            'stubs': required_stubs,
                            'run_skip': run_sq_skip,
                            'trigger_col': sq_trigger_col,
                            'trigger_val': sq_trigger_val,
                        })
                        st.success(f"SQ Rule added for **{sq_col}**.")
                        st.rerun() # Refresh to show the new rule
                    else:
                        st.warning("Please select a Target Variable.")

        st.markdown("---")
        
        # --- Multi-Select Check (MQ) ---
        display_mq_rules()
        with st.expander("➕ Add Multi-Select Rule (MQ)", expanded=True):
            with st.form("mq_form", clear_on_submit=True):
                mq_cols_default = [c for c in st.session_state.all_cols if c.startswith('Q') and ('_c' in c or '_a' in c)]
                mq_cols = st.multiselect("Select ALL Multi-Select Columns (The Group, e.g., Q1_1 to Q1_9)", st.session_state.all_cols, 
                                        default=mq_cols_default, key=f'mq_cols_select_{uuid.uuid4()}')
                
                st.markdown("**Validation Parameters**")
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    mq_min_count = st.number_input("Minimum Selections Required", min_value=0, value=1, key=f'mq_min_count_{uuid.uuid4()}')
                with col_b:
                    mq_max_count = st.number_input("Maximum Selections Allowed (0 for no max)", min_value=0, key=f'mq_max_count_{uuid.uuid4()}')
                with col_c:
                    exclusive_col = st.selectbox("Select Exclusive Stub Column (Optional)", ['None'] + mq_cols, key=f'mq_exclusive_col_{uuid.uuid4()}')
                
                mq_count_method = st.radio("SPSS Calculation Method", ["SUM", "COUNT"], index=0, help="SUM is generally more robust for 0/1 coded data.")

                st.markdown("---")
                run_mq_skip = st.checkbox(f"Add Skip Logic/Piping Check (EoO/EoC) - uses {mq_cols[0] if mq_cols else 'None'} as proxy", key=f'run_mq_skip_{uuid.uuid4()}')

                mq_trigger_col = 'None'
                mq_trigger_val = ''
                if run_mq_skip:
                    col_d, col_e = st.columns(2)
                    with col_d:
                        mq_trigger_col = st.selectbox("Trigger Question (Q_Prev)", st.session_state.all_cols, key=f'mq_trigger_col_mq_{uuid.uuid4()}')
                    with col_e:
                        mq_trigger_val = st.text_input("Trigger Value (e.g., '1')", value='1', key=f'mq_trigger_val_mq_{uuid.uuid4()}')
                        
                submitted_mq = st.form_submit_button("➕ Add MQ Rule")
                if submitted_mq:
                    if mq_cols:
                        st.session_state.mq_rules.append({
                            'variables': mq_cols,
                            'min_count': mq_min_count,
                            'max_count': mq_max_count if mq_max_count > 0 else None,
                            'exclusive_col': exclusive_col,
                            'count_method': mq_count_method,
                            'run_skip': run_mq_skip,
                            'trigger_col': mq_trigger_col,
                            'trigger_val': mq_trigger_val,
                        })
                        st.success(f"MQ Rule added for group starting with **{mq_cols[0]}**.")
                        st.rerun()
                    else:
                        st.warning("Please select columns for MQ Check.")

        st.markdown("---")

        # --- Ranking Check ---
        display_ranking_rules()
        with st.expander("➕ Add Ranking Rule", expanded=False):
            with st.form("ranking_form", clear_on_submit=True):
                rank_cols_default = [c for c in st.session_state.all_cols if c.startswith('Rank_') or c.startswith('R_')]
                rank_cols = st.multiselect("Select ALL Ranking Columns (The Set)", st.session_state.all_cols, 
                                        default=rank_cols_default, key=f'rank_cols_select_{uuid.uuid4()}')
                col_a, col_b = st.columns(2)
                with col_a:
                    rank_min = st.number_input("Minimum Expected Rank Value", min_value=1, value=1, key=f'rank_min_{uuid.uuid4()}')
                with col_b:
                    rank_max = st.number_input("Maximum Expected Rank Value", min_value=1, value=3, key=f'rank_max_{uuid.uuid4()}')
                
                st.markdown("---")
                run_rank_skip = st.checkbox(f"Add Skip Logic/Piping Check (EoO/EoC) - uses {rank_cols[0] if rank_cols else 'None'} as proxy", key=f'run_rank_skip_{uuid.uuid4()}')

                rank_trigger_col = 'None'
                rank_trigger_val = ''
                if run_rank_skip:
                    col_c, col_d = st.columns(2)
                    with col_c:
                        rank_trigger_col = st.selectbox("Trigger Question (Q_Prev)", st.session_state.all_cols, key=f'rank_trigger_col_rank_{uuid.uuid4()}')
                    with col_d:
                        rank_trigger_val = st.text_input("Trigger Value (e.g., '1')", value='1', key=f'rank_trigger_val_rank_{uuid.uuid4()}')
                
                submitted_rank = st.form_submit_button("➕ Add Ranking Rule")
                if submitted_rank:
                    if rank_cols:
                        st.session_state.ranking_rules.append({
                            'variables': rank_cols,
                            'min_rank': rank_min,
                            'max_rank': rank_max,
                            'run_skip': run_rank_skip,
                            'trigger_col': rank_trigger_col,
                            'trigger_val': rank_trigger_val,
                        })
                        st.success(f"Ranking Rule added for set starting with **{rank_cols[0]}**.")
                        st.rerun()
                    else:
                        st.warning("Please select columns for Ranking Check.")

        st.markdown("---")

        # --- String Check (Open Ends) ---
        display_string_rules()
        with st.expander("➕ Add String/Open-End Rule", expanded=False):
            with st.form("string_form", clear_on_submit=True):
                string_cols_default = [c for c in st.session_state.all_cols if c.endswith('_TEXT') or c.endswith('_OE')]
                string_col = st.selectbox("Target Variable (Qx_TEXT/OE)", st.session_state.all_cols, default=string_cols_default[0] if string_cols_default else None, key=f'string_col_select_{uuid.uuid4()}')
                string_min_length = st.number_input("Minimum Non-Junk Length (e.g., 5 characters)", min_value=1, value=5, key=f'string_min_length_{uuid.uuid4()}')
                
                st.markdown("---")
                run_string_skip = st.checkbox(f"Add Skip Logic/Piping Check (EoO/EoC)", key=f'run_string_skip_{uuid.uuid4()}')

                string_trigger_col = 'None'
                string_trigger_val = ''
                if run_string_skip:
                    col_c, col_d = st.columns(2)
                    with col_c:
                        string_trigger_col = st.selectbox("Trigger Question (Q_Prev)", st.session_state.all_cols, key=f'string_trigger_col_string_{uuid.uuid4()}')
                    with col_d:
                        string_trigger_val = st.text_input("Trigger Value (e.g., '1')", value='1', key=f'string_trigger_val_string_{uuid.uuid4()}')

                submitted_string = st.form_submit_button("➕ Add String Rule")
                if submitted_string:
                    if string_col:
                        st.session_state.string_rules.append({
                            'variable': string_col,
                            'min_length': string_min_length,
                            'run_skip': run_string_skip,
                            'trigger_col': string_trigger_col,
                            'trigger_val': string_trigger_val,
                        })
                        st.success(f"String Rule added for **{string_col}**.")
                        st.rerun()
                    else:
                        st.warning("Please select a Target Variable.")
            
        st.markdown("---")
        st.header("Step 3: Generate Master Syntax")
        
        total_rules = len(st.session_state.sq_rules) + len(st.session_state.mq_rules) + len(st.session_state.ranking_rules) + len(st.session_state.string_rules)
        
        if total_rules > 0:
            
            # --- Generate Master Outputs ---
            master_spss_syntax = generate_master_spss_syntax(
                st.session_state.sq_rules, 
                st.session_state.mq_rules, 
                st.session_state.ranking_rules, 
                st.session_state.string_rules
            )
            # Placeholder for Excel report generation (using a dummy function as actual data flagging is skipped for efficiency)
            excel_report_bytes = generate_excel_report(df_validated, [])
            
            st.success(f"Generated complete syntax for {total_rules} validation rules.")
            
            col_a, col_b = st.columns(2)
            
            with col_a:
                st.download_button(
                    label="⬇️ Download Master SPSS Syntax (.sps)",
                    data=master_spss_syntax,
                    file_name="master_validation_script_knowledgeexcel.sps",
                    mime="text/plain"
                )
            with col_b:
                st.download_button(
                    label="⬇️ Download Excel Error Report (.xlsx) - (Placeholder)",
                    data=excel_report_bytes,
                    file_name="validation_error_summary.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
            st.subheader("Preview of Generated Detailed SPSS Logic")
            # Display a preview of the generated syntax
            preview_syntax_list = [item for sublist in [generate_sq_spss_syntax(r['variable'], r['min_val'], r['max_val'], r['stubs'])[0] for r in st.session_state.sq_rules] + 
                                                    [generate_mq_spss_syntax(r['variables'], r['min_count'], r['max_count'], r['exclusive_col'], r['count_method'])[0] for r in st.session_state.mq_rules] + 
                                                    [generate_ranking_spss_syntax(r['variables'], r['min_rank'], r['max_rank'])[0] for r in st.session_state.ranking_rules] + 
                                                    [generate_string_spss_syntax(r['variable'], r['min_length'])[0] for r in st.session_state.string_rules] 
                                for item in sublist]
            
            preview_syntax = '\n'.join(preview_syntax_list)
            st.code(preview_syntax[:1500] + "\n\n...(Download the .sps file for the complete detailed syntax)", language='spss')
            
        else:
            st.warning("Please define and add at least one validation rule in Step 2.")
            

    except Exception as e:
        st.error(f"An error occurred during processing. Error: {e}")