"""The run log: one line of JSON per run, appended to a local file (docs/AGENT_DESIGN.md, AD-7).

A record holds what is needed to see how an answer came about and to reproduce
its figures: the question, each tool call with its arguments and a hash of what
it returned, the passages retrieved with their scores, the models and their
settings, each draft with the outcome of the check, and whether the run
contains a proposal. The figures can be reproduced by making the same tool
calls again; that does not depend on the language model writing the same words
twice.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ipw.agent.config import AgentConfig
    from ipw.agent.graph import Answer


def record(answer: Answer, config: AgentConfig) -> dict[str, Any]:
    """The log record of one run."""
    found = answer.retrieval
    return {
        "run_id": answer.run_id,
        "time": answer.time,
        "market_date": answer.as_of,
        "question": answer.question,
        "task": answer.task,
        "models": {
            "chat": {k: v for k, v in asdict(config.chat).items() if k != "base_url"},
            "embedding": {"provider": config.embedding.provider, "model": config.embedding.model},
        },
        "retrieval": {
            "method": found.method,
            "covered": found.covered,
            "best_similarity": found.best_similarity,
            "refuse_below": config.retrieval.refuse_below,
            "passages": [
                {
                    "id": hit.passage.id,
                    "ref": hit.passage.ref,
                    "score": hit.score,
                    "similarity": hit.similarity,
                }
                for hit in answer.hits
            ],
        },
        "tool_calls": [
            {
                "result": result.id,
                "tool": result.tool,
                "arguments": result.arguments,
                "ok": result.ok,
                "error": result.error,
                "hash": result.digest(),
            }
            for result in answer.calls
        ],
        "drafts": [
            {
                "text": draft.text,
                "passed": draft.check.ok,
                "problems": [asdict(p) for p in draft.check.problems],
            }
            for draft in answer.drafts
        ],
        "status": answer.status,
        "proposal": answer.proposal,
        "answer": answer.text,
        "model_calls": answer.model_calls,
        "tokens": answer.tokens,
    }


class RunLog:
    """An append-only file of run records, one JSON document per line."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return [
            json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
