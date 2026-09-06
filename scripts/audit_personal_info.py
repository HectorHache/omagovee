#!/usr/bin/env python3
"""audit_personal_info.py — G8/G8b pre-publish audit for the omagovee repo.

Scans the working tree (and optionally `git log -p` history) for anything
personal that must never ship:
  - the Govee API key shape (36 alnum chars)
  - MAC-formatted device ids (Govee device = MAC, verified live)
  - Mick's real device names, location, tailnet hosts/IPs, local paths

Gate G8 :  python3 scripts/audit_personal_info.py            EXPECT: AUDIT CLEAN
Gate G8b:  python3 scripts/audit_personal_info.py --history  EXPECT: AUDIT CLEAN
Exit code 0 = clean, 1 = findings. Prints each finding as file:line.
"""
import os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", ".venv"}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico"}

# 36-char alnum (Govee key shape) and colon-hex MACs (device ids).
KEY_RE = re.compile(r"(?<![0-9A-Za-z])[0-9A-Za-z]{36}(?![0-9A-Za-z])")
MAC_RE = re.compile(r"(?i)(?<![0-9a-f:])[0-9a-f]{2}(?::[0-9a-f]{2}){5,8}(?![0-9a-f:])")

# scripts/test_govee.py exercises mask logic with SYNTHETIC MAC-shaped ids —
# that file is the one legitimate home for such literals.
MAC_ALLOW_PATHS = {"scripts/test_govee.py"}

# Strings that must never appear. Device names are the real account names;
# "Floor Lamp" alone (generic example) is allowed — only the -Left/-Right
# suffixed real names are flagged.
SENSITIVE = [
    "Floor Lamp - Left",
    "Floor Lamp - Right",
    "Fairy - Govee Lights",
    "Govee Lamps",
    "nieuwegein", "utrecht",
    "mick", "héctor", "hector", "pythonmalone@", "miguel",
    "razer-studio", "macmini", "tailf74921", "100.123.82.89", "100.98.216.63",
    "/Users/mick", "/home/mick", "supersizedomp", "id_ed25519",
]

KNOWN_FALSE_POSITIVES = [
    # manifest/README may legitimately say "PythonMalone" (repo owner handle)
    # — covered separately below so it is NOT in SENSITIVE.
]


SELF = os.path.abspath(__file__)


def iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            if os.path.abspath(path) == SELF:
                continue  # the audit script legitimately lists the strings
            if fn.endswith(tuple(SKIP_SUFFIXES)):
                continue
            yield path


def scan_text(rel, text, findings):
    def hit(reason):
        findings.append("%s: %s" % (rel, reason))
    for m in KEY_RE.finditer(text):
        hit("possible API key (%d chars)" % (m.end() - m.start()))
    if rel not in MAC_ALLOW_PATHS:
        for m in MAC_RE.finditer(text):
            hit("MAC-like id %s" % m.group(0))
    low = text.lower()
    for s in SENSITIVE:
        if s.lower() in low:
            hit("sensitive string %r" % s)


def scan_tree():
    findings = []
    for path in iter_files(ROOT):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        scan_text(os.path.relpath(path, ROOT), text, findings)
    return findings


def scan_history():
    findings = []
    try:
        out = subprocess.run(
            ["git", "-C", ROOT, "log", "-p", "--all"],
            capture_output=True, text=True, timeout=120).stdout
    except Exception as e:
        return ["history scan unavailable: %s" % e]
    # commit identity lines (Author:/Commit:) are the repo owner handle —
    # metadata, not content; scan only the actual diffs
    lines = [ln for ln in out.splitlines()
             if not (ln.startswith("Author:") or ln.startswith("Commit:"))]
    scan_text("<git history>", "\n".join(lines), findings)
    return findings


def main():
    history = "--history" in sys.argv
    findings = scan_tree() + (scan_history() if history else [])
    # de-dup while preserving order
    seen, uniq = set(), []
    for f in findings:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    if uniq:
        print("\n".join(uniq))
        print("AUDIT PROBLEMS: %d" % len(uniq))
        return 1
    print("AUDIT CLEAN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
