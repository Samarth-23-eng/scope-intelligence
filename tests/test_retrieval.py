from intelligence.retrieval import EvidenceRetriever, RetrievalHit


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
