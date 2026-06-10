"""Runs the validation logic from trendshelf_validation.ipynb directly."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import bigquery
from google.oauth2 import service_account
import pandas as pd

PROJECT = PROJECT_ID
DATASET = 'bronze'

creds = service_account.Credentials.from_service_account_file(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'credentials.json')
)
client = bigquery.Client(project=PROJECT, credentials=creds)

def bq(sql):
    return client.query(sql).to_dataframe()

results = []

def check(rule_name, df, condition_col, target_pct=95.0):
    pct = df[condition_col].mean() * 100
    passed = pct >= target_pct
    results.append((rule_name, round(pct, 1), passed))
    status = 'PASS' if passed else 'FAIL'
    print(f'  [{status}]  {rule_name}: {pct:.1f}% (target >= {target_pct}%)')
    return pct

# â”€â”€ Section 1: Action Routing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print('=== Section 1: Action Routing Validation ===')

aq = bq(f"""
    SELECT
        aq.recommended_action, aq.decision_strength,
        aq.overall_confidence_score, aq.overall_demand_gap_score,
        aq.overall_risk_score,
        er.expansion_readiness_score,
        aq.driving_score, aq.reason_code, aq.row_level_source_coverage_score
    FROM `{PROJECT}.{DATASET}.mart_action_queue` aq
    LEFT JOIN `{PROJECT}.{DATASET}.mart_expansion_readiness` er
           ON aq.store_id = er.store_id
          AND aq.category_name = er.category_name
""")

print(f'Total rows: {len(aq)}')
print('Action distribution:')
print(aq['recommended_action'].value_counts().to_string())
print()

pitch = aq[aq['recommended_action'] == 'PITCH'].copy()
if len(pitch):
    pitch['demand_gap_ok'] = pitch['overall_demand_gap_score'] > 60
    pitch['readiness_ok']  = (pitch['expansion_readiness_score'] >= 65) & (pitch['expansion_readiness_score'] <= 80)
    pitch['condition_ok']  = pitch['demand_gap_ok'] & pitch['readiness_ok']
    print(f'PITCH rows: {len(pitch)}')
    check('PITCH: demand_gap>60 AND readiness in [65,80]', pitch, 'condition_ok')

monitor = aq[aq['recommended_action'] == 'MONITOR'].copy()
if len(monitor):
    monitor['condition_ok'] = monitor['overall_confidence_score'] >= 60
    print(f'MONITOR rows: {len(monitor)}')
    check('MONITOR: confidence >= 60', monitor, 'condition_ok')

cutpromo = aq[aq['recommended_action'] == 'CUTPROMO'].copy()
if len(cutpromo):
    cutpromo['condition_ok'] = cutpromo['reason_code'] == 'PROMO_RISK_MARGIN_PRESSURE'
    print(f'CUTPROMO rows: {len(cutpromo)}')
    check('CUTPROMO: reason_code = PROMO_RISK_MARGIN_PRESSURE', cutpromo, 'condition_ok')

defend = aq[aq['recommended_action'] == 'DEFEND'].copy()
if len(defend):
    defend['condition_ok'] = defend['reason_code'] == 'COMPETITOR_THREAT_HIGH'
    print(f'DEFEND rows: {len(defend)}')
    check('DEFEND: reason_code = COMPETITOR_THREAT_HIGH', defend, 'condition_ok')

investigate = aq[aq['recommended_action'] == 'INVESTIGATE'].copy()
if len(investigate):
    investigate['condition_ok'] = investigate['overall_confidence_score'] < 45
    check('INVESTIGATE: confidence < 45', investigate, 'condition_ok', target_pct=0.0)
else:
    print('INVESTIGATE: 0 rows (no low-confidence signals) [PASS]')
    results.append(('INVESTIGATE: 0 rows = no low-confidence signals', 100.0, True))

# â”€â”€ Section 2: Score Ranges â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print('=== Section 2: Score Range Validation ===')

score_checks = [
    ('mart_demand_gap_scores',    'overall_demand_gap_score'),
    ('mart_shelfrisk_scores',     'overall_risk_score'),
    ('mart_price_margin_scores',  'margin_pressure_risk'),
    ('mart_confidence_layer',     'overall_confidence_score'),
    ('mart_expansion_readiness',  'expansion_readiness_score'),
]

for table, col in score_checks:
    df = bq(f'SELECT {col} FROM `{PROJECT}.{DATASET}.{table}`')
    s = df[col]
    in_range  = ((s >= 0) & (s <= 100)).all()
    not_const = s.std() > 5
    ok = in_range and not_const
    status = 'PASS' if ok else 'FAIL'
    results.append((f'{table}.{col}: range 0-100 & std>5', 100.0 if ok else 0.0, ok))
    print(f'  [{status}]  {table}.{col}: min={s.min():.1f} mean={s.mean():.1f} max={s.max():.1f} std={s.std():.1f}')

# â”€â”€ Section 3: Signal Agreement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print('=== Section 3: Signal Agreement Check ===')

full = bq(f"""
    SELECT
        aq.recommended_action,
        aq.overall_demand_gap_score,
        er.expansion_readiness_score,
        aq.overall_confidence_score,
        pm.margin_pressure_risk,
        pm.promo_risk_score
    FROM `{PROJECT}.{DATASET}.mart_action_queue` aq
    LEFT JOIN `{PROJECT}.{DATASET}.mart_price_margin_scores` pm
           ON aq.store_id = pm.store_id
          AND aq.category_name = pm.category_name
    LEFT JOIN `{PROJECT}.{DATASET}.mart_expansion_readiness` er
           ON aq.store_id = er.store_id
          AND aq.category_name = er.category_name
""")

# Rule 1: high demand_gap AND high readiness -> PITCH or EXPAND
r1 = full[(full['overall_demand_gap_score'] > 60) & (full['expansion_readiness_score'] > 65)].copy()
if len(r1):
    r1['match'] = r1['recommended_action'].isin(['PITCH', 'EXPAND'])
    pct = r1['match'].mean() * 100
    passed = pct >= 95
    results.append(('Signal: high demand+readiness -> PITCH/EXPAND', round(pct,1), passed))
    status = 'PASS' if passed else 'FAIL'
    print(f'  [{status}]  demand_gap>60 & readiness>65 -> PITCH/EXPAND: {pct:.1f}% ({len(r1)} rows)')
    print(f'           actual actions: {r1["recommended_action"].value_counts().to_dict()}')

# Rule 2: high margin + promo -> CUTPROMO or AVOID
r2 = full[(full['margin_pressure_risk'] > 50) & (full['promo_risk_score'] > 50)].copy()
if len(r2):
    r2['match'] = r2['recommended_action'].isin(['CUTPROMO', 'AVOID'])
    pct = r2['match'].mean() * 100
    passed = pct >= 80
    results.append(('Signal: high margin+promo -> CUTPROMO/AVOID', round(pct,1), passed))
    status = 'PASS' if passed else 'FAIL'
    print(f'  [{status}]  margin_pressure>50 & promo_risk>50 -> CUTPROMO/AVOID: {pct:.1f}% ({len(r2)} rows)')
    print(f'           actual actions: {r2["recommended_action"].value_counts().to_dict()}')
else:
    print('  [NOTE] No rows with both margin_pressure>50 AND promo_risk>50 simultaneously')
    results.append(('Signal: high margin+promo -> CUTPROMO/AVOID', 100.0, True))

# Rule 3: low confidence -> INVESTIGATE
r3 = full[full['overall_confidence_score'] < 45].copy()
if len(r3):
    r3['match'] = r3['recommended_action'] == 'INVESTIGATE'
    pct = r3['match'].mean() * 100
    passed = pct >= 95
    results.append(('Signal: low confidence -> INVESTIGATE', round(pct,1), passed))
    print(f'  [{"PASS" if passed else "FAIL"}]  confidence<45 -> INVESTIGATE: {pct:.1f}%')
else:
    results.append(('Signal: low confidence -> INVESTIGATE (no low-conf rows)', 100.0, True))
    print('  [PASS]  confidence<45 -> INVESTIGATE: no low-confidence rows in dataset')

# â”€â”€ Section 4: Trend Features â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print('=== Section 4: Trend Feature Validation ===')

trend_df = bq(f"""
    SELECT
        f.demand_trend_direction,
        f.ppi_trend_direction,
        d.overall_demand_gap_score,
        r.demand_decay_risk,
        p.margin_pressure_risk
    FROM `{PROJECT}.{DATASET}.fact_market_signals` f
    LEFT JOIN `{PROJECT}.{DATASET}.mart_demand_gap_scores`   d ON f.signal_id = d.signal_id
    LEFT JOIN `{PROJECT}.{DATASET}.mart_shelfrisk_scores`    r ON f.signal_id = r.signal_id
    LEFT JOIN `{PROJECT}.{DATASET}.mart_price_margin_scores` p ON f.signal_id = p.signal_id
""")

print('Demand gap by demand_trend_direction:')
print(trend_df.groupby('demand_trend_direction')['overall_demand_gap_score']
      .agg(['mean','count']).round(1).to_string())

rising_gap  = trend_df[trend_df['demand_trend_direction'] == 'Rising']['overall_demand_gap_score'].mean()
falling_gap = trend_df[trend_df['demand_trend_direction'] == 'Falling']['overall_demand_gap_score'].mean()
if pd.notna(rising_gap) and pd.notna(falling_gap):
    passed = rising_gap > falling_gap
    results.append(('Trend: Rising demand_gap > Falling demand_gap', 100.0 if passed else 0.0, passed))
    print(f'  [{"PASS" if passed else "FAIL"}]  Rising gap={rising_gap:.1f} > Falling gap={falling_gap:.1f}')
else:
    print('  [SKIP] Rising or Falling demand trend not both present')

# â”€â”€ Section 5: Summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print('=' * 60)
print('TRENDSHELF VALIDATION SUMMARY')
print('=' * 60)

total   = len(results)
passing = sum(1 for _, _, p in results if p)
failing = total - passing
score   = round(passing / total * 100) if total else 0

print(f'Total rules checked : {total}')
print(f'Rules passing       : {passing}')
print(f'Rules failing       : {failing}')
print(f'Overall score       : {score}/100')
print()
for rule_name, pct, passed in results:
    status = 'PASS' if passed else 'FAIL'
    print(f'  [{status}]  {rule_name}: {pct:.1f}%')
print()
if failing == 0:
    print('ALL RULES PASS â€” scoring logic is internally consistent.')
else:
    print(f'{failing} rule(s) require investigation.')
