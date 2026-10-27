"""Lock `aifluxx init` scaffolds to GET /api/dev/templates."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from aifluxx_sdk.cli import app
from aifluxx_sdk.templates import TEMPLATES, TEMPLATE_ALIASES, get_template, render_spec, template_rows
from tests.api_template_contract import API_TEMPLATES, tools_for_host

runner = CliRunner()

_TRUEST_URL = "https://api.truest.ae"
_AIFLUXX_URLS = (None, "https://api.aifluxx.co.za", "https://dev.developer.aifluxx.co.za", "https://api.truest.example")


def _spec_tools(text: str) -> list[str]:
    spec = yaml.safe_load(text)
    return list(spec["tools"])


def test_scaffolds_match_the_api_template_list():
    assert {row["id"] for row in API_TEMPLATES} == set(TEMPLATES)
    alias_map = {str(alias): str(row["id"]) for row in API_TEMPLATES for alias in row["aliases"]}  # type: ignore[union-attr]
    assert TEMPLATE_ALIASES == alias_map
    for row in API_TEMPLATES:
        name = str(row["id"])
        template = TEMPLATES[name]
        assert template.tools == row["tools"]
        assert get_template(name) is template
        for alias in row["aliases"]:  # type: ignore[union-attr]
            assert get_template(str(alias)) is template
        assert _spec_tools(render_spec(name, template)) == list(row["tools"])
        listed = next(item for item in template_rows() if item["template"] == name)
        assert listed["tools"] == list(row["tools"])
        assert listed["aliases"] == sorted(row["aliases"])  # type: ignore[arg-type]


def test_ask_tool_follows_the_api_host():
    for row in API_TEMPLATES:
        template = get_template(str(row["id"]))
        truest_tools = list(tools_for_host(row, truest_host=True))
        assert _spec_tools(render_spec("agent", template, api_url=_TRUEST_URL)) == truest_tools
        assert _spec_tools(render_spec("agent", template, api_url="https://dev.developer.truest.ae")) == truest_tools
        assert _spec_tools(render_spec("agent", template, api_url="https://API.TRUEST.AE.")) == truest_tools
        for url in _AIFLUXX_URLS:
            assert _spec_tools(render_spec("agent", template, api_url=url)) == list(row["tools"])


@pytest.mark.parametrize("row", API_TEMPLATES, ids=lambda row: str(row["id"]))
def test_init_accepts_every_api_alias(tmp_path: Path, monkeypatch, row: dict[str, object]):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    names = [str(row["id"]), *[str(alias) for alias in row["aliases"]]]  # type: ignore[union-attr]
    for name in names:
        slug = f"pkg-{name}"
        result = runner.invoke(app, ["init", slug, "--template", name])
        assert result.exit_code == 0, result.output
        spec = (tmp_path / slug / "spec.yaml").read_text(encoding="utf-8")
        assert _spec_tools(spec) == list(row["tools"])
        assert "truest" not in spec.lower()
        assert "truest" not in (tmp_path / slug / "instructions.md").read_text(encoding="utf-8").lower()
        assert "truest" not in (tmp_path / slug / "README.md").read_text(encoding="utf-8").lower()


def test_init_on_truest_platform_env_writes_that_hosts_ask_tool(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    monkeypatch.setenv("AIFLUXX_PLATFORM", "truest")
    monkeypatch.setenv("AIFLUXX_ENV", "dev")
    monkeypatch.setenv("AIFLUXX_CONFIG", str(tmp_path / "missing-config.json"))
    result = runner.invoke(app, ["init", "finance-agent", "-t", "finance"])
    assert result.exit_code == 0, result.output
    spec = (tmp_path / "finance-agent" / "spec.yaml").read_text(encoding="utf-8")
    assert _spec_tools(spec) == ["ask_truest"]
    assert "aifluxx.co.za" not in result.output


def test_init_on_a_truest_host_writes_that_hosts_ask_tool(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    monkeypatch.setenv("AIFLUXX_API_URL", _TRUEST_URL)
    result = runner.invoke(app, ["init", "finance-agent", "-t", "finance-summariser"])
    assert result.exit_code == 0, result.output
    spec = (tmp_path / "finance-agent" / "spec.yaml").read_text(encoding="utf-8")
    assert _spec_tools(spec) == ["ask_truest"]
    listed = runner.invoke(app, ["init", "--list", "--json"])
    payload = json.loads(listed.output)
    finance = next(row for row in payload if row["template"] == "finance")
    qa = next(row for row in payload if row["template"] == "qa-over-documents")
    compliance = next(row for row in payload if row["template"] == "compliance")
    assert finance["tools"] == ["ask_truest"]
    assert qa["tools"] == ["search_company_knowledge", "ask_truest"]
    assert compliance["tools"] == ["list_obligations"]


def test_default_init_output_does_not_name_the_other_brand(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AIFLUXX_API_URL", raising=False)
    monkeypatch.setenv("AIFLUXX_CREDENTIALS", str(tmp_path / "missing-credentials"))
    listed = runner.invoke(app, ["init", "--list"])
    help_result = runner.invoke(app, ["init", "--help"])
    created = runner.invoke(app, ["init", "board", "-t", "qa-documents"])
    assert listed.exit_code == 0, listed.output
    assert created.exit_code == 0, created.output
    spec = (tmp_path / "board" / "spec.yaml").read_text(encoding="utf-8")
    help_text = re.sub(r"\x1b\[[0-9;]*m", "", help_result.output)
    for mark in ("│", "╭", "╮", "╰", "╯", "─"):
        help_text = help_text.replace(mark, " ")
    help_text = " ".join(help_text.split())
    for text in (listed.output, help_result.output, spec, created.output):
        assert "truest" not in text.lower()
    assert "ask_assistant" in spec
    assert "qa-documents is an alias for qa-over-documents" in help_text
    assert "finance-summariser is an alias for finance" in help_text
