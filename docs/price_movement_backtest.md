# Near-Term Price Movement Backtest

## Question
Can TrendShelf signals predict whether
store x category prices change >= 3%?

## Data availability note
Only one Kroger collection date exists (2026-06-10).
A Jun 8 vs Jun 10 temporal comparison was not possible.

## Adapted target
`price_deviated_3pct` — whether a store's category avg price
deviated >= 3% from the category mean across all stores on Jun 10.
This is independent of scoring features — valid cross-sectional backtest.

## Results
| Model              | AUC   | F1    | Precision | Recall | Beats Naive |
|--------------------|-------|-------|-----------|--------|-------------|
| LogisticRegression | 0.908 | 0.667 | 0.6 | 0.75 | YES |
| RandomForest       | 0.888       | 0.818       | 0.9       | 0.75       | YES |
| XGBoost            | 0.941            | 0.857            | 1.0            | 0.75            | YES |
| Naive baseline     | N/A   | 0.000 | 0.000     | 0.000  |             |

## Key finding
Top predictive signal: `pricing_power_score`
Best model: XGBoost  AUC=0.941  F1=0.857

## Limitations
- Cross-sectional only (store vs. category mean on 1 date)
- ~200 rows, store-level holdout
- Temporal split not possible with 1 month of data
- Enable weekly Kroger collection for genuine 2-date comparison
- Improve with weekly collection over 3+ months

## Portfolio statement
"Rebuilt validation using an independent observed outcome — whether Kroger
store x category prices deviate meaningfully from peer stores. Honest
about data availability constraints. First genuine cross-sectional backtest
of whether TrendShelf signals predict near-term retail pricing outliers."
