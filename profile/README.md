# WebbPulse

Personal projects of Tyler Webb, a software engineer with a background in network engineering and full-stack web. Everything here is built the same way: FastAPI on the backend, React and TypeScript on the frontend, DynamoDB for storage, deployed to AWS Lambda with Terraform.

## Projects

| Project | What it is | Live |
| --- | --- | --- |
| [CarModPicker](https://github.com/WebbPulse/CarModPicker) | Track car modifications: manage cars, build phased part lists, log progress in forum-style threads. A companion Chrome extension captures part data from retailer pages. | [carmodpicker.com](https://www.carmodpicker.com) |
| [WebbPulse-Portfolio](https://github.com/WebbPulse/WebbPulse-Portfolio) | Portfolio and blog. Every section is driven from the API through an admin panel rather than hardcoded. | [webbpulse.com](https://webbpulse.com) |

Both are MIT licensed.

## How things are built

- **Backend:** Python 3.13, FastAPI, DynamoDB, AWS Lambda behind an HTTP API
- **Frontend:** React, TypeScript, Vite, Tailwind CSS
- **Infrastructure:** Terraform on HCP Terraform, one workspace per environment, OIDC into AWS with no long-lived keys
- **Platform:** the AWS Organization, HCP Terraform workspaces, GitHub repositories, and DNS are all managed as code in private repositories

## Contact

- Website: [webbpulse.com](https://webbpulse.com)
- LinkedIn: [tylert2610](https://www.linkedin.com/in/tylert2610/)
- Email: tyler@webbpulse.com
