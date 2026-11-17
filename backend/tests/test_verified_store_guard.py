"""The guard: no code except lib/verified_store.py can write law data or set a reviewed or verified status.

This reads all the code (lib, routers, scripts, tools, evals, models, server.py), not a server. It fails if any other module
  1. inserts, changes, replaces, deletes or bulk-writes a row of a law collection (the sources, Acts, provisions, verified library, drafts, mappings, judgment links, forums, rules ...),
  2. keeps a handle on a law collection in a variable (which would hide a write from rule 1),
  3. sets a review or verified field (review_status, reviewed_by, verified_by, verified_on, reviewed_on, provenance, ...) inside an update or insert, or sets a status of VERIFIED, REVIEWED or reviewed,
  4. touches a law collection at all from a route (routers/ read through the store).
The scanner itself is tested on invented offending code below, so it cannot pass by finding nothing. Tests may seed rows directly: tests are not scanned."""

import ast
import pathlib

from lib import verified_store

BACKEND = pathlib.Path(__file__).resolve().parent.parent
STORE = BACKEND / "lib" / "verified_store.py"
SCAN_DIRS = ("lib", "routers", "scripts", "tools", "evals", "models")
LAW = set(verified_store.LAW_COLLECTIONS)
WRITE_OPS = {"insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one", "delete_many", "bulk_write", "find_one_and_update", "find_one_and_replace",
             "find_one_and_delete", "drop", "rename"}
REVIEW_KEYS = set(verified_store.REVIEW_KEYS)
STATUS_VALUES = {"VERIFIED", "REVIEWED", "reviewed"}
MUTATORS = {"$set", "$setOnInsert", "$push", "$addToSet", "$inc", "$unset"}

# Nothing is excused here. A module that must write law data goes through lib/verified_store.py; do not add an entry to make this test pass.
EXCUSED: dict[tuple[str, str], str] = {}


def _is_db(node: ast.AST) -> bool:
    """`db`, `lib.db.db`, `mongo()`, `MongoClient(...)[name]`, `self.db`: something that is a database, not a dict that happens to have a key like 'provisions'."""
    if isinstance(node, ast.Name):
        return node.id in {"db", "database", "mongo_db", "_db"}
    if isinstance(node, ast.Attribute):
        return node.attr in {"db", "database"}
    if isinstance(node, ast.Call):
        return isinstance(node.func, ast.Name) and node.func.id in {"mongo", "get_db"}
    if isinstance(node, ast.Subscript):  # MongoClient(url)[name]
        return isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "MongoClient"
    return False


def _coll_name(node: ast.AST) -> str | None:
    """'provisions' for `db.provisions` and for `db["provisions"]`."""
    if isinstance(node, ast.Attribute) and node.attr in LAW:
        return node.attr
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value in LAW and _is_db(node.value):
        return node.slice.value
    return None


def _const_keys(d: ast.Dict) -> dict[str, ast.AST]:
    return {k.value: v for k, v in zip(d.keys, d.values) if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def findings(source: str, rel: str) -> list[tuple[str, str]]:
    """(rule, detail) for every way this source writes law data or sets a verified status."""
    out: list[tuple[str, str]] = []
    tree = ast.parse(source)
    in_router = rel.startswith("routers/")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in WRITE_OPS:
            c = _coll_name(node.func.value)
            if c:
                out.append(("1 writes a law collection", f"line {node.lineno}: {c}.{node.func.attr}"))
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is not None and _coll_name(value):
                out.append(("2 keeps a law collection in a variable", f"line {node.lineno}: {_coll_name(value)}"))
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and isinstance(value, ast.Constant):
                    if (t.slice.value in REVIEW_KEYS or t.slice.value == "status") and value.value in STATUS_VALUES | {True}:
                        out.append(("3 sets a verified status", f"line {node.lineno}: [{t.slice.value!r}] = {value.value!r}"))
        if isinstance(node, ast.Dict):
            keys = _const_keys(node)
            for op in MUTATORS & keys.keys():
                inner = keys[op]
                if isinstance(inner, ast.Dict):
                    bad = REVIEW_KEYS & _const_keys(inner).keys()
                    if bad:
                        out.append(("3 sets a verified status", f"line {node.lineno}: {op} sets {', '.join(sorted(bad))}"))
                    st = _const_keys(inner).get("status")
                    if isinstance(st, ast.Constant) and st.value in STATUS_VALUES:
                        out.append(("3 sets a verified status", f"line {node.lineno}: {op} sets status {st.value!r}"))
            st = keys.get("status")
            if isinstance(st, ast.Constant) and st.value in {"VERIFIED", "REVIEWED"} and ("id" in keys or "citation" in keys or "text" in keys):
                out.append(("3 sets a verified status", f"line {node.lineno}: a row built with status {st.value!r}"))
        if in_router and _coll_name(node):
            out.append(("4 a route touches a law collection", f"line {node.lineno}: {_coll_name(node)}"))
    return out


def scan() -> dict[str, list[tuple[str, str]]]:
    found: dict[str, list[tuple[str, str]]] = {}
    files = [BACKEND / "server.py"] + [p for d in SCAN_DIRS for p in (BACKEND / d).rglob("*.py")]
    for path in files:
        if path == STORE or "__pycache__" in path.parts or not path.is_file():
            continue
        rel = path.relative_to(BACKEND).as_posix()
        hits = [h for h in findings(path.read_text(encoding="utf-8"), rel) if (rel, h[0]) not in EXCUSED]
        if hits:
            found[rel] = hits
    return found


def test_no_other_code_can_write_law_data_or_set_a_verified_status():
    found = scan()
    assert not found, "These modules write law data or set a verified status outside lib/verified_store.py:\n" + "\n".join(f"  {f}: {h}" for f, hs in found.items() for h in hs)


def test_nothing_is_excused():
    assert EXCUSED == {}  # a written reason is not a way around the store


def test_the_store_is_scanned_for_what_it_may_do_and_it_is_the_only_writer_of_a_verified_library_entry():
    src = STORE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    writers = {fn.name for fn in ast.walk(tree) if isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)) and "library_entries" in ast.get_source_segment(src, fn) and any(
        isinstance(n, ast.Attribute) and n.attr in {"update_one", "update_many"} for n in ast.walk(fn))}
    assert writers == {"publish_verified", "withdraw_verified", "withdraw_missing"}  # a new function that writes the library must be added here on purpose


# ---------- the scanner itself, on invented offending code ----------
def _rules(code: str, rel: str = "lib/x.py") -> set[str]:
    return {r for r, _ in findings(code, rel)}


def test_the_scanner_sees_each_kind_of_offence():
    assert "1 writes a law collection" in _rules("async def f():\n    await db.provisions.update_one({}, {})")
    assert "1 writes a law collection" in _rules('async def f():\n    await db["library_entries"].insert_one({})')
    assert "1 writes a law collection" in _rules("async def f():\n    await mongo().judgment_relations.bulk_write([])")
    assert "2 keeps a law collection in a variable" in _rules("c = db.library_entries\n")
    assert "3 sets a verified status" in _rules('async def f():\n    await c.update_one({}, {"$set": {"review_status": "reviewed"}})')
    assert "3 sets a verified status" in _rules('async def f():\n    await c.update_one({}, {"$set": {"status": "VERIFIED"}})')
    assert "3 sets a verified status" in _rules('x = {}\nx["verified_by"] = "VERIFIED"\nx["status"] = "VERIFIED"')
    assert "3 sets a verified status" in _rules('row = {"id": "a", "status": "VERIFIED"}')
    assert "4 a route touches a law collection" in _rules("async def f():\n    return await db.forums.find_one({})", rel="routers/x.py")


def test_the_scanner_lets_ordinary_code_through():
    assert not _rules("async def f():\n    await db.matters.update_one({}, {'$set': {'title': 'a'}})\n    return await db.provisions.find_one({})")  # other collections, and reads in lib
    assert not _rules("async def f():\n    return await vstore.find_many('provisions', {})", rel="routers/x.py")  # a route reading through the store
    assert not _rules("label = {'status': 'UNVERIFIED - not reviewed'}")  # the word on screen is not a status written to the store
