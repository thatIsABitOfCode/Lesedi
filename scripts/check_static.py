#!/usr/bin/env python3
"""Static sanity checks that need NO Django install. They do not replace running the test suite.

1. Every {% url 'ns:name' %} and reverse()/redirect() name used in templates and code exists in a urls.py.
2. Django template block tags are balanced (if/for/block/with/...).
3. Templates/code contain no inline <script>, inline style="" or phone-number-like strings (the project
   must not publish unverified helpline numbers; see README).
Run:  python3 scripts/check_static.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".venv", "_superseded", "__pycache__", "staticfiles", "private_storage", ".git"}


def files(suffixes):
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in suffixes and not (set(p.relative_to(ROOT).parts) & SKIP):
            yield p


def url_names():
    """Collect 'namespace:name' from each urls.py using app_name and name="..." literals."""
    names = set()
    for p in files({".py"}):
        if p.name != "urls.py" and p.name != "api_urls.py":
            continue
        text = p.read_text()
        m = re.search(r'app_name\s*=\s*"([^"]+)"', text)
        for n in re.findall(r'name="([^"]+)"', text):
            names.add(f"{m.group(1)}:{n}" if m else n)
    return names


def main() -> int:
    problems = []
    known = url_names()

    used = []
    for p in files({".html", ".txt", ".py"}):
        if p.name == "check_static.py":
            continue
        text = p.read_text()
        for n in re.findall(r"\{%\s*url\s+['\"]([^'\"]+)['\"]", text):
            used.append((p, n))
        if p.suffix == ".py":
            for n in re.findall(r'(?:reverse|reverse_lazy|redirect)\(\s*"([a-z_]+:[a-z_]+)"', text):
                used.append((p, n))
    for p, n in used:
        if n not in known:
            problems.append(f"unknown URL name {n!r} in {p.relative_to(ROOT)}")

    openers = {"if": "endif", "for": "endfor", "block": "endblock", "with": "endwith", "autoescape": "endautoescape"}
    for p in files({".html"}):
        text = p.read_text()
        stack = []
        for tag in re.findall(r"\{%\s*(\w+)", text):
            if tag in openers:
                stack.append(tag)
            elif tag in openers.values():
                if not stack or openers[stack[-1]] != tag:
                    problems.append(f"unbalanced {{% {tag} %}} in {p.relative_to(ROOT)}")
                    stack = []
                    break
                stack.pop()
        if stack:
            problems.append(f"unclosed {{% {stack[-1]} %}} in {p.relative_to(ROOT)}")
        if re.search(r"<script(?![^>]*\bsrc=)", text):
            problems.append(f"inline <script> in {p.relative_to(ROOT)} (blocked by the CSP)")
        if re.search(r'\sstyle="', text):
            problems.append(f"inline style attribute in {p.relative_to(ROOT)} (blocked by the CSP)")
        if re.search(r"(?<![\w.])(?:\+?27|0\d{2})[\s-]?\d{2,3}[\s-]?\d{3,4}[\s-]?\d{0,4}(?![\w])", text) and "example" not in text:
            problems.append(f"phone-number-like text in {p.relative_to(ROOT)} - verify it or remove it")

    print(f"URL names known: {len(known)}; references checked: {len(used)}")
    if problems:
        print("\nPROBLEMS:")
        print("\n".join(" - " + x for x in problems))
        return 1
    print("static checks passed (this is NOT a substitute for running the tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
