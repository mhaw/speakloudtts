// static/js/detail.js
document.addEventListener('DOMContentLoaded', () => {
    // ----- Plyr Player Setup -----
    const audioPlayerElement = document.getElementById('audio-player');
    let player = null;

    // Plyr gracefully optional
    if (window.Plyr && audioPlayerElement) {
        player = new Plyr(audioPlayerElement, {
            controls: [
                'play-large', 'play', 'progress', 'current-time',
                'duration', 'mute', 'volume', 'settings', 'download'
            ],
            settings: ['speed'],
            speed: {
                selected: 1,
                options: [0.8, 1, 1.1, 1.25, 1.5]
            },
            tooltips: { controls: true, seek: true }
        });
        window.speakLoudPlayer = player;
    }

    // ----- Elements -----
    const progressBarContainer = document.getElementById('audio-progress-container');
    const progressBar = document.getElementById('audio-progress');
    const paras = Array.from(document.querySelectorAll('#full-text .paragraph'));
    const currentEl = document.getElementById('current-time');
    const totalEl = document.getElementById('total-time');
    const speedBtns = Array.from(document.querySelectorAll('.speed-btn'));
    const rewindBtn = document.getElementById('rewind-btn');
    const forwardBtn = document.getElementById('forward-btn');

    // Tag Editor
    const editTagsBtn = document.getElementById('edit-tags-btn');
    const tagsEditorDiv = document.getElementById('tags-editor');
    const saveTagsBtn = document.getElementById('save-tags-btn');
    const cancelTagsBtn = document.getElementById('cancel-tags-btn');
    const tagsInput = document.getElementById('tags-input');
    const tagsDisplayDiv = document.getElementById('tags-display');

    // ----- State -----
    let boundaries = [];
    const storageKey = `speakloudtts-playback-time-${window.ITEM_ID}`;
    const allowedPlaybackRates = [0.8, 1, 1.1, 1.25, 1.5];
    let currentParaIdx = -1;

    // ----- Utility -----
    function formatTime(seconds) {
        if (isNaN(seconds) || seconds === Infinity) return '00:00';
        const m = Math.floor(seconds / 60);
        const s = String(Math.floor(seconds % 60)).padStart(2, '0');
        return `${m}:${s}`;
    }

    // ----- Player Logic -----
    if (player) {
        player.on('loadedmetadata', () => {
            const duration = player.duration;
            totalEl.textContent = formatTime(duration);
            // Restore last play position
            const savedTime = parseFloat(localStorage.getItem(storageKey));
            if (!isNaN(savedTime) && savedTime > 0 && savedTime < duration) {
                player.currentTime = Math.min(savedTime, duration - 0.1);
            }
            // Time boundaries for paragraph highlighting
            const lengths = paras.map(p => p.textContent.length);
            const totalLength = lengths.reduce((sum, len) => sum + len, 0) || 1;
            let acc = 0;
            boundaries = lengths.map(len => {
                acc += len;
                return (acc / totalLength) * duration;
            });
        });

        player.on('timeupdate', () => {
            const currentTime = player.currentTime;
            localStorage.setItem(storageKey, currentTime.toString());
            currentEl.textContent = formatTime(currentTime);
            if (progressBar && player.duration > 0) {
                progressBar.style.width = `${(currentTime / player.duration) * 100}%`;
            }
            // Highlight current paragraph
            let newIdx = boundaries.findIndex(boundary => currentTime <= boundary);
            if (newIdx === -1 && currentTime > 0) newIdx = paras.length - 1;
            if (newIdx !== currentParaIdx) {
                paras.forEach((p, i) => {
                    p.classList.toggle('bg-yellow-100', i === newIdx);
                    p.classList.toggle('dark:bg-yellow-800', i === newIdx);
                });
                // Only scroll if playing and on mobile or small screen
                if (paras[newIdx] && player.playing && window.innerWidth <= 640) {
                    paras[newIdx].scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                currentParaIdx = newIdx;
            }
        });

        // Seek with custom progress bar
        if (progressBarContainer) {
            progressBarContainer.addEventListener('click', e => {
                if (player.duration > 0) {
                    const rect = progressBarContainer.getBoundingClientRect();
                    const offsetX = e.clientX - rect.left;
                    player.currentTime = (offsetX / rect.width) * player.duration;
                }
            });
        }

        // Rewind & Forward
        if (rewindBtn) rewindBtn.addEventListener('click', () => player.currentTime = Math.max(0, player.currentTime - 15));
        if (forwardBtn) forwardBtn.addEventListener('click', () => player.currentTime = Math.min(player.duration || 0, player.currentTime + 30));

        // Playback Rate
        function setPlaybackRate(rate) {
            if (allowedPlaybackRates.includes(rate)) {
                player.speed = rate;
                localStorage.setItem('playbackRate', rate.toString());
                speedBtns.forEach(btn => {
                    const btnRate = parseFloat(btn.dataset.rate);
                    btn.classList.toggle('bg-primary', btnRate === rate);
                    btn.classList.toggle('text-white', btnRate === rate);
                    btn.classList.toggle('bg-gray-200', btnRate !== rate);
                    btn.classList.toggle('dark:bg-gray-700', btnRate !== rate);
                });
            }
        }
        speedBtns.forEach(button => {
            const rate = parseFloat(button.dataset.rate);
            if (!allowedPlaybackRates.includes(rate)) {
                button.remove();
                return;
            }
            button.addEventListener('click', () => setPlaybackRate(rate));
        });
        let savedRate = parseFloat(localStorage.getItem('playbackRate')) || 1;
        if (!allowedPlaybackRates.includes(savedRate)) savedRate = 1;
        setTimeout(() => setPlaybackRate(savedRate), 100);
    }

    // ----- Tag Editor Logic -----
    if (editTagsBtn && tagsEditorDiv && saveTagsBtn && cancelTagsBtn && tagsInput && tagsDisplayDiv) {
        // Accessibility: focus trap
        function trapFocus(e) {
            if (tagsEditorDiv.classList.contains('hidden')) return;
            const focusable = [tagsInput, saveTagsBtn, cancelTagsBtn];
            if (!focusable.includes(document.activeElement)) {
                tagsInput.focus();
                e.preventDefault();
            }
        }
        tagsEditorDiv.addEventListener('keydown', e => {
            if (e.key === 'Tab') trapFocus(e);
        });

        editTagsBtn.addEventListener('click', () => {
            tagsEditorDiv.classList.remove('hidden');
            editTagsBtn.classList.add('hidden');
            tagsInput.value = Array.from(tagsDisplayDiv.querySelectorAll('span'))
                .map(span => span.textContent.trim())
                .filter(tag => tag.toLowerCase() !== 'none')
                .join(',');
            tagsInput.focus();
        });

        cancelTagsBtn.addEventListener('click', () => {
            tagsEditorDiv.classList.add('hidden');
            editTagsBtn.classList.remove('hidden');
        });

        saveTagsBtn.addEventListener('click', async () => {
            const newTags = tagsInput.value.split(',').map(t => t.trim()).filter(Boolean);
            saveTagsBtn.disabled = true;
            saveTagsBtn.textContent = 'Saving...';
            try {
                const formData = new FormData();
                formData.append('tags', newTags.join(','));
                const response = await fetch(`/item/${window.ITEM_ID}/tags`, {
                    method: 'POST',
                    body: formData,
                });
                if (!response.ok) throw new Error('Failed to save tags.');
                tagsDisplayDiv.innerHTML = newTags.length > 0
                    ? newTags.map(t => `<span class="bg-gray-200 dark:bg-gray-700 text-sm px-2 py-1 rounded">${t}</span>`).join('')
                    : '<span class="text-gray-500">None</span>';
                tagsEditorDiv.classList.add('hidden');
                editTagsBtn.classList.remove('hidden');
            } catch (err) {
                alert('Error saving tags: ' + err.message);
            } finally {
                saveTagsBtn.disabled = false;
                saveTagsBtn.textContent = 'Save';
            }
        });
    }

    // ----- Keyboard Shortcuts -----
    document.addEventListener('keydown', (e) => {
        // Ignore when editing tags
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
        if (!player) return;
        switch (e.key) {
            case ' ':
            case 'k':
                e.preventDefault();
                player.togglePlay();
                break;
            case 'ArrowLeft':
                if (e.shiftKey && rewindBtn) {
                    e.preventDefault();
                    rewindBtn.click();
                } else if (!e.shiftKey) {
                    e.preventDefault();
                    player.rewind();
                }
                break;
            case 'ArrowRight':
                if (e.shiftKey && forwardBtn) {
                    e.preventDefault();
                    forwardBtn.click();
                } else if (!e.shiftKey) {
                    e.preventDefault();
                    player.forward();
                }
                break;
            case 'm':
                e.preventDefault();
                player.muted = !player.muted;
                break;
        }
    });

    // ----- Debug -----
    console.log('SpeakLoudTTS detail page script initialized.');
});