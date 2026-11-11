"""Retrieval: the passages of the knowledge base that bear on a question.

The default path is vector search and nothing else. Two optional stages are
switches in ``config/agent.yaml``, both off by default:

* keyword fusion: BM25 over the same passages, combined with the vector
  ranking by reciprocal rank fusion;
* reranking: a cross-encoder scores the candidates against the question.

Either way at most ``top_k`` passages are returned, best first. If the best
vector similarity is below ``refuse_below`` nothing is returned and the result
says that the knowledge base does not cover the question. Refusal is decided
on vector similarity alone, before the optional stages, so the threshold means
the same thing whichever switches are on.

Fusion and reranking are written here on the LangChain core interfaces; the
ready-made ensemble and compression retrievers are not used.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from ipw.agent import models
from ipw.agent.config import RetrievalConfig
from ipw.agent.kb import KnowledgeBase, Passage

NOT_COVERED = "the knowledge base does not cover this"


@dataclass(frozen=True)
class Hit:
    passage: Passage
    score: float  # what ordered the result: similarity, fused score or reranker score
    similarity: float | None  # cosine similarity to the question; None if only the keyword index found it


@dataclass(frozen=True)
class Retrieval:
    question: str
    hits: tuple[Hit, ...]  # at most top_k, best first; empty when the question is not covered
    covered: bool
    best_similarity: float  # of the nearest passage, whether or not it was kept
    method: str  # "vector", "vector+keyword", "vector+rerank" or "vector+keyword+rerank"

    @property
    def refs(self) -> list[str]:
        """The citations the passages allow, in order, each once."""
        return list(dict.fromkeys(hit.passage.ref for hit in self.hits))


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> dict[str, float]:
    """Score of each id over several rankings: the sum of 1 / (k + rank), with ranks counted from 1."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


class Retriever:
    """Vector search over a knowledge base, with the optional stages the configuration switches on."""

    def __init__(self, kb: KnowledgeBase, config: RetrievalConfig, reranker: models.Scorer | None = None):
        self.kb, self.config = kb, config
        self._reranker = reranker
        self._bm25: BM25Okapi | None = None
        self.method = "+".join(
            ["vector", *(["keyword"] if config.keyword else []), *(["rerank"] if config.rerank else [])]
        )

    def keyword_ranking(self, question: str, k: int) -> list[str]:
        """Ids of the ``k`` passages whose words match the question best (BM25); none that match nothing."""
        ids = list(self.kb.passages)
        if self._bm25 is None:
            self._bm25 = BM25Okapi([models.words(self.kb.passages[i].text) for i in ids])
        scores = self._bm25.get_scores(models.words(question))
        ranked = sorted(range(len(ids)), key=lambda n: (-scores[n], n))
        return [ids[n] for n in ranked[:k] if scores[n] > 0]

    def retrieve(self, question: str) -> Retrieval:
        config = self.config
        nearest = self.kb.similar(question, config.candidates)
        similarity = {passage.id: value for passage, value in nearest}
        best = max(similarity.values(), default=0.0)
        if not nearest or best < config.refuse_below:
            return Retrieval(question, (), False, best, self.method)

        ranked = [(passage.id, value) for passage, value in nearest]
        if config.keyword:
            rankings = [[i for i, _ in ranked], self.keyword_ranking(question, config.candidates)]
            fused = reciprocal_rank_fusion(rankings, config.rrf_k)
            ranked = sorted(fused.items(), key=lambda item: -item[1])  # a tie keeps the vector order
        if config.rerank:
            if self._reranker is None:
                self._reranker = models.reranker(config.reranker_model)
            texts = [self.kb.passages[i].text for i, _ in ranked]
            scores = self._reranker(question, texts)
            ranked = sorted(zip([i for i, _ in ranked], scores), key=lambda item: -item[1])

        hits = tuple(
            Hit(self.kb.passages[i], float(score), similarity.get(i)) for i, score in ranked[: config.top_k]
        )
        return Retrieval(question, hits, True, best, self.method)
