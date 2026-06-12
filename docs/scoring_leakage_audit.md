# TrendShelf Scoring Leakage Audit

## Purpose
Check whether the ML validation model was learning the rule-based opportunity score formula.

## Target
`target = overall_opportunity_score >= 65`

## Why leakage is possible
`overall_opportunity_score` is created from component scores such as demand gap, expansion readiness,
pricing power, confidence, risk safety, and markdown safety. If these same features are used to
train a model, the model may simply reconstruct the formula.

## Tests Run
1. Feature leakage audit
2. Leaky vs masked model comparison
3. K-fold stability check
4. Shuffled-target sanity check
5. Feature importance review

## Results

### Feature Leakage Audit
| Feature | Leakage Level | Reason |
|---------|---------------|--------|
| overall_opportunity_score | Direct target leakage | IS the target or directly encodes it |
| opportunity_tier | Direct target leakage | IS the target or directly encodes it |
| overall_demand_gap_score | Formula component leakage | Direct input to opportunity_score formula |
| expansion_readiness_score | Formula component leakage | Direct input to opportunity_score formula |
| pricing_power_score | Formula component leakage | Direct input to opportunity_score formula |
| confidence_score | Formula component leakage | Direct input to opportunity_score formula |
| overall_risk_score | Formula component leakage | Direct input to opportunity_score formula |
| markdown_safety_score | Formula component leakage | Direct input to opportunity_score formula |
| adjusted_price_gap_pct | Derived / partial leakage | Derived from scoring pipeline |
| price_gap_confidence_weight | Derived / partial leakage | Derived from scoring pipeline |
| price_gap_pct | Allowed masked feature | Upstream proxy; not a direct formula input |
| competitor_product_count | Allowed masked feature | Upstream proxy; not a direct formula input |
| kroger_product_count | Allowed masked feature | Upstream proxy; not a direct formula input |
| google_trends_level_score | Allowed masked feature | Upstream proxy; not a direct formula input |
| google_trends_momentum_score | Allowed masked feature | Upstream proxy; not a direct formula input |
| demand_velocity_score | Allowed masked feature | Upstream proxy; not a direct formula input |
| ppi_3mo_trend | Allowed masked feature | Upstream proxy; not a direct formula input |
| cpi_3mo_trend | Allowed masked feature | Upstream proxy; not a direct formula input |

### Leaky vs Masked Comparison
| Model | Features | AUC | Precision | Recall | F1 | Accuracy | TN | FP | FN | TP |
|-------|----------|-----|-----------|--------|----|----------|----|----|----|----|
| RF Leaky | 16 | 1.000 | 1.0 | 1.0 | 1.0 | 1.0 | 45 | 0 | 0 | 5 |
| RF Masked | 8 | 1.000 | 1.0 | 1.0 | 1.0 | 1.0 | 45 | 0 | 0 | 5 |
| LR Masked | 8 | 1.000 | 1.0 | 1.0 | 1.0 | 1.0 | 45 | 0 | 0 | 5 |
| RF Ultra-masked | 8 | 1.000 | 1.0 | 1.0 | 1.0 | 1.0 | 45 | 0 | 0 | 5 |

### K-Fold Stability (5-fold, RandomForest)
| Feature Set | AUC mean | AUC std | Prec mean | Prec std | Recall mean | Recall std | F1 mean | F1 std |
|-------------|----------|---------|-----------|----------|-------------|------------|---------|--------|
| Leaky | 1.000 | 0.000 | 1.0 | 0.0 | 1.0 | 0.0 | 1.0 | 0.0 |
| Masked | 1.000 | 0.000 | 1.0 | 0.0 | 1.0 | 0.0 | 1.0 | 0.0 |
| Ultra-masked | 1.000 | 0.000 | 1.0 | 0.0 | 1.0 | 0.0 | 1.0 | 0.0 |

### Shuffled-Target Sanity Check
| Check | Value |
|-------|-------|
| Shuffled-target AUC | 0.351 |
| Shuffled-target Precision | 0.0 |
| Shuffled-target F1 | 0.0 |

### Top Feature Importances
**Leaky model top feature:** `google_trends_momentum_score` (importance=0.2284)
**Masked model top feature:** `google_trends_momentum_score` (importance=0.2985)

## Verdict
Partial leakage likely, but raw/proxy features also reconstruct the score well. Upstream demand and pricing signals contain genuine predictive signal, but the model benefits from formula component overlap.

## Interpretation
If the leaky model performs much better than the masked model, the original model should be treated
only as internal consistency validation, not a true predictive backtest.

## Correct README wording
> "Initial ML validation produced very high performance because the model used component scores that
> also define the opportunity target. I treated this as an internal consistency check and then ran
> a masked leakage audit using only upstream proxy features. True outcome validation will require
> future sales, margin, unit-volume, or multi-month action outcome labels."

## Limitations
- 200 rows
- 1 month of scoring data
- Target is rule-derived
- No sales/profit/unit-volume label
- Store-level holdout only
- True validation needs 3-6+ months of history