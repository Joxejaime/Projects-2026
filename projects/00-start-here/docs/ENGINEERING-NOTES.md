# Engineering notes

Three problems from building this repository that were not obvious, where the fix needed an
explanation rather than a patch. They are written down because the reasoning is the interesting
part, and because a portfolio that only shows working code hides where the learning happened.

---

## 1. Deleting a file from a Docker image does not remove it

**Symptom.** The Trivy gate in project 01 failed its first real CI run on four fixable HIGH CVEs:
`urllib3`, `msgpack` and `setuptools`. None of them were dependencies. The app is stdlib-only —
its `requirements.txt` does not exist.

**First attempt.** They live inside `pip` and its bundled wheel in `python:3.13-slim`, so the
Dockerfile removed them:

```dockerfile
RUN python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* ...
```

The scan still reported all four.

**Why.** A Docker image is a stack of layers, and each layer only records a *diff*. Deleting a
file in a later layer writes a whiteout entry — the bytes stay in the layer below, which is why
`docker history` still shows the base image's size. Trivy reads layers, so it kept finding
packages that no longer existed in the running container. Both the scanner and the Dockerfile
were correct; the mental model was wrong.

**Fix.** Flatten the cleaned filesystem into one fresh layer:

```dockerfile
FROM python:3.13-slim AS prepare
RUN ... remove the installers ...

FROM scratch AS runtime
COPY --from=prepare / /
```

The final image now has one layer containing exactly what runs, so what the scanner sees and
what ships are the same thing. The gate stayed at `--exit-code 1` throughout — the fix was to
make the image honest, not to lower the bar.

**Worth knowing:** this is also why `rm` in a Dockerfile never shrinks an image unless it happens
in the same `RUN` as whatever created the files, and why secrets leaked into an early layer are
not removed by deleting them later.

---

## 2. A lint rule that is right in general and wrong here

**Symptom.** Bumping hadolint from 3.1.0 to 3.5.0 turned the `Dockerfile lint` job red:

```
DL3067 warning: Do not copy an entire filesystem from another stage
```

on the `COPY --from=prepare / /` that fixes problem 1. The job runs with
`failure-threshold: info`, so a warning fails the build.

**The tension.** DL3067 is a good rule. Copying a whole filesystem between stages usually means
the multi-stage split bought nothing: the build tools come along with everything else, and the
author has gained a longer Dockerfile for no smaller image. Here it is the entire point, and
there is no narrower `COPY` that achieves layer flattening — flattening is *by definition* moving
the whole filesystem.

**Options considered.**

| | |
|---|---|
| Raise `failure-threshold` to `warning` | Weakens the gate for *every* rule to silence one. Rejected. |
| Drop the flattening | Reintroduces problem 1. Rejected. |
| Declare the exception, narrowly | Chosen. |

**Fix.** A scoped `# hadolint ignore=DL3067` directly above the one line, with the reasoning in
comments beside it, leaving the threshold strict everywhere else. The directive has to sit
immediately above the instruction it applies to — intervening comments go above the directive,
not between it and the `COPY`.

**The general point:** a suppressed warning with a written reason is defensible; a suppressed
warning with no reason is technical debt that looks like a passing build. A reviewer should be
able to tell which one they are reading without asking.

---

## 3. Dependabot can quietly undo your hardening

**Symptom.** After pinning all 19 GitHub Actions to commit SHAs, two Dependabot pull requests
proposed changes that read as ordinary version bumps:

```diff
- uses: terraform-linters/setup-tflint@90f302c2…  # v4
+ uses: terraform-linters/setup-tflint@v6
```

The left side is a commit. The right side is a **tag**, which the publisher can repoint at any
time. Both actions run in jobs holding `contents: write` or `packages: write`.

**Why it happened.** Each branch was cut *before* the pins landed, so Dependabot was faithfully
editing the file as it existed then. Nothing malfunctioned. Separately, merging a `staging`
branch carrying four such PRs reverted three dependency pins to ranges and left `ruff` unbounded
again — so any future `ruff` release could turn CI red with no change to this repository.

**The real lesson.** Both were caught by reading diffs. That is not a control: it works until the
day someone is tired, and the whole point of pinning is to not depend on vigilance.

**Fix.** `scripts/check_supply_chain.py` fails CI if any `uses:` names anything but a
40-character SHA, or any requirements line lacks `==`. It ships with mutation tests — each one a
regression that was actually proposed here — so the guard's own failure path is proven on every
run, not assumed.

`pyproject.toml` is deliberately exempt. A package's *declared* dependencies belong as ranges;
the *reproducible install* is what gets pinned. Those two files are supposed to disagree.

**Worth knowing:** Dependabot handles SHA pins correctly once the base branch has them — it
updates the SHA and the trailing tag comment together. The problem was never the tool, it was
long-lived branches cut before a policy change.

---

## What these have in common

In all three the code was doing exactly what it was told. The bug was in the model: what a Docker
layer is, what a lint rule is protecting against, and what a version pin actually guarantees. The
fix in each case was a check that makes the correct behaviour hard to lose again, with the
reasoning written down next to it — because the next person to touch it will be me, months from
now, having forgotten.
