/**
 * Interview Comfort Manager
 * Provides pause/resume, break timers, emotional support prompts, and progress tracking
 */

class InterviewComfortManager {
    constructor(app) {
        this.app = app;
        this.isPaused = false;
        this.pauseStartTime = null;
        this.totalPauseDuration = 0;
        this.breakTimerInterval = null;
        this.breakReminderMinutes = 15; // Suggest break every 15 minutes
        this.lastBreakReminder = Date.now();
        this.interviewStartTime = null;
        this.breaksTaken = [];
        
        // Emotional support prompts
        this.supportPrompts = [
            { trigger: 'distress', messages: [
                "Take your time. There's no rush here.",
                "It's okay to feel emotional. We can pause whenever you need.",
                "You're doing great. Would you like to take a short break?",
                "I understand this is difficult. Your comfort matters."
            ]},
            { trigger: 'confusion', messages: [
                "Let me rephrase that question for you.",
                "There are no wrong answers here. Just share what you remember.",
                "We can come back to this question later if you'd like."
            ]},
            { trigger: 'fatigue', messages: [
                "We've been talking for a while. How about a 5-minute break?",
                "You've provided a lot of helpful information. Let's take a breather.",
                "Would you like some water? We can pause here."
            ]},
            { trigger: 'encouragement', messages: [
                "That's very helpful information. Thank you.",
                "You're doing an excellent job remembering the details.",
                "These details are valuable for understanding what happened."
            ]}
        ];
        
        this.initializeUI();
        this.initializeBreakTimer();
    }
    
    initializeUI() {
        // Create comfort control panel if it doesn't exist
        const panel = document.getElementById('interview-comfort-panel');
        if (!panel) return;
        
        // Bind event listeners
        const pauseBtn = document.getElementById('comfort-pause-btn');
        const breakBtn = document.getElementById('comfort-break-btn');
        const supportBtn = document.getElementById('comfort-support-btn');
        
        if (pauseBtn) {
            pauseBtn.addEventListener('click', () => this.togglePause());
        }
        if (breakBtn) {
            breakBtn.addEventListener('click', () => this.startBreak());
        }
        if (supportBtn) {
            supportBtn.addEventListener('click', () => this.showSupportPrompt('encouragement'));
        }
        
        // Initialize duration display
        this.updateDurationDisplay();
    }
    
    initializeBreakTimer() {
        // Check every minute if a break reminder is needed
        this.breakTimerInterval = setInterval(() => {
            if (this.isPaused) return;
            
            const timeSinceLastBreak = (Date.now() - this.lastBreakReminder) / 1000 / 60;
            if (timeSinceLastBreak >= this.breakReminderMinutes) {
                this.showBreakReminder();
                this.lastBreakReminder = Date.now();
            }
        }, 60000);
    }
    
    startInterview() {
        this.interviewStartTime = Date.now();
        this.totalPauseDuration = 0;
        this.breaksTaken = [];
        this.lastBreakReminder = Date.now();
        this.updateDurationDisplay();
    }
    
    togglePause() {
        if (this.isPaused) {
            this.resumeInterview();
        } else {
            this.pauseInterview();
        }
    }
    
    pauseInterview() {
        this.isPaused = true;
        this.pauseStartTime = Date.now();
        
        // Update UI
        const pauseBtn = document.getElementById('comfort-pause-btn');
        if (pauseBtn) {
            pauseBtn.innerHTML = '▶️ Resume';
            pauseBtn.classList.add('paused');
        }
        
        // Show pause overlay
        this.showPauseOverlay();
        
        // Disable input controls
        this.setInputsEnabled(false);
        
        // Notify backend
        this.notifyPauseState(true);
        
        // Update status
        this.updateStatus('Interview Paused');
    }
    
    resumeInterview() {
        if (this.pauseStartTime) {
            const pauseDuration = Date.now() - this.pauseStartTime;
            this.totalPauseDuration += pauseDuration;
            
            // Record break if longer than 30 seconds
            if (pauseDuration > 30000) {
                this.breaksTaken.push({
                    start: new Date(this.pauseStartTime).toISOString(),
                    duration: Math.round(pauseDuration / 1000)
                });
            }
        }
        
        this.isPaused = false;
        this.pauseStartTime = null;
        
        // Update UI
        const pauseBtn = document.getElementById('comfort-pause-btn');
        if (pauseBtn) {
            pauseBtn.innerHTML = '⏸️ Pause';
            pauseBtn.classList.remove('paused');
        }
        
        // Hide pause overlay
        this.hidePauseOverlay();
        
        // Re-enable input controls
        this.setInputsEnabled(true);
        
        // Notify backend
        this.notifyPauseState(false);
        
        // Update status
        this.updateStatus('Interview Resumed');
        
        // Reset break reminder
        this.lastBreakReminder = Date.now();
    }
    
    startBreak(duration = 5) {
        this.pauseInterview();
        
        // Show break modal with timer
        this.showBreakModal(duration);
    }
    
    showBreakModal(durationMinutes) {
        let modal = document.getElementById('break-timer-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'break-timer-modal';
            modal.className = 'modal break-timer-modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <h2>☕ Taking a Break</h2>
                    </div>
                    <div class="break-timer-content">
                        <div class="break-timer-display">
                            <span id="break-timer-minutes">05</span>:<span id="break-timer-seconds">00</span>
                        </div>
                        <p class="break-message">Take a moment to relax. The interview will be here when you're ready.</p>
                        <div class="break-tips">
                            <p>💧 Stay hydrated</p>
                            <p>🚶 Stretch your legs</p>
                            <p>🧘 Take deep breaths</p>
                        </div>
                    </div>
                    <div class="modal-actions">
                        <button class="btn btn-secondary" id="extend-break-btn">+5 min</button>
                        <button class="btn btn-primary" id="end-break-btn">I'm Ready to Continue</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
            
            document.getElementById('extend-break-btn').addEventListener('click', () => {
                this.extendBreak(5);
            });
            document.getElementById('end-break-btn').addEventListener('click', () => {
                this.endBreak();
            });
        }
        
        modal.classList.remove('hidden');
        this.startBreakTimer(durationMinutes);
    }
    
    startBreakTimer(minutes) {
        let remainingSeconds = minutes * 60;
        
        const updateDisplay = () => {
            const mins = Math.floor(remainingSeconds / 60);
            const secs = remainingSeconds % 60;
            
            const minsEl = document.getElementById('break-timer-minutes');
            const secsEl = document.getElementById('break-timer-seconds');
            
            if (minsEl) minsEl.textContent = mins.toString().padStart(2, '0');
            if (secsEl) secsEl.textContent = secs.toString().padStart(2, '0');
        };
        
        updateDisplay();
        
        if (this.breakCountdown) clearInterval(this.breakCountdown);
        
        this.breakCountdown = setInterval(() => {
            remainingSeconds--;
            updateDisplay();
            
            if (remainingSeconds <= 0) {
                clearInterval(this.breakCountdown);
                this.playBreakEndSound();
            }
        }, 1000);
    }
    
    extendBreak(minutes) {
        const minsEl = document.getElementById('break-timer-minutes');
        const secsEl = document.getElementById('break-timer-seconds');
        
        if (minsEl && secsEl) {
            const currentMins = parseInt(minsEl.textContent) || 0;
            const currentSecs = parseInt(secsEl.textContent) || 0;
            const totalSecs = (currentMins + minutes) * 60 + currentSecs;
            
            if (this.breakCountdown) clearInterval(this.breakCountdown);
            
            let remainingSeconds = totalSecs;
            
            const updateDisplay = () => {
                const mins = Math.floor(remainingSeconds / 60);
                const secs = remainingSeconds % 60;
                minsEl.textContent = mins.toString().padStart(2, '0');
                secsEl.textContent = secs.toString().padStart(2, '0');
            };
            
            updateDisplay();
            
            this.breakCountdown = setInterval(() => {
                remainingSeconds--;
                updateDisplay();
                
                if (remainingSeconds <= 0) {
                    clearInterval(this.breakCountdown);
                    this.playBreakEndSound();
                }
            }, 1000);
        }
    }
    
    endBreak() {
        if (this.breakCountdown) {
            clearInterval(this.breakCountdown);
        }
        
        const modal = document.getElementById('break-timer-modal');
        if (modal) {
            modal.classList.add('hidden');
        }
        
        this.resumeInterview();
    }
    
    playBreakEndSound() {
        // Gentle notification that break time is up
        if (this.app && this.app.sounds && this.app.sounds.notification) {
            this.app.sounds.notification.play().catch(() => {});
        }
    }
    
    showBreakReminder() {
        if (this.isPaused) return;
        
        // Show a gentle reminder in the chat
        this.addComfortMessage(
            "You've been at this for a while. Would you like to take a short break?",
            'break-reminder'
        );
    }
    
    showSupportPrompt(trigger, customMessage = null) {
        let message = customMessage;
        
        if (!message) {
            const promptGroup = this.supportPrompts.find(p => p.trigger === trigger);
            if (promptGroup) {
                const messages = promptGroup.messages;
                message = messages[Math.floor(Math.random() * messages.length)];
            }
        }
        
        if (message) {
            this.addComfortMessage(message, 'support');
        }
    }
    
    addComfortMessage(text, type = 'general') {
        const chatTranscript = document.getElementById('chat-transcript');
        if (!chatTranscript) return;
        
        const msgDiv = document.createElement('div');
        msgDiv.className = `chat-message comfort-message comfort-${type}`;
        msgDiv.innerHTML = `
            <div class="message-avatar comfort-avatar">💚</div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-sender">Wellness Support</span>
                </div>
                <div class="message-text">${text}</div>
                ${type === 'break-reminder' ? `
                    <div class="comfort-actions">
                        <button class="btn btn-sm btn-secondary" onclick="window.app.comfortManager?.startBreak(5)">Take a 5-min break</button>
                        <button class="btn btn-sm btn-secondary" onclick="this.closest('.comfort-message').remove()">I'm okay</button>
                    </div>
                ` : ''}
            </div>
        `;
        
        chatTranscript.appendChild(msgDiv);
        chatTranscript.scrollTop = chatTranscript.scrollHeight;
    }
    
    showPauseOverlay() {
        let overlay = document.getElementById('pause-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'pause-overlay';
            overlay.className = 'pause-overlay';
            overlay.innerHTML = `
                <div class="pause-content">
                    <div class="pause-icon">⏸️</div>
                    <h2>Interview Paused</h2>
                    <p>Take your time. Click Resume when you're ready to continue.</p>
                    <div class="pause-timer">
                        <span>Paused for: </span>
                        <span id="pause-duration">0:00</span>
                    </div>
                    <button class="btn btn-primary btn-lg" id="overlay-resume-btn">▶️ Resume Interview</button>
                </div>
            `;
            document.body.appendChild(overlay);
            
            document.getElementById('overlay-resume-btn').addEventListener('click', () => {
                this.resumeInterview();
            });
        }
        
        overlay.classList.remove('hidden');
        this.startPauseDurationTimer();
    }
    
    hidePauseOverlay() {
        const overlay = document.getElementById('pause-overlay');
        if (overlay) {
            overlay.classList.add('hidden');
        }
        
        if (this.pauseDurationInterval) {
            clearInterval(this.pauseDurationInterval);
        }
    }
    
    startPauseDurationTimer() {
        const durationEl = document.getElementById('pause-duration');
        if (!durationEl) return;
        
        if (this.pauseDurationInterval) {
            clearInterval(this.pauseDurationInterval);
        }
        
        this.pauseDurationInterval = setInterval(() => {
            if (this.pauseStartTime) {
                const elapsed = Math.floor((Date.now() - this.pauseStartTime) / 1000);
                const mins = Math.floor(elapsed / 60);
                const secs = elapsed % 60;
                durationEl.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
            }
        }, 1000);
    }
    
    setInputsEnabled(enabled) {
        const micBtn = document.getElementById('mic-btn');
        const sendBtn = document.getElementById('send-btn');
        const textInput = document.getElementById('text-input');
        const chatMicBtn = document.getElementById('chat-mic-btn');
        
        if (micBtn) micBtn.disabled = !enabled;
        if (sendBtn) sendBtn.disabled = !enabled;
        if (textInput) textInput.disabled = !enabled;
        if (chatMicBtn) chatMicBtn.disabled = !enabled;
    }
    
    updateStatus(message) {
        const statusText = document.getElementById('status-text');
        if (statusText) {
            statusText.textContent = message;
        }
    }
    
    updateDurationDisplay() {
        const durationEl = document.getElementById('interview-duration-display');
        if (!durationEl || !this.interviewStartTime) return;
        
        const elapsed = Date.now() - this.interviewStartTime - this.totalPauseDuration;
        const mins = Math.floor(elapsed / 1000 / 60);
        const secs = Math.floor((elapsed / 1000) % 60);
        
        durationEl.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
    }
    
    getProgress() {
        const activeDuration = this.interviewStartTime 
            ? Date.now() - this.interviewStartTime - this.totalPauseDuration 
            : 0;
            
        return {
            isPaused: this.isPaused,
            totalDuration: Math.round(activeDuration / 1000),
            totalPauseDuration: Math.round(this.totalPauseDuration / 1000),
            breaksTaken: this.breaksTaken.length,
            breakDetails: this.breaksTaken
        };
    }
    
    async notifyPauseState(paused) {
        // Notify backend of pause state
        if (!this.app || !this.app.sessionId) return;
        
        try {
            await fetch(`/api/sessions/${this.app.sessionId}/comfort/pause`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    paused,
                    timestamp: new Date().toISOString()
                })
            });
        } catch (e) {
            console.warn('Failed to notify pause state:', e);
        }
    }
    
    async getEmotionalSupportPrompt(context) {
        // Get AI-generated emotional support prompt based on context
        if (!this.app || !this.app.sessionId) return null;
        
        try {
            const response = await fetch(`/api/sessions/${this.app.sessionId}/comfort/support`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ context })
            });
            
            if (response.ok) {
                const data = await response.json();
                return data.prompt;
            }
        } catch (e) {
            console.warn('Failed to get support prompt:', e);
        }
        
        // Fallback to local prompts
        return null;
    }
    
    detectDistress(messageText) {
        // Simple keyword detection for distress signals
        const distressKeywords = [
            'sorry', 'i can\'t', 'i don\'t know', 'upset', 'scared',
            'nervous', 'anxious', 'hard to remember', 'difficult',
            'traumatic', 'overwhelmed', 'confused'
        ];
        
        const lowerText = messageText.toLowerCase();
        const hasDistress = distressKeywords.some(kw => lowerText.includes(kw));
        
        if (hasDistress) {
            this.showSupportPrompt('distress');
        }
        
        return hasDistress;
    }
    
    destroy() {
        if (this.breakTimerInterval) {
            clearInterval(this.breakTimerInterval);
        }
        if (this.breakCountdown) {
            clearInterval(this.breakCountdown);
        }
        if (this.pauseDurationInterval) {
            clearInterval(this.pauseDurationInterval);
        }
    }
}

// Export for use in app.js
window.InterviewComfortManager = InterviewComfortManager;
