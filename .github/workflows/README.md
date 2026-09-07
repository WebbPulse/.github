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

Checkout, Python setup with pip cache, install, `ruff check`, `ruff format --check`,
and pytest with a coverage summary written to the job summary. An optional
CodeArtifact pip login runs first when `codeartifact-domain` is non empty, so shared
private packages resolve during the install.

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `python-version` | string | `3.13` | Matches the estate's backends. |
| `working-directory` | string | `backend` | Directory holding the project. |
| `install-command` | string | `python -m pip install --upgrade pip && pip install -r requirements-dev.txt` | Swap for `uv sync` if a repo moves to uv. |
| `ruff-target` | string | `.` | Paths passed to ruff. |
| `pytest-args` | string | `""` | Extra pytest arguments. |
| `coverage-source` | string | `app` | Package measured by coverage. |
| `runs-on` | string | `ubuntu-latest` | Runner label. |
| `codeartifact-domain` | string | `""` | Non empty enables the CodeArtifact login. |
| `codeartifact-repository` | string | `""` | Required with `codeartifact-domain`, and validated at run time. |
| `aws-region` | string | `""` | Required with `codeartifact-domain`, and validated at run time. |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | no | Needed only for the CodeArtifact login. |
| `codeartifact-domain-owner` | no | Account id owning the domain. |

Outputs: none.

```yaml
jobs:
  backend-ci:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/python-ci.yml@v1
    with:
      working-directory: backend
      coverage-source: app
```

---

## `typescript-ci.yml`

Node setup with the package manager cache, install, lint, format check, typecheck,
unit tests, and build. An optional CodeArtifact npm login runs before the install.
A second `playwright` job runs only when `run-playwright` is true, and uploads the
report as an artifact.

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
    uses: WebbPulse/.github/.github/workflows/typescript-ci.yml@v1
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
    uses: WebbPulse/.github/.github/workflows/container-image.yml@v1
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
`function-image-map`:

```yaml
jobs:
  build-images:
    strategy:
      fail-fast: false
      matrix:
        domain: [content, resume, identity, public]
    permissions:
      contents: read
      id-token: write
    environment: ${{ github.ref_name == 'main' && 'production' || 'staging' }}
    uses: WebbPulse/.github/.github/workflows/container-image.yml@v1
    with:
      ecr-repository: webbpulse-${{ github.ref_name == 'main' && 'production' || 'staging' }}/${{ matrix.domain }}
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
      role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}

  image-map:
    needs: build-images
    runs-on: ubuntu-latest
    permissions:
      contents: read
    outputs:
      function-image-map: ${{ steps.map.outputs.function-image-map }}
    steps:
      - uses: actions/download-artifact@v4
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
    uses: WebbPulse/.github/.github/workflows/lambda-image-deploy.yml@v1
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

Builds the frontend, syncs to S3 in two passes, and invalidates CloudFront.

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

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | yes | Writes the bucket and invalidates the distribution. |

Outputs: none.

```yaml
jobs:
  deploy-frontend:
    permissions:
      contents: read
      id-token: write
    uses: WebbPulse/.github/.github/workflows/spa-deploy.yml@v1
    with:
      environment: production
      s3-bucket: ${{ vars.FRONTEND_S3_BUCKET }}
      cloudfront-distribution-id: ${{ vars.CLOUDFRONT_DISTRIBUTION_ID }}
      aws-region: ${{ vars.AWS_REGION }}
      build-env-json: >-
        {"VITE_API_BASE_URL": "${{ vars.API_BASE_URL }}"}
    secrets:
      role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
```

---

## `codeartifact-publish-python.yml` and `codeartifact-publish-npm.yml`

Build a shared package and publish it to CodeArtifact through OIDC into a role in
the artifacts account. Both are idempotent: the version is looked up with
`describe-package-version` before publishing, and an already published version is
skipped with a `::notice::` rather than failing, so re-running a released tag stays
green.

The Python workflow builds with `python -m build`, reads the name and version off the
wheel filename, and uploads with `aws codeartifact login --tool twine` followed by
`twine upload --repository codeartifact`. The npm workflow reads name and version
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
`runs-on`. `codeartifact-publish-python.yml` adds `python-version`.

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
    uses: WebbPulse/.github/.github/workflows/codeartifact-publish-python.yml@v1
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
    uses: WebbPulse/.github/.github/workflows/codeartifact-publish-npm.yml@v1
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
    uses: WebbPulse/.github/.github/workflows/terraform-speculative-plan.yml@v1
    with:
      working-directory: terraform
    secrets:
      tf-api-token: ${{ secrets.TFC_API_TOKEN }}
```

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
uses: WebbPulse/.github/.github/workflows/python-ci.yml@<40 char sha> # v1.4.0
```

Both forms are fine. `@v1` is the default; pin a SHA where a repository needs a
change to this repository to be an explicit, reviewed event.

---

## Adopting in an existing repo

What a caller repository has to provide before these workflows will run.

**Repository content**

- A **ruff** configuration for `python-ci.yml`, in `pyproject.toml` (`[tool.ruff]`) or
  `ruff.toml`, and `ruff` present in the dev requirements the `install-command`
  installs. The workflow runs `ruff check` and `ruff format --check`, so a repository
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
| `actions/setup-node` | v7.0.0 | `820762786026740c76f36085b0efc47a31fe5020` |
| `actions/upload-artifact` | v7.0.1 | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |
| `aws-actions/configure-aws-credentials` | v6.2.4 | `cbe3b392738ccf3f987d68400dafcf4b0624a56c` |
| `aws-actions/amazon-ecr-login` | v2.1.7 | `03f1aad4c6c7ffd436567f42f9384779290529bd` |
| `docker/setup-buildx-action` | v4.3.0 | `37fe631027851001ddb9b187196cc803df7f5f0e` |
| `docker/build-push-action` | v7.3.0 | `53b7df96c91f9c12dcc8a07bcb9ccacbed38856a` |
| `hashicorp/setup-terraform` | v4.0.1 | `dfe3c3f87815947d99a8997f908cb6525fc44e9e` |
