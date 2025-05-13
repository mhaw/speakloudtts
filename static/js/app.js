// static/js/app.js
document.addEventListener('DOMContentLoaded', () => {
  const audio       = document.getElementById('audio-player');
  if (!audio) return;

  const paras       = Array.from(document.querySelectorAll('#full-text .paragraph'));
  const progressBar = document.getElementById('audio-progress');
  const currentEl   = document.getElementById('current-time');
  const totalEl     = document.getElementById('total-time');
  const speedBtns   = Array.from(document.querySelectorAll('.speed-btn'));
  const rewindBtn   = document.getElementById('rewind-btn');
  const forwardBtn  = document.getElementById('forward-btn');
  const storageKey  = `playbackPos-${window.location.pathname}`;

  // Skip buttons
  rewindBtn.addEventListener('click', () => {
    audio.currentTime = Math.max(0, audio.currentTime - 15);
  });
  forwardBtn.addEventListener('click', () => {
    audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 30);
  });

  // Speed controls
  const allowedRates = [0.8, 1.0, 1.1, 1.25, 1.5];
  function setSpeed(rate) {
    audio.playbackRate = rate;
    localStorage.setItem('playbackRate', rate);
    speedBtns.forEach(btn => {
      const r = parseFloat(btn.dataset.rate);
      if (!allowedRates.includes(r)) return btn.remove();
      btn.classList.toggle('bg-primary', r === rate);
    });
  }
  let savedRate = parseFloat(localStorage.getItem('playbackRate'));
  if (!allowedRates.includes(savedRate)) savedRate = 1.0;
  setSpeed(savedRate);
  speedBtns.forEach(btn => {
    const r = parseFloat(btn.dataset.rate);
    if (allowedRates.includes(r)) {
      btn.addEventListener('click', () => setSpeed(r));
    }
  });

  // Highlight & progress
  let boundaries = [];
  audio.addEventListener('loadedmetadata', () => {
    // restore pos
    const saved = parseFloat(localStorage.getItem(storageKey));
    if (!isNaN(saved)) audio.currentTime = Math.min(saved, audio.duration - 0.1);

    // compute boundaries
    const lengths  = paras.map(p => p.textContent.length);
    const totalLen = lengths.reduce((a,b) => a+b, 0) || 1;
    let acc = 0;
    boundaries = lengths.map(len => {
      const t = (acc + len) / totalLen * audio.duration;
      acc += len;
      return t;
    });
    totalEl.textContent = formatTime(audio.duration);
  });

  audio.addEventListener('timeupdate', () => {
    const t = audio.currentTime;
    localStorage.setItem(storageKey, t);
    progressBar.value = (t / audio.duration) * 100;
    currentEl.textContent = formatTime(t);

    let idx = boundaries.findIndex(b => t <= b);
    if (idx < 0) idx = paras.length - 1;
    paras.forEach((p,i) => {
      const on = i === idx;
      p.classList.toggle('bg-yellow-100', on);
      p.classList.toggle('dark:bg-yellow-800', on);
      p.classList.toggle('p-2', on);
      p.classList.toggle('rounded', on);
      if (on) p.scrollIntoView({ behavior:'smooth', block:'center' });
    });
  });

  progressBar.addEventListener('click', e => {
    const pct = e.offsetX / progressBar.offsetWidth;
    audio.currentTime = pct * audio.duration;
  });

  function formatTime(sec) {
    const m = Math.floor(sec/60), s = String(Math.floor(sec%60)).padStart(2,'0');
    return `${m}:${s}`;
  }

  // MediaSession
  if ('mediaSession' in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title:   document.querySelector('h1')?.textContent||'',
      artist:  document.querySelector('p.text-gray-600')?.textContent.replace(/^By\s*/,'')||'',
      album:   'SpeakLoudTTS'
    });
    navigator.mediaSession.setActionHandler('play',         () => audio.play());
    navigator.mediaSession.setActionHandler('pause',        () => audio.pause());
    navigator.mediaSession.setActionHandler('seekbackward', () => audio.currentTime = Math.max(0, audio.currentTime-15));
    navigator.mediaSession.setActionHandler('seekforward',  () => audio.currentTime = Math.min(audio.duration||0, audio.currentTime+30));
  }

  // ——— Keyboard shortcuts —————————————————————————————————————
  document.addEventListener('keydown', e => {
    if (!audio) return;
    switch(e.code) {
      case 'Space':
        e.preventDefault();
        audio.paused ? audio.play() : audio.pause();
        break;
      case 'ArrowLeft':
        audio.currentTime = Math.max(0, audio.currentTime - 15);
        break;
      case 'ArrowRight':
        audio.currentTime = Math.min(audio.duration||0, audio.currentTime + 30);
        break;
    }
  });
});