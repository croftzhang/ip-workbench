"""The check on a draft answer before it is shown (docs/AGENT_DESIGN.md, AD-6).

The check is code, not a model, so its verdict is the same every time.

Figures. Every number in the draft has to be one of:

* a cell of a tool result of this run, after rounding to the decimals the draft
  shows (sign, currency sign and thousands separators are ignored);
* a number that is part of a label, a text cell, a title or an argument of a
  tool call (the 200 of ``up_200``, the 5 of a 5-year swap that was asked for);
* a count that code can take from a result: its rows, or how often a text value
  occurs in a column (the number of limits whose status is BREACH);
* a number the user typed in the question;
* a number that stands in a retrieved passage which the draft cites.

A total, a difference or a share that the model worked out itself is none of
these and fails; the ``aggregate`` tool is the way to obtain one.

Not figures, and so not checked: dates, identifiers (position, limit, scenario
and result ids), section numbers, list numbering, and spans of whole months or
years used as a description ("12-month income", "a 5-year swap").

Citations. A citation is a document code and a section, written ``[IPS 4.3]``
or in running text. It has to refer to a passage retrieved in this run, or to a
section that a tool result or the question itself names.

What the check does not catch: a correct figure attached to the wrong label.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ipw.agent.retrieval import Hit
from ipw.agent.tools import ToolResult

_NUMBER = re.compile(r"(?<![\w.])[-+−–]?\$?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)")
_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
_NOT_FIGURES = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # 2026-11-09
    re.compile(rf"\b(?:{_MONTHS})[a-z]*\.? \d{{1,2}}(?:, \d{{4}})?"),  # November 9, 2026
    re.compile(rf"\b\d{{1,2}} (?:{_MONTHS})[a-z]*\.?(?: \d{{4}})?"),  # 9 November 2026
    re.compile(
        r"(?<![\w.])[A-Za-z_][A-Za-z_]*[-_.]?\d[\w.-]*"
    ),  # FN30-2.5-001, AOCI_UP200, up_200, FR-11, r3
    re.compile(
        r"(?i)\bsections?\s+\d+(?:\.\d+)*(?:\s*(?:,|and|to)\s*\d+(?:\.\d+)*)*"
    ),  # sections 4.3 and 4.4
    re.compile(r"(?m)^[\s>*#-]*\(?\d{1,2}[.)](?=\s)"),  # list and heading numbering at the start of a line
    re.compile(r"(?i)\b(?:step|option|item|point)\s+\d{1,2}\b"),
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)\b"),  # 2nd largest
    re.compile(r"(?i)\b\d{1,2}[- ]months?\b"),  # 12-month, 12 months: no figure of the engine is in months
    re.compile(r"(?i)\b\d{1,2}-(?:year|yr|day)s?\b"),  # a 5-year swap, 30-year pools
]
_QUOTED = re.compile(r"[\"“]([^\"“”\n]{3,400})[\"”]")
_THINKING = re.compile(r"<think>.*?</think>", flags=re.S)


@dataclass(frozen=True)
class Problem:
    kind: str  # "figure", "citation" or "empty"
    text: str  # the number or the citation as the draft wrote it
    detail: str  # what is wrong, in words the model can act on


@dataclass(frozen=True)
class Check:
    problems: tuple[Problem, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems

    def feedback(self) -> str:
        """What the model is told before its one further attempt."""
        lines = [
            "Your draft did not pass the check of its figures and citations. Correct it and answer again."
        ]
        lines += [f"- {problem.text}: {problem.detail}" for problem in self.problems]
        return "\n".join(lines)


def clean(draft: str) -> str:
    """The draft without any thinking block a model may have left in it."""
    return _THINKING.sub("", draft).strip()


def cites(text: str, ref: str) -> bool:
    """Whether a text names a section, bracketed or not. "IPS 4" is not named by "[IPS 4.3]"."""
    return re.search(rf"(?<![\w.]){re.escape(ref)}(?!\.?\w)", text) is not None


def numbers(text: str) -> list[tuple[float, int, str, int]]:
    """Each number of a text: magnitude, decimals shown, the text as written, and where it starts."""
    found = []
    for match in _NUMBER.finditer(text):
        digits = match.group(1).replace(",", "")
        decimals = len(digits.partition(".")[2])
        found.append((float(digits), decimals, match.group(0), match.start()))
    return found


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _squash(text: str) -> str:
    return " ".join(text.split())


def _strings(value) -> Iterable[str]:
    """Every string inside the arguments of a tool call."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _plain_numbers(value) -> Iterable[float]:
    """Every number inside the arguments of a tool call."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield abs(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _plain_numbers(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _plain_numbers(item)


class _Evidence:
    """What a draft may lean on: the figures, labels and passages of one run."""

    def __init__(
        self, question: str, results: Sequence[ToolResult], hits: Sequence[Hit], codes: Sequence[str]
    ):
        self.cells: list[float] = []
        self.labels: set[str] = set()
        texts: list[str] = [question]
        for result in results:
            if not result.ok:
                continue
            self.cells += list(_plain_numbers(result.arguments))
            texts += list(_strings(result.arguments))
            for table in result.tables:
                texts += [table.title, *table.units]
                self.cells.append(float(len(table.rows)))
                for column in table.units:
                    values = [row[column] for row in table.rows.values()]
                    words = [value for value in values if isinstance(value, str)]
                    texts += words
                    self.cells += [float(count) for count in Counter(words).values()]
                    self.cells += [
                        abs(float(v))
                        for v in values
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                    ]
                texts += list(table.rows)
        self.labels = {text for text in texts[1:] if re.search(r"[A-Za-z]", text) and re.search(r"\d", text)}
        self.cells += [value for text in texts for value, *_ in numbers(text)]
        self.source_text = _squash(" ".join(texts))

        self.hits = list(hits)
        self.passage_numbers = {
            hit.passage.ref: [v for v, *_ in numbers(hit.passage.text)] for hit in self.hits
        }
        self.passage_text = _squash(" ".join(hit.passage.text for hit in self.hits))
        code = "|".join(re.escape(c) for c in sorted(codes, key=len, reverse=True)) or r"(?!)"
        self._bracketed = re.compile(rf"\[\s*((?:{code})\s[^\[\]\n]{{1,120}})\]")
        self._mentioned = re.compile(rf"\b(?:{code})\s+(?:section\s+)?(?:[A-Z]{{2,}}-)?\d+(?:\.\d+)*")
        self._split = re.compile(rf"\s*[;,]\s*(?=(?:{code})\s)")
        named = self.source_text + " " + " ".join(hit.passage.ref for hit in self.hits)
        self.citable = {hit.passage.ref for hit in self.hits} | {
            _squash(m.group(0)) for m in self._mentioned.finditer(named)
        }

    def citations(self, draft: str) -> list[tuple[str, int, int]]:
        """Each citation of the draft: the reference, and the span of text it occupies."""
        found, taken = [], []
        for match in self._bracketed.finditer(draft):
            taken.append(match.span())
            found += [(_squash(ref), *match.span()) for ref in self._split.split(match.group(1).strip())]
        for match in self._mentioned.finditer(draft):
            if not any(start <= match.start() < end for start, end in taken):
                found.append((_squash(match.group(0)).replace(" section ", " "), *match.span()))
        return found


def check(
    draft: str,
    *,
    question: str,
    results: Sequence[ToolResult],
    hits: Sequence[Hit] = (),
    codes: Sequence[str] = (),
) -> Check:
    """Verify every figure and every citation of a draft against the tool results and passages of its run."""
    draft = clean(draft)
    if not draft:
        return Check((Problem("empty", "(no answer)", "the draft is empty; write the answer"),))
    evidence = _Evidence(question, results, hits, codes)
    problems: list[Problem] = []

    # Citations first: they decide which passages a figure may come from.
    text = draft
    cited: set[str] = set()
    allowed = ", ".join(f"[{hit.passage.ref}]" for hit in evidence.hits) or "none: no passage was retrieved"
    for ref, start, end in evidence.citations(draft):
        text = _blank(text, start, end)
        if ref in evidence.citable:
            cited.add(ref)
        elif not any(problem.text == f"[{ref}]" for problem in problems):
            problems.append(
                Problem("citation", f"[{ref}]", f"not a passage of this answer; cite only: {allowed}")
            )

    # A quotation that stands word for word in a passage or a result is not checked figure by figure.
    for match in _QUOTED.finditer(text):
        quoted = _squash(match.group(1))
        if quoted in evidence.passage_text or quoted in evidence.source_text:
            text = _blank(text, *match.span())
    for label in sorted(evidence.labels, key=len, reverse=True):
        for match in re.finditer(rf"(?<![\w.]){re.escape(label)}(?!\w)", text):
            text = _blank(text, *match.span())
    for pattern in _NOT_FIGURES:
        for match in pattern.finditer(text):
            text = _blank(text, *match.span())

    figures = evidence.cells + [value for ref in cited for value in evidence.passage_numbers.get(ref, [])]
    reported: set[str] = set()
    for value, decimals, written, _ in numbers(text):
        tolerance = 0.5 * 10.0**-decimals + 1e-9
        if any(abs(figure - value) <= tolerance for figure in figures) or written in reported:
            continue
        reported.add(written)
        uncited = [
            ref for ref, values in evidence.passage_numbers.items() if ref not in cited and value in values
        ]
        if uncited:
            detail = f"this figure is in passage [{uncited[0]}]; cite that passage where you use it"
        else:
            detail = (
                "not a figure of any tool result. Leave it out, or call the aggregate tool to obtain it; "
                "do not work it out yourself"
            )
        problems.append(Problem("figure", written, detail))
    return Check(tuple(problems))
