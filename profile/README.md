# WebbPulse

WebbPulse builds and runs software products. Everything is designed, built, deployed and supported end to end by [Tyler Webb](https://portfolio.webbpulse.com), a software engineer, on infrastructure WebbPulse runs itself.

## Products

| Product | What it is | Live |
| --- | --- | --- |
| [Standupless](https://github.com/WebbPulse/Standupless) | An issue tracker for small software teams. Teams, cycles, projects and a roadmap, with list and board views. A GitHub App links pull requests to issues and moves them as the work ships, and an API, webhooks, a CLI and an MCP server let scripts and coding agents work in it too. WebbPulse plans its own work in it. | [standupless.dev](https://standupless.dev) |
| [CarModPicker](https://github.com/WebbPulse/CarModPicker) | Plan, track and share a car build. Keep cars and build lists, attach parts to phased builds and log progress in forum-style threads. A companion Chrome extension captures part details from retailer pages. | [carmodpicker.com](https://www.carmodpicker.com) |

## Platform

| Repository | What it is |
| --- | --- |
| [WebbPulse-Terraform](https://github.com/WebbPulse/WebbPulse-Terraform) | A serverless Terraform control plane: workspaces, variables, plan and apply runs, remote state and a private module registry. Every WebbPulse workspace runs on it at [terraform.webbpulse.com](https://terraform.webbpulse.com). |
| [terraform-provider-webbpulse](https://github.com/WebbPulse/terraform-provider-webbpulse) | Terraform provider for the control plane, so workspaces and their variables are managed as code. |
| [terraform-aws-platform-modules](https://github.com/WebbPulse/terraform-aws-platform-modules) | Shared Terraform modules for every application estate: HTTP APIs, Lambda domains, the SPA frontend, identity, secrets, alarms and more. |
| [webbpulse-python](https://github.com/WebbPulse/webbpulse-python) | Shared Python package for the FastAPI services: config, logging, tracing, DynamoDB repositories, rate limiting, Lambda entrypoints, and the `wp-tf` CLI for the control plane. |
| [webbpulse-typescript](https://github.com/WebbPulse/webbpulse-typescript) | Shared TypeScript packages under the `@webbpulse` scope: the API client, auth, config, and the shared ESLint and TypeScript configs the frontends build on. |
| [WebbPulse-Artifacts](https://github.com/WebbPulse/WebbPulse-Artifacts) | The CodeArtifact repositories the shared packages publish to, and the base container images. |
| [WebbPulse-Portfolio](https://github.com/WebbPulse/WebbPulse-Portfolio) | Tyler's [portfolio and blog](https://portfolio.webbpulse.com), plus the [webbpulse.com](https://webbpulse.com) company site. |

The AWS Organization, Terraform workspaces, GitHub repositories and DNS are managed as code in private repositories.

## How things are built

- **Backend:** Python 3.13 and FastAPI, one Lambda container image per domain behind an HTTP API, DynamoDB for storage
- **Frontend:** React, TypeScript, Vite and Tailwind CSS, served from S3 behind CloudFront
- **Infrastructure:** Terraform on the WebbPulse control plane, staging and production in separate AWS accounts, OIDC into AWS with no long-lived keys
- **Delivery:** every change goes through a pull request into `staging`, end-to-end tests run against the staging deploy, and a promotion to `main` ships it to production

## Licensing

The public repositories are source available under the [PolyForm Strict License 1.0.0](https://polyformproject.org/licenses/strict/1.0.0). They are not open source and do not accept outside contributions.

## Contact

- Website: [webbpulse.com](https://webbpulse.com)
- Portfolio: [portfolio.webbpulse.com](https://portfolio.webbpulse.com)
- LinkedIn: [tylert2610](https://www.linkedin.com/in/tylert2610/)
- Email: tyler@webbpulse.com
