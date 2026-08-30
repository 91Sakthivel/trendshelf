"""
Signal-Stability Backtest — Phase 0

Validation, not prediction. Does not touch any existing mart, model, or test.
All data read from BigQuery `bronze`; zero external API cost.

Reproduces every number reported in docs/signal_stability_backtest.md, in the
same order as that document's sections. Run end-to-end from the repo root
(so `.env` / `credentials.json` resolve correctly):

    python scripts/signal_stability_backtest.py

Each permutation-null phase (main results, CHECK 1) uses its own freshly
seeded RNG (seed=20260830), matching how this analysis was actually run
section-by-section — re-running this script reproduces the doc's numbers
exactly, against the same `bronze` snapshot.

See docs/signal_stability_backtest.md for the full write-up, interpretation,
and the framing note on what price_gap_reliability was and wasn't built to
measure.
"""

import os
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account

load_dotenv()

P = os.environ.get("GCP_PROJECT_ID", "windy-container-451804-n4")
_creds = service_account.Credentials.from_service_account_file(
    os.environ.get("GCP_CREDENTIALS_PATH", "credentials.json"),
    scopes=["https://www.googleapis.com/auth/bigquery"],
)
client = bigquery.Client(project=P, credentials=_creds)

# Same vars as models/marts/mart_pricing_intelligence.sql / dbt_project.yml
RELIABILITY_MIN_COMPETITOR_COUNT = 10
MAX_COMPETITOR_STALENESS_DAYS = 14
RELIABILITY_LOW_GAP_THRESHOLD = 50.0
RELIABILITY_MEDIUM_GAP_THRESHOLD = 25.0

# Locked in docs/signal_stability_backtest.md §4 (natural-gap method, calendar-only)
MAGNITUDE_BAND_PP = 0.08

# Locked in docs/signal_stability_backtest.md §7 (1D natural-breaks clustering, k=3)
MAGNITUDE_CUT_1 = (32.69 + 33.84) / 2   # 33.265
MAGNITUDE_CUT_2 = (103.20 + 107.83) / 2  # 105.515

CAL_DATES = pd.to_datetime([
    '2026-06-10', '2026-06-17', '2026-06-24', '2026-07-01', '2026-07-08',
    '2026-07-15', '2026-07-22', '2026-07-29', '2026-08-05', '2026-08-12',
    '2026-08-19', '2026-08-26',
])

N_PERMUTATIONS = 500
SEED = 20260830


def q(sql):
    return client.query(sql).to_dataframe()


def reliability(row):
    if pd.isna(row['competitor_median_price']) or pd.isna(row['kroger_median_price']):
        return 'Unknown'
    if row['competitor_product_count'] < RELIABILITY_MIN_COMPETITOR_COUNT:
        return 'Low'
    if row['competitor_staleness_days'] > MAX_COMPETITOR_STALENESS_DAYS:
        return 'Low'
    if abs(row['price_gap_pct']) > RELIABILITY_LOW_GAP_THRESHOLD:
        return 'Low'
    if abs(row['price_gap_pct']) > RELIABILITY_MEDIUM_GAP_THRESHOLD:
        return 'Medium'
    return 'High'


def directional_signal(row):
    if row['gap_direction_stable'] is not True:
        return 'Insufficient Data'
    if row['price_gap_reliability_backtest'] in ('Low', 'Unknown'):
        return 'Unreliable Benchmark'
    if row['price_position'] == 'Overpriced':
        return 'Sustained Overpriced'
    if row['price_position'] == 'Underpriced':
        return 'Sustained Underpriced'
    if row['price_position'] == 'Fair':
        return 'Sustained Fair'
    return 'Insufficient Data'


def magnitude_band(abs_gap):
    if pd.isna(abs_gap):
        return np.nan
    if abs_gap <= MAGNITUDE_CUT_1:
        return 'Small (<=33.3%)'
    if abs_gap <= MAGNITUDE_CUT_2:
        return 'Moderate (33.3-105.5%)'
    return 'Large (>105.5%)'


def load_panel():
    """Pull fct_store_category_weekly + int_pricing_temporal_features, reproduce
    price_gap_reliability_backtest / directional_pricing_signal_backtest."""
    df = q(f"""
        select
            f.kroger_collection_date, f.store_id, f.category_name,
            f.price_gap_pct, f.price_gap_direction, f.price_position,
            f.competitor_median_price, f.kroger_median_price,
            f.competitor_product_count, f.competitor_staleness_days,
            f.competitor_asof_date,
            t.gap_direction_stable
        from `{P}.bronze.fct_store_category_weekly` f
        join `{P}.bronze.int_pricing_temporal_features` t
          on f.kroger_collection_date = t.kroger_collection_date
         and f.store_id = t.store_id
         and f.category_name = t.category_name
        order by f.store_id, f.category_name, f.kroger_collection_date
    """)
    df['kroger_collection_date'] = pd.to_datetime(df['kroger_collection_date'])
    df['competitor_asof_date'] = pd.to_datetime(df['competitor_asof_date'])
    df['price_gap_reliability_backtest'] = df.apply(reliability, axis=1)
    df['directional_pricing_signal_backtest'] = df.apply(directional_signal, axis=1)
    return df


def build_panels(df, dates):
    sub = df[df['kroger_collection_date'].isin(dates)].copy()
    direction = sub.pivot_table(index=['store_id', 'category_name'], columns='kroger_collection_date',
                                 values='price_gap_direction', aggfunc='first')
    gap_pct = sub.pivot_table(index=['store_id', 'category_name'], columns='kroger_collection_date',
                               values='price_gap_pct', aggfunc='first')
    reliability_p = sub.pivot_table(index=['store_id', 'category_name'], columns='kroger_collection_date',
                                     values='price_gap_reliability_backtest', aggfunc='first')
    action = sub.pivot_table(index=['store_id', 'category_name'], columns='kroger_collection_date',
                              values='directional_pricing_signal_backtest', aggfunc='first')
    date_cols = sorted(direction.columns)
    return direction[date_cols], gap_pct[date_cols], reliability_p[date_cols], action[date_cols], date_cols


def permute_row_inplace(arr, rng):
    mask = pd.notna(arr)
    vals = arr[mask]
    if len(vals) > 1:
        arr = arr.copy()
        arr[mask] = rng.permutation(vals)
    return arr


def permute_panel(panel, rng):
    arr = panel.to_numpy(dtype=object)
    out = np.empty_like(arr)
    for i in range(arr.shape[0]):
        out[i] = permute_row_inplace(arr[i], rng)
    return pd.DataFrame(out, index=panel.index, columns=panel.columns)


# ─────────────────────────────────────────────────────────────────────────────
# §2 — Proof the reproductions match production
# ─────────────────────────────────────────────────────────────────────────────

def section_2_reproduction_proof():
    print("\n" + "=" * 100)
    print("§2 — Proof the reproductions match production")
    print("=" * 100)

    sql = f"""
    with backtest as (
        select
            f.kroger_collection_date, f.store_id, f.category_name, f.price_position,
            t.gap_direction_stable,
            CASE
                WHEN f.competitor_median_price IS NULL OR f.kroger_median_price IS NULL THEN 'Unknown'
                WHEN f.competitor_product_count < {RELIABILITY_MIN_COMPETITOR_COUNT} THEN 'Low'
                WHEN f.competitor_staleness_days > {MAX_COMPETITOR_STALENESS_DAYS} THEN 'Low'
                WHEN ABS(f.price_gap_pct) > {RELIABILITY_LOW_GAP_THRESHOLD} THEN 'Low'
                WHEN ABS(f.price_gap_pct) > {RELIABILITY_MEDIUM_GAP_THRESHOLD} THEN 'Medium'
                ELSE 'High'
            END as price_gap_reliability_backtest
        from `{P}.bronze.fct_store_category_weekly` f
        join `{P}.bronze.int_pricing_temporal_features` t
          on f.kroger_collection_date = t.kroger_collection_date
         and f.store_id = t.store_id
         and f.category_name = t.category_name
        where f.kroger_collection_date = (select max(kroger_collection_date) from `{P}.bronze.fct_store_category_weekly`)
    ),
    backtest_with_signal as (
        select *,
            CASE
                WHEN NOT COALESCE(gap_direction_stable, FALSE) THEN 'Insufficient Data'
                WHEN price_gap_reliability_backtest IN ('Low','Unknown') THEN 'Unreliable Benchmark'
                WHEN price_position = 'Overpriced' THEN 'Sustained Overpriced'
                WHEN price_position = 'Underpriced' THEN 'Sustained Underpriced'
                WHEN price_position = 'Fair' THEN 'Sustained Fair'
                ELSE 'Insufficient Data'
            END as directional_pricing_signal_backtest
        from backtest
    ),
    prod as (
        select store_id, category_name,
               price_gap_reliability as price_gap_reliability_prod,
               directional_pricing_signal as directional_pricing_signal_prod
        from `{P}.bronze.mart_pricing_intelligence`
    )
    select
        b.kroger_collection_date,
        count(*) as n_rows,
        countif(b.price_gap_reliability_backtest = p.price_gap_reliability_prod) as reliability_match,
        countif(b.price_gap_reliability_backtest != p.price_gap_reliability_prod) as reliability_mismatch,
        countif(b.directional_pricing_signal_backtest = p.directional_pricing_signal_prod) as signal_match,
        countif(b.directional_pricing_signal_backtest != p.directional_pricing_signal_prod) as signal_mismatch
    from backtest_with_signal b
    join prod p using (store_id, category_name)
    group by 1
    """
    print(q(sql).to_string(index=False))


# ─────────────────────────────────────────────────────────────────────────────
# §3 — The zero-change transitions
# ─────────────────────────────────────────────────────────────────────────────

def section_3_zero_transitions(df):
    print("\n" + "=" * 100)
    print("§3 — The 618 zero-change transitions — investigated, not assumed")
    print("=" * 100)

    g = df.groupby(['store_id', 'category_name'])
    seq = df.copy()
    seq['prev_kroger_median_price'] = g['kroger_median_price'].shift(1)
    seq['prev_competitor_median_price'] = g['competitor_median_price'].shift(1)
    seq['prev_competitor_asof_date'] = g['competitor_asof_date'].shift(1)
    seq['prev_price_gap_pct'] = g['price_gap_pct'].shift(1)
    seq = seq.dropna(subset=['prev_price_gap_pct']).copy()
    seq['gap_change'] = (seq['price_gap_pct'] - seq['prev_price_gap_pct']).round(2)
    seq['is_zero'] = seq['gap_change'].abs() < 0.005
    seq['asof_unchanged'] = seq['competitor_asof_date'] == seq['prev_competitor_asof_date']

    print(f"Total sequence T->T+1 transitions: {len(seq)}")
    print(f"Exact-zero gap_change transitions: {seq['is_zero'].sum()}")
    zeros = seq[seq['is_zero']]
    print(f"Of those, asof_unchanged (stale-carry double count): {zeros['asof_unchanged'].sum()}")

    # calendar-only re-derivation
    cal = df[df['kroger_collection_date'].isin(CAL_DATES)].copy()
    gcal = cal.groupby(['store_id', 'category_name'])
    cal['prev_competitor_asof_date'] = gcal['competitor_asof_date'].shift(1)
    cal['prev_price_gap_pct'] = gcal['price_gap_pct'].shift(1)
    calseq = cal.dropna(subset=['prev_price_gap_pct']).copy()
    calseq['gap_change'] = (calseq['price_gap_pct'] - calseq['prev_price_gap_pct']).round(2)
    calseq['is_zero'] = calseq['gap_change'].abs() < 0.005
    calseq['asof_unchanged'] = calseq['competitor_asof_date'] == calseq['prev_competitor_asof_date']
    print(f"\nCalendar-only transitions: {len(calseq)}")
    print(f"Calendar-only zero-change transitions: {calseq['is_zero'].sum()}")
    print(f"Calendar-only zero transitions with asof_unchanged: {(calseq['is_zero'] & calseq['asof_unchanged']).sum()}")
    return calseq


# ─────────────────────────────────────────────────────────────────────────────
# §4 — Magnitude band derivation
# ─────────────────────────────────────────────────────────────────────────────

def section_4_magnitude_band(calseq):
    print("\n" + "=" * 100)
    print("§4 — Magnitude band, natural-gap method, calendar-only")
    print("=" * 100)
    clean = calseq[~calseq['asof_unchanged']]
    vals = clean['gap_change'].abs().round(2).value_counts().sort_index()
    print(f"n = {len(clean)}")
    print(vals.head(15))
    print(f"\nLocked band: {MAGNITUDE_BAND_PP}pp (midpoint of the empty interval between the two smallest "
          f"non-zero values and the next cluster)")


# ─────────────────────────────────────────────────────────────────────────────
# §5/§6 — Main results: direction / magnitude / action persistence, with null
# ─────────────────────────────────────────────────────────────────────────────

def compute_transitions(direction_panel, gap_panel, reliability_panel, action_panel, date_cols, n):
    rows = []
    for i in range(len(date_cols) - n):
        t_date, tn_date = date_cols[i], date_cols[i + n]
        d_t, d_tn = direction_panel[t_date], direction_panel[tn_date]
        g_t, g_tn = gap_panel[t_date].astype(float), gap_panel[tn_date].astype(float)
        r_t = reliability_panel[t_date]
        a_t, a_tn = action_panel[t_date], action_panel[tn_date]

        valid_dir = d_t.notna() & d_tn.notna() & (d_t != 'Unknown') & (d_tn != 'Unknown')
        valid_mag = g_t.notna() & g_tn.notna()
        valid_act = a_t.notna() & a_tn.notna()

        chunk = pd.DataFrame({
            'reliability_at_t': r_t,
            'direction_valid': valid_dir,
            'direction_stable': np.where(valid_dir, d_t == d_tn, np.nan),
            'magnitude_valid': valid_mag,
            'magnitude_stable': np.where(valid_mag, (g_tn - g_t).abs() <= MAGNITUDE_BAND_PP, np.nan),
            'action_valid': valid_act,
            'action_stable': np.where(valid_act, a_t == a_tn, np.nan),
        }, index=direction_panel.index)
        rows.append(chunk)
    return pd.concat(rows) if rows else pd.DataFrame()


def summarize(trans, label):
    out = []
    for measure, valid_col, stable_col in [
        ('direction', 'direction_valid', 'direction_stable'),
        ('magnitude', 'magnitude_valid', 'magnitude_stable'),
        ('action', 'action_valid', 'action_stable'),
    ]:
        sub = trans[trans[valid_col]]
        n = len(sub)
        rate = sub[stable_col].astype(float).mean() if n else np.nan
        out.append({'basis': label, 'measure': measure, 'stratum': 'ALL', 'n': n, 'rate': rate})
        for strat in ['High', 'Medium', 'Low', 'Unknown']:
            ssub = sub[sub['reliability_at_t'] == strat]
            sn = len(ssub)
            srate = ssub[stable_col].astype(float).mean() if sn else np.nan
            out.append({'basis': label, 'measure': measure, 'stratum': strat, 'n': sn, 'rate': srate})
    return pd.DataFrame(out)


def section_5_6_main_results(panels):
    print("\n" + "=" * 100)
    print("§5/§6 — Main results: direction / magnitude / action persistence vs. permutation null")
    print("=" * 100)

    observed = []
    for basis_name, (dpanel, gpanel, rpanel, apanel, dates) in panels.items():
        for n in [1, 2, 3]:
            trans = compute_transitions(dpanel, gpanel, rpanel, apanel, dates, n)
            if trans.empty:
                continue
            summ = summarize(trans, basis_name)
            summ['horizon'] = f'T+{n}'
            observed.append(summ)
    observed_df = pd.concat(observed, ignore_index=True)

    rng = np.random.default_rng(SEED)  # fresh RNG for this permutation phase
    null_results = {}
    for basis_name, (dpanel, gpanel, rpanel, apanel, dates) in panels.items():
        for _ in range(N_PERMUTATIONS):
            dpanel_p = permute_panel(dpanel, rng)
            gpanel_p = permute_panel(gpanel, rng)
            apanel_p = permute_panel(apanel, rng)
            for n in [1, 2, 3]:
                trans = compute_transitions(dpanel_p, gpanel_p, rpanel, apanel_p, dates, n)
                if trans.empty:
                    continue
                for measure, valid_col, stable_col in [
                    ('direction', 'direction_valid', 'direction_stable'),
                    ('magnitude', 'magnitude_valid', 'magnitude_stable'),
                    ('action', 'action_valid', 'action_stable'),
                ]:
                    sub = trans[trans[valid_col]]
                    rate = sub[stable_col].astype(float).mean() if len(sub) else np.nan
                    null_results.setdefault((basis_name, f'T+{n}', measure, 'ALL'), []).append(rate)
                    for strat in ['High', 'Medium', 'Low', 'Unknown']:
                        ssub = sub[sub['reliability_at_t'] == strat]
                        srate = ssub[stable_col].astype(float).mean() if len(ssub) else np.nan
                        null_results.setdefault((basis_name, f'T+{n}', measure, strat), []).append(srate)
        print(f"  done {basis_name} permutations")

    null_rows = []
    for (basis, horizon, measure, stratum), rates in null_results.items():
        rates = np.array([r for r in rates if not np.isnan(r)])
        if len(rates) == 0:
            continue
        null_rows.append({
            'basis': basis, 'horizon': horizon, 'measure': measure, 'stratum': stratum,
            'null_mean': rates.mean(), 'null_p5': np.percentile(rates, 5), 'null_p95': np.percentile(rates, 95),
        })
    null_df = pd.DataFrame(null_rows)
    merged = observed_df.merge(null_df, on=['basis', 'horizon', 'measure', 'stratum'], how='left')
    merged['lift_vs_null'] = merged['rate'] - merged['null_mean']

    pd.set_option('display.max_rows', 300)
    pd.set_option('display.width', 200)
    print(merged[merged['stratum'] != 'Unknown'].to_string(index=False))
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# §7 — CHECK 1: matched-magnitude test of the root-cause hypothesis
# ─────────────────────────────────────────────────────────────────────────────

def compute_direction_transitions_with_band(direction_panel, gap_panel, reliability_panel, date_cols, n):
    rows = []
    for i in range(len(date_cols) - n):
        t_date, tn_date = date_cols[i], date_cols[i + n]
        d_t, d_tn = direction_panel[t_date], direction_panel[tn_date]
        g_t = gap_panel[t_date].astype(float)
        r_t = reliability_panel[t_date]
        mband_t = g_t.abs().apply(magnitude_band)
        valid_dir = d_t.notna() & d_tn.notna() & (d_t != 'Unknown') & (d_tn != 'Unknown')
        chunk = pd.DataFrame({
            'reliability_at_t': r_t,
            'magnitude_band_at_t': mband_t,
            'direction_valid': valid_dir,
            'direction_stable': np.where(valid_dir, d_t == d_tn, np.nan),
        }, index=direction_panel.index)
        rows.append(chunk)
    return pd.concat(rows) if rows else pd.DataFrame()


def section_7_check1_matched_magnitude(panels):
    print("\n" + "=" * 100)
    print("§7 — CHECK 1: root-cause hypothesis tested at matched magnitude")
    print("=" * 100)

    bands = ['Small (<=33.3%)', 'Moderate (33.3-105.5%)', 'Large (>105.5%)']
    tiers = ['High', 'Medium', 'Low']

    observed = []
    for basis_name, (dpanel, gpanel, rpanel, apanel, dates) in panels.items():
        for n in [1, 2, 3]:
            trans = compute_direction_transitions_with_band(dpanel, gpanel, rpanel, dates, n)
            sub = trans[trans['direction_valid']]
            for rel in tiers:
                for mband in bands:
                    cell = sub[(sub['reliability_at_t'] == rel) & (sub['magnitude_band_at_t'] == mband)]
                    cn = len(cell)
                    rate = cell['direction_stable'].astype(float).mean() if cn else np.nan
                    observed.append({'basis': basis_name, 'horizon': f'T+{n}', 'reliability': rel,
                                      'magnitude_band': mband, 'n': cn, 'observed_rate': rate})
    observed_df = pd.DataFrame(observed)

    rng = np.random.default_rng(SEED)  # fresh RNG for this permutation phase
    null_results = {}
    for basis_name, (dpanel, gpanel, rpanel, apanel, dates) in panels.items():
        for _ in range(N_PERMUTATIONS):
            dpanel_p = permute_panel(dpanel, rng)
            for n in [1, 2, 3]:
                trans = compute_direction_transitions_with_band(dpanel_p, gpanel, rpanel, dates, n)
                sub = trans[trans['direction_valid']]
                for rel in tiers:
                    for mband in bands:
                        cell = sub[(sub['reliability_at_t'] == rel) & (sub['magnitude_band_at_t'] == mband)]
                        if len(cell) == 0:
                            continue
                        rate = cell['direction_stable'].astype(float).mean()
                        null_results.setdefault((basis_name, f'T+{n}', rel, mband), []).append(rate)
        print(f"  done {basis_name} permutations")

    null_rows = []
    for (basis, horizon, rel, mband), rates in null_results.items():
        rates = np.array([r for r in rates if not np.isnan(r)])
        if len(rates) == 0:
            continue
        null_rows.append({'basis': basis, 'horizon': horizon, 'reliability': rel, 'magnitude_band': mband,
                           'null_mean': rates.mean(), 'null_p5': np.percentile(rates, 5),
                           'null_p95': np.percentile(rates, 95)})
    null_df = pd.DataFrame(null_rows)
    merged = observed_df.merge(null_df, on=['basis', 'horizon', 'reliability', 'magnitude_band'], how='left')
    merged['lift_vs_null'] = merged['observed_rate'] - merged['null_mean']

    pd.set_option('display.max_rows', 300)
    pd.set_option('display.width', 220)
    print(merged.to_string(index=False))
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# §8 — CHECK 2: confirming the calendar basis is genuinely clean
# ─────────────────────────────────────────────────────────────────────────────

def section_8_check2_calendar_clean(df):
    print("\n" + "=" * 100)
    print("§8 — CHECK 2: calendar-basis staleness and asof-date reuse")
    print("=" * 100)

    cal = df[df['kroger_collection_date'].isin(CAL_DATES)].copy()
    print("competitor_staleness_days distribution, all calendar-basis rows:")
    print(cal['competitor_staleness_days'].value_counts().sort_index().to_string())

    asof_piv = cal.pivot_table(index=['store_id', 'category_name'], columns='kroger_collection_date',
                                values='competitor_asof_date', aggfunc='first')
    dates_sorted = sorted(asof_piv.columns)
    for n in [1, 2, 3]:
        same_asof = 0
        total = 0
        for i in range(len(dates_sorted) - n):
            t, tn = dates_sorted[i], dates_sorted[i + n]
            a_t, a_tn = asof_piv[t], asof_piv[tn]
            valid = a_t.notna() & a_tn.notna()
            same = valid & (a_t == a_tn)
            total += valid.sum()
            same_asof += same.sum()
        print(f"T+{n}: valid pairs={total}, sharing SAME competitor_asof_date={same_asof} "
              f"({same_asof / total * 100:.2f}%)")


if __name__ == "__main__":
    df = load_panel()
    print(f"Loaded {len(df)} rows, {df.groupby(['store_id', 'category_name']).ngroups} pairs, "
          f"{df['kroger_collection_date'].nunique()} dates")

    section_2_reproduction_proof()
    calseq = section_3_zero_transitions(df)
    section_4_magnitude_band(calseq)

    cal_panels = build_panels(df, CAL_DATES)
    all_dates = sorted(df['kroger_collection_date'].unique())
    seq_panels = build_panels(df, all_dates)
    panels = {'calendar': cal_panels, 'sequence': seq_panels}

    section_5_6_main_results(panels)
    section_7_check1_matched_magnitude(panels)
    section_8_check2_calendar_clean(df)
