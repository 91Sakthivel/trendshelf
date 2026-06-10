"""
collect_apis.py — TrendShelf Bronze Layer Collector
Pulls raw data from configured sources and uploads directly to BigQuery (bronze dataset).
"""

import os
import time
import base64
import logging
import datetime
import requests
import pandas as pd

from google.cloud import bigquery
from google.oauth2 import service_account

from config import (
    PROJECT_ID, DATASET, CREDENTIALS_PATH,
    KROGER_CLIENT_ID, KROGER_CLIENT_SECRET,
    SERPAPI_KEY, FRED_API_KEY,
    WALMART_DFW_STORE_ID,
    KROGER_STORES, CATEGORIES,
    WALMART_QUERIES, GOOGLE_TRENDS_KEYWORDS,
    COLLECT_GOOGLE_TRENDS, COLLECT_SERPAPI,
    COLLECT_KROGER, COLLECT_FRED, COLLECT_BLS,
)

CREDS_FILE = CREDENTIALS_PATH

# ── Logging + run timestamp ───────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

RUN_TS = datetime.datetime.now(datetime.timezone.utc)

# ── BigQuery client ───────────────────────────────────────────────────────────

_creds = service_account.Credentials.from_service_account_file(
    CREDS_FILE,
    scopes=["https://www.googleapis.com/auth/bigquery"],
)
BQ = bigquery.Client(project=PROJECT_ID, credentials=_creds)


def _upload(df: pd.DataFrame, table_name: str,
            write_disposition: str = "WRITE_TRUNCATE") -> None:
    """Load a DataFrame into a BigQuery table. Default is WRITE_TRUNCATE."""
    destination = f"{PROJECT_ID}.{DATASET}.{table_name}"
    job_config  = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
    )
    job = BQ.load_table_from_dataframe(df, destination, job_config=job_config)
    job.result()
    log.info("  → %d rows  →  %s  [%s]", len(df), destination, write_disposition)


# ── Collectors ────────────────────────────────────────────────────────────────

def collect_google_trends() -> bool:
    """Google Trends — 10 category keywords, US, last 12 months → google_trends_raw"""
    log.info("[1/5] Google Trends — collecting 10 categories...")
    try:
        from pytrends.request import TrendReq
        import time as _time

        pytrends   = TrendReq(hl="en-US", tz=360)
        all_frames = []

        for category, keyword in GOOGLE_TRENDS_KEYWORDS.items():
            try:
                log.info("  Trends: %s → '%s'", category, keyword)
                pytrends.build_payload([keyword], timeframe="today 12-m", geo="US")
                df_raw = pytrends.interest_over_time()

                if df_raw.empty:
                    log.warning("  Trends: %s — no data returned, skipping", category)
                    continue

                df = df_raw.reset_index().rename(columns={
                    "date":      "trend_date",
                    keyword:     "interest_score",
                    "isPartial": "is_partial",
                })
                df = df[~df["is_partial"]].copy()

                df["trend_date"]     = pd.to_datetime(df["trend_date"]).dt.date
                df["interest_score"] = df["interest_score"].astype("Int64")
                df["is_partial"]     = df["is_partial"].astype(bool)
                df["search_keyword"] = keyword
                df["category"]       = category
                df["geography"]      = "US"
                df["collected_at"]   = RUN_TS
                df["load_timestamp"] = RUN_TS

                all_frames.append(df)
                log.info("  Trends: %s — %d rows collected", category, len(df))

                # Rate-limit protection — pytrends blocks on rapid requests
                _time.sleep(15)

            except Exception as keyword_exc:
                log.warning("  Trends: %s — FAILED: %s", category, keyword_exc)
                _time.sleep(30)
                continue

        if not all_frames:
            log.error("[1/5] Google Trends — all keywords failed")
            return False

        combined = pd.concat(all_frames, ignore_index=True)

        # Keep latest collected_at per keyword + trend_date before appending
        combined = combined.sort_values("collected_at", ascending=False)
        combined = combined.drop_duplicates(
            subset=["search_keyword", "trend_date"],
            keep="first",
        )

        # WRITE_APPEND — preserves history across runs; dedup handled above
        _upload(combined, "google_trends_raw", write_disposition="WRITE_APPEND")

        log.info(
            "[1/5] Google Trends — PASS  (%d rows, %d categories)",
            len(combined), combined["category"].nunique(),
        )
        return True

    except Exception as exc:
        log.error("[1/5] Google Trends — FAIL  %s", exc)
        return False


def collect_fred_ppi() -> bool:
    """FRED API — PPI PCU42440042440012, 24 months  →  fred_ppi_raw"""
    log.info("[2/5] FRED PPI — collecting...")
    try:
        resp = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id":  "PCU42440042440012",
                "api_key":    FRED_API_KEY,
                "file_type":  "json",
                "sort_order": "desc",
                "limit":      24,
            },
            timeout=10,
        )
        resp.raise_for_status()
        obs = resp.json().get("observations", [])

        if not obs:
            log.warning("[2/5] FRED PPI — no observations returned")
            return False

        df = pd.DataFrame(obs)[["date", "value"]]
        df = df[df["value"] != "."].copy()

        df["observation_date"] = pd.to_datetime(df["date"]).dt.date
        df["ppi_value"]        = df["value"].astype(float)
        df["series_id"]        = "PCU42440042440012"
        df["collected_at"]     = RUN_TS
        df["load_timestamp"]   = RUN_TS
        df = df.drop(columns=["date", "value"])

        _upload(df, "fred_ppi_raw")
        log.info("[2/5] FRED PPI — PASS  (latest %s = %s)", obs[0]["date"], obs[0]["value"])
        return True

    except Exception as exc:
        log.error("[2/5] FRED PPI — FAIL  %s", exc)
        return False


def collect_kroger_prices() -> bool:
    """Kroger API — 20 DFW stores × 10 categories  →  kroger_prices_raw"""
    log.info(
        "[3/5] Kroger prices — collecting %d stores × %d categories (%d API calls)...",
        len(KROGER_STORES), len(CATEGORIES), len(KROGER_STORES) * len(CATEGORIES),
    )
    try:
        # OAuth2 client-credentials token (lasts 30 min; sufficient for full run)
        credentials = base64.b64encode(
            f"{KROGER_CLIENT_ID}:{KROGER_CLIENT_SECRET}".encode()
        ).decode()
        token_resp = requests.post(
            "https://api.kroger.com/v1/connect/oauth2/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": "product.compact"},
            timeout=10,
        )
        token_resp.raise_for_status()
        token = token_resp.json().get("access_token")
        if not token:
            log.warning("[3/5] Kroger — no access token received")
            return False

        all_rows = []

        for store_idx, store in enumerate(KROGER_STORES, 1):
            store_id, store_city = store["id"], store["city"]
            for cat_idx, category in enumerate(CATEGORIES, 1):
                try:
                    prod_resp = requests.get(
                        "https://api.kroger.com/v1/products",
                        headers={"Authorization": f"Bearer {token}"},
                        params={
                            "filter.term":       category,
                            "filter.limit":      50,
                            "filter.locationId": store_id,
                        },
                        timeout=10,
                    )
                    prod_resp.raise_for_status()
                    products = prod_resp.json().get("data", [])
                except Exception as call_exc:
                    log.warning(
                        "  Store %d/%d (%s) — Category %d/%d (%s) — SKIPPED: %s",
                        store_idx, len(KROGER_STORES), store_city,
                        cat_idx,   len(CATEGORIES),   category, call_exc,
                    )
                    products = []

                for p in products:
                    first_item = (p.get("items") or [{}])[0]
                    price      = first_item.get("price") or {}
                    all_rows.append({
                        "product_id":       p.get("productId"),
                        "upc":              p.get("upc"),
                        "brand":            p.get("brand"),
                        "description":      p.get("description"),
                        "primary_category": (p.get("categories") or [None])[0],
                        "price_regular":    price.get("regular"),
                        "price_promo":      price.get("promo"),
                        "item_size":        first_item.get("size"),
                        "sold_by":          first_item.get("soldBy"),
                        "store_id":         store_id,
                        "store_city":       store_city,
                        "category":         category,
                        "search_term":      category,
                        "collected_at":     RUN_TS,
                        "load_timestamp":   RUN_TS,
                    })

                print(
                    f"  Store {store_idx:>2}/{len(KROGER_STORES)} ({store_city:<28}) — "
                    f"Category {cat_idx:>2}/{len(CATEGORIES)} ({category:<18}) — "
                    f"{len(products):>3} products",
                    flush=True,
                )

            # 1-second delay between stores to be a good API citizen
            if store_idx < len(KROGER_STORES):
                time.sleep(1)

        if not all_rows:
            log.warning("[3/5] Kroger — no products returned across all stores/categories")
            return False

        df = pd.DataFrame(all_rows)
        df["price_regular"] = pd.to_numeric(df["price_regular"], errors="coerce")
        df["price_promo"]   = pd.to_numeric(df["price_promo"],   errors="coerce")

        _upload(df, "kroger_prices_raw")
        log.info(
            "[3/5] Kroger prices — PASS  (%d total products across %d stores × %d categories)",
            len(df), len(KROGER_STORES), len(CATEGORIES),
        )
        return True

    except Exception as exc:
        log.error("[3/5] Kroger prices — FAIL  %s", exc)
        return False


def collect_bls_cpi() -> bool:
    """BLS API — CPI Food at home CUUR0000SAF11, 2 years  →  bls_cpi_raw"""
    log.info("[4/5] BLS CPI — collecting...")
    try:
        today = datetime.date.today()
        resp = requests.post(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            json={
                "seriesid":  ["CUUR0000SAF11"],
                "startyear": str(today.year - 1),
                "endyear":   str(today.year),
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        series_list = data.get("Results", {}).get("series", [])
        entries     = series_list[0].get("data", []) if series_list else []
        if not entries:
            log.warning("[4/5] BLS CPI — no data points returned")
            return False

        rows = []
        for e in entries:
            month     = int(e["period"].replace("M", ""))
            raw_value = e.get("value", "")
            rows.append({
                "reference_year": int(e["year"]),
                "period_code":    e["period"],
                "period_name":    e["periodName"],
                "reference_date": datetime.date(int(e["year"]), month, 1),
                "cpi_value":      None if raw_value == "-" else float(raw_value),
                "is_suppressed":  raw_value == "-",
                "is_latest":      e.get("latest") == "true",
                "series_id":      "CUUR0000SAF11",
                "collected_at":   RUN_TS,
                "load_timestamp": RUN_TS,
            })

        df = pd.DataFrame(rows)
        _upload(df, "bls_cpi_raw")
        latest = entries[0]
        log.info("[4/5] BLS CPI — PASS  (latest %s %s = %s)",
                 latest.get("periodName"), latest.get("year"), latest.get("value"))
        return True

    except Exception as exc:
        log.error("[4/5] BLS CPI — FAIL  %s", exc)
        return False


def collect_serpapi() -> bool:
    """SerpAPI — Walmart DFW competitor prices for 10 categories
    → serpapi_prices_raw

    Uses engine=walmart with DFW Supercenter store_id=2105
    (4122 LBJ Fwy, Dallas TX 75244 — full Supercenter).
    Returns single-item Walmart.com prices with price_per_unit
    for apples-to-apples comparison with Kroger single-item prices.
    7-day cache per category. Max 10 searches per run.
    """
    log.info("[5/5] SerpAPI Walmart DFW — collecting %d categories...", len(CATEGORIES))

    try:
        # 7-day cache check per category
        fresh_categories: set = set()
        try:
            fresh_check = f"""
                SELECT DISTINCT category
                FROM `{PROJECT_ID}.{DATASET}.serpapi_prices_raw`
                WHERE search_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
                  AND competitor_store = 'Walmart DFW'
            """
            for row in BQ.query(fresh_check).result():
                fresh_categories.add(row["category"])
        except Exception:
            pass  # Table doesn't exist yet; treat all as stale

        if all(cat in fresh_categories for cat in CATEGORIES):
            log.info(
                "[5/5] SerpAPI — SKIPPED (all %d categories cached < 7 days)",
                len(CATEGORIES),
            )
            return True

        stale = [cat for cat in CATEGORIES if cat not in fresh_categories]
        log.info("[5/5] SerpAPI — %d/%d categories need refresh", len(stale), len(CATEGORIES))

        all_rows = []
        searches_used = 0

        for category in stale:
            if searches_used >= 10:
                log.info("  QUOTA: reached 10-search limit, stopping")
                break

            query = WALMART_QUERIES.get(category, category)

            resp = requests.get(
                "https://serpapi.com/search",
                params={
                    "engine":   "walmart",
                    "query":    query,
                    "store_id": WALMART_DFW_STORE_ID,
                    "api_key":  SERPAPI_KEY,
                    "sort":     "best_match",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("organic_results", [])
            searches_used += 1

            row_count = 0
            prices_collected = []

            for item in results:
                # Skip out of stock items
                if item.get("out_of_stock", False):
                    continue

                # Skip sponsored results — may not reflect real shelf prices
                if item.get("sponsored", False):
                    continue

                # Get price from primary_offer first, fallback to top-level
                price_float = None
                primary = item.get("primary_offer", {})
                if primary.get("offer_price"):
                    try:
                        price_float = float(primary["offer_price"])
                    except (ValueError, TypeError):
                        pass

                if price_float is None:
                    raw_price = item.get("price", "")
                    try:
                        price_float = float(
                            str(raw_price).replace("$", "").replace(",", "").strip()
                        )
                    except (ValueError, AttributeError):
                        pass

                if price_float is None or price_float <= 0:
                    continue

                # price_per_unit normalizes bundle vs single-item
                # e.g. "$0.18/oz" — use for fair Kroger comparison
                price_per_unit_float = None
                price_per_unit_str = None
                ppu = item.get("price_per_unit", {})
                if ppu:
                    price_per_unit_str = (
                        f"{ppu.get('amount', '')} per {ppu.get('unit', '')}"
                    ).strip()
                    try:
                        ppu_amount = (
                            str(ppu.get("amount", ""))
                            .replace("$", "")
                            .strip()
                        )
                        price_per_unit_float = float(ppu_amount)
                    except (ValueError, TypeError):
                        pass

                prices_collected.append(price_float)

                all_rows.append({
                    "product_name":       item.get("title", "")[:500],
                    "competitor_store":   "Walmart DFW",
                    "walmart_store_id":   WALMART_DFW_STORE_ID,
                    "competitor_price":   price_float,
                    "price_per_unit":     price_per_unit_float,
                    "price_per_unit_str": price_per_unit_str,
                    "category":           category,
                    "search_query":       query,
                    "search_date":        datetime.date.today(),
                    "collected_at":       RUN_TS,
                    "load_timestamp":     RUN_TS,
                })
                row_count += 1

            avg_price = (
                round(sum(prices_collected) / len(prices_collected), 2)
                if prices_collected else 0
            )
            log.info(
                "  Search %2d/10 — %-25s — %3d prices — avg $%.2f",
                searches_used, category, row_count, avg_price,
            )

        if not all_rows:
            log.warning("[5/5] SerpAPI — no parseable prices returned")
            return False

        df = pd.DataFrame(all_rows)
        df["competitor_price"] = pd.to_numeric(df["competitor_price"], errors="coerce")
        df["price_per_unit"]   = pd.to_numeric(df["price_per_unit"],   errors="coerce")

        _upload(df, "serpapi_prices_raw")
        log.info(
            "[5/5] SerpAPI — PASS  (%d prices, %d searches used)",
            len(df), searches_used,
        )
        return True

    except Exception as exc:
        log.error("[5/5] SerpAPI — FAIL  %s", exc)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 64)
    print("  TrendShelf — Bronze Layer Collection → BigQuery")
    print(f"  Run timestamp : {RUN_TS.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Destination   : {PROJECT_ID}.{DATASET}")
    print(f"  Stores        : {len(KROGER_STORES)}   Categories : {len(CATEGORIES)}")
    print("=" * 64)

    results = {}

    if COLLECT_GOOGLE_TRENDS:
        results["google_trends_raw"] = collect_google_trends()
        time.sleep(3)
    else:
        print("  [SKIP] Google Trends — rate-limited; existing history intact")

    if COLLECT_FRED:
        results["fred_ppi_raw"] = collect_fred_ppi()
    else:
        print("  [SKIP] FRED PPI — flag COLLECT_FRED=False")

    if COLLECT_BLS:
        results["bls_cpi_raw"] = collect_bls_cpi()
    else:
        print("  [SKIP] BLS CPI — flag COLLECT_BLS=False")

    if COLLECT_KROGER:
        results["kroger_prices_raw"] = collect_kroger_prices()
    else:
        print("  [SKIP] Kroger prices — flag COLLECT_KROGER=False")

    if COLLECT_SERPAPI:
        results["serpapi_prices_raw"] = collect_serpapi()
    else:
        print("  [SKIP] SerpAPI — flag COLLECT_SERPAPI=False")

    passed = sum(results.values())
    total  = len(results)

    print("\n" + "=" * 64)
    print("  Collection Summary")
    print("=" * 64)
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {PROJECT_ID}.{DATASET}.{name}")
    print("-" * 64)
    print(f"  {passed}/{total} active collectors completed successfully")
    print("=" * 64)

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
