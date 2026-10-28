"""The demo scenario in the repository is the one the submission video is cut from: every take it opens is in the
bundle, every film it plays is beside it, the end card carries the publish-time links, and its words keep the house rules.
(Oct 26: the old scenario named two takes that had left the bundle and showed a verify card from an earlier week.)"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "scripts" / "ui" / "demo.scenario.json"
CLIPS = ROOT / "scripts" / "ui" / "clips"
TAKES = ROOT / "openfield" / "web" / "showcase" / "takes"


def _steps() -> list[dict]:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))["steps"]


def test_every_take_the_demo_opens_is_in_the_bundle():
    takes = sorted({s["take"] for s in _steps() if s.get("take")})
    assert takes, "the demo opens recorded takes"
    missing = [t for t in takes if not (TAKES / t / "receipt.json").is_file()]
    assert not missing, f"takes the demo names but the bundle lacks: {missing}"


def test_every_film_the_demo_plays_is_beside_it():
    films = sorted({s["src"] for s in _steps() if s.get("src")})
    assert films, "the demo plays the saved camera-path clip, a live render and the verify terminal"
    missing = [f for f in films if not (CLIPS / f).is_file()]
    assert not missing, f"films the demo plays but scripts/ui/clips lacks: {missing}"


def test_the_end_card_carries_the_links_and_the_words_keep_the_house_rules():
    text = SCENARIO.read_text(encoding="utf-8")
    assert "{try_url}" in text and "{repo_url}" in text, "the end card takes the site and repository links at record time"
    assert "open source" not in text.lower().replace("#opensourcehiggsfield", ""), 'models are "open weights"'
    assert not re.search(r"higgsfield", text.replace("#OpenSourceHiggsfield", ""), re.IGNORECASE), "named only as the hashtag"
    lines = [s for s in _steps() if s.get("do") == "say"]
    assert 4 <= len(lines) <= 8, f"a few short narration lines, not a voice-over: {len(lines)}"
