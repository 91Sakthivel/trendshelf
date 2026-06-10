#!/usr/bin/env python3
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID, DATASET
"""Generates notebooks/trendshelf_eda.ipynb for TrendShelf EDA."""
import json, os

os.makedirs("notebooks", exist_ok=True)

_id = [0]

def md(src):
    _id[0] += 1
    return {"cell_type": "markdown", "id": f"md{_id[0]:04d}", "metadata": {}, "source": src}

def code(src):
    _id[0] += 1
    return {"cell_type": "code", "execution_count": None, "id": f"cd{_id[0]:04d}",
            "metadata": {}, "outputs": [], "source": src.strip("\n")}

cells = []

# â”€â”€â”€ Title â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cells.append(md(
    "# TrendShelf EDA Notebook\n"
    "*Exploratory Data Analysis â€” BigQuery Bronze Layer*  \n"
    f"*Project: {PROJECT_ID} | Dataset: {DATASET}*"
))

# â”€â”€â”€ Section 0: Setup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cells.append(md("## Section 0 â€” Setup"))

cells.append(code('''
%matplotlib inline
import os, warnings, datetime
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns
from IPython.display import display, HTML
from google.cloud import bigquery
from google.oauth2 import service_account

warnings.filterwarnings("ignore")
pd.set_option("display.max_columns", 50)
pd.set_option("display.float_format", "{:.2f}".format)
sns.set_theme(style="whitegrid", palette="muted")
plt.rcParams["figure.dpi"] = 100

PROJECT_ID = PROJECT_ID
DATASET    = "bronze"
_nb_dir = os.getcwd()
CREDS_FILE = os.path.join(_nb_dir, "credentials.json")
if not os.path.exists(CREDS_FILE):
    CREDS_FILE = os.path.join(os.path.dirname(_nb_dir), "credentials.json")

_creds = service_account.Credentials.from_service_account_file(
    CREDS_FILE, scopes=["https://www.googleapis.com/auth/bigquery"]
)
BQ = bigquery.Client(project=PROJECT_ID, credentials=_creds)

def q(sql):
    return BQ.query(sql).to_dataframe()

# EDA findings accumulator for Section 8 summary
_findings = {
    "total_raw_rows":     0,
    "critical_nulls":     [],
    "warning_nulls":      [],
    "suspicious_dists":   [],
    "stale_sources":      [],
    "corr_warnings":      [],
}

print(ff"Connected to BigQuery: {PROJECT_ID}")
print(f"Dataset  : {DATASET}")
print(f"Creds    : {CREDS_FILE}")
print(f"BQ client: {type(BQ).__name__}")
'''))

# â”€â”€â”€ Section 1: Raw Data Overview â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cells.append(md("## Section 1 â€” Raw Data Overview"))

cells.append(code('''
RAW_META = {
    "kroger_prices_raw":  ("DATE(collected_at)", "price_regular"),
    "serpapi_prices_raw": ("search_date",         "competitor_price"),
    "fred_ppi_raw":       ("observation_date",    "ppi_value"),
    "bls_cpi_raw":        ("reference_date",      "cpi_value"),
    "google_trends_raw":  ("trend_date",           "interest_score"),
}

print("Querying raw tables â€¦")
summary_rows = []
for tbl, (date_col, val_col) in RAW_META.items():
    try:
        sql = f"""
            SELECT
                COUNT(*)                                    AS row_count,
                CAST(MIN({date_col}) AS STRING)             AS min_date,
                CAST(MAX({date_col}) AS STRING)             AS max_date,
                ROUND(COUNTIF({val_col} IS NULL) / COUNT(*) * 100, 1) AS null_pct
            FROM `{PROJECT_ID}.{DATASET}.{tbl}`
        """
        df_i = q(sql)
        rc  = int(df_i["row_count"].iloc[0])
        _findings["total_raw_rows"] += rc
        summary_rows.append({
            "Source":                tbl.replace("_raw", ""),
            "Rows":                  f"{rc:,}",
            "Min Date":              df_i["min_date"].iloc[0],
            "Max Date":              df_i["max_date"].iloc[0],
            f"{val_col} Null %":     f"{df_i['null_pct'].iloc[0]:.1f}%",
        })
        print(f"  {tbl:<28}  {rc:>7,} rows   {df_i['min_date'].iloc[0]} â†’ {df_i['max_date'].iloc[0]}")
    except Exception as exc:
        summary_rows.append({"Source": tbl, "Rows": "ERROR", "Min Date": str(exc)[:60],
                              "Max Date": "", f"{val_col} Null %": ""})
        print(f"  {tbl:<28}  ERROR: {exc}")

print()
print("=== Raw Table Summary ===")
display(pd.DataFrame(summary_rows))
'''))

cells.append(code('''
for tbl in RAW_META:
    print(f"\\n{'â”€'*60}")
    print(f"  {tbl}  (first 5 rows)")
    print(f"{'â”€'*60}")
    try:
        display(q(ff"SELECT * FROM `{PROJECT_ID}.{DATASET}.{tbl}` LIMIT 5"))
    except Exception as exc:
        print(f"  ERROR: {exc}")
'''))

# â”€â”€â”€ Section 2: Null Audit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cells.append(md(
    "## Section 2 â€” Null Audit\n"
    "Color: **green** = 0â€“10% | **yellow** = 10â€“30% (WARNING) | **red** > 30% (CRITICAL)"
))

cells.append(code('''
AUDIT_TABLES = [
    "stg_kroger_prices", "stg_serpapi_prices",
    "stg_fred_ppi", "stg_bls_cpi", "stg_google_trends",
    "fact_market_signals", "mart_demand_gap_scores",
    "mart_shelfrisk_scores", "mart_price_margin_scores",
    "mart_confidence_layer", "mart_expansion_readiness",
    "mart_action_queue",
]

def null_audit(table_name):
    cols_df = q(f"""
        SELECT column_name, data_type
        FROM `{PROJECT_ID}.{DATASET}.INFORMATION_SCHEMA.COLUMNS`
        WHERE table_name = '{table_name}'
        ORDER BY ordinal_position
    """)
    if cols_df.empty:
        return pd.DataFrame()
    # Exclude ARRAY/STRUCT (not directly nullable with COUNTIF)
    scalar = cols_df[
        ~cols_df["data_type"].str.upper().str.contains("ARRAY|STRUCT")
    ]["column_name"].tolist()
    if not scalar:
        return pd.DataFrame()

    exprs = ",\\n".join(
        f"    COUNTIF(`{c}` IS NULL) AS `n_{c}`" for c in scalar
    )
    df_n = q(f"""
        SELECT COUNT(*) AS total, {exprs}
        FROM `{PROJECT_ID}.{DATASET}.{table_name}`
    """)
    total = int(df_n["total"].iloc[0])
    rows = []
    for c in scalar:
        nc  = int(df_n[f"n_{c}"].iloc[0])
        pct = round(nc / total * 100, 1) if total > 0 else 0
        rows.append({
            "table":      table_name,
            "column":     c,
            "total_rows": total,
            "null_count": nc,
            "null_pct":   pct,
            "status":     "CRITICAL" if pct > 30 else ("WARNING" if pct > 10 else "OK"),
        })
    return pd.DataFrame(rows)

all_audit = []
print("Running null audit â€¦")
for tbl in AUDIT_TABLES:
    try:
        df_a = null_audit(tbl)
        if not df_a.empty:
            all_audit.append(df_a)
            cr = (df_a["status"] == "CRITICAL").sum()
            wn = (df_a["status"] == "WARNING").sum()
            print(f"  {tbl:<35}  {len(df_a):>3} cols  |  {wn} WARN  {cr} CRIT")
            for _, r in df_a[df_a["status"] == "CRITICAL"].iterrows():
                _findings["critical_nulls"].append(f"{tbl}.{r['column']} ({r['null_pct']:.0f}%)")
            for _, r in df_a[df_a["status"] == "WARNING"].iterrows():
                _findings["warning_nulls"].append(f"{tbl}.{r['column']} ({r['null_pct']:.0f}%)")
        else:
            print(f"  {tbl:<35}  (no scalar columns found)")
    except Exception as exc:
        print(f"  {tbl:<35}  ERROR: {exc}")

df_audit = pd.concat(all_audit, ignore_index=True) if all_audit else pd.DataFrame()
print(f"\\nAudit complete: {len(df_audit)} column entries across {len(AUDIT_TABLES)} tables")
'''))

cells.append(code('''
def _style_null(val):
    if not isinstance(val, (int, float)):
        return ""
    if val > 30:  return "background-color:#f8d7da;color:#721c24"
    if val > 10:  return "background-color:#fff3cd;color:#856404"
    if val == 0:  return "background-color:#d4edda;color:#155724"
    return ""

print("=== Null Audit â€” Columns WITH Nulls ===")
if not df_audit.empty:
    df_nz = df_audit[df_audit["null_pct"] > 0].copy()
    if df_nz.empty:
        print("No nulls found across all audited tables!")
    else:
        display(df_nz.style.map(_style_null, subset=["null_pct"]))

    print(f"\\nAll-clean columns (null_pct = 0):  {(df_audit['null_pct']==0).sum():,} / {len(df_audit):,}")
    print()
    print("=== Null Summary by Table ===")
    tbl_sum = df_audit.groupby("table").agg(
        total_cols    = ("column",   "count"),
        cols_w_nulls  = ("null_pct", lambda x: (x > 0).sum()),
        max_null_pct  = ("null_pct", "max"),
        critical_cols = ("status",   lambda x: (x == "CRITICAL").sum()),
        warning_cols  = ("status",   lambda x: (x == "WARNING").sum()),
    ).reset_index()
    display(tbl_sum)
else:
    print("No audit data available.")
'''))

# â”€â”€â”€ Section 3: Score Distributions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cells.append(md(
    "## Section 3 â€” Score Distributions\n"
    "Histogram for every 0â€“100 score column. "
    "Yellow background = std < 5 (suspicious uniformity â€” likely proxy data)."
))

cells.append(code('''
SCORE_MARTS = {
    "mart_demand_gap_scores": [
        "category_momentum_score", "search_to_shelf_gap", "phantom_distribution",
        "intent_quality_score", "overall_demand_gap_score",
    ],
    "mart_shelfrisk_scores": [
        "missed_demand_risk", "demand_decay_risk", "phantom_distribution_risk",
        "competitive_threat_risk", "assortment_trap_risk", "overall_risk_score",
    ],
    "mart_price_margin_scores": [
        "price_position_score", "cost_shock_score", "margin_pressure_risk",
        "promo_risk_score", "overall_margin_risk_score",
    ],
    "mart_confidence_layer": [
        "data_completeness_score", "signal_agreement_score",
        "data_freshness_score", "overall_confidence_score",
    ],
    "mart_expansion_readiness": [
        "expansion_readiness_score",
    ],
}

for mart, score_cols in SCORE_MARTS.items():
    col_list = ", ".join(score_cols)
    df_sc = q(ff"SELECT {col_list} FROM `{PROJECT_ID}.{DATASET}.{mart}`")

    n     = len(score_cols)
    ncols = min(3, n)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows), squeeze=False)
    flat  = axes.flatten()
    title = mart.replace("mart_", "").replace("_", " ").title()
    fig.suptitle(title, fontsize=14, fontweight="bold", y=1.01)

    for i, col in enumerate(score_cols):
        ax  = flat[i]
        vals = df_sc[col].dropna()
        if vals.empty:
            ax.set_title(f"{col}\\n(no data)", fontsize=9)
            continue

        std_v = vals.std()
        face  = "#fff3cd" if std_v < 5 else "#f0f4ff"
        ax.set_facecolor(face)
        ax.hist(vals, bins=25, color="steelblue", alpha=0.75, edgecolor="white")
        ax.axvline(vals.mean(),   color="red",    lw=1.5, linestyle="--", label=f"mean={vals.mean():.1f}")
        ax.axvline(vals.median(), color="orange", lw=1.5, linestyle=":",  label=f"med={vals.median():.1f}")
        ax.set_title(col.replace("_", " "), fontsize=9)
        ax.set_xlabel("Score (0â€“100)", fontsize=8)
        ax.set_ylabel("Count", fontsize=8)
        ax.legend(fontsize=7)
        ax.text(0.97, 0.97, f"std={std_v:.1f}", transform=ax.transAxes,
                ha="right", va="top", fontsize=8,
                color="#856404" if std_v < 5 else "#333333")

        if std_v < 5:
            _findings["suspicious_dists"].append(f"{mart}.{col} (std={std_v:.1f})")

    for j in range(len(score_cols), len(flat)):
        flat[j].set_visible(False)

    plt.tight_layout()
    plt.show()
    print(f"  {mart}: {n} score columns plotted")
'''))

# â”€â”€â”€ Section 4: Action Queue Breakdown â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cells.append(md("## Section 4 â€” Action Queue Breakdown"))

cells.append(code('''
df_aq = q(f"""
    SELECT
        a.category_name,
        a.store_id,
        a.action_type,
        a.urgency,
        a.action_priority,
        a.overall_demand_gap_score,
        a.overall_risk_score,
        a.overall_confidence_score,
        a.overall_margin_risk_score,
        l.city       AS store_city,
        l.store_name
    FROM `{PROJECT_ID}.{DATASET}.mart_action_queue` a
    LEFT JOIN `{PROJECT_ID}.{DATASET}.dim_location` l ON a.store_id = l.store_id
""")

print(f"mart_action_queue rows : {len(df_aq):,}")
print(f"Distinct store_ids     : {df_aq['store_id'].nunique()}")
print(f"Distinct categories    : {df_aq['category_name'].nunique()}")
print(f"\\nAction type distribution:")
print(df_aq["action_type"].value_counts().to_string())
'''))

cells.append(code('''
ACTION_COLORS = {
    "EXPAND":      "#28a745", "PITCH":      "#17a2b8",
    "MONITOR":     "#6c757d", "REPRICE":    "#ffc107",
    "DEFEND":      "#fd7e14", "CUT_PROMO":  "#e83e8c",
    "INVESTIGATE": "#dc3545", "AVOID":      "#6f42c1",
}

# â”€â”€ Chart 1: Overall counts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
counts = df_aq["action_type"].value_counts()
order  = counts.index.tolist()

fig, ax = plt.subplots(figsize=(11, 5))
bar_cols = [ACTION_COLORS.get(a, "#adb5bd") for a in order]
bars = ax.bar(order, counts[order], color=bar_cols, edgecolor="white", width=0.65)
for bar, val in zip(bars, counts[order]):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 8,
            f"{val:,}", ha="center", va="bottom", fontsize=10, fontweight="bold")
ax.set_title("Action Queue â€” Overall Distribution  (n=5,000)", fontsize=13, fontweight="bold")
ax.set_xlabel("Action Type"); ax.set_ylabel("Count")
ax.set_ylim(0, counts.max() * 1.18)
plt.tight_layout(); plt.show()
'''))

cells.append(code('''
# â”€â”€ Chart 2: By category â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
action_order = [a for a in ["AVOID","INVESTIGATE","DEFEND","CUT_PROMO",
                              "MONITOR","REPRICE","PITCH","EXPAND"]
                if a in df_aq["action_type"].unique()]
pivot_cat = (df_aq.groupby(["category_name","action_type"])
               .size().unstack(fill_value=0)
               .reindex(columns=action_order, fill_value=0))
bar_c = [ACTION_COLORS.get(a,"#adb5bd") for a in pivot_cat.columns]

fig, ax = plt.subplots(figsize=(15, 6))
pivot_cat.plot(kind="bar", ax=ax, color=bar_c, edgecolor="white", width=0.72)
ax.set_title("Action Type by Category", fontsize=13, fontweight="bold")
ax.set_xlabel("Category"); ax.set_ylabel("Count")
ax.legend(title="Action", bbox_to_anchor=(1.01,1), loc="upper left", fontsize=9)
plt.xticks(rotation=30, ha="right"); plt.tight_layout(); plt.show()
'''))

cells.append(code('''
# â”€â”€ Chart 3: By store city â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
pivot_city = (df_aq.groupby(["store_city","action_type"])
                .size().unstack(fill_value=0)
                .reindex(columns=action_order, fill_value=0))
top_cities = pivot_city.sum(axis=1).sort_values(ascending=False).head(20).index
pivot_top  = pivot_city.loc[top_cities]

fig, ax = plt.subplots(figsize=(17, 6))
pivot_top.plot(kind="bar", ax=ax,
               color=[ACTION_COLORS.get(a,"#adb5bd") for a in pivot_top.columns],
               edgecolor="white", width=0.72)
ax.set_title("Action Type by Store City", fontsize=13, fontweight="bold")
ax.set_xlabel("Store City"); ax.set_ylabel("Count")
ax.legend(title="Action", bbox_to_anchor=(1.01,1), loc="upper left", fontsize=9)
plt.xticks(rotation=45, ha="right", fontsize=8); plt.tight_layout(); plt.show()
'''))

cells.append(code('''
# â”€â”€ Chart 4: Heatmap store Ã— category (avg demand gap score) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
pivot_heat = df_aq.pivot_table(
    values="overall_demand_gap_score",
    index="store_city", columns="category_name", aggfunc="mean"
)

fig, ax = plt.subplots(figsize=(14, 10))
sns.heatmap(
    pivot_heat, ax=ax, cmap="RdYlGn", center=50, vmin=0, vmax=100,
    annot=True, fmt=".0f", annot_kws={"size": 7.5},
    linewidths=0.3, linecolor="#dee2e6",
    cbar_kws={"label": "Avg Demand Gap Score"}
)
ax.set_title("Demand Gap Score â€” Store Ã— Category Heatmap", fontsize=13, fontweight="bold")
ax.set_xlabel("Category", fontsize=11)
ax.set_ylabel("Store City", fontsize=11)
plt.xticks(rotation=30, ha="right", fontsize=9)
plt.yticks(fontsize=8)
plt.tight_layout(); plt.show()
'''))

# â”€â”€â”€ Section 5: Price Analysis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cells.append(md("## Section 5 â€” Price Analysis"))

cells.append(code('''
df_kr = q(f"""
    SELECT category, price_regular
    FROM `{PROJECT_ID}.{DATASET}.stg_kroger_prices`
    WHERE price_regular IS NOT NULL AND price_regular > 0 AND price_regular < 500
""")
df_serp = q(f"""
    SELECT
        REGEXP_REPLACE(search_query, r" price walmart texas", "") AS category,
        competitor_store,
        competitor_price
    FROM `{PROJECT_ID}.{DATASET}.stg_serpapi_prices`
    WHERE competitor_price IS NOT NULL AND competitor_price > 0 AND competitor_price < 500
""")
print(f"Kroger price records   : {len(df_kr):,}")
print(f"Competitor price records: {len(df_serp):,}")
print(f"\\nKroger categories: {sorted(df_kr['category'].dropna().unique().tolist())}")
print(f"\\nTop competitor stores:")
print(df_serp["competitor_store"].value_counts().head(10).to_string())
'''))

cells.append(code('''
# â”€â”€ Box plot: Kroger price distribution by category â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cat_order = (df_kr.groupby("category")["price_regular"]
               .median().sort_values().index.tolist())

fig, ax = plt.subplots(figsize=(14, 6))
bp_data = [df_kr[df_kr["category"]==c]["price_regular"].values for c in cat_order]
bp = ax.boxplot(bp_data, labels=cat_order, patch_artist=True, vert=True,
                medianprops={"color": "black", "linewidth": 2},
                flierprops={"marker": ".", "markersize": 3, "alpha": 0.4})
palette = sns.color_palette("tab10", len(cat_order))
for patch, col in zip(bp["boxes"], palette):
    patch.set_facecolor(col); patch.set_alpha(0.65)
ax.set_title("Kroger Price Distribution by Category", fontsize=13, fontweight="bold")
ax.set_ylabel("Price (USD)"); ax.set_xlabel("Category")
plt.xticks(rotation=30, ha="right"); plt.tight_layout(); plt.show()
'''))

cells.append(code('''
# â”€â”€ Side-by-side: Kroger median vs Competitor median â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
kr_agg   = df_kr.groupby("category")["price_regular"].median().rename("kroger_med")
comp_agg = df_serp.groupby("category")["competitor_price"].median().rename("comp_med")
df_cmp   = pd.concat([kr_agg, comp_agg], axis=1).dropna()
df_cmp["gap_pct"] = ((df_cmp["kroger_med"] - df_cmp["comp_med"]) / df_cmp["comp_med"] * 100).round(1)
df_cmp = df_cmp.sort_values("gap_pct", ascending=False)

print("=== Median Price Comparison: Kroger vs Competitor ===")
display(df_cmp.reset_index().rename(columns={"category":"Category",
    "kroger_med":"Kroger Median ($)","comp_med":"Competitor Median ($)","gap_pct":"Gap %"}))

x = np.arange(len(df_cmp))
fig, ax = plt.subplots(figsize=(14, 6))
b1 = ax.bar(x - 0.18, df_cmp["kroger_med"],  0.35, label="Kroger",     color="#1f77b4", alpha=0.85)
b2 = ax.bar(x + 0.18, df_cmp["comp_med"],    0.35, label="Competitor", color="#ff7f0e", alpha=0.85)
ax.set_title("Median Price: Kroger vs Competitor by Category", fontsize=13, fontweight="bold")
ax.set_xticks(x); ax.set_xticklabels(df_cmp.index, rotation=30, ha="right")
ax.set_ylabel("Median Price (USD)"); ax.legend()
for i, (_, row) in enumerate(df_cmp.iterrows()):
    col = "red" if row["gap_pct"] > 0 else "green"
    ax.text(i, max(row["kroger_med"], row["comp_med"]) + 0.2,
            f"{row['gap_pct']:+.1f}%", ha="center", va="bottom",
            fontsize=8, color=col, fontweight="bold")
plt.tight_layout(); plt.show()
'''))

cells.append(code('''
# â”€â”€ Scatter: price_gap_pct vs demand_gap_score by category â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
df_dem_cat = q(f"""
    SELECT category_name, AVG(overall_demand_gap_score) AS avg_demand_gap
    FROM `{PROJECT_ID}.{DATASET}.mart_demand_gap_scores`
    GROUP BY 1
""")
df_sc5 = df_dem_cat.merge(df_cmp.reset_index(), left_on="category_name", right_on="category")

if not df_sc5.empty:
    fig, ax = plt.subplots(figsize=(9, 6))
    sc = ax.scatter(df_sc5["gap_pct"], df_sc5["avg_demand_gap"],
                    s=130, zorder=5, c=range(len(df_sc5)),
                    cmap="tab10", edgecolors="white", linewidth=1)
    for _, row in df_sc5.iterrows():
        ax.annotate(row["category_name"], (row["gap_pct"], row["avg_demand_gap"]),
                    textcoords="offset points", xytext=(6, 3), fontsize=8.5)
    ax.axvline(0, color="gray", lw=1, linestyle="--")
    ax.set_xlabel("Kroger Price Premium over Competitor (%) â€” positive = Kroger more expensive")
    ax.set_ylabel("Avg Demand Gap Score")
    ax.set_title("Price Gap % vs Demand Gap Score by Category", fontsize=13, fontweight="bold")
    plt.tight_layout(); plt.show()
else:
    print("No matching categories between Kroger and competitor data.")
'''))

# â”€â”€â”€ Section 6: Signal Correlation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cells.append(md("## Section 6 â€” Signal Correlation"))

cells.append(code('''
df_sig = q(f"""
    SELECT
        d.avg_search_interest,
        d.category_momentum_score,
        d.search_to_shelf_gap,
        d.intent_quality_score,
        d.overall_demand_gap_score,
        r.missed_demand_risk,
        r.demand_decay_risk,
        r.competitive_threat_risk,
        r.overall_risk_score,
        p.price_position_score,
        p.cost_shock_score,
        p.margin_pressure_risk,
        p.overall_margin_risk_score,
        c.data_completeness_score,
        c.data_freshness_score,
        c.overall_confidence_score,
        e.expansion_readiness_score,
        d.ppi_value,
        d.retail_price
    FROM `{PROJECT_ID}.{DATASET}.mart_demand_gap_scores`  d
    JOIN `{PROJECT_ID}.{DATASET}.mart_shelfrisk_scores`    r ON d.signal_id = r.signal_id
    JOIN `{PROJECT_ID}.{DATASET}.mart_price_margin_scores` p ON d.signal_id = p.signal_id
    JOIN `{PROJECT_ID}.{DATASET}.mart_confidence_layer`    c ON d.signal_id = c.signal_id
    JOIN `{PROJECT_ID}.{DATASET}.mart_expansion_readiness` e ON d.signal_id = e.signal_id
""")
print(f"Joined signal rows : {len(df_sig):,}")
print(f"Columns            : {df_sig.shape[1]}")
print(f"Non-null rows (any): {df_sig.dropna(how='all').shape[0]:,}")
'''))

cells.append(code('''
# â”€â”€ Correlation matrix heatmap â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
df_num = df_sig.select_dtypes(include=[np.number]).copy()
# Drop constant columns (std = 0 â†’ NaN correlations)
df_num = df_num.loc[:, df_num.std() > 0]
corr   = df_num.corr()

fig, ax = plt.subplots(figsize=(17, 14))
mask = np.triu(np.ones_like(corr, dtype=bool))
sns.heatmap(
    corr, mask=mask, ax=ax,
    cmap="coolwarm", center=0, vmin=-1, vmax=1,
    annot=True, fmt=".2f", annot_kws={"size": 6.5},
    linewidths=0.25, linecolor="#dee2e6",
    square=True, cbar_kws={"shrink": 0.65, "label": "Pearson r"}
)
ax.set_title("Signal Correlation Matrix (Lower Triangle)", fontsize=14, fontweight="bold")
plt.xticks(rotation=45, ha="right", fontsize=8)
plt.yticks(fontsize=8)
plt.tight_layout(); plt.show()
'''))

cells.append(code('''
# â”€â”€ Flag high-correlation pairs (|r| > 0.85) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print("=== High-Correlation Pairs  |r| > 0.85  (potential signal redundancy) ===")
cols_c = corr.columns.tolist()
high_r = []
for i in range(len(cols_c)):
    for j in range(i + 1, len(cols_c)):
        r = corr.iloc[i, j]
        if abs(r) > 0.85:
            high_r.append({"Signal A": cols_c[i], "Signal B": cols_c[j], "r": round(r, 3)})
            _findings["corr_warnings"].append(
                f"{cols_c[i]} â†” {cols_c[j]} (r={r:.2f})"
            )

if high_r:
    df_hr = pd.DataFrame(high_r).sort_values("r", key=abs, ascending=False)
    display(df_hr)
    print(f"\\n{len(high_r)} redundant pairs detected.")
else:
    print("No pairs with |r| > 0.85 found.")
'''))

cells.append(code('''
# â”€â”€ Validation scatterplots â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

df_samp = df_sig.dropna(subset=["avg_search_interest","overall_demand_gap_score"])
df_samp = df_samp.sample(min(800, len(df_samp)), random_state=42)
axes[0].scatter(df_samp["avg_search_interest"], df_samp["overall_demand_gap_score"],
                alpha=0.12, s=12, color="steelblue")
r0 = df_sig[["avg_search_interest","overall_demand_gap_score"]].dropna().corr().iloc[0,1]
axes[0].set_title(f"Google Trends Interest\\nvs Demand Gap Score  (r={r0:.3f})",
                  fontsize=11, fontweight="bold")
axes[0].set_xlabel("avg_search_interest"); axes[0].set_ylabel("overall_demand_gap_score")
axes[0].text(0.05, 0.93, f"r = {r0:.3f}", transform=axes[0].transAxes,
             fontsize=12, color="red", fontweight="bold")

df_ppi = df_sig.dropna(subset=["ppi_value","margin_pressure_risk"])
df_ppi_s = df_ppi.sample(min(800, len(df_ppi)), random_state=42)
axes[1].scatter(df_ppi_s["ppi_value"], df_ppi_s["margin_pressure_risk"],
                alpha=0.12, s=12, color="#e05c00")
r1 = df_ppi[["ppi_value","margin_pressure_risk"]].corr().iloc[0,1]
axes[1].set_title(f"PPI Value vs Margin Pressure Risk  (r={r1:.3f})",
                  fontsize=11, fontweight="bold")
axes[1].set_xlabel("ppi_value (FRED)"); axes[1].set_ylabel("margin_pressure_risk")
axes[1].text(0.05, 0.93, f"r = {r1:.3f}", transform=axes[1].transAxes,
             fontsize=12, color="red", fontweight="bold")

fig.suptitle("Signal Validation Scatterplots", fontsize=13, fontweight="bold", y=1.02)
plt.tight_layout(); plt.show()
'''))

# â”€â”€â”€ Section 7: Data Freshness Check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cells.append(md("## Section 7 â€” Data Freshness Check"))

cells.append(code('''
FRESHNESS_CFG = {
    f"Kroger Prices":   (f"SELECT MAX(DATE(collected_at)) FROM `{PROJECT_ID}.{DATASET}.stg_kroger_prices`",   7),
    f"Google Trends":   (f"SELECT MAX(trend_date) FROM `{PROJECT_ID}.{DATASET}.stg_google_trends`",           14),
    f"FRED PPI":        (f"SELECT MAX(observation_date) FROM `{PROJECT_ID}.{DATASET}.stg_fred_ppi`",          45),
    f"BLS CPI":         (f"SELECT MAX(reference_date) FROM `{PROJECT_ID}.{DATASET}.stg_bls_cpi`",             45),
    f"SerpAPI Prices":  (f"SELECT MAX(reference_date) FROM `{PROJECT_ID}.{DATASET}.stg_serpapi_prices`",      14),
}

today = datetime.date.today()
fresh_rows = []

for source, (sql, threshold) in FRESHNESS_CFG.items():
    try:
        last = list(BQ.query(sql).result())[0][0]
        if last is None:
            fresh_rows.append({"Source": source, "Last Updated": "NO DATA",
                                "Days Old": "â€“", "Threshold (days)": threshold, "Status": "âš  NO DATA"})
            _findings["stale_sources"].append(f"{source}: no data")
            continue
        last_date = last.date() if hasattr(last, "date") else last
        days = (today - last_date).days
        if days > threshold:
            status = f"STALE  ({days}d > {threshold}d)"
            _findings["stale_sources"].append(f"{source}: {days} days old")
        else:
            status = f"FRESH  ({days}d old)"
        fresh_rows.append({"Source": source, "Last Updated": str(last_date),
                           "Days Old": days, "Threshold (days)": threshold, "Status": status})
    except Exception as exc:
        fresh_rows.append({"Source": source, "Last Updated": "ERROR",
                           "Days Old": "â€“", "Threshold (days)": threshold, "Status": str(exc)[:60]})

def _style_status(val):
    if isinstance(val, str):
        if "FRESH"  in val: return "background-color:#d4edda;color:#155724"
        if "STALE"  in val: return "background-color:#f8d7da;color:#721c24"
        if "NO DATA" in val: return "background-color:#fff3cd;color:#856404"
    return ""

df_fresh = pd.DataFrame(fresh_rows)
print("=== Data Freshness Report ===")
display(df_fresh.style.map(_style_status, subset=["Status"]))
'''))

# â”€â”€â”€ Section 8: EDA Summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cells.append(md("## Section 8 â€” EDA Summary"))

cells.append(code('''
print("=" * 68)
print("  TRENDSHELF â€” EDA SUMMARY")
print("=" * 68)
print(f"  Total raw rows audited     : {_findings['total_raw_rows']:>10,}")
print()

crit = _findings["critical_nulls"]
warn = _findings["warning_nulls"]
print(f"  Null Audit")
print(f"    Critical nulls (> 30%)   : {len(crit)}")
for c in crit[:8]:
    print(f"      âœ—  {c}")
print(f"    Warning nulls  (10â€“30%)  : {len(warn)}")
for w in warn[:8]:
    print(f"      âš   {w}")
if not crit and not warn:
    print("    âœ“  No significant null issues found")
print()

sus = _findings["suspicious_dists"]
print(f"  Score Distributions")
print(f"    Suspicious (std < 5)     : {len(sus)}")
for s in sus[:8]:
    print(f"      âš   {s}")
if not sus:
    print("    âœ“  All score distributions show healthy variance")
print()

corr_w = _findings["corr_warnings"]
print(f"  Correlation Warnings")
print(f"    High-r pairs (|r| > 0.85): {len(corr_w)}")
for cw in corr_w[:8]:
    print(f"      âš   {cw}")
if not corr_w:
    print("    âœ“  No redundant signal pairs detected")
print()

stale = _findings["stale_sources"]
print(f"  Data Freshness")
print(f"    Stale sources            : {len(stale)}")
for s in stale:
    print(f"      âš   {s}")
if not stale:
    print("    âœ“  All sources within acceptable freshness window")
print()

# â”€â”€ Data Quality Score â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
quality = 100
quality -= len(crit)   * 10
quality -= len(warn)   *  3
quality -= len(sus)    *  5
quality -= len(stale)  *  8
quality -= len(corr_w) *  2
quality = max(0, min(100, quality))

grade = ("Excellent â€” production-ready" if quality >= 85 else
         "Good â€” minor issues to address" if quality >= 70 else
         "Fair â€” address warnings before dashboard" if quality >= 50 else
         "Poor â€” significant data quality issues")

print(f"  Overall Data Quality Score : {quality}/100  ({grade})")
print()
print("  Recommended Fixes Before Dashboard Build:")
recs = []
if crit:
    recs.append("Resolve CRITICAL null columns (> 30% null rate)")
if stale:
    recs.append("Re-run collect_apis.py to refresh stale data sources")
if sus:
    recs.append("Verify proxy vs measured coverage for uniform-distribution scores")
if corr_w:
    recs.append("Consider consolidating redundant features (|r| > 0.85)")
if not recs:
    recs.append("None â€” data is production-ready for dashboard build")
for rec in recs:
    print(f"  â†’  {rec}")
print("=" * 68)
'''))

# â”€â”€â”€ Assemble and write notebook â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "codemirror_mode": {"name": "ipython", "version": 3},
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "pygments_lexer": "ipython3",
            "version": "3.12.4",
        },
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = os.path.join("notebooks", "trendshelf_eda.ipynb")
with open(out, "w", encoding="utf-8") as fh:
    json.dump(nb, fh, indent=1, ensure_ascii=False)

print(f"Created: {out}  ({len(cells)} cells)")
