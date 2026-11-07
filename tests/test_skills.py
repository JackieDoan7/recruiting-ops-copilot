"""Every skill must load in Claude: valid frontmatter, a short description, and scripts that exist."""
import re

import pytest

from conftest import SKILLS

SKILL_DIRS = sorted(p.parent for p in SKILLS.glob("*/SKILL.md"))


def frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must start with --- frontmatter ---"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


def test_four_skills():
    assert [d.name for d in SKILL_DIRS] == ["onsite-scheduler", "pipeline-pulse", "supply-autopilot",
                                            "talent-research"]


@pytest.mark.parametrize("skill", SKILL_DIRS, ids=lambda p: p.name)
def test_frontmatter(skill):
    meta = frontmatter((skill / "SKILL.md").read_text())
    assert meta["name"] == skill.name
    assert re.fullmatch(r"[a-z0-9-]{1,64}", meta["name"])
    assert 20 < len(meta["description"]) <= 200, "claude.ai limits skill descriptions to 200 characters"
    assert "<" not in meta["description"] and ">" not in meta["description"]


@pytest.mark.parametrize("skill", SKILL_DIRS, ids=lambda p: p.name)
def test_referenced_files_exist(skill):
    text = (skill / "SKILL.md").read_text()
    for ref in re.findall(r"`((?:scripts|references|examples|rubrics|apps-script)/[\w./-]+)`", text):
        assert (skill / ref).exists(), f"{skill.name}/SKILL.md mentions {ref}, which doesn't exist"
