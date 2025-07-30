# DEBUGGING.md

This document provides guidance for debugging common issues in the SpeakLoudAudio application.

## Where Logs Live

Application logs are crucial for debugging. Depending on your environment, you can find logs in the following locations:

-   **Local Development (`run_local_dev.sh`)**: Logs are printed directly to your terminal.
-   **Docker Containers**: Use `docker-compose logs` to view logs from your running containers.
-   **Cloud Run**: Logs are sent to Google Cloud Logging. You can view them in the Google Cloud Console under "Logging" -> "Logs Explorer".

## How to Tell if Playwright is Broken

Playwright is used for robust article extraction. If extraction is failing, Playwright might be the culprit.

**Symptoms of a broken Playwright setup:**

-   `Playwright extraction failed: BrowserType.launch: Executable doesn't exist...` in your logs.
-   `Playwright returned invalid HTML or binary data.` in your logs.
-   Articles consistently fail to extract, especially from complex websites.

**Troubleshooting Steps:**

1.  **Check Dockerfile**: Ensure your `Dockerfile` is using the `mcr.microsoft.com/playwright/python` base image, which includes pre-installed browsers.
2.  **Verify Playwright Installation (inside Docker)**: If you're building your own image, you can shell into the running container and manually run:
    ```bash
    playwright install --with-deps
    ```
    This should confirm if the browsers are present and correctly linked.
3.  **Use `/debug_extract`**: Test a problematic URL using the `/debug_extract` endpoint (e.g., `http://localhost:8080/debug_extract?url=https://example.com`). If this returns an error related to Playwright, it confirms the issue.

## Sample `curl` Commands for Testing Endpoints

Here are some `curl` commands you can use to test various application endpoints, especially useful for debugging API interactions.

### Testing `/submit` (requires authentication)

First, you'll need to log in to get a session cookie. This is typically done via the browser. For API testing, you might need to simulate a login or use a tool like Postman/Insomnia that handles sessions.

Assuming you have a valid session (e.g., from a browser login):

```bash
curl -X POST -H "Content-Type: application/json" \
     -b "session=YOUR_SESSION_COOKIE_HERE" \
     -d '{"url": "https://www.example.com/article", "voice": "en-US-Wavenet-D", "tags": "news,tech"}' \
     http://localhost:8080/submit
```

### Testing `/debug_extract`

```bash
curl "http://localhost:8080/debug_extract?url=https://www.nytimes.com/2023/01/01/us/example-article.html"
```

### Testing `/debug`

```bash
curl http://localhost:8080/debug
```

This should return JSON indicating the application status and environment.


```