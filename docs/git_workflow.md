# Working on this repository

Eight rules. Each one has a one-line reason, because a rule you understand is
a rule you keep.

If you only read one thing: **rule 2**. Everything else on this page is
tidiness. Rule 2 is the one that has actually cost this project real work.

---

## 1. Set your own git identity before your first commit

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
```

> **Why:** the lab PC has a default identity (`match@Raman`) that is not a
> person, and everything committed under it gets credited to whoever used that
> machine last. Set your own and your work stays yours.

Check it took, and check it on *every* machine you commit from:

```bash
git config user.name && git config user.email
```

---

## 2. Push every day you touch the code, even if it is broken

On your own branch, at the end of the day, whatever state it is in.

> **Why:** the entire laser migration once existed only as uncommitted changes
> on the lab PC for six months. Nobody could see it, review it, or recover it
> if the disk died. Forty messy commits on a branch are worth more than one
> perfect commit that arrives in September.

"But it doesn't work yet" is the reason to push, not the reason not to. That
is what branches are for.

```bash
git add -A
git commit -m "wip: halfway through the grating homing fix"
git push
```

---

## 3. Work on a branch, never directly on `develop`

```bash
git switch develop
git pull
git switch -c fix/grating-backlash      # or feature/...
```

> **Why:** a branch can be reviewed, discussed and abandoned. A commit
> straight onto `develop` can only be reverted, and reverting is loud.

Name it for what it does: `fix/triax-timeout`, `feature/polarisation-scan`.
Delete it once merged — the history stays, the clutter does not.

---

## 4. Run the tests before you push

```bash
python -m pytest test_controller_simulated.py test_headless_simulation.py -q
```

Expect `29 passed`. No hardware needed — it takes about ten seconds.

> **Why:** these run the whole application against simulated instruments, so
> they catch the "it won't even start" class of bug in ten seconds instead of
> in front of the microscope.

CI runs the same two suites on every push, so you will find out either way.
Better to find out before.

---

## 5. If you had to edit a tracked file to make the rig run, say so

A changed COM port, a changed path, a flag flipped — report it, don't quietly
keep it in your working tree.

> **Why:** an undeclared local edit is exactly how the repository and the
> instrument drift apart, and it stays invisible until someone else's pull
> breaks the rig.

It is a finding, not a workaround. Open an issue or put it in the PR.

---

## 6. Never `git reset --hard` or `git checkout -- .` on the lab PC

If a pull complains about local changes, stash them:

```bash
git stash push -u -m "lab PC state before pull 2026-08-26"
git stash list
```

> **Why:** a stash can always be recovered or dropped later. A hard reset
> cannot be undone, and on the lab PC it may be destroying the only copy of
> somebody's bench work.

Full procedure in [`lab_pc_verification.md`](lab_pc_verification.md).

---

## 7. Never commit the per-machine state files

These are already in `.gitignore`. Do not force them in:

- `calibration/tiger_step_position.json`
- `instrument_state.json`
- `acquisitioncontrol/acquisition_config.json`
- `acquisitioncontrol/viewer_settings.json`
- `instrument_errors.log`

> **Why:** they record where *this* rig's hardware physically is. Committing a
> value from one machine tells another machine its motors are somewhere they
> are not, and the next relative move goes to the wrong place.

If a pull ever tries to change one of these, stop and report it.

---

## 8. Write the commit subject so it finishes "applying this commit will…"

```
feat: add polarisation sweep to the scan controller     ✅
fix: stop triax initialise timing out on cold start     ✅

update                                                  ❌
pulled from dev PC to sync changes                      ❌  (how it travelled,
                                                             not what changed)
```

> **Why:** you are writing for the person who runs `git log` in six months
> trying to work out why something moved. That person is usually you.

Keep the `feat:` / `fix:` / `chore:` / `docs:` / `refactor:` prefixes — this
repo already uses them. Body text is free: use it to say *why*, since the
diff already says *what*.

---

## Opening a pull request

```bash
git push -u origin fix/grating-backlash
```

Then open a PR into `develop` on GitHub and describe:

- what changed, and why
- whether you tested it on real hardware or only in simulation
- anything you are unsure about

> **Why the PR, with only two of us:** it is not gatekeeping. It is a
> permanent, threaded conversation about a specific piece of code, attached to
> that code — which is a far better place to learn than email.

Mark it a draft if it is not finished. A draft PR is a good way to ask "am I
going in the right direction?" before spending another week.

---

## When something goes wrong

Git rarely loses work that was committed. If you are in a mess:

```bash
git status                # what state am I actually in
git stash list            # anything parked?
git reflog                # every commit HEAD has pointed at, including "lost" ones
```

**Stop before running anything with `--hard`, `--force` or `clean -fd`.** Those
are the four ways to actually destroy work. Everything else is recoverable.

Ask. A five-minute question beats a day of reconstruction.
