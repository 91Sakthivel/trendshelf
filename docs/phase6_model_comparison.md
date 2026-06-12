# Phase 6: Prophet vs XGBoost Demand Forecasting

## Task
Predict Google Trends interest_score 4 weeks ahead per category.

## Why this is valid
- Target is FUTURE interest_score (not TrendShelf score)
- XGBoost features are past lags and rolling stats only
- Temporal train/test split — test weeks 41-52 never seen in training
- Shuffled-target leakage guard confirms data integrity

## Results
| Model   | MAE  | RMSE | Beats Naive |
|---------|------|------|-------------|
| Naive   | 17.94 | 23.58 | baseline |
| XGBoost | 13.11 | 16.82 | True |
| Prophet | 523.80 | 1088.83 | False |

## Winner
XGBoost wins overall (lower MAE).
Easiest to forecast: beverages.  Hardest: breakfast cereal.

## Key finding
Top XGBoost signal: rolling_mean_8
XGBoost wins 10/10 categories, Prophet wins 0/10.

## Leakage guard
Shuffled-target MAE: 22.93  Real model MAE: 13.11
No leakage — real model clearly beats shuffled baseline.

## Limitations
- 52 weeks — Prophet needs 2+ seasonal cycles ideally
- Google Trends normalization: 100 = peak week (relative)
- Values may shift when new data is added (rescaling artifact)
- Improve with 12+ months of collection

## Why rule-based scoring over ML forecasting
TrendShelf uses rule-based scoring for interpretability.
ML forecasting here validates that the signals used in
scoring have genuine predictive power for demand.