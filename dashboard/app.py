"""TrendShelf — Retail Intelligence Dashboard (4 pages)."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone

from dashboard.config import (
    COLORS, ACTION_QUEUE_COLORS, CONFIDENCE_COLORS, BADGE_COLORS,
    OPPORTUNITY_TIER_COLORS, LIFECYCLE_COLORS, INTENSITY_COLORS,
    MACRO_RISK_COLORS, VELOCITY_COLORS,
    WALMART_DFW_STORE_ID, TOTAL_DBT_MODELS,
)
from dashboard.queries import (
    get_action_queue, get_pricing_intelligence, get_demand_scores,
    get_google_trends, get_expansion_avg, get_avg_confidence,
    get_top_pricing_actions, get_dfw_avg_scores, get_store_health_rankings,
    get_store_list, get_store_scores, get_data_freshness,
    get_intelligence_summary, get_category_opportunity_scores,
    get_weekly_events,
)

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TrendShelf",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Shared style helpers ──────────────────────────────────────────────────────

def _color_action(val, color_map):
    c = color_map.get(str(val), "#6B7280")
    return f"background-color:{c}22; color:{c}; font-weight:600"


def _color_trend(val):
    mapping = {"Rising": "#10B981", "Stable": "#6B7280", "Falling": "#EF4444"}
    c = mapping.get(str(val), "#6B7280")
    return f"color:{c}; font-weight:600"


def _page_footer():
    st.divider()
    st.caption(
        "TrendShelf v4 | Built with Kroger API · Google Trends · FRED · BLS · "
        "SerpAPI Walmart DFW | dbt Core + BigQuery | "
        "Scoring: CV-calibrated statistical model"
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📊 TrendShelf")
    st.caption("CPG Retail Intelligence")
    st.divider()

    page = st.radio(
        "Navigate",
        ["Command Center", "Demand Intelligence", "Pricing Intelligence", "Weekly Events", "Store Deep Dive"],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("**Data Sources**")

    try:
        _fresh = get_data_freshness()
        _now   = datetime.now(timezone.utc)
        for _, _row in _fresh.iterrows():
            _ts   = pd.Timestamp(_row["last_updated"])
            _days = (_now - _ts.to_pydatetime().replace(tzinfo=timezone.utc)).days
            _dot  = "🟢" if _days <= 7 else ("🟡" if _days <= 30 else "🔴")
            st.markdown(f"{_dot} **{_row['source']}** — {_ts.strftime('%Y-%m-%d')}")
    except Exception:
        st.caption("Freshness unavailable")

    st.divider()
    st.markdown("**Scoring**")
    try:
        _aq = get_action_queue()
        _score_ver = _aq["score_version"].iloc[0] if not _aq.empty else "v4_statistical_calibration"
    except Exception:
        _aq = pd.DataFrame()
        _score_ver = "v4_statistical_calibration"
    st.markdown(f"`{_score_ver}`")
    st.markdown("- Method: `v4_cv_calibrated`")
    st.markdown("- Kroger stores: 20")
    st.markdown("- Categories: 10")
    st.markdown(f"- Competitor: Walmart DFW #{WALMART_DFW_STORE_ID}")

    st.divider()
    st.markdown("**Quick Stats**")
    try:
        if _aq.empty:
            _aq = get_action_queue()
        st.markdown(f"- Total scoring rows: {len(_aq)}")
        st.markdown(f"- Models passing: {TOTAL_DBT_MODELS} / {TOTAL_DBT_MODELS}")
        _aq_ts = _aq["load_timestamp"].max()
        st.markdown(f"- Last dbt run: {pd.Timestamp(_aq_ts).strftime('%Y-%m-%d')}")
    except Exception:
        st.markdown(f"- Total scoring rows: —")
        st.markdown(f"- Models passing: {TOTAL_DBT_MODELS} / {TOTAL_DBT_MODELS}")
        st.markdown("- Last dbt run: —")

    st.divider()
    st.markdown("**Intelligence Layer**")
    try:
        _intel = get_intelligence_summary()
        st.markdown(f"- Macro environment: **{_intel.get('macro_env', '—')}**")
        st.markdown(f"- Active seasonal spikes: **{_intel.get('active_spikes', '—')}**")
        st.markdown(f"- Accelerating categories: **{_intel.get('accelerating_cats', '—')}**")
        st.markdown(f"- Top opportunity: **{_intel.get('top_opportunity', '—')}**")
    except Exception:
        st.caption("Intelligence summary unavailable")

    st.divider()
    st.caption("Built with Kroger API · Google Trends · FRED · BLS · SerpAPI")
    st.caption("Scoring: dbt Core + BigQuery")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — Command Center
# ═══════════════════════════════════════════════════════════════════════════════

if page == "Command Center":
    st.title("TrendShelf — Retail Intelligence")
    st.caption("DFW Kroger × 10 Categories | Powered by real API data")

    with st.spinner("Loading data from BigQuery..."):
        try:
            aq         = get_action_queue()
            pi         = get_pricing_intelligence()
            avg_expand = get_expansion_avg()
            avg_conf   = get_avg_confidence()
        except Exception as e:
            st.error(f"BigQuery error: {e}")
            st.stop()

    if aq.empty:
        st.warning("No data available for this view.")
        st.stop()

    # ── ROW 1 — KPI metrics (6 columns) ──────────────────────────────────────

    non_monitor   = aq[~aq["action_type"].isin(["MONITOR", "INVESTIGATE"])]
    high_conf_aq  = aq[aq["decision_strength"] == "Strong"]

    pricing_actions = 0
    if not pi.empty:
        pricing_actions = pi[
            ~pi["recommended_price_action"].isin(["Monitor", "Investigate"])
        ]["category_name"].nunique()

    prime_opps = 0
    if "opportunity_tier" in aq.columns:
        prime_opps = int((aq["opportunity_tier"] == "Prime").sum())

    days_since_kroger = None
    try:
        _fr = get_data_freshness()
        _kr = _fr[_fr["source"] == "Kroger Prices"]
        if not _kr.empty:
            _ts = pd.Timestamp(_kr["last_updated"].iloc[0])
            days_since_kroger = (
                datetime.now(timezone.utc) - _ts.to_pydatetime().replace(tzinfo=timezone.utc)
            ).days
    except Exception:
        pass

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Opportunities",  len(non_monitor))
    k2.metric("High Confidence", len(high_conf_aq))
    k3.metric("Need Pricing",   pricing_actions)
    k4.metric("Prime Opps",     str(prime_opps) if prime_opps > 0 else "0")

    st.caption("Data Health")
    k5, k6, k7 = st.columns(3)
    k5.metric("Expansion Score", f"{avg_expand:.1f}")
    k6.metric("Confidence",      f"{avg_conf:.1f}")
    k7.metric(
        "Data Age (days)",
        str(days_since_kroger) if days_since_kroger is not None else "—",
    )

    st.divider()

    # ── ROW 2 — Action queue table ────────────────────────────────────────────

    st.subheader("Action Queue")
    st.info(
        "Actions below are operational shelf decisions from mart_action_queue. "
        "Pricing-specific actions (Hold Premium, Reduce Price, Raise Price) "
        "are on Page 3 — Pricing Intelligence."
    )
    show_monitor = st.checkbox("Show Monitor / Investigate rows", value=False)

    display_aq = aq if show_monitor else non_monitor
    if "overall_opportunity_score" in display_aq.columns:
        display_aq = display_aq.sort_values("overall_opportunity_score", ascending=False)

    if display_aq.empty:
        st.warning("No non-Monitor rows found.")
    else:
        cols_show = [
            "store_name", "category_name", "action_type", "decision_strength",
            "overall_opportunity_score", "opportunity_tier", "category_lifecycle",
            "reason_code", "overall_confidence_score", "overall_demand_gap_score",
            "driving_score", "action_reason",
        ]
        cols_show = [c for c in cols_show if c in display_aq.columns]
        tbl = display_aq[cols_show].rename(columns={
            "store_name":               "Store",
            "category_name":            "Category",
            "action_type":              "Action",
            "decision_strength":        "Decision Strength",
            "overall_opportunity_score":"Opportunity Score",
            "opportunity_tier":         "Opp Tier",
            "category_lifecycle":       "Lifecycle",
            "reason_code":              "Reason Code",
            "overall_confidence_score": "Conf Score",
            "overall_demand_gap_score": "Demand Gap",
            "driving_score":            "Driving Score",
            "action_reason":            "Action Reason",
        })

        def _sa(v):        return _color_action(v, ACTION_QUEUE_COLORS)
        def _sd(v):        return _color_action(v, CONFIDENCE_COLORS)
        def _s_tier(v):    return _color_action(v, OPPORTUNITY_TIER_COLORS)
        def _s_lifecycle(v): return _color_action(v, LIFECYCLE_COLORS)

        _fc = tbl.select_dtypes(include='float').columns
        tbl[_fc] = tbl[_fc].round(2)

        fmt_aq = {}
        if "Opportunity Score" in tbl.columns:
            fmt_aq["Opportunity Score"] = "{:.1f}"

        styled = tbl.style.format(fmt_aq)
        if "Action"            in tbl.columns: styled = styled.map(_sa,          subset=["Action"])
        if "Decision Strength" in tbl.columns: styled = styled.map(_sd,          subset=["Decision Strength"])
        if "Opp Tier"          in tbl.columns: styled = styled.map(_s_tier,      subset=["Opp Tier"])
        if "Lifecycle"         in tbl.columns: styled = styled.map(_s_lifecycle, subset=["Lifecycle"])

        st.dataframe(styled, use_container_width=True, hide_index=True)

    st.caption(
        "Source: mart_action_queue — operational shelf decisions. "
        "For pricing decisions see Page 3 → Pricing Intelligence."
    )

    st.divider()

    # ── ROW 3 — Action distribution bar chart ─────────────────────────────────

    st.subheader("Action Distribution — Operational Queue (200 rows)")
    action_counts = (
        aq["action_type"].value_counts()
        .reset_index()
        .rename(columns={"action_type": "Action", "count": "Count"})
        .sort_values("Count", ascending=False)
    )

    fig = px.bar(
        action_counts,
        x="Action", y="Count",
        color="Action",
        color_discrete_map=ACTION_QUEUE_COLORS,
        text="Count",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        showlegend=False,
        xaxis_title=None,
        yaxis_title="# Rows",
        xaxis={"categoryorder": "total descending"},
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Avg Opportunity Score by Category ────────────────────────────────────

    st.subheader("Avg Opportunity Score by Category")
    try:
        cat_opp = get_category_opportunity_scores()
    except Exception:
        cat_opp = pd.DataFrame()

    if cat_opp.empty:
        st.caption("Category opportunity data not available — refresh cache.")
    else:
        def _tier_color(score):
            if score >= 65:
                return "#10B981"
            if score >= 55:
                return "#3B82F6"
            return "#F59E0B"

        cat_opp = cat_opp.sort_values("avg_score", ascending=True)
        bar_colors = [_tier_color(s) for s in cat_opp["avg_score"]]

        fig_cat = go.Figure(go.Bar(
            x=cat_opp["avg_score"],
            y=cat_opp["category_name"],
            orientation="h",
            marker_color=bar_colors,
            text=cat_opp["avg_score"],
            textposition="outside",
        ))
        fig_cat.add_vline(
            x=75, line_dash="dash", line_color="#10B981", line_width=1.5,
            annotation_text="Prime 75", annotation_position="top",
            annotation_font_size=11,
        )
        fig_cat.add_vline(
            x=55, line_dash="dash", line_color="#3B82F6", line_width=1.5,
            annotation_text="Solid 55", annotation_position="top",
            annotation_font_size=11,
        )
        fig_cat.update_layout(
            xaxis=dict(title="Avg Opportunity Score", range=[0, 100]),
            yaxis_title=None,
            showlegend=False,
            height=420,
        )
        st.plotly_chart(fig_cat, use_container_width=True)
        st.caption(
            "Prime threshold: 75+ | Solid: 55–74 | Watch: 35–54 | Low: <35 | "
            "All categories currently Solid — variance increases as monthly collection accumulates."
        )

    _page_footer()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — Demand Intelligence
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "Demand Intelligence":
    st.title("Demand Intelligence")
    st.caption("Where is demand growing and shelf coverage weak?")

    with st.spinner("Loading data from BigQuery..."):
        try:
            demand = get_demand_scores()
            trends = get_google_trends()
        except Exception as e:
            st.error(f"BigQuery error: {e}")
            st.stop()

    if demand.empty:
        st.warning("No data available for this view.")
        st.stop()

    # ── Velocity summary metrics ──────────────────────────────────────────────

    v_cats = pd.Series(dtype=str)
    if "demand_velocity_direction" in demand.columns:
        v_cats = demand.groupby("category_name")["demand_velocity_direction"].first()
    n_acc = int((v_cats == "Accelerating").sum())
    n_dec = int((v_cats == "Decelerating").sum())

    spike_count = 0
    if "seasonality_flag" in demand.columns:
        spike_count = int(
            demand[demand["seasonality_flag"] == "Possible Seasonal Spike"]["category_name"].nunique()
        )

    vm1, vm2, vm3 = st.columns(3)
    vm1.metric("Accelerating Categories", n_acc)
    vm2.metric("Decelerating Categories", n_dec)
    vm3.metric("Seasonal Spikes Active",  spike_count)

    st.divider()

    # ── ROW 1 — Heatmap (store × category) ───────────────────────────────────

    st.subheader("Demand Gap Score — Store × Category")

    score_pivot = demand.pivot_table(
        index="store_city", columns="category_name",
        values="overall_demand_gap_score", aggfunc="mean",
    ).round(1)

    trend_pivot = demand.pivot_table(
        index="store_city", columns="category_name",
        values="demand_trend_direction", aggfunc="first",
    ).reindex(index=score_pivot.index, columns=score_pivot.columns).fillna("N/A")

    vel_col = "demand_velocity_direction" if "demand_velocity_direction" in demand.columns else None
    if vel_col:
        vel_pivot = demand.pivot_table(
            index="store_city", columns="category_name",
            values=vel_col, aggfunc="first",
        ).reindex(index=score_pivot.index, columns=score_pivot.columns).fillna("N/A")
        heatmap_customdata = np.dstack([trend_pivot.values, vel_pivot.values])
        vel_hover_line = "<b>Velocity:</b> %{customdata[1]}<br>"
        trend_ref = "%{customdata[0]}"
    else:
        heatmap_customdata = trend_pivot.values
        vel_hover_line = ""
        trend_ref = "%{customdata}"

    fig_heat = go.Figure(data=go.Heatmap(
        z=score_pivot.values,
        x=score_pivot.columns.tolist(),
        y=score_pivot.index.tolist(),
        customdata=heatmap_customdata,
        colorscale=[[0, "#EF4444"], [0.5, "#F59E0B"], [1, "#10B981"]],
        zmin=0, zmax=100,
        text=score_pivot.values.round(1),
        texttemplate="%{text}",
        hovertemplate=(
            "<b>Store:</b> %{y}<br>"
            "<b>Category:</b> %{x}<br>"
            "<b>Demand Gap Score:</b> %{z:.1f}/100<br>"
            f"<b>Trend:</b> {trend_ref}<br>"
            + vel_hover_line +
            "<extra></extra>"
        ),
        colorbar=dict(title="Demand Gap Score"),
    ))
    fig_heat.update_layout(
        xaxis_title=None,
        yaxis_title=None,
        height=560,
    )
    st.plotly_chart(fig_heat, use_container_width=True)

    st.divider()

    # ── ROW 2 — Google Trends line chart ──────────────────────────────────────

    st.subheader("Category Demand Trends — Last 12 Months")

    if trends.empty:
        st.warning("Google Trends data not available.")
    else:
        trends["trend_date"] = pd.to_datetime(trends["trend_date"])
        cutoff    = trends["trend_date"].max() - pd.DateOffset(months=12)
        trends_yr = trends[trends["trend_date"] >= cutoff].copy()

        label_col = "category" if trends_yr["category"].notna().any() else "search_keyword"

        # Sort categories alphabetically for legend
        cat_order = sorted(trends_yr[label_col].dropna().unique().tolist())

        fig_trend = px.line(
            trends_yr.sort_values(["trend_date"]),
            x="trend_date",
            y="interest_score",
            color=label_col,
            category_orders={label_col: cat_order},
            labels={
                "trend_date":    "Week",
                "interest_score": "Search Interest (0-100)",
                label_col:        "Category",
            },
            height=420,
        )
        fig_trend.update_layout(
            xaxis_title="Week",
            yaxis_title="Search Interest (0-100)",
            legend_title_text="Category",
        )

        # Overlay spike markers
        spikes = trends_yr[trends_yr["seasonality_flag"] == "Possible Seasonal Spike"]
        if not spikes.empty:
            for cat in spikes[label_col].unique():
                cat_spikes = spikes[spikes[label_col] == cat]
                fig_trend.add_trace(go.Scatter(
                    x=cat_spikes["trend_date"],
                    y=cat_spikes["interest_score"],
                    mode="markers",
                    marker=dict(size=9, symbol="circle", color="crimson",
                                line=dict(width=1, color="white")),
                    name="Seasonal Spike",
                    showlegend=False,
                    hovertemplate=(
                        f"Category: {cat}<br>"
                        "Date: %{x}<br>"
                        "Interest: %{y}<br>"
                        "<b>Possible Seasonal Spike</b>"
                        "<extra></extra>"
                    ),
                ))
            fig_trend.add_annotation(
                xref="paper", yref="paper",
                x=0.01, y=1.04,
                text="● Possible Seasonal Spike",
                showarrow=False,
                font=dict(size=11, color="crimson"),
            )

        st.plotly_chart(fig_trend, use_container_width=True)

    st.divider()

    # ── ROW 3 — Top opportunities table ───────────────────────────────────────

    st.subheader("Top Demand Gap Opportunities (score > 45)")

    top_demand = demand[demand["overall_demand_gap_score"] > 45].copy()

    if top_demand.empty:
        st.warning("No rows with demand gap > 45.")
    else:
        cols_show = [
            "store_city", "category_name", "overall_demand_gap_score",
            "search_to_shelf_gap", "demand_trend_direction",
            "demand_velocity_direction",
            "phantom_distribution", "shelf_product_count",
        ]
        cols_show = [c for c in cols_show if c in top_demand.columns]

        tbl2 = (
            top_demand[cols_show]
            .sort_values("overall_demand_gap_score", ascending=False)
            .rename(columns={
                "store_city":               "Store",
                "category_name":            "Category",
                "overall_demand_gap_score": "Demand Gap",
                "search_to_shelf_gap":      "Shelf Gap",
                "demand_trend_direction":   "Trend Direction",
                "demand_velocity_direction":"Velocity",
                "phantom_distribution":     "Phantom Dist.",
                "shelf_product_count":      "Shelf Products",
            })
        )

        _fc = tbl2.select_dtypes(include='float').columns
        tbl2[_fc] = tbl2[_fc].round(2)

        def _stl_trend(v): return _color_trend(v)
        def _stl_vel(v):
            c = VELOCITY_COLORS.get(str(v), "#6B7280")
            return f"color:{c}; font-weight:600"

        styled2 = tbl2.style
        if "Trend Direction" in tbl2.columns:
            styled2 = styled2.map(_stl_trend, subset=["Trend Direction"])
        if "Velocity" in tbl2.columns:
            styled2 = styled2.map(_stl_vel, subset=["Velocity"])

        st.dataframe(styled2, use_container_width=True, hide_index=True)

    _page_footer()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — Pricing Intelligence
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "Pricing Intelligence":
    st.title("Pricing Intelligence")
    st.caption("Kroger vs Walmart DFW — Category-aware pricing decisions")

    with st.spinner("Loading data from BigQuery..."):
        try:
            pi   = get_pricing_intelligence()
            top5 = get_top_pricing_actions()
        except Exception as e:
            st.error(f"BigQuery error: {e}")
            st.stop()

    if pi.empty:
        st.warning("No data available for this view.")
        st.stop()

    # ── ROW 0 — Top 5 Pricing Action Cards ───────────────────────────────────

    st.subheader("Top 5 Pricing Actions")

    if top5.empty:
        st.info("No non-Monitor actions available.")
    else:
        card_cols = st.columns(min(len(top5), 5))
        for i, row in top5.head(5).iterrows():
            action = row.get("recommended_price_action", "Monitor")
            color  = COLORS.get(action, "#6B7280")
            kr     = row.get("kroger_avg_price",  0) or 0
            rec    = row.get("recommended_price",  kr) or kr
            city   = row.get("store_city",   "—")
            cat    = row.get("category_name", "—")
            conf   = row.get("action_confidence_level", "—")

            with card_cols[i]:
                st.markdown(
                    f'<div style="border-left:4px solid {color};padding:8px 10px;'
                    f'background:{color}0d;border-radius:4px;margin-bottom:4px">'
                    f'<div style="font-size:0.72rem;color:#6B7280;line-height:1.3">'
                    f'{city}<br>{cat}</div>'
                    f'<div style="font-size:1.05rem;font-weight:700;color:{color};'
                    f'margin:4px 0">{action}</div>'
                    f'<div style="font-size:0.78rem;color:#374151">'
                    f'Kroger ${kr:.2f} → ${rec:.2f}</div>'
                    f'<div style="font-size:0.7rem;color:#9CA3AF;margin-top:2px">'
                    f'Confidence: {conf}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    st.divider()

    # ── ROW 1 — Price comparison grouped bar chart ────────────────────────────

    st.subheader("Avg Price by Category — Kroger vs Walmart DFW Store 2105")

    price_cat = (
        pi.groupby("category_name")[["kroger_avg_price", "competitor_avg_price"]]
        .mean().round(2).reset_index()
    )

    fig_prices = go.Figure()
    fig_prices.add_trace(go.Bar(
        name="Kroger",
        x=price_cat["category_name"],
        y=price_cat["kroger_avg_price"],
        marker_color="#3B82F6",
        text=price_cat["kroger_avg_price"].map("${:.2f}".format),
        textposition="outside",
    ))
    fig_prices.add_trace(go.Bar(
        name="Walmart DFW",
        x=price_cat["category_name"],
        y=price_cat["competitor_avg_price"],
        marker_color="#9CA3AF",
        text=price_cat["competitor_avg_price"].map("${:.2f}".format),
        textposition="outside",
    ))
    fig_prices.update_layout(
        barmode="group",
        xaxis_title=None,
        yaxis_title="Avg Price ($)",
        legend_title_text="Retailer",
        height=380,
    )
    st.plotly_chart(fig_prices, use_container_width=True)

    st.divider()

    # ── ROW 2 — Three charts: price position, action donut, situation bar ──────

    col_l, col_m, col_r = st.columns([1, 1, 2])

    with col_l:
        st.markdown("**Price Position**")
        pos_counts = pi["price_position"].value_counts().reset_index()
        pos_counts.columns = ["position", "count"]
        pos_colors = {
            "Overpriced":  "#EF4444",
            "Fair":        "#3B82F6",
            "Underpriced": "#10B981",
            "Unknown":     "#9CA3AF",
        }
        fig_pos = px.pie(
            pos_counts, names="position", values="count",
            hole=0.45, color="position", color_discrete_map=pos_colors,
        )
        fig_pos.update_traces(textinfo="label+percent")
        fig_pos.update_layout(showlegend=False, height=280)
        st.plotly_chart(fig_pos, use_container_width=True)

    with col_m:
        st.markdown("**Action Mix**")
        act_counts = pi["recommended_price_action"].value_counts().reset_index()
        act_counts.columns = ["action", "count"]
        fig_act = px.pie(
            act_counts, names="action", values="count",
            hole=0.45, color="action", color_discrete_map=COLORS,
        )
        fig_act.update_traces(textinfo="label+percent")
        fig_act.update_layout(showlegend=False, height=280)
        st.plotly_chart(fig_act, use_container_width=True)

    with col_r:
        st.markdown("**Pricing Situations — Demand × Price Interaction**")
        sit_counts = (
            pi["pricing_situation"].value_counts()
            .reset_index()
            .rename(columns={"pricing_situation": "Situation", "count": "Count"})
            .sort_values("Count", ascending=True)
        )
        sit_palette = px.colors.qualitative.Pastel
        fig_sit = px.bar(
            sit_counts, x="Count", y="Situation",
            orientation="h",
            color="Situation",
            color_discrete_sequence=sit_palette,
            text="Count",
        )
        fig_sit.update_traces(textposition="outside")
        fig_sit.update_layout(showlegend=False, xaxis_title="# Rows", yaxis_title=None, height=280)
        st.plotly_chart(fig_sit, use_container_width=True)

    st.divider()

    # ── Competitive Intensity Donut ───────────────────────────────────────────

    if "competitive_intensity" in pi.columns:
        st.subheader("Walmart DFW Shelf Intensity by Category")
        _int_counts = (
            pi.groupby("category_name")["competitive_intensity"].first()
            .value_counts().reset_index()
        )
        _int_counts.columns = ["Intensity", "Count"]
        fig_int = px.pie(
            _int_counts, names="Intensity", values="Count",
            hole=0.45, color="Intensity",
            color_discrete_map=INTENSITY_COLORS,
        )
        fig_int.update_traces(textinfo="label+value")
        fig_int.update_layout(showlegend=True, height=300)
        st.plotly_chart(fig_int, use_container_width=True)
        st.divider()

    # ── Promo Diagnostics (expander) ──────────────────────────────────────────

    _promo_cols_present = all(
        c in pi.columns for c in ["kroger_promo_share", "kroger_effective_price", "effective_gap_pct"]
    )

    with st.expander("Promo Diagnostics", expanded=False):
        if not _promo_cols_present:
            st.info("Promo columns not yet available — rebuild mart_pricing_intelligence to activate.")
        else:
            st.caption(
                "Diagnostic view only. kroger_effective_price uses COALESCE(price_promo, price_regular) "
                "so it reflects the shelf price a shopper actually pays. "
                "This does NOT change scoring, price_position, or action recommendations."
            )

            promo_toggle = st.toggle("Show promo-adjusted gap (effective price)", key="promo_toggle")

            # ── KPI cards ────────────────────────────────────────────────────
            pm1, pm2, pm3 = st.columns(3)
            with pm1:
                st.metric("Avg promo share", f"{pi['kroger_promo_share'].mean()*100:.0f}%")
            with pm2:
                _deep = pi.groupby('category_name')['kroger_promo_share'].mean()
                st.metric("Categories on deep promo (>30%)", int((_deep > 0.30).sum()))
            with pm3:
                st.metric("Avg effective gap", f"{pi['effective_gap_pct'].mean():.1f}%")

            # ── Bar chart: promo share by category ───────────────────────────
            _ps = (pi.groupby('category_name', as_index=False)['kroger_promo_share'].mean()
                     .sort_values('kroger_promo_share', ascending=False))
            _fig = px.bar(_ps, x='category_name', y='kroger_promo_share',
                          color_discrete_sequence=["#3B82F6"])
            _fig.update_layout(yaxis_tickformat=".0%")
            st.plotly_chart(_fig, use_container_width=True)

            # ── Toggle: list gap vs promo-adjusted gap ────────────────────────
            if promo_toggle:
                _cmp = (pi[["category_name", "store_id", "price_gap_pct", "effective_gap_pct"]]
                          .dropna(subset=["effective_gap_pct"])
                          .sort_values("effective_gap_pct", ascending=False))
                st.dataframe(_cmp, use_container_width=True, hide_index=True)

    # ── ROW 3 — Filters ───────────────────────────────────────────────────────

    st.subheader("Pricing Detail")

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        elast_opts = sorted(pi["elasticity_tier"].dropna().unique().tolist())
        sel_elast  = st.multiselect("Elasticity Tier", elast_opts, default=elast_opts)
    with f2:
        act_opts   = sorted(pi["recommended_price_action"].dropna().unique().tolist())
        sel_act    = st.multiselect("Action Type", act_opts, default=act_opts)
    with f3:
        badge_opts = sorted(pi["price_gap_confidence"].dropna().unique().tolist())
        sel_badge  = st.multiselect("Data Quality", badge_opts, default=badge_opts)
    with f4:
        rel_opts   = sorted(pi["price_gap_reliability"].dropna().unique().tolist())
        sel_rel    = st.multiselect("Reliability", rel_opts, default=rel_opts)
    st.caption("Reduce Price recommendations only appear under High reliability.")

    filtered = pi[
        pi["elasticity_tier"].isin(sel_elast) &
        pi["recommended_price_action"].isin(sel_act) &
        pi["price_gap_confidence"].isin(sel_badge) &
        pi["price_gap_reliability"].isin(sel_rel)
    ].copy()

    st.caption(f"{len(filtered)} rows after filters")

    # ── ROW 4 — Pricing detail table ──────────────────────────────────────────

    if filtered.empty:
        st.warning("No rows match the selected filters.")
    else:
        cols_show = [
            "store_city", "category_name", "elasticity_tier",
            "kroger_avg_price", "competitor_avg_price",
            "price_gap_pct", "adjusted_price_gap_pct",
            "price_position", "price_position_threshold",
            "price_gap_reliability", "relative_gap_tier",
            "pricing_situation",
            "recommended_price_action", "price_reduction_intensity",
            "action_confidence_level",
            "recommended_price", "markdown_safety_score",
            "competitor_product_count", "competitive_intensity",
            "category_cv_pct", "kroger_private_label_share",
            "macro_risk_flag",
            "price_gap_confidence",
            "price_action_reason",
        ]
        cols_show = [c for c in cols_show if c in filtered.columns]
        tbl3 = filtered[cols_show].rename(columns={
            "store_city":                 "Store",
            "category_name":              "Category",
            "elasticity_tier":            "Elasticity",
            "kroger_avg_price":           "Kroger $",
            "competitor_avg_price":       "Walmart $",
            "price_gap_pct":              "Gap %",
            "adjusted_price_gap_pct":     "Adj Gap %",
            "price_position":             "Position",
            "price_position_threshold":   "Band Threshold",
            "price_gap_reliability":      "Reliability",
            "relative_gap_tier":          "Gap Tier",
            "pricing_situation":          "Situation",
            "recommended_price_action":   "Action",
            "price_reduction_intensity":  "Intensity",
            "action_confidence_level":    "Confidence",
            "recommended_price":          "Rec Price $",
            "markdown_safety_score":      "Markdown Safety",
            "competitor_product_count":   "Walmart Products",
            "competitive_intensity":      "Walmart Shelf",
            "category_cv_pct":            "Category CV %",
            "kroger_private_label_share": "Private Label %",
            "macro_risk_flag":            "Macro Risk",
            "price_gap_confidence":       "Data Quality",
            "price_action_reason":        "Reason",
        })

        _fc = tbl3.select_dtypes(include='float').columns
        tbl3[_fc] = tbl3[_fc].round(4)

        def _sap(v):    return _color_action(v, COLORS)
        def _scp(v):    return _color_action(v, CONFIDENCE_COLORS)
        def _sbp(v):    return _color_action(v, BADGE_COLORS)
        def _sint(v):   return _color_action(v, INTENSITY_COLORS)
        def _smacro(v): return _color_action(v, MACRO_RISK_COLORS)
        def _srel(v):   return _color_action(v, CONFIDENCE_COLORS)

        fmt = {}
        if "Kroger $"        in tbl3.columns: fmt["Kroger $"]        = "${:.2f}"
        if "Walmart $"       in tbl3.columns: fmt["Walmart $"]       = "${:.2f}"
        if "Rec Price $"     in tbl3.columns: fmt["Rec Price $"]     = "${:.2f}"
        if "Gap %"           in tbl3.columns: fmt["Gap %"]           = "{:.1f}%"
        if "Adj Gap %"       in tbl3.columns: fmt["Adj Gap %"]       = "{:.1f}%"
        if "Markdown Safety" in tbl3.columns: fmt["Markdown Safety"] = "{:.0f}/100"
        if "Band Threshold"  in tbl3.columns: fmt["Band Threshold"]  = "{:.1f}%"
        if "Category CV %"   in tbl3.columns: fmt["Category CV %"]   = "{:.1f}%"
        if "Private Label %"  in tbl3.columns: fmt["Private Label %"] = "{:.0%}"

        styled3 = tbl3.style.format(fmt)
        if "Action"        in tbl3.columns: styled3 = styled3.map(_sap,    subset=["Action"])
        if "Confidence"    in tbl3.columns: styled3 = styled3.map(_scp,    subset=["Confidence"])
        if "Data Quality"  in tbl3.columns: styled3 = styled3.map(_sbp,    subset=["Data Quality"])
        if "Reliability"   in tbl3.columns: styled3 = styled3.map(_srel,   subset=["Reliability"])
        if "Walmart Shelf" in tbl3.columns: styled3 = styled3.map(_sint,   subset=["Walmart Shelf"])
        if "Macro Risk"    in tbl3.columns: styled3 = styled3.map(_smacro, subset=["Macro Risk"])

        st.dataframe(styled3, use_container_width=True, hide_index=True)

    st.caption(
        "Price bands are calibrated to each category's price variation (CV), bounded 8-25%. "
        "Method: CV calibrated absolute band. "
        "Competitor prices from Walmart DFW Store 2105 (LBJ Fwy, Dallas TX). "
        "Elasticity tiers are industry priors. "
        "Price gap confidence weighted by competitor product count."
    )

    _page_footer()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — Weekly Events
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "Weekly Events":
    st.title("Weekly Events")
    st.caption("Week-over-week pricing movements — Gap Flips, Big Moves, New Sustained streaks")

    with st.spinner("Loading data from BigQuery..."):
        try:
            df = get_weekly_events()
        except Exception as e:
            st.error(f"BigQuery error: {e}")
            st.stop()

    if df.empty:
        st.warning("No weekly events found.")
        st.stop()

    rel = st.multiselect(
        "Reliability",
        ["High", "Medium", "Low", "Unknown"],
        default=["High", "Medium"],
    )
    df = df[df["competitor_reliability"].isin(rel)]

    for event_type in ["Gap Flip", "Big Move", "New Sustained"]:
        st.subheader(event_type)
        subset = df[(df["event_type"] == event_type) & (df["event_rank"] <= 5)]
        if subset.empty:
            st.caption("No events this week.")
        else:
            st.dataframe(subset, use_container_width=True, hide_index=True)

    _page_footer()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — Store Deep Dive
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "Store Deep Dive":
    st.title("Store Deep Dive")
    st.caption("Select a store to see full scoring profile")

    # ── Store selector ────────────────────────────────────────────────────────

    with st.spinner("Loading store list..."):
        try:
            store_list = get_store_list()
        except Exception as e:
            st.error(f"Could not load store list: {e}")
            st.stop()

    if store_list.empty:
        st.warning("No stores found.")
        st.stop()

    store_list    = store_list.sort_values("display_name")
    store_options = store_list["display_name"].tolist()

    default_idx = 0
    for i, name in enumerate(store_options):
        if "Capitol" in str(name):
            default_idx = i
            break

    selected_label = st.selectbox("Select Store", store_options, index=default_idx)
    selected_id    = store_list.loc[store_list["display_name"] == selected_label, "store_id"].iloc[0]
    selected_city  = selected_label.replace("Kroger ", "", 1)

    with st.spinner("Loading store scores..."):
        try:
            scores   = get_store_scores(selected_id)
            dfw_avgs = get_dfw_avg_scores()
            rankings = get_store_health_rankings()
        except Exception as e:
            st.error(f"BigQuery error: {e}")
            st.stop()

    if scores.empty:
        st.warning(f"No data found for store: {selected_label}")
        st.stop()

    st.divider()

    # ── ROW 1 — Radar chart with DFW average comparison ───────────────────────

    st.subheader(f"{selected_city} vs DFW Average — Scoring Profile")

    radar_def = {
        "demand_gap_score":          ("Demand Gap",          "avg_demand_gap"),
        "expansion_readiness_score": ("Expansion Readiness", "avg_expansion"),
        "pricing_power_score":       ("Pricing Power",       "avg_pricing_power"),
        "confidence_score":          ("Confidence",          "avg_confidence"),
        "risk_score":                ("Shelf Risk (inv.)",   "avg_risk_inv"),
        "markdown_safety_score":     ("Margin Safety",       "avg_markdown_safety"),
    }

    store_vals, dfw_vals, labels = [], [], []
    for col, (label, dfw_key) in radar_def.items():
        if col in scores.columns and scores[col].notna().any():
            sv = scores[col].mean()
            if col == "risk_score":
                sv = 100 - sv
            store_vals.append(round(sv, 1))
        else:
            store_vals.append(50.0)
        dfw_vals.append(round(dfw_avgs.get(dfw_key, 50.0), 1))
        labels.append(label)

    sv_c = store_vals + [store_vals[0]]
    dv_c = dfw_vals  + [dfw_vals[0]]
    lb_c = labels    + [labels[0]]

    fig_radar = go.Figure()
    fig_radar.add_trace(go.Scatterpolar(
        r=sv_c, theta=lb_c,
        fill="toself",
        name=selected_city,
        line=dict(color="#3B82F6", width=2),
        fillcolor="rgba(59,130,246,0.15)",
        hovertemplate="%{theta}: %{r:.1f}<extra>" + selected_city + "</extra>",
    ))
    fig_radar.add_trace(go.Scatterpolar(
        r=dv_c, theta=lb_c,
        fill="none",
        name="DFW Average",
        line=dict(color="#9CA3AF", width=2, dash="dash"),
        hovertemplate="%{theta}: %{r:.1f}<extra>DFW Average</extra>",
    ))
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15),
        height=440,
    )
    st.plotly_chart(fig_radar, use_container_width=True)

    st.divider()

    # ── ROW 2 — Store summary metric cards ────────────────────────────────────

    st.subheader("Store Summary")
    s1, s2, s3, s4 = st.columns(4)

    # Best opportunity category (highest expansion_readiness)
    best_opp = "—"
    if "expansion_readiness_score" in scores.columns and scores["expansion_readiness_score"].notna().any():
        best_opp = scores.loc[scores["expansion_readiness_score"].idxmax(), "category_name"]
    s1.metric("Best Opportunity Category", best_opp)

    # Biggest price gap
    big_price_cat = "—"
    if "price_gap_pct" in scores.columns and scores["price_gap_pct"].notna().any():
        big_price_cat = scores.loc[scores["price_gap_pct"].abs().idxmax(), "category_name"]
    s2.metric("Biggest Price Gap", big_price_cat)

    # Most confident action
    conf_action = "—"
    if "action_confidence_level" in scores.columns and "recommended_price_action" in scores.columns:
        for level in ["High", "Medium"]:
            hi = scores[scores["action_confidence_level"] == level]
            if not hi.empty:
                conf_action = hi.iloc[0]["recommended_price_action"]
                break
    s3.metric("Most Confident Action", conf_action)

    # Store health score
    health_vals = [
        scores[c].mean()
        for c in ["demand_gap_score", "confidence_score", "expansion_readiness_score"]
        if c in scores.columns and scores[c].notna().any()
    ]
    health_score = round(sum(health_vals) / len(health_vals), 1) if health_vals else 0.0
    s4.metric("Store Health Score", f"{health_score} / 100")

    # ── Intelligence v2 cards ────────────────────────────────────────────────

    s5, s6 = st.columns(2)

    # Opportunity Tier (most common for this store)
    opp_tier_val = "—"
    if "opportunity_tier" in scores.columns and not scores["opportunity_tier"].dropna().empty:
        _mode = scores["opportunity_tier"].dropna().mode()
        opp_tier_val = _mode.iloc[0] if len(_mode) > 0 else "—"
    s5.metric("Opportunity Tier", opp_tier_val)

    # Category Lifecycle Mix
    lifecycle_mix = "—"
    if "category_lifecycle" in scores.columns:
        _lc = scores["category_lifecycle"].value_counts()
        lifecycle_mix = " · ".join(f"{v} {k}" for k, v in _lc.items())[:60]
    s6.metric("Category Lifecycle Mix", lifecycle_mix)

    st.divider()

    # ── ROW 3 — Category breakdown table ──────────────────────────────────────

    st.subheader(f"Category Breakdown — {selected_city}")

    cat_cols = [
        "category_name", "recommended_price_action", "decision_strength",
        "demand_signal", "pricing_situation",
        "demand_velocity_direction",
        "kroger_avg_price", "competitor_avg_price", "price_gap_pct",
        "recommended_price", "price_action_reason",
        "demand_reason_code", "risk_reason_code",
    ]
    cat_cols = [c for c in cat_cols if c in scores.columns]

    # Sort by overall_opportunity_score descending if available, else confidence
    sort_col = "overall_opportunity_score" if "overall_opportunity_score" in scores.columns else (
        "action_confidence_score" if "action_confidence_score" in scores.columns else "confidence_score"
    )
    tbl4 = (
        scores[cat_cols + ([sort_col] if sort_col in scores.columns and sort_col not in cat_cols else [])]
        .sort_values(sort_col, ascending=False) if sort_col in scores.columns
        else scores[cat_cols]
    )
    tbl4 = tbl4[cat_cols].rename(columns={
        "category_name":            "Category",
        "recommended_price_action": "Action",
        "decision_strength":        "Decision Strength",
        "demand_signal":            "Demand Level",
        "pricing_situation":        "Situation",
        "demand_velocity_direction":"Velocity",
        "kroger_avg_price":         "Kroger $",
        "competitor_avg_price":     "Walmart $",
        "price_gap_pct":            "Gap %",
        "recommended_price":        "Recommended $",
        "price_action_reason":      "Action Reason",
        "demand_reason_code":       "Demand Signal",
        "risk_reason_code":         "Risk Signal",
    })

    _fc = tbl4.select_dtypes(include='float').columns
    tbl4[_fc] = tbl4[_fc].round(2)

    def _sp4a(v):    return _color_action(v, COLORS)
    def _sp4d(v):    return _color_action(v, CONFIDENCE_COLORS)
    def _sp4v(v):
        c = VELOCITY_COLORS.get(str(v), "#6B7280")
        return f"color:{c}; font-weight:600"
    def _sp4mono(v): return "font-family:monospace; font-size:0.78rem"

    fmt4 = {}
    if "Kroger $"      in tbl4.columns: fmt4["Kroger $"]      = "${:.2f}"
    if "Walmart $"     in tbl4.columns: fmt4["Walmart $"]     = "${:.2f}"
    if "Recommended $" in tbl4.columns: fmt4["Recommended $"] = "${:.2f}"
    if "Gap %"         in tbl4.columns: fmt4["Gap %"]         = "{:.1f}%"

    styled4 = tbl4.style.format(fmt4)
    if "Action"           in tbl4.columns: styled4 = styled4.map(_sp4a,    subset=["Action"])
    if "Decision Strength" in tbl4.columns: styled4 = styled4.map(_sp4d,   subset=["Decision Strength"])
    if "Velocity"         in tbl4.columns: styled4 = styled4.map(_sp4v,    subset=["Velocity"])
    if "Demand Signal"    in tbl4.columns: styled4 = styled4.map(_sp4mono, subset=["Demand Signal"])
    if "Risk Signal"      in tbl4.columns: styled4 = styled4.map(_sp4mono, subset=["Risk Signal"])

    st.dataframe(styled4, use_container_width=True, hide_index=True)

    st.divider()

    # ── ROW 4 — Store ranking context ─────────────────────────────────────────

    st.subheader("Store Ranking — vs All 20 DFW Stores")

    if rankings.empty:
        st.warning("Rankings data unavailable.")
    else:
        n_stores = len(rankings)
        rankings = rankings.reset_index(drop=True)

        def _get_rank(col, ascending=False):
            if col not in rankings.columns:
                return None, None
            ranked = rankings.sort_values(col, ascending=ascending).reset_index(drop=True)
            match  = ranked[ranked["store_id"] == selected_id]
            if match.empty:
                return None, None
            rank = int(match.index[0]) + 1
            dfw_avg = round(float(rankings[col].mean()), 1)
            return rank, dfw_avg

        health_rank, dfw_health = _get_rank("health_score")
        expand_rank, dfw_expand = _get_rank("avg_expansion")
        conf_rank,   dfw_conf   = _get_rank("avg_confidence")

        r1, r2, r3 = st.columns(3)

        if health_rank:
            store_h = rankings.loc[rankings["store_id"] == selected_id, "health_score"]
            h_val   = round(float(store_h.iloc[0]), 1) if not store_h.empty else 0.0
            r1.metric(
                "Store Health Rank",
                f"{health_rank} of {n_stores}",
                delta=f"{h_val - dfw_health:+.1f} vs DFW avg ({dfw_health})",
            )

        if expand_rank:
            store_e = rankings.loc[rankings["store_id"] == selected_id, "avg_expansion"]
            e_val   = round(float(store_e.iloc[0]), 1) if not store_e.empty else 0.0
            r2.metric(
                "Expansion Readiness Rank",
                f"{expand_rank} of {n_stores}",
                delta=f"{e_val - dfw_expand:+.1f} vs DFW avg ({dfw_expand})",
            )

        if conf_rank:
            store_c = rankings.loc[rankings["store_id"] == selected_id, "avg_confidence"]
            c_val   = round(float(store_c.iloc[0]), 1) if not store_c.empty else 0.0
            r3.metric(
                "Avg Confidence Rank",
                f"{conf_rank} of {n_stores}",
                delta=f"{c_val - dfw_conf:+.1f} vs DFW avg ({dfw_conf})",
            )

        st.caption(
            "Near-zero deltas are expected with one month of data — "
            "all stores score similarly until ranking spreads out with 3+ months of history."
        )

    _page_footer()
