
function scrollToPost(postNumber) {
    const post = document.getElementById('post-' + postNumber);
    if (!post) return;
    post.scrollIntoView({ behavior: 'smooth', block: 'center' });
    post.style.background = '#ffe4e4';
    setTimeout(() => {
        post.style.background = '';
    }, 1800);
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

    viewer.onclick = function(e) {
        if (e.target === viewer || e.target.classList.contains('chan-image-viewer-close')) {
            viewer.classList.remove('active');
            document.body.style.overflow = '';
        }
    }
}

function resetReplyTarget() {
    const parentInput = document.getElementById('reply-parent-id');
    const label = document.getElementById('reply-target-label');
    parentInput.value = '{{ post.id }}';
    label.textContent = 'Reply target: Thread No.{{ post.post_number or post.id }}';
}

function setReplyTarget(parentId, postNumber, authorName) {
    const parentInput = document.getElementById('reply-parent-id');
    const label = document.getElementById('reply-target-label');
    const textarea = document.getElementById('reply-content');

    parentInput.value = parentId;
    label.textContent = 'Reply target: ' + authorName + ' / No.' + postNumber;

    const mention = '>>' + postNumber + '\n';
    if (!textarea.value.includes(mention)) {
        textarea.value = mention + textarea.value;
    }
    textarea.focus();
    document.getElementById('reply-form').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.thread-reply-link[data-parent-id]').forEach(btn => {
        btn.addEventListener('click', function() {
            setReplyTarget(
                this.getAttribute('data-parent-id'),
                this.getAttribute('data-post-number'),
                this.getAttribute('data-author-name')
            );
        });
    });

    const urlParams = new URLSearchParams(window.location.search);
    const replyTo = urlParams.get('reply_to');
    if (replyTo) {
        setTimeout(() => scrollToPost(replyTo), 300);
    }
});

