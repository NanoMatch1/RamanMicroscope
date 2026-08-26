# Contributing

Working on this instrument's code? Start with
**[`docs/git_workflow.md`](docs/git_workflow.md)** — eight rules, one line of
reasoning each.

Deploying to or verifying the lab PC? Follow
**[`docs/lab_pc_verification.md`](docs/lab_pc_verification.md)** — a staged
procedure that runs cheapest and safest first.

Looking for something to pick up? `MODERNIZATION.md` is the standing
technical-debt backlog, ordered by tier.

## Quick reference

```bash
# set your identity first, on every machine you commit from
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"

# work on a branch
git switch develop && git pull
git switch -c fix/short-description

# before you push: 29 tests, no hardware, ~10 seconds
python -m pytest test_controller_simulated.py test_headless_simulation.py -q
```
