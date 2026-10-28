"""The cast store: the user's own members plus the read-only shelf of bundled (showcase) characters."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from openfield.cast import CastError, CastStore
from openfield.ledger import write_json


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 120, 40)).save(buf, "PNG")
    return buf.getvalue()


def shelve(root, cast_id, name, created="2026-10-01T00:00:00Z"):
    folder = root / cast_id
    (folder / "refs").mkdir(parents=True)
    (folder / "refs" / "ref_1.png").write_bytes(png())
    write_json(folder / "cast.json", {
        "id": cast_id, "name": name, "kind": "character", "consent": "fictional",
        "consent_text": "These are AI-generated or fictional.", "created_at": created,
        "refs": [{"file": "ref_1.png", "faces": 1}], "face_check": True})
    return folder


def test_bundled_members_are_listed_served_and_kept(tmp_path):
    shelf = tmp_path / "showcase" / "cast"
    shelve(shelf, "ca_0000aaaa", "Mara")
    store = CastStore(tmp_path / "own", None, shelf=[shelf, tmp_path / "missing-shelf"])
    mine = store.create("Oskar", "character", "fictional", [("o.png", png())])

    listed = store.list()
    assert [c["name"] for c in listed] == ["Oskar", "Mara"], "newest first, the user's own member made just now"
    assert listed[1]["bundled"] is True and "bundled" not in listed[0]
    assert store.get("ca_0000aaaa")["bundled"] is True
    assert store.ref_file("ca_0000aaaa", "ref_1.png") == shelf / "ca_0000aaaa" / "refs" / "ref_1.png"
    assert store.ref_paths("ca_0000aaaa") == [shelf / "ca_0000aaaa" / "refs" / "ref_1.png"]
    assert store.ref_paths(mine["id"])[0].parent.parent == tmp_path / "own" / mine["id"]

    with pytest.raises(CastError, match="cannot be deleted"):
        store.delete("ca_0000aaaa")
    assert (shelf / "ca_0000aaaa" / "cast.json").is_file()
    store.delete(mine["id"])
    assert [c["id"] for c in store.list()] == ["ca_0000aaaa"]


def test_the_users_own_member_wins_over_a_bundled_one_with_the_same_id(tmp_path):
    shelf = tmp_path / "shelf"
    shelve(shelf, "ca_0000bbbb", "Shelf copy")
    own = tmp_path / "own"
    shelve(own, "ca_0000bbbb", "My copy")
    store = CastStore(own, None, shelf=[shelf])
    assert [c["name"] for c in store.list()] == ["My copy"]
    assert "bundled" not in store.get("ca_0000bbbb")
