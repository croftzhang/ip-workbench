"""Release 2, build step 2: the knowledge base (docs/AGENT_DESIGN.md, AD-5 and section 4).

The constructed documents agree with the engine's configuration; a document is
split by heading with a size cap and a formula stays with its section; the
index is built on local files and refuses to be used once a source or an
embedding setting has changed.
"""

import dataclasses
import inspect
import re
import sys
from types import SimpleNamespace

import pytest
import typer
import yaml

from ipw.classic import cli
from ipw.core.scenarios import Scenario
from ipw.core.workbench import Workbench

kb = pytest.importorskip("ipw.agent.kb", reason='needs the agent extra: pip install -e ".[agent]"')
config = pytest.importorskip("ipw.agent.config")
models = pytest.importorskip("ipw.agent.models")

CONSTRUCTED = [
    "investment_policy",
    "hedging_policy",
    "afs_htm_accounting",
    "scenario_definitions",
    "mbs_primer",
    "glossary",
]


def section(root, name: str, number: str) -> str:
    """Text of one numbered section of a constructed document, up to the next heading."""
    text = (root / "kb" / f"{name}.md").read_text(encoding="utf-8")
    found = re.search(rf"^#+ {re.escape(number)}[ .].*?(?=^#+ |\Z)", text, flags=re.M | re.S)
    assert found, f"{name} has no section {number}"
    return found.group(0)


def stated(text: str, value: float) -> bool:
    """True if the text gives the figure, without its sign, as a whole number: 3.0, 0.50, 210."""
    forms = {f"{abs(value):g}", f"{abs(value):.1f}", f"{abs(value):.2f}"}
    return any(re.search(rf"(?<![\d.]){re.escape(form)}(?!\d|\.\d)", text) for form in forms)


def written(scenario, defaults: dict) -> str:
    """The parameters of a scenario as the scenario definitions write them: those that are not at rest."""
    parts = []
    for key, value in dataclasses.asdict(scenario).items():
        if key in ("name", "description") or value == defaults[key]:
            continue
        if key == "curve_points_bp":
            value = "{" + ", ".join(f"{tenor:g}: {move:g}" for tenor, move in value) + "}"
        parts.append(f"{key}: {value if isinstance(value, str) else format(value, 'g')}")
    return ", ".join(parts)


# --------------------------------------------------------------------------- documents and configuration


def test_the_configuration_names_the_knowledge_base_of_the_design(root, kb_config):
    """Six constructed documents in kb/, and the functional specification and model document."""
    sources = {source.code: source.path for source in kb_config.knowledge_base.sources}
    assert sorted(sources.values()) == sorted(
        [*(f"kb/{name}.md" for name in CONSTRUCTED), "docs/FUNCTIONAL_SPEC.md", "docs/MODEL.md"]
    )
    assert sorted(path.stem for path in (root / "kb").glob("*.md")) == sorted(CONSTRUCTED)
    for code, path in sources.items():
        text = (root / path).read_text(encoding="utf-8")
        assert "illustrative" in text.split("\n## ")[0], path
        if path.startswith("kb/"):
            assert "| Role | Knowledge base of the assistant: embedded and retrieved |" in text, path
            assert f"| Cited as | {code} and the section number" in text, path


def test_the_investment_policy_states_every_limit_of_the_configuration(wb, root):
    """Each limit's policy reference is a section of the policy that names the limit and its bounds."""
    for limit in wb.limits:
        document, number = limit.policy_ref.split()
        assert document == "IPS"
        text = section(root, "investment_policy", number)
        assert f"`{limit.id}`" in text, f"IPS {number} does not name {limit.id}"
        for bound in (limit.min, limit.max):
            assert bound is None or stated(text, bound), f"IPS {number} does not state {bound} for {limit.id}"
    warning = {limit.warn_at for limit in wb.limits}
    assert warning == {0.80} and "reaches 80%" in section(root, "investment_policy", "5.2")
    summary = section(root, "investment_policy", "4")
    assert all(f"`{limit.id}`" in summary for limit in wb.limits)


def test_the_scenario_definitions_equal_the_configuration(wb, root):
    """One table row per configured scenario, with its description and its parameters, and no other row."""
    text = (root / "kb" / "scenario_definitions.md").read_text(encoding="utf-8")
    definitions, used_by_limits = text.split("\n## 2.")[1].split("\n## 7.")
    rows = dict(re.findall(r"^\| `(\w+)` \| (.+) \|$", definitions, flags=re.M))
    defaults = dataclasses.asdict(Scenario(name="no shock"))
    for name, scenario in wb.scenarios.items():
        assert rows.get(name) == f"{scenario.description} | `{written(scenario, defaults)}`", name
    assert set(rows) == set(wb.scenarios)
    assert all(f"| `{limit.scenario}` |" in used_by_limits for limit in wb.limits if limit.scenario)


def test_the_accounting_note_states_the_configured_tax_rate(wb, root):
    rate = wb.model.balance_sheet.tax_rate
    text = section(root, "afs_htm_accounting", "3.2")
    assert f"tax rate of {rate:.0%}" in text and f"{1 - rate:.0%} of the pre-tax change" in text


def test_the_hedging_policy_states_the_engine_defaults(root):
    """Remediation in steps of USD 10 million, over the tenors the release 1 command tries by default."""
    step = inspect.signature(Workbench.fix_limit).parameters["round_to_mm"].default
    fix = typer.main.get_command(cli.app).commands["fix"]
    *first, last = next(option.default for option in fix.params if option.name == "tenors").split(",")
    text = section(root, "hedging_policy", "5.3").replace("\n", " ")
    assert f"in steps of USD {step:g} million" in text
    assert f"by default {', '.join(first)} and {last} years" in text


# --------------------------------------------------------------------------- splitting

SAMPLE = """# Sample Policy

| | |
|---|---|
| Document | Sample |

## Contents

1. Limits

## 1. Limits

Limits are set here.

### 1.1 Duration

The band is stated first.

```math
D = \\frac{a}{b}
```

A closing remark.

### Notes without a number

These notes belong to section 1.

## Appendix

```text
# not a heading

still inside the fence
```
"""


def test_a_document_is_split_by_heading_and_each_passage_knows_where_it_is_from():
    passages = kb.split_document(SAMPLE, "SMP", max_chars=1600)
    assert [(p.id, p.section, p.heading) for p in passages] == [
        ("SMP Sample Policy#1", "Sample Policy", ""),
        ("SMP 1#1", "1", "1. Limits"),
        ("SMP 1.1#1", "1.1", "1. Limits > 1.1 Duration"),
        ("SMP 1#2", "1", "1. Limits > Notes without a number"),  # cited as its numbered parent
        ("SMP Appendix#1", "Appendix", "Appendix"),
    ]
    assert all(p.document == "Sample Policy" and p.ref == p.id.split("#")[0] for p in passages)
    assert not any("Contents" in p.heading for p in passages)  # the table of contents is not content
    duration = passages[2]
    assert duration.text.startswith("Sample Policy > 1. Limits > 1.1 Duration\n\nThe band is stated first.")
    assert "```math\nD = \\frac{a}{b}\n```" in duration.text
    assert "# not a heading\n\nstill inside the fence" in passages[4].text  # a fence is never a heading


def test_a_long_section_is_cut_between_blocks_and_a_formula_stays_with_its_lead_in():
    paragraphs = [f"Paragraph {n} " + "word " * 40 for n in range(6)]
    formula = "The value is:\n\n```math\nV = \\sum_t CF_t\n```"
    text = "# Doc\n\n## 2. Long\n\n" + "\n\n".join([*paragraphs[:3], formula, *paragraphs[3:]]) + "\n"
    passages = kb.split_document(text, "DOC", max_chars=500)
    assert len(passages) > 2 and [p.id for p in passages] == [
        f"DOC 2#{n}" for n in range(1, len(passages) + 1)
    ]
    for passage in passages:
        body = passage.text.split("\n\n", 1)[1]
        assert len(body) <= 500
        assert body.count("```") % 2 == 0  # no fence is cut
    holder = next(p for p in passages if "```math" in p.text)
    assert "The value is:\n\n```math\nV = \\sum_t CF_t\n```" in holder.text
    joined = " ".join(p.text.split("\n\n", 1)[1] for p in passages)
    assert all(paragraph.strip() in joined for paragraph in paragraphs)  # nothing is lost


def test_a_formula_is_never_cut_even_when_its_lead_in_fills_the_cap():
    lead_in = "This sentence introduces the formula and is long. " * 10
    formula = "```math\nV = \\sum_t CF_t\n\\qquad \\text{(1.1)}\n```"
    passages = kb.split_document(f"# Doc\n\n## 1. Value\n\n{lead_in}\n\n{formula}\n", "DOC", max_chars=500)
    assert [p.text.count("```") for p in passages] == [0, 2]  # the lead-in alone, then the whole formula
    assert passages[1].text.endswith(formula) and passages[1].ref == "DOC 1"  # still cited as its section


def test_a_long_table_is_cut_between_rows_and_keeps_its_header():
    rows = [f"| item {n} | {'value ' * 12}|" for n in range(30)]
    text = "# Doc\n\n## 3. Table\n\n| Name | Meaning |\n|---|---|\n" + "\n".join(rows) + "\n"
    passages = kb.split_document(text, "DOC", max_chars=600)
    assert len(passages) > 3
    for passage in passages:
        body = passage.text.split("\n\n", 1)[1]
        assert body.startswith("| Name | Meaning |\n|---|---|\n| item ") and len(body) <= 600
    assert sum(passage.text.count("| item ") for passage in passages) == 30


def test_a_document_needs_one_title():
    with pytest.raises(ValueError, match="exactly one level-1 heading"):
        kb.split_document("## 1. No title\n\ntext\n", "DOC", 1600)
    with pytest.raises(ValueError, match="exactly one level-1 heading"):
        kb.split_document("# One\n\ntext\n\n# Two\n\ntext\n", "DOC", 1600)


def test_the_repository_knowledge_base_splits_into_citable_passages(kb_config, wb):
    passages = kb.load_passages(kb_config)
    assert len({p.id for p in passages}) == len(passages) > 100
    codes = [source.code for source in kb_config.knowledge_base.sources]
    assert list(dict.fromkeys(p.ref.split()[0] for p in passages)) == codes  # every document, in order
    cap = kb_config.knowledge_base.max_chars
    assert all(len(p.text.split("\n\n", 1)[1]) <= cap for p in passages)
    assert all(p.text.count("```") % 2 == 0 for p in passages)
    refs = {p.ref for p in passages}
    assert {limit.policy_ref for limit in wb.limits} <= refs  # every limit's policy reference can be cited
    assert {f"SPEC FR-{n}" for n in range(18)} | {"SPEC FR-3.1", "MODEL 3", "SPEC Model parameters"} <= refs


# --------------------------------------------------------------------------- embeddings


def test_the_test_embeddings_are_fixed_and_match_shared_words():
    embedder = models.HashingEmbeddings()
    first, again = (
        embedder.embed_query("AOCI limit in a 200bp sell-off"),
        embedder.embed_query("AOCI limit in a 200bp sell-off"),
    )
    assert first == again and len(first) == 4096
    assert sum(value * value for value in first) == pytest.approx(1.0)
    assert embedder.embed_documents(["a limit", "duration"])[1] == embedder.embed_query("duration")

    def cosine(a: str, b: str) -> float:
        return sum(x * y for x, y in zip(embedder.embed_query(a), embedder.embed_query(b)))

    assert cosine("AOCI limit", "the limit on AOCI") == pytest.approx(
        1.0
    )  # order and stop words do not matter
    assert cosine("AOCI limit", "prepayment burnout") == 0.0
    assert 0.0 < cosine("AOCI limit", "duration limit") < 1.0
    assert embedder.embed_query("the of and") == [0.0] * 4096


def test_words_keep_identifiers_whole_and_also_split_them():
    assert models.words("Limit AOCI_UP200, see FR-11 and IPS 4.3 (after-tax).") == [
        "limit", "aoci_up200", "aoci", "up200", "see", "fr-11", "fr", "11", "and", "ips", "4.3",
        "after-tax", "after", "tax",
    ]  # fmt: skip


def test_prefixes_are_added_to_documents_and_to_queries_separately():
    seen = []

    class Recorder(models.Embeddings):
        def embed_documents(self, texts):
            seen.extend(texts)
            return [[0.0] for _ in texts]

        def embed_query(self, text):
            seen.append(text)
            return [0.0]

    prefixed = models.PrefixedEmbeddings(Recorder(), "search_document: ", "search_query: ")
    prefixed.embed_documents(["a passage", "another"])
    prefixed.embed_query("a question")
    assert seen == ["search_document: a passage", "search_document: another", "search_query: a question"]


def test_the_configured_embedding_model_is_served_by_ollama_with_its_prefixes(root):
    """The object is built without contacting a server; nothing is sent until a text is embedded."""
    loaded = config.load_agent_config(root).embedding
    assert (loaded.provider, loaded.model) == ("ollama", "nomic-embed-text")
    assert (loaded.document_prefix, loaded.query_prefix) == ("search_document: ", "search_query: ")
    embedder = models.embeddings(loaded)
    assert isinstance(embedder, models.PrefixedEmbeddings)
    assert type(embedder.base).__name__ == "OllamaEmbeddings" and embedder.base.model == "nomic-embed-text"
    assert isinstance(models.embeddings(config.EmbeddingConfig(provider="hashing")), models.HashingEmbeddings)


def test_the_reranker_scores_pairs_with_the_configured_cross_encoder(monkeypatch):
    class CrossEncoder:
        loaded: list = []

        def __init__(self, name):
            self.loaded.append(name)

        def predict(self, pairs):
            assert all(question == "q" for question, _ in pairs)
            return [len(passage) / 10 for _, passage in pairs]

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=CrossEncoder))
    score = models.reranker("some/cross-encoder")
    assert CrossEncoder.loaded == []  # the model is loaded on first use, not before
    assert score("q", ["ab", "abcd"]) == [0.2, 0.4]
    assert score("q", ["a"]) == [0.1] and CrossEncoder.loaded == ["some/cross-encoder"]


def test_reranking_without_its_extra_says_what_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ValueError, match=r'pip install -e "\.\[agent,rerank\]"'):
        models.reranker("some/cross-encoder")


# --------------------------------------------------------------------------- index


def test_the_index_holds_every_passage_and_measures_cosine_similarity(kb_config, knowledge_base):
    collection = knowledge_base.store._collection
    assert collection.count() == len(knowledge_base.passages) == collection.metadata["passages"]
    passage = knowledge_base.passages["IPS 4.3#1"]
    (nearest, similarity), *others = knowledge_base.similar(passage.text, k=5)
    assert nearest == passage and similarity == pytest.approx(1.0, abs=1e-6)  # a text is nearest to itself
    assert [value for _, value in others] == sorted((value for _, value in others), reverse=True)

    embedder = models.embeddings(kb_config.embedding)
    question = "How large may the after-tax AOCI loss be in a 200bp sell-off?"
    query = embedder.embed_query(question)
    for found, value in knowledge_base.similar(question, k=3):  # the score is the cosine of the two vectors
        cosine = sum(x * y for x, y in zip(query, embedder.embed_query(found.text)))
        assert value == pytest.approx(cosine, abs=1e-6)


def test_the_index_is_reopened_from_local_files(kb_config, knowledge_base):
    reopened = kb.open_index(kb_config)
    assert list(reopened.passages) == list(knowledge_base.passages)
    question = "after-tax AOCI loss in a 200bp sell-off"
    assert reopened.similar(question, 4) == knowledge_base.similar(question, 4)
    assert kb._client(kb_config).get_settings().anonymized_telemetry is False


def test_an_index_that_is_missing_or_out_of_date_is_refused(kb_config, knowledge_base, tmp_path):
    elsewhere = dataclasses.replace(
        kb_config, knowledge_base=dataclasses.replace(kb_config.knowledge_base, index_dir=str(tmp_path))
    )
    with pytest.raises(FileNotFoundError, match="has not been built"):
        kb.open_index(elsewhere)

    other_model = dataclasses.replace(
        kb_config, embedding=config.EmbeddingConfig(provider="hashing", model="another")
    )
    with pytest.raises(ValueError, match="out of date"):
        kb.open_index(other_model)
    smaller = dataclasses.replace(
        kb_config, knowledge_base=dataclasses.replace(kb_config.knowledge_base, max_chars=800)
    )
    with pytest.raises(ValueError, match="out of date"):
        kb.open_index(smaller)

    passages = kb.load_passages(kb_config)
    edited = [dataclasses.replace(passages[0], text=passages[0].text + " edited"), *passages[1:]]
    assert kb.fingerprint(kb_config, edited) != kb.fingerprint(kb_config, passages)
    assert kb.fingerprint(kb_config, passages) == kb.fingerprint(kb_config, list(passages))


def test_building_again_replaces_the_index(kb_config, tmp_path):
    here = dataclasses.replace(
        kb_config, knowledge_base=dataclasses.replace(kb_config.knowledge_base, index_dir=str(tmp_path))
    )
    first = kb.build_index(here)
    before = first.similar("duration band", 3)
    second = kb.build_index(here)
    assert second.store._collection.count() == len(first.passages)
    assert kb.open_index(here).similar("duration band", 3) == before


# --------------------------------------------------------------------------- configuration file


def test_a_wrong_entry_in_the_configuration_is_reported_with_its_key(root, tmp_path):
    for folder, name in (("config", "market.yaml"), ("data", "portfolio.csv"), ("kb", "a.md")):
        (tmp_path / folder).mkdir(exist_ok=True)
        (tmp_path / folder / name).write_text("# A\n\ntext\n", encoding="utf-8")
    good = {"knowledge_base": {"sources": [{"code": "A", "path": "kb/a.md"}]}}

    def load(change: dict):
        merged = {**good, **change}
        (tmp_path / "config" / "agent.yaml").write_text(yaml.safe_dump(merged), encoding="utf-8")
        return config.load_agent_config(tmp_path)

    defaults = load({})
    assert (defaults.retrieval.top_k, defaults.retrieval.keyword, defaults.retrieval.rerank) == (
        4,
        False,
        False,
    )
    cases = [
        ({"retrieval": {"top_n": 4}}, ValueError, r"agent.yaml: retrieval has unknown keys \['top_n'\]"),
        ({"models": {}}, ValueError, r"agent.yaml: unknown sections \['models'\]"),
        ({"chat": {"num_ctx": 512}}, ValueError, "chat.num_ctx must be at least 2048"),
        ({"chat": {"num_predict": 64}}, ValueError, "chat.num_predict must be between 256 and chat.num_ctx"),
        ({"chat": {"num_predict": 20000}}, ValueError, "chat.num_predict must be between 256 and"),
        ({"chat": {"think": True}}, ValueError, r"agent.yaml: chat has unknown keys \['think'\]"),
        ({"assistant": {"tool_calls": 0}}, ValueError, "assistant.tool_calls must be at least 1"),
        (
            {"embedding": {"provider": "openai"}},
            ValueError,
            "embedding.provider must be one of ollama, hashing",
        ),
        ({"retrieval": {"top_k": 30}}, ValueError, "1 <= top_k <= candidates"),
        ({"knowledge_base": {"sources": []}}, ValueError, "knowledge_base.sources is empty"),
        ({"knowledge_base": {"sources": [{"code": "A"}]}}, ValueError, "needs exactly a code and a path"),
        (
            {"knowledge_base": {"sources": [{"code": "a", "path": "kb/a.md"}]}},
            ValueError,
            "written in capitals",
        ),
        ({"knowledge_base": {"sources": [{"code": "A", "path": "kb/b.md"}]}}, FileNotFoundError, "kb/b.md"),
    ]
    for change, error, message in cases:
        with pytest.raises(error, match=message):
            load(change)
