
        // Global error handler to catch any JavaScript errors
        window.onerror = function(msg, url, lineNo, columnNo, error) {
            console.error('Global error:', msg, 'at line', lineNo);
            return false;
        };
        
        // Preloader management - Flash-like instant loading
        (function() {
            const preloader = document.getElementById('preloader');
            const preloadBar = document.getElementById('preloadBar');
            const gameContainer = document.getElementById('gameContainer');
            
            // Simulate asset loading (since we use emojis, this is instant)
            let progress = 0;
            const loadInterval = setInterval(() => {
                progress += 20;
                preloadBar.style.width = progress + '%';
                
                if (progress >= 100) {
                    clearInterval(loadInterval);
                    // Hide preloader and show game
                    setTimeout(() => {
                        preloader.style.opacity = '0';
                        gameContainer.style.opacity = '1';
                        setTimeout(() => {
                            preloader.style.display = 'none';
                        }, 500);
                    }, 200);
                }
            }, 50);
        })();
        
        // Game constants
        const ROUND_SECONDS = 240;
        const POLL_INTERVAL_MS = 850;
        const REMATCH_PREP_SECONDS = 3;

        // Game State - Optimized for instant response
        const state = {
            selectedBet: null,
            inQueue: false,
            inGame: false,
            canSelectCard: false,
            selectingCard: false,
            selectedCard: null,
            gameState: null,
            pollInterval: null,
            pollInFlight: false,
            currentRound: 1,
            isRematch: false,
            inSuspense: false,
            suspenseTimeout: null,
            resultData: null,
            lastResultKey: null,
            preparingMatch: false
        };

        function formatBalance(amount) {
            if (amount >= 10000000) {
                return (amount / 1000000).toFixed(1) + 'M';
            } else if (amount >= 1000000) {
                return Math.floor(amount / 1000000) + 'M';
            } else if (amount >= 100000) {
                return Math.floor(amount / 1000) + 'K';
            }
            return Number(amount || 0).toLocaleString();
        }

        // Confetti effect for wins
        function createConfetti() {
            const container = document.createElement('div');
            container.className = 'confetti-container';
            document.body.appendChild(container);
            
            const colors = ['#ffd700', '#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7', '#dfe6e9', '#fd79a8'];
            
            for (let i = 0; i < 100; i++) {
                const confetti = document.createElement('div');
                confetti.className = 'confetti';
                confetti.style.left = Math.random() * 100 + '%';
                confetti.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
                confetti.style.animationDelay = Math.random() * 2 + 's';
                confetti.style.animationDuration = (Math.random() * 2 + 2) + 's';
                confetti.style.width = (Math.random() * 8 + 6) + 'px';
                confetti.style.height = (Math.random() * 8 + 6) + 'px';
                container.appendChild(confetti);
            }
            
            // Remove container after animation
            setTimeout(() => {
                container.remove();
            }, 4000);
        }

        // Card Info
        const CARD_INFO = {
            king: { emoji: '👑', name: 'KING', class: 'king' },
            people: { emoji: '👥', name: 'PEOPLE', class: 'people' },
            slave: { emoji: '⛓️', name: 'SLAVE', class: 'slave' }
        };

        // DOM Elements
        const elements = {
            lobbyScreen: document.getElementById('lobbyScreen'),
            gameScreen: document.getElementById('gameScreen'),
            matchmakingOverlay: document.getElementById('matchmakingOverlay'),
            suspenseOverlay: document.getElementById('suspenseOverlay'),
            resultModal: document.getElementById('resultModal'),
            playBtn: document.getElementById('playBtn'),
            cancelMatchBtn: document.getElementById('cancelMatchBtn'),
            rematchBtn: document.getElementById('rematchBtn'),
            leaveBtn: document.getElementById('leaveBtn'),
            balance: document.getElementById('balance'),
            roundNum: document.getElementById('roundNum'),
            betAmount: document.getElementById('betAmount'),
            timerFill: document.getElementById('timerFill'),
            myCard: document.getElementById('myCard'),
            myCardName: document.getElementById('myCardName'),
            opponentCard: document.getElementById('opponentCard'),
            opponentCardName: document.getElementById('opponentCardName'),
            opponentLabel: document.getElementById('opponentLabel'),
            gameStatus: document.getElementById('gameStatus'),
            resultBanner: document.getElementById('resultBanner'),
            resultAmount: document.getElementById('resultAmount'),
            resultButtons: document.getElementById('resultButtons'),
            waitingText: document.getElementById('waitingText'),
            potAmount: document.getElementById('potAmount'),
            suspenseCountdown: document.getElementById('suspenseCountdown'),
            suspenseMyEmoji: document.getElementById('suspenseMyEmoji'),
            suspenseOppEmoji: document.getElementById('suspenseOppEmoji')
        };
        const handCards = document.querySelectorAll('.hand-card');

        function setHandEnabled(enabled) {
            handCards.forEach(c => {
                if (enabled) {
                    c.classList.remove('disabled');
                } else {
                    c.classList.add('disabled');
                }
            });
        }

        function setRoundTimerFromSecondsLeft(secondsLeft) {
            const safeLeft = Math.max(0, Math.min(ROUND_SECONDS, Number(secondsLeft) || 0));
            const percentage = (safeLeft / ROUND_SECONDS) * 100;
            elements.timerFill.style.width = percentage + '%';
        }

        function setPreparingTimer(secondsLeft) {
            const rawLeft = Number(secondsLeft);
            const baseLeft = Number.isFinite(rawLeft) ? rawLeft : REMATCH_PREP_SECONDS;
            const safeLeft = Math.max(0, Math.min(REMATCH_PREP_SECONDS, baseLeft));
            const progressPct = ((REMATCH_PREP_SECONDS - safeLeft) / REMATCH_PREP_SECONDS) * 100;
            elements.timerFill.style.width = progressPct + '%';
        }

        // Bet Selection
        document.querySelectorAll('.bet-option').forEach(option => {
            option.addEventListener('click', () => {
                document.querySelectorAll('.bet-option').forEach(o => o.classList.remove('selected'));
                option.classList.add('selected');
                state.selectedBet = parseInt(option.dataset.amount);
                
                // Check balance - handle M (million) and K (thousand) formats
                let balanceText = elements.balance.textContent;
                let balance = 0;
                if (balanceText.includes('M')) {
                    balance = parseFloat(balanceText.replace(/[^0-9.]/g, '')) * 1000000;
                } else if (balanceText.includes('K')) {
                    balance = parseFloat(balanceText.replace(/[^0-9.]/g, '')) * 1000;
                } else {
                    balance = parseInt(balanceText.replace(/,/g, ''));
                }
                
                if (balance >= state.selectedBet) {
                    elements.playBtn.disabled = false;
                } else {
                    elements.playBtn.disabled = true;
                }
            });
        });

        // Play Button
        elements.playBtn.addEventListener('click', async () => {
            if (!state.selectedBet) return;
            
            try {
                const response = await fetch('{{ url_for("game.join_queue") }}', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: 'bet=' + state.selectedBet
                });
                
                const data = await response.json();
                
                if (data.success) {
                    state.inQueue = true;
                    elements.matchmakingOverlay.classList.add('active');
                    startPolling();
                } else {
                    alert(data.message || 'Failed to join queue');
                }
            } catch (err) {
                console.error('Error joining queue:', err);
                alert('Failed to join queue');
            }
        });

        // Cancel Match
        elements.cancelMatchBtn.addEventListener('click', async () => {
            try {
                await fetch('{{ url_for("game.leave_queue") }}', {
                    method: 'POST'
                });
                
                state.inQueue = false;
                elements.matchmakingOverlay.classList.remove('active');
                stopPolling();
            } catch (err) {
                console.error('Error leaving queue:', err);
            }
        });

        // Card Selection
        handCards.forEach(card => {
            card.addEventListener('click', async () => {
                // Allow selection if in game and card not already selected for THIS round
                if (!state.inGame || !state.canSelectCard || state.selectingCard) return;
                
                // Prevent changing card if already selected in this round
                if (state.selectedCard) {
                    return;
                }
                
                // Check with server if we can still select (hand wasn't disabled)
                const cardType = card.dataset.card;
                
                // Update UI immediately for instant feedback
                state.selectingCard = true;
                state.selectedCard = cardType;
                state.canSelectCard = false;
                
                // Disable all hand cards
                setHandEnabled(false);
                card.classList.add('selected');
                
                // Update the played card display
                elements.myCard.textContent = CARD_INFO[cardType].emoji;
                elements.myCard.className = 'game-card ' + CARD_INFO[cardType].class;
                elements.myCard.classList.add('revealed');
                elements.myCardName.textContent = CARD_INFO[cardType].name;
                
                elements.gameStatus.textContent = 'Card selected! Waiting for opponent...';
                
                // Send to server
                try {
                    const response = await fetch('{{ url_for("game.select_card") }}', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                        },
                        body: 'card=' + cardType
                    });
                    
                    const data = await response.json();
                    if (!data.success) {
                        state.selectedCard = null;
                        state.canSelectCard = true;
                        setHandEnabled(true);
                        handCards.forEach(c => c.classList.remove('selected'));
                        elements.myCard.textContent = '❓';
                        elements.myCard.className = 'game-card';
                        elements.myCardName.textContent = 'Select card';
                        elements.gameStatus.textContent = data.message || 'Select your card to play!';
                    } else if (data.status) {
                        handleGameState(data);
                    }
                } catch (err) {
                    console.error('Error selecting card:', err);
                    state.selectedCard = null;
                    state.canSelectCard = true;
                    setHandEnabled(true);
                    handCards.forEach(c => c.classList.remove('selected'));
                    elements.myCard.textContent = '❓';
                    elements.myCard.className = 'game-card';
                    elements.myCardName.textContent = 'Select card';
                    elements.gameStatus.textContent = 'Failed to submit card. Try again.';
                } finally {
                    state.selectingCard = false;
                }
            });
        });

        // REMATCH Button - Wait for both players to confirm
        elements.rematchBtn.addEventListener('click', async () => {
            // Disable the button immediately to prevent double-click
            elements.rematchBtn.disabled = true;
            elements.rematchBtn.textContent = 'WAITING...';
            elements.rematchBtn.classList.add('waiting');
            
            // Show waiting text
            elements.waitingText.style.display = 'block';
            elements.waitingText.textContent = 'Waiting for opponent to confirm...';
            
            try {
                // Call rematch endpoint - this will track that WE want to rematch
                const response = await fetch('{{ url_for("game.rematch") }}', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    }
                });
                
                const data = await response.json();
                
                if (data.success) {
                    // The server will tell us if:
                    // - We're waiting for opponent (status: waiting_rematch)
                    // - Both confirmed and game starting (status: waiting_rematch_start)
                    // - Error occurred
                    
                    if (data.status === 'waiting_rematch') {
                        // We clicked first - wait for opponent
                        elements.rematchBtn.textContent = 'WAITING...';
                        elements.waitingText.style.display = 'block';
                        elements.waitingText.textContent = 'Waiting for opponent to confirm...';
                    } else if (data.status === 'waiting_rematch_start') {
                        // Both confirmed - game is about to start
                        state.preparingMatch = true;
                        hideResult();
                        elements.gameStatus.textContent = 'PREPARING MATCH...';
                        setPreparingTimer(data.seconds_left);
                    } else if (data.message && data.message.includes('Insufficient balance')) {
                        // Not enough coins
                        elements.rematchBtn.disabled = false;
                        elements.rematchBtn.textContent = 'FIGHT AGAIN';
                        elements.rematchBtn.classList.remove('waiting');
                        elements.waitingText.style.display = 'block';
                        elements.waitingText.textContent = 'Insufficient balance!';
                    }
                } else {
                    // Error
                    elements.rematchBtn.disabled = false;
                    elements.rematchBtn.textContent = 'FIGHT AGAIN';
                    elements.rematchBtn.classList.remove('waiting');
                    alert(data.message || 'Failed to request rematch');
                }
            } catch (err) {
                console.error('Error requesting rematch:', err);
                elements.rematchBtn.disabled = false;
                elements.rematchBtn.textContent = 'FIGHT AGAIN';
                elements.rematchBtn.classList.remove('waiting');
            }
        });

        // Leave Button
        elements.leaveBtn.addEventListener('click', async () => {
            await leaveGameAfterResult();
        });

        async function leaveGameAfterResult() {
            try {
                await fetch('{{ url_for("game.leave_game") }}', {
                    method: 'POST'
                });
            } catch (err) {
                console.error('Error leaving game:', err);
            }
            
            // Stop polling to prevent further updates
            stopPolling();
            state.inGame = false;
            state.inQueue = false;
            
            hideResult();
            showLobby();
        }

        // Polling Functions
        function startPolling() {
            if (state.pollInterval) return;
            pollGameState();
            state.pollInterval = setInterval(pollGameState, POLL_INTERVAL_MS);
        }

        function stopPolling() {
            if (state.pollInterval) {
                clearInterval(state.pollInterval);
                state.pollInterval = null;
            }
        }

        async function pollGameState() {
            if (state.pollInFlight) return;
            state.pollInFlight = true;
            try {
                const response = await fetch('{{ url_for("game.game_state") }}', { cache: 'no-store' });
                const data = await response.json();

                // Check if still in queue or game (status 'waiting' means in queue)
                if (data.status === 'idle') {
                    // Not in any game or queue - return to lobby
                    if (state.inGame || state.inQueue) {
                        state.inGame = false;
                        state.inQueue = false;
                        elements.matchmakingOverlay.classList.remove('active');
                        stopPolling();
                        showLobby();
                    }
                    return;
                }

                if (data.status === 'waiting') {
                    state.inQueue = true;
                    elements.matchmakingOverlay.classList.add('active');
                    return;
                }
                
                handleGameState(data);
            } catch (err) {
                console.error('Error polling game state:', err);
            } finally {
                state.pollInFlight = false;
            }
        }

        function handleGameState(data) {
            // Check if matched - new fresh match starting
            if (data.status === 'matched' || data.status === 'waiting_rematch' || 
                data.status === 'waiting_rematch_start' || data.status === 'result' ||
                data.status === 'rematch_expired' || data.status === 'opponent_left') {
                
                if (!state.inGame && data.status !== 'opponent_left') {
                    // Starting a fresh game - completely reset UI
                    state.inGame = true;
                    elements.matchmakingOverlay.classList.remove('active');
                    
                    // Complete reset before showing game
                    resetGameUIForNewMatch();
                    showGame(data);
                } else if (data.status === 'waiting_rematch_start') {
                    // New round preparing state.
                    if (!state.preparingMatch) {
                        hideResult();
                        resetGameUI();
                        elements.roundNum.textContent = data.round || 1;
                        state.currentRound = data.round || 1;
                        state.lastResultKey = null;
                        state.preparingMatch = true;
                    }
                }
                
                // Update game UI
                updateGameUI(data);
            }
            
            // Update balance
            if (data.balance !== undefined) {
                elements.balance.textContent = formatBalance(data.balance);
            }
        }

        function showGame(data) {
            elements.lobbyScreen.classList.remove('active');
            elements.gameScreen.classList.add('active');
            
            elements.opponentLabel.textContent = data.opponent_name || 'OPPONENT';
            elements.roundNum.textContent = data.round || 1;
            state.currentRound = data.round || 1;
            state.isRematch = false;
            state.lastResultKey = null;
            state.preparingMatch = false;
            elements.betAmount.textContent = formatBalance(data.bet || 0);
            
            // Update pot display - show double the bet (2 players x bet amount)
            const pot = data.pot || (data.bet * 2);
            elements.potAmount.textContent = formatBalance(pot);
            
            resetGameUI();
            const initialLeft = data.time_left !== undefined ? Number(data.time_left) : ROUND_SECONDS;
            setRoundTimerFromSecondsLeft(initialLeft);
        }

        function updateGameUI(data) {
            // Check if opponent left - auto leave
            if (data.status === 'opponent_left') {
                // Show opponent left message before auto-leaving
                elements.resultBanner.textContent = 'OPPONENT LEFT';
                elements.resultBanner.className = 'result-banner lose';
                elements.resultAmount.textContent = 'Game ended. Returning to lobby...';
                elements.resultButtons.style.display = 'none';
                elements.waitingText.style.display = 'none';
                elements.resultModal.classList.add('active');
                
                // Auto-leave after 2 seconds
                setTimeout(() => {
                    hideResult();
                    showLobby();
                }, 2000);
                return;
            }
            
            // Update timer
            if (data.time_left !== undefined) {
                setRoundTimerFromSecondsLeft(data.time_left);
            }
            
            // Detect if entering rematch (round incremented)
            if (data.round !== undefined && data.round > state.currentRound) {
                state.isRematch = true;
                state.currentRound = data.round;
                state.lastResultKey = null;
                // Fresh start for new round - reset all cards
                resetGameUI();
            }
            
            // Update card states
            if (data.status === 'matched' && !data.your_selected) {
                state.preparingMatch = false;
                state.selectedCard = null;
                state.canSelectCard = true;
                setHandEnabled(true);
                handCards.forEach(c => c.classList.remove('selected'));
                elements.gameStatus.textContent = 'Select your card to play!';
            } else if (data.status === 'matched' && data.your_selected) {
                state.preparingMatch = false;
                state.canSelectCard = false;
                setHandEnabled(false);
            } else {
                state.canSelectCard = false;
                setHandEnabled(false);
            }
            
            if (data.opponent_selected) {
                elements.opponentCard.textContent = '❓';
                elements.gameStatus.textContent = 'Opponent has chosen!';
            }
            
            // Show result
            if (data.status === 'result') {
                const resultKey = `${data.round || 0}:${data.resolved_at || 0}:${data.outcome || 'draw'}`;
                if (state.lastResultKey !== resultKey) {
                    state.lastResultKey = resultKey;
                    showResult(data);
                }
            }
            
            if (data.status === 'waiting_rematch') {
                elements.resultModal.style.display = 'flex';
                elements.resultModal.classList.add('active');
                elements.resultButtons.style.display = 'flex';
                elements.waitingText.style.display = 'block';
                if (data.rematch_requested_by_you) {
                    elements.rematchBtn.disabled = true;
                    elements.rematchBtn.textContent = 'WAITING...';
                    elements.rematchBtn.classList.add('waiting');
                    elements.waitingText.textContent = 'Waiting for opponent to confirm...';
                } else {
                    elements.rematchBtn.disabled = false;
                    elements.rematchBtn.textContent = 'FIGHT AGAIN';
                    elements.rematchBtn.classList.remove('waiting');
                    elements.waitingText.textContent = 'Your enemy wants to fight again.';
                }
            }

            if (data.status === 'waiting_rematch_start') {
                state.preparingMatch = true;
                elements.gameStatus.textContent = 'PREPARING MATCH...';
                setPreparingTimer(data.seconds_left);
                hideResult();
                elements.resultButtons.style.display = 'none';
                elements.waitingText.style.display = 'none';
            }
            
            if (data.status === 'rematch_expired') {
                state.preparingMatch = false;
                elements.gameStatus.textContent = 'Request expired';
                
                // Show fight again/leave buttons again
                elements.resultBanner.textContent = 'TIME EXPIRED';
                elements.resultBanner.className = 'result-banner draw';
                elements.resultAmount.textContent = 'Time limit exceeded';
                elements.rematchBtn.disabled = false;
                elements.rematchBtn.textContent = 'FIGHT AGAIN';
                elements.rematchBtn.classList.remove('waiting');
                elements.resultButtons.style.display = 'flex';
                elements.waitingText.style.display = 'none';
                elements.resultModal.style.display = 'flex';
                elements.resultModal.classList.add('active');
            }
        }

        function resetGameUI() {
            state.selectedCard = null;
            state.selectingCard = false;
            state.canSelectCard = false;
            
            // Clear suspense state if active
            if (state.inSuspense) {
                state.inSuspense = false;
                elements.suspenseOverlay.classList.remove('active');
                elements.suspenseOverlay.style.display = 'none';
                if (state.suspenseTimeout) {
                    clearTimeout(state.suspenseTimeout);
                    state.suspenseTimeout = null;
                }
            }
            
            // Reset my card display
            elements.myCard.textContent = '❓';
            elements.myCard.className = 'game-card';
            elements.myCardName.textContent = 'Select card';
            
            // Reset opponent card display
            elements.opponentCard.textContent = '❓';
            elements.opponentCard.className = 'game-card';
            elements.opponentCardName.textContent = 'Waiting';
            
            elements.gameStatus.textContent = 'Select your card to play!';
            hideResult();
            elements.rematchBtn.disabled = false;
            elements.rematchBtn.textContent = 'FIGHT AGAIN';
            elements.rematchBtn.classList.remove('waiting');
            elements.waitingText.style.display = 'none';
            elements.waitingText.textContent = '';
            
            // Remove lose shake effect
            document.getElementById('gameContainer').classList.remove('lose-shake');
            
            // Remove any confetti
            const existingConfetti = document.querySelector('.confetti-container');
            if (existingConfetti) existingConfetti.remove();
            
            // Re-enable all hand cards for selection
            handCards.forEach(c => {
                c.classList.remove('disabled', 'selected', 'match-effect');
            });
            setHandEnabled(false);
        }

        // Reset completely for new match (fresh start)
        function resetGameUIForNewMatch() {
            state.selectedCard = null;
            state.currentRound = 1;
            state.selectingCard = false;
            state.canSelectCard = false;
            
            // Clear suspense state if active
            if (state.inSuspense) {
                state.inSuspense = false;
                elements.suspenseOverlay.classList.remove('active');
                elements.suspenseOverlay.style.display = 'none';
                if (state.suspenseTimeout) {
                    clearTimeout(state.suspenseTimeout);
                    state.suspenseTimeout = null;
                }
            }
            
            // Complete reset of all card displays
            elements.myCard.textContent = '❓';
            elements.myCard.className = 'game-card';
            elements.myCardName.textContent = 'Select card';
            
            elements.opponentCard.textContent = '❓';
            elements.opponentCard.className = 'game-card';
            elements.opponentCardName.textContent = 'Waiting';
            elements.opponentLabel.textContent = 'OPPONENT';
            
            elements.gameStatus.textContent = 'Select your card to play!';
            hideResult();
            elements.rematchBtn.disabled = false;
            elements.rematchBtn.textContent = 'FIGHT AGAIN';
            elements.rematchBtn.classList.remove('waiting');
            elements.waitingText.style.display = 'none';
            elements.waitingText.textContent = '';
            
            // Reset round
            elements.roundNum.textContent = '1';
            
            // Reset timer
            elements.timerFill.style.width = '100%';
            
            // Clear all effects
            elements.myCard.classList.remove('winner', 'loser', 'draw-result', 'match-effect');
            elements.opponentCard.classList.remove('winner', 'loser', 'draw-result', 'match-effect');
            
            // Remove lose shake effect
            document.getElementById('gameContainer').classList.remove('lose-shake');
            
            // Remove any confetti
            const existingConfetti = document.querySelector('.confetti-container');
            if (existingConfetti) existingConfetti.remove();
            
            // Re-enable all hand cards
            handCards.forEach(c => {
                c.classList.remove('disabled', 'selected', 'match-effect');
            });
            setHandEnabled(false);
        }

        function showResult(data) {
            // Store the result data for later use
            state.resultData = data;
            
            // If already in suspense, don't start another one
            if (state.inSuspense) {
                return;
            }
            
            // Start suspense phase - 3 second delay before showing result
            startSuspensePhase(data);
        }
        
        // NEW: Suspense phase function - shows suspense overlay for 3 seconds
        function startSuspensePhase(data) {
            // Prevent multiple suspense phases
            if (state.inSuspense) {
                return;
            }
            
            state.inSuspense = true;
            
            // Update suspense overlay with player's card (the one they selected)
            if (data.your_card && CARD_INFO[data.your_card]) {
                elements.suspenseMyEmoji.textContent = CARD_INFO[data.your_card].emoji;
            } else {
                elements.suspenseMyEmoji.textContent = '?';
            }
            
            // Hide opponent's card during suspense
            elements.suspenseOppEmoji.textContent = '?';
            
            // Show suspense overlay - force display first
            elements.suspenseOverlay.style.display = 'flex';
            elements.suspenseOverlay.classList.add('active');
            
            // Start countdown
            let countdown = 3;
            elements.suspenseCountdown.textContent = countdown;
            
            const countdownInterval = setInterval(() => {
                countdown--;
                if (countdown > 0) {
                    elements.suspenseCountdown.textContent = countdown;
                    // Add pulse effect on each number change
                    elements.suspenseCountdown.style.animation = 'none';
                    elements.suspenseCountdown.offsetHeight; // Trigger reflow
                    elements.suspenseCountdown.style.animation = 'countdownPulse 1s ease-in-out infinite';
                } else {
                    clearInterval(countdownInterval);
                }
            }, 1000);
            
            // After 3 seconds, show the actual result
            state.suspenseTimeout = setTimeout(() => {
                // Hide suspense overlay
                elements.suspenseOverlay.classList.remove('active');
                elements.suspenseOverlay.style.display = 'none';
                state.inSuspense = false;
                
                // Now show the actual result
                showResultInternal(data);
            }, 3000);
        }
        
        // NEW: Internal function to show result after suspense
        function showResultInternal(data) {
            // Clear previous modal effects
            elements.resultModal.classList.remove('win-effect', 'lose-effect', 'draw-effect');
            
            // Remove any existing confetti
            const existingConfetti = document.querySelector('.confetti-container');
            if (existingConfetti) existingConfetti.remove();
            
            // Remove screen shake from container
            document.getElementById('gameContainer').classList.remove('lose-shake');
            
            // Force show the modal
            elements.resultModal.style.display = 'flex';
            elements.resultModal.classList.add('active');
            
            const outcome = data.outcome;
            const coinChange = Number(data.coin_change || 0);
            
            // Clear previous effects
            elements.myCard.classList.remove('winner', 'loser', 'draw-result', 'match-effect');
            elements.opponentCard.classList.remove('winner', 'loser', 'draw-result', 'match-effect');
            
            if (outcome === 'win') {
                // Add win effect to modal
                elements.resultModal.classList.add('win-effect');
                
                // Create confetti for win!
                setTimeout(() => {
                    createConfetti();
                }, 300);
                
                elements.resultBanner.textContent = 'YOU WIN!';
                elements.resultBanner.className = 'result-banner win';
                const winAmount = coinChange > 0 ? coinChange : (data.bet || 0);
                const feeAmount = Number(data.platform_fee || 0);
                if (feeAmount > 0) {
                    elements.resultAmount.innerHTML = '+' + formatBalance(winAmount) + ' 🪙 <span style="font-size: 0.5rem; color: #888;">(fee -' + formatBalance(feeAmount) + ')</span>';
                } else {
                    elements.resultAmount.textContent = '+' + formatBalance(winAmount) + ' 🪙';
                }
                
                // Add win effect to my card
                setTimeout(() => {
                    elements.myCard.classList.add('winner', 'match-effect');
                }, 100);
                
                // Add lose effect to opponent card
                elements.opponentCard.classList.add('loser');
            } else if (outcome === 'lose') {
                // Add lose effect to modal
                elements.resultModal.classList.add('lose-effect');
                
                // Add screen shake to container
                setTimeout(() => {
                    document.getElementById('gameContainer').classList.add('lose-shake');
                }, 100);
                
                elements.resultBanner.textContent = 'YOU LOSE';
                elements.resultBanner.className = 'result-banner lose';
                const loseAmount = coinChange < 0 ? Math.abs(coinChange) : (data.bet || 0);
                elements.resultAmount.textContent = '-' + formatBalance(loseAmount) + ' 🪙';
                
                // Add lose effect to my card
                elements.myCard.classList.add('loser');
                
                // Add win effect to opponent card
                setTimeout(() => {
                    elements.opponentCard.classList.add('winner', 'match-effect');
                }, 100);
            } else {
                // Draw effect
                elements.resultModal.classList.add('draw-effect');
                
                elements.resultBanner.textContent = 'DRAW!';
                elements.resultBanner.className = 'result-banner draw';
                elements.resultAmount.textContent = '0 🪙 (no coin change)';
                
                // Add draw effect to both cards
                setTimeout(() => {
                    elements.myCard.classList.add('draw-result', 'match-effect');
                    elements.opponentCard.classList.add('draw-result', 'match-effect');
                }, 100);
            }
            
            // Show card results with animation
            if (data.your_card) {
                const myCardInfo = CARD_INFO[data.your_card];
                elements.myCard.textContent = myCardInfo.emoji;
                elements.myCard.className = 'game-card ' + myCardInfo.class + ' revealed';
elements.myCardName.textContent = myCardInfo.name;
            } else {
                // No card data - show blank
                elements.myCard.textContent = '❓';
                elements.myCard.className = 'game-card';
                elements.myCardName.textContent = 'No card';
            }
            
            if (data.opponent_card) {
                const oppCardInfo = CARD_INFO[data.opponent_card];
                elements.opponentCard.textContent = oppCardInfo.emoji;
                elements.opponentCard.className = 'game-card ' + oppCardInfo.class + ' revealed';
                elements.opponentCardName.textContent = oppCardInfo.name;
            } else {
                // No card data - show blank
                elements.opponentCard.textContent = '❓';
                elements.opponentCard.className = 'game-card';
                elements.opponentCardName.textContent = 'No card';
            }
            
            // Show only stable buttons: FIGHT AGAIN and LEAVE.
            elements.resultButtons.style.display = 'flex';
            elements.rematchBtn.disabled = false;
            elements.rematchBtn.textContent = 'FIGHT AGAIN';
            elements.rematchBtn.classList.remove('waiting');
            elements.waitingText.style.display = 'none';
            elements.waitingText.textContent = '';
        }

        function showLobby() {
            // Clear suspense state if active
            if (state.inSuspense) {
                state.inSuspense = false;
                elements.suspenseOverlay.classList.remove('active');
                elements.suspenseOverlay.style.display = 'none';
                if (state.suspenseTimeout) {
                    clearTimeout(state.suspenseTimeout);
                    state.suspenseTimeout = null;
                }
            }
            
            // Remove lose shake effect
            document.getElementById('gameContainer').classList.remove('lose-shake');
            
            // Remove any confetti
            const existingConfetti = document.querySelector('.confetti-container');
            if (existingConfetti) existingConfetti.remove();
            
            elements.lobbyScreen.classList.add('active');
            elements.gameScreen.classList.remove('active');
            state.inGame = false;
            state.canSelectCard = false;
            state.selectingCard = false;
            state.selectedCard = null;
            state.currentRound = 1;
            state.isRematch = false;
            state.lastResultKey = null;
            state.preparingMatch = false;
            hideResult();
            stopPolling();
            
            // Refresh balance
            fetchGameState();
        }

        function hideResult() {
            elements.resultModal.classList.remove('active');
            elements.resultModal.style.display = 'none';
            elements.resultModal.classList.remove('win-effect', 'lose-effect', 'draw-effect');
        }

        async function fetchGameState() {
            try {
                const response = await fetch('{{ url_for("game.game_state") }}', { cache: 'no-store' });
                const data = await response.json();
                
                if (data.balance !== undefined) {
                    elements.balance.textContent = data.balance.toLocaleString();
                }

                // Recover queue/game state after refresh.
                if (data.status === 'waiting') {
                    state.inQueue = true;
                    elements.matchmakingOverlay.classList.add('active');
                    startPolling();
                    return;
                }

                if (data.status && data.status !== 'idle') {
                    state.inGame = true;
                    elements.matchmakingOverlay.classList.remove('active');
                    handleGameState(data);
                    startPolling();
                }
                
                // Update play button state
                if (state.selectedBet) {
                    const balance = data.balance || 0;
                    elements.playBtn.disabled = balance < state.selectedBet;
                }
            } catch (err) {
                console.error('Error fetching game state:', err);
            }
        }

        // Initial load
        fetchGameState();
    
