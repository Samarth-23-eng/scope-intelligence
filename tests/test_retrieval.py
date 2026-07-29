from contextlib import contextmanager
from unittest.mock import MagicMock

from intelligence import retrieval
from intelligence.retrieval import ChunkIndexer, EvidenceRetriever, RetrievalHit


def hit(
    chunk_id,
    *,
    document_id,
    url,
    content,
    source_type="news",
):
    return RetrievalHit(
        chunk_id=chunk_id,
        evidence_id=chunk_id + 100,
        document_id=document_id,
        document_version_id=document_id + 1000,
        source_url=url,
        title=f"Document {document_id}",
        source_type=source_type,
        content=content,
        published_at=None,
        collected_at=None,
        score=0.01,
        retrieval_methods=("lexical",),
        metadata={},
    )


def test_evidence_pack_fuses_queries_and_removes_exact_content_duplicates(monkeypatch):
    retriever = EvidenceRetriever(1)
    shared = hit(
        1,
        document_id=10,
        url="https://alpha.example/one",
        content="Shared evidence about a product launch.",
    )
    duplicate = hit(
        2,
        document_id=20,
        url="https://mirror.example/copy",
        content=" Shared   evidence about a product launch. ",
    )
    distinct = hit(
        3,
        document_id=30,
        url="https://beta.example/two",
        content="Independent evidence about engineering hiring.",
        source_type="jobs",
    )
    results = {
        "product": [shared, duplicate],
        "hiring": [shared, distinct],
    }
    monkeypatch.setattr(retriever, "prepare", lambda: {})
    monkeypatch.setattr(
        retriever,
        "search",
        lambda query, limit=None, prepare=True: results.get(query, []),
    )

    pack = retriever.build_pack(["product", "hiring"], max_hits=10)

    assert [item.chunk_id for item in pack.hits] == [1, 3]
    assert pack.hits[0].metadata["matched_queries"] == ["product", "hiring"]
    assert pack.diagnostics["candidate_chunks"] == 3
    assert pack.diagnostics["selected_source_types"] == 2
    assert pack.diagnostics["excluded"]["duplicate_content"] == 1


def test_evidence_pack_enforces_domain_and_prompt_budgets(monkeypatch):
    retriever = EvidenceRetriever(1)
    results = [
        hit(
            10,
            document_id=10,
            url="https://same.example/a",
            content="A" * 650,
        ),
        hit(
            11,
            document_id=11,
            url="https://same.example/b",
            content="B" * 650,
        ),
        hit(
            12,
            document_id=12,
            url="https://other.example/c",
            content="C" * 650,
        ),
    ]
    monkeypatch.setattr(retriever, "prepare", lambda: {})
    monkeypatch.setattr(
        retriever,
        "search",
        lambda query, limit=None, prepare=True: results,
    )

    pack = retriever.build_pack(
        ["expansion"],
        max_hits=10,
        max_chars=1000,
        max_per_domain=1,
    )

    assert len(pack.hits) == 1
    assert pack.diagnostics["prompt_chars"] <= 1000
    assert pack.diagnostics["excluded"]["domain_limit"] == 1
    assert pack.diagnostics["excluded"]["prompt_budget"] == 1


def test_indexing_error_response_does_not_expose_internal_exception(monkeypatch):
    row = {
        "id": 1,
        "content": "Evidence",
        "document_version_id": 2,
        "document_id": 3,
        "canonical_url": "https://example.com/evidence",
        "title": "Evidence",
        "source_type": "website",
        "published_at": None,
        "metadata": {},
        "evidence_id": 4,
    }

    cursor = MagicMock()
    cursor.fetchall.return_value = [row]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def fake_connection():
        yield connection

    client = MagicMock()
    client.add.side_effect = RuntimeError(
        "private provider details and C:/internal/stack/path"
    )
    monkeypatch.setattr(retrieval, "get_connection", fake_connection)
    monkeypatch.setattr(ChunkIndexer, "_prepare_model", classmethod(lambda cls: True))
    monkeypatch.setattr(retrieval, "get_client", lambda: client)

    result = ChunkIndexer.index_pending(1)

    assert result["error"] == "semantic indexing failed"
    assert "private provider" not in repr(result)
    assert "internal/stack" not in repr(result)
