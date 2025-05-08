document.addEventListener('DOMContentLoaded', () => {
    const audio = document.getElementById('audio-player');
    if (!audio) return;
  
    // 1) Inject skip-back/forward buttons into the controls area
    const controlsWrapper = audio.parentElement;
    const btnClasses = ['px-2','py-1','bg-gray-200','rounded','dark:bg-gray-700','text-sm','mr-2','hover:bg-gray-300','dark:hover:bg-gray-600'];
    
    const skipBack = document.createElement('button');
    skipBack.id = 'skip-back';
    skipBack.textContent = '« 15s';
    skipBack.classList.add(...btnClasses);
    skipBack.addEventListener('click', () => {
      audio.currentTime = Math.max(0, audio.currentTime - 15);
    });
  
    const skipForward = document.createElement('button');
    skipForward.id = 'skip-forward';
    skipForward.textContent = '30s »';
    skipForward.classList.add(...btnClasses);
    skipForward.addEventListener('click', () => {
      audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 30);
    });
  
    // place them right above the progress bar
    controlsWrapper.insertBefore(skipBack, controlsWrapper.querySelector('progress'));
    controlsWrapper.insertBefore(skipForward, controlsWrapper.querySelector('progress'));
  
    // 2) Media Session API for lock-screen / Android/iOS controls
    if ('mediaSession' in navigator) {
      const title = document.querySelector('h1')?.textContent || '';
      const byline = document.querySelector('p.text-gray-600')?.textContent.replace(/^By\s*/,'') || '';
      const artworkUrl = document.querySelector('img.w-6')?.src || '';
  
      navigator.mediaSession.metadata = new MediaMetadata({
        title,
        artist: byline,
        album: 'SpeakLoudTTS',
        artwork: artworkUrl ? [
          { src: artworkUrl, sizes: '96x96',   type: 'image/png' },
          { src: artworkUrl, sizes: '192x192', type: 'image/png' },
        ] : []
      });
  
      // action handlers
      navigator.mediaSession.setActionHandler('play',     () => audio.play());
      navigator.mediaSession.setActionHandler('pause',    () => audio.pause());
      navigator.mediaSession.setActionHandler('seekbackward', () => {
        audio.currentTime = Math.max(0, audio.currentTime - 15);
      });
      navigator.mediaSession.setActionHandler('seekforward',  () => {
        audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 30);
      });
      // optional: skip tracks if you add podcast playlist in future
      navigator.mediaSession.setActionHandler('previoustrack', null);
      navigator.mediaSession.setActionHandler('nexttrack',     null);
    }
  });