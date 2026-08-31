"""
Orchestrator: fetch -> chunk -> embed -> load, one source at a time.

Per-source failure policy (same shape as collect_apis.py's price
collectors): one source failing is reported and does not block the others.
Run from the repo root:

    python -m ingestion.run_ingest
"""

import os
import sys
from datetime import date, datetime, timezone

import yaml
from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.sources import SOURCES, REPO_ROOT
from ingestion import fetch_sec, fetch_gov, chunk as chunker, embed, load_bigquery

load_dotenv()

MANUAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manual_sources")
MANIFEST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manual_sources_manifest.yaml")


def get_client():
    project = os.environ["GCP_PROJECT_ID"]
    creds = service_account.Credentials.from_service_account_file(
        os.environ.get("GCP_CREDENTIALS_PATH", "credentials.json"),
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    return bigquery.Client(project=project, credentials=creds), project


def load_manifest():
    if not os.path.exists(MANIFEST_PATH):
        return {}
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {e["document_id"]: e for e in (data.get("entries") or [])}


def extract_text_from_file(path):
    if path.lower().endswith(".pdf"):
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n\n".join(page.extract_text() or "" for page in pdf.pages)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def fetch_one(source, manifest):
    """Returns (raw_text, source_url, published_date, doc_kind, status) or
    raises for a hard failure. status is 'ok' or 'pending' (manual, not placed)."""
    fetch_type = source["fetch"]

    if fetch_type == "internal_file":
        with open(source["path"], "r", encoding="utf-8") as f:
            text = f.read()
        return text, source["source_url"], None, "markdown", "ok"

    if fetch_type == "sec_edgar":
        result = fetch_sec.fetch_10k_sections(source["cik"], source["ticker"])
        return result["raw_text"], result["source_url"], result["published_date"], "sec_10k", "ok"

    if fetch_type == "fred_api":
        result = fetch_gov.fetch_fred_series_methodology(source["series_id"])
        return result["raw_text"], result["source_url"], result["published_date"], None, "ok"

    if fetch_type == "http_page":
        result = fetch_gov.fetch_http_page(source["url"])
        return result["raw_text"], result["source_url"], result["published_date"], None, "ok"

    if fetch_type == "manual":
        entry = manifest.get(source["document_id"])
        if entry is None:
            return None, None, None, None, "pending"
        file_path = os.path.join(MANUAL_DIR, entry["filename"])
        if not os.path.exists(file_path):
            return None, None, None, None, "pending"
        text = extract_text_from_file(file_path)
        return text, entry.get("source_url"), entry.get("published_date"), "markdown", "ok"

    raise ValueError(f"Unknown fetch type: {fetch_type}")


def process_source(client, project, source, manifest, tokenizer):
    doc_id = source["document_id"]
    raw_text, source_url, published_date, doc_kind, status = fetch_one(source, manifest)

    if status == "pending":
        return {"document_id": doc_id, "status": "PENDING (manual source not yet placed)"}

    fetch_method = "manual" if source["fetch"] == "manual" else "scripted"

    chunks_raw = chunker.chunk_document(raw_text, doc_kind, tokenizer)
    if not chunks_raw:
        raise load_bigquery.LoadError(f"{doc_id}: chunker produced zero chunks")

    vectors = embed.embed_passages([c["chunk_text"] for c in chunks_raw])

    retrieved_date = date.today().isoformat()
    content_hash = load_bigquery.sha256(raw_text)

    document = {
        "document_id": doc_id,
        "source_class": source["source_class"],
        "source_tier": source["source_tier"],
        "doc_title": source["doc_title"],
        "source_url": source_url,
        "published_date": published_date,
        "retrieved_date": retrieved_date,
        "fetch_method": fetch_method,
        "raw_text": raw_text,
        "content_hash": content_hash,
    }

    chunk_rows = []
    for i, (c, vec) in enumerate(zip(chunks_raw, vectors)):
        chunk_rows.append({
            "document_id": doc_id,
            "chunk_index": i,
            "chunk_text": c["chunk_text"],
            "token_count": c["token_count"],
            "section_heading": c["section_heading"],
            "embedding": vec,
            "embedding_model": embed.MODEL_NAME,
            "embedding_dim": embed.EMBEDDING_DIM,
            "contains_numeric_claim": load_bigquery.contains_numeric_claim(c["chunk_text"]),
            "fetch_method": fetch_method,
            "source_class": source["source_class"],
            "source_tier": source["source_tier"],
            "doc_title": source["doc_title"],
            "source_url": source_url,
            "published_date": published_date,
            "retrieved_date": retrieved_date,
        })

    n = load_bigquery.load_document_and_chunks(client, project, document, chunk_rows)
    return {"document_id": doc_id, "status": f"OK — {n} chunks loaded"}


def main():
    client, project = get_client()
    load_bigquery.ensure_dataset_and_tables(client, project)
    tokenizer = embed.get_tokenizer()
    manifest = load_manifest()

    results = []
    for source in SOURCES:
        try:
            results.append(process_source(client, project, source, manifest, tokenizer))
        except Exception as e:
            results.append({"document_id": source["document_id"], "status": f"FAILED — {type(e).__name__}: {e}"})

    print("\n=== Ingestion results ===")
    for r in results:
        print(f"{r['document_id']:40s} {r['status']}")

    n_ok = sum(1 for r in results if r["status"].startswith("OK"))
    n_pending = sum(1 for r in results if r["status"].startswith("PENDING"))
    n_failed = sum(1 for r in results if r["status"].startswith("FAILED"))
    print(f"\n{n_ok} loaded, {n_pending} pending (manual), {n_failed} failed, {len(results)} total")


if __name__ == "__main__":
    main()
