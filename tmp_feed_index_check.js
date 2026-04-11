
function insertReply(postNumber) {
    const textarea = document.getElementById('post-content');
    if (textarea) {
        textarea.value += '>>' + postNumber + '\n';
        textarea.focus();
        textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function scrollToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function scrollToForm() {
    document.getElementById('post-form').scrollIntoView({ behavior: 'smooth' });
}

function scrollToPost(postNumber) {
    const post = document.getElementById('post-' + postNumber);
    if (post) {
        post.scrollIntoView({ behavior: 'smooth', block: 'center' });
        post.style.background = '#ffe4e4';
        setTimeout(() => {
            post.style.background = '';
        }, 2000);
    }
}

function ensureImageViewer() {
    let viewer = document.getElementById('chan-image-viewer');
    if (viewer) return viewer;

    viewer = document.createElement('div');
    viewer.id = 'chan-image-viewer';
    viewer.className = 'chan-image-viewer';
    viewer.innerHTML = '<span class="chan-image-viewer-close" aria-label="Close">&times;</span><img alt="Preview">';
    document.body.appendChild(viewer);

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            viewer.classList.remove('active');
            document.body.style.overflow = '';
        }
    });

    return viewer;
}

function expandImage(img) {
    const viewer = ensureImageViewer();
    const target = viewer.querySelector('img');
    target.src = img.currentSrc || img.src;
    target.alt = img.alt || 'Preview';
    viewer.classList.add('active');
    document.body.style.overflow = 'hidden';

    // Close and restore scroll when tapping outside image.
    viewer.onclick = function(e) {
        if (e.target === viewer || e.target.classList.contains('chan-image-viewer-close')) {
            viewer.classList.remove('active');
            document.body.style.overflow = '';
        }
    }
}

// Handle scroll
document.addEventListener('DOMContentLoaded', function() {
    window.addEventListener('scroll', handleScroll);
});

function handleScroll() {
    const backToTop = document.getElementById('back-to-top');
    if (backToTop) {
        if (window.scrollY > 300) {
            backToTop.classList.add('visible');
        } else {
            backToTop.classList.remove('visible');
        }
    }
}

// Make functions globally available
window.insertReply = insertReply;
window.scrollToPost = scrollToPost;
window.expandImage = expandImage;
window.scrollToForm = scrollToForm;
window.scrollToTop = scrollToTop;

// Handle Enter key in reply textarea (Ctrl+Enter to submit)
document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        const activeElement = document.activeElement;
        if (activeElement && activeElement.classList.contains('chan-textarea')) {
            // Main post form
            activeElement.closest('form').submit();
        }
    }
});

