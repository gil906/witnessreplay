# Devpost Submission Checklist

## Ready in the repository

- [x] Public code repository: <https://github.com/gil906/witnessreplay>
- [x] Spin-up instructions in `README.md`
- [x] Submission summary files:
  - `docs/devpost/submission-summary.md`
  - `docs/devpost/submission-summary.txt`
- [x] Uploadable architecture diagram:
  - `docs/devpost/architecture-diagram.svg`
- [x] Google Cloud proof doc:
  - `docs/devpost/google-cloud-proof.md`
- [x] Exportable bundle generator:
  - `tools/export_devpost_bundle.py`

## Recommended Devpost form inputs

- **Text description:** paste from `docs/devpost/submission-summary.txt`
- **Public code repository URL:** <https://github.com/gil906/witnessreplay>
- **Google Cloud proof link:** use the GitHub URL of `docs/devpost/google-cloud-proof.md`
- **File upload / image carousel:** upload `docs/devpost/architecture-diagram.svg` or the generated zip bundle

## Manual items to finish before final submission

- [ ] Record the under-4-minute demo video showing the live multimodal workflow
- [ ] Add the final demo/video URL(s) to the Devpost submission
- [ ] If you want stronger hosting proof, record a short Cloud Console / Cloud Run clip in addition to the repo proof doc
- [ ] Double-check the final Devpost category and challenge wording before submitting

## Bundle command

```bash
python3 tools/export_devpost_bundle.py
```

Generated output:

- `dist/devpost/witnessreplay-devpost-submission/`
- `dist/devpost/witnessreplay-devpost-submission.zip`
