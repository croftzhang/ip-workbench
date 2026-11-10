"""Documents and code stay in step.

The requirement documents name functions, tests, commands, files, parameter
values and results. Each check below fails when one of those names or numbers
no longer matches the product, so a document cannot drift from the code
without the build saying so.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest
import typer
import yaml
from typer.testing import CliRunner

from ipw.classic import cli

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DOCUMENTS = [*sorted(DOCS.glob("*.md")), ROOT / "README.md"]

# Named in the release 2 roadmap and design; not built yet.
PLANNED_PATHS = ("src/ipw/agent/", "src/ipw/mcp/", "tests/agent/", "config/agent.yaml", "docs/EVALUATION.md")
REPOSITORY_FOLDERS = ("config/", "data/", "docs/", "scripts/", "src/", "tests/", ".github/")


def read(name: str) -> str:
    path = ROOT / name if name == "README.md" else DOCS / name
    return path.read_text(encoding="utf-8")


def code_spans(text: str) -> set[str]:
    """Inline code in a document, ignoring fenced blocks."""
    return set(re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S)))


def has_number(text: str, figure: str) -> bool:
    """True if the figure appears as a whole number, with the same sign."""
    return re.search(rf"(?<![\d.,-]){re.escape(figure)}(?!\d|[.,]\d)", text) is not None


# --------------------------------------------------------------------------- names


def test_functions() -> set[str]:
    names = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names |= {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    return {name for name in names if name.startswith("test_")}


test_functions.__test__ = False  # a helper, not a test


def resolves(dotted: str) -> bool:
    """Import the longest module prefix, then follow the remaining attributes."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            target = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        for name in parts[cut:]:
            if hasattr(target, name):
                target = getattr(target, name)
            elif name in getattr(target, "__dataclass_fields__", {}):
                return True
            else:
                return False
        return True
    return False


def command_problem(text: str, group) -> str | None:
    """Why `ipw ...` as written in a document would not run, or None."""
    words = text.split()[1:]
    if any("<" in word for word in words):
        return None  # a usage pattern such as `ipw <command> --help`
    command = None
    options = {opt for param in group.params for opt in param.opts}
    for word in words:
        if command is None and word in group.commands:
            command = group.commands[word]
            options = {opt for param in command.params for opt in param.opts}
        elif re.fullmatch(r"--?[A-Za-z][\w-]*", word) and word not in options:
            return f"unknown option {word}"
    if words and command is None:
        return "no known command"
    return None


def test_spec_references_exist():
    """Every test, function, command, option and file a document names exists."""
    tests = test_functions()
    group = typer.main.get_command(cli.app)
    every_option = {opt for param in group.params for opt in param.opts}
    every_option |= {opt for cmd in group.commands.values() for param in cmd.params for opt in param.opts}

    problems = []
    for document in DOCUMENTS:
        for span in sorted(code_spans(document.read_text(encoding="utf-8"))):
            where = f"{document.name}: `{span}`"
            if re.fullmatch(r"test_\w+", span):
                if span not in tests:
                    problems.append(f"{where} is not a test")
            elif re.fullmatch(r"ipw(\.\w+)+", span):
                if not resolves(span):
                    problems.append(f"{where} does not resolve")
            elif span == "ipw" or span.startswith("ipw "):
                problem = command_problem(span, group)
                if problem:
                    problems.append(f"{where}: {problem}")
            elif re.fullmatch(r"--?[A-Za-z][\w-]*( \S+)?", span):
                if span.split()[0] not in every_option:
                    problems.append(f"{where} is not an option of any command")
            elif span.startswith(REPOSITORY_FOLDERS) and not span.startswith(PLANNED_PATHS):
                if not (ROOT / span).exists():
                    problems.append(f"{where} does not exist")
    assert not problems, "\n".join(problems)


def test_the_check_itself_catches_a_bad_reference():
    """The resolver and the command check reject names that are not there."""
    group = typer.main.get_command(cli.app)
    assert resolves("ipw.core.curve.Curve.forward_par")
    assert not resolves("ipw.core.curve.Curve.no_such_method")
    assert not resolves("ipw.core.no_such_module.Thing")
    assert command_problem("ipw hedge -t 4.5 --mode krd", group) is None
    assert command_problem("ipw -f json limits", group) is None
    assert command_problem("ipw hedge --no-such-option", group) == "unknown option --no-such-option"
    assert command_problem("ipw nosuchcommand", group) == "no known command"
    assert has_number("AOCI -225.99 against", "-225.99")
    assert not has_number("AOCI -225.99 against", "225.99")
    assert not has_number("duration 15.30", "5.30")


def slug(heading: str) -> str:
    """Anchor GitHub gives a heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def test_document_links_resolve():
    """Relative links between documents point at files and headings that exist."""
    problems = []
    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        for target, anchor in re.findall(r"\]\(([^)#\s]*)(#[^)\s]+)?\)", text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path = (document.parent / target).resolve() if target else document
            if not path.exists():
                problems.append(f"{document.name}: link to {target} does not exist")
            elif anchor and path.suffix == ".md":
                headings = re.findall(r"^#+ (.+)$", path.read_text(encoding="utf-8"), flags=re.M)
                if anchor[1:] not in {slug(h) for h in headings}:
                    problems.append(f"{document.name}: no heading {anchor} in {path.name}")
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------- parameters


def documented_parameters() -> dict[str, float]:
    section = read("FUNCTIONAL_SPEC.md").split("\n## Model parameters")[1].split("\n## ")[0]
    values = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 5 and re.fullmatch(r"`\w+`", cells[0]):
            values[cells[0].strip("`")] = float(cells[2])
    return values


def documented_list(name: str) -> list[float]:
    section = read("FUNCTIONAL_SPEC.md").split("\n## Model parameters")[1].split("\n## ")[0]
    match = re.search(rf"`{name}`,.*?\bis ([\d.,\sand]+?)(?:, which| years)", section, flags=re.S)
    assert match, f"no sentence giving the values of {name}"
    return [float(number) for number in re.findall(r"\d+(?:\.\d+)?", match.group(1))]


def configured_parameters() -> tuple[dict[str, float], dict[str, list[float]]]:
    scalars, lists = {}, {}

    def walk(node: dict) -> None:
        for key, value in node.items():
            if isinstance(value, dict):
                walk(value)
            elif isinstance(value, list):
                lists[key] = [float(item) for item in value]
            else:
                scalars[key] = float(value)

    walk(yaml.safe_load((ROOT / "config" / "model.yaml").read_text(encoding="utf-8")))
    return scalars, lists


def test_spec_parameter_values_match_the_configuration():
    """The parameter table in the specification is config/model.yaml, value for value."""
    documented = documented_parameters()
    scalars, lists = configured_parameters()
    assert documented.keys() == scalars.keys()
    wrong = {k: (documented[k], scalars[k]) for k in scalars if documented[k] != pytest.approx(scalars[k])}
    assert not wrong, f"specification and configuration differ (documented, configured): {wrong}"
    for name, values in lists.items():
        assert documented_list(name) == pytest.approx(values), name


# ------------------------------------------------------------- requirement numbers

KINDS = "BR|RULE|NFR|SD|FR|US|UAT"


def cited(text: str) -> set[str]:
    """Requirement numbers a text refers to, with ranges such as BR-1 to BR-10 filled in."""
    found = {f"{kind}-{number}" for kind, number in re.findall(rf"\b({KINDS})-(\d+)\b", text)}
    for kind, first, last in re.findall(rf"\b({KINDS})-(\d+) to \1-(\d+)\b", text):
        found |= {f"{kind}-{number}" for number in range(int(first), int(last) + 1)}
    return found


def of_kind(ids: set[str], kind: str) -> set[str]:
    return {i for i in ids if i.startswith(kind + "-")}


@pytest.fixture(scope="module")
def defined() -> dict[str, set[str]]:
    """Where each kind of number is introduced."""
    brd, design, spec = read("BRD.md"), read("SOLUTION_DESIGN.md"), read("FUNCTIONAL_SPEC.md")
    return {
        "BR": set(re.findall(r"^\| (BR-\d+) \|", brd, flags=re.M)),
        "RULE": set(re.findall(r"^\| (RULE-\d+) \|", brd, flags=re.M)),
        "NFR": set(re.findall(r"^\| (NFR-\d+) \|", brd, flags=re.M)),
        "SD": set(re.findall(r"^### (SD-\d+)\.", design, flags=re.M)),
        "FR": set(re.findall(r"^## (FR-\d+) ", spec, flags=re.M)),
        "US": set(re.findall(r"^\| (US-\d+) \| As ", read("PRD.md"), flags=re.M)),
        "UAT": set(re.findall(r"^### (UAT-\d+) ", read("UAT.md"), flags=re.M)),
    }


def test_every_cited_requirement_number_is_defined(defined):
    known = set().union(*defined.values())
    unknown = {doc.name: sorted(cited(doc.read_text(encoding="utf-8")) - known) for doc in DOCUMENTS}
    assert not {name: ids for name, ids in unknown.items() if ids}


def test_requirements_are_carried_through_every_document(defined):
    """Need to design to function to story to acceptance, with no number left behind."""
    brd, design, spec = read("BRD.md"), read("SOLUTION_DESIGN.md"), read("FUNCTIONAL_SPEC.md")
    stories, backlog, acceptance = read("PRD.md"), read("BACKLOG.md"), read("UAT.md")

    release_1 = set(re.findall(r"^\| (BR-\d+) \|.*\| 1 \|$", brd, flags=re.M))
    release_2 = set(re.findall(r"^\| (BR-\d+) \|.*\| 2 \|$", brd, flags=re.M))
    assert release_1 and release_2 and release_1 | release_2 == defined["BR"]

    matrix = spec.split("\n## Traceability matrix")[1].split("\n## ")[0]
    gaps = {
        "release 1 needs without a design decision": release_1 - cited(design),
        "release 1 needs missing from the traceability matrix": release_1 - cited(matrix),
        "release 1 needs without an acceptance case": release_1 - cited(acceptance),
        "needs without a user story": defined["BR"] - cited(stories),
        "needs missing from the backlog": defined["BR"] - cited(backlog),
        "business rules the design does not address": defined["RULE"] - cited(design),
        "business rules the specification does not implement": defined["RULE"] - cited(spec),
        "quality requirements the specification does not answer": defined["NFR"] - cited(spec),
        "quality requirements without an acceptance case": defined["NFR"] - cited(acceptance),
        "design decisions the specification does not implement": defined["SD"] - cited(spec),
        "stories missing from the backlog": defined["US"] - cited(backlog),
        "backlog items that are not stories": of_kind(cited(backlog), "US") - defined["US"],
    }
    assert not {what: sorted(ids) for what, ids in gaps.items() if ids}


def display_formulas(text: str) -> list[str]:
    """Bodies of the fenced math blocks of a document."""
    return re.findall(r"^```math\n(.*?)\n```$", text, flags=re.S | re.M)


def inline_formulas(text: str) -> list[str]:
    """Inline formulas, delimiters included, outside fenced blocks."""
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    return [match.group(0) for match in re.finditer(r"(?<!\$)\$[^$\n]+?\$(?!\$)", prose)]


def test_equation_numbers_are_unique_ordered_and_resolved():
    spec = read("FUNCTIONAL_SPEC.md")
    tags = re.findall(r"\\qquad \\text\{\((\d+\.\d+)\)\}", "\n".join(display_formulas(spec)))
    assert tags, "no numbered equations found"
    assert len(tags) == len(set(tags)), "an equation number is used twice"
    assert tags == sorted(tags, key=lambda tag: tuple(int(part) for part in tag.split(".")))
    for name in ("FUNCTIONAL_SPEC.md", "MODEL.md"):
        prose = re.sub(r"```.*?```", "", read(name), flags=re.S)
        dangling = set(re.findall(r"\((\d{1,2}\.\d{1,2})\)", prose)) - set(tags)
        assert not dangling, f"{name} refers to equations that do not exist: {sorted(dangling)}"


def test_formulas_are_written_the_way_github_renders_them():
    """Display formulas in math fences; nothing GitHub's renderer is known to mishandle.

    GitHub lays out an equation carrying a tag command as a one-character column, and
    Markdown reads asterisks, and backslashes before punctuation, inside dollar
    signs. Display formulas therefore sit in math fences, where Markdown does not
    look, and carry their number as text.
    """
    problems = []
    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        if "$$" in text:
            problems.append(f"{document.name}: display formula in dollar signs; use a math fence")
        for formula in display_formulas(text) + inline_formulas(text):
            for banned in ("\\tag{", "\\operatorname", "*", "<", ">"):
                if banned in formula:
                    problems.append(f"{document.name}: {banned} in {formula[:60]}")
    assert not problems, "\n".join(problems)


def test_inline_formulas_survive_a_plain_markdown_parser():
    """No inline formula is changed by Markdown: no emphasis formed inside it, no escape consumed."""
    markdown_it = pytest.importorskip("markdown_it")
    parser = markdown_it.MarkdownIt("commonmark").enable("table")

    def flat(children) -> str:
        kept = {
            "text": lambda c: c.content,
            "softbreak": lambda c: " ",
            "code_inline": lambda c: f"`{c.content}`",
        }
        return "".join(kept[c.type](c) if c.type in kept else "\x00" for c in children or [])

    altered = []
    for document in DOCUMENTS:
        text = re.sub(r"```.*?```", "", document.read_text(encoding="utf-8"), flags=re.S)
        for token in parser.parse(text):
            if token.type == "inline" and "$" in token.content:
                seen = flat(token.children)
                for formula in inline_formulas(token.content):
                    if formula not in seen:
                        altered.append(f"{document.name}: {formula}")
    assert not altered, "\n".join(altered)


# ------------------------------------------------------------- acceptance figures

# Case, command, and the figures the acceptance script expects the command to show.
ACCEPTANCE = [
    ("UAT-01", ["summary"], ["88", "10,000.0", "10,149.3", "8,909.3", "-1,240.1"]),
    ("UAT-01", ["summary", "--by", "designation"], ["-65.2", "-1,174.9"]),
    ("UAT-01", ["position", "FN30-2.5-001"], ["79.19"]),
    ("UAT-02", ["risk"], ["6.01", "-0.71", "5.30"]),
    ("UAT-02", ["krd"], ["6.01", "5.30"]),
    ("UAT-03", ["scenario", "-n", "up_200"], ["-416.6", "-575.6", "119.3", "-226.0", "4.93"]),
    ("UAT-03", ["nii"], ["103.6", "122.1", "82.6"]),
    ("UAT-04", ["prepay"], ["3.9", "6.6", "16.1"]),
    ("UAT-04", ["prepay", "--s-curve"], ["3.9", "8.9", "29.0"]),
    ("UAT-04", ["scenario", "-n", "prepay_fast", "-n", "prepay_slow"], ["67.3", "-74.5"]),
    ("UAT-05", ["limits"], ["-225.99", "-210.00", "108", "84"]),
    (
        "UAT-06",
        ["fix", "AOCI_UP200"],
        ["570.0", "260.0", "150.0", "-209.98", "-209.40", "-209.62", "-1.5", "-1.0"],
    ),
    ("UAT-07", ["hedge", "-t", "4.5"], ["1,614.0", "5.30", "4.50"]),
    ("UAT-07", ["hedge", "-t", "4.5", "--mode", "krd", "--tenors", "2,5,10"], ["318.2", "486.7", "555.8"]),
    ("UAT-08", ["whatif", "--pay-fixed", "5:260"], ["-225.99", "-209.40", "5.17", "103.64", "102.61"]),
    ("UAT-08", ["whatif", "--drop", "FN30-2.5-001"], ["8,909.27", "8,838.79", "-70.48"]),
    ("UAT-09", ["explain"], ["-38.80", "-29.29", "-0.24", "0.22", "-9.49"]),
    ("UAT-10", ["brief", "--stdout"], ["7 OK, 1 WARN, 1 BREACH"]),
]


@pytest.mark.parametrize(
    ("case", "command", "figures"), ACCEPTANCE, ids=[f"{case} {' '.join(cmd)}" for case, cmd, _ in ACCEPTANCE]
)
def test_acceptance_script_figures_match_the_engine(case, command, figures, root):
    """Each figure is in the acceptance case as written and in what the command prints."""
    script = read("UAT.md")
    section = script.split(f"\n### {case} ")[1].split("\n### ")[0]
    assert f"`ipw {' '.join(command)}`".replace(" --stdout", "") in section, "command is not in the case"

    result = CliRunner().invoke(cli.app, ["--root", str(root), *command])
    assert result.exit_code == 0, result.output
    for figure in figures:
        assert has_number(section, figure), f"{case} no longer expects {figure}"
        assert has_number(result.output, figure), f"`ipw {' '.join(command)}` no longer shows {figure}"


def test_acceptance_script_refusals_are_refused(root, monkeypatch, capsys):
    """UAT-06 and UAT-13: the commands the script expects to fail do fail, in one line."""
    for command in (["fix", "NII_UP100"], ["fix", "HTM_SHARE", "--target", "50"], ["position", "NOPE"]):
        assert f"`ipw {' '.join(command)}`" in read("UAT.md")
        monkeypatch.setattr("sys.argv", ["ipw", "--root", str(root), *command])
        with pytest.raises(SystemExit) as stop:
            cli.main()
        message = capsys.readouterr().err
        assert stop.value.code == 1
        assert message.startswith("Error:") and "Traceback" not in message


def test_documents_state_the_stored_result_count_and_the_brief_layout(wb):
    """Counts quoted in the documents: stored results, scenarios, limits, brief sections."""
    import json

    from ipw.classic.brief import build_brief

    stored = len(json.loads((ROOT / "tests" / "golden.json").read_text(encoding="utf-8")))
    assert f"{stored} results of the sample book" in read("FUNCTIONAL_SPEC.md")
    assert len(re.findall(r"^## \d+\. ", build_brief(wb), flags=re.M)) == 10
    assert "ten numbered sections" in read("UAT.md")
    assert len(wb.limit_report()) == 9 and "Nine limits" in read("UAT.md")
