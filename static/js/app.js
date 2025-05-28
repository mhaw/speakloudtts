// static/js/app.js

// — Make sure you include Plyr’s CSS & JS in your base.html head, e.g.:
// <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/plyr@3/dist/plyr.css" />
// <script src="https://cdn.jsdelivr.net/npm/plyr@3/dist/plyr.polyfilled.min.js"></script>

document.addEventListener('DOMContentLoaded', () => {
  // 1) Initialize Plyr on our audio element
  const plyrPlayer = new Plyr('#audio-player', {
    controls: ['play', 'progress', 'current-time', 'mute', 'volume', 'settings', 'fullscreen'],
    settings: ['speed','quality'],
    speed: { selected: 1, options: [0.8, 1, 1.1, 1.25, 1.5] },
  });

  // 2) Elements & state
  const paras       = Array.from(document.querySelectorAll('#full-text .paragraph'));
  const progressBar = document.getElementById('audio-progress');
  const currentEl   = document.getElementById('current-time');
  const totalEl     = document.getElementById('total-time');
  const storageKey  = `playbackPos-${window.location.pathname}`;

  let boundaries = [], lastIdx = -1;

  // 3) Compute boundaries once metadata is loaded
  plyrPlayer.on('loadedmetadata', () => {
    // restore last play position
    const saved = parseFloat(localStorage.getItem(storageKey));
    if (!isNaN(saved)) plyrPlayer.currentTime = Math.min(saved, plyrPlayer.duration - 0.1);

    // build time boundaries proportional to paragraph length
    const lengths  = paras.map(p => p.textContent.length);
    const totalLen = lengths.reduce((a, b) => a + b, 0) || 1;
    let acc = 0;
    boundaries = lengths.map(len => {
      const t = (acc / totalLen) * plyrPlayer.duration;
      acc += len;
      return t;
    });

    // init progress UI
    totalEl.textContent = formatTime(plyrPlayer.duration);
    progressBar.max      = 100;
  });

  // 4) On timeupdate: highlight, save, update UI
  plyrPlayer.on('timeupdate', () => {
    const t = plyrPlayer.currentTime;
    localStorage.setItem(storageKey, t);
    currentEl.textContent = formatTime(t);
    progressBar.value     = (t / plyrPlayer.duration) * 100;

    // only re-render when idx changes
    let idx = boundaries.findIndex(b => t <= b);
    if (idx < 0) idx = paras.length - 1;
    if (idx !== lastIdx) {
      paras.forEach((p,i) => {
        const on = i===idx;
        p.classList.toggle('bg-yellow-100', on);
        p.classList.toggle('dark:bg-yellow-800', on);
        p.classList.toggle('p-2', on);
        p.classList.toggle('rounded', on);
      });
      paras[idx]?.scrollIntoView({ behavior:'smooth', block:'center' });
      lastIdx = idx;
    }
  });

  // 5) Click-to-seek via custom progress bar
  progressBar.addEventListener('click', e => {
    const pct = e.offsetX / progressBar.offsetWidth;
    plyrPlayer.currentTime = pct * plyrPlayer.duration;
  });

  // 6) Utility: mm:ss formatting
  function formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = String(Math.floor(sec % 60)).padStart(2,'0');
    return `${m}:${s}`;
  }
    // 1) Make the voice dropdown searchable
    if (window.TomSelect) {
      new TomSelect('#voice-select', {
        create: false,
        sortField: { field: 'text', direction: 'asc' }
      });
    }
  
    // 2) Edit toggle for extracted-text preview
    const editBtn = document.getElementById('edit-toggle');
    const textarea = document.getElementById('extracted-text');
    if (editBtn && textarea) {
      editBtn.addEventListener('click', () => {
        textarea.readOnly = !textarea.readOnly;
        textarea.classList.toggle('bg-white');
        textarea.classList.toggle('bg-gray-800');
        editBtn.textContent = textarea.readOnly ? 'Edit Text' : 'Lock Text';
      });
    }
});