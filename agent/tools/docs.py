"""
agent/tools/docs.py -- the 3 RAG tools over rag_corpus.chunks.

Reuses ingestion.embed.embed_query so a question lands in the exact same
vector space as the stored chunk embeddings -- a different model would
make cosine distance meaningless. This is why agent/ inherits ingestion/'s
heavy ML dependency (sentence-transformers/torch); see the Phase 2
proposal, point 1.

No similarity cutoff is applied here -- flagged, not derived. Filtering
out low-relevance hits below some cosine-distance threshold is a real
idea, but any specific number right now would be a guess dressed up as a
default. Left for the Phase 4 ablation to set with evidence, same status
as retail_healthy_pct_divisor (docs/threshold_decisions.md #7.13).
"""
from google.cloud import bigquery

from agent import bq
from agent.schemas import DocSearchResult, RetrievedChunk
import config

try:
    from ingestion.embed import embed_query
    _EMBED_IMPORT_ERROR: str | None = None
except ImportError as e:  # pragma: no cover - exercised only if ingestion/ deps are missing
    embed_query = None
    _EMBED_IMPORT_ERROR = str(e)


def _search(query: str, where_sql: str, top_k: int = 5) -> DocSearchResult:
    if embed_query is None:
        return DocSearchResult(query=query, error=f"embedding model unavailable: {_EMBED_IMPORT_ERROR}")
    try:
        vec = embed_query(query)
        sql = f"""
            SELECT
                base.chunk_id, base.document_id, base.doc_title, base.chunk_text,
                base.source_url, base.source_tier, base.published_date,
                base.contains_numeric_claim, distance
            FROM VECTOR_SEARCH(
                (SELECT * FROM `{config.PROJECT_ID}.{config.RAG_CORPUS_DATASET}.chunks`
                 WHERE {where_sql}),
                'embedding',
                (SELECT @qv AS embedding),
                top_k => @top_k,
                distance_type => 'COSINE'
            )
            ORDER BY distance
        """
        rows = bq.run_query(
            sql,
            params=[
                bigquery.ArrayQueryParameter("qv", "FLOAT64", vec),
                bigquery.ScalarQueryParameter("top_k", "INT64", top_k),
            ],
        )
        chunks = [
            RetrievedChunk(
                chunk_id=r["chunk_id"],
                document_id=r["document_id"],
                doc_title=r["doc_title"],
                chunk_text=r["chunk_text"],
                source_url=r["source_url"],
                source_tier=r["source_tier"],
                published_date=r["published_date"],
                contains_numeric_claim=r["contains_numeric_claim"],
                similarity_distance=r["distance"],
            )
            for r in rows
        ]
        return DocSearchResult(query=query, chunks=chunks)
    except Exception as e:
        return DocSearchResult(query=query, error=str(e))


def lookup_methodology(question: str) -> DocSearchResult:
    """General 'how/why does the model do X' -- internal docs only
    (scoring_methodology.md, README, threshold_decisions.md, signal_stability_backtest.md)."""
    return _search(question, "source_class = 'internal'")


def get_threshold_rationale(threshold_name: str) -> DocSearchResult:
    """Scoped to internal_threshold_decisions specifically, not the general
    internal set. Directly sidesteps the #7.24 finding: a query like "why is
    the CV multiplier 0.16" ranks README's copy of the value above
    threshold_decisions.md's own canonical entry, because retrieval ranks by
    textual similarity, not by which doc is authoritative. Restricting this
    tool to the one doc that's actually the source of record removes that
    failure mode by construction rather than hoping ranking improves later."""
    return _search(threshold_name, "document_id = 'internal_threshold_decisions'")


def search_external_context(question: str) -> DocSearchResult:
    """"What's happening in the market" -- external sources only (10-Ks,
    FRED/USDA methodology notes, and once loaded, earnings calls/industry
    reports). Without this tool, 5 of the corpus's 13 planned sources were
    unreachable by any tool regardless of retrieval quality."""
    return _search(question, "source_class = 'external'")
