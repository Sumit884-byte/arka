"""Push-gate: llm.txt ask contracts scored with semantic similarity."""

from __future__ import annotations

import pytest

from arka.core.semantic_verify import (
    bow_cosine,
    load_ask_contracts,
    parse_ask_contracts,
    verify_semantic_answer,
)


CONTRACTS = load_ask_contracts()


def test_llm_txt_defines_ask_contracts() -> None:
    ids = {row.case_id for row in CONTRACTS}
    assert ids >= {
        "usa-today",
        "news-refusal",
        "nvidia-gtc",
        "apple-event",
        "finance-minister-usa",
        "taj-mahal",
        "memory-relevance",
        "high-cpu-processes",
        "what-can-you-do",
    }


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda row: row.case_id)
def test_good_example_matches_contract_meaning(contract) -> None:
    verdict = verify_semantic_answer(contract.good, contract)
    assert verdict.passed, (contract.case_id, verdict.reasons, verdict.score)
    assert verdict.score >= 0.22


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda row: row.case_id)
def test_bad_example_fails_similarity_or_forbid(contract) -> None:
    verdict = verify_semantic_answer(contract.bad, contract)
    assert not verdict.passed, (contract.case_id, contract.bad, verdict.score)
    assert verdict.reasons


def test_good_is_closer_to_gold_than_bad() -> None:
    for contract in CONTRACTS:
        good = bow_cosine(contract.good, contract.must_mean + " " + contract.good)
        bad = bow_cosine(contract.bad, contract.must_mean + " " + contract.good)
        assert good > bad, contract.case_id


def test_parser_reads_minimal_block() -> None:
    text = """
### case: demo
question: what happened in kenya today
must_mean: specific Kenya events with article links
must_not: unfolding; cannot fulfill
good: Kenya's cabinet approved a new rail link after overnight talks in Nairobi.
bad: Major developments are unfolding. I cannot fulfill this request.
"""
    rows = parse_ask_contracts(text)
    assert len(rows) == 1
    assert rows[0].case_id == "demo"
    assert verify_semantic_answer(rows[0].good, rows[0]).passed
    assert not verify_semantic_answer(rows[0].bad, rows[0]).passed
