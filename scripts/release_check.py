#!/usr/bin/env python3
"""Pre-publish gate. Nothing in this repo is published until this passes and a person says go.

    python scripts/release_check.py [--min-takes 6] [--root .] [--json]

    files       nothing git would add is over 95 MB, a model weight, a key file or a .env
    secrets     no API token or private key pattern in any text file
    personal    no email addresses, absolute user paths, public IP addresses, or anything listed in
                .release-deny.txt (one literal per line, or re:<regex>; untracked: put your own names and handles there)
    unfinished  no TODO( / FIXME / TBD markers in README.md, SUBMISSION.md or docs/
    product     the web app, every workflow template, enough recorded takes with valid receipts,
                and a static export that builds
    licences    LICENSE is present and THIRD_PARTY_MODELS.md matches the model registry
    git         warns about a dirty tree and about commit email addresses that are not GitHub no-reply

Exit status is 0 only when nothing failed. Warnings never fail the run but should be read.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAX_FILE_BYTES = 95 * 1024 * 1024
MAX_EXPORT_BYTES = 950_000_000  # GitHub Pages: "Published GitHub Pages sites may be no larger than 1 GB"; 50 MB of room
WEIGHT_SUFFIXES = {".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".onnx", ".bin"}
KEY_NAMES = {".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}
KEY_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
BINARY_SUFFIXES = {".mp4", ".webm", ".mov", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".zip", ".woff", ".woff2",
                   ".ttf", ".otf", ".ico", ".pdf", ".onnx", ".safetensors"}
PROSE_UNFINISHED = re.compile(r"TODO\(|FIXME|\bTBD\b|lorem ipsum|"
                              r"\[(?:TESTED\?|UI\?|UPSCALE\?|TAKE\?|FILL[^\]]*|GPU|COST|N(?: [a-z]+)?)\]",  # draft placeholders
                              re.IGNORECASE)
PLACEHOLDER_LINK = re.compile(r"<[a-z][a-z -]* link>")  # "(<try-it link>)": a link still to be filled in

SECRET_PATTERNS = {
    "Hugging Face token": re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Comfy API key": re.compile(r"\bcomfyui-[A-Za-z0-9]{16,}"),
    # NAME=value or NAME: "value" for key/token/secret/password names, quoted or not, with names such as
    # COMFY_API_KEY (an underscore is not a word boundary, so no \b before the name). The value must be long,
    # contain a digit, and not look like a placeholder or a function call.
    "credential assignment": re.compile(
        r"(?i)(?<![A-Za-z0-9])(?:[a-z0-9]+[_-])*(?:api[_-]?key|token|secret|password)\b[\"']?\s*[:=]\s*[\"']?"
        r"(?![<$%{(])(?=[A-Za-z0-9_\-./+]*\d)[A-Za-z0-9_\-./+]{16,}"),
}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_OK = re.compile(r"(@example\.(?:com|org|net|test)$|@users\.noreply\.github\.com$|^noreply@anthropic\.com$"
                      r"|^git@github\.com$)", re.IGNORECASE)
USER_PATH = re.compile(
    r"(?:(?<![\w.\-])(?:[A-Za-z]:[\\/]Users[\\/]|/Users/|/home/)|/mnt/[a-z]/Users/)([A-Za-z0-9_][^\\/\s\"'<>:]*)")
USER_OK = {"alex", "john", "john smith", "public", "default", "user", "you", "yourname", "name", "me", "runner",
           "ubuntu", "example", "someone", "<user>", "username", "$user", "%username%", "~"}
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")


@dataclass
class Result:
    name: str
    state: str  # ok | warn | FAIL
    detail: str = ""
    items: list[str] = field(default_factory=list)


def addable_files(root: Path) -> list[Path]:
    """Files git would add (tracked + untracked, minus ignored); a plain walk outside a repository."""
    if (root / ".git").exists():
        done = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root, capture_output=True, check=False)
        if done.returncode == 0:
            names = [n for n in done.stdout.decode("utf-8", "replace").split("\0") if n]
            return sorted(root / n for n in names if (root / n).is_file())
    skip = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
    return sorted(p for p in root.rglob("*") if p.is_file() and not skip.intersection(p.relative_to(root).parts))


def read_text(path: Path) -> str | None:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


def load_denylist(root: Path) -> list[str]:
    path = root / ".release-deny.txt"
    if not path.is_file():
        return []
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]


def public_ip(text: str) -> bool:
    octets = [int(n) for n in text.split(".")]
    if any(n > 255 for n in octets):
        return False
    first, second = octets[0], octets[1]
    if first in {0, 127} or octets == [255, 255, 255, 255]:
        return False
    if (first, second) in {(192, 0), (198, 51), (203, 0)}:  # documentation ranges
        return False
    return True


def scan_text(rel: str, text: str, deny: list[str]) -> dict[str, list[str]]:
    """Findings per category for one file's text."""
    found: dict[str, list[str]] = {"secrets": [], "personal": []}
    for label, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(text):
            found["secrets"].append(f"{rel}: {label} ({match.group(0)[:6]}...)")
    for match in EMAIL.finditer(text):
        if not EMAIL_OK.search(match.group(0)):
            found["personal"].append(f"{rel}: email address {match.group(0)}")
    # JSON doubles every backslash in a Windows path, which the pattern would not see: look at both spellings
    seen_paths: set[str] = set()
    for source in (text, text.replace("\\\\", "\\")):
        for match in USER_PATH.finditer(source):
            if match.group(1).lower() not in USER_OK and match.group(0) not in seen_paths:
                seen_paths.add(match.group(0))
                found["personal"].append(f"{rel}: user path {match.group(0)}")
    for match in IPV4.finditer(text):
        if public_ip(match.group(0)):
            found["personal"].append(f"{rel}: IP address {match.group(0)}")
    lowered = text.lower()
    for entry in deny:
        if entry.startswith("re:"):
            hit = re.search(entry[3:], text, re.IGNORECASE) is not None
        else:
            hit = entry.lower() in lowered
        if hit:
            found["personal"].append(f"{rel}: contains {entry!r} from .release-deny.txt")
    return found


def check_files(root: Path, files: list[Path]) -> Result:
    problems = []
    total = 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES:
            problems.append(f"{rel}: {size / 1_048_576:.0f} MB is over GitHub's 100 MB limit")
        if path.suffix.lower() in WEIGHT_SUFFIXES:
            problems.append(f"{rel}: a model weight file must never be committed")
        if path.name in KEY_NAMES or path.name.startswith(".env.") and path.name != ".env.example" \
                or path.suffix.lower() in KEY_SUFFIXES:
            problems.append(f"{rel}: looks like a secret file")
    if problems:
        return Result("files", "FAIL", f"{len(problems)} problem(s)", problems)
    return Result("files", "ok", f"{len(files)} files, {total / 1_000_000:.1f} MB")


def check_content(root: Path, files: list[Path]) -> list[Result]:
    deny = load_denylist(root)
    secrets: list[str] = []
    personal: list[str] = []
    for path in files:
        text = read_text(path)
        if text is None:
            continue
        found = scan_text(path.relative_to(root).as_posix(), text, deny)
        secrets += found["secrets"]
        personal += found["personal"]
    results = [
        Result("secrets", "FAIL", f"{len(secrets)} finding(s)", secrets) if secrets
        else Result("secrets", "ok", "no token or key patterns"),
        Result("personal", "FAIL", f"{len(personal)} finding(s)", personal) if personal
        else Result("personal", "ok", "no emails, user paths or public IPs"),
    ]
    if not deny:
        results.append(Result(
            "denylist", "warn",
            "no .release-deny.txt: list your own name, handles and emails there (one per line, never committed) "
            "so they are searched for too"))
    return results


def check_unfinished(root: Path, files: list[Path]) -> Result:
    docs = [p for p in files if p.suffix.lower() == ".md"
            and (p.parent == root and p.name in {"README.md", "SUBMISSION.md", "PRODUCT.md"}
                 or p.relative_to(root).as_posix() in {"showcase/README.md", "openfield/workflows/README.md"}
                 or "docs" in p.relative_to(root).parts)]
    hits = []
    prose = False
    for path in docs:
        for number, line in enumerate((read_text(path) or "").splitlines(), start=1):
            if PROSE_UNFINISHED.search(line) or PLACEHOLDER_LINK.search(line):
                hits.append(f"{path.relative_to(root).as_posix()}:{number}: {line.strip()[:90]}")
                prose = prose or bool(PROSE_UNFINISHED.search(line))
    if hits and not prose:  # only the links that exist once the project is published
        return Result("unfinished", "FAIL", f"{len(hits)} link(s) to fill at publish time: "
                      "python scripts/fill_links.py --repo <url> --site <url> --video <url>", hits)
    if hits:
        return Result("unfinished", "FAIL", f"{len(hits)} marker(s)", hits)
    return Result("unfinished", "ok", f"{len(docs)} documents checked")


def fake_stack_evidence(folder: Path, receipt: dict) -> list[str]:
    """Signs that a take was made on the offline dev stack (scripts/dev_fake_stack.py), never on a real model.

    Its outputs are synthetic test patterns; a showcase made of them would be a lie. The fake API names its
    files fake_NNNNN_, and the dev stack labels its backend FAKE.
    """
    problems: list[str] = []
    label = str((receipt.get("backend") or {}).get("label", ""))
    try:
        take = json.loads((folder / "take.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        take = {}
    label += " " + str((take.get("backend") or {}).get("label", ""))
    if "fake" in label.lower():
        problems.append(f"{folder.name}: recorded on the fake dev stack (backend label {label.strip()!r})")
    for run_json in sorted(folder.glob("runs/*/run.json")):
        try:
            outputs = json.loads(run_json.read_text(encoding="utf-8")).get("outputs", [])
        except (OSError, ValueError, AttributeError):
            continue
        if any(str(o.get("name", "")).startswith("fake_") for o in outputs if isinstance(o, dict)):
            problems.append(f"{folder.name}: {run_json.parent.name} holds synthetic fake_ outputs")
            break
    return problems


def check_export_size(folder: Path, limit: int | None = None) -> Result:
    """The hosted export must fit GitHub Pages: its published sites may be no larger than 1 GB."""
    limit = MAX_EXPORT_BYTES if limit is None else limit
    total = sum(path.stat().st_size for path in Path(folder).rglob("*") if path.is_file())
    megabytes = total / 1_000_000
    if total > limit:
        return Result("static export size", "FAIL",
                      f"{megabytes:.1f} MB is over the {limit / 1_000_000:.0f} MB limit "
                      "(GitHub Pages allows up to 1 GB)")
    return Result("static export size", "ok", f"{megabytes:.1f} MB (GitHub Pages allows up to 1 GB)")


def hosted_smoke(root: Path, site: Path) -> Result:
    """The hosted copy's browser smoke test on the full export. The test suite runs it on a small fixture set, which cannot show
    what only the whole bundle shows: on October 26 two of the five Cast members were missing from the bundle, so the hero's
    Recreate read "Needs a backend" on the hosted copy, and only a full export caught it."""
    import shutil
    import socket
    import time
    import urllib.request
    node = shutil.which("node")
    if not node:
        return Result("hosted smoke", "warn", "node is not on PATH, so the browser check did not run")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--directory", str(site), "--bind", "127.0.0.1"],
                              cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "static/manifest.json", timeout=1).read(1)
                break
            except OSError:
                time.sleep(0.1)
        done = subprocess.run([node, str(root / "tests" / "ui" / "smoke.mjs"), "static", url],
                              capture_output=True, text=True, cwd=root, check=False, timeout=900)
    except subprocess.TimeoutExpired:
        return Result("hosted smoke", "FAIL", "the browser check did not finish in 15 minutes")
    finally:
        server.terminate()
        server.wait(timeout=10)
    lines = (done.stdout + done.stderr).splitlines()
    passed = sum(1 for line in lines if line.startswith("PASS"))
    failed = [line for line in lines if line.startswith("FAIL")]
    if done.returncode == 0 and not failed:
        return Result("hosted smoke", "ok", f"{passed} checks pass on the full export")
    return Result("hosted smoke", "FAIL", f"{len(failed)} check(s) failed on the full export", failed[:8] or lines[-5:])


def check_product(root: Path, min_takes: int, browser: bool = True) -> list[Result]:
    from openfield.engine import receipt as receipts
    from openfield.engine.contract import CONTRACTS, check_contract
    from openfield.engine.workflows import load_template
    from openfield.static_export import StaticExportError, export_static, recorded_takes

    results = []
    web = root / "openfield" / "web"
    results.append(Result("web app", "ok", "index.html present") if (web / "index.html").is_file()
                   else Result("web app", "FAIL", f"{web / 'index.html'} is missing"))

    workflows = root / "openfield" / "workflows"
    missing = []
    for name in CONTRACTS:
        try:
            template = load_template(name, workflows)
        except (FileNotFoundError, ValueError, KeyError) as exc:
            missing.append(f"{name}: {exc}")
            continue
        missing += [f"{name}: {p}" for p in check_contract(name, template) + template.problems()]
    results.append(Result("workflows", "FAIL", f"{len(missing)} problem(s)", missing) if missing
                   else Result("workflows", "ok", f"{len(CONTRACTS)} templates pass the contract and the audit"))

    takes_root = web / "showcase" / "takes"
    folders = recorded_takes(takes_root)
    bad = []
    for folder in folders:
        try:
            receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            bad.append(f"{folder.name}: receipt.json is unreadable")
            continue
        if not receipts.verify(receipt):
            bad.append(f"{folder.name}: receipt seal does not verify")
        if receipt.get("audit", {}).get("result") != "pass":
            bad.append(f"{folder.name}: open-weights audit did not pass")
        bad.extend(fake_stack_evidence(folder, receipt))
    if len(folders) < min_takes:
        bad.append(f"only {len(folders)} recorded take(s); need at least {min_takes}")
    results.append(Result("showcase", "FAIL", f"{len(bad)} problem(s)", bad) if bad
                   else Result("showcase", "ok", f"{len(folders)} recorded takes, all receipts verify"))

    if folders and (web / "index.html").is_file():
        from openfield.config import get_settings
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            try:
                summary = export_static(get_settings(), site, takes_root=takes_root, web_dir=web)
                results.append(Result("static export", "ok",
                                      f"{summary['takes']} takes, {summary['media_bytes'] / 1_048_576:.0f} MB"))
                results.append(check_export_size(site))
                if browser:
                    results.append(hosted_smoke(root, site))
            except StaticExportError as exc:
                results.append(Result("static export", "FAIL", str(exc)))
    return results


def check_licences(root: Path) -> list[Result]:
    results = []
    licence = root / "LICENSE"
    ok = licence.is_file() and "MIT License" in licence.read_text(encoding="utf-8")[:200]
    results.append(Result("LICENSE", "ok", "MIT") if ok else Result("LICENSE", "FAIL", "missing or not MIT"))
    done = subprocess.run([sys.executable, str(root / "scripts" / "gen_third_party.py"), "--check"],
                          capture_output=True, text=True, cwd=root, check=False)
    results.append(Result("THIRD_PARTY_MODELS.md", "ok", "matches the model registry") if done.returncode == 0
                   else Result("THIRD_PARTY_MODELS.md", "FAIL", (done.stderr or done.stdout).strip()))
    return results


def check_git(root: Path) -> list[Result]:
    if not (root / ".git").exists():
        return [Result("git", "warn", "not a git repository")]

    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
        return done.stdout.strip()

    results = []
    dirty = git("status", "--porcelain")
    results.append(Result("working tree", "warn", f"{len(dirty.splitlines())} uncommitted change(s)")
                   if dirty else Result("working tree", "ok", "clean"))
    emails = {e for e in git("log", "--format=%ae%n%ce").splitlines() if e}
    configured = git("config", "user.email")
    if configured:
        emails.add(configured)
    private = sorted(e for e in emails if not e.lower().endswith("@users.noreply.github.com"))
    results.append(Result(
        "commit emails", "warn",
        f"{len(private)} commit email address(es) are not GitHub no-reply addresses: they become public "
        "with the history. Decide before publishing (GitHub > Settings > Emails > keep my email private).")
        if private else Result("commit emails", "ok", "only no-reply addresses"))
    return results


def run(root: Path, min_takes: int, browser: bool = True) -> list[Result]:
    files = addable_files(root)
    results = [check_files(root, files)]
    results += check_content(root, files)
    results.append(check_unfinished(root, files))
    results += check_product(root, min_takes, browser)
    results += check_licences(root)
    results += check_git(root)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--min-takes", type=int, default=6)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-browser", action="store_true", help="skip the hosted copy's browser smoke test on the full export")
    args = parser.parse_args(argv)
    results = run(Path(args.root).resolve(), args.min_takes, browser=not args.no_browser)
    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        for r in results:
            print(f"[{r.state:^4}] {r.name}: {r.detail}")
            for item in r.items[:12]:
                print(f"         - {item}")
            if len(r.items) > 12:
                print(f"         ... and {len(r.items) - 12} more")
        failed = sum(r.state == "FAIL" for r in results)
        warned = sum(r.state == "warn" for r in results)
        print(f"\n{'NOT READY' if failed else 'ready'}: {failed} failed, {warned} warning(s)")
    return 1 if any(r.state == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
