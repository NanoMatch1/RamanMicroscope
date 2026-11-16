# Grating alignment quickstart

Use this guide when the Raman signal is lost completely and the excitation
filter (gratings g1–g4 of the double subtractive monochromator) needs
re-aligning.

> **⚠️ Before you start:** place a laser blocker at the very end of the optical
> path so the laser cannot reach the camera directly.

0. **Rule out the simple causes first.**
   - The spectrometer is set to grating 3 and is in position (check with the
     Hg lamp).
   - The camera is working (check with the Hg lamp).
   - The laser is on.
   - The sample is in focus and not degraded.
   - No laser blockers are sitting in the optical path (other than the one
     protecting the camera).
1. Home gratings 1–4.
2. Align g1 so the beam passes through the pinhole placed in front of the
   sample. This is the only fully consistent reference. Mark this position in steps or 
   wavelength.
3. We are going to use g1 to back-reflect the laser now past the cutoff filter mirror of 
   stage 1. 
   Move g1 a lot, until the first-order reflection now hits the cuttoff filter mirror.
   Bring the beam onto the edge of the filter, then keep moving towards the edge until it
   can no longer be observed on the filter (i.e. it is now passing the edge of the mirror 
   as the Raman light will. This is approximately −608 steps from the alignment position of (2) when using 1/32 microstepping).
4. Place a fluorescent target near the end of the optical path and align g2 so
   the (now broad) laser spot sits at middle height. If no laser spot is
   visible, move g3 negative until it passes the second cutoff filter.
5. Move g3 until the beam is completely blocked by the second cutoff filter.
6. Move g4 to approximately the same position as g3, with the sign flipped.
7. Return g1 to alignment.
8. Remove all laser blockers and targets.
9. Begin recording spectra (30 s acquisition).
10. If no signal is observed, move g4 a long way off and scan slowly back.
