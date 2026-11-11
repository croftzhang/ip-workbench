"""Evaluation of the assistant: fixed question sets and deterministic measures.

This module holds the retrieval question set and its two measures
(docs/AGENT_DESIGN.md, AD-8):

* retrieval hit rate at 4: the share of questions for which a reference
  section is among the passages given to the model;
* refusal correctness: the share of out-of-scope questions answered
  "not covered".

A measure takes any function from a question to a ``Retrieval``, so the same
code scores vector search, keyword fusion and reranking.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from ipw.agent.retrieval import Retrieval

Retrieve = Callable[[str], Retrieval]


@dataclass(frozen=True)
class RetrievalQuestion:
    id: str
    question: str
    references: tuple[str, ...]  # sections that answer it, for example "IPS 4.3"; empty when out of scope

    @property
    def in_scope(self) -> bool:
        return bool(self.references)


def load_retrieval_questions(path: str | Path) -> list[RetrievalQuestion]:
    """Read the question set: ``in_scope`` questions with references, ``out_of_scope`` questions without."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = set(raw) - {"in_scope", "out_of_scope"}
    if unknown:
        raise ValueError(f"{path.name}: unknown sections {sorted(unknown)}")
    questions = []
    for section, needs_references in (("in_scope", True), ("out_of_scope", False)):
        for item in raw.get(section) or []:
            extra = set(item) - {"id", "question", "references"}
            references = tuple(item.get("references") or ())
            if extra or "id" not in item or "question" not in item or bool(references) != needs_references:
                raise ValueError(
                    f"{path.name}: {section} item {item.get('id')!r} needs an id, a question and "
                    f"{'at least one reference' if needs_references else 'no references'}"
                )
            questions.append(RetrievalQuestion(str(item["id"]), str(item["question"]), references))
    ids = [question.id for question in questions]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path.name}: question ids must be different")
    return questions


def hit_rate(questions: Iterable[RetrievalQuestion], retrieve: Retrieve) -> float:
    """Share of in-scope questions with a reference section among the passages returned."""
    asked = [question for question in questions if question.in_scope]
    hits = sum(bool(set(question.references) & set(retrieve(question.question).refs)) for question in asked)
    return hits / len(asked)


def refusal_correctness(questions: Iterable[RetrievalQuestion], retrieve: Retrieve) -> float:
    """Share of out-of-scope questions for which nothing is returned."""
    asked = [question for question in questions if not question.in_scope]
    return sum(not retrieve(question.question).covered for question in asked) / len(asked)


def suggest_threshold(in_scope: Sequence[float], out_of_scope: Sequence[float]) -> float:
    """The refusal threshold that classifies most questions correctly, from their best similarities.

    A question is refused when its best similarity is below the threshold.
    Candidates are the midpoints between neighbouring observed values; among
    equally good ones the lowest is returned, which refuses least.
    """
    values = sorted({*in_scope, *out_of_scope})
    candidates = [0.0, *((low + high) / 2.0 for low, high in zip(values, values[1:]))]

    def correct(threshold: float) -> int:
        return sum(v >= threshold for v in in_scope) + sum(v < threshold for v in out_of_scope)

    return max(candidates, key=lambda threshold: (correct(threshold), -threshold))
