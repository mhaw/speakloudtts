// static/js/submit.js
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('submit-form');
    const urlInput = document.getElementById('url-input');
    const voiceSelect = document.getElementById('voice-select');
    const tagsInput = document.getElementById('tags-input');
    const submitBtn = document.getElementById('submit-btn');
    const statusDiv = document.getElementById('status');

    if (!form) {
        console.error('Submit form not found.');
        return;
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const url = urlInput.value.trim();
        if (!url) {
            statusDiv.textContent = 'Please enter an Article URL.';
            statusDiv.className = 'text-red-500 min-h-[2em] text-center';
            return;
        }

        submitBtn.disabled = true;
        statusDiv.textContent = 'Submitting...';
        statusDiv.className = 'text-blue-600 min-h-[2em] text-center';

        try {
            const formData = new FormData(form);

            // DEBUG: log the fields sent
            for (let pair of formData.entries()) {
                console.log(pair[0], pair[1]);
            }

            const response = await fetch('/submit', {
                method: 'POST',
                body: formData
                // DO NOT set Content-Type header!
            });

            if (response.redirected) {
                window.location.href = response.url;
                return;
            }

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || 'Unknown error');
            }
            statusDiv.textContent = data.message || 'Submission successful!';
            statusDiv.className = 'text-green-600 min-h-[2em] text-center';
            form.reset();
        } catch (err) {
            statusDiv.textContent = `Error: ${err.message}`;
            statusDiv.className = 'text-red-500 min-h-[2em] text-center';
        } finally {
            submitBtn.disabled = false;
        }
    });
});