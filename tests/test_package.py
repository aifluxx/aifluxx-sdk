import io
import tarfile
from pathlib import Path

from aifluxx_sdk.dev import _tarball
from aifluxx_sdk.package import LOCAL_META_DIRS, validate_package
from aifluxx_sdk.templates import get_template, render_spec

_LEAK = "token = 'supersecretvalue'\n"
_FAKE_KEY = 'API_KEY = "afx_dev_testkey_abcd"\n'


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


def test_secret_in_venv_is_ignored(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    venv = pkg / ".venv"
    venv.mkdir()
    (venv / "leak.txt").write_text("token = 'supersecretvalue'\n", encoding="utf-8")
    report = validate_package(pkg)
    assert report.ok
    assert not any(row.code == "secret_in_package" for row in report.findings)


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


def _archive_names(package: Path) -> set[str]:
    with tarfile.open(fileobj=io.BytesIO(_tarball(package)), mode="r:gz") as archive:
        return set(archive.getnames())


def _vendor_sdk(pkg: Path) -> None:
    """A bundled SDK tree whose README, example, fixtures, and egg-info look like secrets."""
    sdk = pkg / "sdk"
    (sdk / "examples").mkdir(parents=True)
    (sdk / "README.md").write_text(_LEAK, encoding="utf-8")
    (sdk / "examples" / "send_mail.py").write_text(_FAKE_KEY, encoding="utf-8")
    fixtures = sdk / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "keys.txt").write_text("afx_dev_testkey_abcd\n" + _FAKE_KEY, encoding="utf-8")
    egg = sdk / "src" / "aifluxx_sdk.egg-info"
    egg.mkdir(parents=True)
    (egg / "PKG-INFO").write_text(_LEAK, encoding="utf-8")


def test_vendored_sdk_egg_info_and_default_skips_are_omitted(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    _vendor_sdk(pkg)
    outside = pkg / "src" / "my_agent.egg-info"
    outside.mkdir(parents=True)
    (outside / "PKG-INFO").write_text(_LEAK, encoding="utf-8")
    (outside / "SOURCES.txt").write_text("afx_dev_testkey_abcd\n", encoding="utf-8")
    (pkg / "leak.egg-info").write_text(_LEAK, encoding="utf-8")
    (pkg / "notes.egg-info.txt").write_text("hello\n", encoding="utf-8")
    nested_venv = pkg / "src" / ".venv" / "lib"
    nested_venv.mkdir(parents=True)
    (nested_venv / "leak.txt").write_text(_LEAK, encoding="utf-8")
    for name in LOCAL_META_DIRS:
        meta = pkg / name
        meta.mkdir()
        (meta / "agent.lock").write_text(_LEAK, encoding="utf-8")
    (pkg / "keep.txt").write_text("hello\n", encoding="utf-8")
    (pkg / "logo.png").write_bytes(b"token = 'supersecretvalue'\n")

    report = validate_package(pkg)
    assert report.ok, [(row.code, row.path, row.note) for row in report.errors]
    names = _archive_names(pkg)
    assert "spec.yaml" in names
    assert "instructions.md" in names
    assert "keep.txt" in names
    assert "notes.egg-info.txt" in names
    assert "logo.png" in names
    assert not any(name == "sdk" or name.startswith("sdk/") for name in names)
    assert not any(part.endswith(".egg-info") for name in names for part in Path(name).parts)
    assert not any(".venv" in Path(name).parts for name in names)
    assert all(LOCAL_META_DIRS.isdisjoint(Path(name).parts) for name in names)


def test_secret_beside_vendored_sdk_is_reported(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    _vendor_sdk(pkg)
    (pkg / "notes.md").write_text(_LEAK, encoding="utf-8")
    report = validate_package(pkg)
    paths = [row.path for row in report.errors if row.code == "secret_in_package"]
    assert paths == ["notes.md"]


def test_nested_sdk_directory_is_still_scanned(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    nested = pkg / "tools" / "sdk"
    nested.mkdir(parents=True)
    (nested / "note.md").write_text(_LEAK, encoding="utf-8")
    report = validate_package(pkg)
    assert any(row.path == "tools/sdk/note.md" and row.code == "secret_in_package" for row in report.errors)
    assert "tools/sdk/note.md" in _archive_names(pkg)


def test_file_named_sdk_is_scanned(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    (pkg / "sdk").write_text(_LEAK, encoding="utf-8")
    report = validate_package(pkg)
    assert any(row.path == "sdk" and row.code == "secret_in_package" for row in report.errors)


def test_sdk_directory_match_is_case_sensitive(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    folder = pkg / "SDK"
    folder.mkdir()
    (folder / "README.md").write_text(_LEAK, encoding="utf-8")
    report = validate_package(pkg)
    assert any(row.code == "secret_in_package" and row.path == "SDK/README.md" for row in report.errors)


def test_aifluxxignore_excludes_paths_from_validate_and_upload(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    (pkg / ".aifluxxignore").write_text(
        "# comments and blank lines are ignored\n"
        "\n"
        "vendor/\n"
        "docs/*.md\n"
        "**/*.pem\n"
        "fixtures/*.txt\n",
        encoding="utf-8",
    )
    vendor = pkg / "vendor" / "nested"
    vendor.mkdir(parents=True)
    (vendor / "key.txt").write_text(_FAKE_KEY, encoding="utf-8")
    (pkg / "docs").mkdir()
    (pkg / "docs" / "secret.md").write_text(_LEAK, encoding="utf-8")
    (pkg / "docs" / "sub").mkdir()
    (pkg / "docs" / "sub" / "secret.md").write_text(_LEAK, encoding="utf-8")
    (pkg / "docs" / "sub" / "readme.txt").write_text("hello\n", encoding="utf-8")
    (pkg / "keys").mkdir()
    (pkg / "keys" / "id.pem").write_text(_LEAK, encoding="utf-8")
    (pkg / "root.pem").write_text(_LEAK, encoding="utf-8")
    fixtures = pkg / "fixtures"
    fixtures.mkdir()
    (fixtures / "keys.txt").write_text("afx_dev_testkey_abcd\n" + _LEAK, encoding="utf-8")
    (fixtures / "readme.md").write_text("hello\n", encoding="utf-8")
    (pkg / "keep.txt").write_text("hello\n", encoding="utf-8")

    report = validate_package(pkg)
    secret_paths = [row.path for row in report.errors if row.code == "secret_in_package"]
    assert secret_paths == ["docs/sub/secret.md"]
    names = _archive_names(pkg)
    assert ".aifluxxignore" in names
    assert "keep.txt" in names
    assert "docs/sub/secret.md" in names
    assert "docs/sub/readme.txt" in names
    assert "fixtures/readme.md" in names
    assert "docs/secret.md" not in names
    assert "keys/id.pem" not in names
    assert "root.pem" not in names
    assert "fixtures/keys.txt" not in names
    assert not any(name == "vendor" or name.startswith("vendor/") for name in names)


def test_aifluxxignore_rejects_parent_segments_and_negation(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    _vendor_sdk(pkg)
    (pkg / ".aifluxxignore").write_text("../outside\n!sdk/\nvendor/\n", encoding="utf-8")
    (pkg / "vendor").mkdir()
    (pkg / "vendor" / "key.txt").write_text(_LEAK, encoding="utf-8")
    report = validate_package(pkg)
    invalid = [row for row in report.errors if row.code == "exclude_invalid"]
    assert [row.note for row in invalid] == [
        "Line 1 must be a relative path pattern.",
        "Line 2 must be a relative path pattern.",
    ]
    assert not any(row.code == "secret_in_package" for row in report.errors)
    names = _archive_names(pkg)
    assert not any(name.startswith("vendor/") or name.startswith("sdk/") for name in names)


def test_aifluxxignore_accepts_backslashes(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    (pkg / ".aifluxxignore").write_text("private\\keys.txt\n", encoding="utf-8")
    (pkg / "private").mkdir()
    (pkg / "private" / "keys.txt").write_text(_LEAK, encoding="utf-8")
    (pkg / "private" / "keep.txt").write_text("hello\n", encoding="utf-8")
    report = validate_package(pkg)
    assert report.ok, [(row.code, row.path, row.note) for row in report.errors]
    names = _archive_names(pkg)
    assert "private/keys.txt" not in names
    assert "private/keep.txt" in names


def test_aifluxxignore_must_be_utf8(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    _vendor_sdk(pkg)
    (pkg / ".aifluxxignore").write_bytes(b"\xff\xfe\n")
    report = validate_package(pkg)
    assert any(row.code == "exclude_unreadable" and row.path == ".aifluxxignore" for row in report.errors)
    assert not any(row.code == "secret_in_package" for row in report.errors)


def test_directory_symlink_is_not_packaged(tmp_path: Path):
    pkg = _write_ok(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.txt").write_text(_LEAK, encoding="utf-8")
    (pkg / "linked").symlink_to(outside, target_is_directory=True)
    report = validate_package(pkg)
    assert report.ok, [(row.code, row.path) for row in report.errors]
    assert not any(name.startswith("linked/") for name in _archive_names(pkg))


def test_readme_documents_aifluxxignore():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert ".aifluxxignore" in readme
    assert "top-level `sdk/`" in readme
    assert "*.egg-info" in readme
    changelog = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 1.3.1 - 2026-10-31" in changelog
    assert ".aifluxxignore" in changelog
