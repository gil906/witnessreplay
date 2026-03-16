# Google Cloud Proof for WitnessReplay

Use **this file's GitHub URL** in the Devpost "Proof of Google Cloud Deployment" field if you want judges to land on one place that points to the Google Cloud pieces in the repository.

Repository: <https://github.com/gil906/witnessreplay>

## Files that show Google Cloud deployment and service usage

1. **Cloud Build deploys the app to Cloud Run**  
   [`deploy/cloudbuild.yaml`](https://github.com/gil906/witnessreplay/blob/master/deploy/cloudbuild.yaml) builds the Docker image and runs `gcloud run deploy witnessreplay`.

2. **Terraform provisions Google Cloud infrastructure**  
   [`deploy/terraform/main.tf`](https://github.com/gil906/witnessreplay/blob/master/deploy/terraform/main.tf) enables Google APIs, provisions a Cloud Storage bucket, creates a Cloud Run service, wires Secret Manager, and grants IAM roles.

3. **Firestore is used for cloud-backed session persistence**  
   [`backend/app/services/firestore.py`](https://github.com/gil906/witnessreplay/blob/master/backend/app/services/firestore.py) initializes `google.cloud.firestore_v1.AsyncClient` with `GCP_PROJECT_ID` and uses it for session and case data.

4. **Google Cloud Storage is used for media/image storage**  
   [`backend/app/services/storage.py`](https://github.com/gil906/witnessreplay/blob/master/backend/app/services/storage.py) initializes `google.cloud.storage.Client` with `GCP_PROJECT_ID` and uploads witness/session assets.

5. **The app uses Google's GenAI SDK**  
   [`backend/requirements.txt`](https://github.com/gil906/witnessreplay/blob/master/backend/requirements.txt) includes `google-genai`, and code paths such as [`backend/app/services/api_key_manager.py`](https://github.com/gil906/witnessreplay/blob/master/backend/app/services/api_key_manager.py) instantiate `genai.Client` for Gemini-backed features.

6. **Architecture reference**  
   [`docs/ARCHITECTURE.md`](https://github.com/gil906/witnessreplay/blob/master/docs/ARCHITECTURE.md) documents the intended Google Cloud deployment path and how Gemini, Firestore, GCS, and the backend fit together.

## Recommended Devpost usage

- **Proof field/link:** use the GitHub URL of this file.
- **Architecture upload:** use [`docs/devpost/architecture-diagram.svg`](./architecture-diagram.svg).
- **Text description:** start from [`docs/devpost/submission-summary.txt`](./submission-summary.txt) or [`docs/devpost/submission-summary.md`](./submission-summary.md).

## Notes

WitnessReplay also contains a self-hosted Docker/GitHub Actions deployment path for iteration and local operations. The files above are the Google Cloud-specific assets to highlight for the challenge submission.
