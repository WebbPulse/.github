"""Decide which backend domains a diff affects.

A domain is an immediate subdirectory of `app/domains/` holding an `entrypoint.py`.
Every changed path is attributed to the domains it can reach: a file under a
domain belongs to that domain plus every other domain whose entrypoint import
closure reaches it, a file under `app/common/` belongs to every domain whose
entrypoint import closure contains it, and anything that rebuilds every image
belongs to all of them. The result drives which CI shards and which deploys
actually run.

The walk is static, so it holds for the image that ships without importing
anything. Module level and function body imports are both followed, TYPE_CHECKING
blocks are skipped, and the lazy per-domain router loaders are attributed only to
the domain they load, which is the property that lets one `app/` tree ship as
several single-domain functions.
"""

import argparse
import ast
import fnmatch
import json
import os
import posixpath
import subprocess
import sys
import tomllib
from pathlib import Path

CODE_SUBTREES = ("app",)
"""Subtrees of the working directory whose changes can affect a deployed image."""

NON_CODE_SUBTREES = ("tests", "e2e", "scripts", "docs")
"""Subtrees that never ship in an image, so in deploy mode they change nothing."""


class Unknown(Exception):
    """The diff could not be computed, so every domain has to be assumed affected."""


def _run(args, cwd):
    """Run a git command, returning stdout, or raise `Unknown` if it fails."""
    try:
        done = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise Unknown(f"could not run {' '.join(args)}: {error}") from error
    if done.returncode != 0:
        raise Unknown(f"{' '.join(args)} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def _have(ref, repo_root):
    """Whether the ref resolves to an object already present locally."""
    try:
        _run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], repo_root)
    except Unknown:
        return False
    return True


def changed_paths(base, head, repo_root):
    """Repo-relative paths changed between base and head, with a shallow fetch if needed.

    Raises `Unknown` when base is empty, cannot be resolved even after fetching,
    or is not an ancestor of head, since a diff against an unrelated commit would
    silently under-report.
    """
    if not base:
        raise Unknown("base is empty, so the diff is unknown")

    if not _have(base, repo_root):
        try:
            _run(["git", "fetch", "--no-tags", "--depth=1", "origin", base], repo_root)
        except Unknown:
            pass
    if not _have(base, repo_root):
        raise Unknown(f"base {base} could not be resolved, even after a fetch")
    if not _have(head, repo_root):
        raise Unknown(f"head {head} could not be resolved")

    try:
        _run(["git", "merge-base", "--is-ancestor", base, head], repo_root)
    except Unknown as error:
        raise Unknown(f"base {base} is not an ancestor of {head}") from error

    output = _run(["git", "diff", "--name-only", base, head], repo_root)
    return [line for line in output.splitlines() if line.strip()]


def discover_domains(app_dir):
    """Domain names: immediate subdirectories of `app/domains/` holding an entrypoint."""
    domains_dir = app_dir / "domains"
    if not domains_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in domains_dir.iterdir()
        if path.is_dir() and not path.name.startswith("__") and (path / "entrypoint.py").is_file()
    )


def read_reachability_config(work_dir):
    """The `[tool.webbpulse.reachability]` table, or an empty mapping."""
    path = work_dir / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return document.get("tool", {}).get("webbpulse", {}).get("reachability", {})


class ImportGraph:
    """Module level and function body `app` imports for every file under `app/`."""

    def __init__(self, app_dir):
        self.app_dir = app_dir
        self.work_dir = app_dir.parent
        self.files = {
            path for path in app_dir.rglob("*.py") if "__pycache__" not in path.parts
        }
        self.eager = {}
        self.lazy = {}
        for path in self.files:
            self.eager[path], self.lazy[path] = self._edges(path)

    def module_files(self, module):
        """Every file that importing the dotted module executes."""
        if not module.startswith("app"):
            return []
        parts = module.split(".")
        found = []
        for index in range(1, len(parts) + 1):
            init = self.work_dir.joinpath(*parts[:index], "__init__.py")
            if init in self.files:
                found.append(init)
        leaf = self.work_dir.joinpath(*parts).with_suffix(".py")
        if leaf in self.files:
            found.append(leaf)
        return found

    def leaf_file(self, module):
        """The single file the dotted module itself provides, parents excluded.

        `module_files` deliberately includes every parent `__init__.py`, because
        importing a module executes them. That is the wrong set for asking whether
        a closure reaches one particular module, since every closure reaches
        `app/__init__.py`.
        """
        if not module.startswith("app"):
            return None
        parts = module.split(".")
        leaf = self.work_dir.joinpath(*parts).with_suffix(".py")
        if leaf in self.files:
            return leaf
        package = self.work_dir.joinpath(*parts, "__init__.py")
        if package in self.files:
            return package
        return None

    def _edges(self, path):
        """This file's eager and lazy `app` imports, kept apart."""
        parts = path.relative_to(self.work_dir).with_suffix("").parts
        package = parts[:-1]
        eager, lazy = set(), set()

        def resolve(node):
            found = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.extend(self.module_files(alias.name))
                return found
            if node.level:
                base = package[: len(package) - node.level + 1]
                prefix = ".".join(base + ((node.module,) if node.module else ()))
            else:
                prefix = node.module or ""
            if prefix.startswith("app"):
                found.extend(self.module_files(prefix))
                for alias in node.names:
                    found.extend(self.module_files(f"{prefix}.{alias.name}"))
            return found

        def visit(node, in_function):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit(child, True)
                    continue
                if (
                    isinstance(child, ast.If)
                    and isinstance(child.test, ast.Name)
                    and child.test.id == "TYPE_CHECKING"
                ):
                    continue
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    (lazy if in_function else eager).update(resolve(child))
                visit(child, in_function)

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            return eager, lazy
        visit(tree, False)
        return eager, lazy


def domain_of(path, domains_dir):
    """The domain a file belongs to, or None for common, shared and non-domain files."""
    try:
        relative = path.relative_to(domains_dir)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) < 2:
        return None
    return parts[0]


def build_closures(graph, domains):
    """Every file each domain's entrypoint executes, keyed by domain name.

    A lazy `app.domains.<name>` import inside a file that is not itself part of a
    domain is a per-domain router loader: it counts for `<name>` alone, never for
    whoever happens to reach the loader.
    """
    domains_dir = graph.app_dir / "domains"

    loader_edges = {domain: set() for domain in domains}
    for path in graph.files:
        if domain_of(path, domains_dir) is not None:
            continue
        for target in graph.lazy[path]:
            owner = domain_of(target, domains_dir)
            if owner in loader_edges:
                loader_edges[owner].add(target)

    def eager_closure(seeds):
        seen, stack = set(), list(seeds)
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(graph.eager.get(current, ()))
        return seen

    closures = {}
    for domain in domains:
        entry = domains_dir / domain / "entrypoint.py"
        reached = eager_closure({entry} | loader_edges[domain])
        while True:
            extra = set()
            for path in reached:
                if domain_of(path, domains_dir) is None:
                    extra |= {
                        target
                        for target in graph.lazy[path]
                        if domain_of(target, domains_dir) is None
                    }
                else:
                    extra |= graph.lazy[path]
            grown = eager_closure(reached | extra)
            if grown == reached:
                break
            reached = grown
        closures[domain] = reached
    return closures


def module_name_of(path, work_dir):
    """The dotted module name a file under the working directory provides."""
    relative = path.relative_to(work_dir).with_suffix("")
    parts = relative.parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def by_name_owners(graph, closures, config, domains):
    """Domains that own each module matched by a `loaded-by-name` glob.

    A module loaded through `importlib` by a registry the static walk cannot
    follow belongs to every domain that reaches the module declaring the glob.
    `anchor` names that declaring module; without one the globs fall back to
    every domain, which is the safe reading.
    """
    patterns = config.get("loaded-by-name") or []
    if not patterns:
        return {}

    anchor = config.get("anchor") or ""
    anchor_owners = set(domains)
    if anchor:
        anchor_file = graph.leaf_file(anchor)
        if anchor_file is not None:
            anchor_owners = {
                domain for domain in domains if anchor_file in closures[domain]
            }

    owners = {}
    for path in graph.files:
        module = module_name_of(path, graph.work_dir)
        if any(fnmatch.fnmatchcase(module, pattern) for pattern in patterns):
            owners[path] = set(anchor_owners)
    return owners


def matches_any(path, patterns):
    """Whether a repo-relative path matches any of the glob patterns."""
    for pattern in patterns:
        if fnmatch.fnmatchcase(path, pattern):
            return True
        if pattern.endswith("/") and path.startswith(pattern):
            return True
    return False


def under(path, prefix):
    """Whether a repo-relative path sits inside the given directory prefix."""
    return path == prefix or path.startswith(prefix + "/")


def is_readme(name):
    """Whether a file name is a README, in any of the spellings we accept."""
    return name.upper().startswith("README")


def attribute(paths, *, work_dir_rel, mode, unattributed, extra_full_paths, domains, closures, name_owners, work_dir):
    """Map each changed path to the domains it affects.

    Returns the per-path attribution, whether every domain is forced, and whether
    the shared CI shard has to run.
    """
    all_domains = set(domains)
    attribution = {}
    forced = False
    shared = False

    domains_prefix = f"{work_dir_rel}/app/domains"
    common_prefix = f"{work_dir_rel}/app/common"
    app_prefix = f"{work_dir_rel}/app"
    tests_prefix = f"{work_dir_rel}/tests"
    test_domains_prefix = f"{tests_prefix}/domains"

    for path in paths:
        if matches_any(path, extra_full_paths):
            attribution[path] = ("all", set(all_domains))
            forced = True
            shared = True
            continue

        if not under(path, work_dir_rel):
            attribution[path] = ("outside", set())
            continue

        relative = path[len(work_dir_rel) + 1 :]
        head = relative.split("/", 1)[0]
        name = posixpath.basename(relative)

        if head not in CODE_SUBTREES + NON_CODE_SUBTREES and not is_readme(name):
            attribution[path] = ("runtime", set(all_domains))
            forced = True
            shared = True
            continue

        if under(path, domains_prefix):
            rest = path[len(domains_prefix) + 1 :].split("/")
            shared = True
            if len(rest) >= 2 and rest[0] in all_domains:
                owners = _domain_file_owners(
                    work_dir / relative, rest[0], domains, closures, name_owners
                )
                label = "domain" if owners == {rest[0]} else "domain-imported"
                attribution[path] = (label, owners)
            elif len(rest) >= 2:
                attribution[path] = ("not-a-domain", set())
            else:
                attribution[path] = (
                    "unattributed",
                    _unattributed(unattributed, all_domains),
                )
            continue

        if under(path, common_prefix):
            absolute = work_dir / relative
            if not relative.endswith(".py"):
                attribution[path] = ("common-data", set(all_domains))
                forced = True
                shared = True
                continue
            owners = name_owners.get(absolute)
            if owners is None:
                owners = {domain for domain in domains if absolute in closures[domain]}
                label = "common"
            else:
                label = "loaded-by-name"
            if owners:
                attribution[path] = (label, set(owners))
            else:
                attribution[path] = ("unattributed", _unattributed(unattributed, all_domains))
            shared = True
            continue

        if under(path, app_prefix):
            attribution[path] = ("unattributed", _unattributed(unattributed, all_domains))
            shared = True
            continue

        if under(path, test_domains_prefix):
            rest = path[len(test_domains_prefix) + 1 :].split("/")
            if mode == "ci" and len(rest) >= 2 and rest[0] in all_domains:
                attribution[path] = ("test-domain", {rest[0]})
            else:
                attribution[path] = ("test-domain", set())
            continue

        attribution[path] = ("support", set())
        if mode == "ci":
            shared = True

    if mode == "deploy":
        shared = False

    return attribution, forced, shared


def _domain_file_owners(absolute, owning_domain, domains, closures, name_owners):
    """Domains a file under `app/domains/<owning_domain>/` affects.

    Its own domain always owns it, so a test helper or any other module no closure
    reaches stays with that domain alone. Every other domain whose entrypoint
    closure reaches the file is added, which is what makes a cross-domain import
    deploy both functions, and a file claimed by the `loaded-by-name` globs takes
    that rule's owners on top.
    """
    owners = {owning_domain}
    by_name = name_owners.get(absolute)
    if by_name is not None:
        owners |= set(by_name)
    owners |= {domain for domain in domains if absolute in closures[domain]}
    return owners


def _unattributed(policy, all_domains):
    """Domains an unattributed change belongs to, per the `unattributed` policy."""
    return set(all_domains) if policy == "all" else set()


def render_summary(attribution, reason, domains, all_flag, shared, mode):
    """The `$GITHUB_STEP_SUMMARY` markdown: the verdict, then path to domains."""
    lines = ["## Affected domains", "", reason, ""]
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| mode | `{mode}` |")
    lines.append(f"| domains | `{json.dumps(domains)}` |")
    lines.append(f"| all | `{str(all_flag).lower()}` |")
    if mode == "ci":
        lines.append(f"| shared | `{str(shared).lower()}` |")
    lines.append("")

    if attribution:
        lines.append("| Changed path | Domains |")
        lines.append("| --- | --- |")
        for path in sorted(attribution):
            label, owners = attribution[path]
            if owners:
                rendered = ", ".join(f"`{name}`" for name in sorted(owners))
            else:
                rendered = "_none_"
            lines.append(f"| `{path}` | {rendered} <sub>{label}</sub> |")
    else:
        lines.append("No changed paths were attributed.")
    lines.append("")
    return "\n".join(lines)


def write_outputs(values, summary):
    """Write the action outputs and append the step summary, when running under Actions."""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")


def main(argv=None):
    """Resolve the affected domains and emit the action outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--working-directory", default="backend")
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--mode", choices=("deploy", "ci"), default="ci")
    parser.add_argument("--extra-full-paths", default="")
    parser.add_argument("--unattributed", choices=("all", "none"), default="all")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    work_dir_rel = args.working_directory.strip("/") or "."
    work_dir = repo_root / work_dir_rel
    app_dir = work_dir / "app"

    extra_full_paths = [
        line.strip() for line in args.extra_full_paths.splitlines() if line.strip()
    ]

    domains = discover_domains(app_dir)

    unknown_reason = ""
    try:
        paths = changed_paths(args.base, args.head, repo_root)
    except Unknown as error:
        unknown_reason = str(error)
        paths = []

    if unknown_reason:
        affected = set(domains)
        all_flag = True
        shared = args.mode == "ci"
        attribution = {}
        reason = f"All {len(domains)} domains: {unknown_reason}."
    elif not domains:
        affected = set()
        all_flag = False
        shared = args.mode == "ci" and bool(paths)
        attribution = {}
        reason = f"No domains found under {work_dir_rel}/app/domains."
    else:
        graph = ImportGraph(app_dir)
        closures = build_closures(graph, domains)
        config = read_reachability_config(work_dir)
        name_owners = by_name_owners(graph, closures, config, domains)

        attribution, forced, shared = attribute(
            paths,
            work_dir_rel=work_dir_rel,
            mode=args.mode,
            unattributed=args.unattributed,
            extra_full_paths=extra_full_paths,
            domains=domains,
            closures=closures,
            name_owners=name_owners,
            work_dir=work_dir,
        )
        affected = set()
        for _label, owners in attribution.values():
            affected |= owners
        all_flag = forced or (bool(domains) and affected == set(domains))

        if not paths:
            reason = "No files changed, so no domain is affected."
        elif all_flag:
            reason = f"All {len(domains)} domains are affected by {len(paths)} changed file(s)."
        elif affected:
            reason = (
                f"{len(affected)} of {len(domains)} domains affected by "
                f"{len(paths)} changed file(s): {', '.join(sorted(affected))}."
            )
        else:
            reason = f"No domain is affected by the {len(paths)} changed file(s)."

    ordered = [domain for domain in domains if domain in affected]
    values = {
        "domains": json.dumps(ordered),
        "all": str(bool(all_flag)).lower(),
        "any": str(bool(ordered)).lower(),
        "shared": str(bool(shared)).lower(),
        "reason": reason,
    }

    summary = render_summary(attribution, reason, ordered, all_flag, shared, args.mode)
    write_outputs(values, summary)

    print(reason)
    print(f"domains={values['domains']}")
    print(f"all={values['all']} any={values['any']} shared={values['shared']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
