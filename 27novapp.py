import streamlit as st
import pandas as pd
import numpy as np
import io
import time # Used for unique keys for delete buttons only

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
    This function strictly adheres to the user's requested syntax structure.
    """
    if '_' in target_col:
        target_clean = target_col.split('_')[0]
    else:
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
        eoc_condition = f"~miss({target_col})" # If not missing, it was answered
    elif rule_type == 'String':
        # EoO for String: Missing OR empty string
        eoo_condition = f"({target_col}='' | miss({target_col}))"
        eoc_condition = f"{target_col}<>''" # For String OE, check if it's not empty
    else:
        # EoO for MQ/Ranking/General: Just check for missing (use miss() on the first variable)
        eoo_condition = f"miss({target_col})"
        eoc_condition = f"~miss({target_col})" # Check if data is present
        
    # --- EoO/EoC Logic ---
    syntax.append(f"**************************************SKIP LOGIC EoO/EoC CHECK: {target_col} -> {final_error_flag}")
    
    # Error of Omission (EoO) - Flag=1: Trigger Met (Flag_Qx=1), Target Fails Check (EoO condition)
    # IF(Flag_Q1=1 & (miss(Q1) | ~range(Q1,1,10)))xxQ1=1.
    syntax.append(f"COMMENT EoO (1): Trigger Met ({filter_flag}=1), Target Fails Check/Missing/Out-of-Range.")
    syntax.append(f"IF({filter_flag} = 1 & {eoo_condition}) {final_error_flag}=1.")
    
    # Error of Commission (EoC) - Flag=2: Trigger NOT Met AND Target Answered (EoC condition)
    # IF((Flag_Q1<>1 | miss(Flag_Q1)) & ~miss(Q1))xxQ1=2.
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
    syntax.append(f"COMMENT EoO (1): Piping/Skip met, Target value is wrong/missing.")
    syntax.append(f"IF(({overall_skip_filter_flag}=1) & ({piping_source_col}={piping_stub_val}) & {target_col}<>{piping_stub_val}) {flag_col}=1.")
    
    # 2. Error of Commission (EOC / Reverse Condition) - Target has data when piping condition is NOT met
    # Condition: (Overall Skip NOT met OR Piping NOT met) AND Target has data
    syntax.append(f"**************************************PIPING (EOC / Reverse) Check: (Filter NOT met OR Piping NOT met) AND {target_col} is answered")
    syntax.append(f"COMMENT EoC (2): Skip/Piping not met, Target value is wrongly answered.")
    
    # EOC Condition: (Flag_Qx<>1 OR miss(Flag_Qx) OR Q_source<>i OR miss(Q_source)) AND ~miss(Target)
    eoc_condition = f"({overall_skip_filter_flag}<>1 | miss({overall_skip_filter_flag}) | {piping_source_col}<>{piping_stub_val} | miss({piping_source_col})) & ~miss({target_col})"
    syntax.append(f"IF({eoc_condition}) {flag_col}=2.")
    syntax.append(f"EXECUTE.\n")
    
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

    # 1. Missing/Range Check (Only if no piping is run, otherwise piping handles EOO/EOC for sub-variables)
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
    
    # A. Generate Filter Flag and Run Checks if EITHER Skip or Piping is enabled
    if (rule['run_skip'] or rule['run_piping_check']) and rule['trigger_col'] != '-- Select Variable --':
        
        # B. Piping/Reverse Condition Check (Requires Filter Flag to be present)
        if rule['run_piping_check']:
            
            # Since Piping is run, we must generate the filter flag here first if it wasn't already generated by standard skip
            trigger_col = rule['trigger_col']
            trigger_val = rule['trigger_val']
            syntax.append(f"**************************************SQ Filter Flag for Skip/Piping: {filter_flag}")
            syntax.append(f"COMMENT Filter for {target_clean}: {trigger_col} = {trigger_val}.")
            syntax.append(f"IF({trigger_col} = {trigger_val}) {filter_flag}=1.")
            syntax.append(f"EXECUTE.\n")
            generated_flags.append(filter_flag)
            
            pipe_syntax, pipe_flags = generate_piping_spss_syntax(
                col, filter_flag, rule['piping_source_col'], rule['piping_stub_val']
            )
            syntax.extend(pipe_syntax)
            generated_flags.extend(pipe_flags)
        
        # C. Standard Skip Logic (EoO/EoC) - Only if Piping is NOT run on this specific variable
        # If piping is run, the piping logic handles EOO/EOC for the sub-question.
        elif rule['run_skip']:
            # Use the refined skip logic function which creates the Flag_Qx and xxQx flag.
            sl_syntax, sl_flags = generate_skip_spss_syntax(
                col, rule['trigger_col'], rule['trigger_val'], 'SQ', rule['min_val'], rule['max_val']
            )
            syntax.extend(sl_syntax)
            generated_flags.extend(sl_flags)
        
    return syntax, generated_flags 

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
    syntax.append(f"**************************************MQ Minimum Count Check: {mq_set_name} (Min: