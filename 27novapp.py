import streamlit as st
import pandas as pd
import numpy as np
import io
import os 
import tempfile
import re

# --- 1. CONFIGURATION ---
FLAG_PREFIX = "xx" 
SYSTEM_VARS = ['sys_respnum', 'status', 'duration', 'starttime', 'endtime', 'uuid', 'recordid', 'respid', 'index', 'id', 'status_code']

st.set_page_config(layout="wide", page_title="Survey Data Validation")
st.title("📊 Survey Data Validation Automation")
st.markdown("---")

# --- 2. INITIALIZATION (Fixes Buffering/Reset issues) ---
if 'sq_rules' not in st.session_state: st.session_state.sq_rules = []
if 'mq_rules' not in st.session_state: st.session_state.mq_rules = []
if 'string_rules' not in st.session_state: st.session_state.string_rules = []
if 'straightliner_rules' not in st.session_state: st.session_state.straightliner_rules = []
if 'all_cols' not in st.session_state: st.session_state.all_cols = []
if 'var_types' not in st.session_state: st.session_state.var_types = {}
if 'sq_batch_vars' not in st.session_state: st.session_state.sq_batch_vars = []
if 'oe_batch_vars' not in st.session_state: st.session_state.oe_batch_vars = []

# --- 3. DATA HELPERS ---
def load_data_file(uploaded_file):
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    df = None
    try:
        if file_extension == '.csv':
            df = pd.read_csv(uploaded_file, na_values=['', ' ', 'N/A'])
        elif file_extension in ['.sav', '.zsav']:
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp:
                tmp.write(uploaded_file.getbuffer())
                df = pd.read_spss(tmp.name, convert_categoricals=False)
            os.remove(tmp.name)
        
        if df is not None:
            # STRICT FILTER: Remove system variables immediately
            cols = [c for c in df.columns if c.lower() not in SYSTEM_VARS]
            st.session_state.all_cols = cols
            st.session_state.var_types = {
                col: 'String' if df[col].dtype == 'object' or pd.api.types.is_string_dtype(df[col]) else 'Numeric'
                for col in cols
            }
            return df
    except Exception as e:
        st.error(f"Error: {e}")
    return None

def get_variable_groups():
    groups = {}
    for col in st.session_state.all_cols:
        if "_" in col:
            base = col.split("_")[0]
            if base not in groups: groups[base] = []
            groups[base].append(col)
    return {k: v for k, v in groups.items() if len(v) > 1}

# --- 4. UI FLOW (YOUR ORIGINAL UI) ---

uploaded_file = st.sidebar.file_uploader("Step 1: Upload Data", type=['sav', 'csv'])

if uploaded_file:
    df = load_data_file(uploaded_file)
    if df is not None:
        st.sidebar.success(f"Loaded {len(st.session_state.all_cols)} variables")
        
        # Original Tabs Layout
        tab_sq, tab_oe, tab_mq, tab_sl, tab_final = st.tabs([
            "Single Select", "Open Ends", "Multi-Select", "Rating Grid", "Generate Syntax"
        ])
        
        all_options = ["-- Select Variable --"] + st.session_state.all_cols

        with tab_sq:
            st.subheader("Single Select Configuration")
            # Only show Numeric types for SQ
            num_vars = [c for c in st.session_state.all_cols if st.session_state.var_types.get(c) == 'Numeric']
            sq_batch = st.multiselect("Select SQ Variables", num_vars)
            
            if st.button("Configure Selected SQ"):
                st.session_state.sq_batch_vars = sq_batch
            
            if st.session_state.sq_batch_vars:
                with st.form("sq_batch_form"):
                    for c in st.session_state.sq_batch_vars:
                        st.write(f"**Variable: {c}**")
                        c1, c2, c3, c4 = st.columns(4)
                        mi = c1.number_input(f"Min {c}", 1, key=f"mi_{c}")
                        ma = c2.number_input(f"Max {c}", 5, key=f"ma_{c}")
                        tr = c3.selectbox(f"Trig {c}", all_options, key=f"tr_{c}")
                        tv = c4.text_input(f"Val {c}", "1", key=f"tv_{c}")
                        if st.form_submit_button(f"Save {c}"):
                            st.session_state.sq_rules.append({'var': c, 'min': mi, 'max': ma, 'trig': tr, 'tr_v': tv})
                
        with tab_oe:
            st.subheader("Open Ended Configuration")
            # Only show String types for OE
            str_vars = [c for c in st.session_state.all_cols if st.session_state.var_types.get(c) == 'String']
            oe_batch = st.multiselect("Select OE Variables", str_vars)
            
            if st.button("Configure Selected OE"):
                st.session_state.oe_batch_vars = oe_batch
            
            if st.session_state.oe_batch_vars:
                with st.form("oe_batch_form"):
                    for c in st.session_state.oe_batch_vars:
                        c1, c2 = st.columns(2)
                        tr = c1.selectbox(f"Trig {c}", all_options, key=f"oetr_{c}")
                        tv = c2.text_input(f"Val {c}", "1", key=f"oetv_{c}")
                        if st.form_submit_button(f"Save OE {c}"):
                            st.session_state.string_rules.append({'var': c, 'trig': tr, 'tr_v': tv})

        with tab_mq:
            st.subheader("Multi-Select Grouping")
            groups = get_variable_groups()
            sel_g = st.selectbox("Select Group Prefix (Q1, A4...)", ["-- Select --"] + list(groups.keys()))
            mq_vars = st.multiselect("Variables in MQ", st.session_state.all_cols, default=groups.get(sel_g, []))
            if mq_vars:
                min_c = st.number_input("Min selections", 1)
                if st.button("Add MQ Rule"):
                    st.session_state.mq_rules.append({'vars': mq_vars, 'min': min_c, 'name': sel_g if sel_g != "-- Select --" else mq_vars[0]})

        with tab_sl:
            st.subheader("Rating Grid Straightlining")
            sl_g = st.selectbox("Select Grid Prefix", ["-- Select --"] + list(get_variable_groups().keys()), key="sl_sel")
            if sl_g != "-- Select --" and st.button(f"Add Straightliner for {sl_g}"):
                st.session_state.straightliner_rules.append({'vars': get_variable_groups()[sl_g], 'name': sl_g})

        with tab_final:
            if st.button("Generate SPSS Syntax"):
                syntax = ["* FINAL SYNTAX\n", "SET DECIMAL=DOT.\n"]
                # Logic generation follows your requirements for blank checks (miss() vs '')
                for r in st.session_state.sq_rules:
                    syntax.append(f"IF(miss({r['var']}) | ~range({r['var']},{r['min']},{r['max']})) {FLAG_PREFIX}{r['var']}_Rng=1.")
                for r in st.session_state.string_rules:
                    syntax.append(f"IF({r['var']} = '' | miss({r['var']})) {FLAG_PREFIX}{r['var']}_Str=1.")
                # MQ/SL Logic...
                for r in st.session_state.mq_rules:
                    syntax.append(f"COMPUTE {r['name']}_Sum = SUM({' '.join(r['vars'])}).")
                    syntax.append(f"IF({r['name']}_Sum < {r['min']}) {FLAG_PREFIX}{r['name']}_Min=1.")
                
                final_code = "\n".join(syntax + ["EXECUTE."])
                st.code(final_code, language="spss")
                st.download_button("Download .sps", final_code, "Validation.sps")