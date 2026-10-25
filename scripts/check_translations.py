#!/usr/bin/env python3
"""Checks that every string passed to L("...") / fmt("...") has a Russian and a Spanish translation.

    scripts/check_translations.py            report missing strings (exit code 1 if any)
    scripts/check_translations.py --unused   also list translations no code uses

The English text is the key. A key may carry a context after "|" ("Crop|tab"). Strings built at run time are
listed in scripts/dynamic_strings.txt, one per line, so they are checked too.
"""
import ast
import json
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parent.parent
source = root / "src" / "mangosteen"
tables = {code: json.loads((source / "strings" / f"{code}.json").read_text(encoding="utf-8")) for code in ("ru", "es")}

def constants(node):
    """The string constants an expression can evaluate to ("a" or "x" if c else "y")."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.IfExp):
        yield from constants(node.body)
        yield from constants(node.orelse)


# Calls whose argument at the given position is a user-visible string: L("..."), fmt("..."), the wheel builder's
# add(condition, id, "Title", icon), and any call with a title= or text= keyword (tool windows, buttons).
WHERE = {"L": 0, "fmt": 0, "add": 2, "tr": 0}

used: set[str] = set()
for path in source.rglob("*.py"):
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        index = WHERE.get(name)
        if index is not None and len(node.args) > index and (name != "add" or len(node.args) == 4):
            used.update(constants(node.args[index]))
        for keyword in node.keywords:
            if keyword.arg in ("title", "text", "tooltip") and name in ("L_", "label"):
                used.update(constants(keyword.value))
dynamic = root / "scripts" / "dynamic_strings.txt"
if dynamic.exists():
    used.update(line.rstrip("\n") for line in dynamic.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#"))

missing = {code: sorted(k for k in used if not table.get(k)) for code, table in tables.items()}
for code, keys in missing.items():
    for key in keys:
        print(f"missing {code}: {key!r}")
if "--unused" in sys.argv:
    for code, table in tables.items():
        for key in sorted(set(table) - used):
            print(f"unused {code}: {key!r}")
print(f"{len(used)} strings in code; missing ru: {len(missing['ru'])}, es: {len(missing['es'])}")
sys.exit(1 if any(missing.values()) else 0)
