import streamlit as st
import pandas as pd
import numpy as np
import io
import time 

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
if 'all_cols' not in st.session_state:
    st.session_state.all_cols = []
    
# --- CORE UTILITY FUNCTIONS (SYNTAX GENERATION) ---

def generate_skip_spss_syntax(target_col, trigger_col, trigger_val, rule_type, range_min=None, range_max=None):
    """
    Generates detailed SPSS syntax for Skip Logic (Error of Omission/Commission)
    using the two-stage process: Flag_Qx (intermediate filter) -> xxQx (final EoO/EoC flag).
    This function strictly adheres to the user's requested syntax structure (IF(Q0=1)Flag_Q1=1. EXECUTE.)
    """
    if '_' in target_col:
        # Use only the base question name for the Flag_ and final xx-flag, e.g., Q12_1 -> Q12
        target_clean = target_col.split('_')[0]
    else:
        # Use the question name itself
        target_clean = target_col
        
    filter_flag = f"Flag_{target_clean}" 
    # Use the base question name for the final flag, e.g., xxQ1
    final_error_flag = f"{FLAG_PREFIX}{target_clean}" 
    
    syntax = []
    
    # Stage 1: Filter Flag (Flag_Qx) - Identifies who should have seen the question (Matches user example)
    syntax.append(f"**************************************SKIP LOGIC FILTER FLAG: {trigger_col}={trigger_val} -> {target_clean}")
    syntax.append(f"COMMENT Qx should ONLY be asked if {trigger_col} = {trigger_val}.")
    syntax.append(f"IF({trigger_col} = {trigger_val}) {filter_flag}=1.")
    syntax.append(f"EXECUTE.\n") # Matches user's example
    
    # Determine the EoO condition for the target variable
    if rule_type == 'SQ' and range_min is not None and range_max is not None:
        # EoO for SQ: Missing OR answered but OUT of the valid range (Matches user example)
        eoo_condition = f"(miss({target_col}) | ~range({target_col},{range_min},{range_max}))"
        # EoC for SQ: If not missing, it was answered
        eoc_condition = f"~miss({target_col})" 
        
    elif rule_type == 'String':
        # EoO for String: Missing OR empty string (Matches user's simpler check for OE)
        eoo_condition = f"({target_col}='' | miss({target_col}))"
        # EoC for String: Target Answered (Not empty string AND not system missing)
        eoc_condition = f"({target_col}<>'' & ~miss({target_col}))" 
        
    else: # MQ/Ranking/General
        # EoO for MQ/Ranking/General: Just check for missing (use miss() on the single variable proxy)
        eoo_condition = f"miss({target_col})"
        # EoC: Check if data is present
        eoc_condition = f"~miss({target_col})" 
        
    # --- EoO/EoC Logic ---
    syntax.append(f"**************************************SKIP LOGIC EoO/EoC CHECK: {target_col} -> {final_error_flag}")
    
    # Error of Omission (EoO) - Flag=1: Trigger Met (Flag_Qx=1), Target Fails Check (EoO condition)
    # IF(Flag_Q1=1 & (miss(Q1) | ~range(Q1,1,10)))xxQ1=1. (Matches user's example logic)
    syntax.append(f"COMMENT EoO (1): Trigger Met ({filter_flag}=1), Target Fails Check/Missing/Out-of-Range/Empty.")
    syntax.append(f"IF({filter_flag} = 1 & {eoo_condition}) {final_error_flag}=1.")
    
    # Error of Commission (EoC) - Flag=2: Trigger NOT Met AND Target Answered (EoC condition)
    # IF((Flag_Q1<>1 | miss(Flag_Q1)) & ~miss(Q1))xxQ1=2. (Matches user's example logic)
    syntax.append(f"COMMENT EoC (2): Trigger Not Met ({filter_flag}<>1 | miss({filter_flag})), Target Answered.")
    syntax.append(f"IF(({filter_flag} <> 1 | miss({filter_flag})) & {eoc_condition}) {final_error_flag}=2.")
    
    syntax.append("EXECUTE.\n")
    
    return syntax, [filter_flag, final_error_flag]


def generate_other_specify_spss_syntax(main_col, other_col, other_stub_val):
    """
    Generates syntax for Other-Specify checks (Both forward and reverse conditions).
    """
    syntax = []
    # Use the main variable's base name for the flags
    if '_' in main_col:
        main_clean = main_col.split('_')[0]
    else:
        main_clean = main_col
        
    flag_name_fwd = f"{FLAG_PREFIX}{main_clean}_OtherFwd"
    flag_name_rev = f"{FLAG_PREFIX}{main_clean}_OtherRev"
    
    # Forward Check (Main selected, Other is empty/missing) - EoO type check
    syntax.append(f"**************************************OTHER SPECIFY (Forward) Check: {main_col}={other_stub_val} AND {other_col} is missing/blank")
    syntax.append(f"COMMENT EoO (1): Main selected ({main_col}={other_stub_val}), Other is missing/blank.")
    syntax.append(f"IF({main_col}={other_stub_val} & ({other_col}='' | miss({other_col}))) {flag_name_fwd}=1.")
    syntax.append(f"EXECUTE.\n")
    
    # Reverse Check (Other answered, Main not selected) - EoC type check
    syntax.append(f"**************************************OTHER SPECIFY (Reverse) Check: {other_col} has data AND {main_col}<>{other_stub_val}")
    syntax.append(f"COMMENT EoC (2): Other has data (~miss({other_col}) & {other_col}<>''), Main not selected.")
    syntax.append(f"IF(~miss({other_col}) & {other_col}<>'' & {main_col}<>{other_stub_val}) {flag_name_rev}=1.")
    syntax.append(f"EXECUTE.\n")
    
    return syntax, [flag_name_fwd, flag_name_rev]

def generate_piping_spss_syntax(target_col, overall_skip_filter_flag, piping_source_col, piping_stub_val):
    """
    Generates syntax for the Rating Piping/Reverse Condition check (Qx_i must equal i if Q_source=i),
    integrated with the overall Skip Filter Flag (Flag_Qx). (Matches user example)
    """
    syntax = []
    
    flag_col = f"{FLAG_PREFIX}{target_col}" # Use the target variable itself as the flag (1=EOO, 2=EOC)
    
    # 1. Error of Omission (EOO) - Target is missing/wrong when piping condition is met
    # Condition: (Overall Skip Met AND Piping met AND Target is not the expected value)
    syntax.append(f"**************************************PIPING (EOO) Check: (Filter={overall_skip_filter_flag}=1) AND ({piping_source_col}={piping_stub_val}) AND {target_col}<>{piping_stub_val}")
    syntax.append(f"COMMENT EoO (1): Piping/Skip met, Target value is wrong/missing. IF(((Flag_Q12=1) & Q11=1 ) & Q12_1<>1)xxQ12_1=1.")
    # Note: Using {target_col}<>{piping_stub_val} catches both missing and wrong values.
    syntax.append(f"IF(({overall_skip_filter_flag}=1) & ({piping_source_col}={piping_stub_val}) & {target_col}<>{piping_stub_val}) {flag_col}=1.")
    
    # 2. Error of Commission (EOC / Reverse Condition) - Target has data when piping condition is NOT met
    # Condition: (Overall Skip NOT met OR Piping NOT met) AND Target has data
    syntax.append(f"**************************************PIPING (EOC / Reverse) Check: (Filter NOT met OR Piping NOT met) AND {target_col} is answered")
    syntax.append(f"COMMENT EoC (2): Skip/Piping not met, Target value is wrongly answered. IF((Flag_Q12<>1 | miss(Flag_Q12) | Q11<>1 | miss(Q11)) & ~miss(Q12_1))xxQ12_1=2.")
    
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
    
    # Use the base question name for the filter flag, e.g., if col=Q12_1, target_clean=Q12
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
        # Flag if: Missing OR answered but OUT of the valid range
        syntax.append(f"IF(miss({col}) | ~range({col},{min_val},{max_val})) {flag_name}=1.")
        syntax.append(f"EXECUTE.\n")
        generated_flags.append(flag_name)
    
    # 2. Specific Stub Check (ANY)
    if required_stubs_list:
        stubs_str = ', '.join(map(str, required_stubs_list))
        flag_any = f"{FLAG_PREFIX}{col}_Any"
        syntax.append(f"**************************************SQ Specific Stub Check (Not IN Acceptable List): {col} (Accept: {stubs_str})")
        # Flag if: Not missing AND NOT in the acceptable list
        syntax.append(f"IF(~miss({col}) & NOT(any({col}, {stubs_str}))) {flag_any}=1.")
        syntax.append(f"EXECUTE.\n")
        generated_flags.append(flag_any)

    # 3. Other Specify Check
    if rule.get('other_var') and rule['other_var'] != '-- Select Variable --':
        other_syntax, other_flags = generate_other_specify_spss_syntax(col, rule['other_var'], rule['other_stub_val'])
        syntax.extend(other_syntax)
        generated_flags.extend(other_flags)

    # --- Combined Skip/Piping Checks ---
    
    # A. Check if EITHER Skip or Piping is enabled AND a trigger is defined
    if (rule['run_skip'] or rule['run_piping_check']) and rule['trigger_col'] != '-- Select Variable --':
        
        trigger_col = rule['trigger_col']
        trigger_val = rule['trigger_val']
        
        # B. Generate Filter Flag (Flag_Qx)
        # This is needed whether running skip or piping
        syntax.append(f"**************************************SQ Filter Flag for Skip/Piping: {filter_flag}")
        syntax.append(f"COMMENT Filter for {target_clean}: {trigger_col} = {trigger_val}.")
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
        # If piping is run, the piping logic handles EOO/EOC for the sub-question.
        elif rule['run_skip']:
            # Use the refined skip logic function which creates the Flag_Qx and xxQx flag.
            sl_syntax, sl_flags = generate_skip_spss_syntax(
                col, trigger_col, trigger_val, 'SQ', min_val, max_val
            )
            syntax.extend(sl_syntax)
            generated_flags.extend(sl_flags)
        
    return syntax, generated_flags 

def configure_sq_rules(all_variable_options):
    """Handles batch selection and sequential configuration of SQ rules."""
    st.subheader("1. Single Select / Rating Rule (SQ) Configuration")
    
    # 1. Batch Selection
    sq_cols = st.multiselect("Select ALL Target Variables (Qx, Qx_i) for Single Select/Rating", st.session_state.all_cols, 
                             key='sq_batch_select_key', 
                             default=st.session_state.get('sq_batch_vars', []))
    
    if st.button("Start/Update SQ Rule Configuration", key='start_sq_config_btn'):
        st.session_state.sq_batch_vars = sq_cols
        
    st.markdown("---")
    
    # 2. Sequential Configuration
    if st.session_state.get('sq_batch_vars'):
        st.info(f"Configuring **{len(st.session_state.sq_batch_vars)}** selected SQ variables one-by-one below.")
        
        sq_config_form_key = 'sq_config_form'
        with st.form(sq_config_form_key):
            new_sq_rules = []
            
            for i, col in enumerate(st.session_state.sq_batch_vars):
                st.markdown(f"### ⚙️ Rule Configuration for **{col}** (Variable {i+1}/{len(st.session_state.sq_batch_vars)})")
                
                # Retrieve existing rule values if available to pre-fill the form
                existing_rule = next((r for r in st.session_state.sq_rules if r['variable'] == col), {})
                
                # Use a deterministic key prefix for widgets within the form
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
                
                # 1. Define the Filter/Trigger Variable and Value (Used by both C and D)
                skip_trigger_col_default = existing_rule.get('trigger_col') or '-- Select Variable --'
                skip_trigger_val_default = existing_rule.get('trigger_val') or '1'
                
                col_t_col, col_t_val = st.columns(2)
                with col_t_col:
                    # *** FIXED: This variable selection is now available for all SQ rules ***
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
                            # Attempt to auto-detect the stub value from Qx_i name, e.g., Q12_3 -> 3
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
                # Clear existing rules for the variables being reconfigured (simple replace strategy)
                existing_vars_to_keep = [r for r in st.session_state.sq_rules if r['variable'] not in st.session_state.sq_batch_vars]
                
                # Add new rules
                for rule in new_sq_rules:
                    # Overwrite existing or append new
                    existing_vars_to_keep.append(rule)
                    
                st.session_state.sq_rules = existing_vars_to_keep
                    
                st.success(f"Successfully saved {len(new_sq_rules)} SQ rules.")
                st.session_state.sq_batch_vars = [] # Clear the batch variables to reset the form
                st.rerun()
            else:
                st.markdown("Submit the form above to save the configured rules.")

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
    syntax.append(f"IF({mq_sum_var} < {rule['min_count']} & ~miss({cols[0]})) {flag_min}=1.") # Only flag if the group is not entirely missing (using first variable as proxy)
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
        # If exclusive stub is selected, the count of *other* stubs must be 0
        other_cols_str = ' '.join([c for c in cols if c != rule['exclusive_col']])
        syntax.append(f"**************************************MQ Exclusive Stub Check: {rule['exclusive_col']} vs Others")
        # Check if exclusive is selected (1) AND the SUM of all other columns is > 0
        syntax.append(f"COMPUTE #Other_Count = SUM({other_cols_str}).")
        syntax.append(f"IF({rule['exclusive_col']}={exclusive_value} & #Other_Count > 0) {flag_exclusive}=1.")
        syntax.append("EXECUTE.\n")
        generated_flags.append(flag_exclusive)
        syntax.append("DELETE VARIABLES #Other_Count.\n") # Cleanup

    # 4. Other Specify Check
    if rule.get('other_var') and rule['other_var'] != 'None' and rule.get('other_checkbox_col') and rule['other_checkbox_col'] != 'None':
         other_syntax, other_flags = generate_other_specify_spss_syntax(rule['other_checkbox_col'], rule['other_var'], rule['other_stub_val'])
         syntax.extend(other_syntax)
         generated_flags.extend(other_flags)

    # 5. Skip Logic (EoO/EoC) - uses the base question name as proxy
    if rule['run_skip'] and rule['trigger_col'] != '-- Select Variable --':
        # The target_col for skip logic on an MQ is the base name (Qx)
        target_col = mq_set_name 
        # Use the refined skip logic function which creates the Flag_Qx and xxQx flag.
        sl_syntax, sl_flags = generate_skip_spss_syntax(
            target_col, rule['trigger_col'], rule['trigger_val'], 'MQ'
        )
        syntax.extend(sl_syntax)
        generated_flags.extend(sl_flags)

    return syntax, generated_flags

def configure_mq_rules(all_variable_options):
    """Handles batch selection and sequential configuration of MQ rules (currently one rule per group)."""
    st.subheader("2. Multi-Select Rule (MQ) Configuration")
    
    # MQ is still best handled per group since counts/exclusives apply to the whole group.
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
                        st.info(f"Define the condition that means **{mq_set_name}** should have been answered (e.g., Q_Prev=1).")
                        col_t_col, col_t_val = st.columns(2)
                        with col_t_col:
                            # *** FIXED: This variable selection is now available for MQ rules ***
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

def configure_string_rules(all_variable_options):
    """Handles batch selection and sequential configuration of String rules."""
    st.subheader("3. String/Open-End Rule Configuration")
    
    # 1. Batch Selection
    string_cols = st.multiselect("Select ALL Target Variables (Qx_OE/TEXT) for String/Open-End", st.session_state.all_cols, 
                             key='string_batch_select_key',
                             default=st.session_state.get('string_batch_vars', []))
    
    if st.button("Start/Update String Rule Configuration", key='start_string_config_btn'):
        st.session_state.string_batch_vars = string_cols
        
    st.markdown("---")
    
    # 2. Sequential Configuration
    if st.session_state.get('string_batch_vars'):
        st.info(f"Configuring **{len(st.session_state.string_batch_vars)}** selected String variables one-by-one below. (Note: String skip logic uses `xxQx=1/2` flag.)")
        
        string_config_form_key = 'string_config_form'
        with st.form(string_config_form_key):
            new_string_rules = []
            
            for i, col in enumerate(st.session_state.string_batch_vars):
                st.markdown(f"### ⚙️ Rule Configuration for **{col}** (Variable {i+1}/{len(st.session_state.string_batch_vars)})")
                key_prefix = f'string_{col}_{i}'
                existing_rule = next((r for r in st.session_state.string_rules if r['variable'] == col), {})
                
                # A. Length Check
                st.markdown("#### A. Length & Missing Check")
                min_length = st.number_input("Minimum Non-Junk Length (e.g., 5 characters) - Flags if answered but too short", min_value=1, value=existing_rule.get('min_length', 5), key=f'{key_prefix}_min_len')
                
                # B. Skip Logic (EoO/EoC)
                st.markdown("#### B. Skip Logic Filter Condition (EoO/EoC Check)")
                run_skip_default = existing_rule.get('run_skip', False)
                
                skip_trigger_col_default = existing_rule.get('trigger_col') or '-- Select Variable --'
                skip_trigger_val_default = existing_rule.get('trigger_val') or '1'
                
                run_skip = st.checkbox("Enable Standard Skip Logic Check (Creates Flag_Qx and xxQx=1/2)", value=run_skip_default, key=f'{key_prefix}_run_skip')
                
                if run_skip:
                    with st.container(border=True):
                        st.info(f"Define the condition that means **{col}** should have been answered (e.g., Q_Prev=2).")
                        col_t_col, col_t_val = st.columns(2)
                        with col_t_col:
                            # *** FIXED: This variable selection is now available for String rules ***
                            skip_trigger_col = st.selectbox("**Filter/Trigger Variable** (e.g., Q0)", all_variable_options, 
                                                            index=all_variable_options.index(skip_trigger_col_default) if skip_trigger_col_default in all_variable_options else 0, 
                                                            key=f'{key_prefix}_t_col')
                        with col_t_val:
                            skip_trigger_val = st.text_input("**Filter Condition Value** (e.g., 2)", value=skip_trigger_val_default, key=f'{key_prefix}_t_val')
                else:
                    skip_trigger_col = '-- Select Variable --'
                    skip_trigger_val = '1'

                st.markdown("---")
                
                # Construct the rule dictionary
                new_string_rules.append({
                    'variable': col,
                    'min_length': min_length,
                    'run_skip': run_skip and skip_trigger_col != '-- Select Variable --',
                    'trigger_col': skip_trigger_col,
                    'trigger_val': skip_trigger_val,
                })
            
            if st.form_submit_button("✅ Save ALL Configured String Rules"):
                # Clear existing rules for the variables being reconfigured
                existing_vars_to_keep = [r for r in st.session_state.string_rules if r['variable'] not in st.session_state.string_batch_vars]
                
                # Add new rules
                for rule in new_string_rules:
                    existing_vars_to_keep.append(rule)
                    
                st.session_state.string_rules = existing_vars_to_keep
                    
                st.success(f"Successfully saved {len(new_string_rules)} String rules.")
                st.session_state.string_batch_vars = []
                st.rerun()
            else:
                st.markdown("Submit the form above to save the configured rules.")

# Omitted Ranking rule configuration UI for brevity, but the generator function is present
# def configure_ranking_rules(all_variable_options):
#    ...

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
    # The loop condition must check from min to max Ranks (e.g., 1 to 3), not the number of columns.
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
        # Check if answered but out of range
        syntax.append(f"IF(~miss({col}) & ~range({col},{min_rank},{max_rank})) {flag_range_name}=1.")
    syntax.append(f"EXECUTE.\n")
    generated_flags.append(flag_range_name)
    
    # 3. Skip Logic (EoO/EoC) - uses the base variable name as proxy