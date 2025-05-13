// static/js/submit.js
document.addEventListener('DOMContentLoaded', () => {
    const form      = document.getElementById('submit-form');
    const input     = document.getElementById('url-input');
    const voiceSel  = document.getElementById('voice-select');
    const btn       = document.getElementById('submit-btn');
    const spinner   = document.getElementById('btn-spinner');
    const btnText   = document.getElementById('btn-text');
    const statusDiv = document.getElementById('status');
    const recentUl  = document.getElementById('recent-list');
  
    // Validate URL via try { new URL(...) }
    function validate() {
      try {
        new URL(input.value.trim());
        btn.disabled = false;
        statusDiv.textContent = '';
      } catch {
        btn.disabled = true;
        if (input.value) {
          statusDiv.textContent = 'Please enter a valid URL.';
        } else {
          statusDiv.textContent = '';
        }
      }
    }
    input.addEventListener('input', validate);
  
    // Load recent articles
    async function loadRecent() {
      try {
        const res   = await fetch('/api/recent');
        const items = await res.json();
        recentUl.innerHTML = '';
        items.forEach(i => {
          const li = document.createElement('li');
          const a  = document.createElement('a');
          a.href        = `/items/${i.id}`;
          a.textContent = i.title;
          a.className   = 'hover:underline';
          li.append(a);
          recentUl.append(li);
        });
      } catch (e) {
        // silently fail
      }
    }
    loadRecent();
  
    // Handle submission
    form.addEventListener('submit', async e => {
      e.preventDefault();
      statusDiv.textContent = '';
  
      const url = input.value.trim();
      if (!url) return;
  
      btn.disabled = true;
      input.disabled = true;
      voiceSel.disabled = true;
      spinner.classList.remove('hidden');
      btnText.textContent = 'Submitting…';
  
      try {
        statusDiv.innerHTML = `<p>Validating & extracting…</p>`;
        const res  = await fetch('/submit', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ url, voice_name: voiceSel.value })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || 'Server error');
        window.location.href = `/items/${data.item_id}`;
      } catch (err) {
        console.error(err);
        statusDiv.innerHTML = `
          <div class="text-red-600">
            <strong>Error:</strong> ${err.message}
          </div>`;
      } finally {
        btn.disabled     = false;
        input.disabled   = false;
        voiceSel.disabled= false;
        spinner.classList.add('hidden');
        btnText.textContent = 'Convert to Audio';
      }
    });
  });