/**
 * WitnessReplay - UI Utilities Module
 * Handles toasts, modals, onboarding, keyboard shortcuts, sound effects
 */

class UIManager {
    constructor() {
        this.toastContainer = document.getElementById('toast-container');
        this.sounds = {
            sceneGenerated: null,
            micClick: null,
            notification: null
        };
        this.soundEnabled = true;
        this._suppressToasts = true; // suppress toasts during initial app load
        setTimeout(() => { this._suppressToasts = false; }, 4000);
        this.initSounds();
        this.initKeyboardShortcuts();
        this.checkOnboarding();
    }
    
    // ==================== TOAST NOTIFICATIONS ====================
    showToast(message, type = 'info', duration = 3000) {
        // Suppress toasts during initial app load to avoid notification spam
        if (this._suppressToasts && type !== 'error') return null;

        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.style.cssText = 'position:fixed;top:10px;right:10px;z-index:99999;display:flex;flex-direction:column;gap:8px;max-width:350px;pointer-events:none;';
            document.body.appendChild(container);
        }
        // Limit to 3 visible toasts
        while (container.children.length >= 3) {
            container.firstChild.remove();
        }
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.style.cssText = 'pointer-events:auto;';
        
        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };
        
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || icons.info}</span>
            <span class="toast-message">${message}</span>
            <button class="toast-close" aria-label="Close">&times;</button>
        `;
        
        container.appendChild(toast);
        
        // Close button
        toast.querySelector('.toast-close').addEventListener('click', () => {
            this.removeToast(toast);
        });
        
        // Auto remove
        if (duration > 0) {
            setTimeout(() => this.removeToast(toast), duration);
        }
        
        // Play sound
        if (type === 'success' || type === 'info') {
            this.playSound('notification');
        }
        
        return toast;
    }
    
    removeToast(toast) {
        toast.style.animation = 'toastSlideIn 0.3s ease-out reverse';
        setTimeout(() => {
            if (toast.parentElement) {
                toast.remove();
            }
        }, 300);
    }
    
    // ==================== SOUND EFFECTS ====================
    initSounds() {
        // Create simple audio context for sound effects
        this.audioContext = null;
        
        // We'll use Web Audio API to generate simple tones
        // For production, load actual sound files
    }
    
    playSound(soundType) {
        if (!this.soundEnabled) return;
        
        try {
            if (!this.audioContext) {
                this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            
            const oscillator = this.audioContext.createOscillator();
            const gainNode = this.audioContext.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(this.audioContext.destination);
            
            // Different sounds for different events
            switch (soundType) {
                case 'sceneGenerated':
                    oscillator.frequency.value = 800;
                    gainNode.gain.value = 0.1;
                    break;
                case 'micClick':
                    oscillator.frequency.value = 400;
                    gainNode.gain.value = 0.05;
                    break;
                case 'notification':
                    oscillator.frequency.value = 600;
                    gainNode.gain.value = 0.05;
                    break;
            }
            
            oscillator.start();
            oscillator.stop(this.audioContext.currentTime + 0.1);
        } catch (error) {
            // Silently fail if audio not supported
        }
    }
    
    toggleSound() {
        this.soundEnabled = !this.soundEnabled;
        this.showToast(
            `Sound effects ${this.soundEnabled ? 'enabled' : 'disabled'}`,
            'info',
            2000
        );
        return this.soundEnabled;
    }
    
    // ==================== KEYBOARD SHORTCUTS ====================
    initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Don't trigger shortcuts when typing in input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                return;
            }
            
            switch (e.key) {
                case ' ':
                    e.preventDefault();
                    const micBtn = document.getElementById('mic-btn');
                    if (micBtn && !micBtn.disabled) {
                        micBtn.click();
                    }
                    break;
                    
                case 'Escape':
                    e.preventDefault();
                    // Stop recording if active
                    if (window.app && window.app.isRecording) {
                        window.app.stopRecording();
                    }
                    // Close modals
                    this.closeAllModals();
                    break;
                    
                case '?':
                    e.preventDefault();
                    this.showOnboarding();
                    break;
                    
                case 'n':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        document.getElementById('new-session-btn')?.click();
                    }
                    break;
                    
                case 's':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        document.getElementById('sessions-list-btn')?.click();
                    }
                    break;
            }
        });
    }
    
    // ==================== ONBOARDING ====================
    checkOnboarding() {
        const completed = localStorage.getItem('witnessreplay-onboarding-completed');
        if (!completed) {
            // Show onboarding after a brief delay
            setTimeout(() => this.showOnboarding(), 1000);
        }
    }
    
    showOnboarding() {
        const overlay = document.getElementById('onboarding-overlay');
        if (overlay) {
            overlay.classList.remove('hidden');
            // Reset to first step
            window.currentOnboardingStep = 1;
            document.querySelectorAll('.onboarding-step').forEach((step, index) => {
                step.classList.toggle('active', index === 0);
            });
        }
    }
    
    // ==================== MODALS ====================
    showModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            this._previousFocus = document.activeElement;
            modal.classList.remove('hidden');
            modal.style.display = 'flex';
            modal.setAttribute('aria-hidden', 'false');
            // Focus the modal content for keyboard users
            const focusTarget = modal.querySelector('.modal-content, [tabindex="-1"]') || modal;
            requestAnimationFrame(() => focusTarget.focus?.());
            // Trap focus inside modal
            this._trapFocusHandler = (e) => this._trapFocus(e, modal);
            modal.addEventListener('keydown', this._trapFocusHandler);
        }
    }
    
    hideModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('hidden');
            modal.setAttribute('aria-hidden', 'true');
            if (this._trapFocusHandler) {
                modal.removeEventListener('keydown', this._trapFocusHandler);
                this._trapFocusHandler = null;
            }
            // Restore focus to previous element
            if (this._previousFocus && this._previousFocus.focus) {
                this._previousFocus.focus();
                this._previousFocus = null;
            }
            setTimeout(() => {
                modal.style.display = 'none';
            }, 300);
        }
    }
    
    _trapFocus(e, modal) {
        if (e.key !== 'Tab') return;
        const focusable = modal.querySelectorAll(
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }

    closeAllModals() {
        document.querySelectorAll('.modal').forEach(modal => {
            modal.classList.add('hidden');
            modal.setAttribute('aria-hidden', 'true');
            modal.style.display = 'none';
        });
        if (this._previousFocus && this._previousFocus.focus) {
            this._previousFocus.focus();
            this._previousFocus = null;
        }
    }
    
    // ==================== LOADING STATES ====================
    showLoading(elementId, text = 'Loading...') {
        const element = document.getElementById(elementId);
        if (element) {
            element.innerHTML = `
                <div class="skeleton" style="width: 100%; height: 20px; margin-bottom: 10px;"></div>
                <div class="skeleton" style="width: 80%; height: 20px;"></div>
            `;
        }
    }
    
    setLoadingScene(isLoading) {
        const sceneDisplay = document.getElementById('scene-display');
        if (isLoading) {
            sceneDisplay.classList.add('loading');
        } else {
            sceneDisplay.classList.remove('loading');
        }
    }
    
    // ==================== STATUS MANAGEMENT ====================
    setStatus(text, state = 'default') {
        const statusText = document.getElementById('status-text');
        const statusIndicator = document.getElementById('status-indicator');
        
        if (statusText) {
            statusText.textContent = text;
        }
        
        if (statusIndicator) {
            // Remove all state classes
            statusIndicator.classList.remove('listening', 'processing', 'generating');
            
            // Add new state class
            if (state !== 'default') {
                statusIndicator.classList.add(state);
            }
            
            // Add/remove spinner
            const existingSpinner = statusIndicator.querySelector('.status-spinner');
            if (existingSpinner) {
                existingSpinner.remove();
            }
            
            if (state === 'processing' || state === 'generating') {
                const spinner = document.createElement('span');
                spinner.className = 'status-spinner';
                statusIndicator.insertBefore(spinner, statusText);
            }
        }
    }
    
    // ==================== SESSION STATS ====================
    updateStats(stats) {
        if (stats.versionCount !== undefined) {
            const versionEl = document.getElementById('version-count');
            if (versionEl) {
                versionEl.textContent = stats.versionCount;
            }
        }
        
        if (stats.statementCount !== undefined) {
            const statementEl = document.getElementById('statement-count');
            if (statementEl) {
                statementEl.textContent = stats.statementCount;
            }
        }
        
        if (stats.duration !== undefined) {
            const durationEl = document.getElementById('session-duration');
            if (durationEl) {
                durationEl.textContent = this.formatDuration(stats.duration);
            }
        }
    }
    
    formatDuration(seconds) {
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) {
            return `${minutes}m`;
        }
        const hours = Math.floor(minutes / 60);
        const remainingMinutes = minutes % 60;
        return `${hours}h ${remainingMinutes}m`;
    }
    
    // ==================== SCENE CONTROLS ====================
    showSceneControls() {
        const controls = document.querySelector('.scene-controls');
        if (controls) {
            controls.classList.remove('hidden');
        }
    }
    
    hideSceneControls() {
        const controls = document.querySelector('.scene-controls');
        if (controls) {
            controls.classList.add('hidden');
        }
    }
    
    // ==================== CONFIDENCE INDICATOR ====================
    createConfidenceBadge(confidence) {
        const level = confidence > 0.8 ? 'high' : confidence > 0.5 ? 'medium' : 'low';
        const percentage = Math.round(confidence * 100);
        
        return `<span class="confidence-badge ${level}">${percentage}% confident</span>`;
    }
}

// Export to global scope
window.UIManager = UIManager;
