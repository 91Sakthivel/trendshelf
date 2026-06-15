# TrendShelf v4 — Pricing Engine + Append Fix Session
Date: June 2026 (pre-June-22 collection)

## DONE THIS SESSION (uncommitted, on disk)

### Batch 1 — mart_pricing_intelligence.sql
- COALESCE NULL bug fixed: price_gap_pct returns NULL (not -100%)
  when either side missing; price_position guards NULL with 'Unknown'
- Median aggregation (APPROX_QUANTILES[50]) replaces AVG, both sides
- Outlier exclusion: products > 5x category median dropped
  (removed $229.99 espresso machine from coffee tea)
- CV-calibrated price bands: GREATEST(8, LEAST(25, cv_pct * 0.16))
  replaces flat +/-10% — each category self-calibrates
- Smooth confidence weight: n/(n+15) replaces step-function CASE
- kroger_private_label_share column added (exposed, not penalizing)
- score_version = 'v4_statistical_calibration' in ALL 7 marts

### Batch 1.5 — reliability gate (THE KEY FIX)
- price_gap_reliability column: High/Medium/Low/Unknown
  Low when competitor_product_count < 10 OR abs(gap) > 50
  Medium when abs(gap) > 25
  High otherwise
- price_gap_reliability_reason: plain-English explanation
- Reduce Price branches gated on reliability = 'High'
- private_label confidence penalty REMOVED (keyed wrong variable;
  reliability gate does this job correctly now)
- RESULT: Reduce Price 90 -> 20, removed 70 fake recommendations
- INVARIANT PROVEN: zero Reduce Price under Low reliability

### Append fix — collect_apis.py (CRITICAL data-loss bug)
- WAS: WRITE_TRUNCATE on kroger_prices_raw + serpapi_prices_raw
  (every collection wiped all prior dates)
- NOW: _upload_append_idempotent() using DAY partition decorator
  ($YYYYMMDD suffix + WRITE_TRUNCATE on partition only)
  Free-tier safe (Load Jobs API, not DML)
  Same-day rerun = idempotent; new day = accumulates
- fred/bls unchanged (WRITE_TRUNCATE, reference series)
- google_trends unchanged (already WRITE_APPEND)
- Backups retained: kroger_prices_raw_backup_jun10 (9,995 rows),
  serpapi_prices_raw_backup_jun09 (248 rows)
- Verified: dbt run PASS=19, dbt test PASS=103 WARN=1 (sold-by-weight)

## LEFT TO DO

Group A (single-date safe, build anytime):
- 6-cleanup: move CV constants (0.16, 8, 25) to dbt_project.yml vars
  + add relative_gap_tier diagnostic (Top/Middle/Bottom third, NOT
  precise percentile — N=20 too small). CV stays the classifier,
  percentile is diagnostic only (reviewer decision).
- 7: OLS slope velocity in int_demand_trend_features.sql
  (replaces fragile 3-point second-derivative). Uses LAG window
  over 8 weeks. demand_state from slope/noise ratio.
- 10: NTILE(4) opportunity tiers + within-category rank
- 11: sensitivity notebook (test CV multiplier 0.12/0.16/0.20,
  thresholds, confirm action distribution stable)

Group B (AFTER June 22, needs 2+ dates):
- 8: explicit demand x price matrix routing (fills 3 empty
  fall-through cells). Build WITH temporal gate, not before.
- temporal gate: gap_direction_stable via LAG over collection_date,
  directional_pricing_signal column (separate from
  recommended_price_action), gated on collection_count >= 2.
  Dormant today, auto-activates June 22.

## DATA SCIENCE LAYER (parked until July 6, 3+ dates)
- Isolation Forest anomaly detection (July 6)
- Bayesian price-gap estimation (replaces hardcoded confidence)
- Promote XGBoost demand forecast -> production scoring feature
- Price elasticity regression (August, month 3+)
- Mature time-series + backtesting (November, month 6+)
- NO deep learning (theater at this data scale)

## JUNE 22 RITUAL (do not skip)
After collection, BEFORE deleting backups:
  SELECT DATE(collected_at) dt, COUNT(*) rows
  FROM kroger_prices_raw GROUP BY 1 ORDER BY 1;
  MUST show 2026-06-10 AND 2026-06-22.
  If only one date -> append failed -> restore backup -> debug.

## KEY DECISIONS / PRINCIPLES
- CV method = action classifier; percentile = peer context only
  (percentile over-flags ~25% by construction — rejected as primary)
- Reliability gate = safety layer barring fake gaps from actions
- Constants externalized to vars + documented + sensitivity-tested,
  not eliminated (can't derive without 6+ months data)
- No DL. ML enhances where it adds signal; rules decide.
