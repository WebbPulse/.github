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
| `codeartifact-repository` | string | `""` | Required with `codeartifact-domain`. |
| `aws-region` | string | `""` | Required with `codeartifact-domain`. |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | no | Needed only for the CodeArtifact login. |
| `codeartifact-domain-owner` | no | Account id owning the domain. |

Outputs: none.

```yaml
jobs:
  backend-ci:
    uses: WebbPulse/.github/.github/workflows/python-ci.yml@main
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
    uses: WebbPulse/.github/.github/workflows/typescript-ci.yml@main
    with:
      working-directory: frontend
      node-version: "22"
      run-playwright: true
```

---

## `container-image.yml`

Builds one domain image with buildx for a single platform, logs in to ECR through
OIDC, pushes the immutable tag `sha-<full git sha>`, and returns the digest and the
digest pinned image URI so a deploy job can pin the exact artifact.

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

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `ecr-repository` | string | required | Repository name only, no registry host. |
| `aws-region` | string | required | |
| `context` | string | `.` | Docker build context. |
| `dockerfile` | string | `Dockerfile` | |
| `platform` | string | `linux/arm64` | Exactly one platform. |
| `build-args` | string | `""` | Newline separated build arguments. |
| `runs-on` | string | `ubuntu-latest` | |

| Secret | Required | Notes |
| --- | --- | --- |
| `role-to-assume` | yes | Allowed to push to the ECR repository. |

| Output | Notes |
| --- | --- |
| `image-digest` | `sha256:...` |
| `image-uri` | `registry/repository@sha256:...` |
| `image-tag` | `sha-<full git sha>` |

```yaml
jobs:
  image:
    uses: WebbPulse/.github/.github/workflows/container-image.yml@main
    with:
      ecr-repository: ${{ vars.ECR_REPOSITORY }}
      aws-region: ${{ vars.AWS_REGION }}
      context: backend
      dockerfile: backend/Dockerfile
    secrets:
      role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
```

---

## `lambda-image-deploy.yml`

Points one or many functions at an image URI: waits for the function to settle,
runs `update-function-code --image-uri`, waits again with `function-updated-v2`
(container image functions stay `Pending` while Lambda optimizes the image), then
optionally probes a smoke URL with retries.

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
    uses: WebbPulse/.github/.github/workflows/lambda-image-deploy.yml@main
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

The two passes exist so a deploy is never briefly broken. Pass one uploads the
hashed `assets/*` files with `max-age=31536000, immutable` and no `--delete`, so the
assets the currently served `index.html` references stay in place. Pass two uploads
`index.html` and the other unhashed files with `no-cache` and runs `--delete`, which
prunes stale objects including old hashed assets. The invalidation then waits for
completion so the job does not report success before the edge is serving the build.

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `node-version` | string | `22` | |
| `working-directory` | string | `frontend` | |
| `package-manager` | string | `npm` | `npm` or `pnpm`. |
| `build-command` | string | `npm run build` | |
| `build-output-directory` | string | `dist` | Relative to `working-directory`. |
| `build-env-json` | string | `{}` | JSON object of build variables. |
| `s3-bucket` | string | required | |
| `s3-prefix` | string | `""` | Optional key prefix. |
| `cloudfront-distribution-id` | string | `""` | Empty skips the invalidation. |
| `invalidation-paths` | string | `/*` | Space separated. |
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
    uses: WebbPulse/.github/.github/workflows/spa-deploy.yml@main
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
`codeartifact-repository` (required), `aws-region` (required), `environment`,
`runs-on`, plus `python-version` or `node-version` / `package-manager` /
`build-command`.

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
    uses: WebbPulse/.github/.github/workflows/codeartifact-publish-python.yml@main
    with:
      codeartifact-domain: ${{ vars.CODEARTIFACT_DOMAIN }}
      codeartifact-repository: ${{ vars.CODEARTIFACT_REPOSITORY }}
      aws-region: ${{ vars.AWS_REGION }}
    secrets:
      role-to-assume: ${{ secrets.CODEARTIFACT_PUBLISH_ROLE_ARN }}
      codeartifact-domain-owner: ${{ secrets.CODEARTIFACT_DOMAIN_OWNER }}
```

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
    uses: WebbPulse/.github/.github/workflows/terraform-speculative-plan.yml@main
    with:
      working-directory: terraform
    secrets:
      tf-api-token: ${{ secrets.TFC_API_TOKEN }}
```

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
