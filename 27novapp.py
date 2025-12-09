import streamlit as st
import pandas as pd
import numpy as np
import io

# --- Configuration ---
FLAG_PREFIX = "xx" 
st.set_page_config(layout="wide")
st.title("📊 Survey Data Validation Automation (Final Version)")
st.markdown("Generates **KnowledgeExcel-compatible SPSS `IF` logic syntax** (`xx` prefix) for multiple variables and integrates optional Skip Logic (EoO/EoC).")
st.markdown("---")

# Initialize state
if 'current_flag_cols' not in st.session_state:
    st.session_state.current_flag_cols = []
if 'spss_syntax_blocks' not in st.session_state:
    st.session_state.spss_syntax_blocks = []
    
# --- CORE UTILITY FUNCTIONS (DATA PROCESSING & SYNTAX GENERATION) ---

# All syntax generation functions now take a list of columns and return a list of syntax lines

def run_skip_logic_check(df, target_col, trigger_col, trigger_val):
    """Applies skip logic for a single target/trigger pair (for data frame flagging)."""
    flag_cols = []
    if all(col in df.columns for col in [target_col, trigger_col]):
        target_name = target_col.split('_')[0]
        trigger_name = trigger_col.split('_')[0]
        flag_col = f"{FLAG_PREFIX}SL_{trigger_name}_to_{target_name}"
        
        df[trigger_col] = df[trigger_col].astype(str).str.strip()
        trigger_val_str = str(trigger_val).strip()
        
        commission_mask = (df[trigger_col] != trigger_val_str) & (df[target_col].notna())
        omission_mask = (df[trigger_col] == trigger_val_str) & (df[target_col].isna())
        
        df[flag_col] = np.select([commission_mask, omission_mask], [2, 1], default=0)
        flag_cols.append(flag_col)
    return df, flag_cols

def generate_skip_spss_syntax(target_col, trigger_col, trigger_val):
    """Generates detailed SPSS syntax for Skip Logic (Error of Omission/Commission)."""
    target_clean = target_col.split('_')[0] if target_col else 'Target'
    trigger_clean = trigger_col.split('_')[0] if trigger_col else 'Trigger'
    flag_col = f"{FLAG_PREFIX}SL_{trigger_clean}_to_{target_clean}"
    
    syntax = []
    syntax.append(f"**************************************SKIP LOGIC/PIPING CHECK: {trigger_col}={trigger_val} -> {target_col}")
    syntax.append(f"COMMENT EoO (1): Trigger Met ({trigger_col}={trigger_val}), Target Missing.")
    syntax.append(f"IF({trigger_col} = {trigger_val} & miss({target_col})) {flag_col}=1.")
    
    # EoC logic: Trigger not met OR Trigger is missing, AND Target is answered
    syntax.append(f"COMMENT EoC (2): Trigger Not Met ({trigger_col}<>{trigger_val} OR miss({trigger_col})), Target Answered.")
    syntax.append(f"IF(({trigger_col} <> {trigger_val} | miss({trigger_col})) & ~miss({target_col})) {flag_col}=2.")
    syntax.append("EXECUTE.\n")
    
    return syntax


def generate_sq_spss_syntax(cols, min_val, max_val, required_stubs_list):
    """Generates detailed SPSS syntax for Multiple Single Select checks."""
    syntax = []
    for col in cols:
        # Missing/Range Check
        flag_name = f"{FLAG_PREFIX}{col}_Rng"
        syntax.append(f"**************************************SQ Missing/Range Check: {col} (Range: {min_val} to {max_val})")
        syntax.append(f"IF(miss({col}) | ~range({col},{min_val},{max_val})) {flag_name}=1.")
        syntax.append(f"EXECUTE.")
        syntax.append("\n")

        # Specific Stubs (ANY check)
        if required_stubs_list:
            stubs_str = ', '.join(map(str, required_stubs_list))
            flag_any = f"{FLAG_PREFIX}{col}_Any"
            syntax.append(f"**************************************SQ Specific Stub Check: {col} (NOT IN: {stubs_str})")
            syntax.append(f"IF(~miss({col}) & NOT(any({col}, {stubs_str}))) {flag_any}=1.")
            syntax.append(f"EXECUTE.")
            syntax.append("\n")
    return syntax


def generate_mq_spss_syntax(cols, min_count, max_count, exclusive_col, count_method):
    """Generates detailed SPSS syntax for Multi-Select checks (single group)."""
    syntax = []
    mq_list_str = ' '.join(cols)
    # Use the first variable's stem as the set name
    mq_set_name = cols[0].split('_')[0] if cols else 'MQ_Set' 
    
    # 1. Sum/Count Calculation
    calc_func = "SUM" if count_method == "SUM" else "COUNT"
    syntax.append(f"**************************************MQ Count Calculation for Set: {mq_set_name} (Method: {calc_func})")
    
    if calc_func == "SUM":
        syntax.append(f"COMPUTE {mq_set_name}_Sum = SUM({mq_list_str}).")
    else: # COUNT method checks how many stubs are marked with '1'
        count_args = ', '.join([f"{col}(1)" for col in cols])
        syntax.append(f"COMPUTE {mq_set_name}_Sum = NVALID({mq_list_str}). /* Use NVALID if all are coded 1/SysMiss. Or use COUNT for specific value */")
        # For simplicity and robustness with standard 0/1 data, SUM is often preferred. 
        # Since the user requested COUNT, we'll assume the COUNT logic which requires checking for a specific value.
        # However, for 0/1 data, SUM is equivalent to COUNT(cols, 1). We'll use the user's input for the command comment.
        syntax.append(f"COMMENT For 0/1 data, SUM is often safer. Using SUM here which is equivalent to COUNT for 0/1 data.")
        syntax.append(f"COMPUTE {mq_set_name}_Count = SUM({mq_list_str}).")
        mq_sum_var = f"{mq_set_name}_Count"

    syntax.append(f"EXECUTE.")
    syntax.append("\n")

    # 2. Minimum Count Check
    flag_min = f"{FLAG_PREFIX}{mq_set_name}_Min"
    syntax.append(f"**************************************MQ Minimum Count Check: {mq_set_name} (Min: {min_count})")
    syntax.append(f"IF(miss({mq_sum_var}) | {mq_sum_var} < {min_count}) {flag_min}=1.")
    syntax.append(f"EXECUTE.")
    syntax.append("\n")
    
    # 3. Maximum Count Check (Optional)
    if max_count and max_count > 0:
        flag_max = f"{FLAG_PREFIX}{mq_set_name}_Max"
        syntax.append(f"**************************************MQ Maximum Count Check: {mq_set_name} (Max: {max_count})")
        syntax.append(f"IF({mq_sum_var} > {max_count}) {flag_max}=1.")
        syntax.append(f"EXECUTE.")
        syntax.append("\n")

    # 4. Exclusive Stub Check
    if exclusive_col and exclusive_col != 'None' and exclusive_col in cols:
        flag_exclusive = f"{FLAG_PREFIX}{mq_set_name}_Exclusive"
        exclusive_value = 1 
        syntax.append(f"**************************************MQ Exclusive Stub Check: {exclusive_col}")
        # If exclusive selected AND total sum is > 1 (meaning other stubs were also selected)
        syntax.append(f"IF({exclusive_col}={exclusive_value} & {mq_sum_var} > {exclusive_value}) {flag_exclusive}=1.")
        syntax.append(f"EXECUTE.")
        syntax.append("\n")
        
    return syntax, mq_sum_var


def generate_ranking_spss_syntax(cols, min_rank, max_rank):
    """Generates detailed SPSS syntax for Multiple Ranking checks."""
    syntax = []
    
    for rank_set_name in cols:
        # We assume the user selects the representative columns one by one, 
        # or the set of columns is defined by the selection. 
        # Since ranking checks are often performed on a set of variables that use ranks 1-N, 
        # this function should ideally receive the *entire set*. 
        # Due to the multiple selection feature, we will assume each selected column is part of a single large ranking set for now,
        # or the user selects all columns in the set (e.g., Q1_R1, Q1_R2, Q1_R3) in the multi-select.
        
        # We will assume all selected columns form ONE ranking set.
        pass
    
    rank_list_str = ' '.join(cols)
    rank_set_name = cols[0].split('_')[0] if cols else 'Rank_Set'
    
    # Duplicate Rank Check
    flag_duplicate = f"{FLAG_PREFIX}{rank_set_name}_Dup"
    syntax.append(f"**************************************Ranking Duplicate Check: {rank_set_name}")
    syntax.append(f"COMPUTE {flag_duplicate} = 0.")
    syntax.append(f"LOOP #rank = {min_rank} TO {max_rank}.")
    syntax.append(f"  COUNT #rank_count = {rank_list_str} (#rank).")
    syntax.append(f"  IF(#rank_count > 1) {flag_duplicate}=1.")
    syntax.append(f"END LOOP.")
    syntax.append(f"EXECUTE.")
    syntax.append("\n")
    
    # Rank Range Check
    flag_range_name = f"{FLAG_PREFIX}{rank_set_name}_Rng"
    syntax.append(f"**************************************Ranking Range Check: {rank_set_name} (Range: {min_rank} to {max_rank})")
    syntax.append(f"COMPUTE {flag_range_name} = 0.")
    for col in cols:
        syntax.append(f"IF(~miss({col}) & ~range({col},{min_rank},{max_rank})) {flag_range_name}=1.")
    syntax.append(f"EXECUTE.")
    syntax.append("\n")
        
    return syntax


def generate_string_spss_syntax(cols, min_length):
    """Generates detailed SPSS syntax for Multiple String/Open-End checks."""
    syntax = []
    for col in cols:
        # Missing Data Check
        flag_missing = f"{FLAG_PREFIX}{col}_Miss"
        syntax.append(f"**************************************String Missing Check: {col}")
        syntax.append(f"IF({col}='' | miss({col})) {flag_missing}=1.")
        syntax.append(f"EXECUTE.")
        syntax.append("\n")
        
        # Junk Check
        flag_junk = f"{FLAG_PREFIX}{col}_Junk"
        syntax.append(f"**************************************String Junk Check: {col} (Length < {min_length})")
        syntax.append(f"IF(~miss({col}) & length(rtrim({col})) < {min_length}) {flag_junk}=1.")
        syntax.append(f"EXECUTE.")
        syntax.append("\n")
        
    return syntax


def generate_master_spss_syntax(all_syntax_blocks, flag_cols):
    """Generates the final .sps file, including labels and reports."""
    sps_content = []
    sps_content.append(f"*{'='*60}*")
    sps_content.append(f"* PYTHON-GENERATED DATA VALIDATION SCRIPT (KNOWLEDGEEXCEL FORMAT) *")
    sps_content.append(f"*{'='*60}*\n")
    sps_content.append("DATASET ACTIVATE ALL.")
    
    # 1. Insert ALL detailed validation logic
    sps_content.append("\n\n* --- 1. DETAILED VALIDATION LOGIC --- *")
    sps_content.append("\n".join([item for sublist in all_syntax_blocks for item in sublist]))
    
    # 2. Add Value Labels (Crucial for KnowledgeExcel format)
    sps_content.append("\n* --- 2. VALUE LABELS & VARIABLE INITIALIZATION --- *")
    unique_flag_names = sorted(list(set(flag_cols)))
    
    for flag in unique_flag_names:
        if flag.startswith(f'{FLAG_PREFIX}SL_'):
            sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail: Error of Omission' 2 'Fail: Error of Commission'.")
        elif flag.startswith('Flag_'):
             sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail: Quality Check'.")
        elif flag.startswith(FLAG_PREFIX):
            sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail: Data Check'.")
            
    sps_content.append("EXECUTE.\n")

    # 3. Compute a Master Reject Flag
    master_flag_cols = [f for f in flag_cols if f.startswith('Flag_') or f.startswith(FLAG_PREFIX)]
    
    sps_content.append("\n* --- 3. MASTER REJECT FLAG COMPUTATION --- *")
    if master_flag_cols:
        temp_flag_logic = []
        temp_flags = []
        
        for flag in master_flag_cols:
            temp_name = f"T_{flag}"
            temp_flag_logic.append(f"IF({flag}>0) {temp_name}=1.") 
            temp_flag_logic.append(f"ELSE {temp_name}=0.")
            temp_flags.append(temp_name)
        
        sps_content.append("\n*--- Temporary Binary Flags for Counting ---*")
        sps_content.extend(temp_flag_logic)
        sps_content.append("EXECUTE.\n")

        master_flag_logic = ' + '.join(temp_flags)
        mq_sums = [f for f in flag_cols if f.endswith('_Sum') or f.endswith('_Count')]
        
        sps_content.append(f"COMPUTE Master_Reject_Count = SUM({master_flag_logic}).")
        sps_content.append("VARIABLE LABELS Master_Reject_Count 'Total Validation Errors (DV)'.")
        sps_content.append("EXECUTE.")

        # Cleanup
        sps_content.append("\nDELETE VARIABLES T_*.")
        sps_content.append("EXECUTE.")
        sps_content.append("\n*--- MQ SUM/COUNT Variables (KEEPING) ---*")
        
        # 4. Frequencies
        sps_content.append("\n* --- 4. VALIDATION REPORT (Frequencies) --- *")
        sps_content.append(f"FREQUENCIES VARIABLES=Master_Reject_Count {'; '.join(master_flag_cols)} {'; '.join(mq_sums)} /STATISTICS=COUNT MEAN.")
        
    return "\n".join(sps_content)


def generate_excel_report(df, flag_cols):
    """Generates the Excel error report as bytes."""
    # (Simplified for brevity, assumes data processing is done in the run_* functions)
    error_df = pd.DataFrame() 
    if flag_cols:
        existing_flag_cols = [col for col in flag_cols if col in df.columns]
        if existing_flag_cols:
            normalized_flags = {col: np.where(df[col].fillna(0) > 0, 1, 0) for col in existing_flag_cols}
            df_norm = pd.DataFrame(normalized_flags)
            df['Total_Errors'] = df_norm.sum(axis=1)
            error_df = df[df['Total_Errors'] > 0].copy() 
            
    cols_to_report = ['uuid'] + [col for col in df.columns if col.startswith('Flag_') or col.startswith(FLAG_PREFIX)] + ['Total_Errors']
    cols_to_report = [col for col in cols_to_report if col in error_df.columns]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if not error_df.empty:
            report_df = error_df[cols_to_report]
            report_df.to_excel(writer, sheet_name='Respondent Errors', index=False)
        else:
            status_df = pd.DataFrame([["Validation completed successfully. No flagged errors detected in this run."]], columns=['Status'])
            status_df.to_excel(writer, sheet_name='Validation Status', index=False)
            
    return output.getvalue()


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
        
        all_cols = df_raw.columns.tolist()
        df_validated = df_raw.copy()
        
        st.markdown("---")
        st.header("Step 2: Define and Run Validation Checks")
        st.info("Select multiple variables for checks. Enable 'Skip Condition' for EoO/EoC logic.")
        
        
        # --- Single Select / Rating Check ---
        with st.expander("✅ Single Select / Rating Check (SQ, Range, Specific Stubs)", expanded=True):
            with st.form("sq_form"):
                sq_cols = st.multiselect("Select SQ/Rating Variables (Ctrl/Cmd to select multiple)", all_cols, key='sq_col_select')
                col_a, col_b = st.columns(2)
                with col_a:
                    sq_min = st.number_input("Minimum Valid Value (Range Check)", min_value=1, value=1, key='sq_min')
                with col_b:
                    sq_max = st.number_input("Maximum Valid Value (Range Check)", min_value=1, value=5, key='sq_max')
                sq_stubs_str = st.text_input("Specific Stubs (ANY) - Must be one of: e.g., '1, 3, 5' (Optional)", value='', key='sq_stubs_str')
                
                st.markdown("---")
                # INTEGRATED OPTIONAL SKIP LOGIC
                run_sq_skip = st.checkbox(f"Add Skip Logic/Piping Check (EoO/EoC)", key='run_sq_skip', help="Applies the skip logic to ALL selected SQ variables.")
                
                sq_trigger_col = None
                sq_trigger_val = None
                if run_sq_skip:
                    col_c, col_d = st.columns(2)
                    with col_c:
                        sq_trigger_col = st.selectbox("Trigger Question (Q_Prev)", all_cols, key='sq_trigger_col_sl')
                    with col_d:
                        sq_trigger_val = st.text_input("Trigger Value (e.g., '1' for 'Yes')", value='1', key='sq_trigger_val_sl')
                
                submitted_sq = st.form_submit_button("Run SQ Checks")
                if submitted_sq and sq_cols:
                    required_stubs = [int(s.strip()) for s in sq_stubs_str.split(',') if s.strip().isdigit()] if sq_stubs_str else None
                    
                    # 1. Run Data Checks & Generate Syntax for Standard Checks (Loops through multiple SQ's)
                    df_validated, new_flags = run_sq_check(df_validated, sq_cols, sq_min, sq_max, required_stubs=required_stubs)
                    sq_syntax = generate_sq_spss_syntax(sq_cols, sq_min, sq_max, required_stubs)
                    st.session_state.spss_syntax_blocks.append(sq_syntax)
                    st.session_state.current_flag_cols.extend(new_flags)
                        
                    st.success(f"SQ Checks applied and detailed SPSS syntax generated for **{len(sq_cols)}** columns.")

                    # 2. Run Skip Logic check if enabled (Loops through multiple SQ's)
                    if run_sq_skip and sq_trigger_col and sq_trigger_val:
                        for col in sq_cols:
                            df_validated, sl_flags = run_skip_logic_check(df_validated, col, sq_trigger_col, sq_trigger_val)
                            sl_syntax = generate_skip_spss_syntax(col, sq_trigger_col, sq_trigger_val)
                            st.session_state.spss_syntax_blocks.append(sl_syntax)
                            st.session_state.current_flag_cols.extend(sl_flags)
                        st.success(f"Skip Logic rule applied to all **{len(sq_cols)}** targets.")
                elif submitted_sq:
                    st.warning("Please select at least one column for SQ Check.")

        st.markdown("---")
        
        # --- Multi-Select Check (MQ) ---
        with st.expander("✅ Multi-Select Check (MQ, Min/Max Count, Exclusive Stub)", expanded=True):
            with st.form("mq_form"):
                mq_cols_default = [c for c in all_cols if c.startswith('Q') and ('_c' in c or '_a' in c)]
                # User selects the entire group of variables
                mq_cols = st.multiselect("Select ALL Multi-Select Columns (The entire group, e.g., Q1_1 to Q1_9)", all_cols, 
                                        default=mq_cols_default, key='mq_cols_select')
                
                st.markdown("**Validation Parameters**")
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    mq_min_count = st.number_input("Minimum Selections Required", min_value=0, value=1, key='mq_min_count')
                with col_b:
                    mq_max_count = st.number_input("Maximum Selections Allowed (0 for no max)", min_value=0, key='mq_max_count')
                with col_c:
                    exclusive_col = st.selectbox("Select Exclusive Stub Column (Optional)", ['None'] + mq_cols, key='mq_exclusive_col')
                
                mq_count_method = st.radio("SPSS Calculation Method", ["SUM", "COUNT"], index=0, help="SUM is generally more robust for 0/1 coded data.")

                st.markdown("---")
                # INTEGRATED OPTIONAL SKIP LOGIC
                run_mq_skip = st.checkbox(f"Add Skip Logic/Piping Check (EoO/EoC)", key='run_mq_skip', help="Applies skip logic check to the **first** column in the set as a representative target.")

                mq_trigger_col = None
                mq_trigger_val = None
                if run_mq_skip and mq_cols:
                    col_d, col_e = st.columns(2)
                    with col_d:
                        mq_trigger_col = st.selectbox("Trigger Question (Q_Prev)", all_cols, key='mq_trigger_col_mq')
                    with col_e:
                        mq_trigger_val = st.text_input("Trigger Value (e.g., '1')", value='1', key='mq_trigger_val_mq')
                        
                submitted_mq = st.form_submit_button("Run Multi-Select Checks")
                if submitted_mq and mq_cols:
                    
                    # 1. Run Data Checks & Generate Syntax for Standard Checks
                    df_validated, new_flags = run_mq_check(
                        df_validated, mq_cols, 
                        min_count=mq_min_count, 
                        max_count=mq_max_count if mq_max_count > 0 else None, 
                        exclusive_stub=exclusive_col if exclusive_col != 'None' else None
                    )
                    mq_syntax, mq_sum_var = generate_mq_spss_syntax(mq_cols, mq_min_count, mq_max_count, exclusive_col, mq_count_method)
                    
                    st.session_state.spss_syntax_blocks.append(mq_syntax)
                    st.session_state.current_flag_cols.extend(new_flags)
                    # Add MQ sum/count variable to flag list so it gets added to the final report/syntax
                    st.session_state.current_flag_cols.append(mq_sum_var) 

                    st.success(f"MQ Checks applied ({mq_count_method} method) and detailed SPSS syntax generated for the group.")

                    # 2. Run Skip Logic check if enabled
                    if run_mq_skip and mq_trigger_col and mq_trigger_val:
                        # Use the first column as the target reference for the skip logic check
                        mq_rep_col = mq_cols[0]
                        df_validated, sl_flags = run_skip_logic_check(df_validated, mq_rep_col, mq_trigger_col, mq_trigger_val)
                        sl_syntax = generate_skip_spss_syntax(mq_rep_col, mq_trigger_col, mq_trigger_val)
                        st.session_state.spss_syntax_blocks.append(sl_syntax)
                        st.session_state.current_flag_cols.extend(sl_flags)
                        st.success(f"Skip Logic rule applied. Flag: **{sl_flags[0]}** (Referencing **{mq_rep_col}**).")
                elif submitted_mq:
                    st.warning("Please select columns for MQ Check.")

        st.markdown("---")

        # --- Ranking Check ---
        with st.expander("✅ Ranking Check (Duplicate Rank, Range)", expanded=False):
            with st.form("ranking_form"):
                rank_cols_default = [c for c in all_cols if c.startswith('Rank_') or c.startswith('R_')]
                # User selects all columns that make up the ranking set
                rank_cols = st.multiselect("Select ALL Ranking Columns (e.g., Rank_1, Rank_2, Rank_3)", all_cols, 
                                        default=rank_cols_default, key='rank_cols_select')
                col_a, col_b = st.columns(2)
                with col_a:
                    rank_min = st.number_input("Minimum Expected Rank Value", min_value=1, value=1, key='rank_min')
                with col_b:
                    rank_max = st.number_input("Maximum Expected Rank Value", min_value=1, value=3, key='rank_max')
                
                st.markdown("---")
                # INTEGRATED OPTIONAL SKIP LOGIC
                run_rank_skip = st.checkbox(f"Add Skip Logic/Piping Check (EoO/EoC)", key='run_rank_skip', disabled=(not rank_cols), help="Applies skip logic check to the **first** column in the set as a representative target.")

                rank_trigger_col = None
                rank_trigger_val = None
                if run_rank_skip and rank_cols:
                    col_c, col_d = st.columns(2)
                    with col_c:
                        rank_trigger_col = st.selectbox("Trigger Question (Q_Prev)", all_cols, key='rank_trigger_col_rank')
                    with col_d:
                        rank_trigger_val = st.text_input("Trigger Value (e.g., '1')", value='1', key='rank_trigger_val_rank')
                
                submitted_rank = st.form_submit_button("Run Ranking Checks")
                if submitted_rank and rank_cols:
                    # 1. Run Data Checks & Generate Syntax for Standard Checks
                    df_validated, new_flags = run_ranking_check(df_validated, rank_cols, min_rank_expected=rank_min, max_rank_expected=rank_max)
                    rank_syntax = generate_ranking_spss_syntax(rank_cols, rank_min, rank_max)
                    st.session_state.spss_syntax_blocks.append(rank_syntax)
                    st.session_state.current_flag_cols.extend(new_flags)

                    st.success(f"Ranking Checks applied and detailed SPSS syntax generated for the set.")

                    # 2. Run Skip Logic check if enabled
                    if run_rank_skip and rank_trigger_col and rank_trigger_val:
                        # Use the first column as the target reference
                        rank_rep_col = rank_cols[0]
                        df_validated, sl_flags = run_skip_logic_check(df_validated, rank_rep_col, rank_trigger_col, rank_trigger_val)
                        sl_syntax = generate_skip_spss_syntax(rank_rep_col, rank_trigger_col, rank_trigger_val)
                        st.session_state.spss_syntax_blocks.append(sl_syntax)
                        st.session_state.current_flag_cols.extend(sl_flags)
                        st.success(f"Skip Logic rule applied. Flag: **{sl_flags[0]}** (Referencing **{rank_rep_col}**).")
                elif submitted_rank:
                    st.warning("Please select columns for Ranking Check.")

        st.markdown("---")

        # --- String Check (Open Ends) ---
        with st.expander("✅ String/Open-End Check (Missing, Junk)", expanded=False):
            with st.form("string_form"):
                string_cols_default = [c for c in all_cols if c.endswith('_TEXT') or c.endswith('_OE')]
                string_cols = st.multiselect("Select String/Open-End Columns (Ctrl/Cmd to select multiple)", all_cols, 
                                        default=string_cols_default, key='string_cols_select')
                string_min_length = st.number_input("Minimum Non-Junk Length (e.g., 5 characters)", min_value=1, value=5, key='string_min_length')
                
                st.markdown("---")
                # INTEGRATED OPTIONAL SKIP LOGIC
                run_string_skip = st.checkbox(f"Add Skip Logic/Piping Check (EoO/EoC)", key='run_string_skip', disabled=(not string_cols), help="Applies the skip logic to ALL selected String variables.")

                string_trigger_col = None
                string_trigger_val = None
                if run_string_skip and string_cols:
                    col_c, col_d = st.columns(2)
                    with col_c:
                        string_trigger_col = st.selectbox("Trigger Question (Q_Prev)", all_cols, key='string_trigger_col_string')
                    with col_d:
                        string_trigger_val = st.text_input("Trigger Value (e.g., '1')", value='1', key='string_trigger_val_string')

                submitted_string = st.form_submit_button("Run String Checks")
                if submitted_string and string_cols:
                    # 1. Run Data Checks & Generate Syntax for Standard Checks
                    df_validated, new_flags = run_string_check(df_validated, string_cols, min_length=string_min_length)
                    string_syntax = generate_string_spss_syntax(string_cols, string_min_length)
                    st.session_state.spss_syntax_blocks.append(string_syntax)
                    st.session_state.current_flag_cols.extend(new_flags)

                    st.success(f"String Checks applied and detailed SPSS syntax generated for **{len(string_cols)}** columns.")

                    # 2. Run Skip Logic check if enabled
                    if run_string_skip and string_trigger_col and string_trigger_val:
                        for col in string_cols:
                            df_validated, sl_flags = run_skip_logic_check(df_validated, col, string_trigger_col, string_trigger_val)
                            sl_syntax = generate_skip_spss_syntax(col, string_trigger_col, string_trigger_val)
                            st.session_state.spss_syntax_blocks.append(sl_syntax)
                            st.session_state.current_flag_cols.extend(sl_flags)
                        st.success(f"Skip Logic rule applied to all **{len(string_cols)}** targets.")
                elif submitted_string:
                    st.warning("Please select columns for String Check.")
            
        st.markdown("---")
        st.header("Step 3: Final Validation Report & Master Syntax")

        # Compile and clean master flag list
        final_flag_cols = sorted(list(set([col for col in st.session_state.current_flag_cols if col in df_validated.columns or col.startswith(FLAG_PREFIX) or col.endswith('_Sum') or col.endswith('_Count')])))
        
        if final_flag_cols:
            
            # --- Generate Master Outputs ---
            master_spss_syntax = generate_master_spss_syntax(st.session_state.spss_syntax_blocks, final_flag_cols)
            excel_report_bytes = generate_excel_report(df_validated, final_flag_cols)
            
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
                    label="⬇️ Download Excel Error Report (.xlsx)",
                    data=excel_report_bytes,
                    file_name="validation_error_summary.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
            st.subheader("Preview of Generated Detailed SPSS Logic")
            preview_syntax = '\n'.join([item for sublist in st.session_state.spss_syntax_blocks for item in sublist])
            st.code(preview_syntax[:800] + "\n\n...(Download the .sps file for the complete detailed syntax)", language='spss')
            
        else:
            st.warning("Please define and run at least one validation check in Step 2 to generate the final report.")
            

    except Exception as e:
        st.error(f"An error occurred during processing. Error: {e}")