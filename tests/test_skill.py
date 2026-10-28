"""The director skill (skills/openfield-director/SKILL.md) names only tools the MCP server has and keeps the house words."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "openfield-director" / "SKILL.md"
MCP_DOC = ROOT / "docs" / "MCP.md"


def _frontmatter(text: str) -> dict[str, str]:
    head = text.split("---", 2)
    assert len(head) >= 3 and head[0] == "", "the skill starts with a frontmatter block"
    return dict(line.split(":", 1) for line in head[1].strip().splitlines() if ":" in line)


def test_skill_has_a_name_and_a_description():
    meta = _frontmatter(SKILL.read_text(encoding="utf-8"))
    assert meta["name"].strip() == "openfield-director"
    assert len(meta["description"].strip()) > 40


def test_skill_names_only_tools_the_server_documents():
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", MCP_DOC.read_text(encoding="utf-8"), re.M))
    assert len(documented) >= 20, "docs/MCP.md lists the tools in its table"
    named = set(re.findall(r"`([a-z_]+)`", SKILL.read_text(encoding="utf-8")))
    tools = {n for n in named if "_" in n and n not in {"auto_approve", "max_renders", "focal_length_mm"}}
    assert tools <= documented, f"the skill names tools the server does not have: {sorted(tools - documented)}"
    for required in ("studio_status", "list_options", "plan_shot", "direct_shot", "wait_for_take", "approve_stills", "get_receipt"):
        assert required in tools, required


def test_skill_keeps_the_house_words():
    text = SKILL.read_text(encoding="utf-8")
    low = text.lower().replace("open-source", "open source")
    assert low.count("open source") == low.count('not "open source"'), "the words appear only as the thing not to say"
    assert "higgsfield" not in text.lower()
    assert "docs/MCP.md" in text
