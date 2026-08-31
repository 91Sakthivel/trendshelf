"""
Embedding model wrapper — local sentence-transformers, pinned model.

BAAI/bge-base-en-v1.5: 768-dim, MIT-licensed, 512-token max sequence length.
Chosen over Vertex AI embeddings for determinism (a pinned local model file
never changes; a hosted API model version can be silently retired), per the
Phase 1 design decision and consistent with docs/threshold_decisions.md
§7.19's finding that unforced dependence on something outside your control
that can silently change your numbers is a defect, not a convenience
tradeoff.

BGE models are trained to expect a specific query-side instruction prefix
for asymmetric search (query vs. passage) — applied here for query
embeddings only; passage/chunk embeddings use the raw text, per BGE's
documented usage convention.
"""

from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-base-en-v1.5"
EMBEDDING_DIM = 768
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def get_tokenizer():
    return get_model().tokenizer


def embed_passages(texts: list[str]) -> list[list[float]]:
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    model = get_model()
    vector = model.encode([QUERY_INSTRUCTION + text], normalize_embeddings=True, show_progress_bar=False)
    return vector[0].tolist()
