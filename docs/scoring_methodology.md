# TrendShelf Scoring Methodology

## Overview

TrendShelf scores each combination of Kroger store × product category × month on five dimensions — demand gap, shelf risk, price/margin health, signal confidence, and expansion readiness — then routes each signal to a recommended action. Scores are rules-based composites derived from five data sources (Kroger shelf prices, Google Trends, FRED PPI, BLS CPI, SerpAPI competitor prices). They are leading indicators designed to help CPG brand account managers prioritise where to pitch distribution expansion, defend shelf position, or adjust pricing, before the opportunity closes or the threat escalates.

---

## Data Sources

| Source | What it measures | Refresh cadence | Signal type |
|--------|-----------------|-----------------|-------------|
| Kroger prices (Kroger API) | Retail shelf prices, promo activity, product count per store × category | Weekly | Measured |
| Google Trends (pytrends) | Consumer search interest by category, US-level, daily | Weekly | Measured (proxy for consumer intent) |
| FRED PPI (FRED API) | Producer Price Index by Industry: Food Manufacturing (PCU311311) — a producer-side input-cost index, applied as a cost proxy | Monthly (2-month lag) | Measured |
| BLS CPI (BLS API) | Consumer Price Index for Food at home — retail inflation benchmark | Monthly (2-month lag) | Measured |
| SerpAPI competitor prices | Competitor shelf prices from Google Shopping (Walmart proxy) | Weekly | Measured |

---

## Score Weights and Justification

### `category_momentum_score`

Measures how fast consumer interest in the category is moving and whether macro conditions support demand.

```
category_momentum_score =
    google_trends_momentum_score × 0.80
  + ((normalized_cpi_growth_score + normalized_ppi_growth_score) / 2) × 0.20
```

**Why these weights:**
- Google Trends momentum (80%) is the primary driver because it directly measures consumer intent in near-real time, while PPI/CPI are lagging indicators of cost pressure rather than consumer demand.
- Macro signals (20%) add context: when both input costs and consumer prices are rising, category momentum is partly inflated by price rather than volume, so the combined score is discounted slightly.

### `search_to_shelf_gap`

Measures unmet demand: how much consumer interest exists relative to the number of products currently on shelf.

```
search_to_shelf_gap = avg_search_interest × SAFE_DIVIDE(50.0, product_count_per_store_category)
```

**Why 50 as the baseline:** 50 products represents a reasonably complete shelf assortment for one category at one store. Above 50 products the gap is negative (over-supplied relative to interest). Below 50 the gap is positive. Capped at 100.

### `overall_demand_gap_score`

Composite of four signals measuring how much consumer demand exceeds current shelf supply.

```
overall_demand_gap_score =
    category_momentum_score × 0.25
  + search_to_shelf_gap     × 0.40
  + phantom_distribution    × 0.15
  + intent_quality_score    × 0.20
```

**Why search_to_shelf_gap is weighted highest (40%):** It is the most direct and actionable signal — it quantifies how many shelf positions are missing relative to consumer interest at a specific store. The other three components provide supporting context.

### `overall_confidence_score`

Scores how much to trust each row's analysis. Combines four components.

```
overall_confidence_score =
    data_completeness_score         × 0.30
  + signal_agreement_score          × 0.25
  + collection_recency_score        × 0.20
  + row_level_source_coverage_score × 0.25
```

**Component justifications:**

| Component | Weight | Rationale |
|-----------|--------|-----------|
| `data_completeness_score` | 30% | Source presence is the prerequisite for any analysis. 5 sources × 20 pts each. |
| `signal_agreement_score` | 25% | Signals pointing in different directions reduce confidence that the composite score is correct. |
| `collection_recency_score` | 20% | Stale data degrades signal quality — for the 4 actively-refreshed sources. Kroger weighted highest (31.25%) within this component; SerpAPI lowest (18.75%) because it is a shopping-level proxy. Google Trends is excluded: it's a deliberate one-time historical baseline (`COLLECT_GOOGLE_TRENDS` off by design), not a source that should ever look "fresh" — scoring it as stale would permanently dock confidence for a design choice. Trends still counts toward `data_completeness_score` and `row_level_source_coverage_score`. |
| `row_level_source_coverage_score` | 25% | Kroger anchors the retail price (35 pts), Trends provides consumer intent (25 pts), FRED+BLS together provide macro context (25 pts), SerpAPI provides competitive context (15 pts). |

**Why Kroger gets the highest single-source weight (35 pts):** It is the retail anchor — without a shelf price there is no fact row. Every other score depends on it.

**Why SerpAPI gets only 15 pts:** Competitor pricing from Google Shopping is a category-level proxy, not a SKU-level match. It is useful directionally but less precise than first-party Kroger data.

### `expansion_readiness_score`

Model-derived composite synthesising all four scoring layers into a single pitch-priority score.

```
expansion_readiness_score =
    region_opportunity_score × 0.35
  + store_market_fit_score   × 0.30
  + (100 - overall_risk_score) × 0.20
  + overall_confidence_score   × 0.15
```

Where:
- `region_opportunity_score = overall_demand_gap_score × 0.50 + category_momentum_score × 0.30 + intent_quality_score × 0.20`
- `store_market_fit_score = search_to_shelf_gap × 0.40 + price_position_score × 0.25 + (100 − margin_pressure_proxy_score) × 0.20 + (100 − promo_risk_score) × 0.15`

**Why risk inverted (1 − risk):** High risk is a gate on expansion. The formula penalises readiness when risk is elevated — it would be counterproductive to expand into a store where shelf risk is already severe.

**Why confidence is only 15%:** Confidence is a prerequisite check, not a demand signal. A low-confidence score with otherwise strong demand still warrants investigation rather than expansion, so the INVESTIGATE gate in the action queue catches it before this score matters.

### Action Cascade (mart_action_queue)

Actions fire in priority order — the first matching condition wins:

| Priority | Action | Condition |
|----------|--------|-----------|
| 0 | INVESTIGATE (gate) | `retail_price IS NULL OR confidence < 45 OR completeness < 60` |
| 1 | AVOID | `demand_decay_risk > 70 OR margin_pressure_proxy_score > 80` |
| 2 | EXPAND | `expansion_readiness > 80 AND confidence > 70` |
| 3 | DEFEND | `competitive_threat_risk > 70` |
| 4 | PITCH | `readiness BETWEEN 65 AND 80 AND demand_gap > 60` |
| 5 | REPRICE | `price_position_score > 70 AND demand_gap > 50` |
| 6 | CUTPROMO | `promo_risk_score > 70` |
| 7 | MONITOR | `confidence >= 60 AND readiness < 65` |
| 8 | INVESTIGATE (default) | Catch-all |

---

## Intelligence Layer v2 — Added Features

### `demand_velocity_score` and `demand_velocity_direction` (int_demand_trend_features)

Measures the **rate of change of momentum** — the second derivative of Google Trends interest. Uses three consecutive 4-week windows (recent, prior, earlier).

```
demand_velocity_score =
    (trends_recent_4wk_avg − trends_prior_4wk_avg)
  − (trends_prior_4wk_avg − earlier_4wk_avg)
```

| Direction label | Condition |
|-----------------|-----------|
| Accelerating | velocity_score > 5 |
| Decelerating | velocity_score < −5 |
| Stable Velocity | −5 ≤ velocity_score ≤ 5 (or insufficient history) |

**Why the second derivative:** A rising trend (positive 4wk momentum) that is slowing down is fundamentally different from one that is accelerating. Velocity direction distinguishes categories that are gaining steam from those that are peaking, enabling earlier action.

---

### `macro_risk_flag` (fact_market_signals)

Synthesises PPI and CPI trend directions into a single actionable macro risk label.

| Flag | Condition |
|------|-----------|
| High Inflation Risk | PPI Rising AND CPI Rising |
| Cost Pressure | PPI Rising (CPI not rising) |
| Cost Relief | PPI Falling |
| Stable Macro | All other combinations |

**Why PPI is the primary driver:** PPI measures input costs for producers — it is a leading indicator of margin pressure for Kroger and brands. CPI rising on top of PPI indicates the full inflation pass-through has occurred, creating the highest risk scenario.

---

### `competitive_intensity` (mart_pricing_intelligence)

Classifies the competitive landscape for each category based on competitor product count sampled from SerpAPI (Walmart DFW store 2105).

| Label | Condition |
|-------|-----------|
| Saturated | competitor_product_count ≥ 30 |
| Competitive | competitor_product_count ≥ 15 |
| Emerging | competitor_product_count ≥ 5 |
| Sparse | competitor_product_count < 5 |

**Cascade guard:** Hold Premium is blocked when `competitive_intensity = 'Saturated'`. In a saturated market, holding a premium over Walmart is unlikely to be sustainable even with high pricing power, because consumers have abundant alternatives.

---

### `overall_opportunity_score` (mart_action_queue)

Weighted composite of six strategic dimensions. Designed to rank signals by their commercial value rather than urgency alone.

```
overall_opportunity_score =
    overall_demand_gap_score     × 0.25
  + expansion_readiness_score    × 0.20
  + (100 − overall_risk_score)   × 0.20
  + overall_confidence_score     × 0.15
  + premium_support_proxy_score  × 0.10
  + (100 − overall_margin_risk)  × 0.10
```

| Tier | Threshold |
|------|-----------|
| Prime | score ≥ 75 |
| Solid | score ≥ 55 |
| Watch | score ≥ 35 |
| Low | score < 35 |

---

### `category_lifecycle` (mart_action_queue)

Classifies where a category sits in its demand cycle based on velocity direction, trend direction, and competitive intensity.

| Lifecycle Stage | Condition |
|-----------------|-----------|
| Growth Accelerating | demand_velocity_direction = 'Accelerating' |
| Growth Slowing | Decelerating AND demand_trend in (Rising, Stable) |
| Declining | Decelerating AND demand_trend = Falling |
| Emerging | competitive_intensity in (Sparse, Emerging) |
| Mature | Default |

---

### `seasonality_adjusted_action` (mart_action_queue)

Protects against over-committing to expansion during a seasonal spike that may not represent durable demand.

**Guard condition:** If `seasonality_flag = 'Possible Seasonal Spike'` AND `confidence < 75` AND `action_type IN ('EXPAND', 'PITCH')`, then output `MONITOR` instead.

**Why confidence < 75 as the gate:** High-confidence signals (≥75) have sufficient data quality to distinguish a genuine demand surge from a seasonal blip. Low-confidence spikes are more likely to be noise. Only EXPAND and PITCH are downgraded — DEFEND and REPRICE are valid responses to seasonal competition.

---

### `demand_reason_code` and `risk_reason_code` (mart_action_queue)

Machine-readable tags for downstream filtering and dashboard tooltips.

**demand_reason_code** (first-match):

| Code | Condition |
|------|-----------|
| SEASONAL_SPIKE | seasonality_flag = 'Possible Seasonal Spike' |
| ACCELERATING | demand_velocity_direction = 'Accelerating' |
| DECELERATING | demand_velocity_direction = 'Decelerating' |
| HIGH_STABLE | Stable velocity AND demand_gap ≥ 60 |
| MEDIUM_STABLE | Stable velocity AND demand_gap ≥ 45 |
| LOW_STABLE | Stable velocity AND demand_gap < 45 |
| NO_DATA | No trend data available |

**risk_reason_code** (first-match):

| Code | Condition |
|------|-----------|
| HIGH_INFLATION_RISK | macro_risk_flag = 'High Inflation Risk' |
| COST_PRESSURE | macro_risk_flag = 'Cost Pressure' |
| COST_RELIEF | macro_risk_flag = 'Cost Relief' |
| SATURATED_MARKET | competitive_intensity = 'Saturated' |
| HIGH_OPERATIONAL_RISK | overall_risk_score > 70 |
| STABLE | Default |

---

## Limitations

- **Only 1 month of Kroger retail data currently.** LAG-based scores (margin_pressure_proxy_score, demand_decay_risk, trend velocity) all default to conservative mid-range values because there is no prior month to compare against. Score standard deviations are low; differentiation will improve as more months accumulate.
- **Google Trends is category-level, not SKU-level.** "beverages" search interest is attributed equally to all stores in the same month. Store-level demand variation is captured only through the shelf coverage (product count) dimension.
- **Competitor pricing from SerpAPI is a Walmart/Google Shopping proxy.** It is not a direct SKU-to-SKU Kroger vs. competitor match. Competitive threat risk is more reliable when both competitor prices and Kroger prices are available in the same category.
- **No actual sales outcome data.** All scores are leading indicators derived from publicly available signals. They have not been validated against historical sell-through data.
- **PPI and CPI have a 2-month reporting lag.** The model uses a latest-available-as-of join to handle this, but macro signals always reflect conditions 2 months prior to the current reference month.

---

## Future Improvements

- **ML scoring layer** after 6+ months of data accumulates — replace rules-based thresholds with a trained model calibrated against actual distribution outcomes.
- **SKU-level demand signals** — integrate Kroger's item-level sales velocity (requires retailer data sharing agreement).
- **Multi-retailer competitor pricing** — expand SerpAPI queries to Target, Costco, Amazon to improve competitive threat accuracy.
- **Seasonal baseline normalisation** — once 12+ months of Google Trends data exists, use year-over-year comparisons rather than the current 4-week-vs-prior-4-week momentum signal.
- **Confidence-weighted score aggregation** — weight each mart score by its row-level confidence before composite construction to reduce noise from low-confidence signals.
