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


@pytest.fixture(scope="session")
def agent_config(kb_config, tmp_path_factory):
    """As ``kb_config``, with a refusal threshold that suits the test embeddings and a temporary run log."""
    config = pytest.importorskip("ipw.agent.config")
    log = tmp_path_factory.mktemp("logs") / "runs.jsonl"
    return dataclasses.replace(
        kb_config,
        retrieval=dataclasses.replace(kb_config.retrieval, refuse_below=0.15),
        assistant=config.AssistantConfig(run_log=str(log)),
    )


class FakeOllama:
    """A local stand-in for the Ollama server: it records each chat request and plays back scripted replies.

    It lets the real chat model class run, over HTTP, without a model. ``replies``
    holds the assistant messages to return, in order; ``error`` makes every
    request fail with that status and message. ``tags`` and ``running`` are what
    the server reports as its installed and its loaded models.
    """

    def __init__(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.requests: list[dict] = []
        self.replies: list[dict] = []
        self.error: tuple[int, str] | None = None
        self.tags: list[dict] = []
        self.running: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                listed = {"/api/tags": fake.tags, "/api/ps": fake.running}.get(self.path)
                payload = json.dumps({"models": listed or []}).encode("utf-8")
                self.send_response(200 if listed is not None else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                if fake.error:
                    status, data = fake.error[0], {"error": fake.error[1]}
                else:
                    message = fake.replies[len(fake.requests) - 1]
                    status = 200
                    data = {"model": body["model"], "created_at": "2026-11-10T00:00:00Z", "message": message}
                    data |= {"done": True, "done_reason": "stop", "prompt_eval_count": 1200, "eval_count": 40}
                payload = (json.dumps(data) + "\n").encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def fake_ollama():
    server = FakeOllama()
    yield server
    server.close()
