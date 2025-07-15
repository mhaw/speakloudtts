// static/js/detail.js
// This file is for item detail page specific javascript.

function showToast(message) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'alert alert-success shadow-lg transition-all duration-300 ease-in-out transform translate-x-full opacity-0';
  toast.innerHTML = `
    <div>
      <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current flex-shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
      <span>${message}</span>
    </div>
  `;
  
  container.appendChild(toast);

  // Animate in
  setTimeout(() => {
    toast.classList.remove('translate-x-full', 'opacity-0');
    toast.classList.add('translate-x-0', 'opacity-100');
  }, 10);

  // Animate out and remove
  setTimeout(() => {
    toast.classList.add('opacity-0');
    toast.addEventListener('transitionend', () => {
      toast.remove();
    });
  }, 3000);
}


document.addEventListener('DOMContentLoaded', () => {
  const audioPlayer = document.getElementById('audio-player');
  const tagsInput = document.getElementById('tags-input');
  const copyBtn = document.getElementById('copy-link-btn');
  const backToTopBtn = document.getElementById('back-to-top');

  // Copy link button handler
  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(window.location.href)
        .then(() => {
          showToast('Link copied to clipboard!');
        })
        .catch(err => {
          console.error('Failed to copy: ', err);
          showToast('Failed to copy link.');
        });
    });
  }

  // Auto-select tags input text on focus
  if (tagsInput) {
    tagsInput.addEventListener('focus', () => {
      tagsInput.select();
    });
  }

  // Back to top button handler
  if (backToTopBtn) {
    window.addEventListener('scroll', () => {
      if (window.scrollY > 200) {
        backToTopBtn.classList.remove('hidden');
      } else {
        backToTopBtn.classList.add('hidden');
      }
    });

    backToTopBtn.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // Keyboard shortcut for audio player
  if (audioPlayer) {
    document.addEventListener('keydown', (e) => {
      // Check if spacebar is pressed and user is not typing in an input
      if (e.code === 'Space' && document.activeElement !== tagsInput) {
        e.preventDefault(); // Prevent page scroll
        if (audioPlayer.paused) {
          audioPlayer.play();
        } else {
          audioPlayer.pause();
        }
      }
    });
  }
});
