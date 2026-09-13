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
| `Tests (<domain>)` | one per discovered domain | `fail-fast: false`, so a two-domain break needs one run, not two. |
| `Tests (shared)` | always | Everything outside the domain directories. Whole suite when there are none. |
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
| `entrypoints` | `""` | When set, every domain directory must have a matching module. |

Paths are relative to `working-directory`. With `entrypoints` set, a domain directory
`tests/domains/identity` requires `app/entrypoints/identity.py`; a hyphen in a directory name
maps to an underscore in the module name. Discovery **fails** naming the directories with no
module and listing the modules that do exist, so a test directory can never drift away from
the deployable it covers.

A repository with no `domains-root` directory gets no domain jobs and a `shared` job carrying
everything, so the workflow can be called unconditionally.

A `[tool.webbpulse.ci.domains]` table is a **hard error** in v3. Discovery stops and points at
the directory convention.

### Adding a domain

1. Create `tests/domains/<name>/` with the domain's tests, and `app/entrypoints/<name>.py`
   if `entrypoints` is set.
2. Open the pull request. `Discover domains` picks it up and a `Tests (<name>)` job appears.

No workflow edit and **no ruleset edit**: the required context is `all-checks-passed`, which
does not change when the matrix does.

Add `pytest-xdist` to the project's dev dependency group. The `pytest-workers` input defaults
to `auto`, and without the plugin the workflow drops `-n` and logs a warning rather than
running the domains in parallel.

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

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | no | Needed only for the CodeArtifact login. |
| `codeartifact-domain-owner` | no | Account id owning the domain. |

Outputs: none.

```yaml
jobs:
  frontend-ci:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/typescript-ci.yml@v2
    with:
      working-directory: frontend
      node-version: "22"
      run-playwright: true
```

---

## `container-image.yml`

Builds one domain image with buildx for a single platform, logs in to ECR through
OIDC, pushes the immutable tag `sha-<full git sha>`, and returns the digest and the
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
`IMMUTABLE` tags and the only tag is `sha-<full git sha>`, so re-running a green
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
| `image-tag` | `sha-<full git sha>` |
| `image-existed` | `true` when the tag already resolved and the build was skipped. |

Single image, no CodeArtifact, no cross account base:

```yaml
jobs:
  image:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/container-image.yml@v2
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
    uses: WebbPulse/.github/.github/workflows/container-image.yml@v2
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

## `lambda-image-deploy.yml`

Points one or many functions at an image URI: waits for the function to settle,
runs `update-function-code --image-uri`, waits again with `function-updated-v2`
(container image functions stay `Pending` while Lambda optimizes the image), then
optionally probes a smoke URL with retries.

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
    uses: WebbPulse/.github/.github/workflows/lambda-image-deploy.yml@v2
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
optional CodeArtifact npm login runs before the install, and an optional HCP Terraform
wait runs before the sync.

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

**Waiting for HCP Terraform.** A Terraform apply that touches the same bucket or
distribution can land in the middle of the sync. Set `tfc-organization` and
`tfc-workspace` and pass the `tfc-api-token` secret, and the deploy polls the
workspace's most recent run and holds until it reaches a settled status (`applied`,
`planned_and_finished`, `discarded`, `errored`, `canceled`, `force_canceled`) or the
workspace has no runs at all. Both the workspace input and the token gate the step, so
a repository that sets neither, or sets the workspace before the token is in place,
deploys exactly as it did before. `tfc-wait-attempts` and `tfc-wait-interval-seconds`
tune the poll; the defaults give ten minutes.

A run parked awaiting confirmation is not a wait. No WebbPulse workspace auto-applies,
so a VCS triggered plan-and-apply run stops in `planned` and stays there until somebody
confirms it. Polling such a run can only ever time out, so the step reads the run's
`has-changes` and `actions.is-confirmable` instead:

- **Awaiting confirmation, no resource changes.** Nothing can move under the deploy, so
  the step reports the run in the job summary and proceeds immediately.
- **Awaiting confirmation with resource changes.** The deploy would race an apply that
  is about to happen, so the step fails straight away with the run URL in the log and
  the job summary. Apply or discard the run, then rerun. This is the same outcome the
  ten minute timeout produced, reached in seconds instead.
- **Still planning or applying.** Unchanged: the step polls until the run settles.

A workspace whose API response carries no `actions` object falls back to polling, so the
behaviour degrades to the old one rather than guessing.

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
| `invalidation-paths` | string | `""` | Space separated **extra** paths. `/index.html` and `/` are always invalidated. |
| `immutable-asset-globs` | string | `assets/*` | Files treated as content hashed. |
| `aws-region` | string | required | |
| `environment` | string | `""` | GitHub Environment. |
| `concurrency-group` | string | `""` | Defaults to workflow plus ref. |
| `runs-on` | string | `ubuntu-latest` | |
| `codeartifact-domain` | string | `""` | Non empty enables the npm login before the install. |
| `codeartifact-repository` | string | `""` | Required with `codeartifact-domain`, validated at run time. |
| `tfc-organization` | string | `""` | Required with `tfc-workspace`, validated at run time. |
| `tfc-workspace` | string | `""` | Empty skips the wait. |
| `tfc-wait-attempts` | number | `40` | Polls before the job gives up. |
| `tfc-wait-interval-seconds` | number | `15` | Seconds between polls. |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | yes | Writes the bucket and invalidates the distribution. |
| `codeartifact-domain-owner` | no | Account id owning the domain. Required with `codeartifact-domain`. |
| `tfc-api-token` | no | HCP Terraform API token. Unset skips the wait. |

Outputs: none.

```yaml
jobs:
  deploy-frontend:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/spa-deploy.yml@v2
    with:
      environment: production
      s3-bucket: ${{ vars.FRONTEND_S3_BUCKET }}
      cloudfront-distribution-id: ${{ vars.CLOUDFRONT_DISTRIBUTION_ID }}
      aws-region: ${{ vars.AWS_REGION }}
      tfc-organization: ${{ vars.TFC_ORGANIZATION }}
      tfc-workspace: ${{ vars.TFC_WORKSPACE }}
      codeartifact-domain: ${{ vars.CODEARTIFACT_DOMAIN }}
      codeartifact-repository: ${{ vars.CODEARTIFACT_REPOSITORY }}
      build-env-json: >-
        {"VITE_API_BASE_URL": "${{ vars.API_BASE_URL }}"}
    secrets:
      role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
      codeartifact-domain-owner: ${{ secrets.CODEARTIFACT_DOMAIN_OWNER }}
      tfc-api-token: ${{ secrets.TFC_API_TOKEN }}
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
| `environment` | string | required | `staging` or `production`. Also the GitHub Environment. |
| `sha` | string | `""` | Commit the check run lands on. Empty means `github.sha`. |
| `api-base-url` | string | required | |
| `web-base-url` | string | required | |
| `aws-region` | string | required | |
| `api-id` | string | required | API Gateway v2 api id, normally a terraform output. |
| `access-log-group` | string | required | Gateway access log group. |
| `gate-ssm-parameter` | string | `""` | Staging gate parameter name. Empty skips the gate. |
| `gate-signing-key-ssm-parameter` | string | `""` | Gate signing key parameter. Empty means no web gate. |
| `gate-key-pair-id` | string | `""` | CloudFront public key id for the minted cookies. |
| `gate-cookie-domain` | string | `""` | Domain the minted cookies are scoped to. |
| `user-email` | string | required | Durable e2e user, from the environment's `vars`. |
| `working-directory` | string | `.` | Python project root with `pyproject.toml` and `uv.lock`. |
| `e2e-directory` | string | `e2e` | Directory pytest collects, relative to `working-directory`. |
| `install-command` | string | `uv sync --locked --only-group e2e` | |
| `python-version` | string | `3.13` | |
| `pytest-args` | string | `""` | |
| `browser` | string | `chromium` | Playwright browser the suite drives. |
| `headless` | boolean | `true` | Run the browser headless. |
| `check-name` | string | `""` | Empty derives `e2e (<environment>)`. |
| `legacy-route-names` | string | `""` | Comma separated, must not appear in the bundle. |
| `mint-enabled` | boolean | `false` | Staging only. `mint_test_token` refuses production itself. |
| `kms-key-id` | string | `""` | |
| `issuer` | string | `""` | |
| `audience` | string | `""` | |
| `codeartifact-domain` | string | `""` | Empty skips the CodeArtifact auth step. |
| `codeartifact-index` | string | `codeartifact` | |
| `runs-on` | string | `ubuntu-latest` | |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | yes | Reads the gateway, the access log group and the gate parameter. |
| `e2e-user-password` | yes | Durable e2e user's password. Masked by GitHub. |
| `codeartifact-domain-owner` | no | Required when `codeartifact-domain` is set. |

Outputs: none. The result is the check run and the job conclusion.

The caller adds an `e2e` job to its deploy workflow, needing the deploy job:

```yaml
jobs:
  e2e:
    needs: [resolve-env, deploy]
    permissions:
      contents: read
      id-token: write
      checks: write
    uses: WebbPulse/.github/.github/workflows/e2e.yml@v3
    with:
      environment: ${{ needs.resolve-env.outputs.environment }}
      api-base-url: ${{ vars.API_BASE_URL }}
      web-base-url: ${{ vars.WEB_BASE_URL }}
      aws-region: ${{ vars.AWS_REGION }}
      api-id: ${{ vars.API_ID }}
      access-log-group: ${{ vars.API_ACCESS_LOG_GROUP }}
      gate-ssm-parameter: ${{ vars.GATE_SSM_PARAMETER }}
      gate-signing-key-ssm-parameter: ${{ vars.GATE_SIGNING_KEY_SSM_PARAMETER }}
      gate-key-pair-id: ${{ vars.GATE_KEY_PAIR_ID }}
      gate-cookie-domain: ${{ vars.GATE_COOKIE_DOMAIN }}
      user-email: ${{ vars.E2E_USER_EMAIL }}
      working-directory: backend
      legacy-route-names: ${{ vars.LEGACY_ROUTE_NAMES }}
      mint-enabled: ${{ vars.E2E_MINT_ENABLED == 'true' }}
      kms-key-id: ${{ vars.IDENTITY_KMS_KEY_ID }}
      issuer: ${{ vars.IDENTITY_ISSUER }}
      audience: ${{ vars.IDENTITY_AUDIENCE }}
      codeartifact-domain: webbpulse
    secrets:
      role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
      e2e-user-password: ${{ secrets.E2E_USER_PASSWORD }}
      codeartifact-domain-owner: ${{ secrets.CODEARTIFACT_DOMAIN_OWNER }}
```

`checks: write` must be granted on the calling job, not only inside this workflow, because a
reusable workflow can never hold a permission its caller did not.

**Branch protection.** Add `e2e (staging)`, or whatever `check-name` resolves to on staging,
to the required status checks on `main` in the product's ruleset. The staging deploy publishes
that check on the commit it deployed, and the release pull request from `staging` to `main`
carries the same commit, so a red staging run blocks promotion. Production runs publish
`e2e (production)`, which is left off the required list: it reports after the fact, since
there is nothing left to gate by then.

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
    uses: WebbPulse/.github/.github/workflows/codeartifact-publish-npm.yml@v2
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

## `actions/tfc-wait`

A composite action holding the same HCP Terraform wait `spa-deploy.yml` runs inline, for
a repository whose deploy is a plain job rather than a call into a reusable workflow.
`CarModPicker`'s `backend-deploy.yml` and `frontend-deploy.yml` both use it.

```yaml
      - name: Wait for HCP Terraform
        uses: WebbPulse/.github/actions/tfc-wait@v2
        with:
          workspace-id: ${{ vars.TFC_WORKSPACE_ID }}
          api-token: ${{ secrets.TFC_API_TOKEN }}
```

| Input | Default | Notes |
| --- | --- | --- |
| `workspace-id` | `""` | `ws-XXXXXXXXXXXXXXXX`. Takes precedence over `organization` plus `workspace`. |
| `organization` | `""` | Required when `workspace-id` is empty. |
| `workspace` | `""` | Required when `workspace-id` is empty. |
| `api-token` | required | HCP Terraform API token with read access to the workspace runs. |
| `attempts` | `40` | Polls before the step gives up. |
| `interval-seconds` | `15` | Seconds between polls. |

See [Waiting for HCP Terraform](#spa-deployyml) for what the step does with a run parked
awaiting confirmation.

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
    uses: WebbPulse/.github/.github/workflows/terraform-speculative-plan.yml@v2
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
- A release is cut as an immutable `vMAJOR.MINOR.PATCH` tag, for example `v1.4.0`.
- The `v1` major tag is then **moved** to that commit. Callers pin `@v1` and pick up
  backward compatible fixes without editing anything.
- A breaking change to any input, secret or output means a new major tag (`v2`), and
  `v1` stops moving. Callers migrate deliberately.

```bash
git tag -a v1.4.0 -m "Describe the change"
git push origin v1.4.0
git tag -f v1          # move the major tag
git push -f origin v1
```

A caller that wants no moving target at all pins the SHA instead, with the tag in a
comment, exactly as this repository pins third party actions:

```yaml
uses: WebbPulse/.github/.github/workflows/python-ci.yml@<40 char sha> # v3.0.0
```

Both forms are fine. `@v3` is the current default for the Python workflows and `@v2` for the rest; pin a SHA where a repository needs a
change to this repository to be an explicit, reviewed event.

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
| `container-image.yml` | `ecr:GetAuthorizationToken` (on `*`), plus on the repository: `ecr:BatchCheckLayerAvailability`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`, `ecr:PutImage`, `ecr:BatchGetImage` (the manifest assertion) |
| `lambda-image-deploy.yml` | `lambda:UpdateFunctionCode`, `lambda:GetFunction` (the waiter polls it), and `lambda:PublishVersion` when `publish-version` is true |
| `spa-deploy.yml` | `s3:ListBucket` on the bucket; `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on `bucket/*` (`DeleteObject` is needed by the prune pass); `cloudfront:CreateInvalidation` and `cloudfront:GetInvalidation` on the distribution |
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
