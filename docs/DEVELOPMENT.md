# DEVELOPMENT.md

This document outlines the development workflow for SpeakLoudAudio, covering local setup, environment toggles, and Git best practices.

## Local Development Setup

To run the application locally in development mode, use the provided `run_local_dev.sh` script. This script sets the `ENV_MODE` to `dev` and starts the Flask development server with auto-reloading.

```bash
./scripts/run_local_dev.sh
```

In `dev` mode, Google Cloud integrations (Firestore, GCS, TTS) are skipped. The application will log expected behavior and return dummy values for these services, allowing you to develop and test core application logic without needing active GCP credentials or incurring costs.

## Environment Toggles (`ENV_MODE`)

The application uses an `ENV_MODE` environment variable to distinguish between development and production environments. This is configured in `config.py` and read from your `.env` file.

-   **`ENV_MODE=dev`**: Local development mode. Skips GCP integrations. Ideal for rapid iteration and testing.
-   **`ENV_MODE=prod`**: Production mode. Connects to actual GCP services. Used for deployments (e.g., Cloud Run).

To switch modes, set the `ENV_MODE` environment variable accordingly. For local development, `run_local_dev.sh` handles this automatically.

## Testing Playwright Extraction Locally

Playwright is used for robust article extraction. If you encounter issues with Playwright, ensure its browsers are correctly installed within your Docker environment. The `Dockerfile` is configured to install these dependencies.

To test Playwright extraction for a specific URL, you can use the `/debug_extract` endpoint:

```bash
curl "http://localhost:8080/debug_extract?url=https://example.com/your-article-url"
```

This will return the extracted text as plain text, helping you debug extraction issues.

## Deployment Checklist for Cloud Run

1.  **Ensure `ENV_MODE` is set to `prod`**: Before deploying to Cloud Run, verify that your deployment environment sets `ENV_MODE=prod`.
2.  **GCP Credentials**: Ensure your Cloud Run service has the necessary IAM permissions to access Firestore, GCS, and Cloud Tasks.
3.  **Environment Variables**: All required environment variables (e.g., `GCS_BUCKET_NAME`, `GCP_PROJECT_ID`, `TTS_TASK_QUEUE_ID`, `FLASK_SECRET_KEY`) must be configured in your Cloud Run service.
4.  **Build and Deploy Docker Image**: Build your Docker image and deploy it to Cloud Run.

## How to Roll Back a Broken Deploy with Git Tags

Git tags are used to mark stable, working versions of your application, enabling quick rollbacks if a deployment introduces issues.

1.  **Tag a Working Version**: Before deploying a new feature or significant change, tag your current working version:

    ```bash
    git tag vX.Y.Z-working
    git push origin vX.Y.Z-working
    ```

    Replace `vX.Y.Z` with your version number (e.g., `v0.4.2`).

2.  **Roll Back**: If a new deployment is broken, you can roll back to a previously tagged working version:

    ```bash
    git checkout vX.Y.Z-working
    # Then rebuild and redeploy your application from this state
    ```

    This will revert your local repository to the state of the tagged version. You can then rebuild and redeploy from this stable point.

## Git Commit Guidance

Follow this suggested commit flow for clear and manageable changes:

1.  **Start a new feature branch**: 
    ```bash
    git checkout -b feature/my-new-feature
    ```
2.  **Commit frequently with descriptive messages**: 
    ```bash
    git commit -m "Add feature X: detailed description of changes"
    ```
3.  **Push your feature branch**: 
    ```bash
    git push origin feature/my-new-feature
    ```
4.  **Merge into main (after review, if applicable)**:
    ```bash
    git checkout main
    git merge feature/my-new-feature
    ```

