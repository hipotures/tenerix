# Repository completeness review

Date: 2026-11-01. Reviewed revision: `fdaa554`.

No untracked, non-ignored files were present. No omitted project source files
were identified in the inspected ignored artifact directories. The cached panel
dependency had a clean working tree; its fetch script and pinned provenance are
already tracked. This review did not execute a clean build.

## Useful additions

The following ignored outputs are candidates for reviewed, sanitized copies in
an evidence directory, rather than adding entire artifact directories to Git:

- `artifacts/dom/logs/summary.json` and relevant per-test JSON results: preserve
  evidence of the boot/update/rollback/failure test runs alongside their scripts.
- `artifacts/dom-system/qemu-test.json` and `qemu-test-pendrive.json`: preserve the
  DOM and pendrive test summaries.
- `artifacts/dom-system/build.json`, `build-pendrive.json`, and
  `artifacts/md-system/build.json`: preserve selected build IDs, dependency and
  output checksums, and sizes needed to associate test results with builds.

The JSON structures were inspected at the key level, not approved for publishing
verbatim. Review all values before copying; omit deployment identifiers and local
paths where unnecessary. Raw console logs require a separate credential review.
The existing hardware and Alpine serial evidence directories provide precedent
for retaining selected evidence, without tracking generated binaries.

`boot/rn426/md-system/` has build and test scripts but no README. A dedicated
reproduction guide would be useful: its build consumes
`artifacts/dom-system/build/rootfs`, `artifacts/dom/build/rootfs/lib/modules`, and
`artifacts/alpine-hardware/repro-one`. Documenting the producer commands and order
would reduce reliance on the current workspace. This is a documentation gap, not
evidence that a particular source file was lost.

## Files correctly kept outside Git

Original device images, generated rootfs trees, image/archive outputs, passwords,
private test keys, deployment authorized keys, downloaded packages, Python caches,
and fetched upstream checkouts should remain outside Git. The local
`artifacts/dom/partitions-core.c` is a Linux source reference; no tracked code
reference to that path was found, so its presence alone does not establish a
missing project source dependency. Fixture configuration and test-key generation
already have tracked producer code.

Only this review was added. Candidate evidence was not automatically published.
