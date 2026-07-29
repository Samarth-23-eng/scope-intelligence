import json
from pathlib import Path

from agents.analysis.base import BaseAnalysisAgent


CORPUS_PATH = Path(__file__).with_name("fixtures") / "agent_grounding_corpus.json"


def test_grounding_regression_corpus():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    outcomes = {}

    for case in corpus:
        validation = BaseAnalysisAgent.validate_grounded_collection(
            case["payload"],
            collection_key=case["collection_key"],
            statement_key=case["statement_key"],
            allowed_evidence_ids=case["allowed_evidence_ids"],
            allowed_chunk_ids=case["allowed_chunk_ids"],
            maximum_items=case["maximum_items"],
            allowed_values={
                key: set(values)
                for key, values in case["allowed_values"].items()
            },
        )
        outcomes[case["name"]] = not validation.errors

    assert outcomes == {case["name"]: case["valid"] for case in corpus}
