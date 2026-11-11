"""Fixtures for the tests of the assistant's knowledge base and retrieval.

The tests use the word-hash embeddings of ``ipw.agent.models``: no model, no
download, the same vectors on every machine. The index is built once for the
session in a temporary folder.
"""

import dataclasses

import pytest


@pytest.fixture(scope="session")
def kb_config(root, tmp_path_factory):
    """The repository's assistant configuration, on the test embeddings and a temporary index folder."""
    config = pytest.importorskip("ipw.agent.config")
    loaded = config.load_agent_config(root)
    index = tmp_path_factory.mktemp("index")
    return dataclasses.replace(
        loaded,
        embedding=config.EmbeddingConfig(provider="hashing"),
        knowledge_base=dataclasses.replace(loaded.knowledge_base, index_dir=str(index)),
    )


@pytest.fixture(scope="session")
def knowledge_base(kb_config):
    """The knowledge base of the repository, split and indexed once."""
    kb = pytest.importorskip("ipw.agent.kb", reason='needs the agent extra: pip install -e ".[agent]"')
    return kb.build_index(kb_config)
