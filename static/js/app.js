// static/js/app.js
// Original comments about Plyr CSS/JS inclusion can be removed or kept if this file
// is repurposed for other global initializations later.
// For now, its previous functionalities have been moved to more specific files (detail.js, submit.js)
// or were found to be unused in the current context.

document.addEventListener('DOMContentLoaded', () => {
    // All previous Plyr player initialization and event handling code has been removed.
    // This is now handled by static/js/detail.js for the detail page.

    // All previous TomSelect initialization code for #voice-select has been removed.
    // This is now handled by static/js/submit.js for the submit page.

    // The "Edit toggle for extracted-text preview" code has been removed as the
    // targeted elements (#edit-toggle, #extracted-text) and the client-side
    // extraction display/edit flow are not part of the current active features.

    // If there's any other truly global JavaScript initialization that applies to
    // all pages and isn't specific to features like the detail page player or the
    // submit form, it could go here. Otherwise, this file might remain empty.
    
    // console.log('Global app.js loaded. Specific functionalities are in detail.js and submit.js.');
});

// If this file ends up being completely empty (except for comments) after review,
// and you don't foresee adding other global, non-specific JavaScript soon,
// you could consider removing its inclusion from your base template if it was ever included globally.
// However, keeping an empty, named global JS file can be a placeholder for future use.