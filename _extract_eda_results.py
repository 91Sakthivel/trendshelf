"""Extract key outputs from the executed EDA notebook."""
import json

with open("notebooks/trendshelf_eda_executed.ipynb", encoding="utf-8") as f:
    nb = json.load(f)

def get_text_output(cell):
    lines = []
    for out in cell.get("outputs", []):
        otype = out.get("output_type", "")
        if otype in ("stream", "execute_result", "display_data"):
            text = out.get("text", out.get("data", {}).get("text/plain", []))
            if isinstance(text, list):
                lines.extend(text)
            elif isinstance(text, str):
                lines.append(text)
    return "".join(lines)

def cell_source(cell):
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else src

# Index-based extraction (from debug run)
code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
# code_cells indices: 0=setup, 2=sec1_raw, 3=sec1_preview, 5=sec2_audit, 6=sec2_display
# 8=sec3_scores, 10=sec4_query, 11-14=sec4_charts, 16=sec5_kr
# 21=sec6_join, 23=sec6_corr, 26=sec7_fresh, 28=sec8_summary

def find_cell(keyword):
    for c in code_cells:
        if keyword in cell_source(c):
            return c
    return None

sec1  = find_cell("RAW_META")
sec2a = find_cell("Running null audit")
sec2b = find_cell("_style_null")
sec4  = find_cell("mart_action_queue rows")
sec6  = find_cell("High-Correlation Pairs")
sec8  = find_cell("TRENDSHELF — EDA SUMMARY")

# sec4 match
sec4 = None
for c in code_cells:
    src = cell_source(c)
    if 'df_aq = q' in src and 'mart_action_queue' in src:
        sec4 = c
        break

print("=" * 70)
print("SECTION 1 — RAW ROW COUNTS PER SOURCE TABLE")
print("=" * 70)
print(get_text_output(sec1) if sec1 else "(not found)")

print()
print("=" * 70)
print("SECTION 2 — NULL AUDIT FINDINGS (WARNING >10%, CRITICAL >30%)")
print("=" * 70)
if sec2a:
    print(get_text_output(sec2a))
if sec2b:
    # strip the Styler repr and just show the text parts
    raw = get_text_output(sec2b)
    # remove the Styler object line
    lines = [l for l in raw.splitlines() if "Styler" not in l]
    print("\n".join(lines))

print()
print("=" * 70)
print("SECTION 4 — ACTION QUEUE BREAKDOWN")
print("=" * 70)
print(get_text_output(sec4) if sec4 else "(not found)")

print()
print("=" * 70)
print("SECTION 6 — CORRELATION WARNINGS (|r| > 0.85)")
print("=" * 70)
print(get_text_output(sec6) if sec6 else "(not found)")

print()
print("=" * 70)
print("SECTION 8 — FINAL EDA SUMMARY")
print("=" * 70)
print(get_text_output(sec8) if sec8 else "(not found)")
