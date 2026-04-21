(function() {
    let chatPollTimer = null;
    let activeConversationId = 0;

    function clearChatPolling() {
        if (chatPollTimer) {
            window.clearInterval(chatPollTimer);
            chatPollTimer = null;
        }
        activeConversationId = 0;
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatTime(value) {
        if (!value) return '';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '';
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function normalizeImageUrl(imagePath) {
        if (!imagePath) return '';
        const normalized = String(imagePath).replace(/^\/+/, '').replace(/^uploads\//, '');
        return `/static/uploads/${normalized}`;
    }

    function initChatPage() {
        const chatPage = document.querySelector('.chat-page');
        if (!chatPage) {
            clearChatPolling();
            return;
        }

        const conversationId = Number(chatPage.dataset.conversationId || 0);
        if (!conversationId) return;

        clearChatPolling();
        activeConversationId = conversationId;

        const messagesUrl = chatPage.dataset.messagesUrl;
        const sendUrl = chatPage.dataset.sendUrl;
        const currentUserId = Number(chatPage.dataset.currentUserId || 0);

        const chatMessages = document.getElementById('chatMessages');
        const chatForm = document.getElementById('chatForm');
        const imageInput = document.getElementById('imageInput');
        const imagePreview = document.getElementById('imagePreview');
        const messageInput = document.getElementById('messageInput');
        const liveStatus = document.getElementById('chatLiveStatus');

        let latestMessageId = 0;

        function scrollToBottom(force) {
            if (!chatMessages) return;
            const isNearBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < 120;
            if (force || isNearBottom) {
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        }

        function renderMessages(messages, forceScroll) {
            if (!chatMessages) return;

            if (!messages.length) {
                chatMessages.innerHTML = '<div class="chat-empty" id="chatEmptyState"><div class="chat-empty-icon">✉️</div><p>No messages yet. Start the chat.</p></div>';
                latestMessageId = 0;
                return;
            }

            chatMessages.innerHTML = messages.map((message) => {
                const ownClass = message.sender_id === currentUserId ? 'is-own' : 'is-other';
                const imageHtml = message.image_path
                    ? `<img src="${normalizeImageUrl(message.image_path)}" alt="Chat image" class="chat-image">`
                    : '';
                const textHtml = message.content ? `<p class="chat-text">${escapeHtml(message.content)}</p>` : '';
                return `
                    <article class="chat-bubble ${ownClass}" data-message-id="${message.id}">
                        <div class="chat-bubble-inner">
                            ${imageHtml}
                            ${textHtml}
                        </div>
                        <div class="chat-meta"><span>${formatTime(message.created_at)}</span></div>
                    </article>
                `;
            }).join('');

            latestMessageId = messages[messages.length - 1].id || 0;
            scrollToBottom(Boolean(forceScroll));
        }

        async function fetchMessages(silent) {
            if (activeConversationId !== conversationId) return;
            try {
                const response = await fetch(messagesUrl, {
                    credentials: 'same-origin',
                    headers: { 'Accept': 'application/json' }
                });
                if (!response.ok) throw new Error('Failed to fetch messages');

                const data = await response.json();
                const messages = data.messages || [];
                const newestId = messages.length ? messages[messages.length - 1].id : 0;
                const shouldRender = !silent || newestId !== latestMessageId;

                if (shouldRender) {
                    renderMessages(messages, newestId !== latestMessageId);
                }
                if (liveStatus) liveStatus.textContent = 'Live';
            } catch (error) {
                console.error(error);
                if (liveStatus) liveStatus.textContent = 'Reconnecting...';
            }
        }

        function previewSelectedImage(file) {
            if (!imagePreview) return;
            if (!file) {
                imagePreview.innerHTML = '';
                imagePreview.classList.add('hidden');
                return;
            }

            const reader = new FileReader();
            reader.onload = function(e) {
                imagePreview.innerHTML = `<img src="${e.target.result}" alt="Preview"><span class="chat-preview-remove" id="removeChatImage">Remove</span>`;
                imagePreview.classList.remove('hidden');
                const removeBtn = document.getElementById('removeChatImage');
                if (removeBtn) {
                    removeBtn.addEventListener('click', function() {
                        if (imageInput) imageInput.value = '';
                        previewSelectedImage(null);
                    });
                }
            };
            reader.readAsDataURL(file);
        }

        imageInput?.addEventListener('change', function() {
            previewSelectedImage(this.files && this.files[0] ? this.files[0] : null);
        });

        if (messageInput) {
            messageInput.addEventListener('input', function() {
                this.style.height = '46px';
                this.style.height = `${Math.min(this.scrollHeight, 140)}px`;
            });
            window.setTimeout(() => {
                if (document.body.contains(messageInput)) {
                    messageInput.focus();
                }
            }, 20);
        }

        chatForm?.addEventListener('submit', async function(event) {
            event.preventDefault();
            const formData = new FormData(chatForm);
            const messageText = (formData.get('message') || '').toString().trim();
            const imageFile = formData.get('image');

            if (!messageText && !(imageFile && imageFile.name)) {
                return;
            }

            try {
                if (liveStatus) liveStatus.textContent = 'Sending...';

                const response = await fetch(sendUrl, {
                    method: 'POST',
                    body: formData,
                    credentials: 'same-origin',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'Accept': 'application/json'
                    }
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.error || 'Failed to send message');
                }

                chatForm.reset();
                if (messageInput) {
                    messageInput.style.height = '46px';
                }
                previewSelectedImage(null);

                await fetchMessages(false);
                if (liveStatus) liveStatus.textContent = 'Live';
            } catch (error) {
                console.error(error);
                if (liveStatus) liveStatus.textContent = 'Send failed';
            }
        });

        fetchMessages(false);
        chatPollTimer = window.setInterval(function() {
            fetchMessages(true);
        }, 2500);
    }

    document.addEventListener('DOMContentLoaded', initChatPage);
    document.addEventListener('turbo:load', initChatPage);
    document.addEventListener('turbo:before-cache', clearChatPolling);
})();
