"""The pre-publish gate: it must catch what would embarrass a public repo, and stay quiet about the rest.

Sample leaks are assembled at run time on purpose: this file is itself scanned by the gate, so it must
not contain a contiguous token, key, address or user path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .test_scripts import load


@pytest.fixture(scope="module")
def rc():
    return load("release_check")


def scan(rc, text, deny=()):
    return rc.scan_text("file.txt", text, list(deny))


def ip(*octets):
    return ".".join(str(o) for o in octets)


def test_tokens_and_keys_are_caught(rc):
    token = "hf_" + "a1B2c3D4e5" * 4
    found = scan(rc, f"HF_TOKEN={token}\n")
    assert found["secrets"] and "Hugging Face token" in found["secrets"][0]
    assert token not in found["secrets"][0], "the finding must not echo the whole secret"
    assert scan(rc, "key = sk-" + "x" * 30)["secrets"]
    assert scan(rc, "ghp_" + "Z" * 36)["secrets"]
    assert scan(rc, "AKIA" + "ABCDEFGHIJKLMNOP")["secrets"]
    assert scan(rc, "-----BEGIN " + "OPENSSH PRIVATE KEY-----")["secrets"]
    assert scan(rc, 'api_key = "' + "abcdefghijklmnop1234" + '"')["secrets"]
    assert not scan(rc, "HF_TOKEN=<your read-only token>\nCOMFY_API_KEY=\n")["secrets"]
    assert not scan(rc, "export COMFY_API_KEY=your_key_here")["secrets"]


def test_email_addresses_are_personal_unless_obviously_fake(rc):
    assert scan(rc, "contact me at " + "someone.real" + "@" + "gmail.com")["personal"]
    for fine in ("a@example.com", "b@example.test", "12345+name@users.noreply.github.com",
                 "noreply@anthropic.com", "git@github.com:org/repo.git"):
        assert not scan(rc, fine)["personal"], fine


def test_absolute_user_paths_are_personal_but_scrubber_samples_and_urls_are_not(rc):
    name = "real" + "person"
    for leak in ("C:" + "\\Users\\" + name + "\\Videos", "C:" + "/Users/" + name + "/x", "/home/" + name + "/x",
                 "/Users/" + name + "/x", "/mnt/c/Users/" + name + "/x"):
        assert scan(rc, f'path = "{leak}"')["personal"], leak
    for fine in ("C:" + "\\Users\\Alex\\Videos", "/home/alex/x", "C:" + "\\Users\\John Smith\\a.mp4",
                 "https://example.com/home/x.png", "/Users/|/home/)([^", "see /home/runner/work"):
        assert not scan(rc, fine)["personal"], fine


def test_public_ip_addresses_are_personal_but_loopback_docs_and_versions_are_not(rc):
    odd = ip(203, 1, 2, 3)
    assert scan(rc, "ssh root@" + odd)["personal"] == [f"file.txt: IP address {odd}"]
    assert scan(rc, "host " + ip(8, 8, 8, 8))["personal"]
    for fine in ("127.0.0.1:8189", "0.0.0.0", "192.0.2.10", "198.51.100.7", "203.0.113.9",
                 "version 1.2.3", "v10.0.19045.1", "999.1.1.1", "255.255.255.255"):
        assert not scan(rc, fine)["personal"], fine


def test_the_local_denylist_supports_literals_and_regexes(rc):
    deny = ["Quux Handle", r"re:\bzed\b"]
    assert scan(rc, "made by quux handle", deny)["personal"]
    assert scan(rc, "by Zed, 2026", deny)["personal"]
    assert not scan(rc, "a zedoary and a bized", deny)["personal"], "regex entries respect word boundaries"
    assert not scan(rc, "nothing here", deny)["personal"]


def test_denylist_file_skips_blank_lines_and_comments(rc, tmp_path):
    (tmp_path / ".release-deny.txt").write_text("# my names\n\nalpha\n  beta  \n", encoding="utf-8")
    assert rc.load_denylist(tmp_path) == ["alpha", "beta"]
    assert rc.load_denylist(tmp_path / "nowhere") == []


def test_check_files_flags_weights_secret_files_and_oversize_files(rc, tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "MAX_FILE_BYTES", 1000)
    (tmp_path / "ok.py").write_text("print(1)")
    (tmp_path / ".env.example").write_text("X=")
    files = [tmp_path / "ok.py", tmp_path / ".env.example"]
    assert rc.check_files(tmp_path, files).state == "ok"

    for name, content in (("model.safetensors", b"x"), (".env", b"X=1"), (".env.local", b"X=1"),
                          ("deploy.pem", b"x"), ("huge.txt", b"x" * 2000)):
        (tmp_path / name).write_bytes(content)
        result = rc.check_files(tmp_path, [tmp_path / name])
        assert result.state == "FAIL" and name in result.items[0], name


def test_unfinished_markers_fail_only_in_the_public_documents(rc, tmp_path):
    (tmp_path / "docs").mkdir()
    readme = tmp_path / "README.md"
    notes = tmp_path / "docs" / "POD.md"
    code = tmp_path / "tool.py"
    submission = tmp_path / "SUBMISSION.md"
    marker = "TO" + "DO"
    readme.write_text("# OpenField\n\nAll good.\n")
    notes.write_text("Steps.\n")
    code.write_text(f"# {marker}(refactor) internal note\n")
    submission.write_text("- [ ] a checklist box is fine\n")
    files = [readme, notes, code, submission]
    assert rc.check_unfinished(tmp_path, files).state == "ok"

    readme.write_text(f"# OpenField\n\n<!-- {marker}(hero): add the clip -->\n")
    notes.write_text("Steps to be decided: " + "TB" + "D\n")
    result = rc.check_unfinished(tmp_path, files)
    assert result.state == "FAIL" and len(result.items) == 2
    assert result.items[0].startswith("README.md:3") and any("docs/POD.md:1" in i for i in result.items)


def test_binary_files_are_not_text_scanned(rc, tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"hf_" + b"a" * 40)
    (tmp_path / "blob.dat").write_bytes(b"\x00\x01hf_" + b"a" * 40)
    (tmp_path / "note.txt").write_text("fine")
    assert rc.read_text(tmp_path / "clip.mp4") is None
    assert rc.read_text(tmp_path / "blob.dat") is None
    assert rc.read_text(tmp_path / "note.txt") == "fine"


def test_without_git_the_walker_skips_environments_and_caches(rc, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x")
    for skipped in (".venv", "node_modules", "__pycache__", ".git"):
        (tmp_path / skipped).mkdir()
        (tmp_path / skipped / "junk.py").write_text("x")
    names = [p.relative_to(tmp_path).as_posix() for p in rc.addable_files(tmp_path)]
    assert names == ["src/a.py"]


def test_env_style_keys_are_caught_where_word_boundaries_used_to_miss_them(rc):
    key = "A1b2C3d4" + "E5f6G7h8"
    for leak in (f'COMFY_API_KEY="comfyui-{key}"', f"COMFY_API_KEY={key}", f"export HF_TOKEN: {key}",
                 f'{{"api_key": "{key}"}}', f"comfyui-{key}"):
        assert scan(rc, leak)["secrets"], leak
    for fine in ("COMFY_API_KEY=", "COMFY_API_KEY=<your key>", "HF_TOKEN=hf_...", "token = secrets.token_hex(6)",
                 "max_tokens=4096", 'password = os.environ["PASSWORD"]', "COMFY_API_KEY=your_key_here"):
        assert not scan(rc, fine)["secrets"], fine


def test_paths_inside_json_are_caught_in_their_escaped_form(rc):
    import json

    name = "real" + "person"
    escaped = json.dumps({"source": "C:" + "\\Users\\" + name + "\\clip.mp4"})
    assert "\\\\" in escaped, "the sample really is JSON-escaped"
    found = scan(rc, escaped)["personal"]
    assert found and name in found[0]
    assert not scan(rc, json.dumps({"source": "C:" + "\\Users\\Alex\\clip.mp4"}))["personal"]


def test_takes_made_on_the_fake_dev_stack_are_recognised(rc, tmp_path):
    import json

    def folder(name, *, label="GPU box", output="take.mp4"):
        path = tmp_path / name
        (path / "runs" / "01_hero").mkdir(parents=True)
        (path / "take.json").write_text(json.dumps({"backend": {"kind": "pod", "label": label}}))
        (path / "runs" / "01_hero" / "run.json").write_text(json.dumps({"outputs": [{"name": output}]}))
        return path

    assert rc.fake_stack_evidence(folder("real"), {"backend": {"label": "GPU box"}}) == []
    synthetic = rc.fake_stack_evidence(folder("synthetic", output="fake_00001_.mp4"), {})
    assert synthetic and "synthetic fake_ outputs" in synthetic[0]
    labelled = rc.fake_stack_evidence(folder("labelled"), {"backend": {"label": "FAKE dev stack (synthetic)"}})
    assert labelled and "fake dev stack" in labelled[0]
    assert rc.fake_stack_evidence(folder("task", label="FAKE dev stack"), {})


def test_the_repository_itself_has_no_personal_data_or_secrets(rc):
    """The same scan the gate runs, over what git would add right now."""
    root = Path(__file__).resolve().parents[1]
    files = rc.addable_files(root)
    results = rc.check_content(root, files)
    bad = [r for r in results if r.state == "FAIL"]
    assert not bad, [(r.name, r.items[:5]) for r in bad]
