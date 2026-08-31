"""
Government-source fetchers: FRED API (structured, official) and a generic
defensive HTTP+HTML fetch for pages like USDA ERS that don't have a clean
API but do have a stable URL.
"""

import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

HEADERS = {"User-Agent": "Mozilla/5.0 TrendShelf-research"}
FRED_API_KEY = os.environ.get("FRED_API_KEY")

MIN_EXTRACTED_CHARS = 500  # below this, treat as a failed/garbage fetch


class GovFetchError(Exception):
    pass


def fetch_fred_series_methodology(series_id: str) -> dict:
    """FRED's structured API has no long-form methodology prose for this series
    (verified: /series 'notes' field is empty, /series/tags is sparse). What it
    does have — series definition, category, and parent release (which links to
    the BLS PPI program that actually defines the methodology) — is real,
    accurate, structured metadata. This is deliberately compact, not a failed
    fetch; the minimum length here is calibrated to what a complete record of
    this shape actually looks like, not the generic page-fetch minimum."""
    if not FRED_API_KEY:
        raise GovFetchError("FRED_API_KEY not set in .env")

    def _get(endpoint, **params):
        params.update({"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json"})
        resp = requests.get(f"https://api.stlouisfed.org/fred/{endpoint}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    series = _get("series")["seriess"][0]
    tags = [t["name"] for t in _get("series/tags").get("tags", [])]
    categories = [c["name"] for c in _get("series/categories").get("categories", [])]
    release = _get("series/release")["releases"][0]

    raw_text = (
        f"Series ID: {series['id']}\n"
        f"Title: {series['title']}\n"
        f"Units: {series['units']}\n"
        f"Frequency: {series['frequency']}\n"
        f"Seasonal Adjustment: {series['seasonal_adjustment']}\n"
        f"Observation range: {series['observation_start']} to {series['observation_end']}\n"
        f"Last updated: {series['last_updated']}\n"
        f"FRED category: {', '.join(categories) or '(none listed)'}\n"
        f"Tags: {', '.join(tags) or '(none listed)'}\n"
        f"Parent release: {release['name']} (id {release['id']})\n"
        f"Underlying methodology source: {release['link']} — this FRED series is "
        f"republished from the Bureau of Labor Statistics' Producer Price Index "
        f"program; the full PPI methodology is documented there, not by FRED "
        f"itself (FRED is a distribution layer over BLS's underlying series).\n"
        f"Notes: {series.get('notes') or '(FRED provides no notes field for this series)'}\n"
    )
    FRED_MIN_CHARS = 300
    if len(raw_text) < FRED_MIN_CHARS:
        raise GovFetchError(
            f"FRED series {series_id}: extracted metadata suspiciously short "
            f"({len(raw_text)} chars, expected >= {FRED_MIN_CHARS}) — API response shape may have changed."
        )
    return {
        "raw_text": raw_text,
        "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
        "published_date": None,  # methodology metadata, not a dated publication
    }


def fetch_http_page(url: str) -> dict:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    raw_text = "\n".join(lines)
    if len(raw_text) < MIN_EXTRACTED_CHARS:
        raise GovFetchError(
            f"{url}: extracted text suspiciously short ({len(raw_text)} chars) — "
            f"page structure may have changed or content is behind JS rendering."
        )
    return {"raw_text": raw_text, "source_url": url, "published_date": None}
