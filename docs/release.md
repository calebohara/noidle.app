# Releasing noidle.app

## Cutting a release

1. Bump the version in `pyproject.toml` (and anywhere else it lives).
2. Commit and push to `main`.
3. Tag and push:

   ```bash
   git tag v0.1.0
   git push --tags
   ```

4. Watch the `build` workflow in GitHub Actions. On a `v*` tag it will:
   - Build `noidle.exe` on `windows-latest` with PyInstaller
   - Upload the binary as a workflow artifact
   - Create a GitHub Release and attach `noidle.exe`

That's the whole flow. No manual upload step.

## Manual / dry-run builds

Trigger the `build` workflow from the Actions tab via **Run workflow**
(`workflow_dispatch`). The artifact will be attached to the workflow run but
no Release will be created.

## Antivirus / SmartScreen false positives

PyInstaller-packed `.exe` files are routinely flagged by Windows Defender
SmartScreen and several third-party AV engines. This is not because the binary
is actually malicious — it's because the PyInstaller bootloader is a popular
packaging tool for both legitimate apps and malware, so heuristic detectors
are noisy on it.

Expect the following on a fresh download:

- **SmartScreen warning**: "Windows protected your PC" — users will need to
  click *More info* then *Run anyway*.
- **Occasional AV detections** (Defender, Avast, etc.) — usually transient
  and clear up after the binary has been seen in the wild for a while.

The real fix is an Authenticode code-signing certificate (EV cert builds
SmartScreen reputation immediately). That's **out of scope for v1** — buying
and managing a cert is several hundred dollars per year plus key custody
overhead.

### Pre-publish hygiene

Before announcing a release, upload the built `.exe` to
[VirusTotal](https://www.virustotal.com/) and skim the results. If a flag
looks credible (not a generic `PyInstaller`/`Wacatac.B!ml` heuristic), pull
the release and investigate before promoting it.
