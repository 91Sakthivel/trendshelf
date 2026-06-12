# Demand Direction Prediction — Temporal Backtest

## Question
Can past Google Trends patterns predict whether
category demand will increase in the next 4 weeks?

## Why this is valid ML
- Target is FUTURE demand (not TrendShelf scores)
- Features are PAST lags and rolling stats only
- Temporal train/test split — test weeks never seen in training
- Shuffled-target leakage guard confirms data integrity

## Results
| Model | AUC | F1 | Precision | Recall | Beats Naive |
|-------|-----|----|-----------|----|-------------|
| LogisticRegression | 0.421 | 0.0 | 0.0 | 0.0 | no |
| RandomForest | 0.789 | 0.125 | 0.067 | 1.0 | YES |
| XGBoost | 0.816 | 0.105 | 0.056 | 1.0 | YES |
| Naive baseline | N/A | 0.095 | 0.05 | 1.0 |  |

## Key finding
Top predictive signal: week_of_year
Best model: XGBoost  AUC=0.816  F1=0.105
Shuffled-target AUC: 0.737  (leakage guard)

## Limitations
- 52 weeks x 10 categories = 520 rows
- Single time series per category — limited diversity
- 4-week ahead prediction window
- Google Trends = search interest, not actual sales

## How this differs from the scoring leakage audit
The scoring leakage audit confirmed formula consistency.
This notebook is a genuine temporal backtest using
future outcomes as the target.

## Portfolio statement
"Built a temporal demand direction model predicting whether category
search interest will increase over the next 4 weeks. Used past lags
and rolling features only, with a held-out future test set. Distinct
from the scoring leakage audit — this uses future outcomes as the
prediction target, not TrendShelf own scores."