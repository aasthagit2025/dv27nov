import streamlit as st
import pandas as pd
import numpy as np
import io
import os 
import tempfile

# --- 1. CONFIGURATION ---
FLAG_PREFIX = "xx" 
# List of variables to COMPLETELY REMOVE from all dropdowns
SYSTEM_VARS = ['sys_respnum', 'status', 'duration', 'starttime', 'endtime', 'uuid', 'recordid', 'respid', 'index', 'id', 'status_code']

st.set_page_config(layout="wide", page_title="Survey Validation")
st.title("📊 Survey Data Validation (Fixed UI)")

# --- 2. INITIALIZE SESSION STATE (Pre-defining lists to stop buffering) ---
if 'all_cols' not in st.session_state: st.session_state.all_cols = []
if 'numeric_cols' not in st.session_state: st.session_state.numeric_cols = []
if 'string_cols' not in st.session_state: st.session_state.string_cols = []
if 'sq_rules' not in st.session_state: st.session_state.sq_rules = []
if 'string_rules' not in st.session_state: st.session_state.string_rules = []
if 'mq_rules' not in st.session_state: st.session_state.mq_rules = []
if 'sq_batch_vars' not in st.session_state: st.session_state.sq_batch_vars = []
if 'oe_batch_vars' not in st.session_state: st.session_state.oe_batch_vars = []

# --- 3. OPTIMIZED DATA LOADING (Calculates everything ONCE) ---
def process_data(uploaded_file):
    file_ext = os.path.splitext(uploaded_file.name)[1].lower()
    try:
        if file_ext == '.csv':
            df = pd.read_csv(uploaded_file)
        elif file_ext in ['.sav', '.zsav']:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
                tmp.write(uploaded_file.getbuffer())
                df = pd.read_spss(tmp.name, convert_categoricals=False)
            os.remove(tmp.name)
        else:
            df = pd.read_excel(uploaded_file)
        
        # 1. REMOVE SYSTEM VARIABLES IMMEDIATELY
        all_vars = [c for c in df.columns if c.lower() not in SYSTEM_VARS]
        
        # 2. SEPARATE TYPES ONCE (This stops the buffering in dropdowns)
        num_vars = []
        str_vars = []
        for col in all_vars:
            if df[col].dtype == 'object' or pd.api.types.is_string_dtype(df[col]):
                str_vars.append(col)
            else:
                num_vars.append(col)
        
        st.session_state.all_cols = all_vars
        st.session_state.numeric_cols = num_vars
        st.session_state.string_cols = str_vars
        return True
    except Exception as e:
        st.error(f"Error processing file: {e}")
        return False

# --- 4. THE UI (REVERTED TO 10DECAPP.PY STYLE) ---

st.header("Step 1: Upload Survey Data")
up_file = st.file_uploader("Upload CSV, Excel, or SPSS", type=['csv', 'xlsx', 'sav'])

if up_file:
    if not st.session_state.all_cols: # Only process if not already loaded
        process_data(up_file)

    if st.session_state.all_cols:
        st.success(f"Data Loaded: {len(st.session_state.all_cols)} variables (System variables removed)")
        
        st.header("Step 2: Define Validation Rules")
        
        # Original Tabs
        tab_sq, tab_oe, tab_mq, tab_final = st.tabs([
            "1. Single Select (SQ)", "2. Open Ends (OE)", "3. Multi-Select (MQ)", "4. Generate Syntax"
        ])

        with tab_sq:
            st.subheader("Numeric/Rating Validation")
            # ONLY shows numeric variables - NO buffering because list is pre-calculated
            sq_sel = st.multiselect("Select Target Variables (Numeric Only)", 
                                   st.session_state.numeric_cols, 
                                   default=st.session_state.sq_batch_vars)
            
            if st.button("Configure Selected SQ"):
                st.session_state.sq_batch_vars = sq_sel

            if st.session_state.sq_batch_vars:
                with st.form("sq_form"):
                    for col in st.session_state.sq_batch_vars:
                        st.markdown(f"**Settings for {col}**")
                        c1, c2, c3, c4 = st.columns(4)
                        mi = c1.number_input(f"Min {col}", 1, key=f"mi_{col}")
                        ma = c2.number_input(f"Max {col}", 5, key=f"ma_{col}")
                        # Filtered Trigger List (No system variables)
                        tr = c3.selectbox(f"Trigger {col}", ["-- Select --"] + st.session_state.all_cols, key=f"tr_{col}")
                        tv = c4.text_input(f"Value {col}", "1", key=f"tv_{col}")
                        if st.form_submit_button(f"Save {col}"):
                            st.session_state.sq_rules.append({'var': col, 'min': mi, 'max': ma, 'trig': tr, 'val': tv})

        with tab_oe:
            st.subheader("String/Open-End Validation")
            # ONLY shows string variables
            oe_sel = st.multiselect("Select Open-End Variables (String Only)", 
                                   st.session_state.string_cols, 
                                   default=st.session_state.oe_batch_vars)
            
            if st.button("Configure OE"):
                st.session_state.oe_batch_vars = oe_sel

            if st.session_state.oe_batch_vars:
                for col in st.session_state.oe_batch_vars:
                    with st.form(f"oe_form_{col}"):
                        st.write(f"**OE Check: {col}**")
                        c1, c2 = st.columns(2)
                        tr = c1.selectbox("Parent Question", ["-- Select --"] + st.session_state.all_cols, key=f"ot_{col}")
                        tv = c2.text_input("Trigger Value", "1", key=f"ov_{col}")
                        if st.form_submit_button(f"Save Rule for {col}"):
                            st.session_state.string_rules.append({'var': col, 'trig': tr, 'val': tv})

        with tab_mq:
            st.subheader("Multi-Select (Smart Grouping)")
            # Auto-detect prefixes like Q1, A4
            prefixes = sorted(list(set([c.split('_')[0] for c in st.session_state.all_cols if '_' in c])))
            sel_prefix = st.selectbox("Select Question Prefix (e.g., Q1)", ["-- Select --"] + prefixes)
            
            suggested = [c for c in st.session_state.all_cols if c.startswith(sel_prefix)] if sel_prefix != "-- Select --" else []
            mq_vars = st.multiselect("Confirm MQ Variables", st.session_state.all_cols, default=suggested)
            
            if mq_vars and st.button("Add MQ Group Rule"):
                st.session_state.mq_rules.append({'vars': mq_vars, 'name': sel_prefix})
                st.success(f"Added group {sel_prefix}")

        with tab_final:
            st.header("Step 3: Generate Syntax")
            if st.button("Generate Master SPSS Syntax"):
                syntax = ["* FINAL SPSS VALIDATION\n", "SET DECIMAL=DOT.\n"]
                # Logic for SQ
                for r in st.session_state.sq_rules:
                    syntax.append(f"IF(miss({r['var']}) | ~range({r['var']},{r['min']},{r['max']})) {FLAG_PREFIX}{r['var']}_Rng=1.")
                # Logic for OE
                for r in st.session_state.string_rules:
                    syntax.append(f"IF({r['var']} = '' | miss({r['var']})) {FLAG_PREFIX}{r['var']}_Str=1.")
                
                final_code = "\n".join(syntax + ["EXECUTE."])
                st.code(final_code, language="spss")
                st.download_button("Download .sps", final_code, "validation.sps")

        if st.sidebar.button("🗑️ Clear All Rules"):
            for k in ['sq_rules', 'string_rules', 'mq_rules', 'sq_batch_vars', 'oe_batch_vars']:
                st.session_state[k] = []
            st.rerun()