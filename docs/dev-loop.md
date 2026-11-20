# Development loop

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). How a change goes from idea to release when agents do the building. It adds to `AGENTS.md` (release rules), [specs/agent-rules.md](specs/agent-rules.md) (rules for builders) and [ROADMAP.md](ROADMAP.md) (what is planned); where they differ, those pages win.

## Roles

- **Owner**: decides, answers questions, publishes releases.
- **Coordinator**: the main Claude session. The only agent that talks to the owner, and the only one that merges.
- **Implementer**: one agent, one worktree, one PR.
- **Reviewer**: a read-only agent that reads a finished PR and reports.

Implementer and reviewer agents never merge.

## Stages

1. **Spec.** A file in `docs/specs/` with "Check first", the blocked items, and what cannot be verified. Starts from a ROADMAP row marked planned whose dependencies are merged.
2. **Spec questions.** The coordinator asks the owner about every blocked item. Each is answered or parked. The owner says "build".
3. **Build.** An implementer builds from the answered spec and opens a PR, pushing after every step.
4. **Checks.** `ci-ok` is green on the PR head, including macOS, Windows and the GUI jobs. The implementer fixes red checks.
5. **Review.** A reviewer reads the PR after CI is green. The report lists findings with file and line, says which were verified by running something and which only by reading, and ends with go or no-go.
6. **Result questions.** The coordinator asks the owner to accept the behaviour, the judgement calls and every "verified" claim in the docs.
7. **Merge.** See below.
8. **Release gate.** Only when the owner asks for a release. `main` is green on the exact commit, the coordinator runs a release question session, and the owner says "publish".
9. **Release.** The owner publishes. Agents only read the `release` and `docker-publish` runs and create `hotfix/X.Y.Z` as `AGENTS.md` says.
10. **Retro.** After each release: what failed, what the review caught, at most one rule change, asked as a question.

## Merging

The coordinator merges, after the owner has accepted the result (stage 6). Owner decision, 2026-11-20. The conditions:

- CI is fully green on the exact head commit, and the merge names that commit: `gh pr merge --squash --match-head-commit <full 40-character sha>`.
- The commit author is DDSNA, and no commit or PR body has a Claude, `Co-Authored-By`, `Claude-Session` or "Generated with" line.
- One PR at a time. After each merge the coordinator reads the push CI on `main` and waits for green before merging the next one. Two PRs that were green on their own have turned `main` red before.
- Two PRs that touch `docs/cli.md` or `tests/test_exit_codes.py` merge one at a time with a rebase between.
- Nobody pushes to `main` or force-pushes.
- Releases stay with the owner. Merging a release PR is part of the release flow, so the coordinator does it only on the owner's explicit word. The same goes for publishing.

The ROADMAP row changes in the same PR as the work.

## Questions from agents

Agents cannot ask the owner. Every implementer and reviewer report ends with a block like this:

```
## Questions for the owner
Q1 [blocking|non-blocking] <one-line question>
  Context: <two sentences, file:line or spec section>
  Options: A (recommended) <...> | B <...> | C <...>
  Built as: <what the PR does today, or "nothing built">
```

The coordinator does not forward the block raw. It drops what ROADMAP "Owner answers recorded" already answers, merges the rest with its own questions, and asks the owner through the interactive question tool.

- One question session at a time. A session asks at most **16** questions. If more are open, the coordinator asks the first 16 and then asks the owner whether to continue.
- Agents keep working on the parts that are not blocked while a session runs.
- Answers go to the live agent quoted word for word with the date, or into the brief of a new agent if the old one died. They are written to ROADMAP "Owner answers recorded" before the agent resumes.

## After a reboot or a killed agent

- Trust git and `gh` over the conversation. Run `git worktree list`, `gh pr list` and `git log origin/main` first.
- Implementers commit and push after every step, so a cut-off agent loses at most one step. If a PR exists, resume on its branch. If nothing was pushed, start again from the spec.
- Answers the owner gave in chat but that are not yet in ROADMAP get written down before anything else.
- Keep waits short: `gh pr checks --watch` with a `timeout`. The owner may have two terminals on one session.

## Limits

- At most **4** agents at once, and at most **one** of them runs Chromium (GUI tests, screenshots).
- Before starting an agent: `free -m` shows at least 1.5 GB available, the load is under 3, and the disk is not above about 88 percent. Otherwise wait.
- Inside a track the next package starts after the previous one is merged. Tracks A, B and C may run side by side.
- The rules in `specs/agent-rules.md` apply to every agent: own worktree, no version bump, no merge, no pushing to `main`.

## Screenshots

`AGENTS.md` retakes the screenshots at every major release. 0.6.0 breaks the CLI exit codes and the library `on_clash` default, so it counts as a major release (owner, 2026-11-20): run `scripts/gui_screenshots.py` and `scripts/readme_screenshots.py` on the release commit and commit the images before the release PR.

## Only the owner

- Running the Tableau Desktop checks ([tableau-check.md](tableau-check.md)). The writers that wait for them stay paused until he reports.
- Publishing a GitHub Release, PyPI and GHCR, and the word "release".
- Branch protection and repository settings ([ci-workflows.md](ci-workflows.md)).
- Starting Docker, installing skills or hooks, changing settings.

## What to track per release

- Defects the review found per PR, and how many CI missed.
- Defects found after a merge: red `main`, follow-up fix PRs, and the time to green.
- Questions asked, answered and parked, and any asked twice.
- Owner answers missing from ROADMAP at the retro (should be none).
- Agents cut off, and the steps lost.
- Doc claims the review had to correct.
- ROADMAP rows that were stale at release time.

## Failures seen so far

| Failure | Guard |
|---|---|
| `main` red after two PRs that were each green (#189 and #190, fixed by #192) | Merge one PR, read `main` push CI, then the next. |
| macOS-only break (#214) | The PR matrix has macOS (#218); `ci-ok` is the gate, not Ubuntu alone. |
| Docs that overclaim ("works in Tableau", flows never run) | The reviewer checks claims; the owner accepts each "verified" wording. Nothing is verified in Tableau Desktop unless a page says so. |
| Stale ROADMAP and plan pages | The ROADMAP row changes in the same PR; the release session asks about stale rows. |
| Agents cut off by reboots | Push after every step; check git first. |
| Owner answers only in chat | Written to ROADMAP before the agent resumes. |
| The harness adds Claude attribution lines | The owner's rule wins; the reviewer checks `git log`. |
