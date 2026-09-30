"""R10-06: pyproject.toml holds only the optional ``formats`` dependency group."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stylometry import loaders


def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_formats_group_lists_what_the_loaders_import():
    requirements = pyproject()["dependency-groups"]["formats"]
    names = {re.split(r"[<>=~!\[; ]", r, maxsplit=1)[0] for r in requirements}
    assert names == {"python-docx", "pypdf", "tree-sitter", "tree-sitter-typescript"}
    assert all(re.search(r">=\d", r) for r in requirements), "every entry carries a floor"


def test_pyproject_declares_nothing_but_dependency_groups():
    # ruff.toml, pytest.ini and .coveragerc keep configuring their tools; a [tool.*] table here
    # could change them. A [project] table would give find_requires_python a requires-python to
    # act on and turn on future_annotations_on_314 for this repository.
    assert set(pyproject()) == {"dependency-groups"}
    assert set(pyproject()["dependency-groups"]) == {"formats"}


def test_the_install_hint_names_the_group():
    assert "--group formats" in loaders.INSTALL_HINT


def test_this_repository_has_no_requires_python_for_the_detector_to_read():
    assert loaders.find_requires_python(ROOT) is None


def test_files_the_round_adds_are_not_swallowed_by_the_deny_by_default_gitignore():
    # .gitignore is "/*" plus an allowlist: a new top-level file or folder is ignored until it
    # is listed, silently. R10 met this twice (tools/, pyproject.toml).
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout")
    tools = sorted(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "tools").rglob("*.py")
        if "__pycache__" not in p.parts
    )
    done = subprocess.run(
        [git, "check-ignore", "--", "pyproject.toml", *tools],  # no -v: it reports negations too
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1, f"ignored by .gitignore:\n{done.stdout}"
