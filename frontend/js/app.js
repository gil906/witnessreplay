/**
 * WitnessReplay - Main Application
 * Enhanced with Detective Ray persona, professional UI, and comprehensive features
 */

class WitnessReplayApp {
    constructor() {
        this.ws = null;
        this.sessionId = null;
        this.audioRecorder = null;
        this.audioVisualizer = null;
        this.isRecording = false;
        this.currentVersion = 0;
        this.statementCount = 0;
        this.sessionStartTime = null;
        this.durationTimer = null;
        this.ui = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectTimer = null;
        this.hasReceivedGreeting = false;
        this.fetchTimeout = 10000; // 10 second timeout for API calls
        this.soundEnabled = localStorage.getItem('soundEnabled') !== 'false'; // Default true
        this.sounds = {}; // Sound effect cache
        this.comparisonMode = false; // Scene comparison mode
        this.previousSceneUrl = null; // For before/after comparison
        
        this.initializeUI();
        this.initializeAudio();
        this.initializeModals();
        this.initializeSounds();
        this.initializeParticles();
        this.initializeSceneZoom();
        this.fetchAndDisplayVersion(); // Fetch version from API
        
        // Show onboarding for first-time users
        this.checkOnboarding();
    }
    
    /**
     * Fetch with timeout to prevent hanging requests
     * @param {string} url - The URL to fetch
     * @param {object} options - Fetch options
     * @param {number} timeout - Timeout in milliseconds
     * @returns {Promise<Response>}
     */
    async fetchWithTimeout(url, options = {}, timeout = this.fetchTimeout) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);
        
        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            return response;
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                throw new Error('Request timeout - the server took too long to respond');
            }
            throw error;
        }
    }
    
    initializeUI() {
        // Initialize UI Manager
        this.ui = new UIManager();
        
        // Get UI elements
        this.micBtn = document.getElementById('mic-btn');
        this.sendBtn = document.getElementById('send-btn');
        this.textInput = document.getElementById('text-input');
        this.sceneDisplay = document.getElementById('scene-display');
        this.sceneDescription = document.getElementById('scene-description');
        this.chatTranscript = document.getElementById('chat-transcript');
        this.timeline = document.getElementById('timeline');
        this.sessionIdEl = document.getElementById('session-id');
        this.newSessionBtn = document.getElementById('new-session-btn');
        this.sessionsListBtn = document.getElementById('sessions-list-btn');
        this.helpBtn = document.getElementById('help-btn');
        this.waveformRing = document.getElementById('waveform-ring');
        
        // Stats elements
        this.versionCountEl = document.getElementById('version-count');
        this.statementCountEl = document.getElementById('statement-count');
        this.complexityScoreEl = document.getElementById('complexity-score');
        this.contradictionCountEl = document.getElementById('contradiction-count');
        this.complexityCard = document.getElementById('complexity-card');
        this.contradictionCard = document.getElementById('contradiction-card');
        this.exportControls = document.getElementById('export-controls');
        
        // Event listeners
        this.micBtn.addEventListener('click', () => this.toggleRecording());
        this.sendBtn.addEventListener('click', () => this.sendTextMessage());
        this.textInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendTextMessage();
        });
        this.newSessionBtn.addEventListener('click', () => this.createNewSession());
        this.sessionsListBtn.addEventListener('click', () => this.showSessionsList());
        this.helpBtn.addEventListener('click', () => this.ui.showOnboarding());
        
        // Chat mic button
        this.chatMicBtn = document.getElementById('chat-mic-btn');
        if (this.chatMicBtn) {
            this.chatMicBtn.addEventListener('click', () => this.toggleRecording());
        }
        
        // Scene controls
        document.getElementById('download-btn')?.addEventListener('click', () => this.downloadScene());
        document.getElementById('zoom-btn')?.addEventListener('click', () => this.toggleZoom());
        document.getElementById('fullscreen-btn')?.addEventListener('click', () => this.toggleFullscreen());
        
        // Export buttons
        document.getElementById('export-pdf-btn')?.addEventListener('click', () => this.exportPDF());
        document.getElementById('export-json-btn')?.addEventListener('click', () => this.exportJSON());
        document.getElementById('export-evidence-btn')?.addEventListener('click', () => this.exportEvidence());
        
        // Model & Quota button
        const quotaBtn = document.getElementById('quota-btn');
        if (quotaBtn) {
            quotaBtn.addEventListener('click', () => this.showQuotaModal());
        }
        
        // Analytics button
        const analyticsBtn = document.getElementById('analytics-btn');
        if (analyticsBtn) {
            analyticsBtn.addEventListener('click', () => this.showAnalyticsModal());
        }
        
        // Info button
        const infoBtn = document.getElementById('info-btn');
        if (infoBtn) {
            infoBtn.addEventListener('click', () => this.showInfoModal());
        }
        
        // Admin portal button
        const adminPortalBtn = document.getElementById('admin-portal-btn');
        if (adminPortalBtn) {
            adminPortalBtn.addEventListener('click', () => {
                window.location.href = '/admin';
            });
        }
        
        // Start with a new session
        this.createNewSession();
        
        // Initialize suggested action buttons
        this._initSuggestedActions();
        
        // Initialize keyboard shortcuts
        this._initKeyboardShortcuts();
        
        // Sound toggle button (add dynamically if not in HTML)
        this._addSoundToggle();
    }
    
    _addSoundToggle() {
        const sessionInfo = document.querySelector('.session-info');
        if (!sessionInfo || document.getElementById('sound-toggle-btn')) return;
        
        const soundBtn = document.createElement('button');
        soundBtn.id = 'sound-toggle-btn';
        soundBtn.className = 'btn btn-secondary';
        soundBtn.setAttribute('data-tooltip', 'Toggle sound effects');
        soundBtn.innerHTML = this.soundEnabled ? '🔊' : '🔇';
        soundBtn.addEventListener('click', () => this.toggleSound());
        
        sessionInfo.appendChild(soundBtn);
    }
    
    toggleSound() {
        this.soundEnabled = !this.soundEnabled;
        localStorage.setItem('soundEnabled', this.soundEnabled);
        
        const soundBtn = document.getElementById('sound-toggle-btn');
        if (soundBtn) {
            soundBtn.innerHTML = this.soundEnabled ? '🔊' : '🔇';
        }
        
        this.ui.showToast(
            this.soundEnabled ? '🔊 Sound effects enabled' : '🔇 Sound effects disabled',
            'success',
            2000
        );
    }
    
    initializeSounds() {
        // Simple sound effects using Web Audio API
        this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    
    playSound(type) {
        if (!this.soundEnabled || !this.audioContext) return;
        
        const ctx = this.audioContext;
        const oscillator = ctx.createOscillator();
        const gainNode = ctx.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(ctx.destination);
        
        // Different sounds for different actions
        switch (type) {
            case 'click':
                oscillator.frequency.value = 800;
                gainNode.gain.setValueAtTime(0.08, ctx.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.08);
                oscillator.start(ctx.currentTime);
                oscillator.stop(ctx.currentTime + 0.08);
                break;
            case 'success':
                oscillator.frequency.value = 1200;
                gainNode.gain.setValueAtTime(0.12, ctx.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.2);
                oscillator.start(ctx.currentTime);
                oscillator.stop(ctx.currentTime + 0.2);
                break;
            case 'error':
                oscillator.type = 'sawtooth';
                oscillator.frequency.value = 300;
                gainNode.gain.setValueAtTime(0.08, ctx.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
                oscillator.start(ctx.currentTime);
                oscillator.stop(ctx.currentTime + 0.3);
                break;
            case 'recording-start':
                oscillator.frequency.value = 880;
                gainNode.gain.setValueAtTime(0.1, ctx.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
                oscillator.start(ctx.currentTime);
                oscillator.stop(ctx.currentTime + 0.15);
                break;
            case 'recording-stop':
                oscillator.frequency.value = 660;
                gainNode.gain.setValueAtTime(0.1, ctx.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
                oscillator.start(ctx.currentTime);
                oscillator.stop(ctx.currentTime + 0.15);
                break;
            case 'scene-ready':
                // Pleasant three-tone chime
                [600, 800, 1000].forEach((freq, i) => {
                    setTimeout(() => {
                        const osc = ctx.createOscillator();
                        const gain = ctx.createGain();
                        osc.connect(gain);
                        gain.connect(ctx.destination);
                        osc.frequency.value = freq;
                        gain.gain.setValueAtTime(0.1, ctx.currentTime);
                        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.2);
                        osc.start(ctx.currentTime);
                        osc.stop(ctx.currentTime + 0.2);
                    }, i * 80);
                });
                break;
            case 'notification':
                oscillator.type = 'triangle';
                oscillator.frequency.value = 900;
                gainNode.gain.setValueAtTime(0.08, ctx.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.12);
                oscillator.start(ctx.currentTime);
                oscillator.stop(ctx.currentTime + 0.12);
                break;
        }
    }
    
    _initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ignore if typing in input field
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                return;
            }
            
            // Space: Toggle recording (only if mic button is not disabled)
            if (e.code === 'Space' && !this.micBtn.disabled) {
                e.preventDefault();
                this.toggleRecording();
            }
            
            // Escape: Close any open modal or shortcuts overlay
            if (e.code === 'Escape') {
                e.preventDefault();
                const shortcutsOverlay = document.getElementById('shortcuts-overlay');
                if (shortcutsOverlay && !shortcutsOverlay.classList.contains('hidden')) {
                    shortcutsOverlay.classList.add('hidden');
                    return;
                }
                
                const openModal = document.querySelector('.modal:not(.hidden)');
                if (openModal) {
                    this.ui.hideModal(openModal.id);
                }
            }
            
            // ? : Show keyboard shortcuts overlay
            if (e.key === '?') {
                e.preventDefault();
                this.showShortcuts();
            }
            
            // N: New session
            if (e.key.toLowerCase() === 'n' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.createNewSession();
            }
            
            // S: Show sessions list
            if (e.key.toLowerCase() === 's' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.showSessionsList();
            }
            
            // M: Model selector
            if (e.key.toLowerCase() === 'm' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.showQuotaModal();
            }
            
            // A: Analytics
            if (e.key.toLowerCase() === 'a' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.showAnalytics();
            }
            
            // I: Server info
            if (e.key.toLowerCase() === 'i' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.showServerInfo();
            }
        });
    }
    
    initializeAudio() {
        if (window.AudioRecorder) {
            this.audioRecorder = new AudioRecorder();
        }
        
        if (window.EnhancedAudioVisualizer) {
            this.audioVisualizer = new EnhancedAudioVisualizer('audio-visualizer');
        }
        
        // Check if microphone is available (requires HTTPS or localhost)
        const isSecureContext = window.isSecureContext || 
            window.location.hostname === 'localhost' || 
            window.location.hostname === '127.0.0.1';
        
        if (!isSecureContext) {
            console.warn('Microphone requires HTTPS. Current page is not in a secure context.');
            const micWarning = '⚠️ Microphone requires HTTPS. Use text input instead, or access via localhost.';
            setTimeout(() => {
                if (this.ui) this.ui.showToast(micWarning, 'warning', 8000);
            }, 2000);
        }
        
        // Pre-request microphone permission on user interaction
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            console.warn('MediaDevices API not available');
        }
    }
    
    initializeModals() {
        // Session modal close buttons
        document.getElementById('close-modal-btn')?.addEventListener('click', () => {
            this.ui.hideModal('session-modal');
        });
        document.getElementById('modal-close-btn-2')?.addEventListener('click', () => {
            this.ui.hideModal('session-modal');
        });
        
        // Click outside modal to close
        document.getElementById('session-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'session-modal') {
                this.ui.hideModal('session-modal');
            }
        });
        
        // Quota modal close buttons
        document.getElementById('close-quota-modal-btn')?.addEventListener('click', () => {
            this.ui.hideModal('quota-modal');
        });
        document.getElementById('modal-close-quota-btn-2')?.addEventListener('click', () => {
            this.ui.hideModal('quota-modal');
        });
        
        // Click outside quota modal to close
        document.getElementById('quota-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'quota-modal') {
                this.ui.hideModal('quota-modal');
            }
        });
        
        // Model selector and quota controls
        const modelSelect = document.getElementById('model-select');
        const applyModelBtn = document.getElementById('apply-model-btn');
        const refreshQuotaBtn = document.getElementById('refresh-quota-btn');
        
        if (modelSelect) {
            modelSelect.addEventListener('change', () => {
                if (applyModelBtn) {
                    applyModelBtn.disabled = false;
                }
            });
        }
        
        if (applyModelBtn) {
            applyModelBtn.addEventListener('click', () => this.applyModelChange());
        }
        
        if (refreshQuotaBtn) {
            refreshQuotaBtn.addEventListener('click', () => this.refreshQuota());
        }
        
        // Analytics modal close buttons
        document.getElementById('close-analytics-modal-btn')?.addEventListener('click', () => {
            this.ui.hideModal('analytics-modal');
        });
        document.getElementById('modal-close-analytics-btn')?.addEventListener('click', () => {
            this.ui.hideModal('analytics-modal');
        });
        document.getElementById('analytics-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'analytics-modal') {
                this.ui.hideModal('analytics-modal');
            }
        });
        
        // Info modal close buttons
        document.getElementById('close-info-modal-btn')?.addEventListener('click', () => {
            this.ui.hideModal('info-modal');
        });
        document.getElementById('modal-close-info-btn')?.addEventListener('click', () => {
            this.ui.hideModal('info-modal');
        });
        document.getElementById('info-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'info-modal') {
                this.ui.hideModal('info-modal');
            }
        });
        
        // Comparison modal close buttons
        document.getElementById('close-comparison-modal-btn')?.addEventListener('click', () => {
            this.ui.hideModal('comparison-modal');
        });
        document.getElementById('modal-close-comparison-btn')?.addEventListener('click', () => {
            this.ui.hideModal('comparison-modal');
        });
        document.getElementById('comparison-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'comparison-modal') {
                this.ui.hideModal('comparison-modal');
            }
        });
    }
    
    async createNewSession() {
        try {
            this.ui.setStatus('Creating session...', 'processing');
            
            // Call API to create session
            const response = await this.fetchWithTimeout('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    title: `Session ${new Date().toLocaleString()}`
                })
            });
            
            if (!response.ok) throw new Error('Failed to create session');
            
            const session = await response.json();
            this.sessionId = session.id;
            this.sessionIdEl.textContent = `Session: ${session.id.substring(0, 8)}...`;
            
            // Reset state
            this.currentVersion = 0;
            this.statementCount = 0;
            this.sessionStartTime = Date.now();
            this.reconnectAttempts = 0;
            this.hasReceivedGreeting = false;
            
            // Start duration timer
            this.startDurationTimer();
            
            // Clear UI
            this.chatTranscript.innerHTML = '';
            this.displaySystemMessage("👋 Detective Ray here. Ready to reconstruct the scene. Start speaking when you're ready.");
            this.timeline.innerHTML = '<p class="empty-state">No versions yet</p>';
            
            // Update stats
            this.ui.updateStats({
                versionCount: 0,
                statementCount: 0,
                duration: 0
            });
            
            // Connect WebSocket
            this.connectWebSocket();
            
            // Show success toast
            this.ui.showToast('New session created', 'success');
            
        } catch (error) {
            console.error('Error creating session:', error);
            this.ui.setStatus('Error creating session', 'default');
            this.ui.showToast('Failed to create session. Please try again.', 'error');
        }
    }
    
    startDurationTimer() {
        if (this.durationTimer) {
            clearInterval(this.durationTimer);
        }
        
        this.durationTimer = setInterval(() => {
            if (this.sessionStartTime) {
                const elapsed = Math.floor((Date.now() - this.sessionStartTime) / 1000);
                this.ui.updateStats({ duration: elapsed });
            }
        }, 10000); // Update every 10 seconds
    }
    
    connectWebSocket() {
        if (this.ws) {
            this.ws.close();
        }
        
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/${this.sessionId}`;
        
        this.ui.setStatus('Connecting to Detective Ray...', 'processing');
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            this.reconnectAttempts = 0;
            this.ui.setStatus('Ready — Press Space to speak', 'default');
            this.micBtn.disabled = false;
            if (this.chatMicBtn) this.chatMicBtn.disabled = false;
            this.textInput.disabled = false;
            this.sendBtn.disabled = false;
            
            // Update connection status indicator
            const statusDot = document.querySelector('.status-dot');
            if (statusDot) {
                statusDot.style.background = 'var(--accent-green)';
                statusDot.style.boxShadow = '0 0 8px var(--accent-green)';
            }
            
            this.ui.showToast('🔌 Connected to Detective Ray', 'success', 2000);
        };
        
        this.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            this.handleWebSocketMessage(message);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.ui.setStatus('Connection error', 'default');
        };
        
        this.ws.onclose = () => {
            this.ui.setStatus('Disconnected', 'default');
            this.micBtn.disabled = true;
            if (this.chatMicBtn) this.chatMicBtn.disabled = true;
            this.textInput.disabled = true;
            this.sendBtn.disabled = true;
            
            // Update connection status indicator
            const statusDot = document.querySelector('.status-dot');
            if (statusDot) {
                statusDot.style.background = 'var(--accent-amber)';
                statusDot.style.boxShadow = '0 0 8px var(--accent-amber)';
                statusDot.style.animation = 'statusPulse 1.5s ease-in-out infinite';
            }
            
            // Reconnect with backoff, max attempts
            if (this.sessionId && this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000);
                this.ui.showToast(
                    `🔄 Reconnecting in ${Math.floor(delay/1000)}s (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`,
                    'warning',
                    delay
                );
                this.reconnectTimer = setTimeout(() => {
                    this.connectWebSocket();
                }, delay);
            } else if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                // Max attempts reached - show error state
                this.ui.setStatus('Connection lost - Please reload', 'default');
                this.ui.showToast(
                    '❌ Unable to reconnect after ' + this.maxReconnectAttempts + ' attempts. Please reload the page.',
                    'error',
                    0 // Persistent
                );
                
                // Show error in scene display
                this.sceneDisplay.innerHTML = `
                    <div class="error-state">
                        <div class="error-icon">📡</div>
                        <div class="error-title">Connection Lost</div>
                        <div class="error-message">
                            Unable to reconnect to Detective Ray. Please reload the page to continue.
                        </div>
                        <div class="error-actions">
                            <button class="btn btn-primary" onclick="location.reload()">
                                🔄 Reload Page
                            </button>
                        </div>
                    </div>
                `;
                
                // Update status indicator
                if (this.sessionIdEl) {
                    const statusSpan = this.sessionIdEl.querySelector('.connection-status');
                    if (statusSpan) {
                        statusSpan.className = 'connection-status offline';
                        statusSpan.innerHTML = `
                            <span class="status-dot"></span>
                            Offline
                        `;
                    }
                }
            }
        };
    }
    
    handleWebSocketMessage(message) {
        switch (message.type) {
            case 'text':
                const speaker = message.data.speaker || 'agent';
                this.displayMessage(message.data.text, speaker);
                if (speaker === 'agent') {
                    this.ui.playSound('notification');
                }
                break;
            
            case 'scene_update':
                this.updateScene(message.data);
                this.ui.playSound('sceneGenerated');
                this.ui.showToast('Scene updated', 'success', 2000);
                
                // Show contradictions if any
                if (message.data.contradictions && message.data.contradictions.length > 0) {
                    this.displayContradictions(message.data.contradictions);
                }
                break;
            
            case 'scene_state':
                this._handleSceneState(message.data);
                break;
            
            case 'status':
                const statusMsg = message.data.message || message.data.status;
                const state = this.getStatusState(statusMsg);
                this.ui.setStatus(statusMsg, state);
                
                // Show typing indicator when agent is thinking
                if (state === 'processing') {
                    this._showTyping();
                } else {
                    this._hideTyping();
                }
                
                // Show loading skeleton when generating scene
                if (state === 'generating' && !this.sceneDisplay.querySelector('.scene-image')) {
                    this.showSceneLoadingSkeleton();
                }
                break;
            
            case 'error':
                const errorMsg = `Error: ${message.data.message}`;
                this.ui.setStatus(errorMsg, 'default');
                this.displaySystemMessage(errorMsg);
                this.ui.showToast(message.data.message, 'error');
                this._hideTyping();
                break;
            
            case 'pong':
                // Heartbeat response
                break;
            
            default:
                console.warn('Unknown message type:', message.type);
        }
    }
    
    getStatusState(statusText) {
        const lower = statusText.toLowerCase();
        if (lower.includes('listening') || lower.includes('recording')) {
            return 'listening';
        } else if (lower.includes('processing') || lower.includes('analyzing')) {
            return 'processing';
        } else if (lower.includes('generating') || lower.includes('creating')) {
            return 'generating';
        }
        return 'default';
    }
    
    toggleRecording() {
        if (this.isRecording) {
            this.stopRecording();
        } else {
            this.startRecording();
        }
    }
    
    async startRecording() {
        try {
            // Check secure context first
            if (!window.isSecureContext && 
                window.location.hostname !== 'localhost' && 
                window.location.hostname !== '127.0.0.1') {
                this.ui.showToast('⚠️ Microphone requires HTTPS. Use text input or access via localhost.', 'error', 5000);
                this.displaySystemMessage('⚠️ Voice recording requires a secure connection (HTTPS). Please type your statement instead.');
                return;
            }
            
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                this.ui.showToast('Microphone not supported in this browser', 'error');
                return;
            }
            
            // Request permission explicitly — this triggers the browser popup
            try {
                const testStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                testStream.getTracks().forEach(t => t.stop());
            } catch (permErr) {
                console.error('Microphone permission denied:', permErr);
                this.ui.showToast('🎤 Microphone access denied. Check browser permissions.', 'error', 5000);
                this.displaySystemMessage('🎤 Microphone access was denied. Please allow microphone access in your browser settings, or type your statement below.');
                return;
            }
            
            if (this.audioRecorder) {
                await this.audioRecorder.start();
                this.isRecording = true;
                this.micBtn.classList.add('recording');
                const btnText = this.micBtn.querySelector('.btn-text');
                if (btnText) btnText.textContent = 'Recording...';
                if (this.chatMicBtn) {
                    this.chatMicBtn.classList.add('recording');
                    this.chatMicBtn.textContent = '⏹';
                }
                if (this.stopBtn) this.stopBtn.style.display = 'inline-block';
                this.setStatus('Listening...');
                
                // Play recording start sound
                this.playSound('recording-start');
                
                // Add pulsing animation to Detective Ray avatar
                const detectiveAvatar = document.querySelector('.detective-avatar');
                if (detectiveAvatar) {
                    detectiveAvatar.classList.add('listening');
                }
            } else {
                this.ui.showToast('Audio recorder not available. Use text input.', 'warning');
            }
        } catch (error) {
            console.error('Error starting recording:', error);
            this.ui.showToast('Microphone error: ' + error.message, 'error');
            this.playSound('error');
            this.displaySystemMessage('🎤 Could not access microphone. Please type your statement instead.');
        }
    }
    
    async stopRecording() {
        if (!this.isRecording) return;
        
        try {
            if (this.audioRecorder) {
                const audioBlob = await this.audioRecorder.stop();
                this.isRecording = false;
                this.micBtn.classList.remove('recording');
                const btnText2 = this.micBtn.querySelector('.btn-text');
                if (btnText2) btnText2.textContent = 'Start Speaking';
                if (this.chatMicBtn) {
                    this.chatMicBtn.classList.remove('recording');
                    this.chatMicBtn.textContent = '🎤';
                }
                if (this.stopBtn) this.stopBtn.style.display = 'none';
                
                // Play recording stop sound
                this.playSound('recording-stop');
                
                // Remove pulsing animation from Detective Ray avatar
                const detectiveAvatar = document.querySelector('.detective-avatar');
                if (detectiveAvatar) {
                    detectiveAvatar.classList.remove('listening');
                }
                
                // Convert to base64 and send
                this.sendAudioMessage(audioBlob);
            }
        } catch (error) {
            console.error('Error stopping recording:', error);
            this.setStatus('Error processing audio');
            this.playSound('error');
        }
    }
    
    async sendAudioMessage(audioBlob) {
        try {
            const reader = new FileReader();
            reader.onloadend = () => {
                const base64Audio = reader.result.split(',')[1];
                
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({
                        type: 'audio',
                        data: {
                            audio: base64Audio,
                            format: 'webm'
                        }
                    }));
                    this.setStatus('Processing audio...');
                }
            };
            reader.readAsDataURL(audioBlob);
        } catch (error) {
            console.error('Error sending audio:', error);
        }
    }
    
    sendTextMessage() {
        const text = this.textInput.value.trim();
        if (!text) return;
        
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'text',
                data: {text: text}
            }));
            
            this.displayMessage(text, 'user');
            this.textInput.value = '';
            this.setStatus('Processing...');
        }
    }
    
    displayMessage(text, speaker) {
        if (this.chatTranscript.querySelector('.empty-state')) {
            this.chatTranscript.innerHTML = '';
        }
        
        // Hide typing indicator
        this._hideTyping();
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${speaker}`;
        
        const avatar = speaker === 'user' ? '👤' : speaker === 'agent' ? '🔍' : 'ℹ️';
        const labelText = speaker === 'user' ? 'You' : speaker === 'agent' ? 'Detective Ray' : 'System';
        const now = new Date();
        const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        
        messageDiv.innerHTML = `<span class="msg-avatar">${avatar}</span><strong>${labelText}</strong><span class="msg-time">${timeStr}</span><br>${this._escapeHtml(text)}`;
        
        this.chatTranscript.appendChild(messageDiv);
        this.chatTranscript.scrollTo({ top: this.chatTranscript.scrollHeight, behavior: 'smooth' });
        
        // Track statement count for user messages
        if (speaker === 'user') {
            this.statementCount++;
            if (this.statementCountEl) this.statementCountEl.textContent = this.statementCount;
        }
    }
    
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    _showTyping() {
        const el = document.getElementById('typing-indicator');
        if (el) el.classList.remove('hidden');
        // Scroll
        this.chatTranscript.scrollTo({ top: this.chatTranscript.scrollHeight, behavior: 'smooth' });
    }
    
    _hideTyping() {
        const el = document.getElementById('typing-indicator');
        if (el) el.classList.add('hidden');
    }
    
    updateScene(data) {
        // Crossfade animation for scene changes
        const existingImage = this.sceneDisplay.querySelector('.scene-image');
        
        if (existingImage) {
            // Fade out old image
            existingImage.classList.add('crossfade-out');
            setTimeout(() => {
                this.setSceneImage(data);
            }, 400);
        } else {
            // First scene, no crossfade needed
            this.setSceneImage(data);
        }
        
        // Update description
        if (data.description) {
            this.sceneDescription.innerHTML = `<p>${data.description}</p>`;
        }
        
        // Update stats
        this.currentVersion = data.version || this.currentVersion + 1;
        if (this.versionCountEl) this.versionCountEl.textContent = this.currentVersion;
        
        if (data.statement_count) {
            if (this.statementCountEl) this.statementCountEl.textContent = data.statement_count;
        }
        
        // Update complexity if available
        if (data.complexity !== undefined) {
            if (this.complexityCard) this.complexityCard.style.display = 'block';
            if (this.complexityScoreEl) this.complexityScoreEl.textContent = (data.complexity * 100).toFixed(0) + '%';
        }
        
        // Update contradictions if available
        if (data.contradictions && data.contradictions.length > 0) {
            if (this.contradictionCard) this.contradictionCard.style.display = 'block';
            if (this.contradictionCountEl) this.contradictionCountEl.textContent = data.contradictions.length;
            this.ui.showToast(`⚠️ ${data.contradictions.length} contradiction(s) detected`, 'warning', 4000);
        }
        
        // Show export controls once we have a scene
        if (this.exportControls) this.exportControls.style.display = 'block';
        
        // Add to timeline
        this.addTimelineVersion(data);
    }
    
    showSceneLoadingSkeleton() {
        // Show enhanced loading skeleton before scene generation
        const skeleton = document.createElement('div');
        skeleton.className = 'scene-skeleton';
        skeleton.innerHTML = `
            <div class="skeleton-overlay">
                <div class="spinner-gradient"></div>
                <p class="skeleton-text">🎨 Reconstructing scene...</p>
                <p class="skeleton-subtext" style="font-size: 0.8rem; margin-top: 0.5rem; color: var(--text-muted);">
                    Detective Ray is analyzing your description
                </p>
            </div>
        `;
        
        this.sceneDisplay.innerHTML = '';
        this.sceneDisplay.appendChild(skeleton);
        
        this.sceneDescription.innerHTML = '<p class="text-muted loading-dots">Generating scene</p>';
    }
    
    setSceneImage(data) {
        if (data.image_url) {
            // Clear existing scene
            this.sceneDisplay.innerHTML = '';
            
            // Create container for scene with version badge
            const sceneContainer = document.createElement('div');
            sceneContainer.style.position = 'relative';
            sceneContainer.style.width = '100%';
            sceneContainer.style.height = '100%';
            sceneContainer.style.display = 'flex';
            sceneContainer.style.alignItems = 'center';
            sceneContainer.style.justifyContent = 'center';
            
            // Add version badge
            const versionBadge = document.createElement('div');
            versionBadge.className = 'scene-version-badge';
            versionBadge.innerHTML = `
                <span class="badge-icon">🎬</span>
                <span>Version ${data.version || this.currentVersion}</span>
            `;
            sceneContainer.appendChild(versionBadge);
            
            // Create image with enhanced loading state
            const img = new Image();
            img.className = 'scene-image scene-entering';
            img.alt = 'Scene reconstruction';
            
            img.onload = () => {
                // Smooth transition from entering to loaded
                setTimeout(() => {
                    img.classList.remove('scene-entering');
                    img.classList.add('loaded');
                }, 600);
            };
            
            img.onerror = () => {
                // Show error state with retry option
                this.showSceneError('Failed to load scene image', data);
            };
            
            img.src = data.image_url;
            sceneContainer.appendChild(img);
            this.sceneDisplay.appendChild(sceneContainer);
            
            // Show scene controls
            const controls = this.sceneDisplay.querySelector('.scene-controls');
            if (controls) controls.classList.remove('hidden');
        } else if (data.base64_image) {
            // Similar handling for base64 images
            this.sceneDisplay.innerHTML = '';
            
            const sceneContainer = document.createElement('div');
            sceneContainer.style.position = 'relative';
            sceneContainer.style.width = '100%';
            sceneContainer.style.height = '100%';
            sceneContainer.style.display = 'flex';
            sceneContainer.style.alignItems = 'center';
            sceneContainer.style.justifyContent = 'center';
            
            const versionBadge = document.createElement('div');
            versionBadge.className = 'scene-version-badge';
            versionBadge.innerHTML = `
                <span class="badge-icon">🎬</span>
                <span>Version ${data.version || this.currentVersion}</span>
            `;
            sceneContainer.appendChild(versionBadge);
            
            const img = new Image();
            img.className = 'scene-image scene-entering';
            img.alt = 'Scene reconstruction';
            img.onload = () => {
                setTimeout(() => {
                    img.classList.remove('scene-entering');
                    img.classList.add('loaded');
                }, 600);
            };
            img.src = `data:image/png;base64,${data.base64_image}`;
            sceneContainer.appendChild(img);
            this.sceneDisplay.appendChild(sceneContainer);
            
            const controls = this.sceneDisplay.querySelector('.scene-controls');
            if (controls) controls.classList.remove('hidden');
        }
        
        // Play success sound for scene generation
        this.playSound('scene-ready');
        
        // Save current scene URL for comparison
        const currentImg = this.sceneDisplay.querySelector('.scene-image');
        if (currentImg && currentImg.src && !this.comparisonMode) {
            this.previousSceneUrl = currentImg.src;
            
            // Add comparison button if we have previous version
            if (this.currentVersion > 1) {
                this.addComparisonButton();
            }
        }
    }
    
    addComparisonButton() {
        const sceneControls = this.sceneDisplay.querySelector('.scene-controls');
        if (!sceneControls || sceneControls.querySelector('#compare-btn')) return;
        
        const compareBtn = document.createElement('button');
        compareBtn.id = 'compare-btn';
        compareBtn.className = 'scene-control-btn';
        compareBtn.setAttribute('data-tooltip', 'Compare versions');
        compareBtn.setAttribute('aria-label', 'Compare with previous version');
        compareBtn.textContent = '🔀';
        compareBtn.addEventListener('click', () => this.toggleComparisonMode());
        
        // Insert before fullscreen button
        const fullscreenBtn = sceneControls.querySelector('#fullscreen-btn');
        if (fullscreenBtn) {
            sceneControls.insertBefore(compareBtn, fullscreenBtn);
        } else {
            sceneControls.appendChild(compareBtn);
        }
    }
    
    toggleComparisonMode() {
        if (!this.previousSceneUrl) {
            this.ui.showToast('No previous version to compare', 'warning', 2000);
            return;
        }
        
        this.comparisonMode = !this.comparisonMode;
        const compareBtn = document.getElementById('compare-btn');
        
        if (this.comparisonMode) {
            this.showComparison();
            if (compareBtn) compareBtn.classList.add('active');
            this.playSound('click');
        } else {
            const currentImgSrc = this.sceneDisplay.querySelector('.comparison-side:last-child img')?.src;
            this.hideComparison(currentImgSrc);
            if (compareBtn) compareBtn.classList.remove('active');
        }
    }
    
    showComparison() {
        const currentImg = this.sceneDisplay.querySelector('.scene-image');
        if (!currentImg || !this.previousSceneUrl) return;
        
        const currentSrc = currentImg.src;
        
        // Use enhanced comparison slider
        this.showEnhancedComparison(this.previousSceneUrl, currentSrc);
    }
    
    hideComparison(currentSrc) {
        this.sceneDisplay.classList.remove('comparison-mode');
        
        // Restore single image view
        if (currentSrc) {
            this.sceneDisplay.innerHTML = '';
            
            const sceneContainer = document.createElement('div');
            sceneContainer.style.position = 'relative';
            sceneContainer.style.width = '100%';
            sceneContainer.style.height = '100%';
            sceneContainer.style.display = 'flex';
            sceneContainer.style.alignItems = 'center';
            sceneContainer.style.justifyContent = 'center';
            
            const versionBadge = document.createElement('div');
            versionBadge.className = 'scene-version-badge';
            versionBadge.innerHTML = `
                <span class="badge-icon">🎬</span>
                <span>Version ${this.currentVersion}</span>
            `;
            sceneContainer.appendChild(versionBadge);
            
            const img = document.createElement('img');
            img.className = 'scene-image fade-in';
            img.src = currentSrc;
            img.alt = 'Reconstructed scene';
            sceneContainer.appendChild(img);
            
            this.sceneDisplay.appendChild(sceneContainer);
            
            const controls = this.sceneDisplay.querySelector('.scene-controls');
            if (controls) controls.classList.remove('hidden');
        }
    }
    
    /**
     * Show enhanced comparison with draggable slider
     * @param {string} beforeSrc - URL of before image
     * @param {string} afterSrc - URL of after image
     */
    showEnhancedComparison(beforeSrc, afterSrc) {
        this.sceneDisplay.innerHTML = '';
        this.sceneDisplay.classList.add('comparison-mode');
        
        const sliderContainer = document.createElement('div');
        sliderContainer.className = 'comparison-slider-container';
        sliderContainer.innerHTML = `
            <div class="comparison-slider-before" style="background-image: url('${beforeSrc}');"></div>
            <div class="comparison-slider-after" style="background-image: url('${afterSrc}');"></div>
            <div class="comparison-slider-handle"></div>
            <div class="comparison-label before">Before v${this.currentVersion - 1}</div>
            <div class="comparison-label after">After v${this.currentVersion}</div>
        `;
        
        this.sceneDisplay.appendChild(sliderContainer);
        
        // Initialize drag functionality
        this.initializeComparisonSlider(sliderContainer);
        
        this.ui.showToast('Drag the slider to compare versions', 'info', 3000);
    }
    
    /**
     * Initialize draggable comparison slider
     * @param {HTMLElement} container - The slider container element
     */
    initializeComparisonSlider(container) {
        const handle = container.querySelector('.comparison-slider-handle');
        const afterImage = container.querySelector('.comparison-slider-after');
        let isDragging = false;
        
        const updateSliderPosition = (clientX) => {
            const rect = container.getBoundingClientRect();
            let position = ((clientX - rect.left) / rect.width) * 100;
            position = Math.max(0, Math.min(100, position)); // Clamp between 0-100
            
            // Update clip path
            afterImage.style.clipPath = `inset(0 ${100 - position}% 0 0)`;
            handle.style.left = `${position}%`;
        };
        
        // Mouse events
        const handleMouseDown = (e) => {
            isDragging = true;
            container.style.cursor = 'col-resize';
            e.preventDefault();
        };
        
        const handleMouseMove = (e) => {
            if (!isDragging) return;
            updateSliderPosition(e.clientX);
        };
        
        const handleMouseUp = () => {
            isDragging = false;
            container.style.cursor = 'default';
        };
        
        // Touch events
        const handleTouchStart = (e) => {
            isDragging = true;
            e.preventDefault();
        };
        
        const handleTouchMove = (e) => {
            if (!isDragging) return;
            const touch = e.touches[0];
            updateSliderPosition(touch.clientX);
            e.preventDefault();
        };
        
        const handleTouchEnd = () => {
            isDragging = false;
        };
        
        // Attach events to handle
        handle.addEventListener('mousedown', handleMouseDown);
        handle.addEventListener('touchstart', handleTouchStart);
        
        // Attach events to document for dragging
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
        document.addEventListener('touchmove', handleTouchMove, { passive: false });
        document.addEventListener('touchend', handleTouchEnd);
        
        // Click anywhere to move slider
        container.addEventListener('click', (e) => {
            if (e.target === container || e.target.classList.contains('comparison-slider-before') || e.target.classList.contains('comparison-slider-after')) {
                updateSliderPosition(e.clientX);
            }
        });
        
        // Cleanup function (store for later)
        container._cleanupSlider = () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            document.removeEventListener('touchmove', handleTouchMove);
            document.removeEventListener('touchend', handleTouchEnd);
        };
    }
    
    showSceneError(message, data) {
        // Enhanced error state for scene loading failures
        this.sceneDisplay.innerHTML = `
            <div class="error-state">
                <div class="error-icon">⚠️</div>
                <div class="error-title">Scene Generation Error</div>
                <div class="error-message">${this._escapeHtml(message)}</div>
                <div class="error-actions">
                    <button class="btn btn-primary" onclick="location.reload()">
                        Reload Page
                    </button>
                </div>
            </div>
        `;
    }
    
    addTimelineVersion(data) {
        if (this.timeline.querySelector('.empty-state')) {
            this.timeline.innerHTML = '';
        }
        
        const versionDiv = document.createElement('div');
        versionDiv.className = 'timeline-item active';
        versionDiv.dataset.version = data.version || this.currentVersion;
        
        const changes = data.changes ? `<div class="timeline-changes">✨ ${data.changes}</div>` : '';
        const thumbnailSrc = data.image_url || (data.base64_image ? `data:image/png;base64,${data.base64_image}` : '');
        
        versionDiv.innerHTML = `
            <div class="timeline-version">Version ${data.version || this.currentVersion}</div>
            <div class="timeline-time">${new Date().toLocaleTimeString()}</div>
            ${thumbnailSrc ? `<img src="${thumbnailSrc}" alt="Version ${data.version}" class="timeline-thumbnail">` : ''}
            ${data.description ? `<p class="timeline-description">${this._escapeHtml(data.description.substring(0, 80))}...</p>` : ''}
            ${changes}
            <button class="timeline-compare" title="Compare with current">
                ⚖️ Compare
            </button>
        `;
        
        // Remove active class from previous versions
        this.timeline.querySelectorAll('.timeline-item').forEach(item => {
            item.classList.remove('active');
        });
        
        // Add click handler for viewing
        versionDiv.addEventListener('click', (e) => {
            // Don't trigger if clicking compare button
            if (!e.target.classList.contains('timeline-compare')) {
                this.showTimelineVersion(versionDiv);
            }
        });
        
        // Add compare button handler
        const compareBtn = versionDiv.querySelector('.timeline-compare');
        if (compareBtn) {
            compareBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.compareVersions(versionDiv);
            });
        }
        
        this.timeline.insertBefore(versionDiv, this.timeline.firstChild);
        
        // Smooth scroll to show new version with a slight delay for animation
        requestAnimationFrame(() => {
            this.timeline.scrollTo({ top: 0, behavior: 'smooth' });
            // Add highlight pulse effect
            versionDiv.style.animation = 'timelinePulse 0.6s ease-out';
        });
    }
    
    compareVersions(versionElement) {
        // Show comparison modal with before/after view
        const versionNum = parseInt(versionElement.dataset.version);
        const versionImg = versionElement.querySelector('.timeline-thumbnail');
        const versionDesc = versionElement.querySelector('.timeline-description');
        
        if (!versionImg || !this.sceneDisplay.querySelector('.scene-image')) {
            this.ui.showToast('Unable to compare - missing images', 'warning');
            return;
        }
        
        // Get current scene
        const currentImg = this.sceneDisplay.querySelector('.scene-image');
        const currentDesc = this.sceneDescription.textContent;
        
        // Populate comparison modal
        const beforeContainer = document.getElementById('comparison-before');
        const afterContainer = document.getElementById('comparison-after');
        const beforeDesc = document.getElementById('comparison-before-description');
        const afterDesc = document.getElementById('comparison-after-description');
        
        beforeContainer.innerHTML = `
            <div class="version-badge">Version ${versionNum}</div>
            <img src="${versionImg.src}" alt="Version ${versionNum}" class="comparison-image loading">
        `;
        
        afterContainer.innerHTML = `
            <div class="version-badge">Version ${this.currentVersion}</div>
            <img src="${currentImg.src}" alt="Current version" class="comparison-image loading">
        `;
        
        beforeDesc.textContent = versionDesc ? versionDesc.textContent : 'No description';
        afterDesc.textContent = currentDesc || 'Current scene';
        
        // Show modal
        this.ui.showModal('comparison-modal');
        this.playSound('click');
        
        // Add load handlers to remove skeleton
        const beforeImg = beforeContainer.querySelector('img');
        const afterImg = afterContainer.querySelector('img');
        
        beforeImg.addEventListener('load', () => beforeImg.classList.remove('loading'));
        afterImg.addEventListener('load', () => afterImg.classList.remove('loading'));
    }
    
    showTimelineVersion(versionElement) {
        // Remove active class from all
        this.timeline.querySelectorAll('.timeline-item').forEach(item => {
            item.classList.remove('active');
        });
        
        // Add active to clicked
        versionElement.classList.add('active');
        
        // Show this version in main display
        const img = versionElement.querySelector('img');
        const description = versionElement.querySelector('.timeline-description');
        
        if (img) {
            this.sceneDisplay.innerHTML = `
                <img src="${img.src}" alt="Previous version" class="scene-image">
            `;
        }
        
        if (description) {
            this.sceneDescription.innerHTML = `<p>${description.textContent}</p>`;
        }
    }
    
    // Sessions list
    async showSessionsList() {
        this.ui.showModal('session-modal');
        this.ui.showLoading('session-list');
        
        try {
            const response = await this.fetchWithTimeout('/api/sessions');
            if (!response.ok) throw new Error('Failed to load sessions');
            
            const sessions = await response.json();
            const sessionList = document.getElementById('session-list');
            
            if (sessions.length === 0) {
                sessionList.innerHTML = '<p class="empty-state">No sessions yet</p>';
                return;
            }
            
            sessionList.innerHTML = sessions.map(session => `
                <div class="session-card" data-session-id="${session.id}">
                    <div class="session-details">
                        <div class="session-title">${session.title}</div>
                        <div class="session-meta">
                            <span>📅 ${new Date(session.created_at).toLocaleDateString()}</span>
                            <span>💬 ${session.statement_count} statements</span>
                            <span>🎬 ${session.version_count} versions</span>
                        </div>
                    </div>
                    <div class="session-actions">
                        <button class="btn btn-sm btn-primary" onclick="window.app.loadSession('${session.id}')">
                            Load
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="window.app.deleteSession('${session.id}')">
                            🗑️
                        </button>
                    </div>
                </div>
            `).join('');
            
        } catch (error) {
            console.error('Error loading sessions:', error);
            this.ui.showToast('Failed to load sessions', 'error');
        }
    }
    
    async loadSession(sessionId) {
        this.ui.hideModal('session-modal');
        this.ui.showToast('Loading session...', 'info');
        
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${sessionId}`);
            if (!response.ok) throw new Error('Failed to load session');
            
            const session = await response.json();
            this.sessionId = session.id;
            this.sessionIdEl.textContent = `Session: ${session.id.substring(0, 8)}...`;
            
            this.connectWebSocket();
            this.ui.showToast('Session loaded', 'success');
            
        } catch (error) {
            console.error('Error loading session:', error);
            this.ui.showToast('Failed to load session', 'error');
        }
    }
    
    async deleteSession(sessionId) {
        if (!confirm('Are you sure you want to delete this session?')) {
            return;
        }
        
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${sessionId}`, {
                method: 'DELETE'
            });
            
            if (!response.ok) throw new Error('Failed to delete session');
            
            this.ui.showToast('Session deleted', 'success');
            this.showSessionsList(); // Refresh list
            
        } catch (error) {
            console.error('Error deleting session:', error);
            this.ui.showToast('Failed to delete session', 'error');
        }
    }
    
    // Scene controls
    downloadScene() {
        const img = this.sceneDisplay?.querySelector('.scene-image');
        if (img) {
            const link = document.createElement('a');
            link.href = img.src;
            link.download = `scene-v${this.currentVersion}.png`;
            link.click();
            this.ui.showToast('Scene downloaded', 'success');
        }
    }
    
    toggleZoom() {
        const display = this.sceneDisplay;
        const img = display.querySelector('.scene-image');
        
        if (img) {
            if (img.style.transform === 'scale(2)') {
                img.style.transform = 'scale(1)';
                img.style.cursor = 'zoom-in';
            } else {
                img.style.transform = 'scale(2)';
                img.style.cursor = 'zoom-out';
            }
        }
    }
    
    toggleFullscreen() {
        const display = this.sceneDisplay;
        
        if (!document.fullscreenElement) {
            display.requestFullscreen();
        } else {
            document.exitFullscreen();
        }
    }
    
    displaySystemMessage(text) {
        if (this.chatTranscript.querySelector('.empty-state')) {
            this.chatTranscript.innerHTML = '';
        }
        
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message message-system';
        messageDiv.textContent = text;
        
        this.chatTranscript.appendChild(messageDiv);
        this.chatTranscript.scrollTop = this.chatTranscript.scrollHeight;
    }
    
    displayContradictions(contradictions) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message message-contradiction';
        
        let html = '<strong>⚠️ Contradiction Detected</strong>';
        contradictions.forEach(c => {
            html += `<div class="contradiction-item">
                <div class="contradiction-field">${c.field || 'Unknown field'}</div>
                <div class="contradiction-change">
                    <span class="old-value">"${c.old_value}"</span>
                    <span class="arrow">→</span>
                    <span class="new-value">"${c.new_value}"</span>
                </div>
            </div>`;
        });
        
        messageDiv.innerHTML = html;
        this.chatTranscript.appendChild(messageDiv);
        this.chatTranscript.scrollTop = this.chatTranscript.scrollHeight;
    }
    
    // ======================================
    // Scene State & Evidence Board
    // ======================================
    
    _handleSceneState(data) {
        // Update progress tracker
        const completeness = data.completeness || 0;
        const categories = data.categories || {};
        
        const pctEl = document.getElementById('progress-pct');
        const barEl = document.getElementById('progress-bar-fill');
        if (pctEl) pctEl.textContent = Math.round(completeness * 100) + '%';
        if (barEl) barEl.style.width = Math.round(completeness * 100) + '%';
        
        // Update checklist
        const checklist = document.getElementById('progress-checklist');
        if (checklist) {
            checklist.querySelectorAll('li').forEach(li => {
                const cat = li.getAttribute('data-cat');
                if (cat && categories[cat]) {
                    li.classList.add('done');
                    li.querySelector('.check-icon').textContent = '✅';
                } else {
                    li.classList.remove('done');
                    li.querySelector('.check-icon').textContent = '⬜';
                }
            });
        }
        
        // Update complexity
        if (data.complexity !== undefined) {
            if (this.complexityCard) this.complexityCard.style.display = 'block';
            if (this.complexityScoreEl) this.complexityScoreEl.textContent = Math.round(data.complexity * 100) + '%';
        }
        
        // Update contradictions count
        if (data.contradictions && data.contradictions.length > 0) {
            if (this.contradictionCard) this.contradictionCard.style.display = 'block';
            if (this.contradictionCountEl) this.contradictionCountEl.textContent = data.contradictions.length;
        }
        
        // Update statement count
        if (data.statement_count !== undefined && this.statementCountEl) {
            this.statementCountEl.textContent = data.statement_count;
        }
        
        // Update evidence board
        this._renderEvidenceBoard(data.elements || [], data.contradictions || []);
    }
    
    _renderEvidenceBoard(elements, contradictions) {
        const container = document.getElementById('evidence-cards');
        if (!container) return;
        
        if (elements.length === 0) {
            container.innerHTML = '<p class="empty-state">Evidence will appear as you describe the scene</p>';
            return;
        }
        
        const typeIcons = {
            'vehicle': '🚗', 'person': '🧑', 'object': '📦', 'location_feature': '📍'
        };
        
        // Build contradiction lookup (element description -> old/new)
        const contradictionSet = new Set();
        (contradictions || []).forEach(c => {
            contradictionSet.add(c.element || '');
        });
        
        let html = '';
        elements.forEach(e => {
            const conf = e.confidence || 0.5;
            const confClass = conf > 0.7 ? 'high' : conf > 0.4 ? 'med' : 'low';
            const icon = typeIcons[e.type] || '❓';
            const isContradiction = contradictionSet.has(e.type + '_' + (e.description || '').substring(0, 30));
            const cardClass = isContradiction ? 'evidence-card contradiction' : 'evidence-card';
            
            let meta = '';
            if (e.color) meta += `🎨 ${e.color} `;
            if (e.position) meta += `📍 ${e.position} `;
            if (e.size) meta += `📐 ${e.size}`;
            
            html += `<div class="${cardClass}">
                <div><span class="ev-icon">${icon}</span><span class="ev-type">${e.type}</span></div>
                <div class="ev-desc">${this._escapeHtml(e.description || '')}</div>
                <div class="ev-meta">
                    <span class="confidence-dot ${confClass}"></span>${Math.round(conf * 100)}%
                    ${meta ? ' · ' + meta : ''}
                </div>
            </div>`;
        });
        
        container.innerHTML = html;
        
        // Update event timeline from conversation history
        this._updateEvidenceTimeline(elements);
    }
    
    _updateEvidenceTimeline(elements) {
        const tlContainer = document.getElementById('evidence-timeline');
        const eventsContainer = document.getElementById('timeline-events');
        if (!tlContainer || !eventsContainer) return;
        
        if (elements.length < 2) {
            tlContainer.style.display = 'none';
            return;
        }
        
        tlContainer.style.display = 'block';
        let html = '';
        elements.slice(0, 8).forEach((e, i) => {
            html += `<div class="timeline-event">
                <div class="te-marker"></div>
                <span>${e.description || e.type}</span>
            </div>`;
        });
        eventsContainer.innerHTML = html;
    }
    
    _initSuggestedActions() {
        document.querySelectorAll('.suggestion-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.getAttribute('data-action');
                let text = '';
                if (action === 'correct') text = 'I want to correct something about the scene.';
                else if (action === 'generate') text = 'Please generate the scene image now.';
                else if (action === 'details') text = 'I have more details to add about what I saw.';
                if (text && this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ type: 'text', data: { text } }));
                    this.displayMessage(text, 'user');
                }
            });
        });
    }
    
    setStatus(status) {
        // Deprecated - use this.ui.setStatus instead
        if (this.ui) {
            this.ui.setStatus(status);
        }
    }
    
    // Export functions
    async exportPDF() {
        if (!this.sessionId) {
            this.ui.showToast('No session to export', 'warning');
            return;
        }
        
        try {
            this.ui.showToast('Generating PDF...', 'info');
            const response = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/export/pdf`, {}, 30000); // 30s for PDF generation
            
            if (!response.ok) throw new Error('Export failed');
            
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `witness-replay-${this.sessionId.substring(0, 8)}.pdf`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            this.ui.showToast('PDF exported successfully!', 'success');
        } catch (error) {
            console.error('Export error:', error);
            this.ui.showToast('Failed to export PDF', 'error');
        }
    }
    
    async exportJSON() {
        if (!this.sessionId) {
            this.ui.showToast('No session to export', 'warning');
            return;
        }
        
        try {
            this.ui.showToast('Exporting JSON...', 'info');
            const response = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/export/json`);
            
            if (!response.ok) throw new Error('Export failed');
            
            const data = await response.json();
            const jsonStr = JSON.stringify(data, null, 2);
            const blob = new Blob([jsonStr], { type: 'application/json' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `witness-replay-${this.sessionId.substring(0, 8)}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            this.ui.showToast('JSON exported successfully!', 'success');
        } catch (error) {
            console.error('Export error:', error);
            this.ui.showToast('Failed to export JSON', 'error');
        }
    }
    
    async exportEvidence() {
        if (!this.sessionId) {
            this.ui.showToast('No session to export', 'warning');
            return;
        }
        
        try {
            this.ui.showToast('Generating evidence report...', 'info');
            const response = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/export/evidence`);
            
            if (!response.ok) throw new Error('Export failed');
            
            const data = await response.json();
            const jsonStr = JSON.stringify(data, null, 2);
            const blob = new Blob([jsonStr], { type: 'application/json' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `evidence-report-${this.sessionId.substring(0, 8)}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            this.ui.showToast('🔒 Evidence report generated successfully!', 'success');
        } catch (error) {
            console.error('Export error:', error);
            this.ui.showToast('Failed to export evidence report', 'error');
        }
    }
    
    downloadScene() {
        const img = this.sceneDisplay.querySelector('.scene-image');
        if (!img) {
            this.ui.showToast('No scene to download', 'warning');
            return;
        }
        
        const a = document.createElement('a');
        a.href = img.src;
        a.download = `scene-v${this.currentVersion}.png`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        
        this.ui.showToast('Scene downloaded!', 'success');
    }
    
    toggleZoom() {
        const img = this.sceneDisplay.querySelector('.scene-image');
        if (!img) return;
        
        if (img.style.transform === 'scale(1.5)') {
            img.style.transform = 'scale(1)';
            img.style.cursor = 'zoom-in';
        } else {
            img.style.transform = 'scale(1.5)';
            img.style.cursor = 'zoom-out';
        }
    }
    
    toggleFullscreen() {
        if (!document.fullscreenElement) {
            this.sceneDisplay.requestFullscreen().catch(err => {
                console.error('Fullscreen error:', err);
            });
        } else {
            document.exitFullscreen();
        }
    }
    
    // ======================================
    // Model Selector & Quota Dashboard
    // ======================================
    
    async showQuotaModal() {
        this.ui.showModal('quota-modal');
        
        // Show loading state
        const modelSelect = document.getElementById('model-select');
        const quotaContainer = document.querySelector('.quota-dashboard');
        
        if (modelSelect) {
            modelSelect.disabled = true;
            modelSelect.innerHTML = '<option>Loading models...</option>';
        }
        
        if (quotaContainer) {
            quotaContainer.style.opacity = '0.5';
        }
        
        // Load data with error handling
        try {
            await Promise.all([
                this.loadModels(),
                this.loadCurrentModel(),
                this.refreshQuota()
            ]);
        } catch (error) {
            console.error('Error loading quota modal data:', error);
            this.ui.showToast('Some data failed to load. Check console for details.', 'warning');
        } finally {
            if (modelSelect) {
                modelSelect.disabled = false;
            }
            if (quotaContainer) {
                quotaContainer.style.opacity = '1';
            }
        }
    }
    
    async loadModels() {
        const modelSelect = document.getElementById('model-select');
        
        try {
            const response = await this.fetchWithTimeout('/api/models');
            
            if (!response.ok) {
                throw new Error(`Server returned ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            if (!modelSelect) return;
            
            // Clear existing options
            modelSelect.innerHTML = '';
            
            if (!data.models || data.models.length === 0) {
                modelSelect.innerHTML = '<option>No models available</option>';
                return;
            }
            
            // Add models to dropdown
            data.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.name;
                option.textContent = `${model.display_name || model.name}`;
                
                // Add info about capabilities
                if (model.input_token_limit) {
                    option.textContent += ` (${(model.input_token_limit / 1000).toFixed(0)}k tokens)`;
                }
                
                modelSelect.appendChild(option);
            });
            
        } catch (error) {
            console.error('Error loading models:', error);
            
            // Provide fallback UI
            if (modelSelect) {
                modelSelect.innerHTML = '<option>Error loading models</option>';
            }
            
            // Show user-friendly error message
            const errorMsg = error.message.includes('timeout') 
                ? 'Server timeout - models are unavailable right now'
                : 'Failed to load models from server';
            
            this.ui.showToast(errorMsg, 'error', 5000);
        }
    }
    
    async loadCurrentModel() {
        try {
            const response = await this.fetchWithTimeout('/api/models/current');
            
            if (!response.ok) {
                throw new Error(`Server returned ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            const modelSelect = document.getElementById('model-select');
            
            if (modelSelect && data.gemini_model) {
                modelSelect.value = data.gemini_model;
            }
            
        } catch (error) {
            console.error('Error loading current model:', error);
            
            // Don't show toast for this - it's not critical
            // The model selector will just not have a pre-selected value
        }
    }
    
    async applyModelChange() {
        const modelSelect = document.getElementById('model-select');
        const applyBtn = document.getElementById('apply-model-btn');
        
        if (!modelSelect || !modelSelect.value) return;
        
        const newModel = modelSelect.value;
        
        try {
            applyBtn.disabled = true;
            applyBtn.textContent = 'Applying...';
            
            const response = await this.fetchWithTimeout('/api/models/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model_name: newModel })
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `Server returned ${response.status}`);
            }
            
            const data = await response.json();
            
            this.ui.showToast(
                `Model changed: ${data.previous_model} → ${data.new_model}`, 
                'success', 
                3000
            );
            
            applyBtn.textContent = 'Applied ✓';
            applyBtn.classList.add('apply-success');
            
            // Refresh quota after model change
            await this.refreshQuota();
            
            setTimeout(() => {
                applyBtn.textContent = 'Apply';
                applyBtn.disabled = true;
                applyBtn.classList.remove('apply-success');
            }, 2000);
            
        } catch (error) {
            console.error('Error applying model change:', error);
            
            const errorMsg = error.message.includes('timeout')
                ? 'Server timeout - please try again'
                : `Failed to change model: ${error.message}`;
            
            this.ui.showToast(errorMsg, 'error', 5000);
            applyBtn.textContent = 'Apply';
            applyBtn.disabled = false;
        }
    }
    
    async refreshQuota() {
        try {
            const response = await this.fetchWithTimeout('/api/models/quota');
            
            if (!response.ok) {
                throw new Error(`Server returned ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            // Update UI elements
            this.updateQuotaDisplay(data);
            
        } catch (error) {
            console.error('Error refreshing quota:', error);
            
            // Show placeholder/error state in quota dashboard
            this.updateQuotaDisplay({
                requests_per_minute: { used: 0, limit: 0, remaining: 0 },
                requests_per_day: { used: 0, limit: 0, remaining: 0 },
                tokens_per_day: { used: 0, limit: 0, remaining: 0 }
            });
            
            const errorMsg = error.message.includes('timeout')
                ? 'Server timeout - quota data unavailable'
                : 'Failed to refresh quota data';
            
            this.ui.showToast(errorMsg, 'error', 5000);
        }
    }
    
    updateQuotaDisplay(quotaData) {
        // Requests Per Minute
        const rpmUsed = quotaData.requests_per_minute?.used || 0;
        const rpmLimit = quotaData.requests_per_minute?.limit || 0;
        const rpmRemaining = quotaData.requests_per_minute?.remaining || 0;
        const rpmPercent = rpmLimit > 0 ? (rpmUsed / rpmLimit) * 100 : 0;
        
        document.getElementById('rpm-used').textContent = rpmUsed;
        document.getElementById('rpm-limit').textContent = rpmLimit;
        
        const rpmBar = document.getElementById('rpm-bar');
        const rpmBadge = document.getElementById('rpm-badge');
        
        if (rpmBar) {
            rpmBar.style.width = `${rpmPercent}%`;
            rpmBar.className = 'quota-bar';
            if (rpmPercent > 80) rpmBar.classList.add('danger');
            else if (rpmPercent > 60) rpmBar.classList.add('warning');
        }
        
        if (rpmBadge) {
            rpmBadge.textContent = `${rpmRemaining} left`;
            rpmBadge.className = 'quota-badge';
            if (rpmPercent > 80) rpmBadge.classList.add('danger');
            else if (rpmPercent > 60) rpmBadge.classList.add('warning');
        }
        
        // Requests Per Day
        const rpdUsed = quotaData.requests_per_day?.used || 0;
        const rpdLimit = quotaData.requests_per_day?.limit || 0;
        const rpdRemaining = quotaData.requests_per_day?.remaining || 0;
        const rpdPercent = rpdLimit > 0 ? (rpdUsed / rpdLimit) * 100 : 0;
        
        document.getElementById('rpd-used').textContent = rpdUsed;
        document.getElementById('rpd-limit').textContent = rpdLimit;
        
        const rpdBar = document.getElementById('rpd-bar');
        const rpdBadge = document.getElementById('rpd-badge');
        
        if (rpdBar) {
            rpdBar.style.width = `${rpdPercent}%`;
            rpdBar.className = 'quota-bar';
            if (rpdPercent > 80) rpdBar.classList.add('danger');
            else if (rpdPercent > 60) rpdBar.classList.add('warning');
        }
        
        if (rpdBadge) {
            rpdBadge.textContent = `${rpdRemaining} left`;
            rpdBadge.className = 'quota-badge';
            if (rpdPercent > 80) rpdBadge.classList.add('danger');
            else if (rpdPercent > 60) rpdBadge.classList.add('warning');
        }
        
        // Tokens Per Day
        const tpdUsed = quotaData.tokens_per_day?.used || 0;
        const tpdLimit = quotaData.tokens_per_day?.limit || 0;
        const tpdRemaining = quotaData.tokens_per_day?.remaining || 0;
        const tpdPercent = tpdLimit > 0 ? (tpdUsed / tpdLimit) * 100 : 0;
        
        // Format large numbers (e.g., 15000000 -> 15M)
        const formatNumber = (num) => {
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
            return num.toString();
        };
        
        document.getElementById('tpd-used').textContent = formatNumber(tpdUsed);
        document.getElementById('tpd-limit').textContent = formatNumber(tpdLimit);
        
        const tpdBar = document.getElementById('tpd-bar');
        const tpdBadge = document.getElementById('tpd-badge');
        
        if (tpdBar) {
            tpdBar.style.width = `${tpdPercent}%`;
            tpdBar.className = 'quota-bar';
            if (tpdPercent > 80) tpdBar.classList.add('danger');
            else if (tpdPercent > 60) tpdBar.classList.add('warning');
        }
        
        if (tpdBadge) {
            tpdBadge.textContent = `${formatNumber(tpdRemaining)} left`;
            tpdBadge.className = 'quota-badge';
            if (tpdPercent > 80) tpdBadge.classList.add('danger');
            else if (tpdPercent > 60) tpdBadge.classList.add('warning');
        }
        
        // Show warning banner if any quota is near limit
        this.updateQuotaWarningBanner(rpmPercent, rpdPercent, tpdPercent);
    }
    
    updateQuotaWarningBanner(rpmPercent, rpdPercent, tpdPercent) {
        const maxPercent = Math.max(rpmPercent, rpdPercent, tpdPercent);
        const quotaDashboard = document.querySelector('.quota-dashboard');
        
        if (!quotaDashboard) return;
        
        // Remove existing warning banner
        const existingBanner = quotaDashboard.querySelector('.quota-warning-banner');
        if (existingBanner) {
            existingBanner.remove();
        }
        
        // Add warning if quota is above 80%
        if (maxPercent > 80) {
            const banner = document.createElement('div');
            banner.className = 'quota-warning-banner';
            banner.innerHTML = `
                <h4>⚠️ Quota Alert</h4>
                <p>You're approaching your quota limit. Consider upgrading to a paid tier for higher limits.</p>
            `;
            quotaDashboard.insertBefore(banner, quotaDashboard.firstChild);
        }
    }
    
    async showAnalyticsModal() {
        this.ui.showModal('analytics-modal');
        
        try {
            // Load both regular analytics and session insights
            const [statsResponse, insightsResponse, timelineResponse] = await Promise.all([
                this.fetchWithTimeout('/api/analytics/stats').catch(() => null),
                this.sessionId ? this.fetchWithTimeout(`/api/sessions/${this.sessionId}/insights`).catch(() => null) : null,
                this.sessionId ? this.fetchWithTimeout(`/api/sessions/${this.sessionId}/timeline`).catch(() => null) : null
            ]);
            
            // Handle regular analytics
            if (statsResponse && statsResponse.ok) {
                const data = await statsResponse.json();
                
                // Update overall statistics
                document.getElementById('analytics-total-sessions').textContent = data.total_sessions || 0;
                document.getElementById('analytics-active-sessions').textContent = data.active_sessions || 0;
                document.getElementById('analytics-total-scenes').textContent = data.total_scenes_generated || 0;
                
                // Format average duration
                const avgDuration = data.avg_session_duration_minutes || 0;
                const durationText = avgDuration < 1 
                    ? '<1m' 
                    : avgDuration >= 60 
                        ? `${Math.floor(avgDuration / 60)}h ${Math.round(avgDuration % 60)}m`
                        : `${Math.round(avgDuration)}m`;
                document.getElementById('analytics-avg-duration').textContent = durationText;
                
                // Element insights
                if (data.top_elements && data.top_elements.length > 0) {
                    const topElements = data.top_elements.slice(0, 5).map(e => e.type).join(', ');
                    document.getElementById('analytics-top-elements').textContent = topElements;
                } else {
                    document.getElementById('analytics-top-elements').textContent = 'No data yet';
                }
                
                const avgConf = data.avg_confidence || 0;
                document.getElementById('analytics-avg-confidence').textContent = 
                    avgConf > 0 ? `${Math.round(avgConf * 100)}%` : 'N/A';
            }
            
            // Handle session insights (NEW!)
            if (insightsResponse && insightsResponse.ok) {
                const insights = await insightsResponse.json();
                this._displaySessionInsights(insights);
            }
            
            // Handle timeline events (NEW!)
            if (timelineResponse && timelineResponse.ok) {
                const timeline = await timelineResponse.json();
                this._displaySessionTimeline(timeline);
            }
            
        } catch (error) {
            console.error('Error loading analytics:', error);
            this.ui.showToast('Failed to load analytics data', 'error');
        }
    }
    
    _displaySessionInsights(insights) {
        // Add a new section to the analytics modal for session-specific insights
        const analyticsModal = document.querySelector('#analytics-modal .analytics-dashboard');
        if (!analyticsModal) return;
        
        // Remove existing insights section if any
        const existingSection = analyticsModal.querySelector('.session-insights-section');
        if (existingSection) {
            existingSection.remove();
        }
        
        const insightsSection = document.createElement('div');
        insightsSection.className = 'session-insights-section';
        insightsSection.innerHTML = `
            <h3 style="margin-top: 2rem;">🔍 Current Session Insights</h3>
            <div class="insight-cards">
                <div class="insight-card">
                    <div class="insight-icon">📊</div>
                    <div class="insight-title">Quality Score</div>
                    <div class="insight-value">${Math.round((insights.quality_score || 0) * 100)}%</div>
                </div>
                <div class="insight-card">
                    <div class="insight-icon">📝</div>
                    <div class="insight-title">Completeness</div>
                    <div class="insight-value">${Math.round((insights.completeness || 0) * 100)}%</div>
                </div>
                <div class="insight-card ${insights.contradictions_count > 0 ? 'warning' : ''}">
                    <div class="insight-icon">⚠️</div>
                    <div class="insight-title">Contradictions</div>
                    <div class="insight-value">${insights.contradictions_count || 0}</div>
                </div>
            </div>
            ${insights.recommendations && insights.recommendations.length > 0 ? `
                <div class="recommendations">
                    <h4>💡 Recommendations</h4>
                    <ul>
                        ${insights.recommendations.map(r => `<li>${this._escapeHtml(r)}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}
        `;
        
        analyticsModal.appendChild(insightsSection);
    }
    
    _displaySessionTimeline(timeline) {
        // Add timeline visualization to analytics modal
        const analyticsModal = document.querySelector('#analytics-modal .analytics-dashboard');
        if (!analyticsModal) return;
        
        // Remove existing timeline section if any
        const existingSection = analyticsModal.querySelector('.session-timeline-section');
        if (existingSection) {
            existingSection.remove();
        }
        
        const timelineSection = document.createElement('div');
        timelineSection.className = 'session-timeline-section';
        
        let timelineHTML = '<h3 style="margin-top: 2rem;">⏱️ Session Timeline</h3>';
        
        if (timeline.events && timeline.events.length > 0) {
            timelineHTML += '<div class="timeline-events-list">';
            timeline.events.forEach(event => {
                const icon = event.type === 'statement' ? '💬' : event.type === 'scene_generation' ? '🎬' : '📌';
                timelineHTML += `
                    <div class="timeline-event-item">
                        <div class="event-icon">${icon}</div>
                        <div class="event-details">
                            <div class="event-type">${event.type.replace('_', ' ')}</div>
                            <div class="event-time">${event.timestamp}</div>
                            ${event.delta_seconds ? `<div class="event-delta">+${Math.round(event.delta_seconds)}s</div>` : ''}
                        </div>
                    </div>
                `;
            });
            timelineHTML += '</div>';
        } else {
            timelineHTML += '<p class="empty-state">No timeline events yet</p>';
        }
        
        timelineSection.innerHTML = timelineHTML;
        analyticsModal.appendChild(timelineSection);
    }
    
    async showInfoModal() {
        this.ui.showModal('info-modal');
        
        try {
            const response = await this.fetchWithTimeout('/api/info');
            
            if (!response.ok) {
                throw new Error('Failed to load server info');
            }
            
            const data = await response.json();
            
            // System status
            document.getElementById('info-version').textContent = data.version || '1.0.0';
            document.getElementById('info-env').textContent = data.environment || 'unknown';
            document.getElementById('info-python').textContent = data.python_version || 'unknown';
            document.getElementById('info-debug').textContent = data.debug ? 'Enabled' : 'Disabled';
            
            // Configuration
            document.getElementById('info-model').textContent = data.config?.gemini_model || 'unknown';
            document.getElementById('info-rate-limit').textContent = 
                data.config?.enforce_rate_limits ? 'Enabled' : 'Disabled';
            
            // Feature badges
            const featureBadges = document.getElementById('feature-badges');
            if (featureBadges && data.features) {
                featureBadges.innerHTML = '';
                
                const features = [
                    { key: 'voice_recording', label: '🎤 Voice Recording', icon: '🎤' },
                    { key: 'scene_generation', label: '🖼️ Scene Generation', icon: '🖼️' },
                    { key: 'firestore', label: '💾 Cloud Storage', icon: '💾' },
                    { key: 'websocket', label: '🔌 Real-time WebSocket', icon: '🔌' },
                    { key: 'pdf_export', label: '📄 PDF Export', icon: '📄' },
                    { key: 'analytics', label: '📊 Analytics', icon: '📊' },
                    { key: 'evidence_export', label: '🔒 Evidence Export', icon: '🔒' }
                ];
                
                features.forEach(feature => {
                    const enabled = data.features[feature.key];
                    const badge = document.createElement('div');
                    badge.className = `feature-badge${enabled ? '' : ' disabled'}`;
                    badge.innerHTML = `<span class="badge-icon">${enabled ? '✓' : '✗'}</span> ${feature.label}`;
                    featureBadges.appendChild(badge);
                });
            }
            
        } catch (error) {
            console.error('Error loading server info:', error);
            this.ui.showToast('Failed to load server information', 'error');
        }
    }
    
    // ======================================
    // Keyboard Shortcuts Overlay
    // ======================================
    
    showShortcuts() {
        const overlay = document.getElementById('shortcuts-overlay');
        if (overlay) {
            overlay.classList.remove('hidden');
            this.playSound('click');
        }
    }
    
    hideShortcuts() {
        const overlay = document.getElementById('shortcuts-overlay');
        if (overlay) {
            overlay.classList.add('hidden');
        }
    }
    
    // ======================================
    // Version Display
    // ======================================
    
    async fetchAndDisplayVersion() {
        try {
            const response = await this.fetchWithTimeout('/api/version', {}, 5000);
            if (!response.ok) {
                console.error('Failed to fetch version');
                return;
            }
            const data = await response.json();
            const versionEl = document.querySelector('.version-number');
            if (versionEl && data.version) {
                versionEl.textContent = data.version;
            }
        } catch (error) {
            console.error('Error fetching version:', error);
            // Keep default version shown in HTML
        }
    }
    
    // ======================================
    // Enhanced Scene Loading with Skeleton
    // ======================================
    
    showSceneLoadingSkeleton() {
        // Create skeleton loader for scene
        this.sceneDisplay.innerHTML = `
            <div class="scene-skeleton">
                <div class="skeleton-shimmer"></div>
                <div class="skeleton-overlay">
                    <div class="loading-spinner"></div>
                    <p>Generating scene...</p>
                </div>
            </div>
        `;
    }
    
    // ======================================
    // Enhanced Error Messages
    // ======================================
    
    showConnectionError(message = 'Connection interrupted') {
        this.ui.showToast(
            `⚠️ ${message} — Detective Ray is reconnecting...`,
            'error',
            5000
        );
    }
    
    showTimeoutError(endpoint = 'server') {
        this.ui.showToast(
            `⏱️ Request timeout — ${endpoint} took too long to respond`,
            'error',
            6000
        );
    }
    
    /**
     * Check if user has seen onboarding before
     */
    checkOnboarding() {
        const hasSeenOnboarding = localStorage.getItem('hasSeenOnboarding');
        if (!hasSeenOnboarding) {
            setTimeout(() => {
                this.showOnboardingModal();
            }, 1000); // Show after 1 second delay
        }
    }
    
    /**
     * Show onboarding modal for first-time users
     */
    showOnboardingModal() {
        const modal = document.getElementById('onboarding-modal');
        if (!modal) return;
        
        modal.classList.remove('hidden');
        
        // Start button
        const startBtn = document.getElementById('onboarding-start-btn');
        if (startBtn) {
            startBtn.onclick = () => {
                const dontShowAgain = document.getElementById('dont-show-onboarding');
                if (dontShowAgain && dontShowAgain.checked) {
                    localStorage.setItem('hasSeenOnboarding', 'true');
                }
                modal.classList.add('hidden');
                this.ui.showToast('🎙️ Ready to start! Press Space to record', 'info', 3000);
            };
        }
        
        // Close on escape
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                modal.classList.add('hidden');
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    }
    
    /**
     * Initialize particle background effect
     */
    initializeParticles() {
        const canvas = document.getElementById('particle-canvas');
        if (!canvas) return;
        
        const ctx = canvas.getContext('2d');
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        
        const particles = [];
        const particleCount = 50;
        
        // Create particles
        for (let i = 0; i < particleCount; i++) {
            particles.push({
                x: Math.random() * canvas.width,
                y: Math.random() * canvas.height,
                vx: (Math.random() - 0.5) * 0.5,
                vy: (Math.random() - 0.5) * 0.5,
                radius: Math.random() * 2 + 1
            });
        }
        
        // Animation loop
        const animate = () => {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            // Draw particles
            particles.forEach(p => {
                // Move particle
                p.x += p.vx;
                p.y += p.vy;
                
                // Wrap around screen
                if (p.x < 0) p.x = canvas.width;
                if (p.x > canvas.width) p.x = 0;
                if (p.y < 0) p.y = canvas.height;
                if (p.y > canvas.height) p.y = 0;
                
                // Draw particle
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(0, 212, 255, 0.3)';
                ctx.fill();
            });
            
            // Draw connections
            for (let i = 0; i < particles.length; i++) {
                for (let j = i + 1; j < particles.length; j++) {
                    const dx = particles[i].x - particles[j].x;
                    const dy = particles[i].y - particles[j].y;
                    const distance = Math.sqrt(dx * dx + dy * dy);
                    
                    if (distance < 150) {
                        ctx.beginPath();
                        ctx.moveTo(particles[i].x, particles[i].y);
                        ctx.lineTo(particles[j].x, particles[j].y);
                        ctx.strokeStyle = `rgba(0, 212, 255, ${0.15 * (1 - distance / 150)})`;
                        ctx.lineWidth = 0.5;
                        ctx.stroke();
                    }
                }
            }
            
            requestAnimationFrame(animate);
        };
        
        animate();
        
        // Resize handler
        window.addEventListener('resize', () => {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        });
    }
    
    /**
     * Initialize scene zoom and pan functionality
     */
    initializeSceneZoom() {
        const zoomBtn = document.getElementById('zoom-btn');
        const sceneDisplay = document.getElementById('scene-display');
        
        if (!zoomBtn || !sceneDisplay) return;
        
        let isZoomed = false;
        let scale = 1;
        let panX = 0;
        let panY = 0;
        let isDragging = false;
        let startX = 0;
        let startY = 0;
        
        zoomBtn.addEventListener('click', () => {
            isZoomed = !isZoomed;
            
            if (isZoomed) {
                scale = 2;
                sceneDisplay.classList.add('zoomed');
                zoomBtn.textContent = '🔍-';
                zoomBtn.setAttribute('data-tooltip', 'Zoom Out');
            } else {
                scale = 1;
                panX = 0;
                panY = 0;
                sceneDisplay.classList.remove('zoomed');
                zoomBtn.textContent = '🔍';
                zoomBtn.setAttribute('data-tooltip', 'Zoom In');
            }
            
            this.updateSceneTransform(scale, panX, panY);
        });
        
        // Pan on drag
        sceneDisplay.addEventListener('mousedown', (e) => {
            if (!isZoomed) return;
            isDragging = true;
            startX = e.clientX - panX;
            startY = e.clientY - panY;
            sceneDisplay.style.cursor = 'grabbing';
        });
        
        document.addEventListener('mousemove', (e) => {
            if (!isDragging || !isZoomed) return;
            panX = e.clientX - startX;
            panY = e.clientY - startY;
            this.updateSceneTransform(scale, panX, panY);
        });
        
        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                sceneDisplay.style.cursor = 'grab';
            }
        });
        
        // Wheel zoom
        sceneDisplay.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY > 0 ? -0.1 : 0.1;
            scale = Math.max(1, Math.min(3, scale + delta));
            
            if (scale === 1) {
                panX = 0;
                panY = 0;
                isZoomed = false;
                sceneDisplay.classList.remove('zoomed');
                zoomBtn.textContent = '🔍';
            } else {
                isZoomed = true;
                sceneDisplay.classList.add('zoomed');
                zoomBtn.textContent = '🔍-';
            }
            
            this.updateSceneTransform(scale, panX, panY);
        });
    }
    
    /**
     * Update scene transform for zoom/pan
     */
    updateSceneTransform(scale, panX, panY) {
        const sceneImage = this.sceneDisplay.querySelector('img');
        if (sceneImage) {
            sceneImage.style.transform = `scale(${scale}) translate(${panX / scale}px, ${panY / scale}px)`;
        }
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new WitnessReplayApp();
});
