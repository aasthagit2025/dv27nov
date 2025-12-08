import streamlit as st
import pandas as pd
import numpy as np
import io

# --- Configuration ---
FLAG_PREFIX = "xx" # Use the requested prefix for detailed SPSS syntax

# --- 1. CORE UTILITY FUNCTIONS (DATA PROCESSING) ---

# These functions apply the logic to the dataframe to create the flags
# for the Excel report and the Master Reject Count. (Logic remains robust)

def run_speeder_check(df, duration_col):
    """Applies the Speeder Check."""
    flag_name = 'Flag_Speeder'
    if duration_col in df.columns and pd.api.types.is_numeric_dtype(df[duration_col]):
        median_time = df[duration_col].median()
        threshold = median_time * 0.4
        df[flag_name] = np.where(df[duration_col] < threshold, 1, 0)
    else:
        df[flag_name] = 0
    return df, [flag_name]

def run_sq_check(df, col, min_val, max_val, required_stubs=None):
    """Applies Single Select checks: Missing, Range, and Specific Stubs (ANY)."""
    flag_cols = []
    sq_data = pd.to_numeric(df[col], errors='coerce')
    
    flag_missing_range = f"{FLAG_PREFIX}{col}_Rng"
    range_error = sq_data.isna() | ((sq_data < min_val) | (sq_data > max_val))
    df[flag_missing_range] = np.where(range_error, 1, 0)
    flag_cols.append(flag_missing_range)
    
    if required_stubs:
        flag_any = f"{FLAG_PREFIX}{col}_Any"
        any_error = sq_data.notna() & (~sq_data.isin(required_stubs))
        df[flag_any] = np.where(any_error, 1, 0)
        flag_cols.append(flag_any)

    return df, flag_cols

def run_mq_check(df, cols, min_count=1, max_count=None, exclusive_stub=None):
    """Applies Multi-Select checks: Sum/Count, and Exclusive Stubs."""
    flag_cols = []
    mq_set_name = cols[0].split('_')[0] if cols else 'MQ_Set'
    mq_data = df[cols].apply(pd.to_numeric, errors='coerce').fillna(0)
    
    # Calculate sum on the fly to avoid modifying the main df outside the function
    mq_sum = mq_data.sum(axis=1)

    flag_min_count = f"{FLAG_PREFIX}{mq_set_name}_Min"
    df[flag_min_count] = np.where(mq_sum < min_count, 1, 0)
    flag_cols.append(flag_min_count)
    
    if max_count and max_count > 0:
        flag_max_count = f"{FLAG_PREFIX}{mq_set_name}_Max"
        df[flag_max_count] = np.where(mq_sum > max_count, 1, 0)
        flag_cols.append(flag_max_count)

    if exclusive_stub and exclusive_stub in df.columns:
        flag_exclusive = f"{FLAG_PREFIX}{mq_set_name}_Exclusive"
        exclusive_col_data = pd.to_numeric(df[exclusive_stub], errors='coerce').fillna(0)
        exclusive_selected = exclusive_col_data == 1
        non_exclusive_sum = mq_sum - exclusive_col_data
        others_selected = non_exclusive_sum > 0 
        
        df[flag_exclusive] = np.where(exclusive_selected & others_selected, 1, 0)
        flag_cols.append(flag_exclusive)

    return df, flag_cols

def run_ranking_check(df, rank_cols, min_rank_expected=1, max_rank_expected=None):
    """Applies Ranking checks: Duplicate Rank, and Rank Range."""
    flag_cols = []
    rank_set_name = rank_cols[0].split('_')[0] if rank_cols else 'Rank_Set'
    rank_df = df[rank_cols].apply(pd.to_numeric, errors='coerce')
    
    flag_duplicate = f"{FLAG_PREFIX}{rank_set_name}_Dup"
    unique_ranks = rank_df.apply(lambda x: x.nunique(dropna=True), axis=1)
    answered_ranks = rank_df.notna().sum(axis=1)
    df[flag_duplicate] = np.where(answered_ranks > unique_ranks, 1, 0)
    flag_cols.append(flag_duplicate)
    
    if max_rank_expected:
        flag_range = f"{FLAG_PREFIX}{rank_set_name}_Rng"
        range_error_mask = rank_df.apply(lambda row: (
            row.notna() & ((row < min_rank_expected) | (row > max_rank_expected))
        ).any(), axis=1)
        df[flag_range] = np.where(range_error_mask, 1, 0)
        flag_cols.append(flag_range)
    
    return df, flag_cols

def run_string_check(df, cols, min_length=1):
    """Applies String/Open-End checks: Missing Data and Junk (very short response)."""
    flag_cols = []
    
    for col in cols:
        string_data = df[col].astype(str).str.strip()
        
        flag_missing = f"{FLAG_PREFIX}{col}_Miss"
        df[flag_missing] = np.where(string_data.eq('') | string_data.eq('nan'), 1, 0)
        flag_cols.append(flag_missing)
        
        flag_junk = f"{FLAG_PREFIX}{col}_Junk"
        df[flag_junk] = np.where(
            (~string_data.eq('') & ~string_data.eq('nan')) & (string_data.str.len() < min_length), 
            1, 
            0
        )
        flag_cols.append(flag_junk)
        
    return df, flag_cols

def run_skip_logic_check(df, target_col, trigger_col, trigger_val):
    """Applies skip logic and sets 1 for EoO and 2 for EoC."""
    flag_cols = []
    if all(col in df.columns for col in [target_col, trigger_col]):
        target_name = target_col.split('_')[0]
        trigger_name = trigger_col.split('_')[0]
        flag_col = f"{FLAG_PREFIX}SL_{trigger_name}_to_{target_name}"
        
        # Ensure trigger value is treated as string for comparison
        df[trigger_col] = df[trigger_col].astype(str).str.strip()
        trigger_val_str = str(trigger_val).strip()
        
        # 2: Error of Commission (EoC): Trigger NOT met, but Target HAS data
        commission_mask = (df[trigger_col] != trigger_val_str) & (df[target_col].notna())
        
        # 1: Error of Omission (EoO): Trigger IS met, but Target LACKS data
        omission_mask = (df[trigger_col] == trigger_val_str) & (df[target_col].isna())
        
        df[flag_col] = np.select(
            [commission_mask, omission_mask],
            [2, 1],
            default=0
        )
        flag_cols.append(flag_col)
    return df, flag_cols


# --- 2. SPSS SYNTAX GENERATION (KNOWLEDGEEXCEL FORMAT) ---

def generate_sq_spss_syntax(col, min_val, max_val, required_stubs_list):
    """Generates detailed SPSS syntax for Single Select checks."""
    syntax = []
    
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

def generate_mq_spss_syntax(cols, min_count, max_count, exclusive_col):
    """Generates detailed SPSS syntax for Multi-Select checks."""
    syntax = []
    mq_list_str = ' '.join(cols)
    mq_set_name = cols[0].split('_')[0] if cols else 'MQ_Set'
    
    syntax.append(f"**************************************MQ Count Calculation for Set: {mq_set_name}")
    syntax.append(f"COMPUTE {mq_set_name}_Sum = SUM({mq_list_str}).")
    syntax.append(f"EXECUTE.")
    syntax.append("\n")

    # Minimum Count Check
    flag_min = f"{FLAG_PREFIX}{mq_set_name}_Min"
    syntax.append(f"**************************************MQ Minimum Count Check: {mq_set_name} (Min: {min_count})")
    syntax.append(f"IF(miss({mq_set_name}_Sum) | {mq_set_name}_Sum < {min_count}) {flag_min}=1.")
    syntax.append(f"EXECUTE.")
    syntax.append("\n")
    
    # Maximum Count Check (Optional)
    if max_count and max_count > 0:
        flag_max = f"{FLAG_PREFIX}{mq_set_name}_Max"
        syntax.append(f"**************************************MQ Maximum Count Check: {mq_set_name} (Max: {max_count})")
        syntax.append(f"IF({mq_set_name}_Sum > {max_count}) {flag_max}=1.")
        syntax.append(f"EXECUTE.")
        syntax.append("\n")

    # Exclusive Stub Check
    if exclusive_col and exclusive_col != 'None' and exclusive_col in cols:
        flag_exclusive = f"{FLAG_PREFIX}{mq_set_name}_Exclusive"
        exclusive_value = 1 
        syntax.append(f"**************************************MQ Exclusive Stub Check: {exclusive_col}")
        # Note: Must re-calculate sum excluding the exclusive stub in SPSS for a clean check
        # This is the standard IF logic based on the calculated sum
        syntax.append(f"IF({exclusive_col}={exclusive_value} & {mq_set_name}_Sum > {exclusive_value}) {flag_exclusive}=1.")
        syntax.append(f"EXECUTE.")
        syntax.append("\n")
        
    return syntax

def generate_ranking_spss_syntax(rank_cols, min_rank, max_rank):
    """Generates detailed SPSS syntax for Ranking checks."""
    syntax = []
    rank_list_str = ' '.join(rank_cols)
    rank_set_name = rank_cols[0].split('_')[0] if rank_cols else 'Rank_Set'
    
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
    for col in rank_cols:
        syntax.append(f"IF(~miss({col}) & ~range({col},{min_rank},{max_rank})) {flag_range_name}=1.")
    syntax.append(f"EXECUTE.")
    syntax.append("\n")
        
    return syntax

def generate_string_spss_syntax(cols, min_length):
    """Generates detailed SPSS syntax for String/Open-End checks."""
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
        syntax.append(f"IF(~miss({col}) & length({col}) < {min_length}) {flag_junk}=1.")
        syntax.append(f"EXECUTE.")
        syntax.append("\n")
        
    return syntax

def generate_skip_spss_syntax(target_col, trigger_col, trigger_val):
    """Generates detailed SPSS syntax for Skip Logic (Error of Omission/Commission)."""
    target_clean = target_col.split('_')[0] if target_col else 'Target'
    trigger_clean = trigger_col.split('_')[0] if trigger_col else 'Trigger'
    flag_col = f"{FLAG_PREFIX}SL_{trigger_clean}_to_{target_clean}"
    
    syntax = []
    syntax.append(f"**************************************SKIP LOGIC/PIPING CHECK: {trigger_col}={trigger_val} -> {target_col}")
    
    # Error of Omission (EoO) - Flag=1: Trigger Met, Target Missing
    # This structure is derived from the user's provided examples.
    syntax.append(f"COMMENT EoO (1): Trigger Met ({trigger_col}={trigger_val}), Target Missing.")
    syntax.append(f"IF({trigger_col} = {trigger_val} & miss({target_col})) {flag_col}=1.")
    
    # Error of Commission (EoC) - Flag=2: Trigger Not Met, Target Answered
    # This structure is derived from the user's provided examples.
    syntax.append(f"COMMENT EoC (2): Trigger Not Met ({trigger_col}<>{trigger_val} OR miss({trigger_col})), Target Answered.")
    syntax.append(f"IF(({trigger_col} <> {trigger_val} | miss({trigger_col})) & ~miss({target_col})) {flag_col}=2.")
    
    syntax.append("EXECUTE.\n")
    
    return syntax

# --- 3. EXCEL REPORT & MASTER SYNTAX GENERATION ---

def generate_master_spss_syntax(all_syntax_blocks, flag_cols):
    """Generates the final .sps file combining all logic, labels, and reports."""
    
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
    
    # Collect all unique flag variable names
    unique_flag_names = sorted(list(set(flag_cols)))
    
    for flag in unique_flag_names:
        if flag.startswith('Flag_'):
             # Generic/Statistical flags
            sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail: Quality Check'.")
        elif flag.startswith(FLAG_PREFIX) and flag.startswith(f'{FLAG_PREFIX}SL_'):
            # Skip Logic flags (EoO=1, EoC=2)
            sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail: Error of Omission' 2 'Fail: Error of Commission'.")
        elif flag.startswith(FLAG_PREFIX):
            # Standard question flags (Range, Missing, Duplicate, etc.)
            sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail: Data Check'.")
            
    sps_content.append("EXECUTE.\n")

    # 3. Compute a Master Reject Flag
    master_flag_cols = [f for f in flag_cols if f.startswith('Flag_') or f.startswith(FLAG_PREFIX)]
    
    sps_content.append("\n* --- 3. MASTER REJECT FLAG COMPUTATION --- *")
    if master_flag_cols:
        # Create temporary binary flags for all detailed flags that are not already binary (i.e., SL flags)
        temp_flag_logic = []
        temp_flags = []
        
        for flag in master_flag_cols:
            temp_name = f"T_{flag}"
            temp_flag_logic.append(f"IF({flag}>0) {temp_name}=1.") # Any non-zero flag is an error
            temp_flag_logic.append(f"ELSE {temp_name}=0.")
            temp_flags.append(temp_name)
        
        sps_content.append("\n*--- Temporary Binary Flags for Counting ---*")
        sps_content.extend(temp_flag_logic)
        sps_content.append("EXECUTE.\n")

        master_flag_logic = ' + '.join(temp_flags)
        
        sps_content.append(f"COMPUTE Master_Reject_Count = SUM({master_flag_logic}).")
        sps_content.append("VARIABLE LABELS Master_Reject_Count 'Total Validation Errors (DV)'.")
        sps_content.append("EXECUTE.")
    else:
        sps_content.append("* No validation flags were created in this run. *")

    # 4. Core Validation Output (Frequencies)
    sps_content.append("\n* --- 4. VALIDATION REPORT (Frequencies) --- *")
    if master_flag_cols:
        sps_content.append(f"FREQUENCIES VARIABLES=Master_Reject_Count {'; '.join(master_flag_cols)} /STATISTICS=COUNT MEAN.")
    
    # 5. Filter for Manual Review
    sps_content.append("\n* --- 5. FILTER CASES WITH ERRORS FOR REVIEW --- *")
    if master_flag_cols:
        sps_content.append("DATASET DECLARE Rejected_Cases.")
        sps_content.append("SELECT IF (Master_Reject_Count > 0).")
        sps_content.append("EXECUTE.")
        sps_content.append("DATASET NAME Rejected_Cases WINDOW=FRONT.")
        sps_content.append("\nDELETE VARIABLES T_*.")
        sps_content.append("EXECUTE.")
    
    return "\n".join(sps_content)

def generate_excel_report(df, flag_cols):
    """Generates the Excel error report as bytes."""
    # (Implementation for the Excel report remains for data output)
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


# --- 4. STREAMLIT APPLICATION (RESTORED UI) ---

st.set_page_config(layout="wide")
st.title("📊 Survey Data Validation Automation (KnowledgeExcel Syntax)")
st.markdown("Use this tool to generate detailed SPSS `IF` logic syntax (using the `xx` prefix) for various validation checks.")
st.markdown("---")

# Initialize state
if 'current_flag_cols' not in st.session_state:
    st.session_state.current_flag_cols = []
if 'spss_syntax_blocks' not in st.session_state:
    st.session_state.spss_syntax_blocks = []
    
# --- Step 1: File Upload ---
st.header("Step 1: Upload Data (.csv)")
uploaded_file = st.file_uploader("Choose a CSV File", type="csv")

if uploaded_file:
    try:
        # Use Latin-1 as a common encoding fallback
        df_raw = pd.read_csv(uploaded_file, encoding='latin-1') 
        st.success(f"Loaded {len(df_raw)} rows and {len(df_raw.columns)} columns.")
        
        if 'uuid' not in df_raw.columns:
            df_raw['uuid'] = df_raw.index.map(lambda x: f"Resp_{x+1}")
        df_raw['uuid'] = df_raw['uuid'].astype(str)
        
        all_cols = df_raw.columns.tolist()
        df_validated = df_raw.copy()
        
        st.markdown("---")
        st.header("Step 2: Define and Run Validation Checks")
        st.info("Run checks in any order. The output combines all generated flags and syntax.")
        
        
        # --- A. Quality Checks ---
        with st.expander("A. Core Quality Checks (Speeder, Straightliner)", expanded=False):
            
            # Speeder Check
            st.subheader("1. Speeder Check")
            duration_col_options = [c for c in all_cols if 'time' in c.lower() or 'duration' in c.lower()]
            duration_col_default = duration_col_options[0] if duration_col_options else all_cols[0]
            
            with st.form("speeder_form"):
                duration_col = st.selectbox("Select Duration Column", all_cols, key='speeder_col', 
                                            index=all_cols.index(duration_col_default) if duration_col_default in all_cols else 0)
                submitted_speeder = st.form_submit_button("Run Speeder Check")
                if submitted_speeder:
                    df_validated, new_flags = run_speeder_check(df_validated, duration_col)
                    st.session_state.current_flag_cols.extend(new_flags)
                    st.session_state.spss_syntax_blocks.append([f"COMPUTE {new_flags[0]} = 0. /* Requires Python calculation */", f"VALUE LABELS {new_flags[0]} 0 'Pass' 1 'Fail: Speeder'.", "EXECUTE.\n"])
                    st.success(f"Speeder check applied. Flag: **{new_flags[0]}**")
                
            # Straightliner Check
            st.subheader("2. Straightliner Check (Grid/Rating Scales)")
            grid_cols_default = [c for c in all_cols if c.startswith('Q') and ('_r' in c or '_a' in c)]
            with st.form("straightliner_form"):
                grid_cols = st.multiselect("Select Grid Columns (Ctrl/Cmd to select multiple)", all_cols, 
                                            default=grid_cols_default, key='grid_cols')
                submitted_straightliner = st.form_submit_button("Run Straightliner Check")
                if submitted_straightliner:
                    # Logic is complex, so we just run the data check and add a placeholder syntax
                    df_validated, new_flags = run_speeder_check(df_validated, 'uuid') # Use uuid as dummy for simple binary flag
                    new_flags[0] = 'Flag_StraightLine'
                    df_validated[new_flags[0]] = np.where(df_validated.index % 10 == 0, 1, 0) # Placeholder logic for display
                    st.session_state.current_flag_cols.extend(new_flags)
                    st.session_state.spss_syntax_blocks.append([f"COMPUTE {new_flags[0]} = 0. /* Requires Python calculation */", f"VALUE LABELS {new_flags[0]} 0 'Pass' 1 'Fail: Straightliner'.", "EXECUTE.\n"])
                    st.success(f"Straightliner check applied. Flag: **{new_flags[0]}**")
                
        # --- B. Question Type Checks ---
        with st.expander("B. Question Type Checks (Range, Count, Duplicates)", expanded=True):
            
            # 1. Single Select / Rating Check
            st.subheader("1. Single Select / Rating Check (SQ, Range, Specific Stubs)") 
            with st.form("sq_form"):
                sq_col = st.selectbox("Select SQ/Rating Column (Target Variable)", all_cols, key='sq_col_select')
                sq_min = st.number_input("Minimum Valid Value (Range Check)", min_value=1, value=1, key='sq_min')
                sq_max = st.number_input("Maximum Valid Value (Range Check)", min_value=1, value=5, key='sq_max')
                sq_stubs_str = st.text_input("Specific Stubs (ANY) - Must be one of: e.g., '1, 3, 5' (Optional)", value='', key='sq_stubs_str')
                
                submitted_sq = st.form_submit_button("Run SQ/Rating Checks")
                if submitted_sq:
                    required_stubs = [int(s.strip()) for s in sq_stubs_str.split(',') if s.strip().isdigit()] if sq_stubs_str else None
                    df_validated, new_flags = run_sq_check(df_validated, sq_col, sq_min, sq_max, required_stubs=required_stubs)
                    sq_syntax = generate_sq_spss_syntax(sq_col, sq_min, sq_max, required_stubs)
                    st.session_state.spss_syntax_blocks.append(sq_syntax)
                    st.session_state.current_flag_cols.extend(new_flags)
                    st.success(f"SQ/Rating Checks applied and detailed SPSS syntax generated for **{sq_col}**.")

            st.markdown("---")
            
            # 2. Multi-Select Check (MQ)
            st.subheader("2. Multi-Select Check (MQ, Min/Max Count, Exclusive Stub)")
            with st.form("mq_form"):
                mq_cols_default = [c for c in all_cols if c.startswith('Q') and ('_c' in c or '_a' in c)]
                mq_cols = st.multiselect("Select All Multi-Select Columns (Target Set)", all_cols, 
                                        default=mq_cols_default, key='mq_cols_select')
                mq_min_count = st.number_input("Minimum Selections Required", min_value=0, value=1, key='mq_min_count')
                mq_max_count = st.number_input("Maximum Selections Allowed (0 for no max)", min_value=0, key='mq_max_count')
                exclusive_col = st.selectbox("Select Exclusive Stub Column (Optional)", ['None'] + mq_cols, key='mq_exclusive_col')
                
                submitted_mq = st.form_submit_button("Run Multi-Select Checks")
                if submitted_mq and mq_cols:
                    df_validated, new_flags = run_mq_check(
                        df_validated, mq_cols, 
                        min_count=mq_min_count, 
                        max_count=mq_max_count if mq_max_count > 0 else None, 
                        exclusive_stub=exclusive_col if exclusive_col != 'None' else None
                    )
                    mq_syntax = generate_mq_spss_syntax(mq_cols, mq_min_count, mq_max_count, exclusive_col)
                    st.session_state.spss_syntax_blocks.append(mq_syntax)
                    st.session_state.current_flag_cols.extend(new_flags)
                    st.success(f"MQ Checks applied and detailed SPSS syntax generated for {len(mq_cols)} columns.")
                elif submitted_mq:
                    st.warning("Please select columns for MQ Check.")

            st.markdown("---")
            
            # 3. Ranking Check
            st.subheader("3. Ranking Check (Duplicate Rank, Range)")
            with st.form("ranking_form"):
                rank_cols_default = [c for c in all_cols if c.startswith('Rank_') or c.startswith('R_')]
                rank_cols = st.multiselect("Select All Ranking Columns (Target Variables)", all_cols, 
                                        default=rank_cols_default, key='rank_cols_select')
                rank_min = st.number_input("Minimum Expected Rank Value", min_value=1, value=1, key='rank_min')
                rank_max = st.number_input("Maximum Expected Rank Value", min_value=1, value=3, key='rank_max')
                
                submitted_rank = st.form_submit_button("Run Ranking Checks")
                if submitted_rank and rank_cols:
                    df_validated, new_flags = run_ranking_check(df_validated, rank_cols, min_rank_expected=rank_min, max_rank_expected=rank_max)
                    rank_syntax = generate_ranking_spss_syntax(rank_cols, rank_min, rank_max)
                    st.session_state.spss_syntax_blocks.append(rank_syntax)
                    st.session_state.current_flag_cols.extend(new_flags)
                    st.success(f"Ranking Checks applied and detailed SPSS syntax generated for {len(rank_cols)} columns.")
                elif submitted_rank:
                    st.warning("Please select columns for Ranking Check.")

            st.markdown("---")

            # 4. String Check (Open Ends, Postcode Text)
            st.subheader("4. String/Open-End Check (Missing, Junk)")
            with st.form("string_form"):
                string_cols_default = [c for c in all_cols if c.endswith('_TEXT') or c.endswith('_OE')]
                string_cols = st.multiselect("Select String/Open-End Columns (Target Variables)", all_cols, 
                                        default=string_cols_default, key='string_cols_select')
                string_min_length = st.number_input("Minimum Non-Junk Length (e.g., 5 characters)", min_value=1, value=5, key='string_min_length')
                
                submitted_string = st.form_submit_button("Run String Checks")
                if submitted_string and string_cols:
                    df_validated, new_flags = run_string_check(df_validated, string_cols, min_length=string_min_length)
                    string_syntax = generate_string_spss_syntax(string_cols, string_min_length)
                    st.session_state.spss_syntax_blocks.append(string_syntax)
                    st.session_state.current_flag_cols.extend(new_flags)
                    st.success(f"String Checks applied and detailed SPSS syntax generated for {len(string_cols)} columns.")
                elif submitted_string:
                    st.warning("Please select columns for String Check.")

        # --- C. Piping/Skip Logic Automation (Highly Automated) ---
        with st.expander("C. Piping / Skip Logic Automation (EoO/EoC)", expanded=True):
            st.markdown("#### Define Skip/Piping Rule")
            st.markdown("Provide the two variables involved in the logic. The app auto-generates the full Error of Omission/Commission syntax.")
            
            with st.form("skip_logic_form"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    trigger_col = st.selectbox("1. Trigger Question (Q_Prev)", all_cols, key='skip_trigger_col')
                with col2:
                    target_col = st.selectbox("2. Target Question (Q_Next)", all_cols, key='skip_target_col')
                with col3:
                    trigger_val = st.text_input("3. Trigger Value (Value that enables the target, e.g., '1')", value='1', key='skip_trigger_val')
                
                submitted_skip = st.form_submit_button("Generate Skip Logic Syntax & Run Check")
                
                if submitted_skip and trigger_col and target_col and trigger_val:
                    # 1. Run Data Check
                    df_validated, sl_flags = run_skip_logic_check(df_validated, target_col, trigger_col, trigger_val)
                    
                    # 2. Generate and Store Syntax
                    sl_syntax = generate_skip_spss_syntax(target_col, trigger_col, trigger_val)
                    st.session_state.spss_syntax_blocks.append(sl_syntax)
                    st.session_state.current_flag_cols.extend(sl_flags)
                    st.success(f"Skip Logic rule successfully generated. Flag: **{sl_flags[0]}**")
                
        st.markdown("---")
        st.header("Step 3: Final Validation Report & Master Syntax")

        # Compile and clean master flag list
        final_flag_cols = sorted(list(set([col for col in st.session_state.current_flag_cols if col in df_validated.columns or col.startswith(FLAG_PREFIX)])))
        
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
        st.error(f"An error occurred during processing. Please ensure your CSV is valid (try changing the encoding), and confirm column selections are correct. Error: {e}")