// static/js/detail.js
document.addEventListener('DOMContentLoaded', () => {
    const audioPlayerElement = document.getElementById('audio-player');
    if (!audioPlayerElement) {
        console.error('Audio player element (#audio-player) not found.');
        return;
    }

    // --- 1. Initialize Plyr Player ---
    const player = new Plyr(audioPlayerElement, {
        // Consider making controls more extensive if desired
        controls: [
            'play-large', 'play', 'progress', 'current-time',
            'duration', 'mute', 'volume', 'settings', 'download'
        ],
        settings: ['speed'], // Enable speed controls in the settings menu
        speed: {
            selected: 1,
            // Ensure these options match the data-rate attributes of your speed buttons
            options: [0.8, 1, 1.1, 1.25, 1.5] 
        },
        tooltips: { controls: true, seek: true },
        // Plyr's default seekTime is 10s. Our buttons are custom.
    });

    // Expose player to global scope for debugging or if other scripts need it
    window.speakLoudPlayer = player;

    // --- 2. Elements & State ---
    const progressBarContainer = document.getElementById('audio-progress-container');
    const progressBar = document.getElementById('audio-progress');
    const paras = Array.from(document.querySelectorAll('#full-text .paragraph'));
    const currentEl = document.getElementById('current-time');
    const totalEl = document.getElementById('total-time');
    const speedBtns = Array.from(document.querySelectorAll('.speed-btn'));
    const rewindBtn = document.getElementById('rewind-btn');
    const forwardBtn = document.getElementById('forward-btn');

    // Tag Editor Elements
    const editTagsBtn = document.getElementById('edit-tags-btn');
    const tagsEditorDiv = document.getElementById('tags-editor');
    const saveTagsBtn = document.getElementById('save-tags-btn');
    const cancelTagsBtn = document.getElementById('cancel-tags-btn');
    const tagsInput = document.getElementById('tags-input');
    const tagsDisplayDiv = document.getElementById('tags-display');

    let boundaries = []; // Time boundaries for paragraph highlighting
    const storageKey = `speakloudtts-playback-time-${ITEM_ID}`; // ITEM_ID is global
    const allowedPlaybackRates = [0.8, 1, 1.1, 1.25, 1.5]; // Should match Plyr options & buttons
    let currentParaIdx = -1;

    // --- 3. Utility Functions ---
    function formatTime(seconds) {
        if (isNaN(seconds) || seconds === Infinity) {
            return '00:00';
        }
        const m = Math.floor(seconds / 60);
        const s = String(Math.floor(seconds % 60)).padStart(2, '0');
        return `${m}:${s}`;
    }

    // --- 4. Player Event Handling & Logic ---

    // Build boundaries once metadata is loaded
    player.on('loadedmetadata', () => {
        const duration = player.duration;
        if (!duration || duration === Infinity) {
            totalEl.textContent = '00:00';
            console.warn('Audio duration not available or invalid.');
            return;
        }

        totalEl.textContent = formatTime(duration);

        // Restore last play position
        const savedTime = parseFloat(localStorage.getItem(storageKey));
        if (!isNaN(savedTime) && savedTime > 0 && savedTime < duration) {
            player.currentTime = Math.min(savedTime, duration - 0.1);
        }

        // Build time boundaries proportional to paragraph length
        // Note: This assumes paragraphs in #full-text correspond to TTS segments.
        // If #full-text shows a preview, highlighting accuracy may be affected.
        const lengths = paras.map(p => p.textContent.length);
        const totalLength = lengths.reduce((sum, len) => sum + len, 0) || 1; // Avoid division by zero

        let accumulatedLength = 0;
        boundaries = lengths.map(len => {
            accumulatedLength += len;
            return (accumulatedLength / totalLength) * duration;
        });
        console.log('Paragraph boundaries calculated:', boundaries);
    });

    // On timeupdate: highlight, save, update UI
    player.on('timeupdate', () => {
        const currentTime = player.currentTime;
        if (isNaN(currentTime)) return;

        localStorage.setItem(storageKey, currentTime.toString());
        currentEl.textContent = formatTime(currentTime);
        
        if (progressBar && player.duration > 0) {
            const progressPercent = (currentTime / player.duration) * 100;
            progressBar.style.width = `${progressPercent}%`;
        }

        // Only re-render highlight when paragraph index changes
        let newIdx = boundaries.findIndex(boundary => currentTime <= boundary);
        if (newIdx === -1 && currentTime > 0) newIdx = paras.length -1; // If past all boundaries, highlight last

        if (newIdx !== currentParaIdx) {
            paras.forEach((p, i) => {
                const isActive = (i === newIdx);
                p.classList.toggle('bg-yellow-100', isActive);
                p.classList.toggle('dark:bg-yellow-800', isActive);
                // Add/remove other active styles if needed
                // p.classList.toggle('p-2', isActive); 
                // p.classList.toggle('rounded', isActive);
            });
            if (paras[newIdx] && player.playing) { // Only scroll if playing
                paras[newIdx].scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            currentParaIdx = newIdx;
        }
    });

    // Click-to-seek via custom progress bar
    if (progressBarContainer) {
        progressBarContainer.addEventListener('click', (e) => {
            if (player.duration > 0) {
                const rect = progressBarContainer.getBoundingClientRect();
                const offsetX = e.clientX - rect.left;
                const newTime = (offsetX / rect.width) * player.duration;
                player.currentTime = newTime;
            }
        });
    }
    
    // --- 5. Control Button Logic ---

    // Rewind & Forward Buttons
    if (rewindBtn) {
        rewindBtn.addEventListener('click', () => {
            player.currentTime = Math.max(0, player.currentTime - 15);
        });
    }
    if (forwardBtn) {
        forwardBtn.addEventListener('click', () => {
            player.currentTime = Math.min(player.duration || 0, player.currentTime + 30);
        });
    }

    // Speed Control Buttons
    function setPlaybackRate(rate) {
        if (allowedPlaybackRates.includes(rate)) {
            player.speed = rate; // Plyr uses 'speed' property
            localStorage.setItem('playbackRate', rate.toString());
            speedBtns.forEach(btn => {
                const btnRate = parseFloat(btn.dataset.rate);
                btn.classList.toggle('bg-primary', btnRate === rate); // Primary style for active rate
                btn.classList.toggle('text-white', btnRate === rate); // White text for active rate
                btn.classList.toggle('bg-gray-200', btnRate !== rate);
                btn.classList.toggle('dark:bg-gray-700', btnRate !== rate);
            });
            console.log('Playback rate set to:', rate);
        }
    }

    speedBtns.forEach(button => {
        const rate = parseFloat(button.dataset.rate);
        if (!allowedPlaybackRates.includes(rate)) {
            button.remove(); // Remove buttons for unsupported rates
            return;
        }
        button.addEventListener('click', () => setPlaybackRate(rate));
    });

    // Initialize playback rate from localStorage or default
    let savedRate = parseFloat(localStorage.getItem('playbackRate')) || 1;
    if (!allowedPlaybackRates.includes(savedRate)) {
        savedRate = 1;
    }
    // Apply initial rate after a short delay to ensure Plyr is ready
    setTimeout(() => setPlaybackRate(savedRate), 100);


    // --- 6. Tag Editor Logic ---
    if (editTagsBtn && tagsEditorDiv && saveTagsBtn && cancelTagsBtn && tagsInput && tagsDisplayDiv) {
        editTagsBtn.addEventListener('click', () => {
            tagsEditorDiv.classList.remove('hidden');
            editTagsBtn.classList.add('hidden');
            tagsInput.value = Array.from(tagsDisplayDiv.querySelectorAll('span'))
                                .map(span => span.textContent.trim())
                                .filter(tag => tag.toLowerCase() !== 'none') // Exclude "None" placeholder
                                .join(',');
            tagsInput.focus();
        });

        cancelTagsBtn.addEventListener('click', () => {
            tagsEditorDiv.classList.add('hidden');
            editTagsBtn.classList.remove('hidden');
        });

        saveTagsBtn.addEventListener('click', async () => {
            const newTags = tagsInput.value.split(',')
                .map(t => t.trim())
                .filter(Boolean); // Remove empty tags

            saveTagsBtn.disabled = true;
            saveTagsBtn.textContent = 'Saving...';

            try {
                const response = await fetch(`/api/items/${ITEM_ID}/tags`, { // ITEM_ID is global
                    method: 'PUT', // Or POST, depending on your API design
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                        // Add CSRF token header if needed
                    },
                    body: JSON.stringify({ tags: newTags })
                });

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || 'Failed to save tags.');
                }

                // Update displayed tags
                tagsDisplayDiv.innerHTML = newTags.length > 0
                    ? newTags.map(t => `<span class="bg-gray-200 dark:bg-gray-700 text-sm px-2 py-1 rounded">${t}</span>`).join('')
                    : '<span class="text-gray-500">None</span>';
                
                tagsEditorDiv.classList.add('hidden');
                editTagsBtn.classList.remove('hidden');
                // alert('Tags saved successfully!'); // Optional success message

            } catch (err) {
                console.error('Error saving tags:', err);
                alert('Error saving tags: ' + err.message);
            } finally {
                saveTagsBtn.disabled = false;
                saveTagsBtn.textContent = 'Save';
            }
        });
    } else {
        console.warn('Tag editor elements not fully found. Tag editing will be disabled.');
    }

    // --- 7. Keyboard Shortcuts ---
    document.addEventListener('keydown', (e) => {
        // Ignore if typing in an input field (like tags editor)
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) {
            return;
        }

        switch (e.key) {
            case ' ': // Space bar for play/pause
            case 'k': // 'k' for play/pause (YouTube style)
                e.preventDefault();
                player.togglePlay();
                break;
            case 'ArrowLeft':
                if (e.shiftKey && rewindBtn) { // Shift + Left Arrow for custom rewind
                    e.preventDefault();
                    rewindBtn.click();
                } else if (!e.shiftKey) { // Left Arrow for Plyr's default seek back
                    e.preventDefault();
                    player.rewind(); // Uses Plyr's seekTime (default 10s)
                }
                break;
            case 'ArrowRight':
                if (e.shiftKey && forwardBtn) { // Shift + Right Arrow for custom forward
                    e.preventDefault();
                    forwardBtn.click();
                } else if (!e.shiftKey) { // Right Arrow for Plyr's default seek forward
                     e.preventDefault();
                    player.forward(); // Uses Plyr's seekTime (default 10s)
                }
                break;
            case 'm': // 'm' for mute/unmute
                e.preventDefault();
                player.muted = !player.muted;
                break;
            // Add more shortcuts if needed (e.g., for speed, fullscreen)
        }
    });

    console.log('SpeakLoudTTS detail page script initialized.');
});