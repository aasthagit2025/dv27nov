import streamlit as st
import pandas as pd
import numpy as np
import io

# --- 1. CONFIGURATION: CORE UTILITY FUNCTIONS ---

def run_speeder_check(df, duration_col):
    """Applies the Speeder Check."""
    if duration_col in df.columns:
        median_time = df[duration_col].median()
        threshold = median_time * 0.4
        df['Flag_Speeder'] = np.where(df[duration_col] < threshold, 1, 0)
    else:
        df['Flag_Speeder'] = 0
    return df

def run_straightliner_check(df, grid_cols):
    """Applies the Straightliner Check."""
    if all(col in df.columns for col in grid_cols) and len(grid_cols) > 1:
        # Calculate standard deviation across the grid columns for each respondent
        df['grid_std'] = df[grid_cols].std(axis=1)
        # Flag 1 if the standard deviation is 0 (all answers are the same)
        df['Flag_StraightLine'] = np.where(df['grid_std'] == 0, 1, 0)
    else:
        df['Flag_StraightLine'] = 0
    return df

def run_skip_logic_check(df, target_col, trigger_col, trigger_val):
    """Applies a single Skip Logic rule."""
    if all(col in df.columns for col in [target_col, trigger_col]):
        flag_col = f"Flag_SL_{trigger_col}_to_{target_col}"
        
        # Error of Commission (Shouldn't have answered, but did)
        commission_mask = (df[trigger_col] != trigger_val) & (df[target_col].notna())
        
        # Error of Omission (Should have answered, but didn't)
        omission_mask = (df[trigger_col] == trigger_val) & (df[target_col].isna())
        
        df[flag_col] = np.where(commission_mask | omission_mask, 1, 0)
        return df, flag_col
    return df, None

# --- 2. SPSS SYNTAX GENERATION (USER-DRIVEN) ---

def generate_spss_syntax_by_type(selected_type, selected_cols):
    """Generates targeted SPSS syntax based on user selection."""
    
    sps_content = []
    
    if selected_type == "Single Select (Categorical)":
        sps_content.append(f"* --- Syntax for Single Select Variables ({len(selected_cols)} columns) --- *")
        for col in selected_cols:
            sps_content.append(f"VALUE LABELS {col} 1 'Option A' 2 'Option B' 99 'Missing'.")
            sps_content.append(f"MISSING VALUES {col} (99).")
        sps_content.append("EXECUTE.")

    elif selected_type == "Multi-Select (Select All That Apply)":
        sps_content.append(f"* --- Syntax for Multi-Select Variables ({len(selected_cols)} columns) --- *")
        sps_content.append("* Multi-select data often needs to be defined as multiple binary variables. *")
        sps_content.append("* Assuming columns are named like Q1_1, Q1_2, etc. (Binary coded 1=Selected, 0=Not Selected/Missing) *")
        sps_content.append("MRSETS")
        sps_content.append(f" /MCGROUP NAME=$MSQ_Example COMPONENTS={'; '.join(selected_cols)}")
        sps_content.append(" /VALUE=1.")

    elif selected_type == "Grid/Scale Variables":
        sps_content.append(f"* --- Syntax for Grid/Scale Variables ({len(selected_cols)} columns) --- *")
        sps_content.append("* This sets standard scale labels and missing values for a Likert Scale. *")
        sps_content.append(f"VALUE LABELS {'; '.join(selected_cols)}")
        sps_content.append("  1 'Strongly Disagree'")
        sps_content.append("  5 'Strongly Agree'")
        sps_content.append("  -99 'Refused'.")
        sps_content.append(f"MISSING VALUES {'; '.join(selected_cols)} (-99).")
        sps_content.append("EXECUTE.")

    elif selected_type == "Data Type Recode (Numeric)":
        sps_content.append(f"* --- Syntax for Recoding String to Numeric ({len(selected_cols)} columns) --- *")
        for col in selected_cols:
            # Assuming codes need to be converted to numeric
            sps_content.append(f"RECODE {col} ('Yes'=1) ('No'=0) INTO {col}_Numeric.")
            sps_content.append(f"VARIABLE LABELS {col}_Numeric '{col} (Numeric Recode)'.")
        sps_content.append("EXECUTE.")

    return "\n".join(sps_content)

# --- 3. EXCEL REPORT & MAIN SYNTAX GENERATION (REVISED) ---

def generate_master_spss_syntax(flag_cols):
    """Generates the master .sps file with final flag definitions and reports."""
    
    sps_content = []
    
    sps_content.append(f"*{'='*60}*")
    sps_content.append(f"* PYTHON-GENERATED VALIDATION FLAGS & REPORT *")
    sps_content.append(f"*{'='*60}*\n")
    sps_content.append("DATASET ACTIVATE ALL.")
    
    # Define the new flag variables
    sps_content.append("\n* --- 1. FLAG VARIABLE DEFINITION --- *")
    for flag in flag_cols:
        sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail'.")
    
    # Compute a Master Reject Flag
    sps_content.append("\n* --- 2. MASTER REJECT FLAG --- *")
    if flag_cols:
        master_flag_logic = ' + '.join(flag_cols)
        sps_content.append(f"COMPUTE Master_Reject_Count = SUM({master_flag_logic}).")
        sps_content.append("VARIABLE LABELS Master_Reject_Count 'Total Validation Errors'.")
        sps_content.append("EXECUTE.")
    else:
        sps_content.append("* No validation flags were created in this run. *")

    # Core Validation Output (Frequencies)
    sps_content.append("\n* --- 3. VALIDATION REPORT (Frequencies) --- *")
    if flag_cols:
        sps_content.append(f"FREQUENCIES VARIABLES={'; '.join(flag_cols)} /STATISTICS=COUNT SUM.")
    
    # Filter for Manual Review
    sps_content.append("\n* --- 4. FILTER CASES WITH ERRORS FOR REVIEW --- *")
    if flag_cols:
        sps_content.append("DATASET DECLARE Rejected_Cases.")
        sps_content.append("SELECT IF (Master_Reject_Count > 0).")
        sps_content.append("EXECUTE.")
        sps_content.append("DATASET NAME Rejected_Cases WINDOW=FRONT.")
        sps_content.append("* The active dataset is now filtered to show only errors. *")
    
    return "\n".join(sps_content)

def generate_excel_report(df, flag_cols):
    """Generates the Excel error report as bytes."""
    
    if flag_cols:
        df['Total_Errors'] = df[[col for col in flag_cols if col in df.columns]].sum(axis=1)
        error_df = df[df['Total_Errors'] > 0]
    else:
        error_df = pd.DataFrame() # Empty if no flags

    # Select only key ID columns and the flag columns for the report
    cols_to_report = [col for col in df.columns if col == 'uuid' or col.startswith('Flag_')] + ['Total_Errors']
    
    # Use io.BytesIO to write the Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if not error_df.empty:
            report_df = error_df[[col for col in cols_to_report if col in error_df.columns]]
            report_df.to_excel(writer, sheet_name='Respondent Errors', index=False)
        else:
            status_df = pd.DataFrame([["Validation completed successfully. No errors detected."]], columns=['Status'])
            status_df.to_excel(writer, sheet_name='Validation Status', index=False)
            
    return output.getvalue()


# --- 4. STREAMLIT APPLICATION ---

st.set_page_config(layout="wide")
st.title("🤖 Dynamic Survey Validation & Syntax Generator")
st.markdown("---")

# --- Step 1: File Upload ---
st.header("Step 1: Upload Data")
uploaded_file = st.file_uploader("Choose a CSV File (Ensure it is encoded as 'latin-1' if UTF-8 fails)", type="csv")

if uploaded_file:
    try:
        # **Robust Fix for Encoding Issue**
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
        current_flag_cols = []
        
        st.markdown("---")
        st.header("Step 2: Define Validation Checks")
        
        # --- Speeder Check UI ---
        st.subheader("A. Speeder Check")
        duration_col = st.selectbox("Select Duration Column (e.g., Duration_Seconds)", all_cols, index=all_cols.index('sys_pagetime_1') if 'sys_pagetime_1' in all_cols else 0)
        if st.button("Run Speeder Check"):
            df_validated = run_speeder_check(df_validated, duration_col)
            current_flag_cols.append('Flag_Speeder')
            st.info("Speeder check applied. Flag_Speeder column created.")
            
        # --- Straightliner Check UI ---
        st.subheader("B. Straightliner Check (Grid Scales)")
        grid_cols = st.multiselect("Select Grid Columns (Use Ctrl/Cmd to select multiple)", all_cols, default=[c for c in all_cols if c.startswith('A3_r')])
        if st.button("Run Straightliner Check"):
            df_validated = run_straightliner_check(df_validated, grid_cols)
            current_flag_cols.append('Flag_StraightLine')
            st.info("Straightliner check applied. Flag_StraightLine column created.")

        # --- Skip Logic Check UI ---
        st.subheader("C. Skip Logic Checks (Custom)")
        with st.form("skip_logic_form"):
            trigger_col = st.selectbox("Trigger Question (Q1)", all_cols)
            trigger_val = st.text_input("Trigger Value (e.g., 1 for 'Yes')", value='1')
            target_col = st.selectbox("Target Question (Q2, which is skipped)", all_cols)
            
            submitted = st.form_submit_button("Add & Run Skip Logic Rule")
            if submitted:
                # Attempt to convert trigger_val to numeric if possible
                try:
                    trigger_val = float(trigger_val)
                except ValueError:
                    pass # Keep as string if conversion fails

                df_validated, new_flag = run_skip_logic_check(df_validated, target_col, trigger_col, trigger_val)
                if new_flag:
                    current_flag_cols.append(new_flag)
                    st.success(f"Skip Logic rule applied. Flag: {new_flag}")

        st.markdown("---")
        st.header("Step 3: Targeted SPSS Syntax Generation")
        
        syntax_type = st.selectbox(
            "Select Variable Type for Syntax Generation:",
            ["None", "Single Select (Categorical)", "Multi-Select (Select All That Apply)", "Grid/Scale Variables", "Data Type Recode (Numeric)"]
        )
        
        if syntax_type != "None":
            syntax_cols = st.multiselect(f"Select columns for {syntax_type} syntax:", all_cols, default=[])
            
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
        final_flag_cols = [col for col in current_flag_cols if col in df_validated.columns]
        
        if final_flag_cols:
            st.success(f"Master process will combine {len(final_flag_cols)} final flags.")
            
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
        else:
            st.warning("Please define and run at least one validation check in Step 2 to generate the final report.")
            

    except Exception as e:
        st.error(f"An error occurred during processing. Please ensure your CSV is valid, try changing the encoding, and confirm column selections are correct: {e}")

# --- End of Streamlit Script ---