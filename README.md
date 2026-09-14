# WebbPulse/.github

Organisation level GitHub configuration for WebbPulse: the reusable workflows every
repository calls, a composite action, and the public organisation profile.

This repository is public and holds nothing estate specific. No AWS account ids, role
ARNs, bucket names, registry hostnames, domain names, distribution ids or HCP workspace
names live here. Every one of those values arrives from the calling repository as an
`input` or a `secret`.

## What is here

- **`.github/workflows/`** contains the shared `workflow_call` workflows, plus `ci.yml`,
  which lints this repository's own workflow files with actionlint. Each reusable
  workflow is documented in
  [`.github/workflows/README.md`](.github/workflows/README.md).
- **`actions/`** contains composite actions. Today that is
  [`actions/tfc-wait`](actions/tfc-wait/action.yml), which holds until an HCP Terraform
  workspace can no longer change infrastructure under a deploy, for a repository whose
  deploy is a plain job rather than a call into a reusable workflow.
- **`profile/README.md`** is the organisation profile rendered on the WebbPulse GitHub
  organisation page.

## Reusable workflows

One line each, pointing at the section that documents the inputs, secrets and behaviour.

- [`python-ci.yml`](.github/workflows/README.md#python-ciyml) runs uv based lint, type
  check, security and a pytest matrix that fans out one job per domain.
- [`typescript-ci.yml`](.github/workflows/README.md#typescript-ciyml) runs Node install,
  lint, format check, typecheck, unit tests, build, and an optional Playwright job.
- [`container-image.yml`](.github/workflows/README.md#container-imageyml) builds one
  domain image with buildx, pushes it to ECR through OIDC, and returns the digest pinned
  image URI.
- [`lambda-image-deploy.yml`](.github/workflows/README.md#lambda-image-deployyml) points
  one or many Lambda functions at an image URI concurrently, waiting for each function
  to settle either side of the update.
- [`spa-deploy.yml`](.github/workflows/README.md#spa-deployyml) builds a frontend, syncs
  it to S3 in three ordered passes so the site is never briefly broken, and invalidates
  CloudFront.
- [`e2e.yml`](.github/workflows/README.md#e2eyml) verifies a deployed environment through
  the real edge and publishes a check run on the deployed commit.
- [`codeartifact-publish-python.yml`](.github/workflows/README.md#codeartifact-publish-pythonyml-and-codeartifact-publish-npmyml)
  builds a Python package with uv and publishes it to CodeArtifact, skipping a version
  that is already published.
- [`codeartifact-publish-npm.yml`](.github/workflows/README.md#codeartifact-publish-pythonyml-and-codeartifact-publish-npmyml)
  does the same for an npm package, reading the name and version from `package.json`.
- [`terraform-speculative-plan.yml`](.github/workflows/README.md#terraform-speculative-planyml)
  runs `terraform fmt -check`, `init` and `validate` on a pull request touching
  `terraform/**`, and nothing else.

## Pinning

Callers pin a tag or a commit SHA of this repository, never `@main`, because a reusable
workflow referenced by a branch changes underneath every caller the moment this
repository is pushed to. Releases are cut as immutable `vMAJOR.MINOR.PATCH` tags and the
major tag is then moved onto that commit, so a caller pinned to the moving `v3` picks up
backward compatible fixes without editing anything, and a breaking change to any input,
secret or output means a new major tag instead. A repository that wants this to be an
explicit, reviewed event pins the 40 character SHA with the tag in a trailing comment,
exactly as this repository pins every third party action.

Full detail is in
[Releasing and what callers pin to](.github/workflows/README.md#releasing-and-what-callers-pin-to)
and [Pinning and updates](.github/workflows/README.md#pinning-and-updates).
