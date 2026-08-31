"""
agent/tools/marts.py -- the 3 quantitative tools.

Every function here catches its own exceptions and returns its own typed
Pydantic result with `error` populated -- never raises into a caller.
"No data for this period" (a valid, unknown-store-and-category-exist
outcome) is NOT an error: found=False, error=None, every score field None.
An unknown store_id/category IS an error: caught before the main query
runs, distinguishable from "no data" by the error field.
"""
from datetime import date
from typing import Optional

from google.cloud import bigquery

from agent import bq
from agent.schemas import (
    DataFreshnessResult,
    PriceHistoryResult,
    StoreCategoryResult,
    WeeklyPriceRow,
)
from agent.tools import validation
import config


def query_store_category(
    store_id: str, category: str, reference_month: Optional[date] = None
) -> StoreCategoryResult:
    try:
        if not validation.store_exists(store_id):
            return StoreCategoryResult(
                store_id=store_id, category=category, found=False,
                error=f"unknown store_id {store_id!r}: not present in dim_location",
            )
        if not validation.category_exists(category):
            return StoreCategoryResult(
                store_id=store_id, category=category, found=False,
                error=f"unknown category {category!r}: not present in dim_category",
            )

        params = [
            bigquery.ScalarQueryParameter("store_id", "STRING", store_id),
            bigquery.ScalarQueryParameter("category", "STRING", category),
        ]
        if reference_month is not None:
            month_filter = "AND scoring_date = @reference_month"
            order_limit = "LIMIT 1"
            params.append(
                bigquery.ScalarQueryParameter("reference_month", "DATE", reference_month)
            )
        else:
            month_filter = ""
            order_limit = "ORDER BY scoring_date DESC LIMIT 1"

        sql = f"""
            SELECT
                scoring_date, recommended_price_action, price_gap_reliability,
                price_gap_confidence, directional_signal_confidence,
                premium_support_proxy_score, markdown_safety_score,
                competitive_intensity, price_position, price_reduction_intensity,
                action_confidence_level, category_sensitivity_tier, demand_signal,
                pricing_situation, kroger_private_label_share,
                competitor_price_staleness_days
            FROM `{config.PROJECT_ID}.{config.DATASET}.mart_pricing_intelligence`
            WHERE store_id = @store_id AND category_name = @category {month_filter}
            {order_limit}
        """
        rows = bq.run_query(sql, params=params)
        if not rows:
            return StoreCategoryResult(store_id=store_id, category=category, found=False)

        r = rows[0]
        return StoreCategoryResult(
            store_id=store_id,
            category=category,
            found=True,
            data_as_of=r["scoring_date"],
            recommended_price_action=r["recommended_price_action"],
            price_gap_reliability=r["price_gap_reliability"],
            price_gap_confidence=r["price_gap_confidence"],
            directional_signal_confidence=r["directional_signal_confidence"],
            premium_support_proxy_score=r["premium_support_proxy_score"],
            markdown_safety_score=r["markdown_safety_score"],
            competitive_intensity=r["competitive_intensity"],
            price_position=r["price_position"],
            price_reduction_intensity=r["price_reduction_intensity"],
            action_confidence_level=r["action_confidence_level"],
            category_sensitivity_tier=r["category_sensitivity_tier"],
            demand_signal=r["demand_signal"],
            pricing_situation=r["pricing_situation"],
            kroger_private_label_share=r["kroger_private_label_share"],
            competitor_price_staleness_days=r["competitor_price_staleness_days"],
        )
    except Exception as e:
        return StoreCategoryResult(store_id=store_id, category=category, found=False, error=str(e))


def get_price_history(store_id: str, category: str, weeks: int = 13) -> PriceHistoryResult:
    try:
        if not validation.store_exists(store_id):
            return PriceHistoryResult(
                store_id=store_id, category=category, found=False,
                error=f"unknown store_id {store_id!r}: not present in dim_location",
            )
        if not validation.category_exists(category):
            return PriceHistoryResult(
                store_id=store_id, category=category, found=False,
                error=f"unknown category {category!r}: not present in dim_category",
            )

        sql = f"""
            SELECT
                kroger_collection_date, price_gap_pct, price_gap_direction, price_position,
                competitor_reliability, competitor_staleness_days, kroger_product_count,
                basket_mismatch_flag
            FROM `{config.PROJECT_ID}.{config.DATASET}.fct_store_category_weekly`
            WHERE store_id = @store_id AND category_name = @category
            ORDER BY kroger_collection_date DESC
            LIMIT @weeks
        """
        rows = bq.run_query(
            sql,
            params=[
                bigquery.ScalarQueryParameter("store_id", "STRING", store_id),
                bigquery.ScalarQueryParameter("category", "STRING", category),
                bigquery.ScalarQueryParameter("weeks", "INT64", weeks),
            ],
        )
        weekly_rows = [WeeklyPriceRow(**dict(r)) for r in rows]
        return PriceHistoryResult(
            store_id=store_id, category=category, found=len(weekly_rows) > 0, rows=weekly_rows
        )
    except Exception as e:
        return PriceHistoryResult(store_id=store_id, category=category, found=False, error=str(e))


def check_data_freshness() -> DataFreshnessResult:
    try:
        sql = f"""
            SELECT
                COUNT(DISTINCT CONCAT(
                    CAST(kroger_hours_ago AS STRING), '|', CAST(fred_hours_ago AS STRING), '|',
                    CAST(bls_hours_ago AS STRING), '|', CAST(serpapi_hours_ago AS STRING), '|',
                    CAST(trends_hours_ago AS STRING), '|', CAST(source_count AS STRING), '|',
                    CAST(collection_recency_score AS STRING)
                )) AS distinct_combos,
                ANY_VALUE(kroger_hours_ago) AS kroger_hours_ago,
                ANY_VALUE(trends_hours_ago) AS trends_hours_ago,
                ANY_VALUE(fred_hours_ago) AS fred_hours_ago,
                ANY_VALUE(bls_hours_ago) AS bls_hours_ago,
                ANY_VALUE(serpapi_hours_ago) AS serpapi_hours_ago,
                ANY_VALUE(source_count) AS source_count,
                ANY_VALUE(collection_recency_score) AS collection_recency_score
            FROM `{config.PROJECT_ID}.{config.DATASET}.mart_confidence_layer`
        """
        rows = bq.run_query(sql)
        if not rows:
            return DataFreshnessResult(error="mart_confidence_layer returned zero rows")

        r = rows[0]
        anomaly = None
        if r["distinct_combos"] != 1:
            anomaly = (
                f"expected exactly 1 distinct freshness combo across all rows "
                f"(docs/threshold_decisions.md #7.19 -- these fields are row-independent "
                f"by design), found {r['distinct_combos']}. The 'one shared collector run' "
                f"assumption this tool relies on has broken; treat these values as unreliable."
            )
        return DataFreshnessResult(
            kroger_hours_ago=r["kroger_hours_ago"],
            trends_hours_ago=r["trends_hours_ago"],
            fred_hours_ago=r["fred_hours_ago"],
            bls_hours_ago=r["bls_hours_ago"],
            serpapi_hours_ago=r["serpapi_hours_ago"],
            source_count=r["source_count"],
            collection_recency_score=r["collection_recency_score"],
            distinct_freshness_combos=r["distinct_combos"],
            anomaly=anomaly,
        )
    except Exception as e:
        return DataFreshnessResult(error=str(e))
