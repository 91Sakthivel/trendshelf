# TrendShelf — Batch 3 + A-to-Z Audit + Repo Hardening
Date: June 25, 2026
Commits (on main, NOT pushed): 3580911 (Batch 3), c28dd58 (hardening)
Build state: dbt run PASS=21 / dbt test PASS=132 WARN=1 (sold-by-weight) ERROR=0

## BATCH 3 — temporal foundation (3580911)

### New model: fct_store_category_weekly
- Grain: store_id x category_name x kroger_collection_date. ALL history preserved
  (opposite of the snapshot mart, which pins to the latest partition).
- 15 columns; 600 rows = 200 x 3 dates. Reuses the same median/outlier/CV logic
  as mart_pricing_intelligence, grouped by collection_date.
- This is the time-series foundation every future temporal/DS feature reads from.

### New model: int_pricing_temporal_features
- Reads fct_store_category_weekly, per store x category ordered by date.
- 8 fields: previous_price_gap_pct, previous_gap_direction, gap_direction_stable,
  collection_count, stable_direction_count (gaps-and-islands run length),
  price_gap_change_pct, price_gap_volatility, directional_action_eligible.
- previous_price_gap_pct NULL only on June 10 (first date) — correct.
- stable_direction_count resets to 1 on a direction flip (verified: 49 correct
  resets on date 2, 0 wrong resets).

### mart_pricing_intelligence — directional layer (joined, cascade untouched)
- directional_pricing_signal + directional_signal_confidence added as SEPARATE
  columns. recommended_price_action cascade NOT modified (stays 161/20/19).

### KEY DECISION — directional signal gated by competitor reliability
- Diagnostic found a leak: 60 of 80 "Sustained Overpriced" were Low reliability
  (personal care 20, household 20, frozen foods 20) — the weak-basket categories
  the Reduce Price gate already blocks. The directional column had no analogous gate,
  so it quietly re-introduced the same bias the action column blocks.
- FIX: gap_direction_stable=TRUE AND reliability in (Low,Unknown) -> 'Unreliable
  Benchmark' (distinct from 'Insufficient Data' — data exists, basket is weak,
  not data-short). Only the 20 High-reliability breakfast-cereal rows remain
  legitimate Sustained Overpriced.
- Final directional split: Insufficient Data 39, Unreliable Benchmark 60,
  Sustained Overpriced 20, Sustained Fair 56, Sustained Underpriced 25.

### KEY DECISION — n-date confidence (removed the "Established" overclaim)
- Calling 3-week signals "Established" overclaims (3 points show direction, not
  trend vs noise). New var directional_established_min_dates: 4.
- Confidence: Insufficient (no prev) / Unreliable (low reliability) /
  Provisional (>=High/Med, <4 dates) / Established (>=4 dates).
- At 3 dates: Established=0, Provisional=101. Auto-promotes at the 4th collection
  (~July 1) with NO code change.

### KEY DECISION — Monitor=161 is NOT a bug, it's framing
- Breakdown: 60 correctly reliability-gated + 50 genuinely fair-priced (no action
  to manufacture) + ~51 blocked by legitimate multi-factor gates. Forcing actions
  would re-create the spurious-rec problem. Honest answer = the 3-tier story:
  39 hard actions (Protect 20 / Reduce 19) + ~101 Provisional advisories +
  transparent gating. This is a demo-framing task, not an engineering fix.

### KEY DECISION — Google Trends slope NOT added to cascade
- demand_state (OLS slope) is frozen — Trends pulled once (52wk), identical across
  all 3 dates. Adding it = static per-category bump, not a temporal signal (theater).
- The cascade already carries Trends LEVEL via demand_signal (from
  overall_demand_gap_score -> category_momentum_score). Deliberately left as-is.

## A-to-Z AUDIT — result
- All correctness sections PASS: clean build 21/132, grain/fan-out integrity,
  date-anchoring regression guard (mart pins to single latest Kroger date, no
  blending), all scoring invariants (zero Reduce/Sustained under Low reliability,
  Established=0), temporal resets, null/value-range, secrets clean, pipeline
  guardrails intact.
- FAILs/FLAGs were all packaging, not engine: stale README + config hygiene.

## HARDENING PASS (c28dd58)
- Investigate gate: replaced inline `confidence_score < 50` in pricing mart with
  var investigate_confidence_threshold (=45); both marts now one source of truth.
  Proven neutral: 0 rows in the [45,50) band, distribution unchanged 161/20/19.
- Externalized 6 action-routing gates to dbt vars: margin_pressure_avoid 65,
  pricing_power_hold 70, pricing_power_strong 75 (kept SEPARATE from 70 on purpose —
  two distinct gates), reduce_price_min_gap_pct 10, markdown_safety_full 60,
  competitive_threat 70. Scoring-formula weights + diagnostic tier cutoffs left
  inline by design (documented, not externalized).
- Source freshness (warn 9 / error 16) added to fred_ppi_raw, bls_cpi_raw,
  google_trends_raw. Stale serpapi + fred sources.yml descriptions corrected.
- Deleted 5 throwaway diagnostic scripts (none imported anywhere).
- README rewritten to reality: 21 models / 9 marts / 132 tests / real model names /
  8-level cascade / temporal + directional layers / v4 bands / score_version /
  date-blending fix / validation-leakage section / accurate "thresholds centralized
  where they affect routing" wording / honest LIMITATIONS paragraph (3 dates ->
  Provisional, Trends frozen -> price-only, no sales labels -> internal-consistency).

## OPEN ITEMS
- [ ] git push 3580911 + c28dd58 (currently local only)
- [ ] decide: drop backup tables (kroger_..._backup_jun10, serpapi_..._backup_jun09)
- [ ] DEFERRED: Streamlit fix (GitHub App re-auth + Python 3.14->3.12)
- [ ] 4th collection ~July 1 -> auto-promotes directional to Established
- [ ] GitHub Actions weekly automation
- [ ] multi-frequency collection decision (--mode kroger twice-weekly) — raised, not decided
- [ ] PARKED DS/ML (start ~July 6): Isolation Forest, Bayesian price-gap,
      promote XGBoost demand forecast, elasticity (Aug), time-series (Nov). No DL.
- [ ] Phase 10: Instacart multi-retailer via SerpAPI; FRED category PPI
- [ ] ComplaintIQ (second project) — not started
