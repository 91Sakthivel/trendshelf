import os, sys

# Ensure project root is on the path so `from config import ...` works
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import PROJECT_ID, DATASET, CREDENTIALS_PATH, WALMART_DFW_STORE_ID, TOTAL_DBT_MODELS

# ── Dashboard deployment constants ─────────────────────────────────────────────
# (re-exported so app.py only imports from dashboard.config)

# ── Pricing intelligence action colors ────────────────────────────────────────
COLORS = {
    "Investigate":    "#EF4444",
    "Avoid Discount": "#F97316",
    "Review Price Reduction": "#F59E0B",
    "Hold Premium":           "#8B5CF6",
    "Review Price Increase":  "#10B981",
    "Protect Price":  "#3B82F6",
    "Monitor":        "#6B7280",
}

# ── Action queue action colors (mart_action_queue uses ALL-CAPS) ──────────────
ACTION_QUEUE_COLORS = {
    "AVOID":       "#EF4444",
    "INVESTIGATE": "#EF4444",
    "EXPAND":      "#10B981",
    "DEFEND":      "#F97316",
    "PITCH":       "#8B5CF6",
    "REPRICE":     "#F59E0B",
    "CUTPROMO":    "#F59E0B",
    "MONITOR":     "#6B7280",
}

CONFIDENCE_COLORS = {
    "High":     "#10B981",
    "Medium":   "#F59E0B",
    "Low":      "#EF4444",
    "Strong":   "#10B981",
    "Moderate": "#F59E0B",
    "Weak":     "#EF4444",
}

BADGE_COLORS = {
    "High":    "#10B981",
    "Medium":  "#3B82F6",
    "Low":     "#F59E0B",
    "Missing": "#EF4444",
}

OPPORTUNITY_TIER_COLORS = {
    "Prime": "#10B981",
    "Solid": "#3B82F6",
    "Watch": "#F59E0B",
    "Low":   "#6B7280",
}

LIFECYCLE_COLORS = {
    "Growth Accelerating": "#3B82F6",
    "Growth Slowing":      "#F59E0B",
    "Emerging":            "#10B981",
    "Mature":              "#6B7280",
    "Declining":           "#EF4444",
}

INTENSITY_COLORS = {
    "Saturated":  "#EF4444",
    "Competitive":"#F59E0B",
    "Emerging":   "#10B981",
    "Sparse":     "#6B7280",
}

MACRO_RISK_COLORS = {
    "High Inflation Risk": "#EF4444",
    "Cost Pressure":       "#F59E0B",
    "Cost Relief":         "#10B981",
    "Stable Macro":        "#6B7280",
}

VELOCITY_COLORS = {
    "Accelerating":   "#10B981",
    "Decelerating":   "#EF4444",
    "Stable Velocity":"#6B7280",
}
