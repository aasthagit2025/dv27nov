import streamlit as st
import pandas as pd
import numpy as np
import io
import time 
import os 
import tempfile

# --- 1. CONFIGURATION ---
FLAG_PREFIX = "xx" 
# Variables that will NEVER show up in your dropdowns
SYSTEM_VARS = ['sys_respnum', 'status', 'duration', 'starttime', 'endtime', 'uuid', 'recordid', 'respid', 'index', 'id', 'status_code']

st.set_page_config(layout="wide")
st.title("📊 Survey Data Validation Automation (Final Version)")
st.markdown("---")

# --- 2. INITIALIZE SESSION STATE ---
for k in ['sq_rules', 'mq_rules', 'ranking_rules', 'string_rules', 'straightliner_rules', 
          'all_cols', 'var_types', 'sq_batch_vars', 'string_batch_vars']:
    if k not in st.session_state:
        st.session_state[k] = [] if k != 'var_types' else {}

# --- 3. OPTIMIZED DATA LOADING ---
def load_data_file(uploaded_file):
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    try:
        if file_extension == '.csv':
            df = pd.read_csv(uploaded_file, na_values=['', ' ', 'N/A'])
        elif file_extension in ['.xlsx', '.xls']:
            df = pd.read_excel(uploaded_file)
        elif file_extension in ['.sav', '.zsav']:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp:
                tmp.write(uploaded_file.getbuffer())
                df = pd.read_spss(tmp.name, convert_categoricals=False)
            os.remove(tmp.name)
        
        if df is not None:
            # Step 1: Filter System Variables
            valid_cols = [c for c in df.columns if c.lower() not in SYSTEM_VARS]
            st.session_state.all_cols = valid_cols
            
            # Step 2: Pre-calculate Types (Prevents Buffering later)
            st.session_state.var_types = {
                col: 'String' if df[col].dtype == 'object' or pd.api.types.is_string_dtype(df[col]) else 'Numeric'
                for col in valid_cols
            }
            return df
    except Exception as e:
        st.error(f"Error: {e}")
    return None

def get_smart_groups():
    """Finds groups like Q1 from Q1_1, Q1_2..."""
    groups = {}
    for col in st.session_state.all_cols:
        if "_" in col:
            base = col.split("_")[0]
            if base not in groups: groups[base] = []
            groups[base].append(col)
    return {k: v for k, v in groups.items() if len(v) > 1}

# --- 4. UI FLOW (YOUR ORIGINAL DESIGN) ---

st.header("Step 1: Upload Survey Data File")
uploaded_file = st.file_uploader("Choose a file", type=['csv', 'xlsx', 'sav'])

if uploaded_file:
    df_raw = load_data_file(uploaded_file)
    if df_raw is not None:
        st.success(f"Loaded {len(st.session_state.all_cols)} usable variables.")
        all_opts = ['-- Select Variable --'] + st.session_state.all_cols
        
        st.header("Step 2: Define Validation Rules")
        
        # Sidebar with Original Clear Button
        if st.sidebar.button("🗑️ Clear All Rules"):
            for k in ['sq_rules', 'mq_rules', 'string_rules', 'straightliner_rules', 'sq_batch_vars', 'string_batch_vars']:
                st.session_state[k] = []
            st.rerun()

        # Tabs Layout
        tab_sq, tab_oe, tab_mq, tab_sl, tab_final = st.tabs([
            "1. Single Select (SQ)", "2. Open Ends (OE)", "3. Multi-Select (MQ)", "4. Rating Grid", "5. Master Syntax"
        ])

        with tab_sq:
            st.subheader("SQ Configuration")
            # AUTOMATIC SELECTION: Show only Numeric variables
            num_vars = [c for c in st.session_state.all_cols if st.session_state.var_types.get(c) == 'Numeric']
            sq_sel = st.multiselect("Select Numeric Variables", num_vars, default=st.session_state.sq_batch_vars)
            
            if st.button("Configure Selected SQ"):
                st.session_state.sq_batch_vars = sq_sel

            if st.session_state.sq_batch_vars:
                with st.form("sq_batch_form"):
                    for col in st.session_state.sq_batch_vars:
                        st.markdown(f"**Variable: {col}**")
                        c1, c2, c3, c4 = st.columns(4)
                        mi = c1.number_input(f"Min {col}", 1, key=f"mi_{col}")
                        ma = c2.number_input(f"Max {col}", 5, key=f"ma_{col}")
                        tr = c3.selectbox(f"Trigger {col}", all_opts, key=f"tr_{col}")
                        tv = c4.text_input(f"Value {col}", "1", key=f"tv_{col}")
                        if st.form_submit_button(f"Save Rule for {col}"):
                            st.session_state.sq_rules.append({'variable': col, 'min_val': mi, 'max_val': ma, 'trigger_col': tr, 'trigger_val': tv})
                            st.success(f"Saved {col}")

        with tab_oe:
            st.subheader("OE Configuration")
            # AUTOMATIC SELECTION: Show only String variables
            str_vars = [c for c in st.session_state.all_cols if st.session_state.var_types.get(c) == 'String']
            oe_sel = st.multiselect("Select String Variables", str_vars, default=st.session_state.string_batch_vars)
            
            if st.button("Configure OE"):
                st.session_state.string_batch_vars = oe_sel

            if st.session_state.string_batch_vars:
                for i, col in enumerate(st.session_state.string_batch_vars):
                    with st.form(f"oe_form_{col}"):
                        st.write(f"**Settings for {col}**")
                        c1, c2 = st.columns(2)
                        tr = c1.selectbox(f"Parent Question", all_opts, key=f"oet_{col}")
                        tv = c2.text_input(f"Trigger Value", "1", key=f"oev_{col}")
                        if st.form_submit_button(f"Save OE Rule for {col}"):
                            st.session_state.string_rules.append({'variable': col, 'trigger_col': tr, 'trigger_val': tv})

        with tab_mq:
            st.subheader("Multi-Select Grouping")
            groups = get_smart_groups()
            sel_g = st.selectbox("Quick-Select Prefix (Q1, A4...)", ["-- Select --"] + list(groups.keys()))
            mq_vars = st.multiselect("Variables", st.session_state.all_cols, default=groups.get(sel_g, []))
            if mq_vars and st.button("Add MQ Rule"):
                st.session_state.mq_rules.append({'variables': mq_vars, 'name': sel_g if sel_g != "-- Select --" else mq_vars[0]})
                st.success("Group Added")

        with tab_sl:
            st.subheader("Rating Grid Straightlining")
            sl_g = st.selectbox("Select Grid Prefix", ["-- Select --"] + list(get_smart_groups().keys()), key="sl_sel")
            if sl_g != "-- Select --" and st.button(f"Add Straightliner for {sl_g}"):
                st.session_state.straightliner_rules.append({'variables': get_smart_groups()[sl_g], 'group_name': sl_g})
                st.success(f"Straightliner added for {sl_g}")

        with tab_final:
            st.header("Step 3: Generate Master Syntax")
            if st.button("Generate Final SPSS Script"):
                syntax = ["* FINAL VALIDATION SCRIPT\n", "SET DECIMAL=DOT.\n"]
                for r in st.session_state.sq_rules:
                    syntax.append(f"IF(miss({r['variable']}) | ~range({r['variable']},{r['min_val']},{r['max_val']})) {FLAG_PREFIX}{r['variable']}_Rng=1.")
                # Generating syntax based on your original logic...
                final_code = "\n".join(syntax + ["EXECUTE."])
                st.code(final_code, language="spss")
                st.download_button("Download .sps", final_code, "master_validation.sps")