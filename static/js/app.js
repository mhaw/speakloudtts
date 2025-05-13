// static/js/app.js

document.addEventListener('DOMContentLoaded', () => {
  const audio       = document.getElementById('audio-player');
  if (!audio) return;

  // Elements
  const paras       = Array.from(document.querySelectorAll('#full-text .paragraph'));
  const progressBar = document.getElementById('audio-progress');
  const currentEl   = document.getElementById('current-time');
  const totalEl     = document.getElementById('total-time');
  const speedBtns   = Array.from(document.querySelectorAll('.speed-btn'));
  const rewindBtn   = document.getElementById('rewind-btn');
  const forwardBtn  = document.getElementById('forward-btn');
  const storageKey  = `playbackPos-${window.location.pathname}`;

  // —— Skip Back / Forward ——————————————————————————————————————
  rewindBtn.addEventListener('click', () => {
    audio.currentTime = Math.max(0, audio.currentTime - 15);
  });
  forwardBtn.addEventListener('click', () => {
    audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 30);
  });

  // —— Speed Controls ————————————————————————————————————————
  const allowedRates = [0.8, 1.0, 1.1, 1.25, 1.5];
  function setSpeed(rate) {
    audio.playbackRate = rate;
    localStorage.setItem('playbackRate', rate);
    speedBtns.forEach(btn => {
      const r = parseFloat(btn.dataset.rate);
      // remove any button not in allowedRates
      if (!allowedRates.includes(r)) {
        btn.remove();
      } else {
        btn.classList.toggle('bg-primary', r === rate);
      }
    });
  }

  // initialize speed
  let savedRate = parseFloat(localStorage.getItem('playbackRate'));
  if (!allowedRates.includes(savedRate)) savedRate = 1.0;
  setSpeed(savedRate);

  // wire buttons
  speedBtns.forEach(btn => {
    const rate = parseFloat(btn.dataset.rate);
    if (allowedRates.includes(rate)) {
      btn.addEventListener('click', () => setSpeed(rate));
    }
  });

  // —— Highlighting & Progress ————————————————————————————————
  let boundaries = [];

  audio.addEventListener('loadedmetadata', () => {
    // restore previous position
    const saved = parseFloat(localStorage.getItem(storageKey));
    if (!isNaN(saved)) audio.currentTime = Math.min(saved, audio.duration - 0.1);

    // compute boundaries solely from paragraph lengths
    const lengths  = paras.map(p => p.textContent.length);
    const totalLen = lengths.reduce((a, b) => a + b, 0) || 1;
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

    // update progress bar & timestamp
    progressBar.value = (t / audio.duration) * 100;
    currentEl.textContent = formatTime(t);

    // highlight the current paragraph
    let idx = boundaries.findIndex(b => t <= b);
    if (idx < 0) idx = paras.length - 1;
    paras.forEach((p, i) => {
      const on = i === idx;
      p.classList.toggle('bg-yellow-100', on);
      p.classList.toggle('dark:bg-yellow-800', on);
      p.classList.toggle('p-2', on);
      p.classList.toggle('rounded', on);
      if (on) p.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  });

  // click-to-seek on the progress bar
  progressBar.addEventListener('click', e => {
    const pct = e.offsetX / progressBar.offsetWidth;
    audio.currentTime = pct * audio.duration;
  });

  function formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = String(Math.floor(sec % 60)).padStart(2, '0');
    return `${m}:${s}`;
  }

  // —— Media Session API —————————————————————————————————————————
  if ('mediaSession' in navigator) {
    const title   = document.querySelector('h1')?.textContent || '';
    const byline  = document.querySelector('p.text-gray-600')?.textContent.replace(/^By\s*/, '') || '';
    const artwork = document.querySelector('img.w-6')?.src;

    navigator.mediaSession.metadata = new MediaMetadata({
      title,
      artist: byline,
      album: 'SpeakLoudTTS',
      artwork: artwork ? [
        { src: artwork, sizes: '96x96',   type: 'image/png' },
        { src: artwork, sizes: '192x192', type: 'image/png' }
      ] : []
    });

    navigator.mediaSession.setActionHandler('play',         () => audio.play());
    navigator.mediaSession.setActionHandler('pause',        () => audio.pause());
    navigator.mediaSession.setActionHandler('seekbackward', () => audio.currentTime = Math.max(0, audio.currentTime - 15));
    navigator.mediaSession.setActionHandler('seekforward',  () => audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 30));
  }
});