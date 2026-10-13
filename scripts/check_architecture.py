"""Check Python dependency directions from an explicit, project-local package map.

No repository map is assumed: --config is required until application ownership
and the independently installable core are agreed. The checker never imports code.
"""
from __future__ import annotations

import argparse
import ast
from collections import deque
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys


def within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


@dataclass(frozen=True)
class Module:
    name: str
    path: Path
    package: str
    tree: ast.Module


@dataclass(frozen=True)
class Edge:
    target: str
    line: int


@dataclass(frozen=True)
class Violation:
    chain: tuple[str, ...]
    reason: str


def module_index(root: Path, source_roots: list[str]) -> dict[str, Module]:
    modules = {}
    for source in source_roots:
        directory = root / source
        if not directory.is_dir() or not directory.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Source root must be an existing directory inside the project: {source}")
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(directory).with_suffix("")
            parts = relative.parts[:-1] if path.name == "__init__.py" else relative.parts
            if not parts:
                raise ValueError(f"Source root must be the import search path, above the package: {source}")
            name = ".".join(parts)
            if name in modules:
                raise ValueError(f"Ambiguous module {name}: {modules[name].path} and {path}")
            package = name if path.name == "__init__.py" else name.rpartition(".")[0]
            modules[name] = Module(name, path, package, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return modules


def dependency_graph(modules: dict[str, Module]) -> tuple[dict[str, list[Edge]], list[tuple[str, str]]]:
    graph, gaps = {}, []
    for name, module in modules.items():
        edges = {}

        def gap(message):
            gaps.append((name, message))

        def add(target, line):
            # Even a missing/unindexed submodule executes existing parent
            # packages first. Preserve that dependency instead of dropping it.
            while target and target not in modules:
                target = target.rpartition(".")[0]
            if target in modules and target != name:
                edges.setdefault(target, Edge(target, line))

        # Loading a module executes its package initializers too. Attach these
        # edges to the loaded module, so an explicitly public app API can own its
        # private initialization without making its caller import private code.
        parts = name.split(".")
        for length in range(1, len(parts)):
            add(".".join(parts[:length]), 1)

        dynamic_names, importlib_names = {"__import__"}, set()
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    add(alias.name, node.lineno)
                    if alias.name == "importlib" or alias.name.startswith("importlib.") and not alias.asname:
                        importlib_names.add(alias.asname or "importlib")
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    try:
                        base = importlib.util.resolve_name("." * node.level + (node.module or ""), module.package)
                    except (ImportError, ValueError) as error:
                        gap(f"{module.path}:{node.lineno}: invalid relative import: {error}")
                        continue
                else:
                    base = node.module or ""
                for alias in node.names:
                    target = base + "." + alias.name
                    # A real submodule has a package-initialization edge. For an
                    # exported symbol or '*', the base module owns resolution.
                    add(target if target in modules else base, node.lineno)
                    if base == "importlib" and alias.name == "import_module":
                        dynamic_names.add(alias.asname or alias.name)

        def is_loader(function):
            return (isinstance(function, ast.Name) and function.id in dynamic_names
                    or isinstance(function, ast.Attribute) and function.attr == "import_module"
                    and isinstance(function.value, ast.Name) and function.value.id in importlib_names)

        for node in ast.walk(module.tree):
            if isinstance(node, ast.Assign) and is_loader(node.value):
                dynamic_names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        parents = {child: parent for parent in ast.walk(module.tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not is_loader(function):
                continue
            loader_name = function.id if isinstance(function, ast.Name) else function.value.id
            scope, shadowed = parents.get(node), False
            while scope is not None:
                if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    arguments = [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs,
                                 *([scope.args.vararg] if scope.args.vararg else []),
                                 *([scope.args.kwarg] if scope.args.kwarg else [])]
                    shadowed = shadowed or any(argument.arg == loader_name for argument in arguments)
                scope = parents.get(scope)
            if shadowed:
                gap(f"{module.path}:{node.lineno}: shadowed import loader; static analysis cannot determine its target")
                continue
            if isinstance(function, ast.Name) and function.id == "__import__":
                level = node.args[4] if len(node.args) > 4 else next((k.value for k in node.keywords if k.arg == "level"), None)
                if level is not None and (not isinstance(level, ast.Constant) or level.value != 0):
                    gap(f"{module.path}:{node.lineno}: relative __import__ requires explicit package analysis; use import_module")
                    continue
            target_node = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "name"), None)
            target = target_node.value if isinstance(target_node, ast.Constant) and isinstance(target_node.value, str) else None
            if target and target.startswith("."):
                package_node = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "package"), None)
                package = (package_node.value if isinstance(package_node, ast.Constant) and isinstance(package_node.value, str)
                           else module.package if isinstance(package_node, ast.Name) and package_node.id == "__package__" else None)
                try:
                    target = importlib.util.resolve_name(target, package) if package else None
                except (ImportError, ValueError):
                    target = None
            if target is None:
                gap(f"{module.path}:{node.lineno}: unresolved dynamic import; use an explicit trusted registration "
                    "or a statically named import before claiming dependency coverage")
            else:
                add(target, node.lineno)
        graph[name] = sorted(edges.values(), key=lambda edge: edge.target)
    return graph, sorted(gaps)


def validate_map(config: dict, modules: dict[str, Module], root: Path):
    core, apps = config["core"], config["apps"]
    packages = [*core, *(app["package"] for app in apps.values())]
    if not core or not apps:
        raise ValueError("Declare at least one core package and one application; an empty map proves no boundary")
    for package in packages:
        if not package or any(not part.isidentifier() for part in package.split(".")):
            raise ValueError(f"Use exact dotted packages, not wildcards: {package}")
        if not any(within(name, package) for name in modules):
            raise ValueError(f"Declared package has no modules: {package}")
    app_packages = [app["package"] for app in apps.values()]
    for package in core:
        if any(within(package, app) for app in app_packages):
            raise ValueError(f"Application ownership cannot replace the core package: {package}")
    for index, first in enumerate(app_packages):
        for second in app_packages[index + 1:]:
            if within(first, second) or within(second, first):
                raise ValueError(f"Overlapping application ownership: {first}, {second}")
    for app in apps.values():
        for public in app.get("public", []):
            if public not in modules or not within(public, app["package"]):
                raise ValueError(f"Public API must name an existing module owned by its app: {public}")
    paths = {module.path.relative_to(root).as_posix(): name for name, module in modules.items()}
    composition = set()
    for path in config.get("composition_roots", []):
        if path not in paths:
            raise ValueError(f"Composition root must name one exact existing source file: {path}")
        composition.add(paths[path])
    if not any(name not in composition and any(within(name, package) for package in core)
               and not any(within(name, app) for app in app_packages) for name in modules):
        raise ValueError("The map must leave actual core modules to check")
    return core, apps, composition


def check(root: Path, config: dict):
    root = root.resolve()
    modules = module_index(root, config["source_roots"])
    core, apps, composition = validate_map(config, modules, root)
    graph, gaps = dependency_graph(modules)

    def owner(name):
        return next((key for key, app in apps.items() if within(name, app["package"])), None)

    violations, covered = [], set()
    for source in sorted(modules):
        is_composition = source in composition
        source_app = owner(source)
        is_core = not is_composition and source_app is None and any(within(source, prefix) for prefix in core)
        if not is_composition and not is_core and source_app is None:
            continue
        queue, visited = deque([(source, (source,))]), {source}
        while queue:
            current, chain = queue.popleft()
            for edge in graph[current]:
                target = edge.target
                if target in visited:
                    continue
                visited.add(target)
                target_app = owner(target)
                path = (*chain, target)
                reason = None
                if target in composition and not is_composition:
                    reason = "Reusable core/apps cannot depend on the composition root; inject the required port instead"
                elif is_core and target_app is not None:
                    reason = "Core reaches application code; move this behavior to its app/adapter and inject a core port"
                elif target_app is not None and (is_composition or target_app != source_app):
                    if target in apps[target_app].get("public", []):
                        # Only cross-app callers stop here. Core has already
                        # failed above; API modules are also checked as origins.
                        continue
                    reason = "Cross-app private implementation; use the declared public API or relocate genuinely shared behavior"
                if reason:
                    violations.append(Violation(path, reason))
                else:
                    queue.append((target, path))
        covered.update(visited)
    return modules, graph, violations, [message for name, message in gaps if name in covered]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, required=True, help="JSON source roots, package ownership, public APIs and exact composition files")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        modules, graph, violations, gaps = check(args.root, config)
    except (OSError, ValueError, SyntaxError, KeyError, TypeError) as error:
        print(f"Architecture configuration/parse error: {error}", file=sys.stderr)
        return 2
    for violation in violations:
        print(" -> ".join(violation.chain), file=sys.stderr)
        for source, target in zip(violation.chain, violation.chain[1:]):
            edge = next(edge for edge in graph[source] if edge.target == target)
            print(f"  {modules[source].path.relative_to(args.root.resolve())}:{edge.line} -> {target}", file=sys.stderr)
        print(f"  Fix: {violation.reason}", file=sys.stderr)
    for gap in gaps:
        print(f"Coverage gap: {gap}", file=sys.stderr)
    print(json.dumps({"modules": len(modules), "violations": len(violations), "coverageGaps": len(gaps),
                      "accepted": not violations and not gaps}))
    return 1 if violations or gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
