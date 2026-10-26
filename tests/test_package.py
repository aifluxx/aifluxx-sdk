from pathlib import Path

from aifluxx_sdk.package import LOCAL_META_DIRS, validate_package
from aifluxx_sdk.templates import get_template, render_spec


def _write_ok(root: Path) -> Path:
    pkg = root / "uae-board-pack-assistant"
    pkg.mkdir()
    tmpl = get_template("compliance")
    (pkg / "spec.yaml").write_text(render_spec("uae-board-pack-assistant", tmpl), encoding="utf-8")
    (pkg / "instructions.md").write_text(tmpl.instructions, encoding="utf-8")
    return pkg


def test_valid_template_package(tmp_path: Path):
    report = validate_package(_write_ok(tmp_path))
    assert report.ok
    assert report.spec["slug"] == "uae-board-pack-assistant"
    assert report.spec["schema"] == "aifluxx/agent/v1"
    tools = report.spec["tools"]
    assert tools == ["list_obligations"]
    assert "list_compliance_obligations" not in tools
    assert "get_compliance_status" not in tools


def test_host_catalogue_rejects_tools_outside_it(tmp_path: Path):
    report = validate_package(_write_ok(tmp_path), read_tools=frozenset({"get_document"}))
    assert any(row.code == "unknown_tool" and "list_obligations" in row.note for row in report.errors)
    assert any("host tool catalogue" in row.note for row in report.errors)


def test_missing_instructions(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    (pkg / "instructions.md").write_text("  \n", encoding="utf-8")
    report = validate_package(pkg)
    assert not report.ok
    assert any(row.code == "missing_instructions" for row in report.errors)


def test_write_tool_not_allowed(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    spec = (pkg / "spec.yaml").read_text(encoding="utf-8")
    (pkg / "spec.yaml").write_text(spec.replace("tools:\n", "tools:\n  - send_mail\n"), encoding="utf-8")
    report = validate_package(pkg)
    assert any(row.code == "write_tool_not_allowed" for row in report.errors)


def test_secret_in_local_meta_is_ignored(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    assert ".aifluxx" in LOCAL_META_DIRS
    assert len(LOCAL_META_DIRS) >= 2
    for name in LOCAL_META_DIRS:
        meta = pkg / name
        meta.mkdir()
        (meta / "agent.lock").write_text("token = 'supersecretvalue'\n", encoding="utf-8")
    report = validate_package(pkg)
    assert report.ok


def test_secret_in_package(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    (pkg / "notes.md").write_text("token = 'supersecretvalue'\n", encoding="utf-8")
    report = validate_package(pkg)
    assert any(row.code == "secret_in_package" for row in report.errors)


def test_known_tool_alias_suggests_replacement(tmp_path: Path):
    pkg = tmp_path / "snapshot"
    pkg.mkdir()
    tmpl = get_template("account-snapshot")
    (pkg / "spec.yaml").write_text(render_spec("snapshot", tmpl), encoding="utf-8")
    (pkg / "instructions.md").write_text(tmpl.instructions, encoding="utf-8")
    spec = (pkg / "spec.yaml").read_text(encoding="utf-8")
    (pkg / "spec.yaml").write_text(spec.replace("search_company_knowledge", "search_documents"), encoding="utf-8")
    report = validate_package(pkg)
    assert not report.ok
    notes = " ".join(row.note for row in report.findings if row.code == "unknown_tool")
    assert "search_documents" in notes
    assert "search_company_knowledge" in notes
    host = validate_package(
        pkg,
        read_tools=frozenset({"search_company_knowledge", "get_document", "list_mandate_tasks", "list_contacts"}),
    )
    host_notes = " ".join(row.note for row in host.findings if row.code == "unknown_tool")
    assert "Use search_company_knowledge" in host_notes


def test_templates_pass_host_company_knowledge_catalogue(tmp_path: Path):
    from aifluxx_sdk.templates import TEMPLATES

    host = frozenset(
        {
            "search_company_knowledge",
            "get_document",
            "list_obligations",
            "ask_assistant",
            "ask_truest",
            "list_mandate_tasks",
            "list_contacts",
            "list_businesses",
        }
    )
    for name, template in TEMPLATES.items():
        pkg = tmp_path / name
        pkg.mkdir()
        (pkg / "spec.yaml").write_text(render_spec(name, template), encoding="utf-8")
        (pkg / "instructions.md").write_text(template.instructions, encoding="utf-8")
        report = validate_package(pkg, read_tools=host)
        assert report.ok, (name, [row.note for row in report.errors])


def test_nested_subagent(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    spec = (pkg / "spec.yaml").read_text(encoding="utf-8")
    (pkg / "spec.yaml").write_text(spec + "subagents:\n  - subagents/checker\n", encoding="utf-8")
    child = pkg / "subagents" / "checker"
    child.mkdir(parents=True)
    (child / "spec.yaml").write_text(
        "schema: aifluxx/agent/v1\nname: Checker\ntrigger:\n  type: chat\n",
        encoding="utf-8",
    )
    (child / "instructions.md").write_text("Check citations.\n", encoding="utf-8")
    report = validate_package(pkg)
    assert any(row.code == "nested_subagent" for row in report.errors)
