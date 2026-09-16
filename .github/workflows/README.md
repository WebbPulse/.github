# WebbPulse reusable workflows

Shared `workflow_call` workflows for every WebbPulse repository. Call them from an
application repository instead of copying CI and deploy steps around.

## The rule this repository lives by

**This repository is public and carries nothing estate specific.** No AWS account
ids, no role ARNs, no bucket names, no ECR registry hostnames, no domain names, no
CloudFront distribution ids, no HCP workspace names. Every one of those values
arrives from the caller as an `input` or a `secret`.

Practical consequences for callers:

- Account scoped values that are not sensitive but do identify the estate (bucket
  name, distribution id, ECR repository, region) are passed as `inputs`, normally
  sourced from a GitHub Environment `vars` entry.
- Role ARNs, the CodeArtifact domain owner account id, and the HCP token are passed
  as `secrets`.
- Use a GitHub Environment per stage so a `staging` run can never read `production`
  values. Every deploy workflow takes an `environment` input for exactly this.

Every third party action is pinned to a full commit SHA with a version comment, per
GitHub's [security hardening guidance](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions).
Each workflow sets the least privilege `permissions:` it needs, and deploy workflows
carry a `concurrency` group so two runs never overlap on one target.

---

## `python-ci.yml`

**uv only.** Every job installs with uv from a committed `uv.lock`, pinned to uv 0.12.10.
Lint, type check and security each run once. Pytest fans out into **one job per domain**
plus a `shared` job carrying everything outside the domain directories, so wall clock time
tracks the largest domain rather than the sum of every domain. A final `all-checks-passed`
job is the single stable context a branch ruleset requires.

An optional CodeArtifact step runs before the install in every job that installs, minting a
token and exporting it as `UV_INDEX_<NAME>_USERNAME` and `UV_INDEX_<NAME>_PASSWORD` so uv can
resolve the private index. The token is masked and never printed.

After the install, an **activate** step puts `<working-directory>/.venv/bin` on `PATH` and
sets `VIRTUAL_ENV`, so `ruff`, `pyright`, `bandit`, `pip-audit`, `python` and `pytest` resolve
from the project environment without a `uv run` prefix.

### Jobs

| Job | Runs when | Notes |
| --- | --- | --- |
| `Discover domains` | always | Walks the test tree in a bare interpreter, no install. |
| `Lint` | `ruff-target` or `lint-commands` non empty | `ruff check`, `ruff format --check`, then each extra command. |
| `Type check` | `typecheck-command` non empty | |
| `Security` | `security-commands` non empty | |
| `Tests (<domain>)` | one per discovered domain, after `domains-filter` | `fail-fast: false`, so a two-domain break needs one run, not two. |
| `Tests (shared)` | `run-shared` is true | Everything outside the domain directories. Whole suite when there are none. |
| `all-checks-passed` | always | The context to require. See [Merging: auto-merge on green](#merging-auto-merge-on-green). |

### Domains are directories

There is no domain list to maintain. A domain is an **immediate subdirectory of
`domains-root` that contains at least one `test_*.py` or `*_test.py` anywhere below it**.
Each domain job runs pytest on `<domains-root>/<domain>`; the `shared` job runs
`<test-root> --ignore=<domains-root>`, so the jobs together run each test exactly once.

The calling repository's `pyproject.toml` configures the roots:

```toml
[tool.webbpulse.ci]
test-root = "tests"
domains-root = "tests/domains"
entrypoints = "app/entrypoints"
```

| Key | Default | Meaning |
| --- | --- | --- |
| `test-root` | `tests` | Directory the `shared` job sweeps. |
| `domains-root` | `<test-root>/domains` | Parent of the per-domain test directories. |
| `entrypoints` | `""` | When set, every domain directory must have a matching entrypoint. |

Paths are relative to `working-directory`. With `entrypoints` set, a domain directory
`tests/domains/identity` requires **either** a flat `app/entrypoints/identity.py` **or** a
domain package `app/domains/identity/entrypoint.py`; a hyphen in a directory name maps to an
underscore in the module name. Either layout satisfies the check, so a repository moving to
the `common` plus `domains` layout keeps the guard instead of deleting the key, and a
repository part way through the move can hold both. Discovery **fails** naming the directories
with no entrypoint and listing what does exist in both layouts, so a test directory can never
drift away from the deployable it covers.

A repository with no `domains-root` directory gets no domain jobs and a `shared` job carrying
everything, so the workflow can be called unconditionally.

A `[tool.webbpulse.ci.domains]` table is a **hard error** in v3. Discovery stops and points at
the directory convention.

### Adding a domain

1. Create `tests/domains/<name>/` with the domain's tests, and the matching entrypoint
   (`app/entrypoints/<name>.py` or `app/domains/<name>/entrypoint.py`) if `entrypoints` is set.
2. Open the pull request. `Discover domains` picks it up and a `Tests (<name>)` job appears.

No workflow edit and **no ruleset edit**: the required context is `all-checks-passed`, which
does not change when the matrix does.

Add `pytest-xdist` to the project's dev dependency group. The `pytest-workers` input defaults
to `auto`, and without the plugin the workflow drops `-n` and logs a warning rather than
running the domains in parallel.

### Running only the domains a change touched

`domains-filter` and `run-shared` narrow the matrix without changing what a domain is.
Discovery still walks the test tree and still enforces the `entrypoints` guard against
**every** domain, so a filtered run cannot hide a test directory that has drifted away from
its deployable. The filter is applied last, intersecting the discovered domains with the
array, so a name in the filter that is not a domain is ignored rather than conjuring a shard.

Pair it with [`actions/affected-domains`](#actionsaffected-domains), which works out the list:

```yaml
jobs:
  affected:
    runs-on: ubuntu-latest
    outputs:
      domains: ${{ steps.affected.outputs.domains }}
      shared: ${{ steps.affected.outputs.shared }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - id: affected
        uses: WebbPulse/.github/actions/affected-domains@v3
        with:
          base: ${{ github.event.pull_request.base.sha }}
          mode: ci

  backend-ci:
    needs: affected
    uses: WebbPulse/.github/.github/workflows/python-ci.yml@v3
    with:
      domains-filter: ${{ needs.affected.outputs.domains }}
      run-shared: ${{ needs.affected.outputs.shared == 'true' }}
```

Omitting both inputs keeps the previous behaviour exactly: every discovered domain gets a
shard and the `shared` shard always runs. Lint, type check and security are untouched by
either input, because they read the whole tree regardless of which domain moved.

`all-checks-passed` stays the required context. A skipped shard counts as a pass there, so a
filtered run still reports the one context a branch ruleset waits on, and no ruleset edit is
needed to adopt this.

### Inputs

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `python-version` | string | `3.13` | Python uv provisions for the project environment. |
| `working-directory` | string | `backend` | Directory holding `pyproject.toml` and `uv.lock`. |
| `install-command` | string | `uv sync --locked` | Run in `working-directory`. Override to float a package, see below. |
| `ruff-target` | string | `.` | Paths for ruff. Empty skips both ruff steps. |
| `lint-commands` | string | `""` | Extra lint commands, one per line. |
| `typecheck-command` | string | `""` | Empty skips the type check job. |
| `security-commands` | string | `""` | Security scans, one per line. Empty skips the job. |
| `pytest-args` | string | `""` | Appended to every pytest run. **Not for paths.** |
| `pytest-workers` | string | `auto` | Value for xdist `-n`. Empty omits `-n` for a suite that is not xdist safe. |
| `coverage-source` | string | `app` | Package measured by coverage. |
| `test-env-json` | string | `{}` | Env vars exported before pytest. Not for secrets: inputs appear in the log. |
| `domains-filter` | string | `""` | JSON array intersected with the discovered domains. `[]` means no domain shards. Empty means no filtering. |
| `run-shared` | boolean | `true` | False skips the `shared` shard. |
| `runs-on` | string | `ubuntu-latest` | Runner label. |
| `codeartifact-domain` | string | `""` | Non empty enables the CodeArtifact auth step. |
| `codeartifact-index` | string | `codeartifact` | Name of the `[[tool.uv.index]]` entry the token authenticates. |
| `aws-region` | string | `""` | Required with `codeartifact-domain`. |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | no | Needed only for the CodeArtifact auth step. |
| `codeartifact-domain-owner` | no | Account id owning the domain. |

Outputs: none.

### The `codeartifact` index name

`codeartifact-index` must match the `name` of the `[[tool.uv.index]]` entry in the caller's
`pyproject.toml`. The workflow upper-cases it and replaces every non-alphanumeric character
with an underscore to build the variable names, so the conventional `codeartifact` becomes
`UV_INDEX_CODEARTIFACT_USERNAME` and `UV_INDEX_CODEARTIFACT_PASSWORD`:

```toml
[[tool.uv.index]]
name = "codeartifact"
url = "https://<domain>-<owner>.d.codeartifact.<region>.amazonaws.com/pypi/<repository>/"
explicit = true

[tool.uv.sources]
webbpulse = { index = "codeartifact" }
```

`explicit = true` plus the `tool.uv.sources` binding means the private package can only ever
be satisfied from CodeArtifact, never from PyPI.

Coverage is collected per job and uploaded as an artifact per domain. It is **not** gated per
domain: a domain job sees only its own tests, so any per-job threshold would measure the wrong
thing. The `shared` job writes the coverage summary, labelled as the floor it is.

```yaml
jobs:
  backend-ci:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/python-ci.yml@v3
    with:
      working-directory: backend
      coverage-source: app
      typecheck-command: pyright
      codeartifact-domain: webbpulse
      aws-region: us-west-2
      install-command: >-
        uv lock --upgrade-package webbpulse && uv sync --locked &&
        uv run --no-sync python -c "import importlib.metadata as m; print('webbpulse', m.version('webbpulse'))"
      security-commands: |
        bandit -r app -ll
        uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/requirements-audit.txt && pip-audit --no-deps -r /tmp/requirements-audit.txt
    secrets:
      role-to-assume: ${{ secrets.AWS_CI_ROLE_ARN }}
      codeartifact-domain-owner: ${{ secrets.CODEARTIFACT_DOMAIN_OWNER }}
```

That `install-command` re-locks only `webbpulse`, so an adopter picks up the newest shared
package on every run while every other dependency stays at the committed lock. A repository
that is itself the package uses the default `uv sync --locked`.
---

## `typescript-ci.yml`

Node setup with the package manager cache, install, lint, format check, typecheck,
unit tests, and build. An optional CodeArtifact npm login runs before the install.
A second `playwright` job runs only when `run-playwright` is true, and uploads the
report as an artifact. A final `all-checks-passed` job gates both, and is the context
a branch ruleset requires. See [Merging: auto-merge on green](#merging-auto-merge-on-green).

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `node-version` | string | `22` | |
| `working-directory` | string | `frontend` | |
| `package-manager` | string | `npm` | `npm` or `pnpm`. Picks the cache and lockfile. |
| `cache-dependency-path` | string | `""` | Lockfile path for the setup-node cache, from the repository root. Empty derives `<working-directory>/package-lock.json`. See [Workspaces monorepos](#workspaces-monorepos). |
| `install-command` | string | `""` | Empty means `npm ci` or `pnpm install --frozen-lockfile`. |
| `lint-command` | string | `npm run lint` | Empty skips the step. |
| `format-check-command` | string | `""` | Empty skips the step. |
| `typecheck-command` | string | `npm run type-check` | Empty skips the step. |
| `test-command` | string | `npm test -- --run --coverage` | Empty skips the step. |
| `build-command` | string | `npm run build` | Empty skips the step. |
| `run-playwright` | boolean | `false` | Enables the end to end job. |
| `playwright-command` | string | `npx playwright test` | |
| `playwright-browsers` | string | `chromium` | Passed to `playwright install`. |
| `build-env-json` | string | `{}` | JSON object of build variables, for example `VITE_` values. |
| `runs-on` | string | `ubuntu-latest` | |
| `codeartifact-domain` / `codeartifact-repository` / `aws-region` | string | `""` | Same gating as `python-ci.yml`. |
| `codeartifact-namespace` | string | `"@webbpulse"` | npm scope to bind. Must start with `@`; the workflow fails when `codeartifact-domain` is set and this is empty or unscoped. See [Scope the npm login](#scope-the-npm-login). |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | no | Needed only for the CodeArtifact login. |
| `codeartifact-domain-owner` | no | Account id owning the domain. |

### Scope the npm login

`aws codeartifact login --tool npm` without `--namespace` rewrites the runner's default
npm registry, so every `npm ci` pulls the entire public registry through CodeArtifact and
bills it as CodeArtifact data transfer and requests. `codeartifact-namespace` binds a single
scope instead, so only that scope resolves from CodeArtifact and everything else goes
straight to npmjs.org.

It defaults to `@webbpulse`, the scope for the shared packages, and the workflow fails
before the login when `codeartifact-domain` is set and the namespace is empty or does not
start with `@`. A caller with a different scope passes it; no caller can turn the binding
off. The same input and the same rule exist on `spa-deploy.yml` and `e2e-local.yml`.

Outputs: none.

```yaml
jobs:
  frontend-ci:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/typescript-ci.yml@v3
    with:
      working-directory: frontend
      node-version: "22"
      run-playwright: true
```

---

## `container-image.yml`

Builds one domain image with buildx for a single platform, logs in to ECR through
OIDC, pushes the immutable tag `sha-<full git sha>` (or
`sha-<full git sha>-<image-tag-suffix>`), and returns the digest and the
digest pinned image URI so a deploy job can pin the exact artifact. Optionally mints
a CodeArtifact token for the build, logs in to a second account's registry so a
cross account base image can be pulled, skips a build whose tag already exists, and
writes each build's digest to its own artifact so a matrix of calls can be collected.

**Why `provenance: false`.** When buildx attaches provenance or SBOM attestations it
publishes an OCI image index (a manifest list) rather than a single image manifest.
The [Lambda container image
requirements](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html) state:
"Lambda provides multi-architecture base images. However, the image you build for
your function must target only one of the architectures. Lambda does not support
functions that use multi-architecture container images." A function pointed at an
index fails. Lambda accepts Docker image manifest V2 schema 2 and OCI specification
v1.0.0 and up, which is what a single platform build without attestations produces.
The workflow also asserts the pushed manifest media type is not an index, so a bad
build fails here rather than at deploy time.

**Why the CodeArtifact token is a BuildKit secret, not a build argument.** A build
argument is recorded in `docker history` and readable by anyone who can pull the
image. The token is minted after the credentials step, masked with `::add-mask::`,
exported to the job environment, and handed to `docker/build-push-action` through
`secret-envs`, which names the variable rather than carrying the value. The
Dockerfile reads it with `RUN --mount=type=secret,id=codeartifact_token`. The
mount id is the `codeartifact-secret-id` input, defaulting to `codeartifact_token`.
The input names match `python-ci.yml` so the two workflows are configured the same
way, with one difference: `codeartifact-domain-owner` is an input here, not a
secret, because it is an account id rather than a credential and a matrix caller
usually already has it in a repository variable.

`codeartifact:GetAuthorizationToken` alone is not enough. The assumed role also
needs `sts:GetServiceBearerToken` conditioned on
`sts:AWSServiceName = codeartifact.amazonaws.com`; without it the call fails with a
denial that names no CodeArtifact action at all.

**Why `additional-ecr-registries` exists, and what it changes.** `amazon-ecr-login`
with no `registries:` authenticates the caller's own account registry and nothing
else, so a `FROM` pointing at a base image in another account fails with a 401 from
a host Docker holds no credential for. That is a missing Docker credential, not a
missing IAM grant, and it does not present as one. Passing account ids here logs in
to those registries as well.

Two consequences are handled inside the workflow. `amazon-ecr-login` takes a comma
delimited list and stops assuming the default registry once a list is given, so the
caller's own account id is prepended automatically and does not need naming. And its
`registry` output is documented as not set when it logs in to more than one
registry, so the workflow resolves the caller's own registry host from
`sts get-caller-identity` plus `aws-region` instead of reading that output. The push
target is unchanged either way: the caller's own account.

**Why the existing tag guard.** ECR repositories in this estate are created with
`IMMUTABLE` tags and the default tag is `sha-<full git sha>`, so re-running a green
commit pushes a tag that already exists. If the rebuild is byte identical ECR treats
the re-tag as a no-op and it succeeds; if anything moved, `PutImage` fails with
`ImageTagAlreadyExistsException` for a reason unrelated to the commit under test.
With `skip-if-tag-exists` left at its default the workflow resolves the tag first
and, when it is already there, skips the build and emits the existing digest as the
outputs, so the rerun is green and still returns a usable URI.

The check uses `aws ecr batch-get-image`, not `describe-images`. A consumer deploy
role typically holds `ecr:BatchGetImage` on its own domain repositories but
`ecr:DescribeImages` only on the shared base image repository, so `describe-images`
would be denied on exactly the repositories this needs to read.

**Why `image-tag-suffix` exists.** The skip is keyed on the tag, and the tag is keyed
on the commit alone, so a rebuild that is meant to change the image without changing
the commit is skipped and the old digest is redeployed. A dependency refresh is the
case that matters: a caller stamps a build argument so the layer that resolves the
newest package rebuilds, but on an already built commit the tag is unchanged and no
build runs at all. Passing a suffix gives that run its own immutable tag, so the
build happens and a new digest is pushed. Left empty the tag and the skip behave
exactly as before. The suffix is validated against `[A-Za-z0-9_.-]+` and the whole
tag against the 128 character ECR limit, so an unusable tag fails at the first step
rather than at `PutImage`.

**Why the base image is served from the Actions cache.** The layer cache
(`cache-from`/`cache-to: type=gha`) caches the layers the build produces, not the
layers it pulls. BuildKit still fetches every `FROM` layer from the registry to
export the final image, so a cross account base image was downloaded from ECR on
every build of every domain, billed as ECR data transfer out.

Before the build, the workflow reads the `ARG BASE_IMAGE=` default out of the
Dockerfile it is about to build, keys an `actions/cache` entry on that reference
plus the platform, and keeps a single platform OCI layout of the base image there.
On a miss it copies the image out of ECR with `skopeo`, which is preinstalled on
`ubuntu-latest` and reuses the `amazon-ecr-login` credentials already in the Docker
config. It then passes `build-contexts: <reference>=oci-layout://<dir>@<manifest
digest>` to `docker/build-push-action`, so BuildKit resolves the `FROM` out of the
local layout. ECR is read once per base digest per repository rather than on every
build.

The `ARG BASE_IMAGE=` line stays the single source of truth, so Dependabot's docker
ecosystem updates continue to drive the base image and no caller repository changes.
The cache path is skipped, and the build behaves exactly as before, when the
Dockerfile has no `ARG BASE_IMAGE=` default, when that default is not pinned by
digest, when `platform` names more than one platform, or when the copy produced no
single platform manifest. The `additional-ecr-registries` login therefore still
matters: it is what makes the cache miss path work.

The restore, copy and save live in [`actions/base-image-cache`](#actionsbase-image-cache)
so the same logic serves both this workflow and the
[`base-image-cache.yml`](#base-image-cacheyml) warm up job. A caller with no warm up
job keeps working unchanged: every matrix leg still restores, and still falls back to
`skopeo` on a miss.

**Why the manifest artifact.** A matrix of reusable workflow calls collapses to one
`needs` entry in the caller whose `outputs` hold whichever leg finished last, and a
job with `uses:` cannot carry `steps:` to capture them itself. With
`upload-manifest-artifact: true` each leg uploads a one file artifact named
`image-<sanitised repository>-<tag>` containing:

```json
{
  "repository": "webbpulse-staging/content",
  "tag": "sha-<full git sha>",
  "digest": "sha256:...",
  "image_uri": "<account>.dkr.ecr.<region>.amazonaws.com/webbpulse-staging/content@sha256:..."
}
```

A downstream job reads all of them with `actions/download-artifact` using
`pattern: image-*` and `merge-multiple: true`, which lands one JSON file per leg in
a single directory, and assembles the `function-image-map` that
`lambda-image-deploy.yml` takes.

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `ecr-repository` | string | required | Repository name only, no registry host. |
| `aws-region` | string | required | |
| `context` | string | `.` | Docker build context. |
| `dockerfile` | string | `Dockerfile` | |
| `platform` | string | `linux/arm64` | Exactly one platform. |
| `build-args` | string | `""` | Newline separated build arguments. |
| `codeartifact-domain` | string | `""` | Empty skips minting a token. |
| `codeartifact-domain-owner` | string | `""` | Account id owning the domain. Required when `codeartifact-domain` is set. |
| `codeartifact-repository` | string | `""` | Required when `codeartifact-domain` is set. |
| `codeartifact-secret-id` | string | `codeartifact_token` | BuildKit secret id the Dockerfile mounts. |
| `additional-ecr-registries` | string | `""` | Comma or newline separated account ids. The caller's own is always included. |
| `image-tag-suffix` | string | `""` | Appended to the tag as `sha-<full git sha>-<suffix>`. Empty keeps the plain `sha-<full git sha>`. Must match `[A-Za-z0-9_.-]+`. |
| `skip-if-tag-exists` | boolean | `true` | Skip the build when the tag already resolves, and emit the existing digest. |
| `upload-manifest-artifact` | boolean | `false` | Upload the per leg JSON manifest. |
| `artifact-name` | string | `""` | Overrides the default `image-<sanitised repository>-<tag>`. |
| `environment` | string | `""` | GitHub Environment the build job binds to. Set it here rather than on the caller job: GitHub rejects a job that both `uses:` a reusable workflow and declares `environment:`. |
| `runs-on` | string | `ubuntu-latest` | |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | yes | Allowed to push to the ECR repository, and to read CodeArtifact and any additional registry when those are used. |

| Output | Notes |
| --- | --- |
| `image-digest` | `sha256:...`, whether built or already present. |
| `image-uri` | `registry/repository@sha256:...` |
| `image-tag` | `sha-<full git sha>`, with `-<image-tag-suffix>` appended when that input is set. |
| `image-existed` | `true` when the tag already resolved and the build was skipped. |

Single image, no CodeArtifact, no cross account base:

```yaml
jobs:
  image:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/container-image.yml@v3
    with:
      ecr-repository: ${{ vars.ECR_REPOSITORY }}
      aws-region: ${{ vars.AWS_REGION }}
      context: backend
      dockerfile: backend/Dockerfile
    secrets:
      role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
```

Four domain images from one Dockerfile, with the CodeArtifact token, a base image
pulled from the Artifacts account, and the per leg manifests collected into a
`function-image-map`. The deploy role ARN lives in an environment variable, and a
job that `uses:` a reusable workflow can neither declare `environment:` nor read
environment scoped `vars`, so a small `resolve-env` job binds to the environment,
exports the ARN, and the build legs pass the environment name through the
`environment` input instead:

```yaml
jobs:
  resolve-env:
    runs-on: ubuntu-latest
    environment: ${{ github.ref_name == 'main' && 'production' || 'staging' }}
    permissions:
      contents: read
    outputs:
      name: ${{ github.ref_name == 'main' && 'production' || 'staging' }}
      role-arn: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
    steps:
      - run: 'true'

  build-images:
    needs: resolve-env
    strategy:
      fail-fast: false
      matrix:
        domain: [content, resume, identity, public]
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/container-image.yml@v3
    with:
      environment: ${{ needs.resolve-env.outputs.name }}
      ecr-repository: webbpulse-${{ needs.resolve-env.outputs.name }}/${{ matrix.domain }}
      aws-region: us-west-2
      context: backend
      dockerfile: backend/Dockerfile
      platform: linux/arm64
      build-args: |
        DOMAIN=${{ matrix.domain }}
        READINESS_PROTOCOL=${{ matrix.domain == 'public' && 'tcp' || 'http' }}
      codeartifact-domain: webbpulse
      codeartifact-domain-owner: ${{ vars.CODEARTIFACT_DOMAIN_OWNER }}
      codeartifact-repository: python
      # The Artifacts account, which holds the shared python-lambda-base image the
      # Dockerfile's FROM pins by digest.
      additional-ecr-registries: "432410731887"
      upload-manifest-artifact: true
    secrets:
      role-to-assume: ${{ needs.resolve-env.outputs.role-arn }}

  image-map:
    needs: build-images
    runs-on: ubuntu-latest
    permissions:
      contents: read
    outputs:
      function-image-map: ${{ steps.map.outputs.function-image-map }}
    steps:
      - uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1
        with:
          path: manifests
          pattern: image-*
          merge-multiple: true

      - id: map
        env:
          ENVIRONMENT: ${{ github.ref_name == 'main' && 'production' || 'staging' }}
        run: |
          set -euo pipefail
          MAP=$(python3 - <<'PY'
          import json, os, pathlib

          env = os.environ["ENVIRONMENT"]
          out = {}
          for path in sorted(pathlib.Path("manifests").glob("*.json")):
              m = json.loads(path.read_text())
              domain = m["repository"].rsplit("/", 1)[-1]
              out[f"webbpulse-{env}-{domain}"] = m["image_uri"]
          print(json.dumps(out))
          PY
          )
          echo "function-image-map=${MAP}" >> "$GITHUB_OUTPUT"
```

---

## `base-image-cache.yml`

Runs [`actions/base-image-cache`](#actionsbase-image-cache) once, on a single job, so a
caller can warm the key before its build matrix fans out. Call it before
`container-image.yml` and every matrix leg then restores instead of pulling.

**The two problems it fixes.** The cache key is derived from the base image reference
plus the platform, so the first run after the base image moves has every matrix leg
miss at the same time and pull the same image concurrently, once per leg. And GitHub
lets a branch read the default branch's caches but never the reverse, so a key written
only on `staging` is never readable on `main`: without a warm up, every production
deploy misses on every leg, forever. One job writing the key ahead of the fan out
fixes both, and on `main` it writes the key where the matrix can read it.

```yaml
  warm-base-image:
    name: Warm the base image cache
    needs: [resolve-env, affected]
    if: needs.affected.outputs.any == 'true'
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/base-image-cache.yml@v3
    with:
      environment: ${{ needs.resolve-env.outputs.name }}
      aws-region: us-west-2
      dockerfile: backend/Dockerfile
      platform: linux/arm64
      additional-ecr-registries: "432410731887"
    secrets:
      role-to-assume: ${{ needs.resolve-env.outputs.role-arn }}
```

The build matrix then adds `warm-base-image` to its `needs`. That is the whole caller
change: one job block plus one `needs` entry.

| Input | Default | Notes |
| --- | --- | --- |
| `aws-region` | required | Region holding the ECR registries. |
| `dockerfile` | `Dockerfile` | Path to the Dockerfile the matrix builds. Pass the same value the matrix passes. |
| `working-directory` | `""` | Directory the dockerfile path resolves against. Empty means the workspace root. |
| `platform` | `linux/arm64` | Must match what the matrix passes, since the key covers the platform. |
| `additional-ecr-registries` | `""` | Further registry account ids to log in to. The caller's own account is always included. |
| `environment` | `""` | GitHub Environment to bind the job to. |
| `runs-on` | `ubuntu-latest` | Runner label. |

| Secret | Notes |
| --- | --- |
| `role-to-assume` | IAM role ARN assumed via OIDC, needing only read access to the base image repository. |

| Output | Notes |
| --- | --- |
| `cache-key` | The key the build matrix will restore. |
| `cache-hit` | `true` when the layout was already cached, so nothing was pulled. |
| `base-image` | The digest pinned reference read out of the Dockerfile. |
| `enabled` | `true` when the cache applies to this Dockerfile and platform. |

The job needs `id-token: write` from the caller.

Because the build matrix reaches it through `needs`, a failed warm up does stop the
deploy rather than degrading it. That is the price of keeping the caller change to one
job block plus one `needs` entry. The correctness of the build does not depend on it:
the matrix legs still restore the key themselves and still fall back to `skopeo` on a
miss, so a caller that would rather trade the pull for the resilience can add
`always() &&` to its build job's `if` and let the warm up fail open.

---

## `lambda-image-deploy.yml`

Points one or many functions at an image URI: waits for the function to settle,
runs `update-function-code --image-uri`, waits again with `function-updated-v2`
(container image functions stay `Pending` while Lambda optimizes the image), then
optionally probes a smoke URL with retries.

**Every function updates concurrently.** The per function work runs in the background
inside the one job, so a fleet takes about as long as its slowest function instead of
the sum of all of them. Almost all of the roughly ten seconds a function takes is
Lambda's own image update latency, so a thirteen function map went from about 140
seconds to about 20. Output stays readable: each function's log is captured to its own
file and the files are printed as `::group::<function>` blocks in map order once every
function has finished, so nothing interleaves. A failing function does not abort its
siblings; the step waits for all of them, prints every group, then fails naming the
functions that failed.

**Why it waits before updating, and retries.** Terraform owns function configuration
in this estate, and `image_uri` is under `ignore_changes` in the Lambda module, so a
deploy only ever moves the digest. But a Terraform apply changing configuration can be
in flight when a deploy starts. The Lambda documentation states that while
`"LastUpdateStatus": "InProgress"`, `UpdateFunctionCode`, `UpdateFunctionConfiguration`
and `PublishVersion` all fail. So the deploy waits with `function-updated-v2` **before**
calling `update-function-code`, and additionally retries `ResourceConflictException`
with a backoff, because an apply can still start in the gap between the wait returning
and the update landing. Any other error fails the deploy immediately.

Pass either `function-name` plus `image-uri`, or a `function-image-map` JSON object
of function name to image URI. The map form is how a multi domain deploy fans out.

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `function-name` | string | `""` | Single function form. |
| `image-uri` | string | `""` | Single function form. |
| `function-image-map` | string | `""` | JSON object, wins over the single form. |
| `aws-region` | string | required | |
| `publish-version` | boolean | `true` | Publish a version after the update. |
| `environment` | string | `""` | GitHub Environment for scoped vars and approvals. |
| `concurrency-group` | string | `""` | Defaults to workflow plus ref. |
| `smoke-url` | string | `""` | Empty skips the smoke test. |
| `smoke-expected-status` | string | `200` | |
| `smoke-attempts` | number | `10` | |
| `smoke-delay-seconds` | number | `6` | |
| `runs-on` | string | `ubuntu-latest` | |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | yes | Allowed to update the functions. |
| `smoke-header` | no | Extra request header as `Name: value`, for a gated staging host. |

Outputs: none.

```yaml
jobs:
  deploy:
    needs: image
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/lambda-image-deploy.yml@v3
    with:
      aws-region: ${{ vars.AWS_REGION }}
      environment: production
      function-image-map: >-
        {"${{ vars.API_FUNCTION_NAME }}": "${{ needs.image.outputs.image-uri }}"}
      smoke-url: ${{ vars.API_BASE_URL }}/health
    secrets:
      role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
```

---

## `spa-deploy.yml`

Builds the frontend, syncs to S3 in three passes, and invalidates CloudFront. An
optional CodeArtifact npm login runs before the install.

Three passes, in this order, so a deploy is never briefly broken:

1. **Hashed assets**, `max-age=31536000, immutable`, no `--delete`. The assets the
   currently served `index.html` references stay in place.
2. **Entry files** (`index.html` and anything else unhashed), `no-cache`, still no
   `--delete`. Once this lands the edge serves the new HTML, and both the new and the
   previous asset sets are present, so no request can miss.
3. **Prune**, `--delete` over the whole tree with no filters.

Pass three is separate on purpose. The AWS CLI documents `--delete` as "Files that
exist in the destination but not in the source are deleted during sync. Note that
files excluded by filters are excluded from deletion." A `--delete` carried on either
filtered pass would therefore never prune what that pass filtered out, so stale hashed
assets would accumulate in the bucket forever. Pass three uploads nothing new, because
the first two passes already uploaded every source file, so the cache headers set
above are preserved.

`/index.html` and `/` are always invalidated: `/` is what a visitor requests and
`/index.html` is what the origin serves for it. Hashed assets never need invalidating,
because a new build gives them new keys. `invalidation-paths` appends extra paths, and
`/*` invalidates everything. The invalidation then waits for completion so the job does
not report success before the edge is serving the build.

**Most callers should turn the invalidation off.** Pass two uploads the entry files with
`no-cache, no-store, must-revalidate`, and the `spa-frontend` module's default cache policy
is the managed CachingOptimized policy, whose minimum TTL is one second. CloudFront therefore
holds an entry file for about a second and refetches it from S3, so a deploy is live on the
next request with or without an invalidation. CloudFront bills invalidations per path
submitted, the first 1000 a month free and shared across the whole organisation under
consolidated billing, then USD 0.005 each, and a viewer request function that rewrites
`/about` to `/about/index.html` means the cache key is the rewritten path, so listing
`/about` matches nothing. Set `invalidate-cloudfront: false` unless the distribution gives
the entry files a real TTL; in that case invalidate `/*`, which counts as one path.

**Private packages.** A frontend that imports the shared `@webbpulse/*` packages needs
`codeartifact-domain`, `codeartifact-repository` and the `codeartifact-domain-owner`
secret. The login runs from the repository root, before the install, so `npm ci`
resolves the scoped packages. Setting `codeartifact-domain` also moves the OIDC role
assumption ahead of the install, since the login needs credentials; the single session
then carries through to the S3 and CloudFront steps. Leave `codeartifact-domain` empty
and the role is assumed after the build, exactly as before.

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `node-version` | string | `22` | |
| `working-directory` | string | `frontend` | |
| `package-manager` | string | `npm` | `npm` or `pnpm`. |
| `cache-dependency-path` | string | `""` | Lockfile path for the setup-node cache, from the repository root. Empty derives `<working-directory>/package-lock.json`. See [Workspaces monorepos](#workspaces-monorepos). |
| `install-command` | string | `""` | Empty means `npm ci` or `pnpm install --frozen-lockfile`. |
| `build-command` | string | `npm run build` | |
| `build-output-directory` | string | `dist` | Relative to `working-directory`. |
| `build-env-json` | string | `{}` | JSON object of build variables. |
| `s3-bucket` | string | required | |
| `s3-prefix` | string | `""` | Optional key prefix. |
| `cloudfront-distribution-id` | string | `""` | Empty skips the invalidation. |
| `invalidate-cloudfront` | boolean | `true` | `false` skips the invalidation even when a distribution id is set. The right value for a distribution whose entry files carry `no-cache` under a minimum TTL of a second or less. |
| `invalidation-paths` | string | `""` | Space separated **extra** paths. `/index.html` and `/` are always invalidated. Ignored when `invalidate-cloudfront` is `false`. |
| `immutable-asset-globs` | string | `assets/*` | Files treated as content hashed. |
| `aws-region` | string | required | |
| `environment` | string | `""` | GitHub Environment. |
| `concurrency-group` | string | `""` | Defaults to workflow plus ref. |
| `runs-on` | string | `ubuntu-latest` | |
| `codeartifact-domain` | string | `""` | Non empty enables the npm login before the install. |
| `codeartifact-repository` | string | `""` | Required with `codeartifact-domain`, validated at run time. |
| `codeartifact-namespace` | string | `"@webbpulse"` | npm scope to bind. Must start with `@`; the workflow fails when `codeartifact-domain` is set and this is empty or unscoped. See [Scope the npm login](#scope-the-npm-login). |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | yes | Writes the bucket and invalidates the distribution. |
| `codeartifact-domain-owner` | no | Account id owning the domain. Required with `codeartifact-domain`. |

Outputs: none.

```yaml
jobs:
  deploy-frontend:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/spa-deploy.yml@v3
    with:
      environment: production
      s3-bucket: ${{ vars.FRONTEND_S3_BUCKET }}
      cloudfront-distribution-id: ${{ vars.CLOUDFRONT_DISTRIBUTION_ID }}
      invalidate-cloudfront: false
      aws-region: ${{ vars.AWS_REGION }}
      codeartifact-domain: ${{ vars.CODEARTIFACT_DOMAIN }}
      codeartifact-repository: ${{ vars.CODEARTIFACT_REPOSITORY }}
      build-env-json: >-
        {"VITE_API_BASE_URL": "${{ vars.API_BASE_URL }}"}
    secrets:
      role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
      codeartifact-domain-owner: ${{ secrets.CODEARTIFACT_DOMAIN_OWNER }}
```

---

## `e2e.yml`

Verifies a **deployed** environment after its deploy jobs succeed, then publishes a check
run on the deployed commit so a release pull request can require a green staging run.

What it checks, through the real edge rather than a mock:

- **Route cut.** Every live gateway route is exercised and the access log entry is read back,
  so the assertion is that the expected `routeKey` and integration served the request.
- **Coverage.** Every OpenAPI operation matches a live route key under API Gateway
  precedence, with the authorizer attached exactly where the operation needs auth.
- **Reachability.** Every parameterless operation is called anonymously and as the durable
  e2e user, and the status must be one the specification declares, never a gateway 404, a
  403 from the gate, or a 5xx.
- **Identity.** Login, refresh, logout and JWKS, with the token's algorithm, issuer and
  audience checked against this environment. Staging additionally exercises minted tokens.
- **Frontend.** The web origin serves the app shell, a bad path still renders it, the bundle
  references the configured API base URL and none of the legacy route names, and a CORS
  preflight from the web origin allows the headers the shared client sends.
- **Browser.** Playwright for Python drives the deployed origin: sign in and sign out through
  the real UI, route guard behaviour, every declared route rendering clean, and each
  product-declared journey.

The suite lives in `webbpulse.e2e` and in each product's `e2e/` directory; this workflow only
supplies the environment and reports the result. The API and browser groups are one pytest
run, so there is a single suite step.

**Read-only production.** The full suite, sign in and browser journeys and every write
included, runs against staging only. After a production deploy the same workflow runs a
read-only smoke: anonymous, no sign in, no mutations, and no e2e user in production.
`read-only-environments` lists the environments that run this way and defaults to
`production`. When the environment the gate resolved is in that list the job exports
`E2E_READ_ONLY=true` and the plugin skips every signed-in and mutating test; otherwise it
exports `false`. In read-only mode `E2E_USER_EMAIL` and `E2E_USER_PASSWORD` are neither
resolved nor required, so a production Environment with no e2e user and no password secret is
the expected shape. The check run keeps the name `e2e (<environment>)` and its title and
summary say `read-only`, so a reader of the production check knows what was verified.

**Secrets stay out of the log.** The workflow never reads the gate value: it passes the SSM
parameter name as `E2E_GATE_SSM_PARAMETER` and the suite reads the SecureString itself with
boto3 at run time. The e2e user's password arrives as a secret, so GitHub masks it.

**The gate cookie inputs.** The staging web origin sits behind the access gate, so browser and
frontend requests need minted CloudFront signed cookies. `gate-signing-key-ssm-parameter`,
`gate-key-pair-id` and `gate-cookie-domain` carry what the suite needs to mint them, and the
signing key is read from SSM by the suite so the PEM never reaches the workflow. All three are
empty in production, which has no gate.

**The check run is always published.** The last step runs under `if: always()` with
`checks: write` and creates a check named `check-name` on the `sha` input, defaulting to the
caller's `github.sha`. Its summary links the run, reports the suite outcome, and lists the
failed test ids parsed out of the junit report when one was written. The job itself still
fails on a red suite, so the deploy workflow goes red and GitHub notifies.

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `environment` | string | `""` | `staging` or `production`. Empty derives it from the deployed branch. |
| `sha` | string | `""` | Commit the check run lands on. Empty lets the gate resolve it. |
| `deploy-workflows` | string | `""` | Comma separated deploy workflow names, in ownership order. Empty disables the sibling wait. |
| `production-branch` | string | `main` | Branch whose deploys mean production. |
| `read-only-environments` | string | `production` | Comma separated environments that run read only. Sets `E2E_READ_ONLY`. |
| `api-base-url` | string | `""` | Empty reads `vars.E2E_API_BASE_URL`. |
| `web-base-url` | string | `""` | Empty reads `vars.E2E_WEB_BASE_URL`. |
| `aws-region` | string | `us-west-2` | |
| `api-id` | string | `""` | API Gateway v2 api id. Empty reads `vars.E2E_API_ID`. |
| `access-log-group` | string | `""` | Empty reads `vars.E2E_ACCESS_LOG_GROUP`. |
| `gate-ssm-parameter` | string | `""` | Empty reads `vars.E2E_GATE_SSM_PARAMETER`. |
| `gate-signing-key-ssm-parameter` | string | `""` | Empty reads `vars.E2E_GATE_SIGNING_KEY_SSM_PARAMETER`. |
| `gate-key-pair-id` | string | `""` | Empty reads `vars.E2E_GATE_KEY_PAIR_ID`. |
| `gate-cookie-domain` | string | `""` | Empty reads `vars.E2E_GATE_COOKIE_DOMAIN`. |
| `user-email` | string | `""` | Durable e2e user. Empty reads `vars.E2E_USER_EMAIL`. |
| `working-directory` | string | `.` | Python project root with `pyproject.toml` and `uv.lock`. |
| `e2e-directory` | string | `e2e` | Directory pytest collects, relative to `working-directory`. |
| `install-command` | string | `uv sync --locked --only-group e2e` | |
| `python-version` | string | `3.13` | |
| `pytest-args` | string | `""` | |
| `browser` | string | `chromium` | Playwright browser the suite drives. |
| `timeout-minutes` | number | `90` | Minutes the suite job may run before GitHub cancels it, so a hung run never blocks the next one queued in the concurrency group. |
| `headless` | boolean | `true` | Run the browser headless. |
| `check-name` | string | `""` | Empty derives `e2e (<environment>)`. |
| `legacy-route-names` | string | `""` | Comma separated, must not appear in the bundle. Empty reads `vars.E2E_LEGACY_ROUTE_NAMES`. |
| `mint-enabled` | boolean | `false` | Also turns on when the resolved KMS key id is non-empty. |
| `kms-key-id` | string | `""` | Empty reads `vars.E2E_KMS_KEY_ID`. |
| `issuer` | string | `""` | Empty reads `vars.E2E_ISSUER`. |
| `audience` | string | `""` | Empty reads `vars.E2E_AUDIENCE`. |
| `codeartifact-domain` | string | `""` | Empty skips the CodeArtifact auth step. |
| `codeartifact-index` | string | `codeartifact` | |
| `runs-on` | string | `ubuntu-latest` | |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | no | Reads the gateway, the access log group and the gate parameter. Empty reads `vars.AWS_DEPLOY_ROLE_ARN`. |
| `E2E_USER_PASSWORD` | staging only | Durable e2e user's password. Define it as an Environment secret on staging: the job runs under the target environment, so that value is the one read, and the repository-level value may stay unset. Production is read only, so the secret is unset there and the caller's mapping simply resolves empty. `e2e-user-password` is the deprecated name. |
| `codeartifact-domain-owner` | no | Required when `codeartifact-domain` is set. Empty reads `vars.CODEARTIFACT_DOMAIN_OWNER`. |

Outputs: none. The result is the check run and the job conclusion.

The caller must grant `actions: read` so the gate can poll sibling deploy runs.

### The caller

The workflow carries the gate, the environment resolution and the value lookup, so a caller
is a trigger block and a `uses:`. This is the standard shape for every product:

```yaml
name: E2E

on:
  workflow_run:
    workflows: ["Deploy Backend", "Frontend Deploy"]
    types: [completed]
    branches: [main, staging]
  workflow_dispatch:

permissions:
  contents: read
  actions: read
  id-token: write

concurrency:
  group: e2e-${{ github.event.workflow_run.head_branch || github.ref_name }}
  cancel-in-progress: false

jobs:
  e2e:
    permissions:
      contents: read
      actions: read
      id-token: write
      checks: write
    uses: WebbPulse/.github/.github/workflows/e2e.yml@v3
    with:
      deploy-workflows: "Deploy Backend, Frontend Deploy"
      working-directory: backend
      install-command: uv sync --locked --group e2e
      pytest-args: "--no-cov"
    secrets:
      E2E_USER_PASSWORD: ${{ secrets.E2E_USER_PASSWORD }}
```

`deploy-workflows` must list the same workflow names as the `workflow_run` trigger, in
ownership order. `actions: read` is what lets the gate poll sibling runs, and `checks: write`
must be granted on the calling job, not only inside this workflow, because a reusable workflow
can never hold a permission its caller did not.

`cancel-in-progress: false` is deliberate. A staging and a production run can be in flight at
once, and cancelling the earlier one would leave its check run unpublished.

Two GitHub rules shape the caller. A `workflow_run` or `workflow_dispatch` workflow only exists
once its file is on the default branch, so a caller merged to `staging` alone never fires; land
the identical file on `main` first. And a `workflow_run` run always executes on the default
branch, so the `staging` GitHub Environment's deployment branch policy must allow `main` as well
as `staging`, otherwise the e2e job is rejected before its first step with "Branch main is not
allowed to deploy to staging".

### The gate

The first job decides whether this run owns the suite, which commit it verifies, and which
environment it targets.

- On `workflow_dispatch`, when `deploy-workflows` is empty, or on any event that is not
  `workflow_run`, the run owns the suite. The commit is the `sha` input or `github.sha`, and
  the environment is the `environment` input or derived from `github.ref_name`.
- On `workflow_run` the triggering deploy must have concluded `success`, otherwise the suite
  is skipped. The commit is the deploy's `head_sha`, and the environment is `production` when
  the deploy's branch equals `production-branch` and `staging` otherwise. An explicit
  `environment` input wins over the derivation.
- Each name in `deploy-workflows` is then polled on that commit, every 30 seconds for up to
  30 minutes. A name with **no run on the commit** was path filtered and is ignored. A name
  still running is waited for. A name that completed **without** success skips the suite,
  since there is nothing sound to verify.
- Ownership is deterministic: the **first** name in `deploy-workflows` order that has a run on
  the commit owns the suite. Every other triggering workflow yields, so two green deploys on
  one commit produce exactly one suite run rather than two.

### Environment variables

Every value resolves as the explicit `with:` input when non-empty, and otherwise as a
variable on the GitHub Environment the gate selected. Products that follow the convention set
variables and pass no value inputs at all.

| Variable | staging | production |
| --- | --- | --- |
| `E2E_API_BASE_URL` | required | required |
| `E2E_WEB_BASE_URL` | required | required |
| `E2E_USER_EMAIL` | required | unset |
| `AWS_DEPLOY_ROLE_ARN` | required | required |
| `E2E_API_ID` | required | required |
| `E2E_ACCESS_LOG_GROUP` | required | required |
| `E2E_ISSUER` | required | required |
| `E2E_AUDIENCE` | required | required |
| `E2E_LEGACY_ROUTE_NAMES` | optional | optional |
| `CODEARTIFACT_DOMAIN_OWNER` | with `codeartifact-domain` | with `codeartifact-domain` |
| `E2E_GATE_SSM_PARAMETER` | required | unset |
| `E2E_GATE_SIGNING_KEY_SSM_PARAMETER` | required | unset |
| `E2E_GATE_KEY_PAIR_ID` | required | unset |
| `E2E_GATE_COOKIE_DOMAIN` | required | unset |
| `E2E_KMS_KEY_ID` | required | unset |

`E2E_USER_PASSWORD` is an Environment **secret**, not a variable, and is the one value the
caller still passes through `secrets:`. It is staging only, and so is `E2E_USER_EMAIL`:
production runs read only, so neither is resolved or required there.

The gate variables and `E2E_KMS_KEY_ID` are unset in production because production has no
access gate and refuses minted tokens. Minting turns on when the resolved `E2E_KMS_KEY_ID` is
non-empty or `mint-enabled` is true, so leaving the production variable unset is what keeps
minting to staging.

A step before anything else lists every required value that resolved empty in one error, so a
missing variable fails in seconds rather than midway through the suite.

**Explicit inputs are overrides.** A product that cannot use the variable names, or that needs
a value the convention does not cover, passes it with `with:` and that wins. The inputs are
unchanged, so a caller written against the earlier tag keeps working.

**Branch protection.** `e2e (staging)` is the required check for the release pull request into
`main`. Add it, or whatever `check-name` resolves to on staging, to the required status checks
on `main` in the product's ruleset. The staging deploy publishes that check on the commit it
deployed, and the release pull request from `staging` to `main` carries the same commit, so a
red staging run blocks promotion. The production run is a read-only smoke that reports only:
it publishes `e2e (production)` after the fact and is never a required check.

---

## `e2e-local.yml`

Runs the same `webbpulse.e2e` suite as `e2e.yml`, but against a **local stack built from
source on the runner** rather than a deployed environment. It is meant for pull requests, so
a broken handler, a broken login, a broken bundle or a broken page is caught before the branch
is deployed.

The stack is three processes and no AWS runtime calls:

- **DynamoDB Local** as a service container, published on `dynamodb-port` (8001 by default).
- **The backend**, started from source by `backend-start-command`, which defaults to
  `uv run uvicorn app.composition.app:app --host 127.0.0.1 --port 8000`. That is the composed
  app carrying every domain on one port, which is contract equivalent to the deployed fan out
  for everything the suite asserts locally.
- **The SPA**, built by `frontend-build-command` and served by `preview-command`, which
  defaults to `npx vite preview --host 127.0.0.1 --port 4173`.

The only AWS the job touches is the existing OIDC plus CodeArtifact token exchange during the
dependency install, because the shared `webbpulse` package and the `@webbpulse/*` npm scope
have no public mirror. Everything else is local: no Secrets Manager, no KMS, no SES, no S3, no
gateway, no SSM, no X-Ray.

**What runs locally, and what stays post deploy.** The local run carries **Reachability**,
**Identity** minus minting, **Frontend** and **Browser**. **Route cut** is skipped, since
nothing local forwards an API Gateway request context and there is no access log group, and
**Coverage** is degraded to comparing the OpenAPI document against a route table synthesized
from that same document. Per domain isolation, the authorizer, the staging access gate, the
stream consumers and the SQS work queues have no local analogue at all. A green local run is
therefore not a substitute for `e2e (staging)`; the post deploy run stays required.

**Secrets are the caller's.** This workflow generates no values. Every per run secret the
stack needs, `SECRET_KEY` and the rest, arrives in `backend-env-json` from the caller. Those
are local throwaway values for a stack that is destroyed with the runner, not real secrets, so
the input appearing in the run log is the expected shape. Do not put a real secret in it.

### The two rules that keep it non required

- **Keep the calling job out of `all-checks-passed`'s `needs`.** That aggregator is the
  required context in every product ruleset, so adding this job to it would make the local
  suite required by the back door.
- **The job never fails the caller.** The suite step is `continue-on-error: true`, the check
  run is published with the suite's real conclusion, and the job then ends green. A red local
  suite shows as a red `e2e (local)` check and a green job, so it reports without blocking.
  A caller that wants the job itself to go red can set `continue-on-error` on its own side,
  but then rule one is doing all the work.

The check run is created through the API under `check-name`, so it is not one of the job's own
statuses and never appears in branch protection unless someone adds it. On a `pull_request`
event `head_sha` is `github.event.pull_request.head.sha`, not `github.sha`, which is the merge
commit nobody is looking at.

### Inputs

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `working-directory` | string | `backend` | Python project root with `pyproject.toml` and `uv.lock`. |
| `e2e-directory` | string | `e2e` | Directory pytest collects, relative to `working-directory`. |
| `install-command` | string | `uv sync --locked --group e2e` | Run in `working-directory`. |
| `python-version` | string | `3.13` | |
| `pytest-args` | string | `""` | A project whose `pytest.ini` pins `--cov` in `addopts` passes `-o addopts=`. |
| `codeartifact-domain` | string | `""` | Empty skips both CodeArtifact auth steps. |
| `codeartifact-index` | string | `codeartifact` | The `[[tool.uv.index]]` entry the token authenticates. |
| `codeartifact-repository` | string | `""` | Empty skips the npm login. Required to resolve `@webbpulse/*`. |
| `codeartifact-namespace` | string | `"@webbpulse"` | npm scope to bind. Must start with `@`; the workflow fails when the npm login runs and this is empty or unscoped. See [Scope the npm login](#scope-the-npm-login). |
| `aws-region` | string | `us-west-2` | For the CodeArtifact token. The stack calls no AWS API. |
| `node-version` | string | `22` | |
| `frontend-directory` | string | `frontend` | Holds `package.json` and `package-lock.json`. |
| `frontend-build-command` | string | `npm run build` | Run in `frontend-directory`. |
| `frontend-build-env-json` | string | `{}` | Exported before the build, for the Vite variable carrying the local API base URL. |
| `preview-command` | string | `npx vite preview --host 127.0.0.1 --port 4173` | Backgrounded in `frontend-directory`. |
| `web-base-url` | string | `http://127.0.0.1:4173` | Must match `preview-command`. Becomes `E2E_WEB_BASE_URL`. |
| `backend-env-json` | string | `{}` | The whole local stack configuration. See below. |
| `backend-start-command` | string | `uv run uvicorn app.composition.app:app --host 127.0.0.1 --port 8000` | Backgrounded in `working-directory`. |
| `api-base-url` | string | `http://127.0.0.1:8000` | Must match `backend-start-command`. Becomes `E2E_API_BASE_URL`. |
| `health-path` | string | `/health` | Polled until 200, capped at 60 seconds. |
| `table-bootstrap-command` | string | `""` | For example `uv run python scripts/create_dynamo_tables.py`. Empty skips the step. |
| `dynamodb-image` | string | `amazon/dynamodb-local:latest` | The image's default command is already `-inMemory -sharedDb`. |
| `dynamodb-port` | number | `8001` | Host port. `backend-env-json` must point at it. |
| `browser` | string | `chromium` | |
| `headless` | boolean | `true` | |
| `check-name` | string | `e2e (local)` | |
| `timeout-minutes` | number | `30` | |
| `runs-on` | string | `ubuntu-latest` | |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | with `codeartifact-domain` | Reads CodeArtifact and nothing else. Empty reads `vars.CI_AWS_ROLE_ARN`. |
| `codeartifact-domain-owner` | with `codeartifact-domain` | Empty reads `vars.CODEARTIFACT_DOMAIN_OWNER`. |

Outputs: none. The result is the check run.

### Environment the workflow sets itself

`E2E_ENVIRONMENT=local`, `E2E_API_BASE_URL`, `E2E_WEB_BASE_URL`, `E2E_AWS_REGION`,
`E2E_BROWSER`, `E2E_HEADLESS`, `E2E_READ_ONLY=false` and
`E2E_RUN_ID=<run_id>-<run_attempt>`. `E2E_API_ID`, `E2E_ACCESS_LOG_GROUP`,
`E2E_GATE_SSM_PARAMETER` and `E2E_MINT_ENABLED` are deliberately left unset, which is what
selects the local behaviour in the plugin. `E2E_USER_EMAIL` and `E2E_USER_PASSWORD` come from
`backend-env-json`, pointing at a user the product's own seed creates locally, not at the
durable staging user.

### The caller

```yaml
  e2e-local:
    needs: changes
    if: needs.changes.outputs.backend == 'true' || needs.changes.outputs.frontend == 'true'
    permissions:
      contents: read
      id-token: write
      checks: write
    uses: WebbPulse/.github/.github/workflows/e2e-local.yml@v3
    with:
      working-directory: backend
      frontend-directory: frontend
      table-bootstrap-command: uv run python scripts/create_local_tables.py
      pytest-args: "-o addopts="
      codeartifact-domain: webbpulse
      codeartifact-repository: webbpulse
      codeartifact-namespace: "@webbpulse"
      frontend-build-env-json: '{"VITE_API_BASE_URL": "http://127.0.0.1:8000/api/v1"}'
      backend-env-json: ${{ vars.E2E_LOCAL_BACKEND_ENV }}
    secrets:
      role-to-assume: ${{ secrets.CI_AWS_ROLE_ARN }}
      codeartifact-domain-owner: ${{ secrets.CODEARTIFACT_DOMAIN_OWNER }}
```

`checks: write` must be granted on the calling job, not only inside this workflow, because a
reusable workflow can never hold a permission its caller did not. Gate the job on the existing
`changes` job so a docs only pull request does not pay for it, and leave it out of
`all-checks-passed`'s `needs`.

Two traps the products hit. `vite preview` does not proxy, so the SPA must be built with a
full `http://` API URL rather than a bare host, and the preview origin must be allowed by the
backend's CORS configuration and be in the preview server's `allowedHosts`. And cookies must
be usable over plain http, so the identity cookie has to be non secure with `samesite=lax`;
`samesite=none` requires `secure`, which a plain http origin never sets.

---

## `codeartifact-publish-python.yml` and `codeartifact-publish-npm.yml`

Build a shared package and publish it to CodeArtifact through OIDC into a role in
the artifacts account. Both are idempotent: the version is looked up with
`describe-package-version` before publishing, and an already published version is
skipped with a `::notice::` rather than failing, so re-running a released tag stays
green.

The Python workflow builds with `uv build` (uv pinned to 0.12.10), reads the name and
version off the wheel filename, and uploads with `uv publish`, pointed at the repository
through `UV_PUBLISH_URL` and authenticated with `UV_PUBLISH_USERNAME=aws` plus a masked
`UV_PUBLISH_PASSWORD` token. No pip, build or twine is installed. The npm workflow reads name and version
from `package.json`, splits a scoped name into the CodeArtifact namespace and package
name, and publishes with `aws codeartifact login --tool npm` followed by `npm publish`.

**CodeArtifact auth.** `GetAuthorizationToken` requires **both**
`codeartifact:GetAuthorizationToken` and `sts:GetServiceBearerToken` on the assumed
role. Missing `sts:GetServiceBearerToken` is the usual cause of a login that fails
with an access denied that mentions no CodeArtifact action. The publishing role also
needs `codeartifact:PublishPackageVersion`, `codeartifact:PutPackageMetadata`,
`codeartifact:ReadFromRepository` and `codeartifact:DescribePackageVersion` on the
repository. Tokens last 12 hours by default.

Shared inputs: `working-directory`, `codeartifact-domain` (required),
`codeartifact-repository` (required), `aws-region` (required), `environment` and
`runs-on`. `codeartifact-publish-python.yml` adds `python-version`, which is the Python
uv builds against. Inputs, secrets and outputs are unchanged from v2.

`codeartifact-publish-npm.yml` adds:

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `node-version` | string | `22` | |
| `package-manager` | string | `npm` | `npm` or `pnpm`. Picks the cache and lockfile. |
| `cache-dependency-path` | string | `""` | Lockfile path for the setup-node cache, from the repository root. Empty derives `<working-directory>/package-lock.json`, or `pnpm-lock.yaml` for pnpm. See [Workspaces monorepos](#workspaces-monorepos). |
| `install-command` | string | `""` | Install command, run from `working-directory`. Empty means `npm ci` or `pnpm install --frozen-lockfile`. See [Workspaces monorepos](#workspaces-monorepos). |
| `build-command` | string | `npm run build` | Empty skips the build. |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | yes | Role in the artifacts account allowed to publish. |
| `codeartifact-domain-owner` | yes | Account id owning the domain. |

| Output | Notes |
| --- | --- |
| `package-name` | Published package name. |
| `package-version` | Published version. |
| `published` | `true` when this run uploaded, `false` when it already existed. |

```yaml
jobs:
  publish:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/codeartifact-publish-python.yml@v3
    with:
      codeartifact-domain: ${{ vars.CODEARTIFACT_DOMAIN }}
      codeartifact-repository: ${{ vars.CODEARTIFACT_REPOSITORY }}
      aws-region: ${{ vars.AWS_REGION }}
    secrets:
      role-to-assume: ${{ secrets.CODEARTIFACT_PUBLISH_ROLE_ARN }}
      codeartifact-domain-owner: ${{ secrets.CODEARTIFACT_DOMAIN_OWNER }}
```

The npm workflow is called the same way:

```yaml
jobs:
  publish:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/codeartifact-publish-npm.yml@v3
    with:
      codeartifact-domain: ${{ vars.CODEARTIFACT_DOMAIN }}
      codeartifact-repository: ${{ vars.CODEARTIFACT_REPOSITORY }}
      aws-region: ${{ vars.AWS_REGION }}
      working-directory: packages/shared
    secrets:
      role-to-assume: ${{ secrets.CODEARTIFACT_PUBLISH_ROLE_ARN }}
      codeartifact-domain-owner: ${{ secrets.CODEARTIFACT_DOMAIN_OWNER }}
```

**Scoped npm packages.** `login --tool npm` sets the *default* registry, but npm
resolves the publish target for `@scope/name` from a `@scope:registry` setting or from
`publishConfig` in `package.json` before falling back to the default. The workflow
therefore binds `@scope:registry` to the CodeArtifact endpoint explicitly, and asserts
the resolved registry is CodeArtifact before uploading, so a private package can never
be published to the public registry by accident.

### Workspaces monorepos

Applies to `codeartifact-publish-npm.yml`, `typescript-ci.yml` and `spa-deploy.yml`.

In a single package repository the lockfile sits next to `package.json`, so deriving
the setup-node cache path as `<working-directory>/package-lock.json` is right. An npm
**workspaces** repository breaks that assumption in two places at once:

1. **The lockfile is only at the repository root.** `packages/<name>/package-lock.json`
   does not exist, and `actions/setup-node` **fails the step** when the cache path
   matches nothing, with `Some specified paths were not resolved, unable to cache
   dependencies`. The job dies at setup, before any build or publish step runs.
2. **The install has to run at the root.** `npm ci` inside a package directory installs
   that package's own dependencies only. Build tooling such as `tsup` and `typescript`
   is normally a root `devDependency`, so a package level install leaves the build
   without its binaries.

`working-directory` must still be the package directory, because the metadata, build
and publish steps read `package.json` and run `npm publish` there. Point the other two
at the root instead:

```yaml
with:
  working-directory: packages/api-client
  cache-dependency-path: package-lock.json
  install-command: npm ci --no-progress --prefix ../..
  build-command: npm run build --if-present --prefix ../.. --workspace "@webbpulse/api-client"
```

`cache-dependency-path` is relative to the **repository root**, not to
`working-directory`, because `actions/setup-node` resolves it from the workspace root.
`install-command` runs from `working-directory`, so it reaches the root with a relative
`--prefix`. Both default to `""`, which reproduces the previous derived behaviour
exactly, so a single package caller changes nothing.

Before these inputs existed the only workaround was to fold the root install into
`build-command`. That still left the setup-node cache step failing on the missing
lockfile, so it never actually got as far as building.

---

## `actions/affected-domains`

A composite action that works out which backend domains a diff actually affects, so CI
shards and deploys run only for the domains whose code changed. It reads the tree it is
run against, so there is no list to maintain and nothing estate specific in it.

A **domain** is an immediate subdirectory of `<working-directory>/app/domains/` that
contains an `entrypoint.py`, which is the same thing the image build means by `DOMAIN`.

```yaml
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false

      - id: affected
        uses: WebbPulse/.github/actions/affected-domains@v3
        with:
          base: ${{ github.event.pull_request.base.sha }}
          mode: deploy
          extra-full-paths: |
            terraform/**
            .github/workflows/deploy.yml
```

| Input | Default | Notes |
| --- | --- | --- |
| `working-directory` | `backend` | Directory holding the Python project. |
| `base` | `""` | Commit sha or ref to diff from. Empty, unresolvable, or not an ancestor of `head` means **unknown**, which yields every domain. |
| `head` | `HEAD` | Commit sha or ref to diff to. |
| `mode` | `ci` | `deploy` attributes only what ships in an image. `ci` also attributes the test tree and reports `shared`. |
| `extra-full-paths` | `""` | Repo-relative globs, one per line, that force every domain. |
| `unattributed` | `all` | What an `app/` file no entrypoint reaches yields. `none` suits a tree whose reachability test already forbids one. |

| Output | Notes |
| --- | --- |
| `domains` | JSON array of affected domain names, ready to pass to `domains-filter`. |
| `all` | `true` when every domain is affected, so a caller can keep its previous behaviour. |
| `any` | `true` when `domains` is non-empty. |
| `shared` | `ci` mode only: whether the shared test shard has to run. Always `false` in `deploy` mode. |
| `reason` | One human readable line, also written to the step summary. |

### How a path is attributed

| Changed path | Affects |
| --- | --- |
| Anything matching `extra-full-paths` | every domain |
| `<wd>/` outside `app/`, `tests/`, `e2e/`, `scripts/`, `docs/` and `README*` | every domain, since the Dockerfile, `pyproject.toml`, `uv.lock` and runtime files rebuild every image |
| `<wd>/app/domains/<name>/**` | that domain |
| `<wd>/app/common/**.py` | every domain whose entrypoint closure reaches the file |
| `<wd>/app/common/**` non Python | every domain, because the walk cannot follow a data file |
| Other `<wd>/app/**`, for example `app/main.py` | per `unattributed` |
| `<wd>/tests/domains/<name>/**` | that domain in `ci` mode, nothing in `deploy` mode |
| Other `<wd>/tests/**`, `<wd>/e2e/**`, `<wd>/scripts/**`, docs | `shared` only in `ci` mode, nothing in `deploy` mode |
| Anything outside `<wd>/` and not in `extra-full-paths` | nothing |

The action writes a changed path to domains table to `$GITHUB_STEP_SUMMARY`, so a run
records why each domain was or was not built.

### The import walk

The closure is computed **statically**, by parsing rather than importing, so it holds for
the image that ships without needing an environment. It follows module level imports and
function body imports transitively, skips `TYPE_CHECKING` blocks because they never run,
and attributes a lazy `app.domains.<name>` import made from outside any domain to `<name>`
alone. That last rule is the per-domain router loader, and it is the property that lets one
`app/` tree ship as several single-domain images.

The walk is the same one the product repositories assert in their own reachability test, so
a domain that starts reaching another domain fails that test rather than silently widening a
deploy here.

### Modules loaded by name

A module reached only through `importlib.import_module` is invisible to a static walk. A
repository with a registry like that declares it in `<working-directory>/pyproject.toml`:

```toml
[tool.webbpulse.reachability]
anchor = "app.common.db.dynamo.registry"
loaded-by-name = ["app.common.db.dynamo.*"]
```

| Key | Meaning |
| --- | --- |
| `loaded-by-name` | Dotted **module globs**, matched against the module name each file provides. |
| `anchor` | The module doing the by-name loading. A matched file is attributed to every domain whose closure reaches this module. |

`anchor` is what keeps the registry honest: a repository where only some domains touch the
registry gets only those domains, rather than every domain on every repository file. Omit it
and the globs fall back to **all** domains, which is the safe reading rather than the useful
one. The table is optional; without it a by-name module is simply unreached and takes the
`unattributed` policy.

Globs are `fnmatch` patterns over dotted module names, so `app.common.db.dynamo.*` matches
`app.common.db.dynamo.users` and also `app.common.db.dynamo.registry` itself.

---

## `actions/base-image-cache`

A composite action holding the base image restore, `skopeo` copy and save that
`container-image.yml` runs before a build. It exists separately so
[`base-image-cache.yml`](#base-image-cacheyml) can run the same logic once, ahead of a
build matrix, and the two can never drift apart.

```yaml
      - id: base
        uses: WebbPulse/.github/actions/base-image-cache@v3
        with:
          dockerfile: backend/Dockerfile
          platform: linux/arm64
          aws-region: us-west-2
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          ecr-registries: "432410731887"
```

| Input | Default | Notes |
| --- | --- | --- |
| `dockerfile` | `Dockerfile` | Path to the Dockerfile whose `ARG BASE_IMAGE=` default is read. |
| `working-directory` | `""` | Directory the dockerfile path resolves against. Empty means the workspace root. |
| `platform` | `linux/arm64` | One platform. More than one skips the cache, since the layout holds one. |
| `aws-region` | required | Region holding the ECR registries. |
| `role-to-assume` | `""` | Role assumed via OIDC. Empty skips the credentials step. |
| `ecr-registries` | `""` | Further registry account ids for the login. The caller's own account is always included. |
| `skip-login` | `false` | `true` leaves the credentials and the ECR login to the caller, which is how `container-image.yml` calls it. |

| Output | Notes |
| --- | --- |
| `enabled` | `true` when the cache applies, so `build-contexts` is worth passing on. |
| `cache-key` | `base-image-v1-<sha256 of the reference plus the platform>`. |
| `cache-hit` | `true` when the layout was restored rather than copied out of the registry. |
| `layout-path` | Directory holding the OCI layout. |
| `base-image` | The digest pinned reference read out of the Dockerfile. |
| `build-contexts` | The `<reference>=oci-layout://<dir>@<digest>` line for `docker/build-push-action`, or empty when the cache does not apply. |

Every skip path leaves `enabled` false and `build-contexts` empty rather than failing,
so a build that cannot use the cache resolves its `FROM` exactly as it did before.

---

## `terraform-speculative-plan.yml`

For a pull request touching `terraform/**`. Runs `terraform fmt -check -diff`,
`terraform init`, and `terraform validate`, and nothing else. **It posts no comment
and produces no plan.** HCP Terraform already runs the speculative plan for the pull
request and reports its own status. This workflow exists only to fail fast on
formatting and configuration errors before HCP picks the run up.

`terraform init` needs to reach the HCP workspace named in the caller's `cloud`
block, so the token is exported as `TF_TOKEN_app_terraform_io`.

| Input | Type | Default |
| --- | --- | --- |
| `working-directory` | string | `terraform` |
| `terraform-version` | string | `1.13.1` |
| `fmt-recursive` | boolean | `true` |
| `runs-on` | string | `ubuntu-latest` |

| Secret | Required | Notes |
| --- | --- | --- |
| `tf-api-token` | yes | Exported as `TF_TOKEN_app_terraform_io`. |

Outputs: none.

```yaml
on:
  pull_request:
    paths: ["terraform/**"]

jobs:
  terraform-checks:
    permissions:
      contents: read
    uses: WebbPulse/.github/.github/workflows/terraform-speculative-plan.yml@v3
    with:
      working-directory: terraform
    secrets:
      tf-api-token: ${{ secrets.TFC_API_TOKEN }}
```

---

## Merging: auto-merge on green

Every repository in the organisation has `allow_auto_merge` and `delete_branch_on_merge`
turned on. The intended flow is to queue the merge when the pull request is opened and let
CI decide:

```bash
# Every repository except WebbPulse-Portfolio
gh pr merge <number> --auto --squash

# WebbPulse-Portfolio, which keeps merge commits
gh pr merge <number> --auto --merge
```

GitHub then merges the pull request by itself the moment every required check is green and
the branch is mergeable, and deletes the branch afterwards.

**Auto-merge is only as safe as the required checks.** With none required, "mergeable" means
nothing more than the absence of a conflict, so auto-merge would merge a pull request whose
tests had not finished, or had failed. That is why each repository's `main-protection` (and
`staging-protection`, where it exists) ruleset requires exactly one status check:

```
all-checks-passed
```

That name is reported by a final job in the reusable CI workflows, which `needs` every other
job, runs with `if: always()`, and fails when any needed job's result is `failure` or
`cancelled`.

**`skipped` counts as success, deliberately.** A job skipped by its `if` is a job nobody asked
for: a caller that passes no `typecheck-command`, or a docs-only pull request whose path
filter skipped the build. Failing on `skipped` would block those pull requests on a check that
never had anything to do. Cancellation is a failure, because a cancelled job has proven
nothing and treating it as success would let a run cancelled mid-flight satisfy the ruleset.

**One gate per repository, not per workflow.** A required context must be reported on *every*
pull request or the pull request waits for it forever. Two shapes satisfy that:

1. **One `ci.yml`** on `pull_request` with no workflow-level `paths:` filter, calling each
   reusable workflow as a job and ending with the repository's own `all-checks-passed`. Path
   filtering moves inside, as a `dorny/paths-filter` step or a changed-files check, so the
   jobs skip but the gate still reports. This is the shape to prefer.
2. **Separate workflows**, each of which must then run on every pull request with no
   workflow-level `paths:` filter, for the same reason. Only one may own the
   `all-checks-passed` name, or the context becomes ambiguous.

The failure mode of getting this wrong is quiet and total: a pull request that touches only
`docs/` never triggers the workflow, the required context is never reported, and the pull
request sits pending forever with auto-merge armed and nothing to tell you why.

### What the split actually bought

Measured on the pull requests that adopted it, comparing the whole pull request check suite
before and after:

| Repository | Before | After | Longest job after |
| --- | --- | --- | --- |
| [CarModPicker](https://github.com/WebbPulse/CarModPicker/actions/runs/34571241652) | 10m21s ([run](https://github.com/WebbPulse/CarModPicker/actions/runs/34566322487)) | **3m59s** | `Tests (identity)` 3m19s |
| [WebbPulse-Portfolio](https://github.com/WebbPulse/WebbPulse-Portfolio/actions/runs/34570889902) | 7m37s ([run](https://github.com/WebbPulse/WebbPulse-Portfolio/actions/runs/34565617050)) | **3m18s** | `Tests (identity)` 2m43s |

Both "before" figures are the backend CI workflow alone, while "after" is the whole
consolidated `ci.yml` including frontend and, for CarModPicker, the Chrome extension. The
comparison is conservative for that reason: the new number covers strictly more work.

The shape of the win matters more than the number. Wall clock now tracks the *largest* domain
rather than the sum of all of them, so a tenth domain costs nothing as long as it is not the
slowest one. CarModPicker's ten test jobs spend about 26 minutes of runner time between them
and finish in under four.

Total compute goes up, not down. This trades runner minutes for wall clock, which is the right
trade for a check a person is waiting on and the wrong one for a nightly batch.

**Verify the split did not lose tests.** The count before and after must match exactly:
CarModPicker's was 2055 passed and 10 skipped in both. A domain path that matches nothing is
not an error - the job passes, having run zero tests - so a typo in `pyproject.toml` shows up
as a suspiciously fast job and a falling total rather than as a failure.

### Adding a domain does not touch the ruleset

The required context is `all-checks-passed`, not the matrix job names. Those carry a domain
and change whenever one is added or removed; a required context naming a job that no longer
exists blocks every pull request until someone edits the ruleset. The gate is what makes
adding a domain a one-line change to `pyproject.toml`.

---

## Releasing and what callers pin to

Callers must pin to a **tag or a commit SHA of this repository**, never to `@main`.
A reusable workflow referenced by a branch changes underneath every caller the moment
this repository is pushed to, and in this estate every push to `main` reaches
production through the callers.

The release approach is a moving major tag:

- Every change lands on `main` behind a pull request.
- A release is cut as an immutable `vMAJOR.MINOR.PATCH` tag, for example `v3.4.0`.
- The `v3` major tag is then **moved** to that commit. Callers pin `@v3` and pick up
  backward compatible fixes without editing anything.
- A breaking change to any input, secret or output means a new major tag (`v4`), and
  `v3` stops moving. Callers migrate deliberately.

```bash
git tag -a v3.4.0 -m "Describe the change"
git push origin v3.4.0
git tag -f v3          # move the major tag
git push -f origin v3
```

A caller that wants no moving target at all pins the SHA instead, with the tag in a
comment, exactly as this repository pins third party actions:

```yaml
uses: WebbPulse/.github/.github/workflows/python-ci.yml@<40 char sha> # v3.0.0
```

Both forms are fine. `v3` is the moving major for every workflow in this repository and
for the composite action, so `@v3` is what a caller pins. `v2` and `v1` are frozen and no
longer move. Pin a SHA where a repository needs a change to this repository to be an
explicit, reviewed event.

### v2 to v3 (Python workflows)

`v3` moves `python-ci.yml` and `codeartifact-publish-python.yml` to **uv**. What a caller
must change:

- Commit a `uv.lock` and give `pyproject.toml` a `[dependency-groups] dev` list, a
  `[[tool.uv.index]]` named `codeartifact` with `explicit = true`, and a `[tool.uv.sources]`
  binding for the private package. Requirements files are no longer read by anything.
- Drop the `cache-dependency-path` and `codeartifact-repository` inputs from the `python-ci`
  call. Both were removed. Caching keys off `<working-directory>/uv.lock` automatically, and
  the repository is part of the index URL in `pyproject.toml` rather than a workflow input.
- Replace `install-command` with a uv command. The default is `uv sync --locked`.
- Replace any `pip-audit -r requirements.txt` in `security-commands` with the `uv export`
  pipeline shown above.
- Delete `[tool.webbpulse.ci.domains]` and move each domain's tests under
  `tests/domains/<domain>/`. The table is now a hard error, not a warning. Set `entrypoints`
  to have discovery enforce that every domain directory has a deployable module.

`codeartifact-publish-python.yml` keeps every input, secret and output, so that call needs
only `@v2` changed to `@v3`.

`v2` stops moving for the Python workflows and remains available. The TypeScript, container
and deploy workflows are untouched by `v3`.

### v1 to v2

`v2` split `python-ci.yml` from one `python-ci` job into `discover`, `lint`, `typecheck`,
`security`, a `Tests (<domain>)` matrix, `Tests (shared)` and `all-checks-passed`, and added
`all-checks-passed` to `typescript-ci.yml`. Every input `v1` accepted still means the same
thing, so most callers migrate by changing `@v1` to `@v2` and nothing else.

It is a major bump because the **job names changed**. A ruleset or branch protection naming
`python-ci` as a required context, or a workflow whose `needs:` referenced that job, has to
move to `all-checks-passed`. `v1` stops moving and remains available for a caller that is not
ready.

Two things are worth doing at the same time as the bump, though neither is required:

- Declare `[tool.webbpulse.ci.domains]` in the caller's `pyproject.toml`. Without it the
  whole suite runs in `Tests (shared)`, exactly as it did under `v1`.
- Move a `typecheck` or `bandit`/`pip-audit` step out of a hand written job and into
  `typecheck-command` and `security-commands`, so they run in parallel with the tests rather
  than in series before them.

---

## Adopting in an existing repo

What a caller repository has to provide before these workflows will run.

**Repository content**

- A **ruff** configuration for `python-ci.yml`, in `pyproject.toml` (`[tool.ruff]`) or
  `ruff.toml`, and `ruff` in the `[dependency-groups] dev` list that `uv sync` installs. The workflow runs `ruff check` and `ruff format --check`, so a repository
  that has never run the formatter should run `ruff format` once and commit first.
- `lint`, `type-check` and `build` scripts in `package.json` for `typescript-ci.yml`,
  or the matching `*-command` inputs set to `""` to skip them.
- A `Dockerfile` that builds for a single architecture for `container-image.yml`.

**GitHub configuration**

- An Environment per stage (`staging`, `production`) holding the `vars` the snippets
  above read, and the deploy role ARN as an Environment secret.
- Nothing estate specific committed to this repository. Bucket names, distribution
  ids, function names, ECR repositories and regions live in caller `vars`.

**OIDC trust**

Each role trusts `token.actions.githubusercontent.com`, with `sub` scoped to the
calling repository and ideally to the environment, and audience `sts.amazonaws.com`.
Roles are assumed by `aws-actions/configure-aws-credentials`, which needs
`id-token: write` on the job. **Every job that calls one of these workflows must
grant `contents: read` and `id-token: write` on the calling job itself:**

```yaml
jobs:
  backend-ci:
    permissions:
      contents: read
      id-token: write
```

A called workflow can only hold permissions equal to or narrower than the grant on
the job that calls it. The reusable workflows do request `id-token: write` on their
own jobs, but that request cannot widen what the caller gave them: a caller job
running under a top level `permissions: contents: read` hands down a token with
`id-token: none`, and the run fails at startup before any step executes, with an
error naming the requested permission rather than the missing credential. This is
what broke the first CI run of `webbpulse-python`.

Setting the permissions at the top level of the caller does not work on its own
either. A job that declares its own `permissions:` block replaces the top level
grant rather than merging with it, so the block above belongs on each calling job.
`terraform-speculative-plan.yml` uses no OIDC and needs only `contents: read`.

**IAM permissions, per workflow**

| Workflow | Actions the role needs |
| --- | --- |
| `base-image-cache.yml` | `ecr:GetAuthorizationToken` (on `*`), plus `ecr:BatchGetImage` and `ecr:GetDownloadUrlForLayer` on the base image repository. Read only, no push. |
| `container-image.yml` | `ecr:GetAuthorizationToken` (on `*`), plus on the repository: `ecr:BatchCheckLayerAvailability`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`, `ecr:PutImage`, `ecr:BatchGetImage` (the manifest assertion) |
| `lambda-image-deploy.yml` | `lambda:UpdateFunctionCode`, `lambda:GetFunction` (the waiter polls it), and `lambda:PublishVersion` when `publish-version` is true |
| `spa-deploy.yml` | `s3:ListBucket` on the bucket; `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on `bucket/*` (`DeleteObject` is needed by the prune pass); `cloudfront:CreateInvalidation` and `cloudfront:GetInvalidation` on the distribution, only when `invalidate-cloudfront` is true |
| `codeartifact-publish-*.yml` | `sts:GetServiceBearerToken` (on `*`), `codeartifact:GetAuthorizationToken` on the domain, and on the repository `codeartifact:PublishPackageVersion`, `codeartifact:PutPackageMetadata`, `codeartifact:ReadFromRepository`, `codeartifact:DescribePackageVersion` |
| `python-ci.yml` / `typescript-ci.yml` | Only when the CodeArtifact login is enabled: `sts:GetServiceBearerToken`, `codeartifact:GetAuthorizationToken`, `codeartifact:ReadFromRepository`. Read only, no publish. |
| `terraform-speculative-plan.yml` | No AWS role. It needs only the HCP token secret. |

`sts:GetServiceBearerToken` is the one that is easy to miss. Without it the
CodeArtifact login fails with an access denied that names no CodeArtifact action.

---

## Pinning and updates

Actions are pinned to full commit SHAs resolved from the release tag with
`gh api repos/<owner>/<repo>/git/ref/tags/<tag>`, dereferencing annotated tags
through `gh api repos/<owner>/<repo>/git/tags/<sha>`. The trailing comment records
the human readable version. When bumping an action, re-resolve the SHA the same way
rather than trusting the comment.

Current pins:

| Action | Version | SHA |
| --- | --- | --- |
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-python` | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| `astral-sh/setup-uv` | v10.1.0 | `bec219d24cd3e171d82865faccec33120bb574f4` |
| `actions/setup-node` | v7.0.0 | `820762786026740c76f36085b0efc47a31fe5020` |
| `actions/upload-artifact` | v7.0.1 | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |
| `aws-actions/configure-aws-credentials` | v6.2.4 | `cbe3b392738ccf3f987d68400dafcf4b0624a56c` |
| `aws-actions/amazon-ecr-login` | v2.1.7 | `03f1aad4c6c7ffd436567f42f9384779290529bd` |
| `docker/setup-buildx-action` | v4.3.0 | `37fe631027851001ddb9b187196cc803df7f5f0e` |
| `docker/build-push-action` | v7.3.0 | `53b7df96c91f9c12dcc8a07bcb9ccacbed38856a` |
| `hashicorp/setup-terraform` | v4.0.1 | `dfe3c3f87815947d99a8997f908cb6525fc44e9e` |
