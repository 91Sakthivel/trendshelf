import json

with open("notebooks/trendshelf_eda_executed.ipynb", encoding="utf-8") as f:
    nb = json.load(f)

def cell_source(cell):
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else src

# List all code cells and their first output
for i, cell in enumerate(nb["cells"]):
    if cell["cell_type"] != "code":
        continue
    src = cell_source(cell)
    outputs = cell.get("outputs", [])
    text_out = ""
    for out in outputs:
        t = out.get("text", [])
        if isinstance(t, list):
            text_out = "".join(t)[:120]
        elif isinstance(t, str):
            text_out = t[:120]
        if text_out:
            break
    # First 80 chars of source
    print(f"[{i:02d}] {src[:80].replace(chr(10),' ')!r}")
    print(f"      OUT: {text_out[:100]!r}")
    print()
