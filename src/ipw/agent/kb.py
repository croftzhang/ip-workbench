"""Knowledge base: the documents the assistant may cite, split into passages and indexed.

The sources are listed in ``config/agent.yaml``. Each document is split by
Markdown heading, with a size cap. A passage carries the document, the section
number and the heading path it came from, and is cited by its reference: the
document code and the section, for example ``IPS 4.3``.

The passages are embedded into a local Chroma index. The index records a
fingerprint of the passages and of the embedding settings it was built with,
and refuses to be used once either has changed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings
from chromadb.errors import NotFoundError
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter

from ipw.agent import models
from ipw.agent.config import AgentConfig

_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]
_BLOCK_JOIN = "  \n"  # how MarkdownHeaderTextSplitter joins the blocks of one section
_NUMBERED = re.compile(r"^((?:[A-Z]{2,}-)?\d+(?:\.\d+)*)[.:]?\s+\S")  # "4.3 Title", "3. Title", "FR-6 Title"
_NOT_CONTENT = {"Contents"}  # a table of contents repeats every heading and answers nothing


class IndexMissing(FileNotFoundError):
    """The index has not been built in the configured folder."""


class IndexOutOfDate(ValueError):
    """A source or an embedding setting changed after the index was built."""


@dataclass(frozen=True)
class Passage:
    id: str  # reference and part, for example "IPS 4.3#1"
    ref: str  # how the passage is cited: document code and section, for example "IPS 4.3"
    document: str  # title of the document
    section: str  # section number, or the heading where no heading on the path is numbered
    heading: str  # heading path below the title
    text: str  # what is embedded and what the model reads: title, heading path, body


# ====================================================================== splitting
def _blocks(body: str) -> list[str]:
    """Blocks of a section: paragraphs, tables, lists and fences. A formula stays with the text before it."""
    blocks: list[str] = []
    open_fence = False
    for part in body.split(_BLOCK_JOIN):
        fences = sum(line.startswith("```") for line in part.splitlines())
        if open_fence:
            blocks[-1] += "\n\n" + part
        elif part.startswith("```") and blocks:
            blocks[-1] += "\n\n" + part
        else:
            blocks.append(part)
        open_fence ^= fences % 2 == 1
    return [block for block in blocks if block.strip()]


def _cut(block: str, max_chars: int) -> list[str]:
    """Pieces of a block over the cap, cut between lines. A table keeps its header; a fence is never cut."""
    lines = block.splitlines()
    header: list[str] = []
    if len(lines) > 2 and lines[0].startswith("|") and re.fullmatch(r"\|[\s:|-]+\|", lines[1]):
        header, lines = lines[:2], lines[2:]
    units: list[str] = []
    in_fence = False
    for line in lines:  # a fence counts as one line
        if in_fence:
            units[-1] += "\n" + line
        else:
            units.append(line)
        in_fence ^= line.startswith("```")
    pieces, current = [], list(header)
    for unit in units:
        if len(current) > len(header) and len("\n".join([*current, unit])) > max_chars:
            pieces.append("\n".join(current).strip("\n"))
            current = list(header)
        current.append(unit)
    pieces.append("\n".join(current).strip("\n"))
    return [piece for piece in pieces if piece]


def _pack(blocks: list[str], max_chars: int) -> list[str]:
    """Whole blocks gathered into pieces of at most ``max_chars``; only an oversized block is cut."""
    pieces: list[str] = []
    for block in blocks:
        for part in [block] if len(block) <= max_chars else _cut(block, max_chars):
            if pieces and len(pieces[-1]) + 2 + len(part) <= max_chars:
                pieces[-1] += "\n\n" + part
            else:
                pieces.append(part)
    return pieces


def split_document(text: str, code: str, max_chars: int) -> list[Passage]:
    """Split one Markdown document by heading, with a size cap, into passages that know their source."""
    sections = MarkdownHeaderTextSplitter(_HEADERS, strip_headers=True).split_text(text)
    titles = {section.metadata.get("h1") for section in sections}
    if len(titles) != 1 or None in titles:
        raise ValueError(f"document {code} needs exactly one level-1 heading, its title")
    title = titles.pop()

    passages: list[Passage] = []
    parts: Counter[str] = Counter()
    for section in sections:
        below = [section.metadata[key].replace("`", "") for _, key in _HEADERS[1:] if key in section.metadata]
        if below and below[-1] in _NOT_CONTENT:
            continue
        numbers = [match.group(1) for match in map(_NUMBERED.match, reversed(below)) if match]
        name = numbers[0] if numbers else below[-1] if below else title
        ref = f"{code} {name}"
        lead = " > ".join([title, *below])
        for piece in _pack(_blocks(section.page_content), max_chars):
            parts[ref] += 1
            passages.append(
                Passage(f"{ref}#{parts[ref]}", ref, title, name, " > ".join(below), f"{lead}\n\n{piece}")
            )
    return passages


def load_passages(config: AgentConfig) -> list[Passage]:
    """Every passage of every source, in the order of the configuration."""
    passages: list[Passage] = []
    for source in config.knowledge_base.sources:
        text = (config.root / source.path).read_text(encoding="utf-8")
        passages += split_document(text, source.code, config.knowledge_base.max_chars)
    return passages


# ====================================================================== index
def fingerprint(config: AgentConfig, passages: list[Passage]) -> str:
    """Changes when a passage changes or when the embedding model or its prefixes change."""
    settings = [
        getattr(config.embedding, name) for name in ("provider", "model", "document_prefix", "query_prefix")
    ]
    content = json.dumps([settings, [(passage.id, passage.text) for passage in passages]])
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _client(config: AgentConfig) -> chromadb.ClientAPI:
    """Chroma on local files in the index folder. Its product telemetry is switched off."""
    folder = Path(config.root, config.knowledge_base.index_dir)
    return chromadb.PersistentClient(path=str(folder), settings=Settings(anonymized_telemetry=False))


@dataclass(frozen=True)
class KnowledgeBase:
    """The passages and the vector index over them."""

    passages: dict[str, Passage]  # by passage id, in document order
    store: Chroma

    def similar(self, question: str, k: int) -> list[tuple[Passage, float]]:
        """The ``k`` passages nearest to the question, each with its cosine similarity, best first."""
        found = self.store.similarity_search_with_score(question, k=k)
        return [(self.passages[document.id], 1.0 - distance) for document, distance in found]


def build_index(config: AgentConfig, embedder: Embeddings | None = None) -> KnowledgeBase:
    """Split, embed and index the sources, replacing any index already there."""
    embedder = embedder or models.embeddings(config.embedding)
    passages = load_passages(config)
    client, name = _client(config), config.knowledge_base.collection
    try:
        client.delete_collection(name)
    except NotFoundError:
        pass
    store = Chroma(
        client=client,
        collection_name=name,
        embedding_function=embedder,
        collection_metadata={"fingerprint": fingerprint(config, passages), "passages": len(passages)},
        collection_configuration={"hnsw": {"space": "cosine"}},
    )
    store.add_texts(
        [passage.text for passage in passages],
        metadatas=[{"ref": p.ref, "document": p.document, "section": p.section} for p in passages],
        ids=[passage.id for passage in passages],
    )
    return KnowledgeBase({passage.id: passage for passage in passages}, store)


def open_index(config: AgentConfig, embedder: Embeddings | None = None) -> KnowledgeBase:
    """Open the index, and refuse it if a source or an embedding setting changed since it was built."""
    embedder = embedder or models.embeddings(config.embedding)
    passages = load_passages(config)
    client, name = _client(config), config.knowledge_base.collection
    try:
        built = client.get_collection(name).metadata or {}
    except NotFoundError:
        raise IndexMissing("the knowledge base index has not been built") from None
    if built.get("fingerprint") != fingerprint(config, passages):
        raise IndexOutOfDate(
            "the knowledge base index is out of date: a source or an embedding setting has changed"
        )
    store = Chroma(
        client=client,
        collection_name=name,
        embedding_function=embedder,
        create_collection_if_not_exists=False,
    )
    return KnowledgeBase({passage.id: passage for passage in passages}, store)
