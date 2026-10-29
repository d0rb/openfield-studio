from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fill_links", ROOT / "scripts" / "fill_links.py")
fill_links = importlib.util.module_from_spec(spec)
sys.modules["fill_links"] = fill_links
spec.loader.exec_module(fill_links)

LINKS = ["--repo", "https://github.com/someone/openfield-studio", "--site", "https://someone.github.io/openfield-studio/",
         "--video", "https://youtu.be/abc123"]


def _docs(root: Path) -> None:
    (root / "docs").mkdir()
    (root / "README.md").write_text("**[Try it](<try-it link>)** · **[Demo](<video link>)**\n\ngit clone <repo link> && cd openfield-studio\n", encoding="utf-8")
    (root / "SUBMISSION.md").write_text("- Repository: `<repo link>`\n- Demo: `<video link>`\n", encoding="utf-8")
    (root / "docs" / "USING.md").write_text("Nothing to fill here.\n", encoding="utf-8")


def test_every_link_is_filled_and_the_gate_has_nothing_left(tmp_path):
    _docs(tmp_path)
    assert fill_links.main([*LINKS, "--root", str(tmp_path)]) == 0
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "**[Try it](https://someone.github.io/openfield-studio/)**" in readme
    assert "git clone https://github.com/someone/openfield-studio && cd openfield-studio" in readme
    assert "`https://youtu.be/abc123`" in (tmp_path / "SUBMISSION.md").read_text(encoding="utf-8")
    assert fill_links.remaining(tmp_path) == []


def test_a_dry_run_writes_nothing_and_a_bad_address_is_refused(tmp_path, capsys):
    _docs(tmp_path)
    before = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert fill_links.main([*LINKS, "--root", str(tmp_path), "--dry-run"]) == 0
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == before
    assert "would change" in capsys.readouterr().out
    bad = [*LINKS[:-1], "http://youtu.be/abc"]
    assert fill_links.main([*bad, "--root", str(tmp_path)]) == 2
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == before


def test_the_real_documents_wait_for_no_link_the_script_cannot_fill():
    """The documents have two honest states. Before publishing they carry the three placeholders and the release gate
    names them; after it they carry the real repository, site and video. What must hold either way is that nothing is
    waiting that `fill_links` would not know how to fill, since such a link would sit there until someone read it in
    the published page."""
    left = fill_links.remaining(ROOT)
    assert {line.rsplit(": ", 1)[1] for line in left} <= set(fill_links.PLACEHOLDERS)


def test_a_published_document_names_a_repository_and_a_place_to_watch():
    """Once the links are filled, the two documents a reader arrives at carry real addresses: somewhere to clone from
    and somewhere to watch. A filled document that names neither would pass the gate and still strand the reader."""
    if fill_links.remaining(ROOT):
        return  # not published yet; the test above covers that state
    for name in ("README.md", "SUBMISSION.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "https://github.com/" in text, f"{name} is filled but names no repository"
        assert any(f"https://{host}" in text for host in ("youtu.be/", "www.youtube.com/", "vimeo.com/", "d0rb.github.io/")), (
            f"{name} is filled but names nowhere to watch the demo")


def test_a_placeholder_the_gate_would_flag_is_never_called_filled(tmp_path):
    _docs(tmp_path)
    (tmp_path / "docs" / "USING.md").write_text("Watch it here: <tutorial link>\n", encoding="utf-8")
    assert fill_links.main([*LINKS, "--root", str(tmp_path)]) == 1, "an unknown link stays, and the script says so"
    assert fill_links.remaining(tmp_path) == ["docs/USING.md:1: <tutorial link>"]
