# Contributing

Working on this instrument's code? Start with
**[`docs/git_workflow.md`](docs/git_workflow.md)** — nine rules, one line of
reasoning each.

Deploying to or verifying the lab PC? Follow
**[`docs/lab_pc_verification.md`](docs/lab_pc_verification.md)** — a staged
procedure that runs cheapest and safest first.

Looking for something to pick up? `MODERNIZATION.md` is the standing
technical-debt backlog, ordered by tier.

## Quick reference

```bash
# set your identity first, on every machine you commit from — use your
# GitHub no-reply address (GitHub -> Settings -> Emails), never a personal one
git config user.name  "Your Name"
git config user.email "<id>+<username>@users.noreply.github.com"
git config core.hooksPath .githooks     # safety checks before every commit

# work on a branch
git switch develop && git pull
git switch -c fix/short-description

# before you push: 64 tests, no hardware, ~15 seconds
python -m pytest test_controller_simulated.py test_headless_simulation.py test_repo_guard.py -q
```
