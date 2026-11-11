"""Configuration of the assistant: ``config/agent.yaml``.

One file holds every model name, every retrieval setting and the budgets of the loop. It is read into
frozen dataclasses and checked on load, so a wrong entry is reported with the
file and the key, as the release 1 configuration is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from ipw.core.config import find_root

FILE = "agent.yaml"
PROVIDERS = ("ollama", "hashing")


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "ollama"
    model: str = "nomic-embed-text"
    base_url: str | None = None
    document_prefix: str = ""
    query_prefix: str = ""


@dataclass(frozen=True)
class Source:
    code: str  # short name used in citations, for example IPS
    path: str  # relative to the root folder


@dataclass(frozen=True)
class KnowledgeBaseConfig:
    sources: tuple[Source, ...] = ()
    index_dir: str = ".chroma"
    collection: str = "ipw-kb"
    max_chars: int = 1600


@dataclass(frozen=True)
class RetrievalConfig:
    top_k: int = 4
    candidates: int = 20
    refuse_below: float = 0.0
    keyword: bool = False
    rrf_k: int = 60
    rerank: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"


@dataclass(frozen=True)
class ChatConfig:
    model: str = "qwen3:8b"
    base_url: str | None = None
    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 16384  # context length in tokens
    num_predict: int = 2048  # the longest reply the model may write, in tokens
    reasoning: bool = False  # thinking mode


@dataclass(frozen=True)
class AssistantConfig:
    tool_calls: int = 8  # tool calls allowed in one run
    run_log: str = "logs/agent_runs.jsonl"  # relative to the root folder


@dataclass(frozen=True)
class AgentConfig:
    root: Path  # the folder that holds config/, data/ and the knowledge base sources
    embedding: EmbeddingConfig
    knowledge_base: KnowledgeBaseConfig
    retrieval: RetrievalConfig
    chat: ChatConfig = ChatConfig()
    assistant: AssistantConfig = AssistantConfig()


def _section(raw: dict[str, Any], name: str, kind: type) -> Any:
    """One section of the file as its dataclass; a key the dataclass does not have is an error."""
    values = raw.get(name) or {}
    if not isinstance(values, dict):
        raise ValueError(f"{FILE}: {name} must be a mapping")
    unknown = set(values) - {field.name for field in fields(kind)}
    if unknown:
        raise ValueError(f"{FILE}: {name} has unknown keys {sorted(unknown)}")
    return kind(**values)


def load_agent_config(root: str | Path | None = None) -> AgentConfig:
    """Read and check ``<root>/config/agent.yaml``."""
    root = find_root(root)
    path = root / "config" / FILE
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = set(raw) - {"embedding", "knowledge_base", "retrieval", "chat", "assistant"}
    if unknown:
        raise ValueError(f"{FILE}: unknown sections {sorted(unknown)}")

    embedding = _section(raw, "embedding", EmbeddingConfig)
    if embedding.provider not in PROVIDERS:
        raise ValueError(f"{FILE}: embedding.provider must be one of {', '.join(PROVIDERS)}")

    listed = dict(raw.get("knowledge_base") or {})
    try:
        listed["sources"] = tuple(Source(**item) for item in listed.get("sources") or ())
    except TypeError:
        raise ValueError(f"{FILE}: each knowledge_base source needs exactly a code and a path") from None
    knowledge_base = _section({"knowledge_base": listed}, "knowledge_base", KnowledgeBaseConfig)
    sources = knowledge_base.sources
    codes = [source.code for source in sources]
    if not sources:
        raise ValueError(f"{FILE}: knowledge_base.sources is empty")
    if len(set(codes)) != len(codes) or not all(re.fullmatch(r"[A-Z][A-Z0-9]*", code) for code in codes):
        raise ValueError(f"{FILE}: source codes must be different and written in capitals, for example IPS")
    missing = [source.path for source in sources if not (root / source.path).is_file()]
    if missing:
        raise FileNotFoundError(f"{FILE}: knowledge base source not found: {', '.join(missing)}")
    if knowledge_base.max_chars < 200:
        raise ValueError(f"{FILE}: knowledge_base.max_chars must be at least 200")

    retrieval = _section(raw, "retrieval", RetrievalConfig)
    if not 1 <= retrieval.top_k <= retrieval.candidates:
        raise ValueError(f"{FILE}: retrieval needs 1 <= top_k <= candidates")
    if retrieval.rrf_k <= 0:
        raise ValueError(f"{FILE}: retrieval.rrf_k must be positive")

    chat = _section(raw, "chat", ChatConfig)
    if chat.num_ctx < 2048:
        raise ValueError(f"{FILE}: chat.num_ctx must be at least 2048")
    if not 256 <= chat.num_predict <= chat.num_ctx:
        raise ValueError(f"{FILE}: chat.num_predict must be between 256 and chat.num_ctx")
    assistant = _section(raw, "assistant", AssistantConfig)
    if assistant.tool_calls < 1:
        raise ValueError(f"{FILE}: assistant.tool_calls must be at least 1")
    return AgentConfig(root, embedding, knowledge_base, retrieval, chat, assistant)
