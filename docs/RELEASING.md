# Manual release evidence

Releases are manual. This checklist does not create a tag, publish assets, enable
GitHub Actions, or attest that a build is reproducible. The model is downloaded
separately and is not included in the wheel or sdist.

1. Decide the release version and license, update `pyproject.toml`,
   `src/nsfw_guard/__init__.py`, and `CHANGELOG.md`, then commit the source. Keep
   the version identical in both code locations. Start from a clean tracked tree.
2. In a local virtual environment with `python -m pip install -e ".[cpu,dev]"`, run
   `python scripts/validate_local.py`. Capture the complete command output and
   exit status. Stop if any step fails.
3. Build wheel and sdist with `python -m build`, then run
   `python -m twine check --strict dist/*`. Capture those commands and outcomes
   too. Test installation of the built wheel in a clean environment, including
   `python -m pip check`, `nsfw-guard --version`, and a safe local smoke test.
   Check any platform/provider combination claimed in the release notes.
4. Review and sanitize the validation logs before sharing them. Never publish
   private image paths, image bytes, secrets, or sensitive samples. Preserve the
   complete local originals for internal review.
5. Generate a manifest from the exact files intended for release, using a
   committed, clean tracked tree:

   ```powershell
   .venv\Scripts\python.exe scripts\release_manifest.py `
     --wheel dist\nsfw_guard-VERSION-py3-none-any.whl `
     --sdist dist\nsfw_guard-VERSION.tar.gz `
     --validation-log release-evidence\validate-local.txt `
     --validation-log release-evidence\build-and-check.txt `
     --validation-log release-evidence\wheel-smoke.txt `
     --output dist\release-manifest.json
   ```

   Replace `VERSION` with the actual version. The script refuses to overwrite an
   existing output file. It checks wheel and sdist metadata against source
   versions, records the current Git commit and clean tracked-tree status, and
   hashes the artifacts and supplied logs. It also records the model's pinned
   revision, URL, license, and SHA-256 from source. It does **not** run or judge
   validation, certify artifact provenance, or sign the manifest. Inspect every
   supplied log and its exit status before making a release claim.
6. Compare the manifest hashes with the final assets, prepare `SHA256SUMS.txt`,
   and review release notes, licensing, and model disclosures. Tag and publish
   only as a separate, deliberate release action after review.

The project intentionally keeps compatible dependency ranges in `pyproject.toml`.
CPU, DirectML, CUDA, and bundled CUDA resolve different dependencies on different
hosts. A single development-environment SBOM would not describe all installed
variants. If downstream distribution requires an SBOM, generate it from each
resolved release environment and label its platform and runtime extra explicitly.
