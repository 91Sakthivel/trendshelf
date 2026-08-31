"""
Heading-aware chunker.

Splits on structural headings first (markdown '#'/'##'/'###' for internal
docs, '[ITEM n]' markers for 10-Ks inserted by fetch_sec.py), then packs
paragraphs within each section up to a token budget measured with the
embedding model's OWN tokenizer — never a word-count heuristic — so nothing
silently exceeds the model's max sequence length and gets truncated.

Overlap (15% of the target size) is applied ONLY on the fallback path, when
a single paragraph is too large to fit in one chunk on its own. Chunks that
already align to a natural section/paragraph boundary get no overlap —
overlap exists to stop a fact being severed at an arbitrary split point, not
as a blanket default.
"""

import re

TARGET_TOKENS = 400
MAX_TOKENS = 512  # bge-base-en-v1.5's hard limit
OVERLAP_RATIO = 0.15

MD_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
ITEM_HEADING = re.compile(r"^\[ITEM\s+(\d+[A-Z]?)\]$")


def _split_into_sections(text: str, doc_kind: str):
    """Returns list of (heading, section_text). doc_kind is 'markdown' or 'sec_10k'."""
    lines = text.split("\n")
    sections = []
    current_heading = None
    current_lines = []

    heading_pattern = MD_HEADING if doc_kind == "markdown" else ITEM_HEADING

    for line in lines:
        m = heading_pattern.match(line.strip())
        if m:
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line.strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    return [(h, t) for h, t in sections if t]


def _pack_paragraphs(section_text: str, tokenizer, target_tokens: int):
    """Greedily pack paragraphs up to target_tokens. If a single paragraph
    alone exceeds MAX_TOKENS, fall back to an overlapping token-window split
    for that paragraph only."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section_text) if p.strip()]
    chunks = []
    buf = []
    buf_tokens = 0

    def flush():
        nonlocal buf, buf_tokens
        if buf:
            chunks.append("\n\n".join(buf))
        buf, buf_tokens = [], 0

    for para in paragraphs:
        para_tokens = len(tokenizer.encode(para, add_special_tokens=False))

        if para_tokens > MAX_TOKENS:
            flush()
            # Fallback: overlapping split of this one oversized paragraph.
            ids = tokenizer.encode(para, add_special_tokens=False)
            step = int(MAX_TOKENS * (1 - OVERLAP_RATIO))
            for start in range(0, len(ids), step):
                window_ids = ids[start:start + MAX_TOKENS]
                if not window_ids:
                    continue
                chunks.append(tokenizer.decode(window_ids))
            continue

        if buf_tokens + para_tokens > target_tokens and buf:
            flush()

        buf.append(para)
        buf_tokens += para_tokens

    flush()
    return chunks


def _enforce_max_tokens(chunk_text: str, tokenizer):
    """Hard invariant, not just a construction-time hope: the decode-then-
    reencode round trip used by the overlap-fallback path is not always
    token-count-stable (WordPiece merges can shift by a few tokens), which
    let 8 chunks in the two 10-Ks land at 513-515 tokens on the first build
    of this pipeline and get silently truncated by the embedding model at
    encode time. Re-check and re-trim here regardless of which path produced
    the chunk, so the 512-token ceiling is actually enforced, not assumed."""
    ids = tokenizer.encode(chunk_text, add_special_tokens=False)
    if len(ids) <= MAX_TOKENS:
        return chunk_text, len(ids)
    trimmed_ids = ids[:MAX_TOKENS]
    trimmed_text = tokenizer.decode(trimmed_ids)
    # Re-verify once — decoding can itself shift the count on rare inputs.
    final_ids = tokenizer.encode(trimmed_text, add_special_tokens=False)
    if len(final_ids) > MAX_TOKENS:
        trimmed_text = tokenizer.decode(trimmed_ids[: MAX_TOKENS - 10])
        final_ids = tokenizer.encode(trimmed_text, add_special_tokens=False)
    return trimmed_text, len(final_ids)


def chunk_document(raw_text: str, doc_kind: str, tokenizer):
    """Returns a list of dicts: {chunk_text, section_heading, token_count}."""
    sections = _split_into_sections(raw_text, doc_kind)
    if not sections:
        sections = [(None, raw_text)]

    results = []
    for heading, section_text in sections:
        for chunk_text in _pack_paragraphs(section_text, tokenizer, TARGET_TOKENS):
            final_text, token_count = _enforce_max_tokens(chunk_text, tokenizer)
            assert token_count <= MAX_TOKENS, (
                f"chunk still exceeds MAX_TOKENS after enforcement: {token_count}"
            )
            results.append({
                "chunk_text": final_text,
                "section_heading": heading,
                "token_count": token_count,
            })
    return results
