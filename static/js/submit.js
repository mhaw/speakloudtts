// static/js/submit.js
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('submit-form');
    const urlInput = document.getElementById('url-input');
    const voiceSelect = document.getElementById('voice-select'); // Corrected ID from original thought process
    const tagsInput = document.getElementById('tags-input');
    const submitBtn = document.getElementById('submit-btn');
    const btnSpinner = document.getElementById('btn-spinner');
    const btnText = document.getElementById('btn-text');
    const statusDiv = document.getElementById('status');

    if (!form) {
        console.error('Submit form not found.');
        return;
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const url = urlInput.value.trim();
        const voiceName = voiceSelect.value; // Assuming voiceSelect is the <select> element
        const tags = tagsInput.value
            .split(',')
            .map(t => t.trim())
            .filter(Boolean);

        if (!url) {
            statusDiv.textContent = 'Please enter an Article URL.';
            statusDiv.className = 'text-red-500 min-h-[2em] text-center';
            return;
        }

        // Disable UI + show spinner
        submitBtn.disabled = true;
        urlInput.disabled = true;
        voiceSelect.disabled = true;
        tagsInput.disabled = true;
        btnSpinner.classList.remove('hidden');
        btnText.textContent = 'Submitting...';
        statusDiv.textContent = 'Submitting your article for processing...';
        statusDiv.className = 'text-blue-600 min-h-[2em] text-center';

        try {
            // No client-side /extract call needed anymore.
            // The backend task handler will perform the extraction.

            const subRes = await fetch('/submit', { // /submit is the endpoint
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify({
                    url: url,
                    voice_name: voiceName,
                    tags: tags,
                    text_from_payload: "" // Sending empty, backend task will extract from URL
                })
            });

            const responseData = await subRes.json();

            if (!subRes.ok) {
                // Handle errors from the /submit endpoint itself (e.g., validation, task creation failure)
                throw new Error(responseData.error || responseData.detail || `Submission failed with status: ${subRes.status}`);
            }

            // Submission was accepted for background processing (202 Accepted)
            statusDiv.innerHTML = `${responseData.message || 'Article submitted successfully!'} Item ID: ${responseData.item_id}. <br>Processing will complete in the background. You can check its status on the <a href="/items" class="underline text-primary">All Articles</a> page.`;
            statusDiv.className = 'text-green-600 min-h-[2em] text-center';
            form.reset(); // Clear the form on successful submission

        } catch (err) {
            console.error('Submission error:', err);
            statusDiv.textContent = `Error: ${err.message || 'Could not submit article.'}`;
            statusDiv.className = 'text-red-500 min-h-[2em] text-center';
        } finally {
            // Re-enable UI
            submitBtn.disabled = false;
            urlInput.disabled = false;
            voiceSelect.disabled = false;
            tagsInput.disabled = false;
            btnSpinner.classList.add('hidden');
            btnText.textContent = 'Convert to Audio';
        }
    });

    // Initialize TomSelect for voice dropdown if it's not handled elsewhere
    // (This part was in static/js/app.js originally, moving it here for submit page specific JS)
    if (typeof TomSelect !== 'undefined' && document.getElementById('voice-select')) {
        new TomSelect('#voice-select', {
            create: false,
            sortField: {
                field: "text",
                direction: "asc"
            }
        });
        logger.info("TomSelect initialized for #voice-select on submit page.");
    } else if (document.getElementById('voice-select')) {
        // logger might not be defined here unless you have a global logger object for frontend
        console.log("TomSelect library not found, or #voice-select element missing. Voice dropdown will be standard.");
    }
});