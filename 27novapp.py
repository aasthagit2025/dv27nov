import streamlit as st
import pandas as pd
import numpy as np
import io
import time 
import os 
import tempfile # NEW: Required for the robust SPSS file handling fix

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

for k in [
    'sq_rules',
    'mq_rules',
    'ranking_rules',
    'string_rules',
    'straightliner_rules',
    'all_cols',
    'string_batch_vars'   # ✅ ADD THIS
]:
    if k not in st.session_state:
        st.session_state[k] = []

    
# --- DATA LOADING FUNCTION ---
def load_data_file(uploaded_file):
    """Reads data from CSV, Excel, or SPSS data files, handling different formats."""
    
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    
    # Define NA values for CSV/Excel
    na_values = ['', ' ', '#N/A', 'N/A', 'NA', '#NA', 'NULL', 'null']
    
    if file_extension in ['.csv']:
        # Try common encodings for CSV
        try:
            # Attempt UTF-8 first
            uploaded_file.seek(0) # Ensure pointer is at start
            return pd.read_csv(uploaded_file, encoding='utf-8', na_values=na_values, keep_default_na=True)
        except Exception:
            try:
                # Reset file pointer and try Latin-1
                uploaded_file.seek(0)
                return pd.read_csv(uploaded_file, encoding='latin-1', na_values=na_values, keep_default_na=True)
            except Exception as e:
                raise Exception(f"Failed to read CSV with both UTF-8 and Latin-1 encodings. Error: {e}")
    
    elif file_extension in ['.xlsx', '.xls']:
        # Excel files
        uploaded_file.seek(0) # Ensure pointer is at start
        return pd.read_excel(uploaded_file)
    
    # CORRECTED LOGIC FOR SPSS FILES (.sav, .zsav) - Uses Temporary File Path
    elif file_extension in ['.sav', '.zsav']:
        tmp_path = None
        try:
            # 1. Use tempfile to create a path that pd.read_spss will accept
            # This is the most reliable way to handle the "expected str, bytes... not BytesIO" error.
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                # 2. Write the content of the UploadedFile to the temporary file
                tmp_file.write(uploaded_file.getbuffer())
                tmp_path = tmp_file.name
            
            # 3. Read the data using the temporary file path
            df = pd.read_spss(tmp_path, convert_categoricals=False)
            st.session_state['spss_var_formats'] = df.dtypes.to_dict()
            
            # 4. Clean up the temporary file immediately
            os.remove(tmp_path)
            
            return df
            
        except ImportError:
            st.error("Error: Reading SPSS files requires the 'pyreadstat' library. Please ensure it is in your requirements.txt.")
            raise
        except Exception as e:
            # Ensure file is removed if an error occurred during read
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise Exception(f"Failed to read SPSS data file. Please ensure it is a valid .sav or .zsav file. Error: {e}")
    
    else:
        raise Exception(f"Unsupported file format: {file_extension}. Please upload CSV, Excel (.xlsx/.xls), or SPSS (.sav/.zsav).")


# --- CORE UTILITY FUNCTIONS (SYNTAX GENERATION) ---

def generate_skip_spss_syntax(target_col, trigger_col, trigger_val, rule_type, range_min=None, range_max=None):
    """
    Generates detailed SPSS syntax for Skip Logic (Error of Omission/Commission)
    using the two-stage process: Flag_Qx (intermediate filter) -> xxQx (final EoO/EoC flag).
    """
    if '_' in target_col:
        target_clean = target_col.split('_')[0]
    else:
        target_clean = target_col
        
    filter_flag = f"Flag_{target_clean}" 
    final_error_flag = f"{FLAG_PREFIX}{target_clean}" 
    
    syntax = []
    
    # Stage 1: Filter Flag (Flag_Qx)
    syntax.append(f"**************************************SKIP LOGIC FILTER FLAG: {trigger_col}={trigger_val} -> {target_clean}")
    syntax.append(f"* Qx should ONLY be asked if {trigger_col} = {trigger_val}.")
    syntax.append(f"IF({trigger_col} = {trigger_val}) {filter_flag}=1.")
    syntax.append(f"EXECUTE.\n") 
    
    if rule_type == 'SQ' and range_min is not None and range_max is not None:
        # EoO: Trigger met AND (Missing OR Out-of-Range)
        eoo_condition = f"(miss({target_col}) | ~range({target_col},{range_min},{range_max}))"
        # EoC: Trigger NOT met AND (Answered)
        eoc_condition = f"~miss({target_col})" 
        
    elif rule_type == 'String':
        # String variables: BLANK only (no miss())
        eoo_condition = f"({target_col}='')"
        eoc_condition = f"({target_col}<>'')" 
        
    else: # MQ/Ranking/General
        eoo_condition = f"miss({target_col})"
        eoc_condition = f"~miss({target_col})" 
        
    # --- EoO/EoC Logic ---
    syntax.append(f"**************************************SKIP LOGIC EoO/EoC CHECK: {target_col} -> {final_error_flag}")
    
    # Error of Omission (EoO) - Flag=1
    syntax.append(f"* EoO (1): Trigger Met ({filter_flag}=1), Target Fails Check/Missing/Out-of-Range/Empty.")
    syntax.append(f"IF({filter_flag} = 1 & {eoo_condition}) {final_error_flag}=1.")
    
    # Error of Commission (EoC) - Flag=2
    syntax.append(f"* EoC (2): Trigger Not Met ({filter_flag}<>1 | miss({filter_flag})), Target Answered.")
    syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & {eoc_condition}) {final_error_flag}=2.")
    
    syntax.append("EXECUTE.\n")
    
    return syntax, [filter_flag, final_error_flag]


def generate_other_specify_spss_syntax(main_col, other_col, other_stub_val):
    """
    Generates syntax for Other-Specify checks (Both forward and reverse conditions).
    """
    syntax = []
    if '_' in main_col:
        main_clean = main_col.split('_')[0]
    else:
        main_clean = main_col
        
    flag_name_fwd = f"{FLAG_PREFIX}{main_clean}_OtherFwd"
    flag_name_rev = f"{FLAG_PREFIX}{main_clean}_OtherRev"
    
    # Forward Check (Main selected, Other is empty/missing) - EoO type check
    syntax.append(f"**************************************OTHER SPECIFY (Forward) Check: {main_col}={other_stub_val} AND {other_col} is missing/blank")
    syntax.append(f"* EoO (1): Main selected ({main_col}={other_stub_val}), Other is missing/blank.")
    syntax.append(f"IF({main_col}={other_stub_val} & {other_col}='') {flag_name_fwd}=1.")
    syntax.append(f"EXECUTE.\n")
    
    # Reverse Check (Other answered, Main not selected) - EoC type check
    syntax.append(f"**************************************OTHER SPECIFY (Reverse) Check: {other_col} has data AND {main_col}<>{other_stub_val}")
    syntax.append(f"* EoC (2): Other has data (~miss({other_col}) & {other_col}<>''), Main not selected.")
    syntax.append(f"IF(~miss({other_col}) & {other_col}<>'' & {main_col}<>{other_stub_val}) {flag_name_rev}=1.")
    syntax.append(f"EXECUTE.\n")
    
    return syntax, [flag_name_fwd, flag_name_rev]

def generate_piping_spss_syntax(target_col, overall_skip_filter_flag, piping_source_col, piping_stub_val):
    """
    Generates syntax for the Rating Piping/Reverse Condition check.
    """
    syntax = []
    
    flag_col = f"{FLAG_PREFIX}{target_col}" 
    
    # 1. Error of Omission (EOO) - Target is missing/wrong when piping condition is met
    syntax.append(f"**************************************PIPING (EOO) Check: (Filter={overall_skip_filter_flag}=1) AND ({piping_source_col}={piping_stub_val}) AND {target_col}<>{piping_stub_val}")
    syntax.append(f"* EoO (1): Piping/Skip met, Target value is wrong/missing. IF(((Flag_Q12=1) & Q11=1 ) & Q12_1<>1)xxQ12_1=1.")
    syntax.append(f"IF(({overall_skip_filter_flag}=1) & ({piping_source_col}={piping_stub_val}) & {target_col}<>{piping_stub_val}) {flag_col}=1.")
    
    # 2. Error of Commission (EOC / Reverse Condition) - Target has data when piping condition is NOT met
    syntax.append(f"**************************************PIPING (EOC / Reverse) Check: (Filter NOT met OR Piping NOT met) AND {target_col} is answered")
    syntax.append(f"* EoC (2): Skip/Piping not met, Target value is wrongly answered. IF((Flag_Q12<>1 | miss(Flag_Q12) | Q11<>1 | miss(Q11)) & ~miss(Q12_1))xxQ12_1=2.")
    
    # EOC Condition: (Flag_Qx<>1 OR miss(Flag_Qx) OR Q_source<>i OR miss(Q_source)) AND ~miss(Target)
    eoc_condition = f"({overall_skip_filter_flag}<>1 | miss({overall_skip_filter_flag}) | {piping_source_col}<>{piping_stub_val} | miss({piping_source_col})) & ~miss({target_col})"
    syntax.append(f"IF({eoc_condition}) {flag_col}=2.")
    syntax.append("EXECUTE.\n")
    
    return syntax, [flag_col]


def generate_sq_spss_syntax(rule):
    """Generates detailed SPSS syntax for a single Single Select check."""
    col = rule['variable']
    min_val = rule['min_val']
    max_val = rule['max_val']
    required_stubs_list = rule['required_stubs']
    
    if '_' in col:
        target_clean = col.split('_')[0]
    else:
        target_clean = col
        
    filter_flag = f"Flag_{target_clean}" 
        
    syntax = []
    generated_flags = []

    # 1. Missing/Range Check 
    if not rule['run_piping_check']:
        flag_name = f"{FLAG_PREFIX}{col}_Rng"
        syntax.append(f"**************************************SQ Missing/Range Check: {col} (Range: {min_val} to {max_val})")
        syntax.append(f"IF(miss({col}) | ~range({col},{min_val},{max_val})) {flag_name}=1.")
        syntax.append(f"EXECUTE.\n")
        generated_flags.append(flag_name)
    
    # 2. Specific Stub Check (ANY)
    if required_stubs_list:
        stubs_str = ', '.join(map(str, required_stubs_list))
        flag_any = f"{FLAG_PREFIX}{col}_Any"
        syntax.append(f"**************************************SQ Specific Stub Check (Not IN Acceptable List): {col} (Accept: {stubs_str})")
        syntax.append(f"IF(~miss({col}) & NOT(any({col}, {stubs_str}))) {flag_any}=1.")
        syntax.append(f"EXECUTE.\n")
        generated_flags.append(flag_any)

    # 3. Other Specify Check
    if rule.get('other_var') and rule['other_var'] != '-- Select Variable --':
        other_syntax, other_flags = generate_other_specify_spss_syntax(col, rule['other_var'], rule['other_stub_val'])
        syntax.extend(other_syntax)
        generated_flags.extend(other_flags)

    # --- Combined Skip/Piping Checks ---
    if (rule['run_skip'] or rule['run_piping_check']) and rule['trigger_col'] != '-- Select Variable --':
        
        trigger_col = rule['trigger_col']
        trigger_val = rule['trigger_val']
        
        # B. Generate Filter Flag (Flag_Qx)
        syntax.append(f"**************************************SQ Filter Flag for Skip/Piping: {filter_flag}")
        syntax.append(f"* Filter for {target_clean}: {trigger_col} = {trigger_val}.")
        syntax.append(f"IF({trigger_col} = {trigger_val}) {filter_flag}=1.")
        syntax.append(f"EXECUTE.\n")
        generated_flags.append(filter_flag)
        
        # C. Piping/Reverse Condition Check
        if rule['run_piping_check'] and rule['piping_source_col'] != '-- Select Variable --':
            pipe_syntax, pipe_flags = generate_piping_spss_syntax(
                col, filter_flag, rule['piping_source_col'], rule['piping_stub_val']
            )
            syntax.extend(pipe_syntax)
            generated_flags.extend(pipe_flags)
        
        # D. Standard Skip Logic (EoO/EoC) - Only if Piping is NOT run on this specific variable
        elif rule['run_skip']:
            sl_syntax, sl_flags = generate_skip_spss_syntax(
                col, trigger_col, trigger_val, 'SQ', min_val, max_val
            )
            syntax.extend(sl_syntax)
            generated_flags.extend(sl_flags)
        
    return syntax, generated_flags 

def configure_sq_rules(all_variable_options):
    """Handles batch selection and sequential configuration of SQ rules."""
    st.subheader("1. Single Select / Rating Rule (SQ) Configuration")
    
    sq_cols = st.multiselect("Select ALL Target Variables (Qx, Qx_i) for Single Select/Rating", st.session_state.all_cols, 
                             key='sq_batch_select_key', 
                             default=st.session_state.get('sq_batch_vars', []))
    
    if st.button("Start/Update SQ Rule Configuration", key='start_sq_config_btn'):
        st.session_state.sq_batch_vars = sq_cols
        
    st.markdown("---")
    
    if st.session_state.get('sq_batch_vars'):
        st.info(f"Configuring **{len(st.session_state.sq_batch_vars)}** selected SQ variables one-by-one below.")
        
        sq_config_form_key = 'sq_config_form'
        with st.form(sq_config_form_key):
            new_sq_rules = []
            
            for i, col in enumerate(st.session_state.sq_batch_vars):
                st.markdown(f"### ⚙️ Rule Configuration for **{col}** (Variable {i+1}/{len(st.session_state.sq_batch_vars)})")
                
                existing_rule = next((r for r in st.session_state.sq_rules if r['variable'] == col), {})
                
                key_prefix = f'sq_{col}_{i}'
                
                # --- A. Range Check ---
                st.markdown("#### A. Range & Stub Check")
                col_min, col_max = st.columns(2)
                with col_min:
                    min_val = st.number_input("Minimum Valid Value (Range)", min_value=1, value=existing_rule.get('min_val', 1), key=f'{key_prefix}_min')
                with col_max:
                    max_val = st.number_input("Maximum Valid Value (Range)", min_value=1, value=existing_rule.get('max_val', 5), key=f'{key_prefix}_max')
                
                stubs_list = existing_rule.get('required_stubs', [])
                stubs_str_default = ', '.join(map(str, stubs_list)) if stubs_list else ''
                stubs_str = st.text_input("Specific Acceptable Stubs (e.g., '1, 3, 5' - for ANY check, leave blank if all in range are acceptable)", value=stubs_str_default, key=f'{key_prefix}_stubs')
                required_stubs = [int(s.strip()) for s in stubs_str.split(',') if s.strip().isdigit()] if stubs_str else None
                
                # --- B. Other Specify Check ---
                st.markdown("#### B. Other Specify Check (Forward and Reverse Condition)")
                col_other_var, col_other_stub = st.columns(2)
                
                other_var_default = existing_rule.get('other_var') or '-- Select Variable --'
                other_stub_default = existing_rule.get('other_stub_val', 99)
                
                with col_other_var:
                    other_var = st.selectbox("Corresponding 'Other Specify' Variable (Qx_OE/TEXT)", all_variable_options, 
                                             index=all_variable_options.index(other_var_default) if other_var_default in all_variable_options else 0, 
                                             key=f'{key_prefix}_other_var')
                with col_other_stub:
                    other_stub_val = st.number_input("Stub Value for 'Other' (e.g., 99)", min_value=1, value=other_stub_default, key=f'{key_prefix}_other_stub')
                    
                # --- C & D. Skip Logic (EoO/EoC) and Piping ---
                st.markdown("#### C. Skip Logic Filter Condition (Applies to both Skip and Piping)")
                
                skip_trigger_col_default = existing_rule.get('trigger_col') or '-- Select Variable --'
                skip_trigger_val_default = existing_rule.get('trigger_val') or '1'
                
                col_t_col, col_t_val = st.columns(2)
                with col_t_col:
                    skip_trigger_col = st.selectbox("**Filter/Trigger Variable** (e.g., Q0)", all_variable_options, 
                                                    index=all_variable_options.index(skip_trigger_col_default) if skip_trigger_col_default in all_variable_options else 0, 
                                                    key=f'{key_prefix}_t_col')
                with col_t_val:
                    skip_trigger_val = st.text_input("**Filter Condition Value** (e.g., 1)", value=skip_trigger_val_default, key=f'{key_prefix}_t_val')


                # 2. Enable/Disable Skip Logic
                st.markdown("#### D. Enable Skip Logic or Piping")

                run_skip_default = existing_rule.get('run_skip', False)
                run_piping_default = existing_rule.get('run_piping_check', False)

                col_e_skip, col_e_pipe = st.columns(2)
                with col_e_skip:
                    run_skip = st.checkbox("Enable **Standard Skip Logic** Check (Creates Flag_Qx and xxQx=1/2)", value=run_skip_default, key=f'{key_prefix}_run_skip')
                
                with col_e_pipe:
                    run_piping = st.checkbox("Enable **Piping/Reverse** Condition Check (Creates xxQx_i = 1/2 flags)", value=run_piping_default, key=f'{key_prefix}_run_pipe')

                
                pipe_source_col_default = existing_rule.get('piping_source_col') or '-- Select Variable --'
                pipe_stub_val_default = existing_rule.get('piping_stub_val', 1) 

                if run_piping:
                    with st.container(border=True):
                        st.warning(f"Piping check is enabled. It uses the Filter defined above and checks if **{col}** matches the expected stub value from the **Piping Source Column**.")
                        col_p_source, col_p_stub = st.columns(2)
                        with col_p_source:
                            pipe_source_col = st.selectbox("Piping Source Column (Q_Source)", all_variable_options, 
                                                           index=all_variable_options.index(pipe_source_col_default) if pipe_source_col_default in all_variable_options else 0, 
                                                           key=f'{key_prefix}_p_source')
                        with col_p_stub:
                            auto_val = int(col.split('_')[-1]) if '_' in col and col.split('_')[-1].isdigit() else 1
                            pipe_stub_val = st.number_input(f"Expected Stub Value (Value of {col} must match this if {pipe_source_col} selected)", min_value=1, value=pipe_stub_val_default if existing_rule.get('piping_stub_val') else auto_val, key=f'{key_prefix}_p_stub')
                    
                else:
                    pipe_source_col = '-- Select Variable --'
                    pipe_stub_val = 1


                st.markdown("---")
                
                # Construct the rule dictionary
                new_sq_rules.append({
                    'variable': col,
                    'min_val': min_val,
                    'max_val': max_val,
                    'required_stubs': required_stubs,
                    'other_var': other_var,
                    'other_stub_val': other_stub_val,
                    
                    # Standard Skip Logic (D)
                    'run_skip': run_skip and skip_trigger_col != '-- Select Variable --',
                    'trigger_col': skip_trigger_col,
                    'trigger_val': skip_trigger_val,
                    
                    # Piping Check (D) - Requires a valid trigger column to be useful
                    'run_piping_check': run_piping and pipe_source_col != '-- Select Variable --' and skip_trigger_col != '-- Select Variable --',
                    'piping_source_col': pipe_source_col,
                    'piping_stub_val': pipe_stub_val,
                })
            
            if st.form_submit_button("✅ Save ALL Configured SQ Rules"):
                existing_vars_to_keep = [r for r in st.session_state.sq_rules if r['variable'] not in st.session_state.sq_batch_vars]
                
                for rule in new_sq_rules:
                    existing_vars_to_keep.append(rule)
                    
                st.session_state.sq_rules = existing_vars_to_keep
                    
                st.success(f"Successfully saved {len(new_sq_rules)} SQ rules.")
                st.session_state.sq_batch_vars = [] 
                st.rerun()
            else:
                st.markdown("Submit the form above to save the configured rules.")

# NEW FUNCTION: Generate Straightliner Syntax
def generate_straightliner_spss_syntax(cols):
    """
    Generates SPSS syntax for a Maximum Straightliner check (MIN=MAX).
    This flags respondents who gave the exact same answer for all items in the grid.
    """
    cols_str = ' '.join(cols)
    set_name = cols[0].split('_')[0] if cols else 'Rating_Set'
    flag_name_max_str = f"{FLAG_PREFIX}{set_name}_MaxStr"
    
    syntax = []
    
    syntax.append(f"**************************************STRAIGHTLINER CHECK: {set_name} (Max: All Items Same Value)")
    syntax.append(f"* Check if the minimum value equals the maximum value across the grid items for a single respondent.")
    
    # Calculate MIN and MAX for the row/case
    syntax.append(f"COMPUTE #Min_Val = MIN({cols_str}).")
    syntax.append(f"COMPUTE #Max_Val = MAX({cols_str}).")
    
    # Flag 1 if MIN = MAX AND at least one item is answered (to ignore fully missing cases)
    syntax.append(f"IF(#Min_Val = #Max_Val & ~miss({cols[0]})) {flag_name_max_str}=1.")
    syntax.append(f"EXECUTE.\n")
    
    # Clean up temporary variables
    syntax.append(f"DELETE VARIABLES #Min_Val #Max_Val.")
    syntax.append(f"EXECUTE.\n")

    return syntax, [flag_name_max_str]

# NEW FUNCTION: Configure Straightliner Rules
def configure_straightliner_rules():
    """Handles the configuration of Straightliner checks for rating grids."""
    st.subheader("2. Straightliner Check (Rating Grids) Configuration")
    
    with st.expander("➕ Add Straightliner Group Rule", expanded=False):
        straightliner_cols = st.multiselect("Select ALL Variables in the Rating Grid (Qx_1, Qx_2, ...)", st.session_state.all_cols, 
                                 key='straightliner_cols_select')
        
        if straightliner_cols:
            group_name = straightliner_cols[0].split('_')[0]
            
            with st.form(f"straightliner_form_{group_name}"):
                st.markdown(f"### ⚙️ Rule Configuration for Grid: **{group_name}**")
                
                # Straightlining is generally a 'Max' check (all same answer) for simplicity in SPSS.
                st.info(f"The rule will check if all items in the group **{group_name}** have the same value (e.g., all 5s) and flag it as `xx{group_name}_MaxStr=1`.")
                
                if st.form_submit_button("✅ Save Straightliner Group Rule"):
                    if len(straightliner_cols) > 1:
                        st.session_state.straightliner_rules.append({
                            'variables': straightliner_cols,
                            'group_name': group_name,
                        })
                        st.success(f"Straightliner Rule added for group **{group_name}**.")
                        st.rerun()
                    else:
                        st.warning("Please select at least two columns for the Straightliner check.")


# MQ functions remain here...
def generate_mq_spss_syntax(rule):
    """Generates detailed SPSS syntax for a Multi-Select check."""
    cols = rule['variables']
    mq_set_name = cols[0].split('_')[0] if cols else 'MQ_Set'
    mq_list_str = ' '.join(cols)
    calc_func = "SUM" if rule['count_method'] == "SUM" else "COUNT"
    mq_sum_var = f"{mq_set_name}_Count"

    syntax = []
    generated_flags = []
    
    # 1. Count Calculation
    syntax.append(f"**************************************MQ Count Calculation for Set: {mq_set_name} (Method: {calc_func})")
    syntax.append(f"COMPUTE {mq_sum_var} = {calc_func}({mq_list_str}).") 
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(mq_sum_var)
    
    # 2. Min/Max Count Check
    flag_min = f"{FLAG_PREFIX}{mq_set_name}_Min"
    syntax.append(f"**************************************MQ Minimum Count Check: {mq_set_name} (Min: {rule['min_count']})")
    syntax.append(f"IF({mq_sum_var} < {rule['min_count']} & ~miss({cols[0]})) {flag_min}=1.") 
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(flag_min)
    
    if rule['max_count'] and rule['max_count'] > 0:
        flag_max = f"{FLAG_PREFIX}{mq_set_name}_Max"
        syntax.append(f"**************************************MQ Maximum Count Check: {mq_set_name} (Max: {rule['max_count']})")
        syntax.append(f"IF({mq_sum_var} > {rule['max_count']}) {flag_max}=1.")
        syntax.append(f"EXECUTE.\n")
        generated_flags.append(flag_max)

    # 3. Exclusive Stub Check
    if rule['exclusive_col'] and rule['exclusive_col'] != 'None' and rule['exclusive_col'] in cols:
        flag_exclusive = f"{FLAG_PREFIX}{mq_set_name}_Exclusive"
        exclusive_value = 1 
        other_cols_str = ' '.join([c for c in cols if c != rule['exclusive_col']])
        syntax.append(f"**************************************MQ Exclusive Stub Check: {rule['exclusive_col']} vs Others")
        syntax.append(f"COMPUTE #Other_Count = SUM({other_cols_str}).")
        syntax.append(f"IF({rule['exclusive_col']}={exclusive_value} & #Other_Count > 0) {flag_exclusive}=1.")
        syntax.append("EXECUTE.\n")
        generated_flags.append(flag_exclusive)
        syntax.append("DELETE VARIABLES #Other_Count.\n") 

    # 4. Other Specify Check
    if rule.get('other_var') and rule['other_var'] != 'None' and rule.get('other_checkbox_col') and rule['other_checkbox_col'] != 'None':
         other_syntax, other_flags = generate_other_specify_spss_syntax(rule['other_checkbox_col'], rule['other_var'], rule['other_stub_val'])
         syntax.extend(other_syntax)
         generated_flags.extend(other_flags)

    # 5. Skip Logic (EoO/EoC) - uses the base question name as proxy
    if rule['run_skip'] and rule['trigger_col'] != '-- Select Variable --':
        target_col = mq_set_name 
        sl_syntax, sl_flags = generate_skip_spss_syntax(
            target_col, rule['trigger_col'], rule['trigger_val'], 'MQ'
        )
        syntax.extend(sl_syntax)
        generated_flags.extend(sl_flags)

    return syntax, generated_flags

def configure_mq_rules(all_variable_options):
    """Handles configuration of MQ rules."""
    st.subheader("3. Multi-Select Rule (MQ) Configuration")
    
    with st.expander("➕ Add Multi-Select Group Rule", expanded=False):
        mq_cols = st.multiselect("Select ALL Multi-Select Variables in the Group (Qx_1, Qx_2, ...)", st.session_state.all_cols, 
                                 key='mq_cols_select')
        
        if mq_cols:
            mq_set_name = mq_cols[0].split('_')[0]
            
            with st.form(f"mq_form_{mq_set_name}"):
                st.markdown(f"### ⚙️ Rule Configuration for Group: **{mq_set_name}**")
                
                # A. Count Check
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    min_count = st.number_input("Minimum Selections Required", min_value=0, value=1, key=f'mq_min_{mq_set_name}')
                with col_b:
                    max_count = st.number_input("Maximum Selections Allowed (0 for no max)", min_value=0, key=f'mq_max_{mq_set_name}')
                with col_c:
                    count_method = st.radio("SPSS Calculation Method", ["SUM", "COUNT"], index=0, key=f'mq_method_{mq_set_name}')
                
                # B. Exclusive Stub Check
                exclusive_col = st.selectbox("Select Exclusive Stub Variable (Optional)", ['None'] + mq_cols, key=f'mq_exclusive_{mq_set_name}')
                
                # C. Other Specify Check
                st.markdown("#### C. Other Specify Check (Requires a checkbox variable and a text variable)")
                col_o_chk, col_o_txt, col_o_stub = st.columns(3)
                with col_o_chk:
                    other_checkbox_col = st.selectbox("Checkbox Column for 'Other' (Qx_i)", ['None'] + mq_cols, key=f'mq_other_chk_{mq_set_name}')
                with col_o_txt:
                    other_var = st.selectbox("Corresponding 'Other Specify' Variable (Qx_OE/TEXT)", ['None'] + [c for c in all_variable_options if c != '-- Select Variable --'], key=f'mq_other_txt_{mq_set_name}')
                with col_o_stub:
                     other_stub_val = st.number_input("Stub Value for 'Other' (Usually 1)", min_value=1, value=1, key=f'mq_other_stub_{mq_set_name}')

                # D. Skip Logic
                st.markdown("#### D. Skip Logic Filter Condition (EoO/EoC Check)")
                
                existing_rule = next((r for r in st.session_state.mq_rules if r.get('variables') == mq_cols), {})

                run_skip_default = existing_rule.get('run_skip', False)
                skip_trigger_col_default = existing_rule.get('trigger_col') or '-- Select Variable --'
                skip_trigger_val_default = existing_rule.get('trigger_val') or '1'

                run_skip = st.checkbox(f"Enable Skip Logic Check (Creates Flag_Qx and xxQx=1/2)", value=run_skip_default, key=f'mq_run_skip_{mq_set_name}')
                
                if run_skip:
                    with st.container(border=True):
                        st.info(f"*Define the condition that means **{mq_set_name}** should have been answered (e.g., Q_Prev=1).")
                        col_t_col, col_t_val = st.columns(2)
                        with col_t_col:
                            skip_trigger_col = st.selectbox("**Filter/Trigger Variable** (e.g., Q0)", all_variable_options, 
                                                            index=all_variable_options.index(skip_trigger_col_default) if skip_trigger_col_default in all_variable_options else 0, key=f'mq_t_col_{mq_set_name}')
                        with col_t_val:
                            skip_trigger_val = st.text_input("**Filter Condition Value** (e.g., 1)", value=skip_trigger_val_default, key=f'mq_t_val_{mq_set_name}')
                else:
                    skip_trigger_col = '-- Select Variable --'
                    skip_trigger_val = '1'


                if st.form_submit_button("✅ Save MQ Group Rule"):
                    if mq_cols:
                        st.session_state.mq_rules.append({
                            'variables': mq_cols,
                            'min_count': min_count,
                            'max_count': max_count if max_count > 0 else None,
                            'exclusive_col': exclusive_col,
                            'count_method': count_method,
                            'other_var': other_var if other_var != 'None' and other_checkbox_col != 'None' else None,
                            'other_checkbox_col': other_checkbox_col if other_checkbox_col != 'None' else None,
                            'other_stub_val': other_stub_val,
                            'run_skip': run_skip and skip_trigger_col != '-- Select Variable --',
                            'trigger_col': skip_trigger_col,
                            'trigger_val': skip_trigger_val,
                        })
                        st.success(f"MQ Rule added for group starting with **{mq_cols[0]}**.")
                        st.rerun()
                    else:
                        st.warning("Please select columns for the MQ group.")

def generate_string_spss_syntax(rule):
    """
    Generates detailed SPSS syntax for a String check.
    """
    col = rule['variable']
    min_length = rule['min_length']
    
    syntax = []
    generated_flags = []

    # 1. Junk/Min Length Check 
    if min_length and min_length > 0:
        flag_length = f"{FLAG_PREFIX}{col}_Junk"
        syntax.append(f"**************************************String Junk Check: {col} (Min Length: {min_length} chars)")
        # Flag 1 if answered (not miss or '') AND length < min_length
        syntax.append(f"IF(~miss({col}) & {col}<>'' & LENGTH(RTRIM({col})) < {min_length}) {flag_length}=1.")
        syntax.append(f"EXECUTE.\n")
        generated_flags.append(flag_length)
    
    # 2. Explicit Missing Check (Only run if NO skip logic is enabled)
    if not rule['run_skip']:
        flag_missing = f"{FLAG_PREFIX}{col}_Miss"
        syntax.append(f"**************************************String Missing Check: {col} (Missing Mandatory Check)")
        # Flag 1 if missing or empty string
        syntax.append(f"IF({col}='') {flag_missing}=1.")
        syntax.append(f"EXECUTE.\n")
        generated_flags.append(flag_missing)
        
    # 3. Skip Logic (EoO/EoC) 
    if rule['run_skip'] and rule['trigger_col'] != '-- Select Variable --':
        sl_syntax, sl_flags = generate_skip_spss_syntax(
            col, rule['trigger_col'], rule['trigger_val'], 'String'
        )
        syntax.extend(sl_syntax)
        generated_flags.extend(sl_flags)
        
    return syntax, generated_flags
def configure_string_rules(all_variable_options):
    """
    FINAL LOCKED VERSION
    - OE Skip UI is OUTSIDE the form (Streamlit-safe)
    - Skip UI will NEVER disappear again
    """

    st.subheader("4. String / Open-End (OE) Configuration")

    # Step 1: Select OE variables
    selected = st.multiselect(
        "Select Open-End (OE) variables",
        st.session_state.all_cols,
        default=st.session_state.string_batch_vars
    )

    if st.button("Configure OE"):
        st.session_state.string_batch_vars = selected

    if not st.session_state.string_batch_vars:
        return

    # Loop through each OE variable
    for i, col in enumerate(st.session_state.string_batch_vars):

        st.markdown(f"### {col}")

        existing = next(
            (r for r in st.session_state.string_rules if r['variable'] == col),
            {}
        )

        key = f"oe_{i}"

        # ----------------------------
        # B. OE SKIP LOGIC (OUTSIDE FORM)
        # ----------------------------
        st.markdown("#### B. OE Skip Logic")

        run_skip = st.checkbox(
            "Enable OE Skip Logic",
            value=existing.get('run_skip', False),
            key=f"{key}_skip_ui"
        )

        if run_skip:
            c1, c2 = st.columns(2)
            with c1:
                trigger_col = st.selectbox(
                    "Parent / Controlling Question",
                    all_variable_options,
                    index=all_variable_options.index(existing.get('trigger_col'))
                    if existing.get('trigger_col') in all_variable_options else 0,
                    key=f"{key}_tcol_ui"
                )
            with c2:
                trigger_val = st.text_input(
                    "Trigger Value (e.g. 1, 99)",
                    value=existing.get('trigger_val', ''),
                    key=f"{key}_tval_ui"
                )
        else:
            trigger_col = '-- Select Variable --'
            trigger_val = ''

        # ----------------------------
        # A. JUNK CHECK + SAVE (FORM)
        # ----------------------------
        with st.form(f"oe_form_{i}"):

            st.markdown("#### A. Junk Answer Check")

            min_len = st.number_input(
                "Minimum Length (characters)",
                min_value=1,
                value=existing.get('min_length', 5),
                key=f"{key}_len_form"
            )

            if st.form_submit_button("Save OE Rule"):

                st.session_state.string_rules = [
                    r for r in st.session_state.string_rules
                    if r['variable'] != col
                ] + [{
                    'variable': col,
                    'min_length': min_len,
                    'run_skip': run_skip and trigger_col != '-- Select Variable --',
                    'trigger_col': trigger_col,
                    'trigger_val': trigger_val
                }]

                st.success(f"Saved OE rule for {col}")
                st.rerun()


# Ranking functions remain here...

def generate_ranking_spss_syntax(rule):
    """Generates detailed SPSS syntax for a Ranking check."""
    cols = rule['variables']
    min_rank = rule['min_rank']
    max_rank = rule['max_rank']
    rank_set_name = cols[0].split('_')[0] if cols else 'Rank_Set'
    rank_list_str = ' '.join(cols)
    
    syntax = []
    generated_flags = []
    
    # 1. Duplicate Rank Check
    flag_duplicate = f"{FLAG_PREFIX}{rank_set_name}_Dup"
    syntax.append(f"**************************************Ranking Duplicate Check: {rank_set_name}")
    syntax.append(f"COMPUTE {flag_duplicate} = 0.")
    syntax.append(f"LOOP #rank = {min_rank} TO {max_rank}.")
    syntax.append(f"  COUNT #rank_count = {rank_list_str} (#rank).")
    syntax.append(f"  IF(#rank_count > 1) {flag_duplicate}=1.")
    syntax.append(f"END LOOP.")
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(flag_duplicate)
    
    # 2. Rank Range Check
    flag_range_name = f"{FLAG_PREFIX}{rank_set_name}_Rng"
    syntax.append(f"**************************************Ranking Range Check: {rank_set_name} (Range: {min_rank} to {max_rank})")
    syntax.append(f"COMPUTE {flag_range_name} = 0.")
    for col in cols:
        syntax.append(f"IF(~miss({col}) & ~range({col},{min_rank},{max_rank})) {flag_range_name}=1.")
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(flag_range_name)
    
    # 3. Skip Logic (EoO/EoC) - uses the base variable name as proxy
    if rule['run_skip'] and rule['trigger_col'] != '-- Select Variable --':
        target_col = rank_set_name
        sl_syntax, sl_flags = generate_skip_spss_syntax(
            target_col, rule['trigger_col'], rule['trigger_val'], 'Ranking'
        )
        syntax.extend(sl_syntax)
        generated_flags.extend(sl_flags)
        
    return syntax, generated_flags

def generate_master_spss_syntax(sq_rules, mq_rules, ranking_rules, string_rules, straightliner_rules):
    """Generates the final .sps file by iterating over all stored rules."""
    all_syntax_blocks = []
    all_flag_cols = []
    
    # Process Rules
    for rule in sq_rules:
        syntax, flags = generate_sq_spss_syntax(rule)
        all_syntax_blocks.append(syntax)
        all_flag_cols.extend(flags)
        
    for rule in mq_rules:
        syntax, flags = generate_mq_spss_syntax(rule)
        all_syntax_blocks.append(syntax)
        all_flag_cols.extend(flags)
            
    for rule in ranking_rules:
        syntax, flags = generate_ranking_spss_syntax(rule)
        all_syntax_blocks.append(syntax)
        all_flag_cols.extend(flags)

    for rule in straightliner_rules: # Straightliner Rules
        syntax, flags = generate_straightliner_spss_syntax(rule['variables'])
        all_syntax_blocks.append(syntax)
        all_flag_cols.extend(flags)

    for rule in string_rules:
        syntax, flags = generate_string_spss_syntax(rule)
        all_syntax_blocks.append(syntax) # Use all_syntax_blocks, not all_syntax_cols
        all_flag_cols.extend(flags)


    # --- Master Syntax Compilation ---
    sps_content = []
    sps_content.append(f"*{'='*60}*")
    sps_content.append(f"* PYTHON-GENERATED DATA VALIDATION SCRIPT (KNOWLEDGEEXCEL FORMAT) *")
    sps_content.append(f"*{'='*60}*\n")
    sps_content.append("DATASET ACTIVATE ALL.")
    sps_content.append("\n* --- 0. INITIALIZE FLAGS --- *")
    
    unique_flag_names = sorted(list(set(all_flag_cols)))
    
    # Filter for flags that need initialization (excluding counts/temp vars)
    init_flags_0 = [f for f in unique_flag_names if f.startswith(FLAG_PREFIX) and not f.endswith(('_Count', '_Miss', '_Junk'))]
    intermediate_flags = [f for f in unique_flag_names if f.startswith('Flag_')]
    
    all_numeric_flags = init_flags_0 + intermediate_flags
    
    # String flags (which are numeric but may not have been in the original init_flags_0 list)
    string_flags = [f for f in unique_flag_names if f.endswith(('_Miss', '_Junk'))]
    all_numeric_flags.extend(string_flags)
    all_numeric_flags = sorted(list(set(all_numeric_flags)))
    
    if all_numeric_flags:
        sps_content.append(f"NUMERIC {'; '.join(all_numeric_flags)}.")
        
        # Initialize the final flags to 0
        if init_flags_0:
            sps_content.append(f"RECODE {'; '.join(init_flags_0)} (ELSE=0).") 
            
        # Initialize intermediate flags to 0
        if intermediate_flags:
            sps_content.append(f"RECODE {'; '.join(intermediate_flags)} (ELSE=0).") 

        # Initialize string flags to 0
        if string_flags:
            sps_content.append(f"RECODE {'; '.join(string_flags)} (ELSE=0).") 
            
    sps_content.append("EXECUTE.\n")
    
    # 1. Insert ALL detailed validation logic
    sps_content.append("\n\n* --- 1. DETAILED VALIDATION LOGIC --- *")
    sps_content.append("\n".join([item for sublist in all_syntax_blocks for item in sublist]))
    
    # 2. Add Value Labels & Master Flags
    sps_content.append("\n* --- 2. VALUE LABELS & VARIABLE INITIALIZATION --- *")
    
    for flag in unique_flag_names:
        
        if flag.startswith(FLAG_PREFIX) and flag.endswith(('_Rng', '_Any', '_OtherFwd', '_OtherRev', '_Min', '_Max', '_Dup', '_Miss', '_Junk', '_MaxStr')):
            # General 'Fail: Data Check' for non-EoO/EoC flags
            sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail: Data Check'.")
            
        elif flag.startswith(FLAG_PREFIX) and not flag.endswith('_Count'):
            # EoO/EoC flags (xxQx)
            sps_content.append(f"VALUE LABELS {flag} 0 'Pass' 1 'Fail: Error of Omission (EOO)' 2 'Fail: Error of Commission (EoC)'.")
        
        elif flag.startswith('Flag_'):
             # Intermediate skip filter flags
             sps_content.append(f"VALUE LABELS {flag} 0 'Pass/Filter Not Met' 1 'Filter Flag Met (Intermediate)'.") 
            
    sps_content.append("EXECUTE.\n")

    # 3. Compute a Master Reject Flag
    master_error_flags = [f for f in unique_flag_names if f.startswith(FLAG_PREFIX) or f.startswith('Flag_')]
    
    sps_content.append("\n* --- 3. MASTER REJECT COUNT COMPUTATION --- *")
    if master_error_flags:
        temp_flag_logic = []
        
        # Only count final error flags (xx prefix, excluding calculated counts)
        error_flags_to_count = [f for f in master_error_flags if f.startswith(FLAG_PREFIX) and not f.endswith('_Count')]
        
        if error_flags_to_count:
            sps_content.append("\n*--- Temporary Binary Flags for Counting ---*")
            
            # Use COMPUTE / IF for temporary flags to handle the mix of 0/1 and 0/1/2 flags correctly
            sps_content.append(f"NUMERIC {'; '.join([f'T_{f}' for f in error_flags_to_count])}.")
            
            for flag in error_flags_to_count:
                temp_name = f"T_{flag}"
                temp_flag_logic.append(f"IF({flag}>0) {temp_name}=1.") 
                temp_flag_logic.append(f"ELSE {temp_name}=0.")
            
            sps_content.extend(temp_flag_logic)
            sps_content.append("EXECUTE.\n")

            master_flag_logic = ' + '.join([f'T_{f}' for f in error_flags_to_count])
            
            sps_content.append(f"COMPUTE Master_Reject_Count = SUM({master_flag_logic}).")
            sps_content.append("VARIABLE LABELS Master_Reject_Count 'Total Validation Errors (DV)'.")
            sps_content.append("EXECUTE.")

            sps_content.append("\nDELETE VARIABLES T_*.")
            sps_content.append("EXECUTE.")
            
            sps_content.append("\n* --- 4. VALIDATION REPORT (Frequencies) --- *")
            sps_content.append(f"FREQUENCIES VARIABLES=Master_Reject_Count {'; '.join(error_flags_to_count)} /STATISTICS=COUNT MEAN.")
        
    return "\n".join(sps_content)


# --- UI Utility Functions ---

def clear_all_rules():
    st.session_state.sq_rules = []
    st.session_state.mq_rules = []
    st.session_state.ranking_rules = []
    st.session_state.string_rules = []
    st.session_state.straightliner_rules = [] 
    if 'sq_batch_vars' in st.session_state: del st.session_state.sq_batch_vars
    if 'mq_batch_vars' in st.session_state: del st.session_state.mq_batch_vars
    if 'ranking_batch_vars' in st.session_state: del st.session_state.ranking_batch_vars
    if 'string_batch_vars' in st.session_state: del st.session_state.string_batch_vars
    st.success("All rules cleared.")

def delete_rule(rule_type, index):
    """Deletes a single rule by type and index."""
    if rule_type == 'sq':
        del st.session_state.sq_rules[index]
    elif rule_type == 'mq':
        del st.session_state.mq_rules[index]
    elif rule_type == 'ranking':
        del st.session_state.ranking_rules[index]
    elif rule_type == 'string':
        del st.session_state.string_rules[index]
    elif rule_type == 'straightliner': 
        del st.session_state.straightliner_rules[index]
    st.rerun() 

def display_rules(rules, columns, header, rule_type):
    if rules:
        st.subheader(header)
        
        display_data = []
        for rule in rules:
            target_name = rule.get('variable') or (rule.get('variables', ['Group']) + [''])[0]
            display_row = {'Target Var': target_name}
            
            if rule_type == 'sq':
                display_row['Range'] = f"{rule['min_val']} to {rule['max_val']}"
                if 'other_var' in rule and rule['other_var'] and rule['other_var'] != '-- Select Variable --': display_row['Other Check'] = rule['other_var']
            
            if rule_type == 'mq':
                display_row['Count Check'] = f"{rule['min_count']} to {rule.get('max_count', 'MAX')}"
                if 'exclusive_col' in rule and rule['exclusive_col'] != 'None': display_row['Exclusive'] = rule['exclusive_col']
            
            if rule_type == 'string':
                display_row['Junk Length'] = rule['min_length']
            
            if rule_type == 'straightliner':
                display_row['Check Type'] = "Max Straightliner"
            
            # Skip/Piping Logic (Applies to SQ, MQ, String, Ranking)
            skip_info = ""
            if rule.get('run_skip') and rule.get('trigger_col') and rule.get('trigger_col') != '-- Select Variable --':
                 skip_info = f"Filter: {rule['trigger_col']}={rule['trigger_val']}"
            
            if rule.get('run_piping_check') and rule.get('piping_source_col') and rule.get('piping_source_col') != '-- Select Variable --':
                if skip_info:
                    skip_info += f" + Piping: {rule['piping_source_col']}"
                else:
                    skip_info = f"Piping: {rule['piping_source_col']}"
                    
            if skip_info: display_row['Skip/Piping Check'] = skip_info
            
            # Explicit Missing Check for String (if no skip is running)
            if rule_type == 'string' and not rule.get('run_skip'):
                 display_row['Missing Check'] = 'Mandatory'
            
            display_data.append(display_row)
            
        df_display = pd.DataFrame(display_data)
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        
        st.markdown("**Delete Individual Rule:**")
        num_rules = len(rules)
        cols_per_row = 5
        
        for i in range(0, num_rules, cols_per_row):
            current_cols = st.columns(min(cols_per_row, num_rules - i))
            for j in range(len(current_cols)):
                rule_index = i + j
                rule = rules[rule_index]
                key = f'delete_{rule_type}_{rule_index}_{time.time()}'
                target_name = rule.get('variable') or (rule.get('variables', ['Group']) + [''])[0]
                
                if current_cols[j].button(f"❌ {target_name}", key=key, help=f"Delete rule for {target_name}"):
                    delete_rule(rule_type, rule_index)
                 
        st.markdown("---")

# --- Main App Flow ---

st.header("Step 1: Upload Survey Data File (CSV, Excel, or SPSS)")

# UPDATED file uploader to include SPSS file types (.sav, .zsav)
uploaded_file = st.file_uploader(
    "Choose a Survey Data File", 
    type=['csv', 'xlsx', 'xls', 'sav', 'zsav'] 
)

if uploaded_file:

        # Use the new data loading function
        df_raw = load_data_file(uploaded_file)
        
        st.success(f"Loaded {len(df_raw)} rows and {len(df_raw.columns)} columns from **{uploaded_file.name}**.")
        st.session_state.all_cols = list(df_raw.columns)
        all_variable_options = ['-- Select Variable --'] + st.session_state.all_cols
        
        st.markdown("---")
        st.header("Step 2: Define Validation Rules")
        
        col_side_a, col_side_b = st.sidebar.columns(2)
        with col_side_a:
            st.sidebar.button("🗑️ Clear All Rules", on_click=clear_all_rules)
        with col_side_b:
            total_rules = len(st.session_state.sq_rules) + len(st.session_state.mq_rules) + len(st.session_state.ranking_rules) + len(st.session_state.string_rules) + len(st.session_state.straightliner_rules)
            st.sidebar.markdown(f"**Total Rules:** {total_rules}")
        
        # Display existing rules
        display_rules(st.session_state.sq_rules, ['variable'], "Current 1. Single Select (SQ) / Rating Rules", 'sq')
        display_rules(st.session_state.straightliner_rules, ['variables'], "Current 2. Straightliner (Grid) Rules", 'straightliner')
        display_rules(st.session_state.mq_rules, ['variables'], "Current 3. Multi-Select (MQ) Rules", 'mq')
        # Ranking Configuration is omitted for brevity but the generator is present
        # display_rules(st.session_state.ranking_rules, ['variables'], "Current Ranking Rules", 'ranking')
        display_rules(st.session_state.string_rules, ['variable'], "Current 4. String/OE Rules", 'string')


        # New Configuration UIs
        configure_sq_rules(all_variable_options)
        st.markdown("---")
        configure_straightliner_rules()
        st.markdown("---")
        configure_mq_rules(all_variable_options)
        st.markdown("---")
        configure_string_rules(all_variable_options)
        st.markdown("---")

        st.header("Step 3: Generate Master Syntax")
        
        total_rules = len(st.session_state.sq_rules) + len(st.session_state.mq_rules) + len(st.session_state.ranking_rules) + len(st.session_state.string_rules) + len(st.session_state.straightliner_rules)
        
        if total_rules > 0:
            
            # --- Generate Master Outputs ---
            master_spss_syntax = generate_master_spss_syntax(
                st.session_state.sq_rules, 
                st.session_state.mq_rules, 
                st.session_state.ranking_rules, 
                st.session_state.string_rules,
                st.session_state.straightliner_rules
            )
            
            st.success(f"Generated complete syntax for **{total_rules}** validation rules.")
            
            col_a, col_b = st.columns(2)
            
            with col_a:
                st.download_button(
                    label="⬇️ Download Master SPSS Syntax (.sps)",
                    data=master_spss_syntax,
                    file_name="master_validation_script_knowledgeexcel.sps",
                    mime="text/plain"
                )
            
            st.subheader("Preview of Generated Detailed SPSS Logic (Filter/Skip/Straightliner)")
            
            preview_syntax_list = []
            
            def get_syntax_for_preview(rule_list, generator_func, rule_type):
                if not rule_list: return False
                rule = rule_list[0] # Just take the first rule for preview
                
                # Straightliner check (different logic)
                if rule_type == 'straightliner':
                     syntax, _ = generator_func(rule['variables'])
                     preview_syntax_list.extend(syntax)
                     return True
                
                # Skip Logic / Piping / Other Checks
                if (rule.get('run_skip') or rule.get('run_piping_check')) and rule['trigger_col'] != '-- Select Variable --':
                    target = rule.get('variable') or rule['variables'][0].split('_')[0]
                    
                    if rule.get('run_piping_check') and rule.get('piping_source_col') != '-- Select Variable --':
                        target_clean = target.split('_')[0] if '_' in target else target
                        filter_flag = f"Flag_{target_clean}"
                        
                        sl_syntax = [
                            f"**************************************SQ Filter Flag for Skip/Piping: {filter_flag}",
                            f"* Filter for {target_clean}: {rule['trigger_col']} = {rule['trigger_val']}.",
                            f"IF({rule['trigger_col']} = {rule['trigger_val']}) {filter_flag}=1.",
                            f"EXECUTE.\n"
                        ]
                        
                        pipe_syntax, _ = generate_piping_spss_syntax(
                            target, filter_flag, rule['piping_source_col'], rule['piping_stub_val']
                        )
                        sl_syntax.extend(pipe_syntax)
                        preview_syntax_list.extend(sl_syntax)
                    
                    elif rule.get('run_skip'):
                        sl_type = 'SQ' if rule_type == 'sq' or rule_type == 'string' else 'MQ'
                        min_val = rule.get('min_val') if rule_type == 'sq' else None
                        max_val = rule.get('max_val') if rule_type == 'sq' else None
                        
                        sl_syntax, _ = generate_skip_spss_syntax(
                            target, 
                            rule['trigger_col'], 
                            rule['trigger_val'], 
                            sl_type, 
                            min_val, 
                            max_val
                        )
                        preview_syntax_list.extend(sl_syntax)

                    return True
                
                # Explicit Missing Check (String only)
                if rule_type == 'string' and not rule.get('run_skip'):
                    syntax, _ = generator_func(rule)
                    # Filter to just the missing check part
                    missing_check_syntax = [line for line in syntax if '_Miss' in line or '*' in line]
                    preview_syntax_list.extend(missing_check_syntax)
                    return True

                return False

            # Find the first rule of any type that has a detailed logic to show
            if not get_syntax_for_preview(st.session_state.straightliner_rules, generate_straightliner_spss_syntax, 'straightliner'):
                if not get_syntax_for_preview(st.session_state.sq_rules, generate_sq_spss_syntax, 'sq'):
                    if not get_syntax_for_preview(st.session_state.mq_rules, generate_mq_spss_syntax, 'mq'):
                        get_syntax_for_preview(st.session_state.string_rules, generate_string_spss_syntax, 'string')


            if preview_syntax_list:
                st.info("Showing preview of the detailed structure of a configured check:")
                preview_text = '\n'.join(preview_syntax_list[:40]) 
            else:
                st.info("No detailed logic configured. Showing top of file.")
                preview_text = '\n'.join(master_spss_syntax.split('\n')[:20]) 
            
            st.code(preview_text + "\n\n*(...Download the .sps file for the complete detailed syntax)*", language='spss')
            
        else:
            st.warning("Please define and add at least one validation rule in Step 2.")
            

    except Exception as e:
        # A clearer error message for the user after the fixes
        st.error(f"A critical error occurred during file processing or setup. Error: {e}")
        st.exception(e) # Show full traceback for debugging if needed