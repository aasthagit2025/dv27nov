# dv_syntax_ui.py
"""
Interactive Syntax Builder (Streamlit)
- Upload a data file (CSV / XLSX) to auto-populate variable list OR
- Paste variable names manually.
- Select a variable, choose question type and options (DK codes, skip rules, Top2/Bottom2, recode).
- Click "Generate for variable" to append block to the working script.
- Download the final .sps file.
"""

import streamlit as st
import pandas as pd
import tempfile
from pathlib import Path
import re
from typing import List, Optional

st.set_page_config(page_title="Interactive Syntax Builder", layout="centered")
st.title("Interactive Syntax Builder — one-click variable-based .sps creator")
st.write("Upload your data (CSV/XLSX) or paste variable names. Pick a variable, set options, Generate. Repeat. Download final .sps when ready.")

# -------------------------
# Helper functions
# -------------------------
def parse_varlist_from_file(uploaded_file) -> List[str]:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix)
    tmp.write(uploaded_file.getbuffer())
    tmp.flush()
    tmp.close()
    path = tmp.name
    try:
        if path.lower().endswith(".csv"):
            df = pd.read_csv(path, nrows=0)
        else:
            df = pd.read_excel(path, nrows=0)
        return list(df.columns)
    except Exception as e:
        st.warning(f"Failed to read file columns automatically: {e}")
        return []

def parse_codes_raw(codes_text: str) -> List[str]:
    if not codes_text: return []
    parts = re.split(r"[;,|\n]+", codes_text)
    parts = [p.strip() for p in parts if p.strip()]
    return parts

def build_single_block(var: str, label: str, value_labels_text: str, dk_codes: List[str], skip_rules: List[str]) -> str:
    sb = []
    sb.append(f"* --- SINGLE SELECT: {var} {(' - ' + label) if label else ''} --- *.")
    # Value labels if provided
    if value_labels_text:
        sb.append(f"VALUE LABELS {var}")
        # value_labels_text expected like: "1=No;2=Yes" or one per line "1 No"
        parts = re.split(r"[;|\n]+", value_labels_text)
        val_lines = []
        for p in parts:
            p = p.strip()
            if not p: continue
            if "=" in p:
                k,v = p.split("=",1)
                val_lines.append(f"    {k.strip()} \"{v.strip()}\"")
            else:
                # try split by whitespace
                toks = p.split(None,1)
                if len(toks)==2:
                    val_lines.append(f"    {toks[0].strip()} \"{toks[1].strip()}\"")
        if val_lines:
            for ln in val_lines:
                sb.append(ln)
            sb[-1] = sb[-1] + "."
    # Skip rules / filter
    if skip_rules:
        # build SELECT IF excluding skip triggers: SELECT IF NOT(condition1 OR condition2)
        # but allow user to provide full expression; we'll wrap safely
        joined = " or ".join([f"({r})" for r in skip_rules])
        sb.append(f"* Applying skip rule(s): {', '.join(skip_rules)}")
        sb.append(f"SELECT IF not({joined}).")
        sb.append(f"FREQUENCIES VARIABLES={var} /FORMAT=NOTABLE.")
        sb.append("USE ALL.")
        sb.append("FILTER OFF.")
    else:
        if dk_codes:
            # exclude DK from base
            excl = " and ".join([f"not({var} = {d})" for d in dk_codes])
            sb.append(f"SELECT IF {excl}.")
            sb.append(f"FREQUENCIES VARIABLES={var} /FORMAT=NOTABLE.")
            sb.append("USE ALL.")
            sb.append("FILTER OFF.")
        else:
            sb.append(f"FREQUENCIES VARIABLES={var} /FORMAT=NOTABLE.")
    sb.append("") 
    return "\n".join(sb)

def build_multi_block(var: str, label: str, checked_code: str, skip_rules: List[str]) -> str:
    sb = []
    sb.append(f"* --- MULTI SELECT: {var} {(' - ' + label) if label else ''} --- *.")
    # assume checked_code like '1' or "1=Checked"
    if checked_code:
        # user-friendly: if they entered "1=Checked" parse
        k = checked_code.split("=")[0].strip()
        sb.append(f"VALUE LABELS {var} {k} 'Checked' 0 'Unchecked'.")
    else:
        sb.append(f"VALUE LABELS {var} 1 'Checked' 0 'Unchecked'.")
    sb.append("EXECUTE.")
    if skip_rules:
        joined = " or ".join([f"({r})" for r in skip_rules])
        sb.append(f"* Applying skip rule(s): {', '.join(skip_rules)}")
        sb.append(f"SELECT IF not({joined}).")
        sb.append(f"FREQUENCIES VARIABLES={var} /FORMAT=NOTABLE.")
        sb.append("USE ALL.")
        sb.append("FILTER OFF.")
    else:
        sb.append(f"FREQUENCIES VARIABLES={var} /FORMAT=NOTABLE.")
    sb.append("")
    return "\n".join(sb)

def build_rating_block(var: str, label: str, value_labels_text: str, dk_codes: List[str], top2: List[str], bot2: List[str], skip_rules: List[str]) -> str:
    sb = []
    sb.append(f"* --- RATING: {var} {(' - ' + label) if label else ''} --- *.")
    # value labels
    if value_labels_text:
        sb.append(f"VALUE LABELS {var}")
        parts = re.split(r"[;|\n]+", value_labels_text)
        val_lines = []
        for p in parts:
            p = p.strip()
            if not p: continue
            if "=" in p:
                k,v = p.split("=",1)
                val_lines.append(f"    {k.strip()} \"{v.strip()}\"")
            else:
                toks = p.split(None,1)
                if len(toks)==2:
                    val_lines.append(f"    {toks[0].strip()} \"{toks[1].strip()}\"")
        if val_lines:
            for ln in val_lines:
                sb.append(ln)
            sb[-1] = sb[-1] + "."
    # create filter if skip rules present or dk codes present
    if skip_rules:
        joined = " or ".join([f"({r})" for r in skip_rules])
        sb.append(f"* Applying skip rule(s): {', '.join(skip_rules)}")
        sb.append(f"SELECT IF not({joined}).")
    elif dk_codes:
        excl = " and ".join([f"not({var} = {d})" for d in dk_codes])
        sb.append(f"* Excluding DK codes: {', '.join(dk_codes)}")
        sb.append(f"SELECT IF {excl}.")
    # Top2
    if top2:
        top_expr = " or ".join([f"{var} = {t}" for t in top2])
        sb.append(f"COMPUTE {var}_TOP2 = ({top_expr}).")
        sb.append("EXECUTE.")
        sb.append(f"FREQUENCIES VARIABLES={var}_TOP2 /FORMAT=NOTABLE.")
    # Bottom2
    if bot2:
        bot_expr = " or ".join([f"{var} = {t}" for t in bot2])
        sb.append(f"COMPUTE {var}_BOT2 = ({bot_expr}).")
        sb.append("EXECUTE.")
        sb.append(f"FREQUENCIES VARIABLES={var}_BOT2 /FORMAT=NOTABLE.")
    if not top2 and not bot2:
        sb.append(f"FREQUENCIES VARIABLES={var} /FORMAT=NOTABLE.")
    # clear filter if applied
    if (skip_rules or dk_codes):
        sb.append("USE ALL.")
        sb.append("FILTER OFF.")
    sb.append("")
    return "\n".join(sb)

def build_recode_block(var: str, label: str, recode_expr: str) -> str:
    sb = []
    sb.append(f"* --- RECODE: {var} {(' - ' + label) if label else ''} --- *.")
    # recode_expr expected like "1=1,2=1,3=0"
    if recode_expr:
        parts = re.split(r"[;,|]+", recode_expr)
        for p in parts:
            p = p.strip()
            if "=" in p:
                old,new = p.split("=",1)
                sb.append(f"RECODE {var} ({old.strip()}={new.strip()}) INTO {var}_RC.")
        sb.append("EXECUTE.")
    sb.append("")
    return "\n".join(sb)

# -------------------------
# Session state init
# -------------------------
if "script_blocks" not in st.session_state:
    st.session_state.script_blocks = []

if "current_var" not in st.session_state:
    st.session_state.current_var = None

# -------------------------
# UI: load variables
# -------------------------
uploaded = st.file_uploader("Upload data file (CSV / XLSX) to auto-populate variable list (optional)", type=["csv","xlsx"])
manual_vars = st.text_area("OR paste variable names (comma or newline separated) — leave blank if you uploaded file", height=80, placeholder="Q1,Q2,Q3 or Q1\nQ2\nQ3")

var_list = []
if uploaded:
    var_list = parse_varlist_from_file(uploaded)
elif manual_vars.strip():
    # split by comma or newline
    toks = re.split(r"[,\n]+", manual_vars)
    var_list = [t.strip() for t in toks if t.strip()]

if not var_list:
    st.info("No variables detected yet. Upload file or paste variable names.")
else:
    st.success(f"{len(var_list)} variables available.")

# Selection areas
colA, colB = st.columns([2,3])
with colA:
    chosen_var = st.selectbox("Pick a variable to generate syntax for", options=[""] + var_list, index=0)
with colB:
    var_label = st.text_input("Optional: Variable label / question text", value="")

# If a variable selected, show type options and dynamic inputs
if chosen_var:
    st.markdown("### Configure syntax for: " + chosen_var)
    qtype = st.radio("Question Type", options=["SINGLE","MULTI","RATING","NUMERIC","OPEN","RECODE"], index=0, horizontal=True)
    # DK codes and skip rules common inputs
    dk_input = st.text_input("DK codes (comma separated) — will be excluded from base (e.g., 88,99)", value="")
    skip_raw = st.text_area("Skip conditions (one per line). Example syntax: Q3=1  or  Q2 IN (2,3)  or  Q5 = 99", height=80, value="")
    skip_rules = [r.strip() for r in re.split(r"[\n]+", skip_raw) if r.strip()]

    # Type-specific
    if qtype == "SINGLE":
        st.subheader("Single select options")
        value_labels_text = st.text_area("Value labels (format: '1=No;2=Yes' or each on new line '1 No')", height=80)
        if st.button("Generate SINGLE syntax for " + chosen_var):
            block = build_single_block(chosen_var, var_label, value_labels_text, parse_codes_raw(dk_input), skip_rules)
            st.session_state.script_blocks.append(block)
            st.success("Block appended.")
    elif qtype == "MULTI":
        st.subheader("Multi-select options")
        checked_code = st.text_input("Checked code (usually 1). You can type '1' or '1=Checked'", value="1")
        if st.button("Generate MULTI syntax for " + chosen_var):
            block = build_multi_block(chosen_var, var_label, checked_code, skip_rules)
            st.session_state.script_blocks.append(block)
            st.success("Block appended.")
    elif qtype == "RATING":
        st.subheader("Rating options")
        value_labels_text = st.text_area("Value labels (format as SINGLE)", height=80)
        top2_raw = st.text_input("Top2 codes (comma separated) e.g., 4,5", value="")
        bot2_raw = st.text_input("Bottom2 codes (comma separated) e.g., 1,2", value="")
        if st.button("Generate RATING syntax for " + chosen_var):
            block = build_rating_block(chosen_var, var_label, value_labels_text, parse_codes_raw(dk_input), [t.strip() for t in top2_raw.split(",") if t.strip()], [b.strip() for b in bot2_raw.split(",") if b.strip()], skip_rules)
            st.session_state.script_blocks.append(block)
            st.success("Block appended.")
    elif qtype == "NUMERIC":
        st.subheader("Numeric options")
        desc = st.checkbox("Include FREQUENCIES / DESCRIPTIVES", value=True)
        if st.button("Generate NUMERIC syntax for " + chosen_var):
            block = f"* --- NUMERIC: {chosen_var} --- *.\n"
            if desc:
                block += f"DESCRIPTIVES VARIABLES={chosen_var} /STATISTICS=MEAN STDDEV MIN MAX.\n\n"
            else:
                block += f"FREQUENCIES VARIABLES={chosen_var} /FORMAT=NOTABLE.\n\n"
            st.session_state.script_blocks.append(block)
            st.success("Block appended.")
    elif qtype == "RECODE":
        st.subheader("Recode options")
        recode_expr = st.text_input("Recode mapping (example '1=1,2=1,3=0')", value="")
        if st.button("Generate RECODE syntax for " + chosen_var):
            block = build_recode_block(chosen_var, var_label, recode_expr)
            st.session_state.script_blocks.append(block)
            st.success("Block appended.")
    else:  # OPEN
        st.subheader("Open/Text options")
        if st.button("Generate OPEN variable syntax for " + chosen_var):
            block = f"* --- OPEN/TEXT: {chosen_var} --- *.\nFREQUENCIES VARIABLES={chosen_var} /FORMAT=NOTABLE.\n\n"
            st.session_state.script_blocks.append(block)
            st.success("Block appended.")

# Show current script preview and allow download / clear
st.markdown("## Current script")
if st.session_state.script_blocks:
    full = "\n".join(st.session_state.script_blocks)
    st.code(full[:10000])
    st.download_button("Download .sps file", data=full, file_name="generated_by_ui.sps", mime="text/plain")
    colx, coly = st.columns([1,1])
    with colx:
        if st.button("Clear generated script"):
            st.session_state.script_blocks = []
            st.success("Cleared.")
    with coly:
        if st.button("Save script to server temp and show path"):
            p = Path(tempfile.gettempdir()) / "generated_by_ui.sps"
            p.write_text(full, encoding="utf-8")
            st.success(f"Saved to {p}")
else:
    st.info("No blocks generated yet. Pick a variable and click Generate.")
