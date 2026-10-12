"""Regression tests for the NameError-class defects fixed on 2026-10-12 (LSP audit 2026-10-11).

The defect class: a name used at runtime (raise / call / attribute base / except type) that
resolves neither to builtins, module-level names, function parameters, nor an enclosing
function scope (closure escape). `py_compile` does not see this — only LSP or runtime, so the
tests work on the AST instead of importing modules (meshcorium_web has import side effects).

Five fixed points + a closure-aware generic guard:
1. contact_admin: _build_remove_summary is module-level; both call-sites pass helper kwargs.
2. contact_backend: MeshCoreError is imported (the guard raises it at 5 sites).
3. meshcorium_web: _sync_meshcorium_channels_to_node_runtime exists (was deleted, callers remained).
4. meshcorium_web: enrich calls contact_groups.list_contact_groups, not undefined get_contact_groups.
5. meshcorium_web: cache-header guard uses the real class name MeshcoriumWebHandler.

Paths resolve relative to the project root, so the tests run on any checkout of the repo.
"""

import ast
import builtins
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTACT_ADMIN = ROOT / "meshcorium" / "contact_admin.py"
CONTACT_BACKEND = ROOT / "meshcorium" / "contact_backend.py"
WEB = ROOT / "meshcorium" / "meshcorium_web.py"

BUILTINS = set(dir(builtins))
MODULE = "<module>"


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _bindings(tree):
    """scope key -> names bound in that scope.

    Keys: "<module>", "funcname", "outer/inner" for nested defs, "<class:Name>".
    A name is bound by: function/lambda parameters, imports, assignments (including
    for/comprehension/walrus targets), except-as, del, class and function definitions.
    """
    scopes = {}

    def bind(scope, names):
        scopes.setdefault(scope, set()).update(names)

    def collect(node):
        names = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                names.add(n.id)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                names.add(n.name)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        return names

    def walk(node, scope, func_path):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = child.name if node is tree else f"{func_path}/{child.name}"
                a = child.args
                params = {arg.arg for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)}
                if a.vararg:
                    params.add(a.vararg.arg)
                if a.kwarg:
                    params.add(a.kwarg.arg)
                bind(key, params)
                bind(func_path, {child.name})
                walk(child, key, key)
                continue
            if isinstance(child, ast.Lambda):
                key = f"{func_path}/<lambda>"
                params = {arg.arg for arg in child.args.args + child.args.kwonlyargs}
                if child.args.vararg:
                    params.add(child.args.vararg.arg)
                if child.args.kwarg:
                    params.add(child.args.kwarg.arg)
                bind(key, params)
                walk(child, key, key)
                continue
            if isinstance(child, ast.ClassDef):
                key = f"<class:{child.name}>"
                bind(func_path, {child.name})
                bind(key, {b.id for b in child.bases if isinstance(b, ast.Name)})
                walk(child, key, key)
                continue
            bind(scope, collect(child))
            walk(child, scope, func_path)

    walk(tree, MODULE, MODULE)
    return scopes


def _usage_scopes(tree):
    """node -> scope key where that node occurs."""
    usage = {}

    def walk(node, scope, func_path):
        usage[node] = scope
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = child.name if node is tree else f"{func_path}/{child.name}"
                walk(child, key, key)
            elif isinstance(child, ast.Lambda):
                key = f"{func_path}/<lambda>"
                walk(child, key, key)
            elif isinstance(child, ast.ClassDef):
                key = f"<class:{child.name}>"
                walk(child, key, key)
            else:
                walk(child, scope, func_path)

    walk(tree, MODULE, MODULE)
    return usage


def _closure_chain(scope, scopes):
    """the usage scope plus every enclosing function scope up to module."""
    parts = scope.split("/")
    chain = []
    for i in range(1, len(parts) + 1):
        chain.append("/".join(parts[:i]))
    chain.append(MODULE)
    return chain


def _used_names(node):
    """the name a runtime lookup would resolve for this node."""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            return node.func.value.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id
    if isinstance(node, ast.Name):
        return node.id
    return None


def _unresolved(tree):
    """runtime-lookup names that resolve in no enclosing scope.

    Module dunder names (__file__, __name__, ...) are provided by the interpreter, not bound
    in the AST, so they are excluded as false positives.
    """
    scopes = _bindings(tree)
    usage = _usage_scopes(tree)
    bad = []
    for node, scope in usage.items():
        name = _used_names(node)
        if not name or name in BUILTINS or name.startswith("__"):
            continue
        resolved = any(name in scopes.get(s, set()) for s in _closure_chain(scope, scopes))
        if not resolved:
            bad.append((name, getattr(node, "lineno", 0), type(node).__name__, scope))
    return sorted(set(bad))


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _calls(tree, name):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == name:
                out.append(node)
            elif isinstance(node.func, ast.Attribute) and node.func.attr == name:
                out.append(node)
    return out


def _module_defs(tree):
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _module_imports(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


# ---------------------------------------------------------------- point 1
def test_build_remove_summary_is_module_level_and_gets_helpers():
    tree = _parse(CONTACT_ADMIN)
    fn = _func(tree, "_build_remove_summary")
    assert fn is not None, "_build_remove_summary missing"
    assert "_build_remove_summary" in _module_defs(tree), "must be module-level, not nested"

    needed = {"mark_cached_contacts_removed_from_node", "prepare_contacts_snapshot"}
    calls = _calls(tree, "_build_remove_summary")
    assert calls, "no call-site left"
    for call in calls:
        kw = {k.arg for k in call.keywords}
        assert needed <= kw, f"call at line {call.lineno} misses helper kwargs: {sorted(kw)}"
    bad = _unresolved(tree)
    assert not bad, f"unresolved names: {bad}"


# ---------------------------------------------------------------- point 2
def test_meshcore_error_imported_in_contact_backend():
    tree = _parse(CONTACT_BACKEND)
    assert "MeshCoreError" in _module_imports(tree), "guard raises MeshCoreError without import"
    # `raise MeshCoreError("...")` parses as Call(func=Name), not Raise(exc=Name)
    guard = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) and isinstance(n.exc.func, ast.Name)
        and n.exc.func.id == "MeshCoreError"
    ]
    assert guard, "guard raises disappeared"
    bad = _unresolved(tree)
    assert not bad, f"unresolved names: {bad}"


# ---------------------------------------------------------------- point 3
HELPERS = [
    "_list_meshcorium_channel_library",
    "_set_channel_with_retry",
    "_channel_runtime_idx",
    "_channel_runtime_name",
    "_channel_runtime_identity",
    "_is_meshcore_public_channel_name",
    "_load_channels_in_session",
    "_mark_access_all_message_channel_slots",
]


def test_sync_runtime_def_exists_and_helpers_are_present():
    tree = _parse(WEB)
    fn = _func(tree, "_sync_meshcorium_channels_to_node_runtime")
    assert fn is not None, "def deleted while callers remained (commit 1019910)"
    assert _calls(tree, "_sync_meshcorium_channels_to_node_runtime"), "def exists but has no caller"
    present = _module_defs(tree)
    for h in HELPERS:
        assert h in present, f"helper {h} missing — restored def would raise NameError"
    # the def must not rebind a helper as a local (shadowing would break resolution)
    local_targets = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    for h in HELPERS:
        assert h not in local_targets, f"{h} rebound as a local inside the restored def"
    bad = _unresolved(tree)
    assert not bad, f"unresolved names: {bad}"


# ---------------------------------------------------------------- point 4
def test_enrich_uses_contact_groups_not_undefined_name():
    tree = _parse(WEB)
    fn = _func(tree, "_enrich_contacts_with_local_state")
    assert fn is not None
    used = {
        n.func.attr
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "contact_groups"
    }
    assert "list_contact_groups" in used, "enrich must call contact_groups.list_contact_groups"
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "get_contact_groups"
        for n in ast.walk(fn)
    ), "undefined get_contact_groups() still referenced"
    assert "contact_groups" in _module_imports(tree), "contact_groups not imported at module level"


# ---------------------------------------------------------------- point 5
def test_cache_header_uses_real_class_name():
    tree = _parse(WEB)
    classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    assert "MeshcoriumWebHandler" in classes, "class name changed — recheck the guard"
    fn = _func(tree, "_cache_headers_for_static_file")
    assert fn is not None
    bases = {
        n.value.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
    }
    assert "MeshcoriumWebHandler" in bases, "guard still uses the wrong class name"
    assert "MeshCoreHandler" not in bases


# ---------------------------------------------------------------- fixture sanity
def test_source_files_exist_and_parse():
    for path in (CONTACT_ADMIN, CONTACT_BACKEND, WEB):
        assert path.is_file(), f"missing source file: {path}"
        _parse(path)
