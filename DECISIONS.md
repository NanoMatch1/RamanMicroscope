# Design decisions -- RamanMicroscope

Why the code is the way it is: each non-obvious choice, the reasoning, and the alternatives that
were tried or rejected. Read the relevant section **before** changing related code, and add or
amend an entry **as part of** the change. The evidence behind an entry is a finding in the private
Raman notebook, cited by ID (`RAM-F#`); the results themselves stay there, not here.

Sections are numbered so code, commits and PRs can cite them ("DECISIONS §1"). Rationale only:
progress notes belong in the changelog and git history.

---

## §1 The stage 1 edge model and its fit stay fixed: a step of free height and slope, least squares

**Decision:** `filter_calibration/edge_fit.py` fits one model, a cumulative-normal step whose
plateau may slope, plus a flat baseline (`edge_model`), by ordinary least squares over a window
around the edge. Every frame of every session is fitted with the same model and the same loss.

**Why:** the g1 calibration is built from these edges, and an edge's position is only comparable
between frames and sessions if "edge" means the same thing in each: the midpoint of the same
model, fitted the same way. The model describes the physics of a cutoff seen through a slit
(a blurred step on a sloping spectrum), and the g1 calibration was made with it (RAM-F5).

**Rejected alternative:** a robust fit (soft-L1 loss, columns off the fit clipped, and a choice
between flat, red-sloped and two-sloped models per frame by BIC), written to cope with frames the
fit had failed on. It made the fit cope with a defect in the data instead of exposing it, moved
the edges of clean sessions, fitted one wide edge through two-component edges, and let the
meaning of "edge" change frame by frame within one walk (RAM-F9). The failure it addressed was
fixed in the first guess instead (§2), and the defect in the data was flagged for the bench.

**Changing it:** a new model or loss needs a known-answer test on simulated frames, and a
comparison on the earlier sessions' frames showing their edges do not move (the fit version
comparison in the notebook's 2026-11-25 session), recorded as a finding before it is merged.

**Where:** `filter_calibration/edge_fit.py` (`edge_model`, `attempt_edge_fit`).

## §2 The fit starts from the first rise of the band, not the steepest

**Decision:** the starting point of the edge fit is the bluest place where the band signal rises
by at least `first_rise_fraction` of its largest rise, measured with medians over
`step_window_nm` (`first_rise_pixel`).

**Why:** the cutoff edge is the first rise coming from the blue. Any feature further red that is
steeper than the edge (the recovery after a narrow dip, such as a shadow fixed to a CCD column)
would otherwise take the fit, which then reports that feature as the edge or fails (RAM-F9).
Medians ignore features narrower than half the window.

**Rejected alternative:** the steepest rise of the signal smoothed over a few columns, the
original guess. It is right on clean frames and wrong whenever anything red of the edge is
steeper (RAM-F9).

**Where:** `filter_calibration/edge_fit.py` (`rise_scores`, `first_rise_pixel`).
