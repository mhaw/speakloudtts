document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('submit-form');
  const input = document.getElementById('url-input');
  const voiceSel = document.getElementById('voice-select');
  const tagsInput = document.getElementById('tags-input');
  const previewSection = document.getElementById('preview-section');
  const extractedText = document.getElementById('extracted-text');
  const editBtn = document.getElementById('edit-toggle');
  const btn = document.getElementById('submit-btn');
  const spinner = document.getElementById('btn-spinner');
  const btnText = document.getElementById('btn-text');
  const status = document.getElementById('status');

  // Load recent submissions if needed
  async function loadRecent() {
    try {
      const res = await fetch('/api/recent');
      const items = await res.json();
      // TODO: render recent items in UI
    } catch (_) {
      // silent fail
    }
  }

  // Toggle extracted-text editability
  if (editBtn && extractedText) {
    editBtn.addEventListener('click', () => {
      const isReadOnly = extractedText.hasAttribute('readonly');
      if (isReadOnly) {
        extractedText.removeAttribute('readonly');
        extractedText.classList.remove('bg-gray-800');
        extractedText.classList.add('bg-white');
        editBtn.textContent = 'Lock Text';
      } else {
        extractedText.setAttribute('readonly', '');
        extractedText.classList.remove('bg-white');
        extractedText.classList.add('bg-gray-800');
        editBtn.textContent = 'Edit Text';
      }
    });
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    status.textContent = '';

    const url = input.value.trim();
    if (!url) {
      status.innerHTML = '<p class="text-red-600">Please enter a valid URL.</p>';
      return;
    }

    // Disable controls and show spinner
    btn.disabled = true;
    input.disabled = true;
    voiceSel.disabled = true;
    tagsInput.disabled = true;
    spinner.classList.remove('hidden');

    const isExtractPhase = previewSection.classList.contains('hidden');
    btnText.textContent = isExtractPhase ? 'Extracting…' : 'Converting…';

    if (isExtractPhase) {
      status.innerHTML = '<p>Validating & extracting…</p>';
      try {
        const res = await fetch('/extract', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || 'Extraction failed.');

        extractedText.value = data.text;
        previewSection.classList.remove('hidden');
        status.textContent = 'Adjust the text above or click Convert again to continue.';
      } catch (err) {
        console.error(err);
        status.innerHTML = `<div class="text-red-600"><strong>Error:</strong> ${err.message}</div>`;
      }
    } else {
      status.innerHTML = '<p>Converting to audio…</p>';
      try {
        const payload = {
          url,
          voice_name: voiceSel.value,
          text: extractedText.value,
          tags: tagsInput.value
            .split(',')
            .map(t => t.trim())
            .filter(t => t)
        };
        const res = await fetch('/submit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || 'Conversion failed.');

        window.location.href = `/items/${data.item_id}`;
      } catch (err) {
        console.error(err);
        status.innerHTML = `<div class="text-red-600"><strong>Error:</strong> ${err.message}</div>`;
      }
    }

    // Re-enable controls
    spinner.classList.add('hidden');
    btnText.textContent = 'Convert to Audio';
    btn.disabled = false;
    input.disabled = false;
    voiceSel.disabled = false;
    tagsInput.disabled = false;
  });

  loadRecent();
});
