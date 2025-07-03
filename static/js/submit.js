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
            const formData = new FormData(form);

            const response = await fetch('/submit', {
                method: 'POST',
                body: formData
            });

            if (response.redirected) {
                window.location.href = response.url;
                return;
            }

            let data, errorText;
            try {
                data = await response.json();
            } catch (jsonErr) {
                errorText = await response.text();
            }

            if (!response.ok) {
                throw new Error(
                    (data && data.error) ||
                    errorText ||
                    `Server error (${response.status})`
                );
            }

            statusDiv.textContent = (data && data.message) || 'Submission successful!';
            statusDiv.className = 'text-green-600 min-h-[2em] text-center';

            // Extra: animate success
            statusDiv.classList.add('animate-pulse');
            setTimeout(() => statusDiv.classList.remove('animate-pulse'), 1500);

            form.reset();
            urlInput.classList.remove('border-red-500');
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