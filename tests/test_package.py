from pathlib import Path

from aifluxx_sdk.package import validate_package
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
    meta = pkg / ".aifluxx"
    meta.mkdir()
    (meta / "agent.lock").write_text("token = 'supersecretvalue'\n", encoding="utf-8")
    report = validate_package(pkg)
    assert report.ok


def test_secret_in_package(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    (pkg / "notes.md").write_text("token = 'supersecretvalue'\n", encoding="utf-8")
    report = validate_package(pkg)
    assert any(row.code == "secret_in_package" for row in report.errors)


def test_nested_subagent(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    spec = (pkg / "spec.yaml").read_text(encoding="utf-8")
    (pkg / "spec.yaml").write_text(spec + "subagents:\n  - subagents/checker\n", encoding="utf-8")
    child = pkg / "subagents" / "checker"
    child.mkdir(parents=True)
    (child / "spec.yaml").write_text(
        "schema: truest/agent/v1\nname: Checker\ntrigger:\n  type: chat\n",
        encoding="utf-8",
    )
    (child / "instructions.md").write_text("Check citations.\n", encoding="utf-8")
    report = validate_package(pkg)
    assert any(row.code == "nested_subagent" for row in report.errors)
