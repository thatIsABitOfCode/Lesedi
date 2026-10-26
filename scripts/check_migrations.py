#!/usr/bin/env python3
"""Approximate migration/model drift check that needs NO Django install.

It parses models.py and migrations/0001_initial.py with `ast` and compares, per model: field names, field
classes, and the kwargs max_length / null / blank / unique / db_index / auto_now(_add) / on_delete / related_name /
target model / literal defaults, plus Meta ordering, constraint names and index names.

This is a safety net for hand-written migrations. It does NOT replace Django's own check, which you must run:

    python manage.py makemigrations --check --dry-run

Run:  python3 scripts/check_migrations.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ["accounts", "audit", "safety", "guardian", "notifications", "evidence", "shield"]
COMPARE_KW = ["max_length", "null", "blank", "unique", "db_index", "auto_now_add", "auto_now", "related_name"]
MODEL_BASE_FIELDS = {"AbstractBaseUser": ["password", "last_login"],
                     "PermissionsMixin": ["is_superuser", "groups", "user_permissions"]}


ENUM_FILES = ["accounts/models.py", "safety/models.py", "guardian/models.py", "guardian/states.py",
              "notifications/models.py", "notifications/channels.py", "evidence/models.py"]


def build_enums():
    """{'Role': [('survivor', 'Survivor / account owner'), ...]} for every models.TextChoices class."""
    enums = {}
    for rel in ENUM_FILES:
        for cls in [n for n in ast.parse((ROOT / rel).read_text()).body if isinstance(n, ast.ClassDef)]:
            if not any(ast.unparse(b).endswith("TextChoices") for b in cls.bases):
                continue
            members = []
            for node in cls.body:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
                    members.append((node.targets[0].id, ast.literal_eval(node.value.elts[0]),
                                    ast.literal_eval(node.value.elts[1])))
            enums[cls.name] = members
    return enums


ENUMS = build_enums()


def enum_value(node):
    """Resolve Role.SURVIVOR -> 'survivor' using the parsed enums, else None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ENUMS:
        for name, value, _ in ENUMS[node.value.id]:
            if name == node.attr:
                return value
    return None


def field_class(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def kws(call):
    return {k.arg: k.value for k in call.keywords if k.arg}


def lit(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return ("<expr>", ast.unparse(node))


def norm_target(node):
    text = ast.unparse(node)
    if "AUTH_USER_MODEL" in text:
        return "USER"
    return text.strip("'\"").split(".")[-1].lower()


def norm_on_delete(node):
    return ast.unparse(node).split(".")[-1]


def describe(call, consts=None):
    consts = consts or {}
    kw = kws(call)
    d = {"class": field_class(call)}
    if d["class"] == "EmailField":
        d["max_length"] = 254  # Django default, always written out in migrations
    for k in COMPARE_KW:
        if k in kw:
            d[k] = lit(kw[k])
    if "on_delete" in kw:
        d["on_delete"] = norm_on_delete(kw["on_delete"])
    to = call.args[0] if call.args else kw.get("to")
    if to is not None and d["class"] in {"ForeignKey", "OneToOneField", "ManyToManyField"}:
        d["to"] = norm_target(to)
    if "default" in kw:
        resolved = enum_value(kw["default"])
        v = resolved if resolved is not None else lit(kw["default"])
        if not (isinstance(v, tuple) and v and v[0] == "<expr>"):
            d["default"] = v
    if "choices" in kw:
        node = kw["choices"]
        if isinstance(node, ast.Attribute) and node.attr == "choices" and ast.unparse(node.value) in ENUMS:
            d["choices"] = [(v, label) for _, v, label in ENUMS[ast.unparse(node.value)]]
        elif isinstance(node, ast.Name) and node.id in consts:
            d["choices"] = [tuple(x) for x in consts[node.id]]
        else:
            d["choices"] = [tuple(x) for x in lit(node)]
    return d


def parse_models(path):
    tree = ast.parse(path.read_text())
    out = {}
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        fields, meta = {}, {"constraints": set(), "indexes": set(), "ordering": None}
        is_model = False
        for node in cls.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                fc = ast.unparse(node.value.func)
                if fc.startswith("models.") and fc.split(".")[-1].endswith(("Field", "Key")):
                    is_model = True
                    fields[node.targets[0].id] = describe(node.value)
            if isinstance(node, ast.ClassDef) and node.name == "Meta":
                for m in node.body:
                    if isinstance(m, ast.Assign) and m.targets[0].id == "ordering":
                        meta["ordering"] = lit(m.value)
                    if isinstance(m, ast.Assign) and m.targets[0].id in {"constraints", "indexes"}:
                        for call in ast.walk(m.value):
                            if isinstance(call, ast.Call):
                                for k in call.keywords:
                                    if k.arg == "name":
                                        meta[m.targets[0].id].add(lit(k.value))
        if is_model:
            bases = [ast.unparse(b) for b in cls.bases]
            out[cls.name] = {"fields": fields, "meta": meta, "bases": bases, "explicit_id": "id" in fields,
                             "indexes_unnamed": sum(
                                 1 for m in cls.body if isinstance(m, ast.ClassDef) and m.name == "Meta"
                                 for a in m.body if isinstance(a, ast.Assign) and a.targets[0].id == "indexes"
                                 for c in ast.walk(a.value) if isinstance(c, ast.Call)
                                 and ast.unparse(c.func).endswith("Index")
                                 and not any(k.arg == "name" for k in c.keywords))}
    return out


def parse_migration(path):
    tree = ast.parse(path.read_text())
    models, extra_constraints, extra_indexes = {}, {}, {}
    consts = {}
    for top in tree.body:
        if isinstance(top, ast.Assign) and isinstance(top.targets[0], ast.Name):
            try:
                consts[top.targets[0].id] = ast.literal_eval(top.value)
            except Exception:
                pass
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("CreateModel"):
            kw = kws(node)
            name = lit(kw["name"])
            fields = {}
            for tup in kw["fields"].elts:
                fname = lit(tup.elts[0])
                fields[fname] = describe(tup.elts[1], consts)
            opts = kw.get("options")
            ordering = None
            if opts is not None:
                for k, v in zip(opts.keys, opts.values):
                    if lit(k) == "ordering":
                        ordering = lit(v)
            models[name] = {"fields": fields, "ordering": ordering}
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(("AddConstraint", "AddIndex")):
            kw = kws(node)
            model = lit(kw["model_name"])
            target = extra_constraints if ast.unparse(node.func).endswith("AddConstraint") else extra_indexes
            inner = kw.get("constraint") or kw.get("index")
            for k in inner.keywords:
                if k.arg == "name":
                    target.setdefault(model, set()).add(lit(k.value))
    return models, extra_constraints, extra_indexes, consts


def main():
    problems, checked = [], 0
    for app in APPS:
        mpath = ROOT / app / "models.py"
        gpath = ROOT / app / "migrations" / "0001_initial.py"
        if not gpath.exists():
            problems.append(f"{app}: migrations/0001_initial.py missing")
            continue
        models = parse_models(mpath)
        mig, constraints, indexes, consts = parse_migration(gpath)
        for name, m in models.items():
            checked += 1
            mm = mig.get(name)
            if mm is None:
                problems.append(f"{app}.{name}: no CreateModel in migration")
                continue
            expected = dict(m["fields"])
            if not m["explicit_id"] and not any(b.endswith("AbstractBaseUser") for b in m["bases"]):
                expected["id"] = {"class": "BigAutoField"}
            if any(b.endswith("AbstractBaseUser") for b in m["bases"]):
                expected.update({"password": {"class": "CharField"}, "last_login": {"class": "DateTimeField"},
                                 "is_superuser": {"class": "BooleanField"},
                                 "groups": {"class": "ManyToManyField"}, "user_permissions": {"class": "ManyToManyField"}})
            mf = mm["fields"]
            for f in sorted(set(expected) - set(mf)):
                problems.append(f"{app}.{name}.{f}: in model, missing from migration")
            for f in sorted(set(mf) - set(expected)):
                problems.append(f"{app}.{name}.{f}: in migration, not in model")
            for f in sorted(set(expected) & set(mf)):
                e, g = expected[f], mf[f]
                if e["class"] != g["class"]:
                    problems.append(f"{app}.{name}.{f}: class {e['class']} (model) != {g['class']} (migration)")
                for k in sorted((set(e) | set(g)) - {"class"}):
                    if k in {"id"} or (f in {"groups", "user_permissions", "password", "last_login", "is_superuser"}):
                        continue
                    if e.get(k) != g.get(k):
                        problems.append(f"{app}.{name}.{f}: {k} model={e.get(k)!r} migration={g.get(k)!r}")
            if (m["meta"]["ordering"] or None) != (mm["ordering"] or None):
                problems.append(f"{app}.{name}: ordering model={m['meta']['ordering']} migration={mm['ordering']}")
            got_c = constraints.get(name.lower(), set())
            if m["meta"]["constraints"] != got_c:
                problems.append(f"{app}.{name}: constraint names model={sorted(m['meta']['constraints'])} "
                                f"migration={sorted(got_c)}")
            got_i = indexes.get(name.lower(), set())
            if len(got_i) != m["indexes_unnamed"] + len(m["meta"]["indexes"]):
                problems.append(f"{app}.{name}: expected {m['indexes_unnamed'] + len(m['meta']['indexes'])} "
                                f"index(es), migration has {len(got_i)}")
        for name in set(mig) - set(models):
            problems.append(f"{app}.{name}: CreateModel has no matching model class")
    states = ast.parse((ROOT / "guardian/states.py").read_text())
    open_members = next([e.attr for e in n.value.elts] for n in states.body
                        if isinstance(n, ast.Assign) and n.targets[0].id == "OPEN_STATES")
    open_values = [next(v for name, v, _ in ENUMS["State"] if name == m) for m in open_members]
    mig_consts = parse_migration(ROOT / "guardian/migrations/0001_initial.py")[3]
    if mig_consts.get("OPEN_STATE_VALUES") != open_values:
        problems.append(f"guardian: OPEN_STATE_VALUES {mig_consts.get('OPEN_STATE_VALUES')} != OPEN_STATES {open_values}")
    print(f"models compared: {checked}; enums resolved: {len(ENUMS)}")
    if problems:
        print("\nPOSSIBLE DRIFT:")
        print("\n".join(" - " + p for p in problems))
        return 1
    print("no drift found by this approximate check (run `makemigrations --check --dry-run` for the real one)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
