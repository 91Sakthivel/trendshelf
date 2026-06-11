# Scoring Sensitivity and Consistency Analysis

## Purpose
Internal consistency check only. Not business outcome validation.

## Score Distribution
- Scores range: 58.6 to 66.2
- Mean: 62.5, Std: 2.4
- Low std flag: yes

## Sensitivity Analysis
Most sensitive weight: confidence
  -- 0.0% of rows change tier with 10% weight adjustment
Least sensitive weight: risk (inv)
  -- 0.0% of rows change tier with 10% weight adjustment

## ML Consistency Check
Best consistency model: Logistic Regression
AUC: 1.000  F1: 1.0
Feature rank correlation with manual weights: r=0.72
Verdict: Consistent

## Key Finding
Feature rank correlation between XGBoost and manual weights is r=0.72 (Consistent). Most sensitive weight is 'confidence' — a 10% change shifts 0.0% of rows to a different tier.

## Limitations
- Internal consistency only -- not outcome validation
- 200 rows, 1 month of data, store-level holdout (5/20 test stores)
- True validation requires sales/volume data
- Rerun after 6+ months of data accumulates
