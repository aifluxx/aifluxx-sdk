"""Wheel, sdist, and editable install include the SDK source files."""
from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import textwrap
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_WHEEL_FILES = (
    "aifluxx_sdk/__init__.py",
    "aifluxx_sdk/cli.py",
    "aifluxx_sdk/templates.py",
    "aifluxx_sdk/py.typed",
    "aifluxx_sdk/starter_ui/package.json",
    "aifluxx_sdk/starter_ui/.env.example",
    "aifluxx_sdk/starter_ui/.gitignore",
    "aifluxx_sdk/starter_ui/src/App.tsx",
    "aifluxx_sdk/_source_root/README.md",
    "aifluxx_sdk/_source_root/pyproject.toml",
    "aifluxx_sdk/_source_root/LICENSE",
    "aifluxx_sdk/_source_root/setup.py",
    "aifluxx_sdk/_source_root/MANIFEST.in",
    "aifluxx_sdk/_source_root/examples/README.md",
    "aifluxx_sdk/_source_root/examples/send_mail.py",
)

_SDIST_FILES = (
    "README.md",
    "pyproject.toml",
    "LICENSE",
    "setup.py",
    "MANIFEST.in",
    "examples/README.md",
    "examples/send_mail.py",
    "src/aifluxx_sdk/templates.py",
    "src/aifluxx_sdk/cli.py",
    "src/aifluxx_sdk/py.typed",
    "src/aifluxx_sdk/starter_ui/package.json",
    "src/aifluxx_sdk/starter_ui/.env.example",
    "src/aifluxx_sdk/starter_ui/.gitignore",
)


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"{cmd} failed ({result.returncode})\n{result.stdout}")
    return result.stdout


def _scripts(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def _exe(venv: Path, name: str) -> Path:
    scripts = _scripts(venv)
    if os.name == "nt":
        return scripts / f"{name}.exe"
    return scripts / name


@pytest.fixture(scope="module")
def dist_paths(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    assert not (REPO / "src" / "aifluxx_sdk" / "_source_root").exists()
    out = tmp_path_factory.mktemp("dist")
    log = _run([sys.executable, "-m", "build", "--outdir", str(out)], cwd=REPO)
    assert "Package would be ignored" not in log
    assert "no previously-included files" not in log
    assert not (REPO / "src" / "aifluxx_sdk" / "_source_root").exists()
    wheels = list(out.glob("*.whl"))
    sdists = list(out.glob("*.tar.gz"))
    assert len(wheels) == 1, wheels
    assert len(sdists) == 1, sdists
    return {"wheel": wheels[0], "sdist": sdists[0]}


def test_wheel_contains_package_data_and_source_root(dist_paths: dict[str, Path]):
    with zipfile.ZipFile(dist_paths["wheel"]) as archive:
        names = set(archive.namelist())
    missing = [name for name in _WHEEL_FILES if name not in names]
    assert missing == [], missing
    assert not any(name.endswith(".pyc") or "/__pycache__/" in name for name in names)
    with zipfile.ZipFile(dist_paths["wheel"]) as archive:
        readme = archive.read("aifluxx_sdk/_source_root/README.md")
        templates = archive.read("aifluxx_sdk/templates.py")
    assert readme == (REPO / "README.md").read_bytes()
    assert templates == (REPO / "src" / "aifluxx_sdk" / "templates.py").read_bytes()
    assert b"TEMPLATES" in templates


def test_sdist_contains_source_files(dist_paths: dict[str, Path]):
    with tarfile.open(dist_paths["sdist"], "r:gz") as archive:
        names = set(archive.getnames())
    prefix = dist_paths["sdist"].name[: -len(".tar.gz")] + "/"
    missing = [name for name in _SDIST_FILES if prefix + name not in names]
    assert missing == [], missing
    assert not any(name.endswith(".pyc") or "/__pycache__/" in name for name in names)


def test_editable_install_exposes_templates_and_starter_ui(tmp_path: Path):
    venv = tmp_path / "venv"
    _run([sys.executable, "-m", "venv", str(venv)])
    _run([str(_exe(venv, "pip")), "install", "-e", str(REPO)])
    assert not (REPO / "src" / "aifluxx_sdk" / "_source_root").exists()
    script = tmp_path / "check_editable.py"
    script.write_text(
        textwrap.dedent(
            """
            import aifluxx_sdk
            import aifluxx_sdk.templates
            from importlib.resources import files
            from pathlib import Path

            pkg = Path(aifluxx_sdk.__file__).resolve().parent
            assert pkg.parent.name == "src", pkg
            assert (pkg / "templates.py").is_file()
            assert (pkg / "starter_ui" / "package.json").is_file()
            assert (pkg / "starter_ui" / ".env.example").is_file()
            assert (pkg / "starter_ui" / ".gitignore").is_file()
            assert "compliance" in aifluxx_sdk.templates.TEMPLATES
            bundled = files("aifluxx_sdk")
            assert bundled.joinpath("templates.py").is_file()
            assert bundled.joinpath("starter_ui", "package.json").is_file()
            assert bundled.joinpath("starter_ui", ".env.example").read_text(encoding="utf-8")
            assert not (pkg / "_source_root").exists()
            assert aifluxx_sdk.__version__ == "1.3.0"
            print("editable-ok")
            """
        ),
        encoding="utf-8",
    )
    out = _run([str(_exe(venv, "python")), str(script)])
    assert "editable-ok" in out
    dest = tmp_path / "from-editable"
    _run([str(_exe(venv, "aifluxx")), "source", str(dest)])
    assert (dest / "src" / "aifluxx_sdk" / "templates.py").is_file()
    assert (dest / "src" / "aifluxx_sdk" / "starter_ui" / "package.json").is_file()
    assert (dest / "examples" / "send_mail.py").is_file()
    assert (dest / "pyproject.toml").is_file()
    assert not (dest / "src" / "aifluxx_sdk" / "_source_root").exists()


def test_wheel_install_source_command(dist_paths: dict[str, Path], tmp_path: Path):
    venv = tmp_path / "venv"
    _run([sys.executable, "-m", "venv", str(venv)])
    _run([str(_exe(venv, "pip")), "install", str(dist_paths["wheel"])])
    script = tmp_path / "check_wheel.py"
    script.write_text(
        textwrap.dedent(
            """
            import aifluxx_sdk.templates
            from aifluxx_sdk.source import package_dir

            pkg = package_dir()
            assert pkg.parent.name == "site-packages", pkg
            bundle = pkg / "_source_root"
            assert (bundle / "README.md").is_file()
            assert (bundle / "pyproject.toml").is_file()
            assert (bundle / "LICENSE").is_file()
            assert (bundle / "examples" / "send_mail.py").is_file()
            assert (pkg / "templates.py").is_file()
            assert (pkg / "starter_ui" / "package.json").is_file()
            assert (pkg / "starter_ui" / ".env.example").is_file()
            assert "compliance" in aifluxx_sdk.templates.TEMPLATES
            print("wheel-install-ok")
            """
        ),
        encoding="utf-8",
    )
    installed = _run([str(_exe(venv, "python")), str(script)])
    assert "wheel-install-ok" in installed
    dest = tmp_path / "from-wheel"
    _run([str(_exe(venv, "aifluxx")), "source", str(dest)])
    compare = tmp_path / "compare.py"
    compare.write_text(
        textwrap.dedent(
            """
            import sys
            from pathlib import Path
            from aifluxx_sdk.source import package_dir

            dest = Path(sys.argv[1])
            pkg = package_dir()
            bundle = pkg / "_source_root"
            assert (dest / "src" / "aifluxx_sdk" / "templates.py").read_bytes() == (pkg / "templates.py").read_bytes()
            assert (dest / "README.md").read_bytes() == (bundle / "README.md").read_bytes()
            assert (dest / "examples" / "send_mail.py").read_bytes() == (bundle / "examples" / "send_mail.py").read_bytes()
            assert (dest / "src" / "aifluxx_sdk" / "starter_ui" / "package.json").read_bytes() == (
                pkg / "starter_ui" / "package.json"
            ).read_bytes()
            assert not (dest / "src" / "aifluxx_sdk" / "_source_root").exists()
            print("wheel-source-ok")
            """
        ),
        encoding="utf-8",
    )
    compared = _run([str(_exe(venv, "python")), str(compare), str(dest)])
    assert "wheel-source-ok" in compared
    assert (dest / "pyproject.toml").is_file()
    assert (dest / "LICENSE").is_file()
    assert (dest / "src" / "aifluxx_sdk" / "starter_ui" / ".env.example").is_file()
    assert (dest / "src" / "aifluxx_sdk" / "starter_ui" / ".gitignore").is_file()
    refused = subprocess.run(
        [str(_exe(venv, "aifluxx")), "source", str(dest)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert refused.returncode == 1
    assert "not empty" in refused.stdout
