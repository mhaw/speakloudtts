// static/js/submit.js

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('submit-form');
    const urlInput = document.getElementById('url-input');
    const voiceSelect = document.getElementById('voice-select');
    const tagsInput = document.getElementById('tags-input');
    const submitBtn = document.getElementById('submit-btn');
    const statusDiv = document.getElementById('status');
    const spinner = document.createElement('span');
    spinner.className = "animate-spin ml-2 inline-block align-middle";
    spinner.innerHTML = '⏳';

    // Extra: focus on first field
    if (urlInput) urlInput.focus();

    // Extra: Instant URL validation (optional)
    urlInput.addEventListener('input', () => {
        try {
            if (urlInput.value && !/^https?:\/\/.+\..+/.test(urlInput.value)) {
                urlInput.classList.add('border-red-500');
            } else {
                urlInput.classList.remove('border-red-500');
            }
        } catch (e) {}
    });

    if (!form) {
        console.error('Submit form not found.');
        return;
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // Extra: Validate URL format
        const url = urlInput.value.trim();
        if (!url || !/^https?:\/\/.+\..+/.test(url)) {
            statusDiv.textContent = 'Please enter a valid Article URL.';
            statusDiv.className = 'text-red-500 min-h-[2em] text-center';
            urlInput.classList.add('border-red-500');
            urlInput.focus();
            return;
        }

        // Extra: Disable all form fields during submission
        [urlInput, voiceSelect, tagsInput, submitBtn].forEach(el => el && (el.disabled = true));
        submitBtn.dataset.oldText = submitBtn.textContent;
        submitBtn.textContent = 'Submitting...';
        submitBtn.appendChild(spinner);

        statusDiv.textContent = '';
        statusDiv.className = 'min-h-[2em] text-center';

        try {
            const data = {
                url: url,
                voice: voiceSelect.value,
                tags: tagsInput.value
            };

            const response = await fetch('/submit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json' // Signal to server we want JSON back
                },
                body: JSON.stringify(data)
            });

            // Check if the response is JSON before trying to parse it
            const contentType = response.headers.get("content-type");
            if (!response.ok || !contentType || !contentType.includes("application/json")) {
                // If we've been redirected (e.g., to the login page), reload the page
                if (response.redirected) {
                    window.location.href = response.url;
                    return;
                }
                // Otherwise, try to get a text error message
                const textError = await response.text();
                throw new Error(textError || `Server returned a non-JSON response (${response.status}).`);
            }

            const responseData = await response.json();

            if (!responseData.success) {
                throw new Error(responseData.error?.message || 'An unknown error occurred.');
            }

            if (responseData.success && responseData.data.redirect) {
                // On success, redirect to the items list
                window.location.href = responseData.data.redirect;
            } else {
                // Handle cases where there might be a success message but no redirect
                statusDiv.textContent = responseData.message || 'Submission processed!';
                statusDiv.className = 'text-green-600 min-h-[2em] text-center';
                form.reset();
            }
        } catch (err) {
            statusDiv.textContent = `Error: ${err.message}`;
            statusDiv.className = 'text-red-500 min-h-[2em] text-center';
        } finally {
            // Restore form fields
            [urlInput, voiceSelect, tagsInput, submitBtn].forEach(el => el && (el.disabled = false));
            submitBtn.textContent = submitBtn.dataset.oldText || 'Convert to Audio';
        }
    });
});