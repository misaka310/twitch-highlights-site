# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected security vulnerability.
Use GitHub's private vulnerability reporting for this repository, or contact
the repository owner privately through the GitHub profile. Include the
affected file or endpoint, reproduction steps, impact, and any safe mitigation
you have identified.

Please do not include credentials, private keys, personal data, or live system
paths in a report. Redact those values and describe the shape of the data
instead.

## Scope and response

This repository publishes a static video-highlights site. Reports involving
the generated public data, third-party platform availability, or a deployment
provider should explain how they create a security impact in this repository.
We will acknowledge actionable reports and coordinate a fix or disclosure
timeline with the reporter.

## Secret handling

Runtime credentials, SSH keys, machine-specific paths, private IP addresses,
and deployment secrets must remain outside the repository. Use local
environment variables or the deployment provider's secret store. Public
documentation must use placeholders and sanitized examples.
