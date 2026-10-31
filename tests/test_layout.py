"""Layout file format, diff, and the project-folder write allow-list."""
from pathlib import Path

import pytest

from aifluxx_sdk.exceptions import AifluxxError
from aifluxx_sdk.layout import (
    LAYOUT_FILENAME,
    WIRING_FILENAME,
    apply_writes,
    canonicalize,
    default_layout,
    files_from_reply,
    format_changes,
    layout_changes,
    project_write_path,
    proposed_writes,
    serialize_layout,
    serialize_wiring,
)

_FIXTURE = Path(__file__).resolve().parents[1] / "src" / "aifluxx_sdk" / "starter_ui" / "tests" / "fixtures" / "default-layout.json"
_RESIZED = Path(__file__).resolve().parents[1] / "src" / "aifluxx_sdk" / "starter_ui" / "tests" / "fixtures" / "resized-layout.json"


def test_default_layout_matches_the_starter_ui_fixture():
    text = serialize_layout(default_layout())
    assert text == _FIXTURE.read_text(encoding="utf-8")
    assert text.endswith("\n")
    again = serialize_layout(canonicalize(default_layout()))
    assert again == text


def test_resize_packs_side_by_side_and_matches_fixture():
    layout = default_layout()
    for item in layout["screens"]["Run"]:
        if item["id"] in {"agent-picker", "prompt"}:
            item["w"] = 6
    packed = canonicalize(layout)
    run = {item["id"]: item for item in packed["screens"]["Run"]}
    assert (run["agent-picker"]["col"], run["agent-picker"]["row"], run["agent-picker"]["w"]) == (1, 1, 6)
    assert (run["prompt"]["col"], run["prompt"]["row"], run["prompt"]["w"]) == (7, 1, 6)
    assert run["run-action"]["row"] == 4
    assert serialize_layout(packed) == _RESIZED.read_text(encoding="utf-8")


def test_reorder_is_a_stable_diff():
    layout = default_layout()
    rows = layout["screens"]["Run"]
    history = next(item for item in rows if item["id"] == "history")
    rest = [item for item in rows if item["id"] != "history"]
    layout["screens"]["Run"] = [history, *rest]
    changes = layout_changes(default_layout(), layout)
    kinds = [change["change"] for change in changes if change["screen"] == "Run"]
    assert "reordered" in kinds
    text = format_changes(changes)
    assert "history" in text
    assert text.splitlines()[0].startswith("Run: order ")


def test_wiring_follows_layout_order_and_targets():
    text = serialize_wiring(default_layout())
    assert '"target": "agent.run"' in text
    assert text.index("agent-picker") < text.index("prompt")
    assert text.endswith("\n")


def test_reply_fence_is_optional():
    assert files_from_reply("No files here.") == []
    assert files_from_reply("```aifluxx-files\nnot-json\n```") == []
    found = files_from_reply(
        'Note.\n```aifluxx-files\n{"files":[{"path":"instructions.md","content":"Be brief.\\n"}]}\n```\n'
    )
    assert found == [("instructions.md", "Be brief.\n")]


def test_proposed_writes_keep_layout_wiring_and_skip_escapes():
    reply = """
```aifluxx-files
{"files":[
  {"path":"../secrets.txt","content":"nope"},
  {"path":"/tmp/x","content":"nope"},
  {"path":"aifluxx.wiring.json","content":"{\\"schema\\":\\"ignored\\"}\\n"},
  {"path":"instructions.md","content":"Be brief.\\n"},
  {"path":"ui/Panel.tsx","content":"export {}\\n"},
  {"path":"run.sh","content":"echo hi\\n"}
]}
```
"""
    writes, skipped = proposed_writes(default_layout(), reply)
    paths = [path for path, _content in writes]
    assert paths[0] == WIRING_FILENAME
    assert "instructions.md" in paths
    assert "ui/Panel.tsx" in paths
    assert "run.sh" not in paths
    assert "../secrets.txt" not in paths
    wiring = next(content for path, content in writes if path == WIRING_FILENAME)
    assert "ignored" not in wiring
    assert skipped
    assert any("run.sh" in note for note in skipped)


def test_apply_writes_stay_inside_the_project(tmp_path: Path):
    project = tmp_path / "pkg"
    project.mkdir()
    (project / "spec.yaml").write_text("slug: pkg\n", encoding="utf-8")
    written = apply_writes(
        project,
        [
            (WIRING_FILENAME, serialize_wiring(default_layout())),
            ("ui/Panel.tsx", "export {}\n"),
            ("instructions.md", "Be brief.\n"),
        ],
    )
    assert (project / WIRING_FILENAME).is_file()
    assert (project / "ui" / "Panel.tsx").read_text(encoding="utf-8") == "export {}\n"
    assert (project / "instructions.md").read_text(encoding="utf-8") == "Be brief.\n"
    assert all(path.is_relative_to(project.resolve()) for path in written)
    for relative in ("../secrets.txt", "/etc/passwd", "run.sh", "ui/../../outside.txt", "~/.ssh/authorized_keys"):
        with pytest.raises(AifluxxError):
            project_write_path(project, relative)
    assert not (tmp_path / "secrets.txt").exists()
    assert not (tmp_path / "outside.txt").exists()


def test_layout_filename_is_the_project_file():
    assert LAYOUT_FILENAME == "aifluxx.layout.json"
