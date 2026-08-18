# Contributing

Contributions are welcome when they preserve the project's safety boundaries,
measurement transparency, and narrow data collection.

## Before opening a change

1. Do not include credentials, host identifiers, GPU UUIDs, live databases,
   command lines, process IDs, or unbounded metric labels.
2. Do not generalize fan curves, device names, or benchmark results from one
   host. Explain the tested hardware and operating conditions.
3. Declare generated code, AI assistance, copied material, and third-party
   sources. Contributors remain responsible for accuracy, licensing, and review.
4. Preserve loopback-only listeners, the protected-device exclusion, and the
   native controller's independent fail-safe behavior unless a change explicitly
   documents and validates a safer replacement.
5. Add tests for parser, restart, stale-data, or configuration behavior affected
   by the change.

Run the repository checks before submitting:

```bash
scripts/validate.sh
```

Performance changes should also report `scripts/observer-check.sh 300`, the
number of repetitions, aggregation method, and any failed or excluded run.
Negative and null results belong in the report.

## Provenance and sign-off

Commits should be focused and use a clear imperative subject. Sign off each
commit with `git commit -s` to certify the Developer Certificate of Origin 1.1:
<https://developercertificate.org/>. The sign-off attests that you have the
right to submit the work; it does not replace attribution or license notices.

By contributing, you agree that your contribution is licensed under the MIT
License in this repository.
