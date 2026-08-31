"""
SEC EDGAR fetcher — Kroger and Walmart 10-Ks.

Uses only official, documented SEC endpoints:
  - data.sec.gov/submissions/CIK##########.json  (filing index, to find the
    latest 10-K's accession number and primary document)
  - www.sec.gov/Archives/edgar/data/...           (the actual filing document)

Extracts Item 1 (Business), Item 1A (Risk Factors), and Item 7 (MD&A) only —
not the full filing (financial statements, exhibits, etc. are out of scope
per the Phase 1 design). Section boundaries are detected via the real
section-header convention SEC filings use: a standalone line reading exactly
"ITEM <n[letter]>." (verified against both Kroger's and Walmart's actual
10-K HTML — this is distinct from table-of-contents entries and inline
references, which never appear as an isolated "ITEM N." line on its own).

If Item 1A or Item 7 can't be located, this fails loudly rather than
ingesting the wrong (or empty) text.
"""

import re
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "TrendShelf-research contact@example.com"}
ITEM_LINE = re.compile(r"^ITEM\s+(\d+[A-Z]?)\.$", re.IGNORECASE)

# (item_number, human label) — extraction range is [Item 1 start, Item 1B start)
# union [Item 1A start, Item 1B start) union [Item 7 start, Item 7A start).
# Simpler: grab 1, 1A, and 7 as three separate contiguous ranges.
WANTED_ITEMS = ["1", "1A", "7"]


class SecFetchError(Exception):
    pass


def get_latest_10k(cik: int) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    recent = data["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        if form == "10-K":
            accession = recent["accessionNumber"][i].replace("-", "")
            return {
                "filing_date": recent["filingDate"][i],
                "accession_number": recent["accessionNumber"][i],
                "primary_document": recent["primaryDocument"][i],
                "doc_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{recent['primaryDocument'][i]}",
            }
    raise SecFetchError(f"No 10-K found in recent filings for CIK {cik}")


ZERO_WIDTH_CHARS = "​‌‍﻿"


def _clean_lines(text: str) -> list[str]:
    """Strip real whitespace AND zero-width Unicode characters (SEC filings
    use standalone \\u200b lines as paragraph separators, which str.strip()
    does NOT treat as blank — left unhandled, every paragraph in a filing
    gets silently merged into one giant blob with no break at all, forcing
    the whole section through the lossy token-decode fallback in chunk.py.
    Blank/zero-width-only lines are kept as empty strings (not dropped) so
    they still mark real paragraph breaks when the caller rejoins with '\\n'."""
    cleaned = []
    for line in text.split("\n"):
        stripped = line.strip()
        for ch in ZERO_WIDTH_CHARS:
            stripped = stripped.replace(ch, "")
        cleaned.append(stripped.strip())
    return cleaned


def _find_item_headers(lines: list[str]) -> dict[str, int]:
    """Map item number ('1', '1A', '7', ...) -> line index of its header,
    using only the FIRST occurrence per item (table-of-contents entries use a
    different format — 'Item\xa01' without a trailing period-only line — and
    are not matched by this pattern)."""
    found = {}
    for i, line in enumerate(lines):
        m = ITEM_LINE.match(line)
        if m:
            num = m.group(1).upper()
            if num not in found:
                found[num] = i
    return found


def fetch_10k_sections(cik: int, ticker: str) -> dict:
    filing = get_latest_10k(cik)
    r = requests.get(filing["doc_url"], headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "lxml")
    text = soup.get_text("\n")
    lines = _clean_lines(text)

    headers = _find_item_headers(lines)
    missing = [item for item in WANTED_ITEMS if item not in headers]
    if missing:
        raise SecFetchError(
            f"{ticker} 10-K ({filing['doc_url']}): could not locate section header(s) "
            f"{missing} using the 'ITEM <n>.' pattern. Refusing to ingest partial/wrong "
            f"content — inspect the filing's actual formatting before retrying."
        )

    # Determine each wanted item's end boundary = the next-numbered header found
    # in document order (whatever it is — 1A after 1, 1B after 1A, 7A after 7).
    ordered = sorted(headers.items(), key=lambda kv: kv[1])
    end_of = {}
    for idx, (num, pos) in enumerate(ordered):
        end_of[num] = ordered[idx + 1][1] if idx + 1 < len(ordered) else len(lines)

    sections = {}
    for item in WANTED_ITEMS:
        start, end = headers[item], end_of[item]
        section_text = "\n".join(lines[start:end])
        if len(section_text) < 200:
            raise SecFetchError(
                f"{ticker} 10-K Item {item}: extracted section is suspiciously short "
                f"({len(section_text)} chars) — likely a boundary-detection error."
            )
        sections[item] = section_text

    combined_text = "\n\n".join(
        f"[ITEM {item}]\n{sections[item]}" for item in WANTED_ITEMS
    )
    return {
        "raw_text": combined_text,
        "source_url": filing["doc_url"],
        "published_date": filing["filing_date"],
    }
