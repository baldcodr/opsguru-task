from __future__ import annotations

import hashlib
import math
import re
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.api.types import PyEmbedding
from chromadb.errors import NotFoundError

from app.models import CanonicalInvoice, RetrievalHit

COLLECTION_NAME = "cloudnova_invoices"
CHUNK_VERSION = "invoice-v2"
EMBEDDING_VERSION = "feature-hash-v1"
DEFAULT_DIMENSIONS = 384


class StaleIndexError(RuntimeError):
    pass


def vector_fingerprint(structured_fingerprint_value: str, *, dimensions: int) -> str:
    payload = (
        f"structured={structured_fingerprint_value}\n"
        f"chunk={CHUNK_VERSION}\n"
        f"embedding={EMBEDDING_VERSION}\n"
        f"dimensions={dimensions}\n"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _features(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    bigrams = [f"{left}::{right}" for left, right in zip(tokens, tokens[1:], strict=False)]
    return tokens + bigrams


def embed_text(text: str, *, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    if dimensions < 16:
        raise ValueError("embedding dimensions must be at least 16")
    vector = [0.0] * dimensions
    for feature in _features(text):
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:8], "big") % dimensions
        sign = 1.0 if digest[8] & 1 else -1.0
        vector[index] += sign
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude:
        vector = [value / magnitude for value in vector]
    return vector


def render_invoice_document(invoice: CanonicalInvoice) -> str:
    churn = "unknown" if invoice.churned is None else str(invoice.churned).lower()
    csat = "unknown" if invoice.csat_score is None else str(invoice.csat_score)
    industry = invoice.industry or "unknown"
    public_quality_flags = tuple(
        flag for flag in invoice.quality_flags if not flag.startswith("contact_email_")
    )
    quality = ", ".join(public_quality_flags) if public_quality_flags else "none"
    return " ".join(
        (
            f"Invoice {invoice.invoice_id}.",
            f"Account {invoice.account_name}, account ID {invoice.account_id}.",
            f"Region {invoice.region}; industry {industry}.",
            f"Plan {invoice.plan}; billing cycle {invoice.billing_cycle}; seats {invoice.seats}.",
            f"Status {invoice.status}; invoice date {invoice.invoice_date.isoformat()}.",
            (
                f"Amount {invoice.amount_local} {invoice.currency}; "
                f"discount {invoice.discount_pct} percent."
            ),
            f"Churned {churn}; CSAT {csat}; support tickets {invoice.support_tickets}.",
            f"Quality flags {quality}.",
        )
    )


def _vector_id(invoice: CanonicalInvoice) -> str:
    return f"invoice:{invoice.invoice_id}:{invoice.source_row}"


def _metadata(invoice: CanonicalInvoice) -> dict[str, str | int | float | bool]:
    return {
        "invoice_id": invoice.invoice_id,
        "account_id": invoice.account_id,
        "account_name": invoice.account_name,
        "source_row": invoice.source_row,
        "region": invoice.region,
        "industry": invoice.industry or "",
        "plan": invoice.plan,
        "billing_cycle": invoice.billing_cycle,
        "status": invoice.status,
        "currency": invoice.currency,
        "invoice_date": invoice.invoice_date.isoformat(),
    }


def _client(index_path: Path) -> ClientAPI:
    index_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(index_path))


def _collection(client: ClientAPI) -> Collection:
    return client.get_collection(COLLECTION_NAME)


def build_vector_index(
    index_path: Path,
    invoices: tuple[CanonicalInvoice, ...],
    *,
    structured_fingerprint_value: str,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> dict[str, str | int]:
    client = _client(index_path)
    with suppress(NotFoundError):
        client.delete_collection(COLLECTION_NAME)

    fingerprint = vector_fingerprint(
        structured_fingerprint_value,
        dimensions=dimensions,
    )
    collection = client.create_collection(
        COLLECTION_NAME,
        metadata={
            "hnsw:space": "cosine",
            "vector_fingerprint": fingerprint,
            "structured_fingerprint": structured_fingerprint_value,
            "embedding_version": EMBEDDING_VERSION,
            "chunk_version": CHUNK_VERSION,
            "dimensions": dimensions,
            "record_count": len(invoices),
        },
    )

    batch_size = 500
    for start in range(0, len(invoices), batch_size):
        batch = invoices[start : start + batch_size]
        documents = [render_invoice_document(invoice) for invoice in batch]
        embeddings: list[PyEmbedding] = [
            embed_text(document, dimensions=dimensions) for document in documents
        ]
        collection.add(
            ids=[_vector_id(invoice) for invoice in batch],
            embeddings=embeddings,
            documents=documents,
            metadatas=[_metadata(invoice) for invoice in batch],
        )

    return {
        "vector_fingerprint": fingerprint,
        "structured_fingerprint": structured_fingerprint_value,
        "embedding_version": EMBEDDING_VERSION,
        "chunk_version": CHUNK_VERSION,
        "dimensions": dimensions,
        "record_count": len(invoices),
    }


def index_is_current(index_path: Path, expected_fingerprint: str) -> bool:
    if not index_path.is_dir():
        return False
    try:
        metadata = _collection(_client(index_path)).metadata or {}
    except (NotFoundError, OSError, ValueError):
        return False
    return metadata.get("vector_fingerprint") == expected_fingerprint


def search(
    index_path: Path,
    question: str,
    *,
    top_k: int,
    expected_fingerprint: str,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> tuple[RetrievalHit, ...]:
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    collection = _collection(_client(index_path))
    metadata = collection.metadata or {}
    if metadata.get("vector_fingerprint") != expected_fingerprint:
        raise StaleIndexError("Vector index is stale; run `python -m app index`.")

    count = collection.count()
    if count == 0:
        return ()
    query_embeddings: list[PyEmbedding] = [
        embed_text(question, dimensions=dimensions)
    ]
    response = collection.query(
        query_embeddings=query_embeddings,
        n_results=count,
        include=["documents", "metadatas", "distances"],
    )
    ids = response["ids"][0]
    documents = response["documents"][0] if response["documents"] else []
    metadatas = response["metadatas"][0] if response["metadatas"] else []
    distances = response["distances"][0] if response["distances"] else []
    hits: list[RetrievalHit] = []
    for vector_id, document, raw_metadata, distance in zip(
        ids,
        documents,
        metadatas,
        distances,
        strict=True,
    ):
        item = cast(dict[str, Any], raw_metadata)
        hits.append(
            RetrievalHit(
                vector_id=vector_id,
                invoice_id=cast(str, item["invoice_id"]),
                account_id=cast(str, item["account_id"]),
                account_name=cast(str, item["account_name"]),
                source_row=int(item["source_row"]),
                document=document,
                distance=float(distance),
                metadata=dict(item),
            )
        )
    question_invoice_ids = {
        match.group(0).upper()
        for match in re.finditer(r"\binv-\d+\b", question, re.IGNORECASE)
    }
    hits.sort(
        key=lambda hit: (
            0 if hit.invoice_id.upper() in question_invoice_ids else 1,
            hit.distance,
            hit.vector_id,
        )
    )
    return tuple(hits[:top_k])