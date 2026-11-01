
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Sequence, Tuple

import httpx
from sqlalchemy.orm import Session

from app.config import (
    EMBEDDINGS_ENABLED,
    EMBEDDING_MODEL,
    LLM_API_BASE_URL,
    LLM_API_KEY,
    MAX_RETRIEVAL_CHUNKS,
)
from app.models.source_document import SourceChunkEmbedding, SourceDocument
from app.services.freshness_service import normalize_utc, source_freshness

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9'-]{1,}", re.IGNORECASE)
STOP_WORDS = {
    "about", "after", "again", "against", "also", "among", "because", "been",
    "before", "being", "between", "both", "could", "does", "during", "each",
    "from", "have", "into", "more", "most", "other", "over", "same", "such",
    "than", "that", "their", "them", "then", "there", "these", "they", "this",
    "those", "through", "under", "very", "were", "what", "when", "where", "which",
    "while", "with", "would", "your",
}
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 160
EMBEDDING_BATCH_SIZE = 32


class EmbeddingProviderError(RuntimeError):
    pass


def tokenize(value: str) -> set:
    return {
        token.lower()
        for token in TOKEN_PATTERN.findall(value)
        if token.lower() not in STOP_WORDS and len(token) > 2
    }


def _split_chunks(content: str) -> List[str]:
    normalized = re.sub(r"\s+", " ", content).strip()
    if not normalized:
        return []

    chunks = []
    start = 0

    while start < len(normalized):
        end = min(len(normalized), start + CHUNK_SIZE)

        if end < len(normalized):
            boundary = normalized.rfind(" ", start + CHUNK_SIZE // 2, end)
            if boundary > start:
                end = boundary

        chunk = normalized[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(normalized):
            break

        start = max(start + 1, end - CHUNK_OVERLAP)

    return chunks


def _excerpt(content: str, terms: Sequence[str], width: int = 360) -> str:
    lower = content.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]

    start = max(0, (min(positions) if positions else 0) - 100)
    end = min(len(content), start + width)

    excerpt = content[start:end].strip()

    if start:
        excerpt = "…{}".format(excerpt)

    if end < len(content):
        excerpt = "{}…".format(excerpt)

    return excerpt


def _chunks_for_sources(
    sources: Sequence[SourceDocument],
) -> List[Tuple[SourceDocument, int, str]]:
    chunks = []

    for source in sorted(sources, key=lambda item: item.id):
        for index, chunk in enumerate(_split_chunks(source.content)):
            chunks.append((source, index, chunk))

            if len(chunks) >= MAX_RETRIEVAL_CHUNKS:
                return chunks

    return chunks


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise EmbeddingProviderError(
            "Embedding provider returned inconsistent vector dimensions."
        )

    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))

    if not left_norm or not right_norm:
        raise EmbeddingProviderError(
            "Embedding provider returned an empty vector."
        )

    return sum(
        float(a) * float(b) for a, b in zip(left, right)
    ) / (left_norm * right_norm)


async def _embed_texts(texts: Sequence[str]) -> List[List[float]]:
    endpoint = "{}/embeddings".format(LLM_API_BASE_URL)
    vectors: List[List[float]] = []

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(35.0, connect=8.0)
        ) as client:
            for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
                batch = list(texts[start:start + EMBEDDING_BATCH_SIZE])

                response = await client.post(
                    endpoint,
                    headers={"Authorization": "Bearer " + LLM_API_KEY},
                    json={
                        "model": EMBEDDING_MODEL,
                        "input": batch,
                    },
                )

                response.raise_for_status()
                body = response.json()
                data = body.get("data")

                if not isinstance(data, list) or len(data) != len(batch):
                    raise ValueError(
                        "Embedding response has an unexpected item count."
                    )

                indices = [item.get("index") for item in data]

                if (
                    any(
                        isinstance(index, bool) or not isinstance(index, int)
                        for index in indices
                    )
                    or sorted(indices) != list(range(len(batch)))
                ):
                    raise ValueError(
                        "Embedding response has invalid item indexes."
                    )

                ordered = sorted(data, key=lambda item: item["index"])

                for item in ordered:
                    vector = item.get("embedding")

                    if (
                        not isinstance(vector, list)
                        or not vector
                        or len(vector) > 8192
                        or any(
                            isinstance(value, bool)
                            or not isinstance(value, (int, float))
                            or not math.isfinite(value)
                            for value in vector
                        )
                    ):
                        raise ValueError(
                            "Embedding response contains an invalid vector."
                        )

                    vectors.append([float(value) for value in vector])

    except (
        httpx.HTTPError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        status_code = getattr(
            getattr(exc, "response", None),
            "status_code",
            None,
        )

        reason = (
            "HTTP {}".format(status_code)
            if status_code
            else type(exc).__name__
        )

        raise EmbeddingProviderError(
            "Configured embedding provider request failed ({}).".format(reason)
        ) from exc

    dimensions = {len(vector) for vector in vectors}

    if len(dimensions) != 1:
        raise EmbeddingProviderError(
            "Embedding provider returned inconsistent vector dimensions."
        )

    return vectors


def _freshness(source: SourceDocument) -> str:
    return source_freshness(source)


def _result(
    source: SourceDocument,
    excerpt: str,
    score: float,
    matched_terms: Sequence[str],
    method: str,
) -> Dict[str, object]:
    return {
        # Legacy field retained for backward compatibility.
        "id": source.id,

        # Structured source provenance for Round 3.
        "source_id": source.id,
        "source_type": "approved_internal_source",
        "document_type": source.source_type,
        "approval_status": source.approval_status,
        "is_active": source.is_active,
        "approval_at": (
            normalize_utc(source.reviewed_at).isoformat()
            if source.reviewed_at
            else None
        ),
        "last_verified_at": (
            normalize_utc(
                source.last_verified_at or source.reviewed_at
            ).isoformat()
            if source.last_verified_at or source.reviewed_at
            else None
        ),

        "name": source.name,
        "url": source.url,
        "guideline_id": source.guideline_id,
        "source_date": (
            source.source_date.isoformat()
            if source.source_date
            else None
        ),
        "valid_from": (
            (source.valid_from or source.source_date).isoformat()
            if source.valid_from or source.source_date
            else None
        ),
        "valid_until": (
            (source.valid_until or source.expiry_date).isoformat()
            if source.valid_until or source.expiry_date
            else None
        ),
        "expiry_date": (
            (source.valid_until or source.expiry_date).isoformat()
            if source.valid_until or source.expiry_date
            else None
        ),
        "review_interval_days": source.review_interval_days,
        "freshness": _freshness(source),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "relevance_score": round(
            max(0.0, min(1.0, score)),
            3,
        ),
        "matched_terms": list(matched_terms)[:8],
        "excerpt": excerpt,
        "retrieval_method": method,
        "verification": "candidate_evidence_requires_human_review",
    }


def _lexical_retrieval(
    query: str,
    sources: Sequence[SourceDocument],
    limit: int,
) -> List[Dict[str, object]]:
    query_tokens = tokenize(query)

    if not query_tokens:
        return []

    chunks = _chunks_for_sources(sources)

    if not chunks:
        return []

    tokenized = [tokenize(chunk) for _, _, chunk in chunks]

    document_frequency = Counter(
        token
        for terms in tokenized
        for token in terms
    )

    average_length = (
        sum(len(terms) for terms in tokenized) / len(tokenized)
    )

    ranked = []
    total_chunks = len(chunks)

    for (source, _index, chunk), terms in zip(chunks, tokenized):
        overlap = query_tokens.intersection(terms)

        if not overlap:
            continue

        frequencies = Counter(TOKEN_PATTERN.findall(chunk.lower()))
        score = 0.0

        for token in overlap:
            idf = math.log(
                1 + (
                    total_chunks - document_frequency[token] + 0.5
                ) / (
                    document_frequency[token] + 0.5
                )
            )

            term_frequency = frequencies[token]

            length_normalizer = term_frequency + 1.2 * (
                1 - 0.75 + 0.75 * len(terms) / max(1, average_length)
            )

            score += (
                idf * term_frequency * 2.2
                / max(0.01, length_normalizer)
            )

        normalized_score = score / (score + 2.0)

        if not normalized_score:
            continue

        ranked.append(
            _result(
                source,
                _excerpt(chunk, sorted(overlap)),
                normalized_score,
                sorted(overlap),
                "bm25_lexical",
            )
        )

    return sorted(
        ranked,
        key=lambda item: (
            item["freshness"] == "expired",
            -float(item["relevance_score"]),
        ),
    )[:limit]


def retrieve_lexical_evidence(
    query: str,
    sources: Sequence[SourceDocument],
    limit: int = 5,
) -> List[Dict[str, object]]:
    return _lexical_retrieval(query, sources, limit)


async def _semantic_retrieval(
    query: str,
    sources: Sequence[SourceDocument],
    db: Session,
    limit: int,
) -> List[Dict[str, object]]:
    chunks = _chunks_for_sources(sources)

    if not chunks:
        return []

    source_ids = [source.id for source, _, _ in chunks]

    cached_rows = (
        db.query(SourceChunkEmbedding)
        .filter(
            SourceChunkEmbedding.model_name == EMBEDDING_MODEL,
            SourceChunkEmbedding.source_id.in_(source_ids),
        )
        .all()
    )

    cache = {
        (row.source_id, row.chunk_index): row
        for row in cached_rows
    }

    missing = [
        (source, index, text)
        for source, index, text in chunks
        if (source.id, index) not in cache
        or cache[(source.id, index)].chunk_text != text
    ]

    texts = [query] + [text for _, _, text in missing]
    vectors = await _embed_texts(texts)
    query_vector = vectors[0]

    for (source, index, text), vector in zip(missing, vectors[1:]):
        row = cache.get((source.id, index))

        if row is None:
            row = SourceChunkEmbedding(
                source_id=source.id,
                chunk_index=index,
                chunk_text=text,
                model_name=EMBEDDING_MODEL,
                vector=vector,
            )

            db.add(row)
            cache[(source.id, index)] = row

        else:
            row.chunk_text = text
            row.vector = vector

    db.flush()

    ranked = []
    query_terms = tokenize(query)

    for source, index, chunk in chunks:
        row = cache.get((source.id, index))

        if row is None or row.chunk_text != chunk:
            continue

        cosine = _cosine_similarity(query_vector, row.vector)
        score = (cosine + 1) / 2

        if cosine < 0.20:
            continue

        overlap = sorted(
            query_terms.intersection(tokenize(chunk))
        )

        ranked.append(
            _result(
                source,
                _excerpt(chunk, overlap),
                score,
                overlap,
                "embedding_cosine",
            )
        )

    return sorted(
        ranked,
        key=lambda item: (
            item["freshness"] == "expired",
            -float(item["relevance_score"]),
        ),
    )[:limit]


async def retrieve_evidence(
    query: str,
    sources: Sequence[SourceDocument],
    db: Session,
    limit: int = 5,
) -> Tuple[List[Dict[str, object]], str]:
    if EMBEDDINGS_ENABLED:
        return (
            await _semantic_retrieval(query, sources, db, limit),
            "embedding_cosine",
        )

    return (
        _lexical_retrieval(query, sources, limit),
        "bm25_lexical",
    )


def retrieval_method() -> str:
    return (
        "embedding_cosine"
        if EMBEDDINGS_ENABLED
        else "bm25_lexical"
    )
