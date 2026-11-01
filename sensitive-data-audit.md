# Sensitive data audit

Date: 2026-11-01. Reviewed revision: `24e04d2` on `main`.

## Result

The repository contains production device identifiers, private network details,
and private share names in committed files. No private keys, common provider
tokens, password hashes, or literal credential assignments were detected in the
165 historical Git blobs examined. This is a bounded audit, not proof that every
possible secret format is absent.

The local ignored artifact directories contain authentication material and device
images. They must not be treated as safe publication artifacts merely because
Git ignores them. No secret values are reproduced in this report.

## Confirmed findings

| ID | Priority | Location | Evidence and impact |
|---|---|---|---|
| S1 | Medium | `readynas-rn426-audit.md:222` | The disk mapping table contains six actual disk serial numbers, linked to disk models and bays. These uniquely identify the user's hardware. Present since commit `185a192`. |
| S2 | Medium | `readynas-rn426-audit.md:270`, `:280`, `:307` | Production RAID, Btrfs, and LUKS mapping identifiers are recorded, together with filesystem labels. These allow correlation with other device evidence. A LUKS identifier is not an encryption key. |
| S3 | Medium | `readynas-rn426-audit.md:285` and `:287` | Actual private share names and subvolume structure are disclosed. No share file contents were found in tracked files during this review. |
| S4 | Low | `boot/rn426/README.md:153`, `boot/rn426/acquire-dom.py:14`, `boot/rn426/dom-system/README.md:33`, `:42`, `readynas-rn426-debian13-audit.md:229` | Production MAC, private LAN address/subnet, root SSH target, and interface assumptions are recorded. The production MAC also appears in QEMU test source files. This exposes deployment metadata, not an authentication credential. Boot files have been present since commit `0797ffc`. |
| S5 | High, local only | `artifacts/dom-system/root-password`; generated rootfs `etc/shadow` files | A plaintext root-password file exists with mode `0600`; password hashes were detected in three generated rootfs shadow files (mode `0640`). The build code reads or generates the password and installs its hash. Git ignores these paths; no corresponding hash was found in historical blobs. |
| S6 | Medium, local only | `artifacts/dom/test-admin` | A private SSH key is present with mode `0600`, alongside its public key and test known-hosts file. Code/documentation identify it as a disposable test key. No evidence of production authorization was established. It is ignored and absent from the scanned Git history. |
| S7 | Potentially high, local only | `artifacts/nas/readynas-os-md0.img.zst`; original DOM image under `artifacts/dom/`; generated images and rootfs archives | Original device snapshots can contain credentials, configuration, and personal metadata. Generated images can embed shadow files and authorized public keys. Their existence was confirmed, but image/archive contents were not mounted, decompressed, or exhaustively inspected. Treat originals as confidential until separately reviewed. |

Priorities describe disclosure impact, not proof that an external party accessed
the material. Remote repository visibility and external access were not checked.

## Items distinguished from secrets

- QEMU fixture MAC addresses, project UUID namespaces, and freshly generated
  fixture filesystem/array identifiers are test data. They should not be confused
  with the production identifiers above.
- Upstream Linux patches/source and tool output include public contributor
  names/email addresses. These are attribution and provenance, not discovered
  user credentials. Git author/committer metadata contains three distinct identity
  strings; names and addresses are intentionally not repeated here.
- SSH public keys and authorized-keys files are not private keys. Local production
  authorized-keys files still reveal deployment trust relationships.
- Credential-assignment matches in local Alpine utilities and Python library
  documentation were code expressions or upstream examples.
- Package checksums, container digests, and source commit hashes are integrity
  metadata, not authentication material.

## Scope and method

- Started from a clean tracked working tree: 140 tracked paths, 25 commits, and a
  non-shallow checkout. Reviewed all locally available refs and reflogs through
  `git rev-list --objects --all --reflog`, scanning 165 unique blob versions.
- Scanned historical content for PEM/OpenSSH private-key headers, common AWS,
  GitHub, OpenAI and Slack token forms, Unix password hashes, credentials in URLs,
  quoted credential assignments, SSH public keys, private IPv4 addresses, MACs,
  UUIDs, and email addresses. Manually reviewed documentation, evidence logs,
  authentication-related build paths, and identifier matches.
- Scanned commit metadata and local Git configuration for the credential patterns;
  none matched. Reviewed tracked artifact names; no tracked disk images, database
  files, environment files, or private-key files were listed by the corresponding
  filename queries.
- Inventoried 18,348 local file entries, including ignored build output. The
  bounded local content pass read 2,593 text files of at most 2,000,000 bytes;
  skipped 13,999 binary files, 115 larger files, and 1,636 symlinks. Five files
  could not be read. Two NFS state directories under
  `artifacts/dom/build/rootfs/var/lib/nfs/` could not be traversed. These counts
  describe the workspace before this report was created.
- Examined names and permissions of local authentication artifacts without
  printing their values. The plaintext password was identified through its file
  and the consuming build code; it was not printed or tested against a service.

## Recommended follow-up

1. Before wider distribution, redact the production serials, identifiers, and
   private share names from published audit documents. Replace the deployment
   address/MAC in shared examples with explicit placeholders; provide real values
   through ignored local inputs where execution requires them.
2. Keep original device snapshots, plaintext passwords, private keys, rootfs
   trees, and generated images in access-controlled local storage. Do not upload
   or force-add ignored artifacts. Existing `0600` permissions on the password
   and test key are appropriate; directory and image access need to be considered
   together with file permissions.
3. If any local password, private key, or credential-bearing image has previously
   been shared, replace the affected authentication material. This review found
   no evidence establishing such sharing.
4. Removing current text does not remove older Git versions. If historical
   identifier removal is required, plan it separately with repository owners;
   no history rewrite or force-push was performed during this audit.

## Limits and changes

No remote device was contacted, credentials tested, SQLite database copied,
database migrated, or device image mounted. Remote-only branches, hosting-side
pull requests, releases, CI logs, caches, Git LFS payloads, other clones, backups,
and unreachable objects outside refs/reflogs are outside this audit. Encoded,
encrypted, unusual-format secrets and free-form personal data can evade regex
checks. No dedicated third-party secret scanner was installed or available.

Only this report was added. Findings were not automatically redacted, deleted,
or rotated; application behavior and original evidence remain unchanged.
