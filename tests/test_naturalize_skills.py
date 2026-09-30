"""The two skills that put the stylometry tools in reach of any Claude Code session.

Their bodies double as documentation, so these tests keep the prose honest: the flags and signal
names they mention must exist, the ones that exist must be mentioned, and the skills must reach
the repo (the .gitignore is deny-by-default) and the installer.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SKILLS = ROOT / "skills"
sys.path.insert(0, str(TOOLS))

import detect_ai_patterns as detect
import measure_skill_effectiveness as measure
import naturalize as cli
from stylometry import CATEGORY
from stylometry import naturalize as engine

NEW = ("naturalize", "detect-ai-patterns")
FALLBACK = r"E:\Projetos\Scripts\watermarks-remover"


def body(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def flags(parser) -> set[str]:
    return {s for a in parser._actions for s in a.option_strings if s.startswith("--")} - {"--help"}


def mentioned(text: str) -> set[str]:
    return set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", text))


@pytest.mark.parametrize("name", NEW)
def test_the_frontmatter_is_valid_yaml_with_the_fields_a_skill_needs(name: str):
    yaml = pytest.importorskip("yaml")
    text = body(name)
    assert text.startswith("---\n")
    front = yaml.safe_load(text.split("---\n")[1])
    assert set(front) == {"name", "description"}
    assert front["name"] == name == (SKILLS / name).name
    assert 100 < len(front["description"]) <= 1024
    assert f"/{name}" in front["description"]
    assert "Use quando" in front["description"]


@pytest.mark.parametrize("name", NEW)
def test_the_skill_locates_the_repo_the_way_the_installed_cmd_does(name: str):
    text = body(name)
    assert "WATERMARKS_REPO" in text
    assert FALLBACK in text  # the same hard-coded fallback as watermarks-server.cmd
    assert "REPO=" in (ROOT / "watermarks-server.cmd").read_text(encoding="utf-8")


def test_naturalize_documents_exactly_the_flags_the_cli_has():
    text = body("naturalize")
    assert flags(cli.build_parser()) <= mentioned(text)
    # the other flags it mentions belong to the tools it tells you to run next
    others = flags(detect.build_parser()) | flags(measure.build_parser()) | {"--group"}
    assert mentioned(text) <= flags(cli.build_parser()) | others


def test_detect_documents_exactly_the_flags_the_cli_has():
    text = body("detect-ai-patterns")
    assert flags(detect.build_parser()) <= mentioned(text)
    # "--stylometry" is the service's own flag, named to tell the two tools apart
    others = flags(cli.build_parser()) | flags(measure.build_parser()) | {"--group", "--stylometry"}
    assert mentioned(text) <= flags(detect.build_parser()) | others


def test_naturalize_lists_every_transformation_and_nothing_else():
    text = body("naturalize")
    table = text.split("## O que muda")[1].split("## O que nunca muda")[0]
    rows = set(re.findall(r"^\| `(\w+)`", table, re.MULTILINE))
    assert rows == set(engine.TRANSFORMS)
    assert rows <= set(CATEGORY)


def test_detect_lists_every_signal_the_detector_has():
    text = body("detect-ai-patterns")
    catalogue = text.split("## Catálogo de sinais")[1].split("## Regras ao reportar")[0]
    documented = set(re.findall(r"`(\w+)`", catalogue))
    assert set(CATEGORY) <= documented, sorted(set(CATEGORY) - documented)
    assert len(CATEGORY) == 37


def test_the_documented_exit_codes_are_the_real_ones():
    naturalize = body("naturalize")
    assert "**0** mudou algo" in naturalize and "**3** nada aplicável" in naturalize
    assert "**2** formato não suportado" in naturalize and "**1** caminho inexistente" in naturalize
    detect_doc = body("detect-ai-patterns")
    assert "**0** rodou" in detect_doc and "**2** nada foi analisado" in detect_doc


def test_git_does_not_ignore_a_skill_folder():
    # .gitignore is "/*" plus an allowlist: a skill added under skills/ is ignored, silently,
    # until it is listed. R10 met this twice, R11 once (skills/naturalize).
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout")
    files = sorted(
        p.relative_to(ROOT).as_posix()
        for p in SKILLS.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    done = subprocess.run(
        [git, "check-ignore", "--", *files],  # no -v: it reports negations too
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1, f"ignored by .gitignore:\n{done.stdout}"


@pytest.mark.parametrize("name", NEW)
def test_the_installer_copies_the_skill_to_claude_code(name: str, tmp_path: Path):
    home = tmp_path / ".claude"
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "install_skill.py"),
            "--skill",
            name,
            "--cursor-home",
            str(home),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    installed = home / "skills" / name / "SKILL.md"
    assert installed.read_bytes() == (SKILLS / name / "SKILL.md").read_bytes()
