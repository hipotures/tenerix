# Agent Instructions

## Version Control and Persistence

- Git commit and push are normal, expected parts of completing work in this repository.
- Save reports, audit findings, scripts, documentation, and other deliverables as repository files.
- Commit completed changes and push them to the current working branch without requesting separate permission for these routine steps, unless the user explicitly instructs otherwise.
- Do not leave important results only in temporary directories or uncommitted local state, where they might be lost after a restart.
- A task requiring read-only access to a production device still permits writing reports and other artifacts to the local development repository, followed by commit and push.
- Explicit user instructions for a particular task take precedence over these defaults.

## Sensitive Data

- Never commit sensitive data, including disk or partition contents, filesystem dumps, device images, or archives containing such data, even when compressed or encoded.
- Never commit passwords (including temporary, disposable, test, or default passwords), password hashes, tokens, credentials, encryption keys, or private keys.
- Never commit key names, filenames, paths, aliases, or labels that identify actual authentication or encryption keys. Use generic placeholders in examples and documentation.
- Apply these rules to source code, configuration, documentation, reports, logs, test fixtures, and generated artifacts. Review content before staging; ignored files must not be force-added if they contain prohibited data.
- Device serial numbers and hardware information, including device MAC addresses, are allowed in the repository.
