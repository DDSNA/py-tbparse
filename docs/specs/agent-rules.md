# Rules for agents building from these specs

The owner's standing rules for every work package in this folder. [README.md](README.md) adds what the specs share; where the two differ, this file wins.

- **Repo.** `DDSNA/py-tbparse` on GitHub. Read `AGENTS.md` and the relevant docs first.
- **Own worktree.** Work in your own git worktree: `git fetch origin && git worktree add .claude/worktrees/<name> -b <branch> origin/main`. Never edit the main checkout. Never use a bare `git stash`. Never commit the `.browser-libs` symlink.
- **Commits and PR.** Author and committer name `DDSNA`, email `79444147+DDSNA@users.noreply.github.com` (set with `git -c user.name=... -c user.email=...`). No `Co-Authored-By`, `Claude-Session` or "Generated with" lines anywhere, in commits or in the PR body. PR description and comments: plain, human, specific; no generic-AI tone.
- **One PR per package.** No version bump in `pyproject.toml`. Never push to `main`, never force-push, never merge. Push with `git -c 'credential.helper=!gh auth git-credential' push -u origin <branch>` and open the PR with `gh pr create` (a draft is fine unless the spec says otherwise).
- **Tests.** Use the project's virtual environment and run plain `pytest` (not `python -m pytest`) with `PYTHONPATH` set to your worktree, as CI does (`scripts/ci-like-tests.sh` does this). Test files import helpers with `sys.path.insert(0, str(Path(__file__).parent))` and `from schema_check import ...`, never `from tests.x import`. Test paths must be valid on Windows (use `Path.as_uri()` for file URLs). Run only the non-browser tests unless told otherwise.
- **Machine limits.** The development machine is small and shared (2 CPUs, 8 GB). Check `free -m` and `uptime` first; run long jobs with `nice -n 10`, a `timeout` and a log. No Chromium unless the spec says so. Never render tens of thousands of rows in a DOM. Keep temporary files outside the repository.
- **No pip.** The machine has no `pip` command; the venv already has the packages the tests need. The Docker daemon is off. Do not use `pkill -f` with a pattern that appears in your own command line.
- **Docs.** Update the README, CLI help and docs for the new feature, and add a short `AGENTS.md` module-table entry if you add a module.
- **Report honestly.** Say what was verified and what was not (nothing is verified in Tableau Desktop), and report failures and weak results. The final report is short: PR URL, what changed, test counts, open questions.
