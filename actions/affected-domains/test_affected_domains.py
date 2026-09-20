"""The attribution rules, exercised against a real git history in tmp_path.

The fixture repository is a miniature of the layout the product repos are moving
to: an `app/common` tree, two domains with an entrypoint each, a lazy per-domain
router loader, and a by-name registry the static walk cannot follow.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import affected_domains  # noqa: E402


def write(root, relative, text):
    """Create a file under root, parents included."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def git(root, *args):
    """Run a git command in the fixture repository."""
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A git repository holding the two-domain backend layout, committed once."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "ci@example.invalid")
    git(root, "config", "user.name", "CI")

    write(root, "backend/pyproject.toml", "[project]\nname = \"fixture\"\n")
    write(root, "backend/Dockerfile", "FROM scratch\n")
    write(root, "backend/uv.lock", "version = 1\n")
    write(root, "backend/README.md", "# fixture\n")

    write(root, "backend/app/__init__.py", "")
    write(root, "backend/app/main.py", "from app.common.composition import wiring\n")

    write(root, "backend/app/common/__init__.py", "")
    write(root, "backend/app/common/settings.py", "VALUE = 1\n")
    write(root, "backend/app/common/logging.py", "MESSAGE = 'hello'\n")
    write(root, "backend/app/common/orphan.py", "UNUSED = True\n")
    write(root, "backend/app/common/data.json", "{}\n")

    write(root, "backend/app/common/composition/__init__.py", "")
    write(
        root,
        "backend/app/common/composition/wiring.py",
        "from app.common import settings\n"
        "\n"
        "\n"
        "def alpha_routers():\n"
        "    from app.domains.alpha import router\n"
        "\n"
        "    return router\n"
        "\n"
        "\n"
        "def beta_routers():\n"
        "    from app.domains.beta import router\n"
        "\n"
        "    return router\n",
    )

    write(root, "backend/app/common/db/__init__.py", "")
    write(
        root,
        "backend/app/common/db/registry.py",
        "import importlib\n"
        "\n"
        "\n"
        "def build(name):\n"
        "    return importlib.import_module(f'app.common.db.{name}')\n",
    )
    write(root, "backend/app/common/db/users.py", "USERS = 1\n")
    write(root, "backend/app/common/db/parts.py", "PARTS = 2\n")

    write(root, "backend/app/domains/__init__.py", "")
    write(root, "backend/app/domains/alpha/__init__.py", "")
    write(
        root,
        "backend/app/domains/alpha/entrypoint.py",
        "from app.common import logging\n"
        "from app.common.composition import wiring\n"
        "from app.domains.alpha import router\n",
    )
    write(root, "backend/app/domains/alpha/router.py", "ROUTES = []\n")
    write(root, "backend/app/domains/alpha/service.py", "def serve():\n    return 1\n")
    write(root, "backend/app/domains/alpha/helpers.py", "HELPER = True\n")
    write(root, "backend/app/domains/alpha/late.py", "LATE = True\n")

    write(root, "backend/app/domains/beta/__init__.py", "")
    write(
        root,
        "backend/app/domains/beta/entrypoint.py",
        "from app.common.composition import wiring\n"
        "from app.domains.alpha import service\n"
        "from app.domains.beta import loader\n"
        "from app.domains.beta import router\n",
    )
    write(root, "backend/app/domains/beta/router.py", "ROUTES = []\n")
    write(
        root,
        "backend/app/domains/beta/loader.py",
        "def load():\n    from app.domains.alpha import late\n\n    return late\n",
    )

    write(root, "backend/tests/test_top.py", "def test_top():\n    assert True\n")
    write(root, "backend/tests/common/test_common.py", "def test_common():\n    assert True\n")
    write(
        root,
        "backend/tests/domains/alpha/test_alpha.py",
        "def test_alpha():\n    assert True\n",
    )
    write(
        root,
        "backend/tests/domains/beta/test_beta.py",
        "def test_beta():\n    assert True\n",
    )
    write(root, "backend/e2e/test_edge.py", "def test_edge():\n    assert True\n")
    write(root, "backend/scripts/seed.py", "SEED = 1\n")
    write(root, "backend/docs/design.md", "# design\n")
    write(root, "terraform/main.tf", "# empty\n")
    write(root, "frontend/index.html", "<p></p>\n")
    write(root, ".github/workflows/deploy.yml", "name: deploy\n")

    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return root


def commit(root, changes, message="change"):
    """Apply a mapping of relative path to text, commit, and return base and head."""
    base = git(root, "rev-parse", "HEAD")
    for relative, text in changes.items():
        write(root, relative, text)
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)
    return base, git(root, "rev-parse", "HEAD")


def run(root, base, head, **kwargs):
    """Invoke the action's script and return its outputs as a mapping."""
    output = root / "outputs.txt"
    output.write_text("", encoding="utf-8")
    argv = [
        "--repo-root",
        str(root),
        "--working-directory",
        kwargs.get("working_directory", "backend"),
        "--base",
        base,
        "--head",
        head,
        "--mode",
        kwargs.get("mode", "ci"),
        "--unattributed",
        kwargs.get("unattributed", "all"),
        "--extra-full-paths",
        kwargs.get("extra_full_paths", ""),
    ]
    summary = root / "summary.md"
    env = {"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)}
    previous = {}
    for key, value in env.items():
        previous[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        affected_domains.main(argv)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    values = {}
    for line in output.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        values[key] = value
    values["_summary"] = summary.read_text(encoding="utf-8")
    return values


def test_a_domain_change_affects_only_that_domain(repo):
    """The narrowest case, and the whole point of the action."""
    base, head = commit(repo, {"backend/app/domains/alpha/router.py": "ROUTES = [1]\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == ["alpha"]
    assert result["all"] == "false"
    assert result["any"] == "true"


def test_a_domain_module_another_domain_imports_is_attributed_to_both(repo):
    """Beta's entrypoint imports alpha's service, so a fix there has to deploy both."""
    base, head = commit(
        repo, {"backend/app/domains/alpha/service.py": "def serve():\n    return 2\n"}
    )
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == ["alpha", "beta"]
    assert result["all"] == "true"


def test_a_domain_module_nobody_imports_stays_with_its_own_domain(repo):
    """An unimported helper is alpha's alone, so a fan-out here would be noise."""
    base, head = commit(repo, {"backend/app/domains/alpha/helpers.py": "HELPER = False\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == ["alpha"]
    assert result["all"] == "false"


def test_a_lazily_imported_cross_domain_module_follows_the_lazy_rules(repo):
    """Beta reaches alpha's `late` through a function body import inside its own tree."""
    base, head = commit(repo, {"backend/app/domains/alpha/late.py": "LATE = False\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == ["alpha", "beta"]


def test_a_domain_module_a_router_loader_reaches_stays_with_its_own_domain(repo):
    """A lazy `app.domains.<name>` import from shared wiring is still that domain's alone."""
    write(
        repo,
        "backend/app/domains/alpha/router.py",
        "from app.domains.alpha import helpers\n\nROUTES = []\n",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "router")

    base, head = commit(repo, {"backend/app/domains/alpha/helpers.py": "HELPER = 1\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == ["alpha"]


def test_a_common_file_reaches_only_the_domains_that_import_it(repo):
    """`logging` is imported by alpha's entrypoint alone, so beta is untouched."""
    base, head = commit(repo, {"backend/app/common/logging.py": "MESSAGE = 'bye'\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == ["alpha"]


def test_a_common_file_every_domain_imports_affects_all(repo):
    """`settings` is reached through the shared wiring module, so both domains rebuild."""
    base, head = commit(repo, {"backend/app/common/settings.py": "VALUE = 2\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == ["alpha", "beta"]
    assert result["all"] == "true"


def test_the_lazy_router_loader_is_attributed_to_its_own_domain(repo):
    """Beta's router is loaded lazily from shared wiring, so it stays beta's alone."""
    base, head = commit(repo, {"backend/app/domains/beta/router.py": "ROUTES = [2]\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == ["beta"]


def test_a_runtime_file_forces_every_domain(repo):
    """The Dockerfile rebuilds every image, so nothing narrower is honest."""
    base, head = commit(repo, {"backend/Dockerfile": "FROM scratch\nRUN true\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == ["alpha", "beta"]
    assert result["all"] == "true"


def test_a_readme_in_the_working_directory_is_not_a_runtime_file(repo):
    """A README next to the Dockerfile ships in the image but changes no behaviour."""
    base, head = commit(repo, {"backend/README.md": "# fixture two\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == []
    assert result["all"] == "false"
    assert result["any"] == "false"


def test_a_non_python_common_file_forces_every_domain(repo):
    """The walk cannot follow a data file, so every domain has to be assumed."""
    base, head = commit(repo, {"backend/app/common/data.json": '{"a": 1}\n'})
    result = run(repo, base, head, mode="deploy")
    assert result["all"] == "true"


def test_an_unreached_app_file_follows_the_unattributed_policy(repo):
    """`orphan.py` is in no closure, so the policy decides."""
    base, head = commit(repo, {"backend/app/common/orphan.py": "UNUSED = False\n"})
    assert run(repo, base, head, mode="deploy")["all"] == "true"

    base, head = commit(repo, {"backend/app/common/orphan.py": "UNUSED = None\n"})
    narrow = run(repo, base, head, mode="deploy", unattributed="none")
    assert json.loads(narrow["domains"]) == []


def test_the_composed_app_is_unattributed(repo):
    """`app/main.py` sits outside common and domains, so it takes the policy."""
    base, head = commit(repo, {"backend/app/main.py": "# composed\n"})
    assert run(repo, base, head, mode="deploy")["all"] == "true"
    base, head = commit(repo, {"backend/app/main.py": "# composed again\n"})
    assert json.loads(run(repo, base, head, mode="deploy", unattributed="none")["domains"]) == []


def test_a_domain_test_change_is_ci_only(repo):
    """CI runs that domain's shard; a deploy has nothing to ship."""
    base, head = commit(
        repo, {"backend/tests/domains/alpha/test_alpha.py": "def test_alpha():\n    assert 1\n"}
    )
    ci = run(repo, base, head, mode="ci")
    assert json.loads(ci["domains"]) == ["alpha"]
    assert ci["shared"] == "false"

    deploy = run(repo, base, head, mode="deploy")
    assert json.loads(deploy["domains"]) == []
    assert deploy["shared"] == "false"


def test_a_cross_cutting_test_change_runs_the_shared_shard_only(repo):
    """Tests at the top of the tree are the shared shard's, not any domain's."""
    base, head = commit(repo, {"backend/tests/test_top.py": "def test_top():\n    assert 1\n"})
    ci = run(repo, base, head, mode="ci")
    assert json.loads(ci["domains"]) == []
    assert ci["shared"] == "true"
    assert run(repo, base, head, mode="deploy")["shared"] == "false"


@pytest.mark.parametrize(
    "path", ["backend/e2e/test_edge.py", "backend/scripts/seed.py", "backend/docs/design.md"]
)
def test_the_support_trees_run_the_shared_shard_only(repo, path):
    """e2e, scripts and docs never ship, and never pick a domain."""
    base, head = commit(repo, {path: "# touched\n"})
    ci = run(repo, base, head, mode="ci")
    assert json.loads(ci["domains"]) == []
    assert ci["shared"] == "true"
    assert json.loads(run(repo, base, head, mode="deploy")["domains"]) == []


def test_a_code_change_also_runs_the_shared_shard(repo):
    """Cross-cutting tests cover the code, so a code change cannot skip them."""
    base, head = commit(repo, {"backend/app/domains/alpha/router.py": "ROUTES = [3]\n"})
    assert run(repo, base, head, mode="ci")["shared"] == "true"


def test_paths_outside_the_working_directory_are_ignored(repo):
    """A frontend edit is no business of the backend matrix."""
    base, head = commit(repo, {"frontend/index.html": "<p>hi</p>\n"})
    result = run(repo, base, head, mode="ci")
    assert json.loads(result["domains"]) == []
    assert result["shared"] == "false"


def test_extra_full_paths_force_every_domain(repo):
    """Terraform and the deploy workflow can move every function, so they force all."""
    base, head = commit(repo, {"terraform/main.tf": "# changed\n"})
    result = run(repo, base, head, mode="deploy", extra_full_paths="terraform/**\n")
    assert json.loads(result["domains"]) == ["alpha", "beta"]
    assert result["all"] == "true"

    base, head = commit(repo, {".github/workflows/deploy.yml": "name: deploy!\n"})
    forced = run(
        repo, base, head, mode="deploy", extra_full_paths=".github/workflows/deploy.yml\n"
    )
    assert forced["all"] == "true"


def test_an_unknown_base_yields_every_domain(repo):
    """An empty base means the diff cannot be trusted, so nothing is skipped."""
    head = git(repo, "rev-parse", "HEAD")
    result = run(repo, "", head, mode="deploy")
    assert json.loads(result["domains"]) == ["alpha", "beta"]
    assert result["all"] == "true"
    assert "unknown" in result["reason"] or "empty" in result["reason"]


def test_an_unresolvable_base_yields_every_domain(repo):
    """A sha that no fetch can find is unknown, not an empty diff."""
    head = git(repo, "rev-parse", "HEAD")
    result = run(repo, "0" * 40, head, mode="ci")
    assert result["all"] == "true"
    assert result["shared"] == "true"


def test_a_base_that_is_not_an_ancestor_yields_every_domain(repo):
    """A force push leaves a base off the branch, and a plain diff would under-report."""
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "side")
    write(repo, "backend/app/common/settings.py", "VALUE = 99\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "side")
    side = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    write(repo, "backend/app/domains/alpha/router.py", "ROUTES = [9]\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "main")
    head = git(repo, "rev-parse", "HEAD")

    assert base
    result = run(repo, side, head, mode="deploy")
    assert result["all"] == "true"
    assert "ancestor" in result["reason"]


def test_an_empty_diff_affects_nothing(repo):
    """Base equal to head is a known diff of zero files, not an unknown one."""
    head = git(repo, "rev-parse", "HEAD")
    result = run(repo, head, head, mode="ci")
    assert json.loads(result["domains"]) == []
    assert result["all"] == "false"
    assert result["any"] == "false"
    assert result["shared"] == "false"


def test_loaded_by_name_maps_globs_to_the_registry_importers(repo):
    """A module reached only through importlib belongs to whoever reaches the registry."""
    write(
        repo,
        "backend/pyproject.toml",
        "[project]\nname = \"fixture\"\n"
        "\n"
        "[tool.webbpulse.reachability]\n"
        "anchor = \"app.common.db.registry\"\n"
        "loaded-by-name = [\"app.common.db.*\"]\n",
    )
    write(
        repo,
        "backend/app/domains/alpha/entrypoint.py",
        "from app.common import logging\n"
        "from app.common.composition import wiring\n"
        "from app.common.db import registry\n"
        "from app.domains.alpha import router\n",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "registry")

    base, head = commit(repo, {"backend/app/common/db/parts.py": "PARTS = 3\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == ["alpha"]


def test_loaded_by_name_without_an_anchor_falls_back_to_every_domain(repo):
    """With no anchor the globs cannot be narrowed, so the safe reading is all."""
    write(
        repo,
        "backend/pyproject.toml",
        "[project]\nname = \"fixture\"\n"
        "\n"
        "[tool.webbpulse.reachability]\n"
        "loaded-by-name = [\"app.common.db.*\"]\n",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "registry")

    base, head = commit(repo, {"backend/app/common/db/users.py": "USERS = 9\n"})
    assert run(repo, base, head, mode="deploy")["all"] == "true"


def test_a_by_name_module_is_not_left_unattributed(repo):
    """Without the table the registry's modules are unreached, so the policy applies."""
    base, head = commit(repo, {"backend/app/common/db/users.py": "USERS = 4\n"})
    assert run(repo, base, head, mode="deploy", unattributed="none")["domains"] == "[]"
    base, head = commit(repo, {"backend/app/common/db/users.py": "USERS = 5\n"})
    assert run(repo, base, head, mode="deploy", unattributed="all")["all"] == "true"


def test_the_step_summary_holds_a_path_to_domains_table(repo):
    """The summary is the record of why a domain was or was not built."""
    base, head = commit(
        repo,
        {
            "backend/app/common/logging.py": "MESSAGE = 'x'\n",
            "backend/app/domains/beta/router.py": "ROUTES = [4]\n",
        },
    )
    summary = run(repo, base, head, mode="ci")["_summary"]
    assert "## Affected domains" in summary
    assert "| Changed path | Domains |" in summary
    assert "backend/app/common/logging.py" in summary
    assert "backend/app/domains/beta/router.py" in summary


def test_a_domain_needs_an_entrypoint_to_be_discovered(repo):
    """A directory under domains without an entrypoint is not a deployable domain."""
    write(repo, "backend/app/domains/gamma/__init__.py", "")
    write(repo, "backend/app/domains/gamma/router.py", "ROUTES = []\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "gamma")

    base, head = commit(repo, {"backend/app/domains/gamma/router.py": "ROUTES = [5]\n"})
    result = run(repo, base, head, mode="deploy")
    assert json.loads(result["domains"]) == []
    assert "gamma" not in result["domains"]


def test_a_type_checking_import_does_not_pull_in_a_domain(repo):
    """A TYPE_CHECKING block never runs, so it cannot widen a closure."""
    write(
        repo,
        "backend/app/common/logging.py",
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from app.common import orphan\n"
        "\n"
        "MESSAGE = 'hello'\n",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "typing")

    base, head = commit(repo, {"backend/app/common/orphan.py": "UNUSED = 1\n"})
    result = run(repo, base, head, mode="deploy", unattributed="none")
    assert json.loads(result["domains"]) == []
