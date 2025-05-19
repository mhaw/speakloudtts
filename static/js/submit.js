// static/js/submit.js

document.addEventListener('DOMContentLoaded', () => {
  const form     = document.getElementById('submit-form');
  const input    = document.getElementById('url-input');
  const voiceSel = document.getElementById('voice-select');
  const btn      = document.getElementById('submit-btn');
  const spinner  = document.getElementById('btn-spinner');
  const btnText  = document.getElementById('btn-text');
  const status   = document.getElementById('status');

  async function loadRecent() {
    try {
      const res   = await fetch('/api/recent');
      const items = await res.json();
      // you can display recent submissions here if desired
    } catch (e) {
      // silent fail
    }
  }

  form.addEventListener('submit', async e => {
    e.preventDefault();
    status.textContent = '';

    const url = input.value.trim();
    if (!url) {
      status.innerHTML = `<p class="text-red-600">Please enter a valid URL.</p>`;
      return;
    }

    // disable & show spinner
    btn.disabled = true;
    input.disabled = true;
    voiceSel.disabled = true;
    spinner.classList.remove('hidden');
    btnText.textContent = 'Submitting…';

    try {
      status.innerHTML = `<p>Validating & extracting…</p>`;
      const res = await fetch('/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          voice_name: voiceSel.value
        })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.error || 'Unexpected server response.');
      }

      // redirect to detail page
      window.location.href = `/items/${data.item_id}`;
    } catch (err) {
      console.error(err);
      status.innerHTML = `
        <div class="text-red-600">
          <strong>Error:</strong> ${err.message}
          <p class="mt-2 text-sm">Tip: Try another URL or check your console for details.</p>
        </div>`;
    } finally {
      btn.disabled     = false;
      input.disabled   = false;
      voiceSel.disabled = false;
      spinner.classList.add('hidden');
      btnText.textContent = 'Convert to Audio';
    }
  });

  // initial recent load (if you implement a recent list)
  loadRecent();
});