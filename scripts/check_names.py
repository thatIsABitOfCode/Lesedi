#!/usr/bin/env python3
"""Poor-man's pyflakes (no install needed): reports names that are used but never defined/imported in a module,
and imports that are never used. It is approximate (it ignores scoping), so it can miss errors but rarely
reports false ones. Run:  python3 scripts/check_names.py"""
import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".venv", "_superseded", "__pycache__", "migrations", "staticfiles"}
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


def check(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    defined, imported, loaded = set(), {}, []
    lines = path.read_text().splitlines()
    star = any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in ast.walk(tree))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                name = (a.asname or a.name).split(".")[0]
                if name != "*":
                    defined.add(name)
                    if "noqa" not in lines[node.lineno - 1]:  # deliberate side-effect imports are marked noqa
                        imported[name] = node.lineno
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, ast.Name):
            (loaded.append((node.id, node.lineno)) if isinstance(node.ctx, ast.Load) else defined.add(node.id))
        elif isinstance(node, ast.alias):
            pass
    problems = [] if star else [  # a star import (settings_test) can define anything, so skip that check there
        f"{path.relative_to(ROOT)}:{ln}: undefined name {n!r}" for n, ln in loaded if n not in defined | BUILTINS]
    used = {n for n, _ in loaded}
    attr_roots = {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    text = path.read_text()
    if path.name != "__init__.py":
        for name, ln in imported.items():
            if name not in used and name not in attr_roots and f"'{name}'" not in text and f'"{name}"' not in text:
                problems.append(f"{path.relative_to(ROOT)}:{ln}: unused import {name!r}")
    return problems


def main():
    problems = []
    for p in sorted(ROOT.rglob("*.py")):
        if set(p.relative_to(ROOT).parts) & SKIP:
            continue
        problems += check(p)
    print("\n".join(problems) if problems else "no undefined names or unused imports found")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
