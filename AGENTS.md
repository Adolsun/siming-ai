# Siming Release Requirement

For every user-visible feature change in Siming, complete the release workflow
before reporting the work as finished unless the user explicitly asks not to
release it:

1. Update the application version and release metadata.
2. Complete a UI design review for every affected user-visible flow before
   packaging. Inspect the actual application at 1920x1080 and the minimum
   supported viewport, covering visual hierarchy, spacing and alignment,
   overflow and text truncation, responsive behavior, Chinese copy, and the
   loading, empty, error, disabled, and completed states. Capture screenshots
   of the key flow and treat unresolved visual regressions as release blockers.
3. Run the relevant backend tests, frontend lint and tests, and
   `frontend/npm run build`.
4. Build the distributable with `build-exe.bat` and verify `Siming.exe`,
   `update.json`, and `sha256.txt` agree.
5. Commit and push the versioned change.
6. Create or update the corresponding GitHub Release and upload the verified
   release assets.

Report the release URL, commit, and validation outcome in the final handoff.
