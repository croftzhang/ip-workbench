"""Model factories of the assistant: the chat model, embeddings and the optional reranker.

Every model is named in ``config/agent.yaml`` and runs on the user's machine.
The chat model and the embedding model are served by Ollama. The reranker is a
cross-encoder run through sentence-transformers and PyTorch, installed with the
``rerank`` extra and loaded only when its switch is on.

Two stand-ins let the whole path run without a model, in the tests and in
continuous integration. ``ScriptedChatModel`` replies with the next message of
a fixed script. ``HashingEmbeddings`` gives the same word-hash vectors on every
machine. A result obtained with either says that the code works and says
nothing about the quality of a real model.
"""

from __future__ import annotations

import math
import re
import zlib
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from ipw.agent.config import ChatConfig, EmbeddingConfig

# A scorer gives one relevance score per passage for a question; higher is more relevant.
Scorer = Callable[[str, Sequence[str]], Sequence[float]]

_WORD = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how in is it its may not of on or "
    "that the their them there this to under was what when where which who why will with".split()
)


def chat(config: ChatConfig) -> BaseChatModel:
    """The chat model named in the configuration, with the settings of the design: fixed and repeatable."""
    from langchain_ollama import ChatOllama  # creates a client; nothing is sent until first use

    return ChatOllama(
        model=config.model,
        base_url=config.base_url,
        temperature=config.temperature,
        seed=config.seed,
        num_ctx=config.num_ctx,
        num_predict=config.num_predict,
        reasoning=config.reasoning,
    )


class ScriptedChatModel(BaseChatModel):
    """The mock model: replies with the next message of a fixed script, whatever it is asked.

    ``calls`` records what it was sent: the messages, and whether tools were offered.
    """

    script: list[AIMessage]
    calls: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any):
        return self.bind(tools=list(tools), **kwargs)

    def _generate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        if len(self.calls) >= len(self.script):
            raise ValueError(
                f"the script of the mock model has {len(self.script)} replies and one more was asked for"
            )
        reply = self.script[len(self.calls)].model_copy(deep=True)  # a script may repeat one message
        self.calls.append({"messages": list(messages), "tools": bool(kwargs.get("tools"))})
        return ChatResult(generations=[ChatGeneration(message=reply)])


def words(text: str) -> list[str]:
    """Lower-case words of a text. An identifier such as AOCI_UP200 or FR-11 is kept whole and also split."""
    found = []
    for word in _WORD.findall(text.lower()):
        found.append(word)
        parts = re.split(r"[._-]", word)
        if len(parts) > 1 and re.search(r"[a-z]", word):
            found.extend(parts)
    return found


class HashingEmbeddings(Embeddings):
    """Fixed word-hash vectors for tests: no model, no download, the same on every machine."""

    def __init__(self, dimensions: int = 4096):
        self.dimensions = dimensions

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        counts = Counter(word for word in words(text) if word not in _STOPWORDS)
        for word, count in counts.items():
            vector[zlib.crc32(word.encode("utf-8")) % self.dimensions] += 1.0 + math.log(count)
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


class PrefixedEmbeddings(Embeddings):
    """Adds the task prefix an embedding model was trained with: one for documents, one for queries."""

    def __init__(self, base: Embeddings, document_prefix: str = "", query_prefix: str = ""):
        self.base, self.document_prefix, self.query_prefix = base, document_prefix, query_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.base.embed_documents([self.document_prefix + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self.base.embed_query(self.query_prefix + text)


def embeddings(config: EmbeddingConfig) -> Embeddings:
    """The embedding model named in the configuration, with its prefixes applied."""
    if config.provider == "hashing":
        base: Embeddings = HashingEmbeddings()
    else:
        from langchain_ollama import OllamaEmbeddings  # creates a client; nothing is sent until first use

        base = OllamaEmbeddings(model=config.model, base_url=config.base_url)
    if config.document_prefix or config.query_prefix:
        return PrefixedEmbeddings(base, config.document_prefix, config.query_prefix)
    return base


def reranker(model: str) -> Scorer:
    """The cross-encoder named in the configuration, as a scorer. Loads the model on the first call."""
    try:
        from sentence_transformers import CrossEncoder
    except ModuleNotFoundError:
        raise ValueError('reranking needs the rerank extra: pip install -e ".[agent,rerank]"') from None
    loaded: list = []

    def score(question: str, passages: Sequence[str]) -> list[float]:
        if not loaded:
            loaded.append(CrossEncoder(model))
        return [float(value) for value in loaded[0].predict([(question, passage) for passage in passages])]

    return score
