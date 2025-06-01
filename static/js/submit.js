// static/js/submit.js
document.addEventListener('DOMContentLoaded', () => {
  const form       = document.getElementById('submit-form');
  const input      = document.getElementById('url-input');
  const voiceSel   = document.getElementById('voice-select');
  const tagsInput  = document.getElementById('tags-input');
  const btn        = document.getElementById('submit-btn');
  const spinner    = document.getElementById('btn-spinner');
  const btnText    = document.getElementById('btn-text');
  const status     = document.getElementById('status');

  form.addEventListener('submit', async e => {
    e.preventDefault();
    status.textContent = '';
    const url    = input.value.trim();
    const voice  = voiceSel.value;
    const tags   = tagsInput.value
                     .split(',')
                     .map(t => t.trim())
                     .filter(Boolean);

    if (!url) {
      status.innerHTML = `<p class="text-red-600">Please enter a valid URL.</p>`;
      return;
    }

    // Disable UI + show spinner
    btn.disabled     = true;
    input.disabled   = true;
    voiceSel.disabled= true;
    tagsInput.disabled = true;
    spinner.classList.remove('hidden');
    btnText.textContent = 'Working…';

    try {
      // 1) Extract
      status.textContent = 'Extracting article…';
      const extRes = await fetch('/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      const meta = await extRes.json();
      if (!extRes.ok) throw new Error(meta.detail || meta.error);

      // 2) Submit
      status.textContent = 'Converting to audio…';
      const subRes = await fetch('/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          voice_name: voice,
          text: meta.text,
          tags
        })
      });
      const data = await subRes.json();
      if (!subRes.ok) throw new Error(data.detail || data.error);

      // Redirect to the new item
      window.location.href = `/items/${data.item_id}`;
    } catch (err) {
      console.error(err);
      status.innerHTML = `
        <p class="text-red-600">
          <strong>Error:</strong> ${err.message}
        </p>`;
    } finally {
      // Re-enable UI
      btn.disabled      = false;
      input.disabled    = false;
      voiceSel.disabled = false;
      tagsInput.disabled= false;
      spinner.classList.add('hidden');
      btnText.textContent = 'Convert to Audio';
    }
  });
});