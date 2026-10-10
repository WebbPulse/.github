"""The stamp script, run against a fake `aws` on PATH that records its arguments."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "resolve_stamp.sh"


@pytest.fixture
def harness(tmp_path):
    """A bin directory holding a fake aws, an output file and an argument log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    args_log = tmp_path / "aws_args"
    reply = tmp_path / "aws_reply"
    fake = bin_dir / "aws"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$@" > "{args_log}"\n'
        f'cat "{reply}"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return {"bin": bin_dir, "output": output, "args": args_log, "reply": reply}


def run(harness, reply="0.82.0\n", **overrides):
    """Run the script with the action's defaults, returning the completed process."""
    harness["reply"].write_text(reply, encoding="utf-8")
    env = {
        "PATH": f"{harness['bin']}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(harness["output"]),
        "STAMP_FRESH_DEPENDENCIES": "false",
        "STAMP_RUN_ID": "123456",
        "STAMP_DOMAIN_OWNER": "111122223333",
        "STAMP_PACKAGE": "webbpulse",
        "STAMP_REPOSITORY": "python",
        "STAMP_DOMAIN": "webbpulse",
    }
    env.update(overrides)
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True
    )


def outputs(harness):
    """The lines the script appended to GITHUB_OUTPUT."""
    return harness["output"].read_text(encoding="utf-8").splitlines()


def test_newest_version_is_the_stamp(harness):
    """The newest Published version keys the dependency layer."""
    result = run(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs(harness) == ["dependency-stamp=0.82.0"]


def test_query_disables_pagination_and_sorts_by_published_time(harness):
    """Pagination is off, so a version list spanning pages still yields one line."""
    run(harness)
    args = harness["args"].read_text(encoding="utf-8").splitlines()
    assert args[:2] == ["codeartifact", "list-package-versions"]
    assert "--no-paginate" in args
    pairs = dict(zip(args, args[1:]))
    assert pairs["--domain"] == "webbpulse"
    assert pairs["--domain-owner"] == "111122223333"
    assert pairs["--repository"] == "python"
    assert pairs["--format"] == "pypi"
    assert pairs["--package"] == "webbpulse"
    assert pairs["--status"] == "Published"
    assert pairs["--sort-by"] == "PUBLISHED_TIME"
    assert pairs["--query"] == "versions[0].version"
    assert pairs["--output"] == "text"


def test_package_repository_and_domain_pass_through(harness):
    """A caller can stamp from a package other than webbpulse."""
    run(
        harness,
        STAMP_PACKAGE="other",
        STAMP_REPOSITORY="npm",
        STAMP_DOMAIN="acme",
    )
    args = harness["args"].read_text(encoding="utf-8").splitlines()
    pairs = dict(zip(args, args[1:]))
    assert pairs["--package"] == "other"
    assert pairs["--repository"] == "npm"
    assert pairs["--domain"] == "acme"


def test_fresh_dependencies_stamps_the_run_id_without_calling_aws(harness):
    """A fresh run needs no credentials and no domain owner."""
    result = run(harness, STAMP_FRESH_DEPENDENCIES="true", STAMP_DOMAIN_OWNER="")
    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs(harness) == ["dependency-stamp=123456"]
    assert not harness["args"].exists()


def test_missing_domain_owner_fails(harness):
    """Without a domain owner the lookup cannot run, so the step fails before calling aws."""
    result = run(harness, STAMP_DOMAIN_OWNER="")
    assert result.returncode == 1
    assert "domain-owner is empty" in result.stdout
    assert outputs(harness) == []
    assert not harness["args"].exists()


@pytest.mark.parametrize("reply", ["", "\n", "None\n"])
def test_nothing_resolved_fails(harness, reply):
    """An empty reply or the CLI's None never becomes a stamp."""
    result = run(harness, reply=reply)
    assert result.returncode == 1
    assert "No Published webbpulse version" in result.stdout
    assert outputs(harness) == []


def test_more_than_one_line_fails(harness):
    """A paginated reply is refused rather than written to GITHUB_OUTPUT."""
    result = run(harness, reply="0.82.0\n0.1.0\n")
    assert result.returncode == 1
    assert "returned 2 lines" in result.stdout
    assert outputs(harness) == []


def test_aws_failure_fails(harness):
    """A failing CLI call fails the step."""
    harness["bin"].joinpath("aws").write_text(
        "#!/usr/bin/env bash\nexit 255\n", encoding="utf-8"
    )
    result = run(harness)
    assert result.returncode != 0
    assert outputs(harness) == []
