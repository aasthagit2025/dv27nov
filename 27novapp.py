import streamlit as st
import pandas as pd
import numpy as np
import io

# --- 1. CONFIGURATION: CORE UTILITY FUNCTIONS (EXPANDED) ---

def run_speeder_check(df, duration_col):
    """Applies the Speeder Check."""
    flag_cols = []
    if duration_col in df.columns and pd.api.types.is_numeric_dtype(df[duration_col]):
        median_time = df[duration_col].median()
        threshold = median_time * 0.4
        df['Flag_Speeder'] = np.where(df[duration_col] < threshold, 1, 0)
        flag_cols.append('Flag_Speeder')
    else:
        # Create a zero-flag column for consistency if the input column is missing/invalid
        df['Flag_Speeder'] = 0
        flag_cols.append('Flag_Speeder')
    return df, flag_cols

def run_straightliner_check(df, grid_cols):
    """Applies the Straightliner Check."""
    flag_cols = []
    
    # Ensure all columns exist and there is more than one column
    valid_cols = [col for col in grid_cols if col in df.columns]
    if len(valid_cols) > 1:
        # Calculate standard deviation across the grid columns for each respondent
        grid_data = df[valid_cols].apply(pd.to_numeric, errors='coerce')
        df['grid_std'] = grid_data.std(axis=1)
        
        # Flag 1 if the standard deviation is 0 (all answers are the same) and they are not all missing
        answered_count = grid_data.notna().sum(axis=1)
        # Use a soft threshold (e.g., 80%) for straightlining detection
        same_answers = (df['grid_std'] == 0) & (answered_count >= len(valid_cols) * 0.8)

        df['Flag_StraightLine'] = np.where(same_answers, 1, 0)
        flag_cols.append('Flag_StraightLine')
    else:
        df['Flag_StraightLine'] = 0
        flag_cols.append('Flag_StraightLine')
    return df, flag_cols

def run_skip_logic_check(df, target_col, trigger_col, trigger_val):
    """Applies a single Skip Logic rule (Error of Commission/Omission)."""
    if all(col in df.columns for col in [target_col, trigger_col]):
        flag_col = f"Flag_SL_{trigger_col}_to_{target_col}"
        
        # Convert trigger column to string for comparison (robustness)
        df[trigger_col] = df[trigger_col].astype(str).str.strip()
        trigger_val_str = str(trigger_val).strip()
        
        # Error of Commission (Shouldn't have answered, but did) - Trigger NOT met, Target HAS data
        commission_mask = (df[trigger_col] != trigger_val_str) & (df[target_col].notna())
        
        # Error of Omission (Should have answered, but didn't) - Trigger IS met, Target LACKS data
        omission_mask = (df[trigger_col] == trigger_val_str) & (df[target_col].isna())
        
        df[flag_col] = np.where(commission_mask | omission_mask, 1, 0)
        return df, [flag_col]
    return df, []

def run_sq_check(df, col, min_val, max_val, required_stubs=None):
    """
    Applies Single Select checks: Missing, Range, and Specific Stubs (ANY).
    Covers SQ, Rating/Piping, and Postcode range/missing checks.
    """
    flag_cols = []
    
    # Ensure the column is numeric for range checking (coercing errors for robustness)
    sq_data = pd.to_numeric(df[col], errors='coerce')
    
    # 1. Missing Values Check
    flag_missing = f"Flag_SQ_Missing_{col}"
    df[flag_missing] = np.where(sq_data.isna(), 1, 0)
    flag_cols.append(flag_missing)

    # 2. Range Check
    flag_range = f"Flag_SQ_Range_{col}"
    # Flag if value is NOT missing AND is outside the min/max range
    range_error = sq_data.notna() & ((sq_data < min_val) | (sq_data > max_val))
    df[flag_range] = np.where(range_error, 1, 0)
    flag_cols.append(flag_range)
    
    # 3. Specific Stubs (ANY check - data should only be in required_stubs)
    if required_stubs and required_stubs != 'None':
        flag_any = f"Flag_SQ_Stubs_{col}"
        # Flag where the value is NOT in the list of required stubs, but is also NOT missing
        any_error = sq_data.notna() & (~sq_data.isin(required_stubs))
        df[flag_any] = np.where(any_error, 1, 0)
        flag_cols.append(flag_any)

    return df, flag_cols

def run_mq_check(df, cols, min_count=1, max_count=None, exclusive_stub=None):
    """
    Applies Multi-Select checks: Sum/Count, and Exclusive Stubs.
    Assumes binary coded columns (1=Selected, 0/NaN=Not Selected).
    """
    flag_cols = []
    
    # Coerce columns to numeric (e.g., if loaded as string '1'/'0')
    mq_data = df[cols].apply(pd.to_numeric, errors='coerce').fillna(0)

    # Calculate the sum of selections for each respondent
    df['MQ_Sum'] = mq_data.sum(axis=1)

    # 1. Minimum Data Availability (Count Check)
    flag_min_count = f"Flag_MQ_MinCount_{min_count}"
    df[flag_min_count] = np.where(df['MQ_Sum'] < min_count, 1, 0)
    flag_cols.append(flag_min_count)
    
    # 2. Maximum Count Check (Optional)
    if max_count:
        flag_max_count = f"Flag_MQ_MaxCount_{max_count}"
        df[flag_max_count] = np.where(df['MQ_Sum'] > max_count, 1, 0)
        flag_cols.append(flag_max_count)

    # 3. "Value of Exclusive" Check
    if exclusive_stub and exclusive_stub in df.columns and exclusive_stub != 'None':
        # Exclusive stub selected (value=1) but other stubs are also selected (> 1 sum)
        flag_exclusive = f"Flag_MQ_Exclusive_{exclusive_stub}"
        exclusive_col_data = pd.to_numeric(df[exclusive_stub], errors='coerce').fillna(0)
        
        exclusive_selected = exclusive_col_data == 1
        # Sum of *all* stubs excluding the exclusive one
        non_exclusive_sum = df['MQ_Sum'] - exclusive_col_data
        others_selected = non_exclusive_sum > 0 
        
        # Flag if Exclusive is selected AND others are selected
        df[flag_exclusive] = np.where(exclusive_selected & others_selected, 1, 0)
        flag_cols.append(flag_exclusive)
        
    # Drop the temporary sum column
    df.drop(columns=['MQ_Sum'], inplace=True, errors='ignore')

    return df, flag_cols

def run_ranking_check(df, rank_cols, min_rank_expected=1, max_rank_expected=None):
    """
    Applies Ranking checks: Missing, Duplicate Rank, and Rank Range.
    """
    flag_cols = []
    
    # Coerce columns to numeric
    rank_df = df[rank_cols].apply(pd.to_numeric, errors='coerce')
    
    # 1. Duplicate Rank Check
    flag_duplicate = f"Flag_Rank_Duplicate"
    # Find number of unique, non-missing values in the rank columns for each row
    unique_ranks = rank_df.apply(lambda x: x.nunique(dropna=True), axis=1)
    answered_ranks = rank_df.notna().sum(axis=1)
    # Flag if the count of answered ranks is greater than the count of unique ranks
    df[flag_duplicate] = np.where(answered_ranks > unique_ranks, 1, 0)
    flag_cols.append(flag_duplicate)
    
    # 2. Missing/Range Condition (Check if the ranks are within the required range)
    if max_rank_expected:
        flag_range = f"Flag_Rank_Range"
        
        # Check if any non-missing rank is outside the min/max range
        range_error_mask = rank_df.apply(lambda row: (
            (row.notna() & ((row < min_rank_expected) | (row > max_rank_expected))).any()
        ), axis=1)
        
        df[flag_range] = np.where(range_error_mask, 1, 0)
        flag_cols.append(flag_range)
    
    return df, flag_cols

def run_string_check(df, cols, min_length=1):
    """
    Applies String/Open-End checks: Missing Data and Junk (very short response).
    """
    flag_cols = []
    
    for col in cols:
        # Convert to string and strip whitespace for robust checking
        string_data = df[col].astype(str).str.strip()
        
        # 1. Missing Data Check
        flag_missing = f"Flag_String_Missing_{col}"
        # Flag if the string is empty or 'nan' after cleaning
        df[flag_missing] = np.where(string_data.eq('') | string_data.eq('nan'), 1, 0)
        flag_cols.append(flag_missing)
        
        # 2. Junk Check (Flagging responses shorter than min_length, but NOT missing)
        flag_junk = f"Flag_String_Junk_{col}"
        df[flag_junk] = np.where(
            (string_data.str.len() > 0) & (string_data.str.len() < min_length) & (~string_data.eq('nan')), 
            1, 
            0
        )
        flag_cols.append(flag_junk)
        
    return df, flag_cols


# --- 2. SPSS SYNTAX GENERATION (USER-DRIVEN) ---

def generate_spss_syntax_by_type(selected_type, selected_cols):
    """Generates targeted SPSS syntax based on user selection."""
    
    sps_content = []
    
    if selected_type == "Single Select (Categorical)":
        sps_content.append(f"* --- Syntax for Single Select Variables ({len(selected_cols)} columns) --- *")
        for col in selected_cols:
            sps_content.append(f"VALUE LABELS {col} 1 'Option 1' 2 'Option 2' 99 'Missing'.")
            sps_content.append(f"MISSING VALUES {col} (99).")
        sps_content.append("EXECUTE.")

    elif selected_type == "Multi-Select (Select All That Apply)":
        sps_content.append(f"* --- Syntax for Multi-Select Variables ({len(selected_cols)} columns) --- *")
        sps_content.append("* Define the Multiple Response Set for analysis *")
        sps_content.append("MRSETS")
        sps_content.append(f" /MCGROUP NAME=$MSQ_Example COMPONENTS={'; '.join(selected_cols)}")
        sps_content.append(" /LABEL='Example Multi-Select Question'")
        sps_content.append(" /VALUE=1.")
        sps_content.append("EXECUTE.")

    elif selected_type == "Grid/Scale Variables":
        sps_content.append(f"* --- Syntax for Grid/Scale Variables ({len(selected_cols)} columns) --- *")
        sps_content.append("* This sets standard scale labels and missing values for a Likert Scale. *")
        sps_content.append(f"VALUE LABELS {'; '.join(selected_cols)}")
        sps_content.append("  1 'Strongly Disagree'")
        sps_content.append("  5 'Strongly Agree'")
        sps_content.append("  -99 'Refused'.")
        sps_content.append(f"MISSING VALUES {'; '.join(selected_cols)} (-99).")
        sps_content.append("EXECUTE.")

    elif selected_type == "Data Type Recode (Numeric/String)":
        sps_content.append(f"* --- Syntax for Recoding String to Numeric ({len(selected_cols)} columns) --- *")
        for col in selected_cols:
            sps_content.append(f"RECODE {col} ('Yes'=1) ('No'=0) ('Refuse'=-99) INTO {col}_Numeric.")
            sps_content.append(f"VARIABLE LABELS {col}_Numeric '{col} (Recoded Numeric)'.")
        sps_content.append("EXECUTE.")

    return "\n".join(sps_content)

# --- 3. EXCEL REPORT & MAIN SYNTAX GENERATION ---

def generate_master_spss_syntax(flag_cols):
    """Generates the master .sps file with final flag definitions and reports."""
    
    sps_content = []
    
    sps_content.append(f"*{'='*60}*")
    sps_content.append(f"* PYTHON-GENERATED DATA VALIDATION FLAGS & REPORT *")
    sps_content.append(f"*{'='*60}*\n")
    sps_content.append("DATASET ACTIVATE ALL.")
    
    # Define the new flag variables
    sps_content.append("\n* --- 1. FLAG VARIABLE DEFINITION --- *")
    for flag in flag_cols:
        sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail'.")
    
    # Compute a Master Reject Flag
    sps_content.append("\n* --- 2. MASTER REJECT FLAG --- *")
    if flag_cols:
        # Sum of all flags to get total errors per respondent
        master_flag_logic = ' + '.join(flag_cols)
        sps_content.append(f"COMPUTE Master_Reject_Count = SUM({master_flag_logic}).")
        sps_content.append("VARIABLE LABELS Master_Reject_Count 'Total Validation Errors (DV)'.")
        sps_content.append("EXECUTE.")
    else:
        sps_content.append("* No validation flags were created in this run. *")

    # Core Validation Output (Frequencies)
    sps_content.append("\n* --- 3. VALIDATION REPORT (Frequencies) --- *")
    sps_content.append("* Run Frequencies on all flags to get summary counts of errors *")
    if flag_cols:
        sps_content.append(f"FREQUENCIES VARIABLES={'; '.join(flag_cols)} /STATISTICS=COUNT MEAN.")
    
    # Filter for Manual Review
    sps_content.append("\n* --- 4. FILTER CASES WITH ERRORS FOR REVIEW --- *")
    if flag_cols:
        sps_content.append("DATASET DECLARE Rejected_Cases.")
        sps_content.append("SELECT IF (Master_Reject_Count > 0).")
        sps_content.append("EXECUTE.")
        sps_content.append("DATASET NAME Rejected_Cases WINDOW=FRONT.")
        sps_content.append("* The active dataset is now filtered to show only cases with validation errors. *")
    
    return "\n".join(sps_content)

def generate_excel_report(df, flag_cols):
    """Generates the Excel error report as bytes."""
    
    error_df = pd.DataFrame() # Initialize an empty DataFrame
    
    if flag_cols:
        # Only select flag columns that actually exist in the DataFrame
        existing_flag_cols = [col for col in flag_cols if col in df.columns]
        
        if existing_flag_cols:
            df['Total_Errors'] = df[existing_flag_cols].sum(axis=1)
            error_df = df[df['Total_Errors'] > 0].copy() # Use .copy() to avoid SettingWithCopyWarning
            
        else:
            # If no flags exist, create a report showing no errors found
            status_df = pd.DataFrame([["Validation completed successfully. No flagged errors detected in this run."]], columns=['Status'])
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                status_df.to_excel(writer, sheet_name='Validation Status', index=False)
            return output.getvalue()
        
    # Select only key ID columns and the flag columns for the report
    cols_to_report = ['uuid'] + [col for col in df.columns if col.startswith('Flag_')] + ['Total_Errors']
    cols_to_report = [col for col in cols_to_report if col in error_df.columns] # Final filter

    # Use io.BytesIO to write the Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if not error_df.empty:
            report_df = error_df[cols_to_report]
            report_df.to_excel(writer, sheet_name='Respondent Errors', index=False)
        else:
            status_df = pd.DataFrame([["Validation completed successfully. No flagged errors detected in this run."]], columns=['Status'])
            status_df.to_excel(writer, sheet_name='Validation Status', index=False)
            
    return output.getvalue()


# --- 4. STREAMLIT APPLICATION ---

st.set_page_config(layout="wide")
st.title("🤖 Dynamic Survey Validation & Syntax Generator (Extended)")
st.markdown("This tool automates comprehensive Data Validation checks and generates final SPSS syntax and error reports.")
st.markdown("---")

# Initialize state to store flags cumulatively
if 'current_flag_cols' not in st.session_state:
    st.session_state.current_flag_cols = []
    
# --- Step 1: File Upload ---
st.header("Step 1: Upload Data")
uploaded_file = st.file_uploader("Choose a CSV File (Try 'latin-1' encoding if UTF-8 fails)", type="csv")

if uploaded_file:
    try:
        # Load data and handle potential encoding/ID issues
        df_raw = pd.read_csv(uploaded_file, encoding='latin-1') 
        st.success(f"Loaded {len(df_raw)} rows and {len(df_raw.columns)} columns.")
        
        # Ensure UUID column exists
        if 'uuid' not in df_raw.columns:
            if 'sys_RespNum' in df_raw.columns:
                df_raw['uuid'] = df_raw['sys_RespNum']
            else:
                df_raw['uuid'] = df_raw.index
        df_raw['uuid'] = df_raw['uuid'].astype(str)
        
        all_cols = df_raw.columns.tolist()
        df_validated = df_raw.copy()
        
        st.markdown("---")
        st.header("Step 2: Define Validation Checks")
        st.info("Run each check individually. Flags are added cumulatively for the final report.")
        
        # --- Speeder & Straightliner Check UI ---
        
        with st.expander("A. Core Quality Checks (Speeder/Straightliner)"):
            
            # Speeder Check
            st.subheader("1. Speeder Check (Junk)")
            duration_col_options = [c for c in all_cols if 'time' in c.lower() or 'duration' in c.lower()]
            duration_col_default = duration_col_options[0] if duration_col_options else all_cols[0]
            
            duration_col = st.selectbox("Select Duration Column", all_cols, key='speeder_col', 
                                        index=all_cols.index(duration_col_default) if duration_col_default in all_cols else 0)
            if st.button("Run Speeder Check", key='run_speeder'):
                df_validated, new_flags = run_speeder_check(df_validated, duration_col)
                st.session_state.current_flag_cols.extend(new_flags)
                st.info("Speeder check applied. Flag_Speeder created.")
                
            # Straightliner Check
            st.subheader("2. Straightliner Check (Grid/Rating Scales)")
            grid_cols_default = [c for c in all_cols if c.startswith('Q') and '_r' in c]
            grid_cols = st.multiselect("Select Grid Columns (Use Ctrl/Cmd to select multiple)", all_cols, 
                                        default=grid_cols_default, key='grid_cols')
            if st.button("Run Straightliner Check", key='run_straightliner'):
                df_validated, new_flags = run_straightliner_check(df_validated, grid_cols)
                st.session_state.current_flag_cols.extend(new_flags)
                st.info("Straightliner check applied. Flag_StraightLine created.")
                
        # --- Standard Question-Type Checks (SQ, MQ, Ranking, String) ---
        
        with st.expander("B. Question Type & Logic Checks"):
            
            # Single Select Check (SQ, Rating, Postcode, Individual Stubs)
            # Corrected line is here: removed invalid citation text
            st.subheader("1. Single Select / Rating Check (SQ, Rating, Postcode)") 
            with st.form("sq_form"):
                sq_col = st.selectbox("Select SQ/Rating/Postcode Column", all_cols, key='sq_col_select')
                sq_min = st.number_input("Minimum Valid Value (Range Check)", min_value=1, value=1, key='sq_min')
                sq_max = st.number_input("Maximum Valid Value (Range Check)", min_value=1, value=5, key='sq_max')
                sq_stubs_str = st.text_input("Specific Stubs (ANY) - e.g., '1, 3, 5' (Optional for Custom Stubs)", value='', key='sq_stubs_str')
                
                submitted_sq = st.form_submit_button("Run Single Select/Rating Check")
                if submitted_sq:
                    try:
                        sq_stubs = [int(s.strip()) for s in sq_stubs_str.split(',') if s.strip().isdigit()]
                        df_validated, new_flags = run_sq_check(df_validated, sq_col, sq_min, sq_max, required_stubs=sq_stubs if sq_stubs_str else None)
                        st.session_state.current_flag_cols.extend(new_flags)
                        st.success(f"SQ/Rating Check applied to {sq_col}. Flags: {', '.join(new_flags)}")
                    except Exception as e:
                        st.error(f"Error in SQ Check: {e}")

            st.markdown("---")
            
            # Multi-Select Check (MQ)
            st.subheader("2. Multi-Select Check (MQ)")
            with st.form("mq_form"):
                mq_cols_default = [c for c in all_cols if c.startswith('Q') and '_c' in c]
                mq_cols = st.multiselect("Select All Multi-Select Columns (Binary coded)", all_cols, 
                                        default=mq_cols_default, key='mq_cols_select')
                mq_min_count = st.number_input("Minimum Selections Required (Count Check)", min_value=0, value=1, key='mq_min_count')
                mq_max_count = st.number_input("Maximum Selections Allowed (0 for no max)", min_value=0, value=0, key='mq_max_count')
                exclusive_col = st.selectbox("Select Exclusive Stub Column (Optional)", ['None'] + all_cols, key='mq_exclusive_col')
                
                submitted_mq = st.form_submit_button("Run Multi-Select Check")
                if submitted_mq:
                    if mq_cols:
                        df_validated, new_flags = run_mq_check(
                            df_validated, mq_cols, 
                            min_count=mq_min_count, 
                            max_count=mq_max_count if mq_max_count > 0 else None, 
                            exclusive_stub=exclusive_col if exclusive_col != 'None' else None
                        )
                        st.session_state.current_flag_cols.extend(new_flags)
                        st.success(f"MQ Check applied to {len(mq_cols)} columns. Flags: {', '.join(new_flags)}")
                    else:
                        st.warning("Please select columns for MQ Check.")

            st.markdown("---")
            
            # Ranking Check
            st.subheader("3. Ranking Check")
            with st.form("ranking_form"):
                rank_cols_default = [c for c in all_cols if c.startswith('Rank_') or c.startswith('R_')]
                rank_cols = st.multiselect("Select All Ranking Columns", all_cols, 
                                        default=rank_cols_default, key='rank_cols_select')
                rank_min = st.number_input("Minimum Expected Rank Value", min_value=1, value=1, key='rank_min')
                rank_max = st.number_input("Maximum Expected Rank Value", min_value=1, value=3, key='rank_max')
                
                submitted_rank = st.form_submit_button("Run Ranking Check")
                if submitted_rank:
                    if rank_cols:
                        df_validated, new_flags = run_ranking_check(df_validated, rank_cols, min_rank_expected=rank_min, max_rank_expected=rank_max)
                        st.session_state.current_flag_cols.extend(new_flags)
                        st.success(f"Ranking Check applied to {len(rank_cols)} columns. Flags: {', '.join(new_flags)}")
                    else:
                        st.warning("Please select columns for Ranking Check.")

            st.markdown("---")

            # String Check (Open Ends, Postcode Text)
            st.subheader("4. String/Open-End Check (Junk and Missing)")
            with st.form("string_form"):
                string_cols_default = [c for c in all_cols if c.endswith('_TEXT') or c.endswith('_OE')]
                string_cols = st.multiselect("Select String/Open-End Columns", all_cols, 
                                        default=string_cols_default, key='string_cols_select')
                string_min_length = st.number_input("Minimum Non-Junk Length (e.g., 5 characters)", min_value=1, value=5, key='string_min_length')
                
                submitted_string = st.form_submit_button("Run String Check")
                if submitted_string:
                    if string_cols:
                        df_validated, new_flags = run_string_check(df_validated, string_cols, min_length=string_min_length)
                        st.session_state.current_flag_cols.extend(new_flags)
                        st.success(f"String Check applied to {len(string_cols)} columns. Flags: {', '.join(new_flags)}")
                    else:
                        st.warning("Please select columns for String Check.")
            
            st.markdown("---")
            
            # Skip Logic Check (Piping, Reverse Condition, Skip Logic)
            st.subheader("5. Custom Skip Logic / Piping Check")
            with st.form("skip_logic_form"):
                trigger_col = st.selectbox("Trigger Question (Q1)", all_cols, key='sl_trigger_col')
                trigger_val = st.text_input("Trigger Value (e.g., 1, 3 or 'Yes')", value='1', key='sl_trigger_val')
                target_col = st.selectbox("Target Question (Q2, which is skipped/piped)", all_cols, key='sl_target_col')
                
                submitted_sl = st.form_submit_button("Add & Run Skip Logic Rule")
                if submitted_sl:
                    df_validated, new_flags = run_skip_logic_check(df_validated, target_col, trigger_col, trigger_val)
                    if new_flags:
                        st.session_state.current_flag_cols.extend(new_flags)
                        st.success(f"Skip Logic rule applied. Flag: {new_flags[0]}")
                    else:
                        st.error("Error: Check if selected columns exist.")

        st.markdown("---")
        st.header("Step 3: Targeted SPSS Syntax Generation")
        
        syntax_type = st.selectbox(
            "Select Variable Type for Syntax Generation (Labels/Sets):",
            ["None", "Single Select (Categorical)", "Multi-Select (Select All That Apply)", "Grid/Scale Variables", "Data Type Recode (Numeric/String)"]
        )
        
        if syntax_type != "None":
            syntax_cols = st.multiselect(f"Select columns for {syntax_type} syntax:", all_cols, default=[], key='syntax_cols')
            
            if syntax_cols:
                targeted_sps_syntax = generate_spss_syntax_by_type(syntax_type, syntax_cols)
                
                st.download_button(
                    label=f"⬇️ Download {syntax_type} Syntax",
                    data=targeted_sps_syntax,
                    file_name=f"targeted_syntax_{syntax_type.split(' ')[0]}.sps",
                    mime="text/plain"
                )
                st.code(targeted_sps_syntax[:500] + "\n...", language='spss')


        st.markdown("---")
        st.header("Step 4: Final Validation Report & Master Syntax")

        # Compile master flag list (only include flags that exist in the validated DF)
        final_flag_cols = sorted(list(set([col for col in st.session_state.current_flag_cols if col in df_validated.columns])))
        
        st.info(f"The final process will combine {len(final_flag_cols)} unique flags.")
        
        if final_flag_cols:
            
            # --- Generate Master Outputs ---
            master_spss_syntax = generate_master_spss_syntax(final_flag_cols)
            excel_report_bytes = generate_excel_report(df_validated, final_flag_cols)
            
            col_a, col_b = st.columns(2)
            
            with col_a:
                st.download_button(
                    label="⬇️ Download Master SPSS Syntax (.sps)",
                    data=master_spss_syntax,
                    file_name="master_validation_report.sps",
                    mime="text/plain"
                )
            with col_b:
                st.download_button(
                    label="⬇️ Download Excel Error Report (.xlsx)",
                    data=excel_report_bytes,
                    file_name="validation_error_summary.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
            st.subheader("Summary of Generated Flags")
            st.code('\n'.join(final_flag_cols), language='text')

        else:
            st.warning("Please define and run at least one validation check in Step 2 to generate the final report.")
            

    except Exception as e:
        st.error(f"An error occurred during processing. Please ensure your CSV is valid, try changing the encoding, and confirm column selections are correct. Error: {e}")
        st.error("Trace:")
        st.code(str(e))
# --- End of Streamlit Script ---