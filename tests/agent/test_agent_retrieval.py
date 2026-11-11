"""Release 2, build step 2: retrieval and its question set (docs/AGENT_DESIGN.md, AD-5 and AD-8).

Vector search is the default; keyword fusion and reranking are switches; a
question the knowledge base does not cover is refused. Everything runs on the
word-hash embeddings of the tests, so these tests show that the code works and
say nothing about how well a real embedding model retrieves.
"""

import dataclasses
import sys

import pytest

retrieval = pytest.importorskip(
    "ipw.agent.retrieval", reason='needs the agent extra: pip install -e ".[agent]"'
)
evals = pytest.importorskip("ipw.agent.evals")
kb = pytest.importorskip("ipw.agent.kb")
config = pytest.importorskip("ipw.agent.config")

Retriever, Retrieval, Hit = retrieval.Retriever, retrieval.Retrieval, retrieval.Hit
DEFAULT = config.RetrievalConfig()


class Scripted:
    """A knowledge base whose vector search returns what the test says, for exact checks of the logic."""

    def __init__(self, texts: dict[str, str], nearest: list[tuple[str, float]]):
        self.passages = {i: kb.Passage(i, i.split("#")[0], "Doc", i, "", text) for i, text in texts.items()}
        self.nearest = nearest
        self.asked: list[int] = []

    def similar(self, question: str, k: int):
        self.asked.append(k)
        return [(self.passages[i], value) for i, value in self.nearest[:k]]


TEXTS = {
    "A 1#1": "duration band of the portfolio",
    "A 2#1": "the limit AOCI_UP200 after tax",
    "A 3#1": "prepayment burnout of a pool",
    "A 4#1": "hedging with swaps",
    "A 5#1": "scenario definitions",
    "A 6#1": "a note that mentions AOCI_UP200 once more",
}
NEAREST = [("A 1#1", 0.90), ("A 3#1", 0.80), ("A 4#1", 0.70), ("A 5#1", 0.60), ("A 2#1", 0.50)]


# --------------------------------------------------------------------------- the default path


def test_the_default_is_vector_search_alone_and_four_passages(root):
    loaded = config.load_agent_config(root).retrieval
    assert (loaded.keyword, loaded.rerank, loaded.top_k, loaded.candidates, loaded.rrf_k) == (
        False,
        False,
        4,
        20,
        60,
    )
    assert loaded == DEFAULT

    base = Scripted(TEXTS, NEAREST)
    found = Retriever(base, DEFAULT).retrieve("anything")
    assert found.covered and found.method == "vector" and base.asked == [20]
    assert [hit.passage.id for hit in found.hits] == [
        "A 1#1",
        "A 3#1",
        "A 4#1",
        "A 5#1",
    ]  # best first, four kept
    assert [(hit.score, hit.similarity) for hit in found.hits] == [
        (0.9, 0.9),
        (0.8, 0.8),
        (0.7, 0.7),
        (0.6, 0.6),
    ]
    assert found.best_similarity == 0.9 and found.refs == ["A 1", "A 3", "A 4", "A 5"]


def test_vector_search_finds_the_section_that_answers(knowledge_base):
    retriever = Retriever(knowledge_base, DEFAULT)
    cases = {
        "Which limit applies to the after-tax AOCI loss in a 200bp sell-off?": "IPS 4.3",
        "How are effective duration and convexity calculated?": "SPEC FR-6",
        "What is burnout in a mortgage pool?": "MBS 2.4",
        "Can held-to-maturity securities be hedged with swaps?": "HEDGE 3.2",
    }
    for question, reference in cases.items():
        found = retriever.retrieve(question)
        assert found.covered and len(found.hits) == 4
        assert found.hits[0].passage.ref == reference, question
        assert found.hits[0].passage.text.startswith(found.hits[0].passage.document)  # title and heading lead
        scores = [hit.score for hit in found.hits]
        assert scores == sorted(scores, reverse=True) and scores[0] == found.best_similarity


# --------------------------------------------------------------------------- refusal


def test_a_question_below_the_threshold_is_not_covered():
    base = Scripted(TEXTS, NEAREST)
    strict = dataclasses.replace(DEFAULT, refuse_below=0.95)
    refused = Retriever(base, strict).retrieve("anything")
    assert (
        not refused.covered and refused.hits == () and refused.refs == [] and refused.best_similarity == 0.9
    )
    assert retrieval.NOT_COVERED == "the knowledge base does not cover this"

    at_threshold = Retriever(base, dataclasses.replace(DEFAULT, refuse_below=0.90)).retrieve("anything")
    assert at_threshold.covered and len(at_threshold.hits) == 4  # refused only when strictly below
    assert not Retriever(Scripted(TEXTS, []), DEFAULT).retrieve("anything").covered  # nothing found at all


def test_refusal_is_decided_before_the_optional_stages():
    """A keyword match or a high reranker score does not rescue a question the vectors do not support."""
    base = Scripted(TEXTS, [("A 1#1", 0.10)])
    everything = dataclasses.replace(DEFAULT, refuse_below=0.20, keyword=True, rerank=True)
    refused = Retriever(base, everything, reranker=lambda question, passages: [9.0] * len(passages)).retrieve(
        "AOCI_UP200"
    )
    assert not refused.covered and refused.hits == () and refused.method == "vector+keyword+rerank"


def test_a_question_far_from_the_knowledge_base_is_refused(knowledge_base):
    retriever = Retriever(knowledge_base, dataclasses.replace(DEFAULT, refuse_below=0.15))
    far = retriever.retrieve("Wie spaet ist es jetzt?")
    assert not far.covered and far.hits == () and far.best_similarity < 0.15
    near = retriever.retrieve("What band must net effective duration stay inside?")
    assert near.covered and near.best_similarity > 0.30 and near.hits[0].passage.ref == "IPS 4.1"


# --------------------------------------------------------------------------- keyword fusion


def test_reciprocal_rank_fusion_is_the_formula_of_the_design():
    """RRF(d) is the sum over rankings of 1 / (k + rank), ranks from 1, k = 60."""
    scores = retrieval.reciprocal_rank_fusion([["a", "b", "c"], ["c", "a"]], k=60)
    assert scores == {"a": 1 / 61 + 1 / 62, "b": 1 / 62, "c": 1 / 63 + 1 / 61}
    assert sorted(scores, key=scores.get, reverse=True) == ["a", "c", "b"]
    assert retrieval.reciprocal_rank_fusion([["a"], ["a"]], k=1) == {"a": 1.0}


def test_the_keyword_switch_adds_passages_the_vectors_ranked_low_or_missed():
    base = Scripted(TEXTS, NEAREST)
    fused = Retriever(base, dataclasses.replace(DEFAULT, keyword=True)).retrieve("AOCI_UP200")
    assert fused.method == "vector+keyword"
    # BM25 ranks A 2 then A 6 (the shorter passage first); A 2 is also fifth by vector, A 6 only by keyword.
    expected = retrieval.reciprocal_rank_fusion(
        [["A 1#1", "A 3#1", "A 4#1", "A 5#1", "A 2#1"], ["A 2#1", "A 6#1"]], k=60
    )
    order = sorted(expected, key=expected.get, reverse=True)[:4]
    # A 3 (second by vector) and A 6 (second by keyword) score the same; a tie keeps the vector order.
    assert [hit.passage.id for hit in fused.hits] == order == ["A 2#1", "A 1#1", "A 3#1", "A 6#1"]
    assert [hit.score for hit in fused.hits] == [pytest.approx(expected[i]) for i in order]
    assert {hit.passage.id: hit.similarity for hit in fused.hits} == {
        "A 2#1": 0.5,
        "A 1#1": 0.9,
        "A 3#1": 0.8,
        "A 6#1": None,  # found by the keyword index only
    }
    assert Retriever(base, DEFAULT).retrieve("AOCI_UP200").refs == ["A 1", "A 3", "A 4", "A 5"]  # switch off


def test_the_keyword_index_matches_identifiers_and_leaves_out_passages_with_no_match(knowledge_base):
    retriever = Retriever(knowledge_base, dataclasses.replace(DEFAULT, keyword=True))
    ranked = retriever.keyword_ranking("DUR_DRIFT_UP100", 20)
    assert ranked and len(ranked) <= 20
    assert all("DUR_DRIFT_UP100" in knowledge_base.passages[i].text for i in ranked[:3])
    assert knowledge_base.passages[ranked[0]].ref in {"IPS 4.2", "IPS 4", "IPS 6", "SCEN 7"}
    assert retriever.keyword_ranking("zzzz qqqq", 20) == []
    assert "IPS 4.2" in retriever.retrieve("What does the policy say about DUR_DRIFT_UP100?").refs


# --------------------------------------------------------------------------- reranking


def test_the_rerank_switch_reorders_the_candidates_and_keeps_the_best_four():
    base = Scripted(TEXTS, NEAREST)
    seen = {}

    def by_length(question: str, passages: list[str]) -> list[float]:
        seen["question"], seen["passages"] = question, list(passages)
        return [float(len(passage)) for passage in passages]

    found = Retriever(base, dataclasses.replace(DEFAULT, rerank=True), reranker=by_length).retrieve(
        "a question"
    )
    assert found.method == "vector+rerank" and seen["question"] == "a question"
    assert seen["passages"] == [TEXTS[i] for i, _ in NEAREST]  # every candidate is scored, in vector order
    longest = sorted((i for i, _ in NEAREST), key=lambda i: -len(TEXTS[i]))[:4]
    assert [hit.passage.id for hit in found.hits] == longest
    assert [hit.score for hit in found.hits] == [float(len(TEXTS[i])) for i in longest]
    assert [hit.similarity for hit in found.hits] == [dict(NEAREST)[i] for i in longest]

    both = Retriever(base, dataclasses.replace(DEFAULT, keyword=True, rerank=True), reranker=by_length)
    assert both.retrieve("AOCI_UP200").method == "vector+keyword+rerank"
    assert (
        "a note that mentions AOCI_UP200 once more" in seen["passages"]
    )  # fused candidates reach the reranker


def test_the_rerank_switch_without_its_extra_is_a_one_line_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    retriever = Retriever(Scripted(TEXTS, NEAREST), dataclasses.replace(DEFAULT, rerank=True))
    with pytest.raises(ValueError, match="reranking needs the rerank extra") as stop:
        retriever.retrieve("a question")
    assert "\n" not in str(stop.value)


# --------------------------------------------------------------------------- the question set


@pytest.fixture(scope="module")
def questions(root):
    return evals.load_retrieval_questions(root / "evals" / "retrieval.yaml")


def test_the_question_set_has_thirty_answerable_questions_and_ten_that_are_not(
    questions, knowledge_base, kb_config
):
    in_scope = [question for question in questions if question.in_scope]
    assert (len(in_scope), len(questions) - len(in_scope)) == (30, 10)
    assert len({question.question for question in questions}) == 40
    refs = {passage.ref for passage in knowledge_base.passages.values()}
    unknown = {question.id: sorted(set(question.references) - refs) for question in in_scope}
    assert not {
        i: missing for i, missing in unknown.items() if missing
    }  # every reference is a section that exists
    cited = {reference.split()[0] for question in in_scope for reference in question.references}
    assert cited == {
        source.code for source in kb_config.knowledge_base.sources
    }  # every document is asked about


def test_the_measures_are_the_shares_the_design_defines():
    asked = [
        evals.RetrievalQuestion("Q1", "one", ("A 1",)),
        evals.RetrievalQuestion("Q2", "two", ("A 2", "A 9")),
        evals.RetrievalQuestion("Q3", "three", ("A 3",)),
        evals.RetrievalQuestion("Q4", "four", ("A 4",)),
        evals.RetrievalQuestion("N1", "five", ()),
        evals.RetrievalQuestion("N2", "six", ()),
    ]

    def answer(refs: list[str]) -> Retrieval:
        hits = tuple(Hit(kb.Passage(f"{ref}#1", ref, "Doc", ref, "", ""), 1.0, 1.0) for ref in refs)
        return Retrieval("", hits, bool(refs), 1.0, "vector")

    returned = {
        "one": ["A 7", "A 1"],  # hit: the reference is among the passages
        "two": ["A 9"],  # hit: any one reference is enough
        "three": ["A 7", "A 8"],  # miss
        "four": [],  # refused: counts as a miss
        "five": [],  # correctly refused
        "six": ["A 1"],  # answered although out of scope
    }
    assert evals.hit_rate(asked, lambda question: answer(returned[question])) == 2 / 4
    assert evals.refusal_correctness(asked, lambda question: answer(returned[question])) == 1 / 2


def test_the_threshold_suggested_from_the_question_set_separates_the_two_groups():
    assert evals.suggest_threshold([0.6, 0.7, 0.8], [0.2, 0.3]) == pytest.approx(
        0.45
    )  # a clean gap: its midpoint
    assert evals.suggest_threshold([0.3, 0.6, 0.7], [0.2, 0.4]) == pytest.approx(
        0.25
    )  # 4 of 5 right, refusing least
    assert evals.suggest_threshold([0.5, 0.6], []) == 0.0  # nothing to refuse


def test_the_question_set_runs_end_to_end_on_the_test_embeddings(questions, knowledge_base):
    """The whole path on every question, with each switch. The levels are word matching, not a model's."""
    vector = Retriever(knowledge_base, DEFAULT)
    fused = Retriever(knowledge_base, dataclasses.replace(DEFAULT, keyword=True))
    reranked = Retriever(
        knowledge_base, dataclasses.replace(DEFAULT, rerank=True), reranker=lambda q, ps: [0.0] * len(ps)
    )
    for retriever in (vector, fused, reranked):
        rate = evals.hit_rate(questions, retriever.retrieve)
        assert 0.6 <= rate <= 1.0, retriever.method
        assert (
            evals.refusal_correctness(questions, retriever.retrieve) == 0.0
        )  # the shipped threshold never refuses

    best = {question.id: vector.retrieve(question.question).best_similarity for question in questions}
    threshold = evals.suggest_threshold(
        [best[q.id] for q in questions if q.in_scope], [best[q.id] for q in questions if not q.in_scope]
    )
    cut = Retriever(knowledge_base, dataclasses.replace(DEFAULT, refuse_below=threshold))
    assert 0.0 < threshold < 1.0
    assert evals.refusal_correctness(questions, cut.retrieve) >= 0.6
    assert evals.hit_rate(questions, cut.retrieve) >= 0.6


def test_a_malformed_question_set_is_rejected(tmp_path):
    def load(text: str):
        path = tmp_path / "questions.yaml"
        path.write_text(text, encoding="utf-8")
        return evals.load_retrieval_questions(path)

    answerable = "  - {id: R1, question: q, references: [A 1]}\n"
    good = load(f"in_scope:\n{answerable}out_of_scope:\n  - {{id: N1, question: n}}\n")
    assert [(q.id, q.in_scope) for q in good] == [("R1", True), ("N1", False)]
    for text, message in [
        ("in_scope:\n  - {id: R1, question: q}\n", "needs an id, a question and at least one reference"),
        ("out_of_scope:\n  - {id: N1, question: n, references: [A 1]}\n", "and no references"),
        ("in_scope:\n  - {id: R1, question: q, references: [A 1], note: x}\n", "needs an id"),
        (f"in_scope:\n{answerable}{answerable}", "ids must be different"),
        ("other: []\n", "unknown sections"),
    ]:
        with pytest.raises(ValueError, match=message):
            load(text)
