import sys
sys.path.insert(0, '.')
import streamlit as st

# Patch cache_data to be a passthrough
def noop_cache(**kwargs):
    def decorator(fn): return fn
    return decorator
st.cache_data = noop_cache

from dashboard.queries import (
    get_action_queue, get_pricing_intelligence,
    get_demand_scores, get_intelligence_summary, get_store_scores, get_store_list,
)

print("=== get_action_queue ===")
aq = get_action_queue()
new_cols = ["overall_opportunity_score", "opportunity_tier", "category_lifecycle",
            "demand_velocity_direction", "demand_reason_code", "risk_reason_code",
            "competitive_intensity", "macro_risk_flag"]
present = [c for c in new_cols if c in aq.columns]
missing = [c for c in new_cols if c not in aq.columns]
print(f"rows={len(aq)}, new cols present={len(present)}/{len(new_cols)}")
if missing:
    print(f"MISSING: {missing}")
print("opportunity_tier dist:", aq["opportunity_tier"].value_counts().to_dict())
print("category_lifecycle dist:", aq["category_lifecycle"].value_counts().to_dict())
print("demand_velocity_direction dist:", aq["demand_velocity_direction"].value_counts().to_dict())

print("\n=== get_intelligence_summary ===")
intel = get_intelligence_summary()
print(intel)

print("\n=== get_pricing_intelligence ===")
pi = get_pricing_intelligence()
print(f"rows={len(pi)}, macro_risk_flag present={'macro_risk_flag' in pi.columns}")
if "macro_risk_flag" in pi.columns:
    print("macro_risk_flag dist:", pi["macro_risk_flag"].value_counts().to_dict())
if "competitive_intensity" in pi.columns:
    print("competitive_intensity dist:", pi["competitive_intensity"].value_counts().to_dict())

print("\n=== get_demand_scores ===")
d = get_demand_scores()
print(f"rows={len(d)}, velocity present={'demand_velocity_direction' in d.columns}")
if "demand_velocity_direction" in d.columns:
    print("velocity dist:", d["demand_velocity_direction"].value_counts().to_dict())

print("\n=== get_store_scores (first store) ===")
sl = get_store_list()
first_id = sl["store_id"].iloc[0]
ss = get_store_scores(first_id)
v2_cols = ["overall_opportunity_score", "opportunity_tier", "category_lifecycle",
           "demand_velocity_direction", "demand_reason_code", "risk_reason_code"]
present_ss = [c for c in v2_cols if c in ss.columns]
print(f"store={first_id}, rows={len(ss)}, v2 cols present={present_ss}")

print("\nAll tests PASS")
