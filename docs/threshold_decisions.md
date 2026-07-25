# TrendShelf — Threshold and Prior Decisions

## 1. Purpose

This file records where the judgement-call numbers in TrendShelf came from. It does not record every constant — structural constants such as 0, 1, or 100 are not listed. The focus is on values that influence a score, label, API call, or action recommendation, where a different reasonable choice would produce a materially different result. Each entry states the source of the value and the conditions under which it should be revisited.

---

## 2. Category sensitivity priors

The table below is verbatim from the `category_elasticity` CTE in `models/marts/mart_pricing_intelligence.sql`. These values are **analyst-set priors** reflecting general grocery category behaviour based on published CPG and retail industry knowledge. They are **not measured from TrendShelf data**. TrendShelf does not have sales velocity or units-sold data; replacing these priors with empirically derived price sensitivity estimates would require time-series sales/units data that the project does not currently collect.

The priors are used in two places in `mart_pricing_intelligence.sql`:

- `category_sensitivity_tier` gates the Hold Premium and Review Price Reduction cascade branches (values `'Low'`, `'Medium'`, `'High'` control elasticity direction).
- `category_premium_tolerance_prior_score` is one of five inputs to `premium_support_proxy_score` with weight 0.20. It shifts pricing power upward for categories where consumers historically tolerate premium pricing relative to mass-market retailers.

| Category | Sensitivity tier | Premium tolerance prior score |
|---|---|---|
| beverages | Low | 70 |
| snacks | Medium | 55 |
| dairy | High | 30 |
| frozen foods | High | 35 |
| breakfast cereal | Medium | 55 |
| meat seafood | High | 30 |
| produce | High | 25 |
| personal care | Low | 75 |
| household | High | 35 |
| coffee tea | Low | 80 |

**Tier interpretation:** High = price-sensitive (consumers readily substitute on price); Low = price-tolerant (brand or quality justifies Kroger premium over Walmart). Medium is intermediate.

**When to revisit:** If a category is added to `config.py:CATEGORIES` it must also be added to this STRUCT; the singular test `tests/assert_elasticity_prior_coverage.sql` will fail if it is not. Values should be recalibrated once sales/units data is available.

---

## 3. Externalized thresholds (dbt_project.yml vars)

These values are externalized because they appear in multiple models or are expected to be tuned as more data accumulates. The current values are as of 2026-07-23.

| Var name | Value | Controls |
|---|---|---|
| `opp_weight_demand` | 0.25 | overall_opportunity_score weight for demand |
| `opp_weight_expansion` | 0.20 | overall_opportunity_score weight for expansion |
| `opp_weight_pricing` | 0.20 | overall_opportunity_score weight for pricing power |
| `opp_weight_confidence` | 0.15 | overall_opportunity_score weight for confidence |
| `opp_weight_risk` | 0.10 | overall_opportunity_score weight for risk |
| `opp_weight_margin` | 0.10 | overall_opportunity_score weight for margin |
| `opp_tier_prime` | 75 | Opportunity tier: Prime threshold |
| `opp_tier_solid` | 55 | Opportunity tier: Solid threshold |
| `opp_tier_watch` | 35 | Opportunity tier: Watch threshold |
| `demand_high_threshold` | 65 | Demand signal High cutoff |
| `demand_medium_threshold` | 45 | Demand signal Medium cutoff |
| `confidence_high` | 75 | Confidence level HIGH cutoff |
| `confidence_medium` | 50 | Confidence level MEDIUM cutoff |
| `investigate_confidence_threshold` | 45 | INVESTIGATE gate: confidence below this |
| `avoid_margin_pressure_threshold` | 80 | AVOID gate: margin pressure above this |
| `avoid_markdown_safety_threshold` | 40 | AVOID gate: markdown safety below this |
| `expand_readiness_threshold` | 80 | EXPAND gate: readiness above this |
| `expand_confidence_threshold` | 70 | EXPAND gate: confidence above this |
| `expand_margin_threshold` | 70 | Review Price Increase gate: pricing power minimum |
| `margin_pressure_avoid_threshold` | 65 | Review Price Increase gate: margin pressure maximum |
| `pricing_power_hold_threshold` | 70 | Hold Premium gate: pricing power minimum |
| `pricing_power_strong_threshold` | 75 | Hold Premium gate: bypass relevance check |
| `reduce_price_min_gap_pct` | 10 | Review Price Reduction gate: minimum adjusted gap (%) |
| `markdown_safety_full_threshold` | 60 | Full vs Partial cut boundary |
| `competitive_threat_threshold` | 70 | Protect Price gate: threat above this blocks |
| `cv_multiplier` | 0.16 | Price band width: CV × multiplier |
| `min_price_gap_threshold` | 8.0 | Price band floor (%) |
| `max_price_gap_threshold` | 25.0 | Price band ceiling (%) |
| `reliability_low_gap_threshold` | 50.0 | Gap above this → Low reliability |
| `reliability_medium_gap_threshold` | 25.0 | Gap above this → Medium reliability |
| `reliability_min_competitor_count` | 10 | Fewer competitor products → Low reliability |
| `max_competitor_staleness_days` | 14 | Competitor price older than this → Low reliability |
| `confidence_smoothing_k` | 15.0 | Laplace smoothing parameter for price_gap_confidence_weight |
| `demand_slope_rising_threshold` | 0.3 | OLS slope-to-noise ratio for demand_state classification |
| `directional_established_min_dates` | 4 | Collections needed to graduate from Provisional to Persistent |
| `threshold_config_version` | 'v4_cv_calibrated' | Version tag stamped on output rows |

---

## 4. Scoring formula weights — deliberately NOT externalized

The per-formula weights (e.g. markdown_safety_score's 0.45/0.30/0.25, premium_support_proxy_score's 0.30/0.20/0.20/0.15/0.15, and the five other composite scores) are kept inline in each model rather than moved to dbt vars.

The reason: a weight belongs next to the formula it governs. A reader looking at the SQL sees both the components and their relative importance together; moving them to a config file requires two files to understand one computation. Additionally, changing a weight without simultaneously reviewing the adjacent formula and its neighbours is error-prone — the inline placement creates natural friction that prevents casual tuning of unvalidated knobs. These weights should only change when a specific empirical finding justifies it, at which point the formula and weight change together in the same commit.

---

## 5. Naming changelog

### Commit 875822a — naming-honesty pass (string values only)

Output string values were renamed to reflect what the system actually recommends rather than the bare action. No formula, threshold, or cascade logic changed.

| Old value | New value | Column |
|---|---|---|
| `'Reduce Price'` | `'Review Price Reduction'` | `mart_pricing_intelligence.recommended_price_action` |
| `'Raise Price'` | `'Review Price Increase'` | `mart_pricing_intelligence.recommended_price_action` |
| `'3 Wk Streak'` (or prior name) | `'3-Collection Streak'` | `mart_weekly_events.event_type` |
| prior directional value | `'Persistent'` | `mart_pricing_intelligence.directional_signal_confidence` |

### Commit 2a — column renames (field names only)

Internal column names were renamed to be self-describing. No score value, formula, weight, threshold, or cascade condition changed. The underlying STRUCT values (tier strings and prior scores) are identical.

| Old name | New name | Files |
|---|---|---|
| `elasticity_tier` | `category_sensitivity_tier` | `mart_pricing_intelligence.sql`, `schema.yml`, `dashboard/queries.py`, `dashboard/app.py` |
| `premium_tolerance_score` | `category_premium_tolerance_prior_score` | `mart_pricing_intelligence.sql`, `dashboard/queries.py`, `dashboard/app.py` |

### Commit 3 — column rename (`pricing_power_score`)

Reason: the score measures whether available signals SUPPORT holding a premium; it does not measure true pricing power, which would require sales and margin data. No formula, weight, threshold, or cascade condition changed — only the column name.

| Old name | New name | Files |
|---|---|---|
| `pricing_power_score` | `premium_support_proxy_score` | `mart_pricing_intelligence.sql`, `mart_action_queue.sql`, `schema.yml`, `dashboard/queries.py`, `dashboard/app.py`, `docs/threshold_decisions.md`, `docs/scoring_methodology.md` |

### Commit 4 — column rename (`margin_pressure_risk`) + user-facing wording

Reason: the score infers margin pressure by comparing Kroger's own shelf-price trend to the FRED PPI index. No cost, margin, or COGS figure is read anywhere. "proxy" marks it as inferred, matching `premium_support_proxy_score`. No formula, weight, threshold, or cascade condition changed — only the column name and three user-facing strings.

| Old name | New name | Files |
|---|---|---|
| `margin_pressure_risk` | `margin_pressure_proxy_score` | `mart_price_margin_scores.sql`, `mart_action_queue.sql`, `mart_confidence_layer.sql`, `mart_expansion_readiness.sql`, `mart_pricing_intelligence.sql`, `schema.yml`, `docs/scoring_methodology.md` |

**What `margin_pressure_proxy_score` uses and does not use:**
- Uses: Kroger's own retail shelf-price trend (`AVG(price_regular)` from `stg_kroger_prices`, month over month) and the FRED Producer Price Index trend (`stg_fred_ppi`, an external industry-wide macro series).
- Does not use: supplier cost, COGS, or any observed margin figure. Nothing in this model reads an actual cost or margin number for the brand or product — the score is a rule-based classification of whether retail price kept pace with a macro cost proxy, not a measurement of margin.

**User-facing wording changed (zero numeric impact, same CASE conditions):**
- `mart_expansion_readiness.sql` — the `'FIX MARGINS'` recommendation string no longer says "negotiate COGS" (implies observed supplier cost data that doesn't exist). Now: "Shelf price has not kept pace with rising category input costs (inferred from industry price indices, not observed supplier costs) — review cost position before expanding."
- `mart_action_queue.sql:316` (action_description) — "margin pressure (N/100)" → "cost-pressure indicator (N/100)".
- `mart_action_queue.sql:402` (action_justification) — "margins critically squeezed" → "cost-pressure indicator elevated"; "margin pressure N" → "cost-pressure indicator N".

**Left unchanged, deliberately:**
- `dbt_project.yml` var names `avoid_margin_pressure_threshold` and `margin_pressure_avoid_threshold`, and their mirrors in `README.md` — these are threshold var identifiers, a separate naming surface from the column itself.
- `docs/session_notes_batch3_hardening.md` and notebook files — dated historical records, not live reference docs.
- `mart_action_queue.sql:455` — the `reason_code` literal `'PROMO_RISK_MARGIN_PRESSURE'`. This is a machine token (a `reason_code`, not display text) with no user-facing consumer; left as-is.

**Noted duplication:** `mart_pricing_intelligence.sql:435` re-applies `COALESCE(margin_pressure_proxy_score, 30)` on top of the producer's own NULL handling in `mart_price_margin_scores.sql:189` (which already resolves NULL inputs to 30 before the value ever leaves that model). The column can never actually be NULL by the time it reaches `mart_pricing_intelligence`, so this second COALESCE is inert — not a bug, just redundant defensive code. Not changed as part of this rename (formula/logic untouched by instruction).

**Open finding — STEP 3 measurement (2026-07-23):** The "healthy" branch (`GREATEST(0, 30 − Δretail_price / 5.0)`, where `Δretail_price = retail_price − retail_price_1m_ago`) currently produces scores confined to **29.52–30.00** across all 71 rows that reach it (55 distinct rounded values, but all within a 0.48-point band out of the score's 0–100 range), even though the underlying `Δretail_price` ranges from $0.01 to $2.40 — a 200× spread in input collapsed to <0.5% of output range by the `/5.0` divisor. Branch membership overall: 329 rows `BRANCH_55_COMPRESSION`, 71 rows `BRANCH_HEALTHY`, 0 rows `BRANCH_80_SQUEEZE`, 0 rows `BRANCH_40_COST_RISING`, 0 rows `NULL_FALLBACK_30` (determined by reconstructing the producer's own `retail_price_1m_ago` / `ppi_1m_ago` LAG logic outside the model and reapplying the identical CASE predicates; verified exact — 0 mismatches against the live `margin_pressure_risk` output across all 400 rows before this rename's rebuild). Not fixed — flagged for a future pass once more months of Kroger data reduce the single-month-lag skew (329 of 400 rows currently have no prior month at all and fall trivially into branch 55).

### Commit 5 — string literal rename (`score_version`)

Reason: the scoring logic is a calibrated heuristic cascade (rule-based CASE branches with analyst-set thresholds and weights), not a fitted statistical model. `'v4_statistical_calibration'` overstated what the engine does. The `v4_` prefix is kept — this pass changed terminology only, not the scoring logic, formulas, weights, thresholds, or cascade conditions in any of the 7 marts.

| Old value | New value | Files |
|---|---|---|
| `'v4_statistical_calibration'` | `'v4_robust_heuristic_calibration'` | `mart_pricing_intelligence.sql` (score_version alias + config description + header comment), `mart_action_queue.sql`, `mart_confidence_layer.sql`, `mart_demand_gap_scores.sql`, `mart_expansion_readiness.sql`, `mart_price_margin_scores.sql`, `mart_shelfrisk_scores.sql`, `models/schema.yml`, `dashboard/app.py` (fallback string, 2 sites) |

**Left unchanged, deliberately:** `docs/session_notes_v4_pricing.md:16` — a dated historical record of the v4 rollout, not a live reference doc.

---

## 6. Open item — CASE branch count vs accepted_values list

Verified at time of writing (2026-07-23):

**`directional_signal_confidence`** (`mart_pricing_intelligence.sql`, actioned CTE):
CASE branches: `'Insufficient'`, `'Unreliable'`, `'Persistent'`, `'Provisional'` = **4 branches**.
`accepted_values` list in `schema.yml`: `['Insufficient', 'Unreliable', 'Persistent', 'Provisional']` = **4 values**.
Result: counts match. ✓

**`event_type`** (`mart_weekly_events.sql`):
Literal strings assigned per CTE: `'Gap Flip'` (gap_flip CTE), `'Big Move'` (big_move CTE), `'3-Collection Streak'` (new_sustained CTE) = **3 values**.
`accepted_values` list in `schema.yml`: `['Gap Flip', 'Big Move', '3-Collection Streak']` = **3 values**.
Result: counts match. ✓

---

## 7. FRED PPI — single-series contract and series identity finding

Covers commit `44afed8` (FRED single-series contract at the staging layer), which shipped without a doc entry.

### 7.1 The single-series staging contract

`fred_ppi_raw` can carry more than one FRED series — the collector can pull an additional series without switching scoring to it. `stg_fred_ppi.sql` filters to exactly one series, named by the var `scoring_ppi_series_id`, before any downstream model sees the data:

```sql
where observation_date >= '2025-01-01'
  and series_id = '{{ var("scoring_ppi_series_id") }}'
```

This is the single point of truth for "which FRED series does scoring use." The alternative — a `series_id` filter repeated in every consumer model — was rejected because it means the same assumption is encoded in five places instead of one; a future model added without remembering the filter would silently reintroduce cross-series contamination. Switching which series scoring uses becomes a one-line var change with no model edits, because every downstream model already assumes (and, with this filter, is guaranteed) a single-series input.

### 7.2 Consumer sites that carry no local filter, and what a second series would have done to each

None of the following files reference `series_id` — they rely entirely on the staging contract:

| File | Mechanism | Failure mode with a second, unfiltered series |
|---|---|---|
| `fact_market_signals.sql` (`fred`, `fred_as_of` CTEs) | Two-step as-of join, no `series_id` predicate | **Fan-out.** The final join (`f.reference_month = fa.fred_month`) would match one row per series for the same month, doubling every row in the `final` CTE and every mart built on it. |
| `mart_price_margin_scores.sql` (`ppi_as_of` CTE) | Same as-of join pattern | **Fan-out**, identical mechanism to `fact_market_signals`. |
| `mart_shelfrisk_scores.sql` (`ppi_lag_monthly` CTE) | `LAG(ppi_value, 1) OVER (ORDER BY month)`, no `PARTITION BY` | **Cross-series LAG.** With two series interleaved in month order, `LAG` would compare one series' value against the other's — a silently wrong month-over-month delta, not a fan-out. |
| `int_macro_trend_features.sql` (`ppi_windowed` CTE) | `LAG(ppi_value, 12)` plus two rolling `AVG(...) OVER (ORDER BY month ROWS BETWEEN ...)` windows, no `PARTITION BY` | **Cross-series LAG/window**, same mechanism as `mart_shelfrisk_scores.sql`, higher blast radius: feeds `ppi_trend_direction`, `normalized_ppi_growth_score`, and `ppi_3mo_trend` into `fact_market_signals`, propagating to every downstream mart. |

`mart_confidence_layer.sql`'s FRED freshness line (`MAX(collected_at)`, `COUNT(*)` from `stg_fred_ppi`) and `dashboard/queries.py`'s direct `fred_ppi_raw` read were left untouched — both answer "did the collector run," not a scoring question, and the confidence-layer one inherits the staging fix for free since it already reads through `stg_fred_ppi`.

### 7.3 Guard tests

- **`tests/assert_ppi_series_resolves.sql`** — fails if `stg_fred_ppi` returns zero rows, i.e. `scoring_ppi_series_id` matches nothing in `fred_ppi_raw` (typo, wrong ID, discontinued series, or a collector regression). Proven: pointing the var at a nonexistent series ID produced FAIL 1; restoring the real ID produced PASS.
- **`tests/assert_ppi_series_coverage.sql`** — fails if `stg_fred_ppi` has fewer than `min_ppi_monthly_rows` (= **13**) monthly rows. Proven: overriding the threshold to 20 against the live 16-row table produced FAIL 1; the real threshold of 13 produced PASS.
- **N = 13, reasoning:** `int_macro_trend_features.sql`'s `ppi_yoy_value = LAG(ppi_value, 12)` needs 13 rows of history (12 preceding plus the current row) for even the most recent month to produce a non-null year-over-year comparison. Below 13, that entire feature is unconditionally NULL for every row — the most demanding requirement of any current consumer (LAG 1/3/6 in `mart_price_margin_scores.sql` need far fewer rows).
- **Current headroom:** 16 rows live against a floor of 13 — 3 months of slack. This widens by one every month the collector's 24-month rolling pull advances without the series being discontinued or the pull window shrinking; it does not widen on its own without continued collection.
- **Rejected guard: `count(distinct series_id) > 1`.** This was the first design considered and discarded — once the staging `WHERE series_id = ...` clause exists, `stg_fred_ppi` can never expose more than one series by construction, so this test would assert exactly what the filter already guarantees and could never fail. It tests the mechanism's own tautology, not a real failure mode.
- **`tests/assert_fred_ppi_raw_no_duplicate_months.sql`** — fails if `fred_ppi_raw` (the source, not `stg_fred_ppi`) has more than one row for the same `(series_id, observation_date)`. Same "test the thing that can actually change" reasoning as the rejected guard above: `stg_fred_ppi` now dedupes via `QUALIFY ROW_NUMBER() OVER (PARTITION BY series_id, observation_date ORDER BY collected_at DESC) = 1`, so testing the model itself would be circular — the `QUALIFY` guarantees it can never fail there. Testing the raw source instead catches a real regression (e.g. `_upload` switching from `WRITE_TRUNCATE` to `WRITE_APPEND`, or gaining a partition decorator) at the point where it would first appear. Proven: temporarily changing the test's own comparison to `having count(*) >= 1` (matching every existing row, since duplicates don't currently exist in live data) produced FAIL 24; reverting to `> 1` produced PASS.
- **Why dedup was added even though today's collector can't produce duplicates:** `_upload` (`collect_apis.py`) uses `WRITE_TRUNCATE` against an undecorated destination, replacing the whole `fred_ppi_raw` table on every call rather than appending — confirmed live: 24 rows, 24 distinct `(series_id, observation_date)` pairs, one `collected_at` batch. So the specific risk of weekly re-collection silently duplicating rows does not occur under the current write pattern. The `QUALIFY` and this test exist as defense-in-depth against that write pattern changing in the future without `stg_fred_ppi` being revisited.

### 7.4 The series finding

`PCU42440042440012` — the series currently in use — is **"PPI by Industry: Grocery and Related Product Merchant Wholesalers: Wholesaling of Packaged Frozen and Canned Foods."** This is a **wholesale trade index measuring distributor gross margins on one packaged-food product line**, not an input-cost index. It is currently applied as a cost proxy across all 10 TrendShelf categories, and feeds `overall_margin_risk_score` at a 0.40 weight via `margin_pressure_proxy_score`.

The intended replacement is `PCU311311` (Food Manufacturing) — a producer-side cost index, not a wholesale-margin index. That switch is **not made in this commit or in commit `44afed8`**: `PCU311311` collection is added to the raw pipeline separately, and `scoring_ppi_series_id` stays pointed at `PCU42440042440012` until a deliberate later switch. The fix for the series-identity problem itself remains pending.

**Update:** the switch is made in §7.7 below.

### 7.5 Standing rule

Check any FRED series' own page (title, breadcrumb category, units) before using it as an input to a model. FRED's breadcrumb path **"Industry Based > Wholesale Trade"** means the series measures trade margins, not the prices or costs a wholesale-trade series' name might suggest at a glance. This applies to every FRED series considered for TrendShelf going forward, not only PPI.

### 7.6 FRED now refreshes weekly

`collect_apis.py`'s FRED PPI block was moved out of the `if mode == "full":` gate to run in both modes, matching Kroger/SerpAPI — it now runs on the weekly `--mode prices` cron, not only during rare full-mode runs. `FRED_API_KEY` was added to `.github/workflows/weekly-collection.yml`'s collect-job `env:` block so the CI run can actually authenticate. Google Trends and BLS CPI remain full-mode-only, unchanged.

Before this, FRED had been collected exactly once (a manual full-mode pull) and never refreshed by CI, so `stg_fred_ppi` sat stuck at April 2026 while FRED itself had already published June. The **"2-month reporting lag"** documented in `fact_market_signals.sql`'s header and handled by the `fred_as_of` latest-available-as-of join is a real, permanent property of FRED's publishing schedule — it does not go away. What does go away with this change is the *second*, unrelated lag that had been stacking on top of it: TrendShelf simply never asking FRED for new data. Going forward, `stg_fred_ppi` should track FRED's own publishing lag only, not a multi-month collection gap on top of it.

### 7.7 The PPI series swap: `PCU42440042440012` → `PCU311311`

`scoring_ppi_series_id` changed from `PCU42440042440012` (Grocery and Related Product Merchant Wholesalers — a wholesale-trade margin index, per §7.4) to `PCU311311` (Producer Price Index by Industry: Food Manufacturing — a genuine producer-side input-cost index). One line in `dbt_project.yml`; no collector change, since both series were already being collected (§7.6 / the `FRED_SUPPLEMENTARY_PPI_SERIES` work). This is a deliberate scoring change — every number downstream of `margin_pressure_proxy_score` moved.

**Pre-swap verification:** `PCU311311` resolves to 18 rows after the staging filter (`observation_date >= '2025-01-01'`, deduped), against a floor of `min_ppi_monthly_rows` = 13. `dbt run` (24/24 models) and `dbt test` (143 pass, 1 pre-existing unrelated warn on `stg_kroger_prices.price_regular`, 0 errors) both passed after the swap, including `assert_ppi_series_resolves` and `assert_ppi_series_coverage`.

**Score movement** (all 400 rows, both marts):

| Metric | Before | After | Delta |
|---|---|---|---|
| `margin_pressure_proxy_score` min/max/avg | 29.52 / 55.0 / 50.56 | 40.0 / 80.0 / 72.90 | +10.48 / +25.00 / +22.34 |
| `cost_shock_score` (constant across all rows) | 14.02 | 9.15 | -4.87 |
| `overall_margin_risk_score` min/max/avg | 26.88 / 52.51 / 43.12 | 29.85 / 61.29 / 50.84 | +2.97 / +8.78 / +7.72 |
| `store_market_fit_score` min/max/avg | 31.58 / 67.38 / 44.28 | 26.58 / 65.28 / 39.81 | -5.00 / -2.10 / -4.47 |
| `overall_confidence_score` min/max/avg | 83.2 / 91.95 / 87.31 | 86.95 / 91.95 / 87.70 | +3.75 / +0.00 / +0.39 |

`cost_passthrough_rate` stayed at 0.0 for all rows before and after — unaffected, still gated by the pre-existing `retail_price_3m_ago` history gap (§ prior sessions, unrelated to this change).

**Branch distribution flip.** Before: `BRANCH_55_COMPRESSION` 329, `BRANCH_HEALTHY` 71 (0 in `BRANCH_80_SQUEEZE`/`BRANCH_40_COST_RISING`). After: `BRANCH_80_SQUEEZE` 329, `BRANCH_40_COST_RISING` 71 (0 in `BRANCH_55_COMPRESSION`/`BRANCH_HEALTHY`). Every row that used to land in the "retail price flat/falling" branch without a cost-rising kicker now gets the kicker, and likewise for the "retail price rising" branch.

The reason is structural, not series-specific: `mart_demand_gap_scores` currently has only **two** distinct `reference_month` values (2026-06-01, 2026-07-01), and both resolve through `ppi_as_of` to the **same** latest available PPI month (2026-06-01, since 2026-07's own PPI hasn't published yet and falls within the staleness window). That means `ppi_value > ppi_1m_ago` is a single shared boolean applied identically to all 400 rows, not something that varies row-by-row — it was `NOT_RISING` for every row against the old series' resolved month, and it is `RISING` (274.942 vs. 273.557, May→June 2026) for every row against the new series' resolved month. `BRANCH_55_COMPRESSION`/`BRANCH_HEALTHY` are still reachable in principle — they just require a spine month whose resolved PPI reading isn't a month-over-month increase, which neither of the two current spine months has. This will diversify as more distinct `reference_month` values accumulate.

**Read the 329 correctly:** with only two reference months present, the "is PPI rising" test is **one shared boolean across all 400 rows**, not 400 independent measurements. The 329 rows landing in `BRANCH_80_SQUEEZE` reflect a single national PPI reading (May→June 2026, +0.5%) combined with each row's own retail-price direction — they are not 329 independent squeeze findings, and the count "329" says more about how many store×category pairs had flat/falling retail price this month than about 329 distinct cost-shock events. This resolves on its own as more months accumulate: once `reference_month` spans enough distinct PPI-resolved months to include both rising and non-rising readings, and per-row retail-price history diverges further, the branch mix will stop being dominated by a single shared macro signal.

**`PCU311311`'s own recent monthly % changes** (Dec 2025 → Jun 2026): -0.03%, +0.23%, +0.71%, +0.80%, +0.51%, +0.51%. All under 1%, consistent with a genuine, low-volatility cost index — a sharp contrast with the old series' documented behavior (§ prior session: avg 2.5%, max 7.7% monthly moves), which was the original tell that `PCU42440042440012` wasn't behaving like a normal PPI.

**Invariant check:** "Review Price Reduction" rows under Low reliability = **0**, both before and after. Holds.

**Fixed in the same commit:** `config.py`'s `FRED_SCORING_PPI_SERIES_ID`/`FRED_SUPPLEMENTARY_PPI_SERIES` were swapped to match — `FRED_SCORING_PPI_SERIES_ID` now names `PCU311311` (abort-on-failure), `FRED_SUPPLEMENTARY_PPI_SERIES` now lists `PCU42440042440012` (warn-and-skip-on-failure). `collect_apis.py` reads both constants by name and needed no code change; the essential-series-first fetch order is unchanged, so the collector still fetches both series. Also fixed: `models/schema.yml`'s `stg_fred_ppi` description (line 54), which still read "energy drink wholesalers (FRED PCU42440042440012)" — a stale description missed by the original four-site cleanup, now corrected to Food Manufacturing (PCU311311), same as the other four sites.

### 7.8 PPI deadband: `ppi_deadband_pct = 0.1`

`margin_pressure_proxy_score`'s branch-80 and branch-40 tests used a strict `ppi_value > ppi_1m_ago` — any month-over-month PPI move above zero, including something as small as +0.02%, counted as "rising" and could flip the branch assignment for the whole panel. Since §7.7 established that the panel currently shares one national PPI reading across all 400 rows, a noise-level tick in that one shared reading was enough to swing the entire dataset between branches for no economically meaningful reason.

**Evidence.** `stg_fred_ppi` (PCU311311) has 17 month-over-month deltas. Sorted by absolute % change: `0.0248, 0.0333, 0.2002, 0.2322, 0.2579, 0.4313, 0.5063, 0.5115, 0.5765, 0.6112, 0.6136, 0.6448, 0.7109, 0.7237, 0.8011, 1.0808, 1.6897`. n=17, MIN=0.0248%, MAX=1.6897%, AVG=0.5676%, P25=0.2579%, P50=0.5765%, P75=0.7109%, P90=0.9130%.

**The natural gap.** The two smallest values (0.0248%, 0.0333%) sit far below the third-smallest (0.2002%) — a 6x jump, with no comparable gap anywhere else in the distribution. That gap is the evidence for where "noise" ends and "real move" begins, specific to this series' own behavior, not borrowed from the old margin series or an arbitrary percentile. `ppi_deadband_pct = 0.1` sits centered in that gap (roughly 3x the noise ceiling, half the smallest real move) — any value in (0.0333, 0.2002] classifies the historical sample identically, so 0.1 is not a fragile pick within that range.

**What it flattens:** 2 of 17 observed months (11.8%) — the two below the gap. The other 15 (88.2%) remain classified as directional moves. This deliberately does **not** suppress the majority of real moves; it only removes the two months that were already indistinguishable from measurement noise.

**Implementation.** `models/marts/mart_price_margin_scores.sql`'s `base` CTE gained one new column, `ppi_mom_pct_change` — `SAFE_DIVIDE(ppi_value - COALESCE(ppi_1m_ago, ppi_value), NULLIF(COALESCE(ppi_1m_ago, ppi_value), 0)) * 100` — computed once, same null-handling as the old inline comparison (a NULL `ppi_1m_ago` collapses to 0% change, not NULL). Both previously-duplicated `ppi_value > COALESCE(ppi_1m_ago, ppi_value)` predicates in `scored`'s branch-80 and branch-40 tests were replaced with `ppi_mom_pct_change > {{ var('ppi_deadband_pct') }}`, reading the same column — one definition, two reads, no remaining copy of the old inline expression.

**One-sided by structure, not by choice.** The branch logic only ever tested "is PPI rising" — there is no separate branch for "PPI falling significantly" versus "PPI flat"; both already fell through to branch 55/healthy before this deadband existed. The deadband doesn't introduce that asymmetry, it just raises the bar for what counts as "rising" from `> 0` to `> 0.1%`. A distinct "costs are falling, margins improving" signal would require a new branch in the CASE, not a change to this deadband — explicitly out of scope here.

**Does not make the signal row-specific.** The deadband smooths noise out of the *shared* national reading — it does not change the finding in §7.7 that the panel still moves together on one series-wide PPI value per resolved month. With only two `reference_month` values live today, all 400 rows still inherit the same `ppi_mom_pct_change` (May→June 2026, +0.5063%), which is comfortably above the 0.1% deadband — so at this snapshot the branch-80/40 assignment is unchanged from before the deadband, and correctly so: a genuine +0.51% move should still register as "rising." The deadband's effect is invisible until a future month's shared PPI move happens to fall inside the (0, 0.1%] noise band; §7.7's structural point (that the panel needs more distinct `reference_month` values before the signal becomes row-specific rather than one shared macro reading) is unaffected either way.

**Verification.** Baseline before the edit (post-§7.7 swap, still live at commit `48dd01e`) and after `dbt run`/`dbt test` are identical except for a floating-point last-digit artifact in `store_market_fit_score`'s AVG (39.80660000000001 → 39.80660000000002, 14 decimal places deep — BigQuery float summation order, not a value change). Branch distribution: `BRANCH_80_SQUEEZE` 329 / `BRANCH_40_COST_RISING` 71, unchanged. Invariant (Review Price Reduction × Low reliability) = 0, unchanged. `dbt run`: 24/24. `dbt test`: 143 pass, 0 errors, same pre-existing unrelated warning; `assert_ppi_series_resolves`, `assert_ppi_series_coverage`, `assert_fred_ppi_raw_no_duplicate_months` all PASS.

### 7.9 Unknown-trend rows must not score as declining: `has_prior_month_price` / `has_prior_month_ppi`

`margin_pressure_proxy_score`'s branch predicates used `retail_price <= COALESCE(retail_price_1m_ago, retail_price)` — when `retail_price_1m_ago` is NULL, this compares `retail_price` to itself, which is always TRUE. The same masking existed on the PPI side via `COALESCE(ppi_1m_ago, ppi_value)`. Both silently treated "we have no prior-period reading" as "the price/cost didn't rise" — the same defect class as the pre-deadband PPI masking (§7.8), one level up.

**How big this was.** 200 of 400 rows (50%, the entire `2026-06-01` cohort — the earlier of the two live `reference_month`s, where no prior month exists in the window) had `retail_price_1m_ago IS NULL`. Every one of them was scoring **exactly 80 — maximum "classic margin squeeze"** — purely from the self-comparison, with zero evidence of actual retail price movement. That's half the table's margin-risk signal being manufactured from a data-availability artifact, not a measurement.

**The fix.** Two new boolean columns, computed once in `base`, same pattern as `ppi_signal_stale`:
- `has_prior_month_price` — `retail_price_1m_ago IS NOT NULL`
- `has_prior_month_ppi` — `ppi_1m_ago IS NOT NULL`

Both declared in `schema.yml` with `not_null` tests. A new CASE branch, `WHEN NOT has_prior_month_price OR NOT has_prior_month_ppi THEN 50`, sits immediately after the existing data-outage branch (`retail_price IS NULL OR ppi_value IS NULL THEN 30`) and before the four evidenced branches. `retail_price_declining` (`retail_price <= retail_price_1m_ago`, no COALESCE) is computed once in `base` and referenced by both the branch-80 and branch-55 tests — same one-definition discipline as `ppi_mom_pct_change`. The healthy-branch delta formula also dropped its `COALESCE(retail_price_1m_ago, retail_price, 0)` self-mask, since by that point in the CASE a real comparison is guaranteed.

**Why 50, not 55.** "Trend unresolved" needs a value with no directional signal, distinguishable from every evidenced branch (0-30 healthy, 40 mild pressure, 55 compression, 80 squeeze). 50 is the exact midpoint of the 0-100 scale and sits in the one gap no evidenced branch occupies — it cannot read as "leaning healthy" or "leaning risky." 55 was rejected because it asserts an observed compression that didn't happen — reusing it would just relocate the same masking bug from the predicate into the neutral value's choice. The value is hardcoded, matching the existing hardcoded siblings (80/55/40/30) rather than introduced as a new var — thresholds are vars in this codebase, branch scores are not.

**PPI side: added correctness-ahead-of-need, dormant today.** `has_prior_month_ppi` and its half of the unknown-branch condition are live in the deployed CASE, but **0 of 400 rows currently trigger it** (`ppi_1m_ago IS NULL` count = 0, confirmed both before and after this change) — both live `reference_month`s resolve to a PPI month that isn't the first in `stg_fred_ppi`'s own history. Its effect today is provably zero; it closes the same defect on the PPI side before it can ever fire, same reasoning as adding the PPI deadband ahead of a month where it would matter (§7.8).

**Invariant proof is structural, not empirical.** `recommended_price_action = 'Review Price Reduction'` has exactly two producing branches in `mart_pricing_intelligence.sql` (lines 697-712), and both require `price_gap_reliability = 'High'` explicitly — a competitor-data-quality gate computed independently of `margin_pressure_proxy_score`. "Review Price Reduction" under `Low` reliability is therefore impossible by construction, regardless of what this change (or any future change to `margin_pressure_proxy_score`) does. Confirmed empirically too: invariant = 0, before and after.

**Verification.** Baseline taken against the live table before editing (200/400 rows at score 80.0 from the artifact, branch distribution 40.0×71 / 80.0×329). `dbt run`: 24/24. `dbt test`: 145 pass, 0 errors, same pre-existing unrelated warning (144 + 2 new `not_null` tests). All three FRED guards and both new `has_prior_month_*` tests PASS.

| Metric | Before | After |
|---|---|---|
| `margin_pressure_proxy_score` branch distribution | 40.0×71, 80.0×329 | 40.0×71, **50.0×200**, 80.0×129 |
| `margin_pressure_proxy_score` avg | 72.90 | **57.90** |
| `overall_margin_risk_score` min/max/avg | 29.85 / 61.29 / 50.84 | 29.85 / 56.61 / **44.84** |
| `store_market_fit_score` min/max/avg | 26.58 / 65.28 / 39.81 | 31.99 / 65.28 / 42.81 |
| `expansion_readiness_score` min/max/avg | 48.04 / 64.76 / 55.30 | 49.32 / 65.25 / 56.20 |
| expansion `FIX MARGINS` count | 163 | **83** |
| expansion `BUILD CASE` / `MONITOR AND PREPARE` / `PREPARE PITCH` | 29 / 82 / 126 | 75 / 96 / 146 |
| `mart_action_queue` DEFEND / MONITOR | 240 / 560 | 240 / 560 (unchanged) |
| `recommended_price_action × reliability` | incl. Avoid Discount×High 19, Review Price Reduction×High 1 | Avoid Discount×High **0**, Review Price Reduction **0** (all levels); Monitor×High 165→184 |
| Invariant (Review Price Reduction × Low) | 0 | 0 |

`margin_pressure_proxy_score`'s average dropped 15.0 points and `overall_margin_risk_score`'s dropped 6.0 points — both fall almost exactly out of the 200 artifact rows moving from 80 to 50 (200 × 30-point drop × 0.40 weight ÷ 400 rows = 6.0), confirming the shift traces entirely to removing the artifact, not to any change in genuinely-evidenced rows (the 129 real squeeze rows and 71 real cost-rising rows kept their exact scores). The expansion-readiness and pricing-intelligence movements are downstream of that same correction.

### 7.10 Expansion cascade: a genuine margin squeeze must not be silently dropped by a pitch recommendation

**The defect (pre-existing, not introduced by any prior commit in this log).** `mart_expansion_readiness.sql`'s action cascade evaluates `PITCH NOW` / `PREPARE PITCH` / `MONITOR AND PREPARE` (gates 1-3, keyed on `expansion_readiness_score` and `risk_level`) *before* the `FIX MARGINS` gate (`margin_pressure_proxy_score >= 70`, gate 7). Any row whose readiness/risk profile satisfied gates 1-3 got a pitch recommendation with no mention of margin, regardless of how severe `margin_pressure_proxy_score` was.

**How big this was — measured at a clean rebuild of `42360a4`.** Both this fix and the confidence-freshness fix (§7.11) were stashed out of the working tree, `dbt run --full-refresh` rebuilt every table from that exact commit, and the baseline was confirmed genuine before trusting it: `overall_confidence_score` avg = 87.70 (not the freshness-fix's ~90) and the freshness sub-score column was still named `data_freshness_score` (not yet renamed) — proving no other pending change was contaminating the measurement. (An earlier attempt at this same measurement was taken without re-running `dbt run` after stashing, so it read a stale, freshness-tainted table; that mistake was caught and this section reflects the corrected, actually-rebuilt numbers.)

```
Of 129 rows with margin_pressure_proxy_score >= 70 (all genuine squeezes, post-§7.9):
  FIX MARGINS           83   (gate fires correctly)
  PREPARE PITCH         34   (squeeze silently dropped — gate 2)
  MONITOR AND PREPARE   12   (squeeze silently dropped — gate 3)
  PITCH NOW               0
```
**46 of 129 rows (35.7%)** — over a third of every genuine maximal margin squeeze in the table — were recommended for expansion (`PREPARE PITCH` or `MONITOR AND PREPARE`) with the margin problem never surfaced.

**Fix: Option (ii) — margin guard on gates 1-3, not a reorder.** Reordering (moving `FIX MARGINS` earlier) would have forced an unscoped decision about its priority relative to `DEFEND FIRST` / `REMEDIATE RISK` / `COLLECT MORE DATA`, none of which were part of this defect. Instead, `margin_pressure_proxy_score < {{ var('expansion_margin_fix_threshold') }}` was added as an additional `AND` condition to gates 1, 2, and 3; a row that fails the guard falls through the cascade exactly as it would have if gates 1-3 didn't exist, reaching whichever gate is next in the existing, unchanged order.

**New var:** `expansion_margin_fix_threshold: 70` (`dbt_project.yml`) — there was no existing var to reuse; `margin_pressure_proxy_score >= 70` at the `FIX MARGINS` gate was a hardcoded literal. The new var now feeds **both** the three guards and the `FIX MARGINS` gate itself (which had its own hardcoded `70` replaced), so the two can never drift apart — single point of truth, same discipline as `ppi_deadband_pct`.

**This is a deliberate business-logic decision, not a cosmetic rename:** a real margin squeeze at or above this threshold now unconditionally blocks an expansion recommendation. A store/category the model itself scores as having maximal margin pressure will never again be told to prepare a buyer pitch without that pressure being surfaced first.

**Verification — genuinely measured, not reconciled on paper.** With the true pre-fix baseline confirmed (above), this fix alone was unstashed and rebuilt (`dbt run --full-refresh`, freshness still stashed):

| | Before (true `42360a4`) | After (this fix alone) |
|---|---|---|
| `FIX MARGINS` | 83 | **129** |
| `PREPARE PITCH` | 146 | **112** |
| `MONITOR AND PREPARE` | 96 | **84** |
| `BUILD CASE` | 75 | 75 (unchanged) |
| margin≥70 → `FIX MARGINS` | 83/129 (64%) | **129/129 (100%)** |

All 129 rows with `margin_pressure_proxy_score >= 70` land on `FIX MARGINS` after the fix — zero diverted to `DEFEND FIRST`/`REMEDIATE RISK`/`COLLECT MORE DATA`, confirming the guard produces exactly the intended fall-through with no unexpected interaction. `recommended_price_action × price_gap_reliability` and `mart_action_queue`'s `action_type` counts are unchanged (this is an expansion-cascade-only fix). Invariant (Review Price Reduction × Low reliability) = 0. `dbt run --full-refresh`: 24/24. `dbt test`: 145/146 pass, 0 errors, same pre-existing unrelated warning; all 5 guard tests PASS.

**How this was found:** surfaced while tracing the confidence-freshness change (§7.11) — that change alone moved 5 boundary rows from `FIX MARGINS` into `PREPARE PITCH`, which led to measuring the full pre-existing defect rather than just the 5-row slice. §7.11 is committed on top of this fix, not bundled with it, so each is independently verifiable.

### 7.11 Confidence freshness: drop the frozen Google Trends source, rename `data_freshness_score` → `collection_recency_score`

**(a) Google Trends removed from the freshness calc.** `COLLECT_GOOGLE_TRENDS` is off by design — Trends is a deliberate one-time historical baseline (`config.py`), not a source that ever refreshes. Scoring it as "stale" permanently docked `data_freshness_score` for a design choice, and made `overall_confidence_score` erode on every `dbt run` from wall-clock passage alone, independent of any real data quality change. Trends' 0.20 weight was removed from the freshness formula and redistributed across the four actively-refreshed sources, scaling their existing ratios (0.25 : 0.20 : 0.20 : 0.15) by 1/0.80 to refill the vacated weight: **Kroger 0.3125, FRED 0.25, BLS 0.25, SerpAPI 0.1875** (sum 1.00). Trends still counts fully toward `data_completeness_score` and `row_level_source_coverage_score` — both read `avg_search_interest`, not collection timestamp, so removing Trends from the recency calc doesn't touch either.

**(b) Renamed `data_freshness_score` → `collection_recency_score`**, everywhere it appeared: the producer (`mart_confidence_layer.sql`, formula + comments), the composite formula, the passthrough in `mart_expansion_readiness.sql`, `models/schema.yml`'s description prose, and `docs/scoring_methodology.md`'s formula and component table. The old name implied it measures how current the data's *content* is; it actually measures how recently each source was *collected* (`MAX(collected_at)`, not `observation_date`) — a real distinction, since a genuine content refresh (e.g. FRED's April→June move, §7.6) doesn't move this score at all unless the *collection event itself* was also recent. Left untouched: the two dated notebooks (`trendshelf_eda.ipynb`, `trendshelf_eda_executed.ipynb`, per the standing rule that dated records keep their original wording) and `dashboard/queries.py`'s unrelated `get_data_freshness()` — a different function entirely, reading raw `collected_at` per source table directly, never referencing the mart column being renamed here.

**(c) Logged as a future item, not fixed here:** true data-*currency* scoring would read `observation_date`-class columns (or `ppi_signal_stale`-style as-of gaps) instead of `collected_at`, so a genuinely fresh calendar month scores as fresh regardless of when it happened to be collected. That's a larger, cross-cutting change (FRED/BLS both have real, permanent publishing lags — §7.6 — so "content currency" would need its own staleness bands, not a copy of the collection-recency ones) and is deliberately deferred, not attempted in this commit.

**Verification — genuinely measured, not reconciled on paper.** Both this fix and §7.10 were stashed, `dbt run --full-refresh` established the true `42360a4` baseline (`overall_confidence_score` avg confirmed 87.70), §7.10 alone was unstashed/rebuilt/committed first, then this fix was unstashed on top of `d50252a` and rebuilt with another full refresh:

| | Before (`d50252a`, §7.10 applied, freshness not yet) | After (this fix applied) |
|---|---|---|
| `collection_recency_score` (constant) | 78.5 | **90.63** |
| `overall_confidence_score` min/max/avg | 86.95 / 91.95 / 87.70 | 89.38 / 94.38 / **90.13** |
| `FIX MARGINS` | 129 | **129 (unchanged)** |
| `PREPARE PITCH` | 112 | 112 (unchanged) |
| `MONITOR AND PREPARE` | 84 | 89 |
| `BUILD CASE` | 75 | 70 |
| margin≥70 → `FIX MARGINS` | 129/129 (100%) | **129/129 (100%)** |

**The whole point of landing §7.10 first:** the confidence rise (+2.43 avg, uniform across all rows) pushes `expansion_readiness_score` up by ~0.36 uniformly (via its `overall_confidence_score × 0.15` term) — enough to move the same 5 boundary rows identified in the original trace (`margin_pressure_proxy_score = 80`, `risk_level = LOW`, `old_readiness` 54.66–54.94) across the `>= 55` gate. Queried directly: **all of them resolve to `FIX MARGINS`, none to `PREPARE PITCH`** — §7.10's guard holds regardless of the confidence rise, exactly as designed. `FIX MARGINS`'s count is unchanged at 129 (100% of genuine squeezes, unaffected by freshness). The remaining movement — `BUILD CASE` 75→70, `MONITOR AND PREPARE` 84→89 — is the separate, benign `risk_level = MEDIUM` boundary crossing already characterized in the original trace (all `margin_pressure_proxy_score < 70` by cascade construction, so none of these touch the margin guard).

`recommended_price_action × price_gap_reliability` and `action_type` unchanged. Invariant (Review Price Reduction × Low reliability) = 0. `dbt run --full-refresh`: 24/24. `dbt test`: 145/146 pass, 0 errors, same pre-existing unrelated warning; all 5 guard tests PASS. Grep confirms zero stray `data_freshness_score` outside the two dated notebooks.

### 7.12 `mart_shelfrisk_scores` self-mask + exact-match join — same defect class as §7.9, one model behind

`mart_shelfrisk_scores.sql`'s `competitive_threat_risk` PROXY leg had its own `ppi_value > COALESCE(prev_ppi, ppi_value)` — the same self-mask defect fixed for `mart_price_margin_scores.sql` in §7.9 — plus a second, larger defect §7.9's model didn't have: `ppi_lag_monthly` joined on an **exact** `reference_month` match (`d.reference_month = pl.reference_month`), not the latest-available-as-of pattern used everywhere else FRED data is consumed. Any spine month FRED hasn't published yet (structurally, always the most recent month) got `prev_ppi = NULL` from a failed join, not from a resolved prior reading.

**Measured dormant before touching anything — and this rules out the model as the 89.2→87.3 culprit.** Live, before any edit: `signal_type` was `MEASURED` for all 400 rows (`competitor_avg_price` present everywhere this snapshot) — meaning the `CASE`'s first branch always wins and the `PROXY` branch containing both defects **never executed**, 0 of 400 rows. Since this is the only place `ppi_value` feeds `mart_shelfrisk_scores`' formulas (`ppi_value` is otherwise just a passthrough column), this defect could not have caused the historical confidence drop investigated in §7.11 — it had zero live effect at the time of measurement. (This doesn't rule out that SerpAPI coverage might have been thinner at some earlier point in the pipeline's history — there's no way to check that retroactively — but it rules out the defect as an *ongoing* explanation, and the fix is prospective regardless of what happened before.)

**Fix — same shape as §7.9, applied here for the first time:**
- Replaced the exact-match `ppi_lag_monthly` join with a ported `ppi_as_of` + `ppi_lags_stg` pair, structurally identical to `mart_price_margin_scores.sql`'s (§7.9/STEP A), using `max_ppi_staleness_months` as the same staleness guard.
- Added `has_prior_month_ppi` (`prev_ppi IS NOT NULL`, computed once), `not_null`-tested in `schema.yml`, same pattern as `mart_price_margin_scores`'s.
- Computed `ppi_mom_pct_change` once (same name/formula as `mart_price_margin_scores.sql`), replacing both duplicated `ppi_value > COALESCE(prev_ppi, ppi_value)` predicates with `ppi_mom_pct_change > {{ var('ppi_deadband_pct') }}` — **reusing** `ppi_deadband_pct` rather than adding a new var, since this is the same series and the same noise-vs-signal question already answered in §7.8; a second, independently-tunable threshold for the identical question would only create a place for the two to drift apart.
- **Neutral value: 25, not §7.9's 50.** This model already had its own unknown sentinel — `WHEN retail_price IS NULL OR prev_retail_price IS NULL THEN 25` — sitting in the gap between this model's healthy floor (15) and its cost-rising-only branch (35). That's this model's own calibrated "we don't know" position on its own 15/35/50/80 scale, distinct from `mart_price_margin_scores`'s 0-30/40/55/80 scale that §7.9's 50 was calibrated for. Rather than importing a value tuned for a different formula, the PPI-unknown case was folded into the *same* existing branch: `WHEN retail_price IS NULL OR prev_retail_price IS NULL OR NOT has_prior_month_ppi THEN 25` — one neutral value covering "we can't render a two-axis verdict" regardless of which axis (retail history or PPI history) is the one missing.

**Known duplication, logged not refactored.** This is now the **third** copy of the FRED latest-available-as-of resolution pattern in the codebase:
1. `fact_market_signals.sql` (`fred_as_of` CTE) — the original
2. `mart_price_margin_scores.sql` (`ppi_as_of` CTE, added in STEP A / §7.7-era work)
3. `mart_shelfrisk_scores.sql` (`ppi_as_of` CTE, this section)

Per-model CTE duplication matches this codebase's existing style, and refactoring mid-fix was out of scope here — but three independent copies of a non-trivial pattern is a real "change one, miss the other two" surface. A shared macro (e.g. a `fred_as_of` macro parameterized on the spine CTE and staleness var) is the eventual right answer; any future change to the as-of resolution logic should check all three sites above until that consolidation happens.

**Verification — the proof pair.** `has_prior_month_ppi` for the `2026-07-01` cohort: **200 NULL → 0 NULL** (all 200 rows now resolve `prev_ppi` via the as-of join, to May's reading through June's resolved `ppi_month`) — proving the wiring is genuinely fixed. Every live-deployed score (`competitive_threat_risk` distribution, `overall_risk_score`, `signal_agreement_score`, `overall_confidence_score`, `risk_level`, `recommended_price_action × reliability`, `action_type`, expansion `recommended_action`, invariant) is **byte-identical before and after** — confirming the fix has exactly the predicted zero live effect, since the branch it touches was already provably dormant. `dbt run --full-refresh`: 24/24. `dbt test`: 146/147 pass (145 + 1 new `not_null` test), 0 errors, same pre-existing unrelated warning; all 6 guard tests (3 FRED + `has_prior_month_price` + `has_prior_month_ppi` ×2 models) PASS. Invariant = 0.
