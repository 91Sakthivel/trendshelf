# Demand Forecasting Model Selection

## Problem
Forecast weekly Google Trends interest score over 8-week holdout per category.

## Split
Temporal: train < 2026-04-01, test >= 2026-04-01
No data leakage verified.

## Results (MAPE %)

| Category | Naive | MovAvg | Linear | Prophet | XGBoost | Best |
|----------|------:|-------:|-------:|--------:|--------:|------|
| beverages              | 10.1 | 10.3 | 13.7 | 18.3 | 10.1 | Naive |
| breakfast cereal       | 42.8 | 33.4 | 38.1 | 71.0 | 41.2 | MovAvg |
| coffee tea             | 8.3 | 11.7 | 12.5 | 41.8 | 12.1 | Naive |
| dairy                  | 16.1 | 14.1 | 19.1 | 23.2 | 15.6 | MovAvg |
| frozen foods           | 4.6 | 5.1 | 12.8 | 33.7 | 4.6 | XGBoost |
| household              | 11.9 | 21.3 | 30.4 | 21.1 | 24.2 | Naive |
| meat seafood           | 23.6 | 27.6 | 33.1 | 48.8 | 23.2 | XGBoost |
| personal care          | 35.3 | 32.4 | 41.6 | 62.0 | 34.9 | MovAvg |
| produce                | 12.5 | 14.1 | 15.0 | 57.8 | 15.0 | Naive |
| snacks                 | 24.0 | 16.7 | 17.9 | 35.2 | 25.3 | MovAvg |
| AVERAGE                | 18.9 | 18.7 | 23.4 | 41.3 | 20.6 | MovAvg |

## Winner: MovAvg
- MAPE: 18.7% vs naive 18.9% (1.3% improvement)
- Beats naive in 4/10 categories
- Selected for accuracy + stability + interpretability balance

## Limitations
- Google Trends proxy -- not actual sales or volume data
- 52-week history limits seasonal signal
- Retrain monthly after each new collection run
- Alert if MAPE exceeds 25% in any category
- True demand forecasting requires POS/sales labels
