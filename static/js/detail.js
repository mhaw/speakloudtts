// static/js/detail.js

document.addEventListener('DOMContentLoaded', () => {
  const ITEM_ID     = window.SLTTS_ITEM_ID;
  const audio       = document.getElementById('audio-player');
  const progressBar = document.getElementById('audio-progress');
  const paras       = Array.from(document.querySelectorAll('#full-text .paragraph'));
  const currentEl   = document.getElementById('current-time');
  const totalEl     = document.getElementById('total-time');
  const speedBtns   = Array.from(document.querySelectorAll('.speed-btn'));
  const rewindBtn   = document.getElementById('rewind-btn');
  const forwardBtn  = document.getElementById('forward-btn');
  const editBtn     = document.getElementById('edit-tags-btn');
  const editor      = document.getElementById('tags-editor');
  const saveBtn     = document.getElementById('save-tags-btn');
  const cancelBtn   = document.getElementById('cancel-tags-btn');
  const tagsInput   = document.getElementById('tags-input');
  const tagsDisplay = document.getElementById('tags-display');
  const storageKey  = `playbackPos-${ITEM_ID}`;

  if (!audio) return;

  // — Skip Back / Forward Buttons —
  rewindBtn.addEventListener('click', () => {
    audio.currentTime = Math.max(0, audio.currentTime - 15);
  });
  forwardBtn.addEventListener('click', () => {
    audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 30);
  });

  // — Utility: format mm:ss —
  function fmt(sec) {
    const m = Math.floor(sec / 60);
    const s = String(Math.floor(sec % 60)).padStart(2, '0');
    return `${m}:${s}`;
  }

  // — Build paragraph time‐boundaries —
  let boundaries = [];
  audio.addEventListener('loadedmetadata', () => {
    // restore last playback pos
    const saved = parseFloat(localStorage.getItem(storageKey));
    if (!isNaN(saved)) {
      audio.currentTime = Math.min(saved, audio.duration - 0.1);
    }

    // compute boundaries based on text length
    const lengths = paras.map(p => p.textContent.length);
    const totalLen = lengths.reduce((a, b) => a + b, 0) || 1;
    let acc = 0;
    boundaries = lengths.map(len => {
      const t = (acc / totalLen) * audio.duration;
      acc += len;
      return t;
    });

    totalEl.textContent = fmt(audio.duration);
  });

  // — Update progress & highlight (no bounce) —
  let lastIdx = -1;
  audio.addEventListener('timeupdate', () => {
    const t = audio.currentTime;
    localStorage.setItem(storageKey, t);
    progressBar.value = (t / audio.duration) * 100;
    currentEl.textContent = fmt(t);

    let idx = boundaries.findIndex(b => t <= b);
    if (idx < 0) idx = paras.length - 1;

    if (idx !== lastIdx) {
      paras.forEach((p, i) => {
        const on = i === idx;
        p.classList.toggle('bg-yellow-100', on);
        p.classList.toggle('dark:bg-yellow-800', on);
        p.classList.toggle('p-2', on);
        p.classList.toggle('rounded', on);
      });
      paras[idx].scrollIntoView({ behavior: 'smooth', block: 'center' });
      lastIdx = idx;
    }
  });

  // — Seek by clicking on progress bar —
  progressBar.addEventListener('click', e => {
    const pct = e.offsetX / progressBar.offsetWidth;
    audio.currentTime = pct * audio.duration;
  });

  // — Speed Controls (no <0.8, include 1.1×) —
  const allowedRates = [0.8, 1, 1.1, 1.25, 1.5];
  function setRate(r) {
    audio.playbackRate = r;
    localStorage.setItem('playbackRate', r);
    speedBtns.forEach(b => {
      b.classList.toggle('bg-primary', parseFloat(b.dataset.rate) === r);
    });
  }
  let savedRate = parseFloat(localStorage.getItem('playbackRate')) || 1;
  if (!allowedRates.includes(savedRate)) savedRate = 1;
  setRate(savedRate);
  speedBtns.forEach(b => {
    const r = parseFloat(b.dataset.rate);
    if (!allowedRates.includes(r)) {
      b.remove();
    } else {
      b.addEventListener('click', () => setRate(r));
    }
  });

  // — Tag Editor —
  editBtn.addEventListener('click', () => {
    editor.classList.remove('hidden');
    editBtn.classList.add('hidden');
  });
  cancelBtn.addEventListener('click', () => {
    editor.classList.add('hidden');
    editBtn.classList.remove('hidden');
  });
  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    const tags = tagsInput.value.split(',').map(t => t.trim()).filter(Boolean);

    try {
      const res = await fetch(`/api/items/${ITEM_ID}/tags`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || JSON.stringify(data));

      tagsDisplay.innerHTML = tags.length
        ? tags.map(t => `<span class="bg-gray-200 dark:bg-gray-700 px-2 py-1 rounded text-sm">${t}</span>`).join('')
        : '<span class="text-gray-500">None</span>';

      editor.classList.add('hidden');
      editBtn.classList.remove('hidden');
    } catch (err) {
      alert('Failed to save tags: ' + err.message);
    } finally {
      saveBtn.disabled = false;
    }
  });
});