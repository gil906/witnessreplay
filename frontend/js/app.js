/**
 * WitnessReplay - Main Application
 * Enhanced with Detective Ray persona, professional UI, and comprehensive features
 */

window.addEventListener('error', (e) => {
    console.error('Global error:', e.error);
    if (e.message?.includes('ResizeObserver') || e.message?.includes('Script error')) return;
});

window.addEventListener('unhandledrejection', (e) => {
    console.error('Unhandled promise rejection:', e.reason);
    e.preventDefault();
});

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
        this._reconnectAttempt = 0;
        this._maxReconnectDelay = 30000;
        this.connectionStatus = 'connecting';
        this.reconnectTimer = null;
        this.hasReceivedGreeting = false;
        this.lastUserMessage = '';
        this.autoScrollEnabled = localStorage.getItem('witnessreplay-auto-scroll') !== 'false';
        this.compactMode = localStorage.getItem('witnessreplay-compact-chat') === 'true';
        this.fetchTimeout = 10000; // 10 second timeout for API calls
        this.audioOutputDisabled = localStorage.getItem('audioOutputDisabled') === 'true';
        this.soundEnabled = !this.audioOutputDisabled && localStorage.getItem('soundEnabled') !== 'false'; // Default true
        this.sounds = {}; // Sound effect cache
        this.comparisonMode = false; // Scene comparison mode
        this.previousSceneUrl = null; // For before/after comparison
        this.streamingMessages = {}; // Track streaming messages by ID
        this.templates = []; // Interview templates cache
        this.selectedTemplateId = null; // Selected template for new session
        
        // Multi-witness support
        this.witnesses = []; // List of witnesses in current session
        this.activeWitnessId = null; // Currently active witness for statements
        
        // Voice Activity Detection (VAD)
        this.vad = null;
        this.vadEnabled = localStorage.getItem('vadEnabled') === 'true';
        this.vadListening = false;
        this.vadAutoRecording = false;
        
        // Text-to-Speech (TTS) for accessibility
        this.ttsPlayer = null;
        this.initializeTTS();
        
        // Voice conversation mode — auto-listen ON by default
        this.autoListenEnabled = localStorage.getItem('autoListenEnabled') !== 'false';
        this._isSpeakingResponse = false;
        this._autoListenTimer = null;
        this._recordingTrigger = 'manual';
        this._autoListenPausedUntilManual = false;
        this._lastVoiceHintState = null;
        this._lastVoiceHintToastAt = 0;
        this._micPermissionGranted = false; // Track if user has granted mic permission via gesture
        this.conversationState = 'ready';
        this.lastAgentMessage = '';
        this._rayListeningCueTimer = null;
        this._sceneUpdatePulseTimer = null;
        this._mobileVoiceHelpEscHandler = null;
        this._mobileTimerObserver = null;
        this.isMobileVoiceUI = window.matchMedia('(max-width: 768px)').matches;
        this.lastCallMetrics = null;
        this._isPageClosing = false;
        this._pageLifecycleHandler = null;
        
        // Interview Comfort Manager
        this.comfortManager = null;
        
        // Feature 6: Emotion detection
        this.emotionEmojis = { distressed: '😰', angry: '😠', confused: '😕', sad: '😢', anxious: '😟', neutral: '😐' };
        
        // Feature 7: Guided walkthrough mode
        this.guidedMode = false;
        this.guidedStep = 0;
        this.guidedQuestions = [
            "Let's start. What type of incident are you reporting? (accident, assault, theft, vandalism, other)",
            "Where did this happen? Please describe the location as specifically as you can.",
            "When did this happen? The date and approximate time.",
            "What did you see? Describe what happened from the beginning.",
            "How many people were involved? Describe each person you saw.",
            "Were there any vehicles involved? Describe them.",
            "Is there anything else important you'd like to add?"
        ];
        
        // Feature 9: Child-friendly mode
        this.childMode = false;
        
        try {
        this.initializeUI();
        this.initializeAudio();
        this.initializeVAD();
        this.initializeModals();
        this.initializeSounds();
        this.initializeParticles();
        this.initializeSceneZoom();
        this.initializeMeasurementTool();
        this.initializeEvidenceMarkerTool();
        this.initializeWitnessTabs(); // Initialize multi-witness UI
        this.initializeComfortFeatures(); // Initialize interview comfort features
        this.initializeLanguageSelector(); // Initialize translation language selector
        this.fetchAndDisplayVersion(); // Fetch version from API
        this._initOfflineQueue(); // Initialize offline message queue
        this._initPageLifecycleHandlers(); // Stop session cleanly on tab close
        this._initAutoTheme(); // Auto dark/light theme detection
        this._initCommandPalette(); // Feature 49: Command palette (Ctrl+K)
        this._initAutoSave(); // Auto-save interview progress
        this._initSessionNotes(); // Session notes panel
        this._initInterviewStatsBadge(); // Interview stats badge in header
        this._initExportChatBtn(); // Export chat transcript button
        this._initFocusMode(); // Focus mode indicator
        this._initChatSearch(); // Chat message search overlay
        this._initMessagePinning(); // Pin/bookmark important messages
        this._initAutoSaveIndicator(); // Save state indicator
        this._initMessageDoubleClickCopy(); // Double-click to copy messages
        this._initPhaseProgressBar(); // Interview phase progress bar
        this._initSmartPlaceholder(); // Smart dynamic input placeholder
        this._initSessionTimer(); // Session duration live timer
        this._initQualityScore(); // Interview quality score widget
        this._initInfoChecklist(); // Interview info checklist
        this._initScrollNav(); // Scroll navigation buttons
        this._initWitnessProfileCard(); // Witness profile card
        this._initContextMenu(); // Message context menu
        this._initQuickTemplates(); // Quick incident templates
        this._initCredibilityGauge(); // Witness credibility score gauge
        this._initAutoSummaryTracker(); // Auto-summary after N messages
        
        // Show onboarding for first-time users
        this.checkOnboarding();
        this._showOnboardingTour(); // Feature 46: One-time welcome tour
        
        // Initialize connection status popup
        this.initializeConnectionPopup();
        
        // Auto-create session on page load so WebSocket connects immediately
        this.connectionError = null;
        this._autoCreateSession();
        
        // Global keyboard handler for modals
        this._initModalKeyboardNav();
        } catch(e) {
            console.error('App initialization error:', e);
            document.body.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;font-family:system-ui;color:#e2e8f0;background:#0a0a0f;padding:20px;"><div><h2>⚠️ Something went wrong</h2><p style="color:#94a3b8;">WitnessReplay couldn't start properly.</p><button style="background:#3b82f6;color:white;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;margin-top:12px;" onclick="location.reload()">Reload</button></div></div>`;
        }
    }
    
    _initModalKeyboardNav() {
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                // Close modals in priority order
                const commandPalette = document.getElementById('command-palette');
                if (commandPalette) { commandPalette.remove(); return; }
                const tourOverlay = document.getElementById('tour-overlay');
                if (tourOverlay) { tourOverlay.remove(); localStorage.setItem('wr_tour_done', 'true'); return; }
                const feedbackModal = document.querySelector('.feedback-modal-overlay');
                if (feedbackModal) { feedbackModal.remove(); return; }
            }
        });
    }
    
    _initAutoTheme() {
        const saved = localStorage.getItem('wr_theme');
        if (!saved || saved === 'auto') {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');
            this._applyTheme(prefersDark.matches ? 'dark' : 'light');
            prefersDark.addEventListener('change', (e) => {
                if (localStorage.getItem('wr_theme') === 'auto' || !localStorage.getItem('wr_theme')) {
                    this._applyTheme(e.matches ? 'dark' : 'light');
                }
            });
        }
    }

    _applyTheme(theme) {
        document.body.classList.toggle('light-mode', theme === 'light');
        document.body.classList.toggle('dark-mode', theme === 'dark');
    }

    _initOfflineQueue() {
        this.offlineQueue = [];
        window.addEventListener('online', () => this._flushOfflineQueue());
    }

    _initPageLifecycleHandlers() {
        if (this._pageLifecycleHandler) return;
        this._pageLifecycleHandler = () => this._handlePageClose();
        window.addEventListener('pagehide', this._pageLifecycleHandler);
        window.addEventListener('beforeunload', this._pageLifecycleHandler);
    }

    _handlePageClose() {
        if (this._isPageClosing) return;
        this._isPageClosing = true;

        // Clean up all intervals to prevent memory leaks
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.durationTimer) {
            clearInterval(this.durationTimer);
            this.durationTimer = null;
        }
        if (this._autoSaveInterval) {
            clearInterval(this._autoSaveInterval);
            this._autoSaveInterval = null;
        }
        if (this._autoListenTimer) {
            clearTimeout(this._autoListenTimer);
            this._autoListenTimer = null;
        }

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
                this.ws.close(1000, 'tab closing');
            } catch (_) {}
        }

        if (!this.sessionId) return;
        const closeUrl = `/api/sessions/${this.sessionId}/close?reason=tab_close`;

        try {
            if (navigator.sendBeacon) {
                const payload = new Blob([], { type: 'application/json' });
                navigator.sendBeacon(closeUrl, payload);
                return;
            }
        } catch (error) {
            console.debug('Session close beacon failed:', error);
        }

        fetch(closeUrl, { method: 'POST', keepalive: true }).catch(() => {});
    }

    _queueOfflineMessage(data) {
        this.offlineQueue.push(data);
        localStorage.setItem('wr_offline_queue', JSON.stringify(this.offlineQueue));
        this.ui?.showToast('📴 Message saved offline. Will send when connected.', 'info', 3000);
    }

    async _flushOfflineQueue() {
        const stored = localStorage.getItem('wr_offline_queue');
        if (stored) {
            try { this.offlineQueue = JSON.parse(stored); } catch(e) { this.offlineQueue = []; }
        }
        if (!this.offlineQueue.length) return;
        this.ui?.showToast('🔄 Sending offline messages...', 'info', 2000);
        for (const msg of this.offlineQueue) {
            if (this.ws?.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify(msg));
                await new Promise(r => setTimeout(r, 500));
            }
        }
        this.offlineQueue = [];
        localStorage.removeItem('wr_offline_queue');
    }

    async _autoCreateSession() {
        this.connectionSteps = [];
        this._addConnectionStep('Initializing...');
        this.updateConnectionStatus('connecting');
        this._updateMicState('connecting');
        try {
            // Check for interview link token/session params
            const urlParams = new URLSearchParams(window.location.search);
            const tokenParam = urlParams.get('token');
            const sessionParam = urlParams.get('session');
            if (tokenParam && sessionParam) {
                this._addConnectionStep('Joining interview session...');
                this.sessionId = sessionParam;
                this.sessionIdEl.textContent = `Session: ${sessionParam.substring(0, 8)}...`;
                this.sessionStartTime = Date.now();
                this.startDurationTimer();
                await this.loadVoicePreferencesFromSession();
                this.syncVoicePreferencesToSession();
                this.connectWebSocket();
                return;
            }
            this._addConnectionStep('Creating session...');
            await this._createSessionWithTemplate(null);
        } catch (error) {
            console.error('Auto-create session failed:', error);
            this.connectionError = error.message || 'Failed to connect';
            this._addConnectionStep(`❌ ${error.message || 'Failed'}`);
            this.updateConnectionStatus('disconnected');
            this._updateMicState('disconnected');
        }
    }
    
    _addConnectionStep(text) {
        if (!this.connectionSteps) this.connectionSteps = [];
        this.connectionSteps.push({ time: new Date().toLocaleTimeString(), text });
        const stepsEl = document.getElementById('popup-steps');
        if (stepsEl) {
            stepsEl.innerHTML = this.connectionSteps.map(s => 
                `<div class="step-line"><span class="step-time">${s.time}</span> ${this._sanitizeHTML(s.text)}</div>`
            ).join('');
        }
    }
    
    initializeConnectionPopup() {
        const indicator = document.getElementById('connection-status');
        const popup = document.getElementById('connection-popup');
        const retryBtn = document.getElementById('popup-retry-btn');
        
        if (indicator) {
            indicator.addEventListener('click', (e) => {
                e.stopPropagation();
                indicator.classList.toggle('popup-open');
            });
            indicator.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    indicator.classList.toggle('popup-open');
                }
            });
        }
        
        // Close popup on outside click
        document.addEventListener('click', () => {
            if (indicator) indicator.classList.remove('popup-open');
        });
        if (popup) {
            popup.addEventListener('click', (e) => e.stopPropagation());
        }
        
        if (retryBtn) {
            retryBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (indicator) indicator.classList.remove('popup-open');
                this._reconnectAttempt = 0;
                this.connectionError = null;
                this._autoCreateSession();
            });
        }
    }
    
    _updateMicState(state) {
        const micBtn = this.micBtn;
        const hint = document.getElementById('mic-status-hint');
        const btnText = micBtn?.querySelector('.btn-text');
        if (!micBtn) return;
        
        micBtn.classList.remove('connecting', 'disconnected');
        
        switch (state) {
            case 'connecting':
                micBtn.disabled = true;
                micBtn.classList.add('connecting');
                if (btnText) btnText.textContent = 'Connecting...';
                if (hint) { hint.textContent = 'Setting up session'; hint.style.display = ''; }
                this.voiceDockMicBtn && (this.voiceDockMicBtn.disabled = true);
                break;
            case 'connected':
                micBtn.disabled = false;
                if (btnText) btnText.textContent = 'Tap to Report';
                if (hint) hint.style.display = 'none';
                this._setConversationState('ready', { silent: true });
                break;
            case 'disconnected':
                micBtn.disabled = false;
                micBtn.classList.add('disconnected');
                if (btnText) btnText.textContent = 'Tap to reconnect';
                if (hint) { hint.textContent = 'Connection lost'; hint.style.display = ''; }
                this._setConversationState('ready', { silent: true });
                // Override click to reconnect
                break;
        }
        this._syncVoiceDockMicLabel();
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
        this.ui.soundEnabled = !this.audioOutputDisabled && this.soundEnabled;
        
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
        this.charCounter = document.getElementById('text-char-counter');
        this.retryLastBtn = document.getElementById('retry-last-btn');
        this.autoScrollToggleBtn = document.getElementById('auto-scroll-toggle');
        this.compactModeBtn = document.getElementById('compact-mode-toggle');
        this.connectionQualityBadge = document.getElementById('connection-quality-badge');
        this.anonymousToggle = document.getElementById('witness-anonymous-toggle');
        this.mobileCallStateChip = document.getElementById('mobile-call-state-chip');
        this.mobileCallSpeakerChip = document.getElementById('mobile-call-speaker-chip');
        this.mobileCallAutoListenChip = document.getElementById('mobile-call-autolisten-chip');
        this.mobileCallElapsed = document.getElementById('mobile-call-elapsed');
        this.mobileCallHelpBtn = document.getElementById('mobile-call-help-btn');
        this.mobileVoiceHelpModal = document.getElementById('mobile-voice-help-modal');
        this.mobileVoiceHelpCloseBtn = document.getElementById('mobile-voice-help-close-btn');
        this.mobileVoiceHelpCloseX = document.getElementById('mobile-voice-help-close-x');
        this.quickPhraseRail = document.getElementById('quick-phrase-rail');
        this.voiceDock = document.getElementById('voice-dock');
        this.voiceDockMicBtn = document.getElementById('voice-dock-mic-btn');
        this.voiceDockMicText = document.getElementById('voice-dock-mic-text');
        this.dockRepeatBtn = document.getElementById('dock-repeat-btn');
        this.dockSlowBtn = document.getElementById('dock-slow-btn');
        this.dockMomentBtn = document.getElementById('dock-moment-btn');
        this.dockMoreBtn = document.getElementById('dock-more-btn');
        this.dockMorePanel = document.getElementById('voice-dock-more-panel');
        this.dockHelpBtn = document.getElementById('dock-help-btn');
        this.dockAutoBtn = document.getElementById('dock-auto-btn');
        this.dockAudioToggleBtn = document.getElementById('dock-audio-toggle-btn');
        this.dockSpeed09Btn = document.getElementById('dock-speed-09-btn');
        this.dockSpeed10Btn = document.getElementById('dock-speed-10-btn');
        this.dockSpeed11Btn = document.getElementById('dock-speed-11-btn');
        this.tapInterruptAffordance = document.getElementById('tap-interrupt-affordance');
        this.tapInterruptBtn = document.getElementById('tap-interrupt-btn');
        this.mobileSceneStripSubtitle = document.getElementById('mobile-scene-strip-subtitle');
        this.mobileSceneUpdateIndicator = document.getElementById('mobile-scene-update-indicator');
        this.rayListeningCue = document.getElementById('ray-listening-cue');
        this.mobileVoiceCoachmark = document.getElementById('mobile-voice-coachmark');
        this.mobileVoiceCoachmarkDismiss = document.getElementById('mobile-voice-coachmark-dismiss');
        
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
        this.textInput.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault();
            }
            this.sendTextMessage();
        });
        this.textInput.addEventListener('input', () => { this._updateCharCounter(); this._showSlashHint(); });
        this.newSessionBtn.addEventListener('click', () => this.createNewSession());
        this.sessionsListBtn.addEventListener('click', () => this.showSessionsList());
        this.helpBtn.addEventListener('click', () => this.ui.showOnboarding());
        
        // Chat mic button
        this.chatMicBtn = document.getElementById('chat-mic-btn');
        if (this.chatMicBtn) {
            this.chatMicBtn.addEventListener('click', () => this.toggleRecording());
        }
        if (this.retryLastBtn) {
            this.retryLastBtn.addEventListener('click', () => this.retryLastMessage());
        }
        if (this.autoScrollToggleBtn) {
            this.autoScrollToggleBtn.addEventListener('click', () => this.toggleAutoScroll());
        }
        if (this.compactModeBtn) {
            this.compactModeBtn.addEventListener('click', () => this.toggleCompactMode());
        }
        if (this.anonymousToggle) {
            this.anonymousToggle.addEventListener('change', (e) => this.toggleAnonymousWitness(e.target.checked));
        }
        
        // Scene controls
        document.getElementById('download-btn')?.addEventListener('click', () => this.downloadScene());
        document.getElementById('zoom-btn')?.addEventListener('click', () => this.toggleZoom());
        document.getElementById('fullscreen-btn')?.addEventListener('click', () => this.toggleFullscreen());
        document.getElementById('compare-btn')?.addEventListener('click', () => this.openComparisonModal());
        
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
        
        // Start with a new session (show template selector)
        this.createNewSession();
        
        // Initialize suggested action buttons
        this._initSuggestedActions();
        
        // Initialize keyboard shortcuts
        this._initKeyboardShortcuts();
        this._updateCharCounter();
        this._updateRetryButton();
        this.setAutoScroll(this.autoScrollEnabled, false);
        this.setCompactMode(this.compactMode, false);
        this._updateConnectionQualityBadge(this.connectionStatus);
        
        // Sound toggle button — add to controls area (near mic), not header
        // _addSoundToggle removed from header — speakers controlled by phone volume
        
        // TTS toggle — add near mic controls instead of header
        this._addTTSToggle();

        // Global audio output toggle (mute/unmute)
        this._addAudioOutputToggle();
        
        // Auto-listen toggle for voice conversation — near mic only, not header
        this._addAutoListenToggle();
        this._initSimplifiedControlMenus();
        
        // Feature 7/9/10: Mode toggles and accessibility
        this._initModeToggles();
        this._initKeyboardAccessibility();
        this.initializeMobileVoiceUX();
        this.setAudioOutputDisabled(this.audioOutputDisabled, { notify: false, persist: false });
    }

    initializeMobileVoiceUX() {
        const isMobileQuery = window.matchMedia('(max-width: 768px)');
        this.isMobileVoiceUI = isMobileQuery.matches;
        isMobileQuery.addEventListener('change', (e) => {
            this.isMobileVoiceUI = e.matches;
            if (!e.matches) {
                this.closeMobileVoiceHelp();
                this.voiceDock?.classList.remove('voice-dock-more-open');
                this.dockMorePanel?.classList.add('hidden');
            }
            this._updateMobileEmptyStateCopy();
            this._initSimplifiedControlMenus();
        });

        this.voiceDockMicBtn?.addEventListener('click', () => this.toggleRecording());
        this.tapInterruptBtn?.addEventListener('click', () => this.interruptAgentSpeech());
        this.mobileCallHelpBtn?.addEventListener('click', () => this.openMobileVoiceHelp());
        this.dockHelpBtn?.addEventListener('click', () => this.openMobileVoiceHelp());
        this.mobileVoiceHelpCloseBtn?.addEventListener('click', () => this.closeMobileVoiceHelp());
        this.mobileVoiceHelpCloseX?.addEventListener('click', () => this.closeMobileVoiceHelp());

        this.dockMoreBtn?.addEventListener('click', () => this.toggleVoiceDockMore());
        document.addEventListener('click', (event) => {
            if (!this.voiceDock || !this.voiceDock.classList.contains('voice-dock-more-open')) return;
            if (this.voiceDock.contains(event.target)) return;
            this.voiceDock.classList.remove('voice-dock-more-open');
            this.dockMorePanel?.classList.add('hidden');
            this.dockMoreBtn?.setAttribute('aria-expanded', 'false');
        });

        this.mobileVoiceHelpModal?.addEventListener('click', (event) => {
            if (event.target === this.mobileVoiceHelpModal) {
                this.closeMobileVoiceHelp();
            }
        });

        const bindAction = (id, handler) => {
            const btn = document.getElementById(id);
            if (btn) btn.addEventListener('click', handler);
        };
        bindAction('dock-repeat-btn', () => this.requestRepeatQuestion());
        bindAction('dock-repeat-more-btn', () => this.requestRepeatQuestion());
        bindAction('dock-slow-btn', () => this.requestSlowDown());
        bindAction('dock-slow-more-btn', () => this.requestSlowDown());
        bindAction('dock-moment-btn', () => this.takeNeedAMoment());
        bindAction('dock-moment-more-btn', () => this.takeNeedAMoment());
        bindAction('dock-auto-btn', () => this.toggleAutoListen());
        bindAction('dock-audio-toggle-btn', () => this.toggleAudioOutputDisabled());
        bindAction('dock-speed-09-btn', () => this.setTTSPlaybackSpeed(0.9));
        bindAction('dock-speed-10-btn', () => this.setTTSPlaybackSpeed(1.0));
        bindAction('dock-speed-11-btn', () => this.setTTSPlaybackSpeed(1.1));

        this.quickPhraseRail?.querySelectorAll('.quick-phrase-chip').forEach((btn) => {
            btn.addEventListener('click', () => this.sendQuickPhrase(btn.dataset.phrase || ''));
        });

        this._syncAutoListenChip();
        this._syncAudioToggleButton();
        this._syncSpeakerChip();
        this._syncSpeedButtons();
        this._syncVoiceDockMicLabel();
        this._syncMobileElapsedTimer();
        this._setConversationState('ready', { silent: true });
        this._initMobileVoiceCoachmark();
        this._updateMobileEmptyStateCopy();
    }

    _syncMobileElapsedTimer() {
        const source = document.getElementById('interview-duration-display');
        if (!source || !this.mobileCallElapsed) return;
        const sync = () => {
            const text = (source.textContent || '').trim();
            this.mobileCallElapsed.textContent = text || '00:00';
        };
        sync();
        if (this._mobileTimerObserver) {
            this._mobileTimerObserver.disconnect();
        }
        this._mobileTimerObserver = new MutationObserver(sync);
        this._mobileTimerObserver.observe(source, { childList: true, subtree: true, characterData: true });
    }

    _initMobileVoiceCoachmark() {
        const key = 'witnessreplay-mobile-voice-coachmark-seen';
        if (!this.mobileVoiceCoachmark || !this.isMobileVoiceUI || localStorage.getItem(key) === 'true') return;
        const dismiss = () => {
            this.mobileVoiceCoachmark.classList.add('hidden');
            localStorage.setItem(key, 'true');
        };
        this.mobileVoiceCoachmarkDismiss?.addEventListener('click', dismiss, { once: true });
        this.mobileVoiceCoachmark.addEventListener('click', (event) => {
            if (event.target === this.mobileVoiceCoachmark) dismiss();
        });
        setTimeout(() => this.mobileVoiceCoachmark.classList.remove('hidden'), 900);
    }

    _updateMobileEmptyStateCopy() {
        if (!this.isMobileVoiceUI || !this.chatTranscript) return;
        const empty = this.chatTranscript.querySelector('.empty-state');
        if (empty) {
            empty.textContent = 'Tap the big mic below and speak naturally with Officer Ray. Use quick phrase chips for fast details.';
        }
    }

    openMobileVoiceHelp() {
        if (!this.mobileVoiceHelpModal) return;
        if (this.mobileVoiceHelpModal.classList.contains('active')) return;
        this.mobileVoiceHelpModal.classList.remove('hidden');
        this.mobileVoiceHelpModal.classList.add('active');
        this.playSound('click');
        this._mobileVoiceHelpEscHandler = (event) => {
            if (event.key === 'Escape') this.closeMobileVoiceHelp();
        };
        document.addEventListener('keydown', this._mobileVoiceHelpEscHandler);
    }

    closeMobileVoiceHelp() {
        if (!this.mobileVoiceHelpModal) return;
        this.mobileVoiceHelpModal.classList.add('hidden');
        this.mobileVoiceHelpModal.classList.remove('active');
        if (this._mobileVoiceHelpEscHandler) {
            document.removeEventListener('keydown', this._mobileVoiceHelpEscHandler);
            this._mobileVoiceHelpEscHandler = null;
        }
    }

    toggleVoiceDockMore() {
        if (!this.voiceDock || !this.dockMorePanel || !this.dockMoreBtn) return;
        const expanded = !this.voiceDock.classList.contains('voice-dock-more-open');
        this.voiceDock.classList.toggle('voice-dock-more-open', expanded);
        this.dockMorePanel.classList.toggle('hidden', !expanded);
        this.dockMoreBtn.setAttribute('aria-expanded', String(expanded));
        this.playSound('click');
    }

    sendQuickPhrase(phrase) {
        if (!phrase) return;
        if (this.textInput) {
            this.textInput.value = phrase;
            this._updateCharCounter();
        }
        this.sendTextMessage();
        this._vibrate(10);
    }

    requestRepeatQuestion() {
        const snippet = (this.lastAgentMessage || '').trim();
        const request = snippet
            ? `Please repeat that. I may have missed this: "${snippet.slice(0, 140)}"`
            : 'Please repeat that.';
        this.sendQuickPhrase(request);
        this.voiceDock?.classList.remove('voice-dock-more-open');
        this.dockMorePanel?.classList.add('hidden');
        this.dockMoreBtn?.setAttribute('aria-expanded', 'false');
    }

    requestSlowDown() {
        this.sendQuickPhrase('Please slow down and ask one question at a time.');
        this.voiceDock?.classList.remove('voice-dock-more-open');
        this.dockMorePanel?.classList.add('hidden');
        this.dockMoreBtn?.setAttribute('aria-expanded', 'false');
    }

    takeNeedAMoment() {
        this.autoListenEnabled = false;
        localStorage.setItem('autoListenEnabled', 'false');
        if (this._autoListenTimer) {
            clearTimeout(this._autoListenTimer);
            this._autoListenTimer = null;
        }
        const btn = document.getElementById('auto-listen-btn');
        if (btn) btn.innerHTML = '⏸️ Manual';
        this._syncAutoListenChip();
        this.setStatus('Take your time — auto-listen paused');
        this.ui?.showToast('Auto-listen paused. Tap to talk when ready.', 'info', 2200);
        this._setConversationState('ready');
        this._vibrate([18, 40, 18]);
        this.syncVoicePreferencesToSession();
        this.recordCallEvent('need_a_moment', { auto_listen: false });
        this.voiceDock?.classList.remove('voice-dock-more-open');
        this.dockMorePanel?.classList.add('hidden');
        this.dockMoreBtn?.setAttribute('aria-expanded', 'false');
    }

    interruptAgentSpeech() {
        if (this.ttsPlayer && this.ttsPlayer.isCurrentlyPlaying()) {
            this.ttsPlayer.interrupt?.('tap_interrupt');
        }
        clearTimeout(this._aiSpeakingTimeout);
        this._isSpeakingResponse = false;
        this._setMicSpeakingState(false);
        this._setConversationState('ready');
        this.recordBargeIn('tap_interrupt');
        this._vibrate([12, 24, 12]);
    }

    _syncAutoListenChip() {
        if (this.mobileCallAutoListenChip) {
            this.mobileCallAutoListenChip.textContent = this.autoListenEnabled ? 'Auto-listen on' : 'Auto-listen off';
            this.mobileCallAutoListenChip.classList.toggle('is-off', !this.autoListenEnabled);
        }
        if (this.dockAutoBtn) {
            this.dockAutoBtn.textContent = this.autoListenEnabled ? '🔁 Auto-listen on' : '🔁 Auto-listen off';
            this.dockAutoBtn.setAttribute('aria-pressed', String(this.autoListenEnabled));
        }
    }

    _syncAudioToggleButton() {
        if (!this.dockAudioToggleBtn) return;
        const disabled = !!this.audioOutputDisabled;
        this.dockAudioToggleBtn.textContent = disabled ? '🔇 Audio off' : '🔊 Audio on';
        this.dockAudioToggleBtn.classList.toggle('is-muted', disabled);
        this.dockAudioToggleBtn.setAttribute('aria-pressed', String(disabled));
    }

    setAudioOutputDisabled(disabled, options = {}) {
        const { notify = true, persist = true, restoreTTS = true } = options;
        this.audioOutputDisabled = !!disabled;
        if (persist) {
            localStorage.setItem('audioOutputDisabled', String(this.audioOutputDisabled));
        }

        if (this.audioOutputDisabled) {
            localStorage.setItem('soundEnabledBeforeAudioDisable', String(this.soundEnabled));
            if (this.ttsPlayer) {
                localStorage.setItem('ttsEnabledBeforeAudioDisable', String(this.ttsPlayer.isEnabled()));
                this.ttsPlayer.interrupt?.('audio_output_disabled');
                this.ttsPlayer.setEnabled(false);
            }
            this._isSpeakingResponse = false;
            this._setMicSpeakingState(false);
            this.soundEnabled = false;
            localStorage.setItem('soundEnabled', 'false');
            if (this.ui) this.ui.soundEnabled = false;
        } else {
            const prevSound = localStorage.getItem('soundEnabledBeforeAudioDisable');
            const shouldEnableSound = prevSound !== null ? prevSound === 'true' : (localStorage.getItem('soundEnabled') !== 'false');
            this.soundEnabled = shouldEnableSound;
            localStorage.setItem('soundEnabled', String(shouldEnableSound));
            if (this.ui) this.ui.soundEnabled = shouldEnableSound;
            if (restoreTTS && this.ttsPlayer) {
                const prevTTS = localStorage.getItem('ttsEnabledBeforeAudioDisable');
                if (prevTTS !== null) {
                    this.ttsPlayer.setEnabled(prevTTS === 'true');
                }
            }
        }

        const ttsBtn = document.getElementById('tts-toggle-btn');
        if (ttsBtn) {
            ttsBtn.innerHTML = this.ttsPlayer && this.ttsPlayer.isEnabled() ? '🔈' : '🔇';
        }
        const audioToggleBtn = document.getElementById('audio-output-toggle-btn');
        if (audioToggleBtn) {
            audioToggleBtn.innerHTML = this.audioOutputDisabled ? '🔇 Audio Off' : '🔊 Audio On';
            audioToggleBtn.setAttribute('aria-pressed', String(this.audioOutputDisabled));
        }

        this._syncAudioToggleButton();
        this._syncSpeakerChip();
        this._syncSpeedButtons();
        this._syncVoiceSettingsMenu();
        this.syncVoicePreferencesToSession();

        if (notify && this.ui) {
            this.ui.showToast(
                this.audioOutputDisabled
                    ? '🔇 Audio disabled — Detective Ray voice will not auto-play'
                    : '🔊 Audio enabled',
                'success',
                2400
            );
        }
    }

    toggleAudioOutputDisabled() {
        this.setAudioOutputDisabled(!this.audioOutputDisabled);
    }

    _syncSpeakerChip() {
        if (!this.mobileCallSpeakerChip) return;
        if (this.audioOutputDisabled) {
            this.mobileCallSpeakerChip.textContent = 'Audio off';
            this.mobileCallSpeakerChip.classList.add('is-off');
            return;
        }
        const enabled = this.ttsPlayer ? this.ttsPlayer.isEnabled() : true;
        const speed = this.ttsPlayer?.getPlaybackSpeed ? this.ttsPlayer.getPlaybackSpeed() : 1.0;
        this.mobileCallSpeakerChip.textContent = enabled ? `Speaker on · ${speed.toFixed(1)}x` : 'Speaker off';
        this.mobileCallSpeakerChip.classList.toggle('is-off', !enabled);
    }

    _syncSpeedButtons() {
        const speed = this.ttsPlayer?.getPlaybackSpeed ? this.ttsPlayer.getPlaybackSpeed() : 1.0;
        const speedButtons = [
            { btn: this.dockSpeed09Btn, speed: 0.9 },
            { btn: this.dockSpeed10Btn, speed: 1.0 },
            { btn: this.dockSpeed11Btn, speed: 1.1 },
        ];
        speedButtons.forEach(({ btn, speed: candidate }) => {
            if (!btn) return;
            const active = Math.abs(speed - candidate) < 0.01;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-pressed', String(active));
        });
    }

    setTTSPlaybackSpeed(speed) {
        if (!this.ttsPlayer || !this.ttsPlayer.setPlaybackSpeed) return;
        this.ttsPlayer.setPlaybackSpeed(speed);
        this._syncSpeedButtons();
        this._syncSpeakerChip();
        this.syncVoicePreferencesToSession();
        this.ui?.showToast(`Voice speed set to ${this.ttsPlayer.getPlaybackSpeed().toFixed(1)}x`, 'success', 1500);
    }

    _collectVoicePreferencesPayload() {
        return {
            auto_listen: !!this.autoListenEnabled,
            tts_enabled: this.audioOutputDisabled ? false : (this.ttsPlayer ? this.ttsPlayer.isEnabled() : true),
            playback_speed: this.ttsPlayer?.getPlaybackSpeed ? this.ttsPlayer.getPlaybackSpeed() : 1.0,
            voice: this.ttsPlayer?.getVoice ? this.ttsPlayer.getVoice() : 'Puck',
        };
    }

    async loadVoicePreferencesFromSession() {
        if (!this.sessionId) return;
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/voice/preferences`, {}, 7000);
            if (!response.ok) return;
            const data = await response.json();
            const prefs = data.voice_preferences || {};
            if (typeof prefs.auto_listen === 'boolean') {
                this.autoListenEnabled = prefs.auto_listen;
                localStorage.setItem('autoListenEnabled', String(this.autoListenEnabled));
            }
            if (this.ttsPlayer) {
                if (typeof prefs.tts_enabled === 'boolean') {
                    this.ttsPlayer.setEnabled(prefs.tts_enabled);
                }
                if (typeof prefs.voice === 'string' && prefs.voice.trim()) {
                    this.ttsPlayer.setVoice(prefs.voice.trim());
                }
                if (typeof prefs.playback_speed === 'number') {
                    this.ttsPlayer.setPlaybackSpeed(prefs.playback_speed);
                }
                if (this.audioOutputDisabled) {
                    this.ttsPlayer.setEnabled(false);
                }
            }
            const autoBtn = document.getElementById('auto-listen-btn');
            if (autoBtn) autoBtn.innerHTML = this.autoListenEnabled ? '🔁 Auto' : '⏸️ Manual';
            const ttsBtn = document.getElementById('tts-toggle-btn');
            if (ttsBtn) ttsBtn.innerHTML = this.ttsPlayer && this.ttsPlayer.isEnabled() ? '🔈' : '🔇';
            this._syncAudioToggleButton();
            this._syncAutoListenChip();
            this._syncSpeakerChip();
            this._syncSpeedButtons();
            this._syncVoiceSettingsMenu();
            this._syncTextToolsMenu();
        } catch (error) {
            console.debug('Voice preference load skipped:', error?.message || error);
        }
    }

    syncVoicePreferencesToSession() {
        if (!this.sessionId) return;
        const payload = this._collectVoicePreferencesPayload();
        fetch(`/api/sessions/${this.sessionId}/voice/preferences`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).catch((error) => {
            console.debug('Voice preference sync skipped:', error?.message || error);
        });
    }

    recordCallEvent(eventType, payload = {}) {
        if (!this.sessionId) return;
        fetch(`/api/sessions/${this.sessionId}/call-event`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_type: eventType,
                source: 'web',
                payload,
            }),
        }).catch(() => {});
    }

    recordBargeIn(reason = 'tap_interrupt') {
        if (!this.sessionId) return;
        fetch(`/api/sessions/${this.sessionId}/barge-in`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source: 'web',
                reason,
            }),
        }).catch(() => {});
    }

    _syncVoiceDockMicLabel() {
        if (!this.voiceDockMicBtn || !this.voiceDockMicText) return;
        this.voiceDockMicBtn.disabled = !!this.micBtn?.disabled;
        let label = 'Tap to talk';
        if (this.micBtn?.classList.contains('disconnected')) label = 'Tap to reconnect';
        else if (this.isRecording) label = 'Tap to stop';
        else if (this.conversationState === 'speaking') label = 'Interrupt & talk';
        else if (this.conversationState === 'thinking') label = 'Ray is thinking...';
        this.voiceDockMicText.textContent = label;
        this.voiceDockMicBtn.classList.toggle('is-recording', this.isRecording);
        this.voiceDockMicBtn.classList.toggle('is-busy', this.conversationState === 'thinking' || this.conversationState === 'speaking');
    }

    _setConversationState(state, options = {}) {
        const validState = ['ready', 'listening', 'thinking', 'speaking'].includes(state) ? state : 'ready';
        const changed = this.conversationState !== validState;
        this.conversationState = validState;

        const labels = {
            ready: 'Ready',
            listening: 'Listening',
            thinking: 'Thinking',
            speaking: 'Ray speaking'
        };

        if (this.mobileCallStateChip) {
            this.mobileCallStateChip.textContent = labels[validState] || 'Ready';
            this.mobileCallStateChip.classList.remove('state-ready', 'state-listening', 'state-thinking', 'state-speaking');
            this.mobileCallStateChip.classList.add(`state-${validState}`);
        }

        if (this.tapInterruptAffordance) {
            const showInterrupt = this.isMobileVoiceUI && validState === 'speaking';
            this.tapInterruptAffordance.classList.toggle('hidden', !showInterrupt);
            this.tapInterruptAffordance.classList.toggle('visible', showInterrupt);
        }

        if (validState !== 'ready') {
            this._hideRayListeningCue();
        }

        this._syncVoiceDockMicLabel();

        if (!changed || options.silent) return;
        this.recordCallEvent('conversation_state', { state: validState });
        const pattern = {
            listening: [16],
            thinking: [10, 30, 10],
            speaking: [20, 30, 20],
            ready: [8]
        }[validState];
        this._vibrate(pattern);
    }

    _showRayListeningCue() {
        if (!this.rayListeningCue || !this.isMobileVoiceUI) return;
        this.rayListeningCue.classList.remove('hidden');
        clearTimeout(this._rayListeningCueTimer);
        this._rayListeningCueTimer = setTimeout(() => {
            this.rayListeningCue?.classList.add('hidden');
        }, 5000);
    }

    _hideRayListeningCue() {
        if (!this.rayListeningCue) return;
        clearTimeout(this._rayListeningCueTimer);
        this.rayListeningCue.classList.add('hidden');
    }

    _triggerSceneUpdatePulse() {
        if (!this.mobileSceneUpdateIndicator) return;
        this.mobileSceneUpdateIndicator.classList.remove('hidden');
        this.mobileSceneUpdateIndicator.classList.add('pulse');
        clearTimeout(this._sceneUpdatePulseTimer);
        this._sceneUpdatePulseTimer = setTimeout(() => {
            this.mobileSceneUpdateIndicator?.classList.remove('pulse');
        }, 2200);
    }

    _vibrate(pattern) {
        if (!this.isMobileVoiceUI || !pattern || typeof navigator === 'undefined' || typeof navigator.vibrate !== 'function') return;
        if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        try { navigator.vibrate(pattern); } catch (_) {}
    }
    
    _addSoundToggle() {
        // Sound effects controlled by phone volume — no separate button needed
        // Keeping the method stub for backward compatibility
    }

    _initSimplifiedControlMenus() {
        if (!window.matchMedia('(min-width: 769px)').matches) {
            document.body.classList.remove('modern-simplified-ui');
            return;
        }
        document.body.classList.add('modern-simplified-ui');
        this._ensureModernMenuDismissHandler();
        this._mountVoiceSettingsMenu();
        this._mountTextToolsMenu();
    }

    _ensureModernMenuDismissHandler() {
        if (this._modernMenuDismissHandler) return;
        this._modernMenuDismissHandler = (event) => {
            const openMenus = document.querySelectorAll('.modern-dropdown.open');
            openMenus.forEach((menuEl) => {
                if (!menuEl.contains(event.target)) {
                    menuEl.classList.remove('open');
                    menuEl.querySelector('.modern-dropdown-trigger')?.setAttribute('aria-expanded', 'false');
                }
            });
        };
        document.addEventListener('click', this._modernMenuDismissHandler);
    }

    _toggleModernDropdown(dropdownId) {
        const dropdown = document.getElementById(dropdownId);
        if (!dropdown) return;
        const shouldOpen = !dropdown.classList.contains('open');
        document.querySelectorAll('.modern-dropdown.open').forEach((el) => {
            el.classList.remove('open');
            el.querySelector('.modern-dropdown-trigger')?.setAttribute('aria-expanded', 'false');
        });
        dropdown.classList.toggle('open', shouldOpen);
        dropdown.querySelector('.modern-dropdown-trigger')?.setAttribute('aria-expanded', String(shouldOpen));
    }

    _mountVoiceSettingsMenu() {
        const controls = document.querySelector('.controls') || document.querySelector('.session-info');
        if (!controls) return;

        let wrap = document.getElementById('voice-settings-dropdown');
        if (!wrap) {
            wrap = document.createElement('div');
            wrap.id = 'voice-settings-dropdown';
            wrap.className = 'modern-dropdown modern-dropdown-inline';
            wrap.innerHTML = `
                <button id="voice-settings-btn" type="button" class="btn btn-secondary modern-dropdown-trigger" aria-haspopup="menu" aria-expanded="false">
                    ⚙️ Voice settings
                </button>
                <div id="voice-settings-menu" class="modern-dropdown-menu" role="menu" aria-label="Voice settings options"></div>
            `;
            controls.appendChild(wrap);
            const trigger = wrap.querySelector('#voice-settings-btn');
            trigger?.addEventListener('click', (event) => {
                event.stopPropagation();
                this._syncVoiceSettingsMenu();
                this._toggleModernDropdown('voice-settings-dropdown');
                trigger.setAttribute('aria-expanded', String(wrap.classList.contains('open')));
            });
        }

        this._syncVoiceSettingsMenu();
    }

    _syncVoiceSettingsMenu() {
        const menu = document.getElementById('voice-settings-menu');
        if (!menu) return;

        const items = [
            { id: 'auto-listen-btn', fallback: '🔁 Auto-listen' },
            { id: 'tts-toggle-btn', fallback: '🔈 Speaker voice' },
            { id: 'audio-output-toggle-btn', fallback: '🔊 Audio output' },
        ];

        menu.innerHTML = '';
        items.forEach(({ id, fallback }) => {
            const source = document.getElementById(id);
            if (!source) return;
            source.classList.add('menu-hidden-source');

            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'modern-dropdown-item';
            item.textContent = (source.textContent || '').trim() || source.getAttribute('aria-label') || fallback;
            item.disabled = !!source.disabled;
            item.addEventListener('click', () => {
                source.click();
                this._syncVoiceSettingsMenu();
                const dropdown = document.getElementById('voice-settings-dropdown');
                dropdown?.classList.remove('open');
                dropdown?.querySelector('.modern-dropdown-trigger')?.setAttribute('aria-expanded', 'false');
            });
            menu.appendChild(item);
        });
    }

    _mountTextToolsMenu() {
        const textBar = document.getElementById('text-input-bar');
        if (!textBar) return;

        let wrap = document.getElementById('text-tools-dropdown');
        if (!wrap) {
            wrap = document.createElement('div');
            wrap.id = 'text-tools-dropdown';
            wrap.className = 'modern-dropdown modern-dropdown-inline text-tools-dropdown';
            wrap.innerHTML = `
                <button id="text-tools-btn" type="button" class="btn btn-secondary modern-dropdown-trigger text-tools-trigger" aria-haspopup="menu" aria-expanded="false" title="Tools & Settings">
                    ⋯
                </button>
                <div id="text-tools-menu" class="modern-dropdown-menu modern-dropdown-menu-right" role="menu" aria-label="Tools and settings"></div>
            `;
            const sendBtn = document.getElementById('send-btn');
            if (sendBtn && sendBtn.parentNode === textBar) {
                textBar.insertBefore(wrap, sendBtn);
            } else {
                textBar.appendChild(wrap);
            }

            const trigger = wrap.querySelector('#text-tools-btn');
            trigger?.addEventListener('click', (event) => {
                event.stopPropagation();
                this._syncTextToolsMenu();
                this._toggleModernDropdown('text-tools-dropdown');
                trigger.setAttribute('aria-expanded', String(wrap.classList.contains('open')));
            });
        }

        this._syncTextToolsMenu();
    }

    _syncTextToolsMenu() {
        const menu = document.getElementById('text-tools-menu');
        if (!menu) return;

        const items = [
            { id: 'upload-evidence-btn', label: '📎 Attach evidence' },
            { id: 'upload-sketch-btn', label: '✏️ Upload sketch' },
            { id: 'camera-btn', label: '📸 Take photo' },
            { id: 'retry-last-btn', label: '↻ Retry last message' },
            { type: 'separator' },
            { type: 'label', text: 'Quick Actions' },
            { id: '__suggest_correct', label: '✏️ Correct something', action: 'correct' },
            { id: '__suggest_generate', label: '🎬 Generate scene', action: 'generate' },
            { id: '__suggest_details', label: '➕ Add more details', action: 'details' },
            { type: 'separator' },
            { type: 'label', text: 'Interview' },
            { id: 'comfort-pause-btn', label: '⏸️ Pause interview' },
            { id: 'comfort-break-btn', label: '☕ Take a break' },
            { id: 'comfort-support-btn', label: '💚 Get support' },
            { type: 'separator' },
            { type: 'label', text: 'Panels' },
            { type: 'toggle-panel', label: '📊 Report Progress', selector: '#investigation-progress' },
            { type: 'toggle-panel', label: '📈 Scene Stats', selector: '.scene-stats' },
            { type: 'toggle-panel', label: '🌤️ Environment', selector: '#environmental-conditions-panel' },
            { type: 'toggle-panel', label: '🎨 Scene Elements', selector: '#scene-editor-container' },
            { type: 'toggle-panel', label: '📋 Evidence Board', selector: '#evidence-board' },
            { type: 'toggle-panel', label: '📜 Version History', selector: '.timeline-panel' },
            { type: 'separator' },
            { type: 'label', text: 'Settings' },
            { id: 'auto-scroll-toggle', label: this.autoScrollEnabled ? '⇣ Auto-scroll: On' : '⏸ Auto-scroll: Off' },
            { id: 'compact-mode-toggle', label: this.compactMode ? '▤ Compact mode: On' : '▤ Compact mode: Off' },
            { id: 'guided-mode-btn', label: '📋 Guided mode' },
            { id: 'child-mode-btn', label: '🧒 Child mode' },
            { id: 'high-contrast-btn', label: '🔲 High contrast' },
        ];

        menu.innerHTML = '';
        items.forEach((entry) => {
            if (entry.type === 'separator') {
                const hr = document.createElement('hr');
                hr.className = 'dropdown-separator';
                menu.appendChild(hr);
                return;
            }
            if (entry.type === 'label') {
                const lbl = document.createElement('div');
                lbl.className = 'dropdown-section-label';
                lbl.textContent = entry.text;
                menu.appendChild(lbl);
                return;
            }
            if (entry.type === 'toggle-panel') {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'modern-dropdown-item';
                const el = document.querySelector(entry.selector);
                const isShown = el?.classList.contains('panel-shown');
                item.textContent = entry.label + (isShown ? ' ✓' : '');
                item.addEventListener('click', () => {
                    const target = document.querySelector(entry.selector);
                    if (target) target.classList.toggle('panel-shown');
                    this._syncTextToolsMenu();
                });
                menu.appendChild(item);
                return;
            }
            const { id, label, action } = entry;
            // Suggestion actions don't have a source element
            if (action) {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'modern-dropdown-item';
                item.textContent = label;
                item.disabled = !this.ws || this.ws.readyState !== WebSocket.OPEN;
                item.addEventListener('click', () => {
                    const textMap = { correct: 'I want to correct something about the scene.', generate: 'Please generate the scene image now.', details: 'I have more details to add about what I saw.' };
                    const text = textMap[action];
                    if (text && this.ws && this.ws.readyState === WebSocket.OPEN) {
                        this.ws.send(JSON.stringify({ type: 'text', data: { text } }));
                        this.displayMessage(text, 'user');
                    }
                    const dropdown = document.getElementById('text-tools-dropdown');
                    dropdown?.classList.remove('open');
                    dropdown?.querySelector('.modern-dropdown-trigger')?.setAttribute('aria-expanded', 'false');
                });
                menu.appendChild(item);
                return;
            }
            const source = document.getElementById(id);
            if (!source) return;
            source.classList.add('menu-hidden-source');
            let displayLabel = label;
            if (id === 'guided-mode-btn') {
                displayLabel = `📋 Guided mode: ${source.classList.contains('active') ? 'On' : 'Off'}`;
            } else if (id === 'child-mode-btn') {
                displayLabel = `🧒 Child mode: ${source.classList.contains('active') ? 'On' : 'Off'}`;
            } else if (id === 'high-contrast-btn') {
                displayLabel = `🔲 High contrast: ${source.classList.contains('active') ? 'On' : 'Off'}`;
            }

            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'modern-dropdown-item';
            item.textContent = displayLabel;
            item.disabled = !!source.disabled;
            item.addEventListener('click', () => {
                source.click();
                this._syncTextToolsMenu();
                const dropdown = document.getElementById('text-tools-dropdown');
                dropdown?.classList.remove('open');
                dropdown?.querySelector('.modern-dropdown-trigger')?.setAttribute('aria-expanded', 'false');
            });
            menu.appendChild(item);
        });
    }
    
    _addTTSToggle() {
        const controls = document.querySelector('.controls') || document.querySelector('.session-info');
        if (!controls || document.getElementById('tts-toggle-btn')) return;
        
        const ttsBtn = document.createElement('button');
        ttsBtn.id = 'tts-toggle-btn';
        ttsBtn.className = 'btn btn-secondary mic-area-btn';
        ttsBtn.setAttribute('data-tooltip', 'Speaker — hear AI responses');
        ttsBtn.setAttribute('aria-label', 'Toggle speaker for AI responses');
        ttsBtn.innerHTML = this.ttsPlayer && this.ttsPlayer.isEnabled() ? '🔊' : '🔇';
        ttsBtn.addEventListener('click', () => this.toggleTTS());
        
        controls.appendChild(ttsBtn);
        this._syncSpeakerChip();
    }

    _addAudioOutputToggle() {
        const controls = document.querySelector('.controls') || document.querySelector('.session-info');
        if (!controls || document.getElementById('audio-output-toggle-btn')) return;

        const btn = document.createElement('button');
        btn.id = 'audio-output-toggle-btn';
        btn.className = 'btn btn-secondary mic-area-btn';
        btn.setAttribute('aria-label', 'Disable or enable all audio output');
        btn.setAttribute('data-tooltip', 'Mute/unmute all app audio output');
        btn.innerHTML = this.audioOutputDisabled ? '🔇 Audio Off' : '🔊 Audio On';
        btn.addEventListener('click', () => this.toggleAudioOutputDisabled());
        controls.appendChild(btn);
    }
    

    _syncAutoListenButtonState(buttonEl = null) {
        const btn = buttonEl || document.getElementById('auto-listen-btn');
        if (!btn) return;
        if (!this.autoListenEnabled) {
            btn.innerHTML = '⏸️ Manual';
            this._syncVoiceSettingsMenu();
            return;
        }
        btn.innerHTML = this._autoListenPausedUntilManual ? '⏸️ Auto Paused' : '🔁 Auto';
        this._syncVoiceSettingsMenu();
    }

    _addAutoListenToggle() {
        const controls = document.querySelector('.controls') || document.querySelector('.session-info');
        if (!controls || document.getElementById('auto-listen-btn')) return;
        
        const btn = document.createElement('button');
        btn.id = 'auto-listen-btn';
        btn.className = 'btn btn-secondary mic-area-btn';
        btn.setAttribute('data-tooltip', 'Auto-listen after AI speaks');
        btn.setAttribute('aria-label', 'Toggle auto-listen mode');
        this._syncAutoListenButtonState(btn);
        btn.addEventListener('click', () => this.toggleAutoListen());
        
        controls.appendChild(btn);
        this._syncAutoListenChip();
    }
    
    toggleAutoListen() {
        this.autoListenEnabled = !this.autoListenEnabled;
        localStorage.setItem('autoListenEnabled', this.autoListenEnabled.toString());
        
        this._syncAutoListenButtonState();
        this._syncAutoListenChip();
        
        this.ui.showToast(
            this.autoListenEnabled
                ? '🔁 Auto-listen ON — recording starts after AI speaks'
                : '⏸️ Auto-listen OFF — tap mic each time',
            'success', 3000
        );
        if (this.autoListenEnabled) {
            this._autoListenPausedUntilManual = false;
        }
        this._syncAutoListenButtonState();
        this._vibrate(this.autoListenEnabled ? [10, 20, 10] : [18]);
        
        // Cancel pending auto-listen if turning off
        if (!this.autoListenEnabled && this._autoListenTimer) {
            clearTimeout(this._autoListenTimer);
            this._autoListenTimer = null;
        }
        this.syncVoicePreferencesToSession();
    }
    
    initializeTTS() {
        // Initialize TTS player for accessibility
        if (window.TTSPlayer) {
            this.ttsPlayer = new TTSPlayer();
            if (this.audioOutputDisabled) {
                this.ttsPlayer.setEnabled(false);
            }
            this._syncSpeedButtons();
            
            // Wire up voice conversation callbacks
            this.ttsPlayer.onPlaybackStart = () => {
                this._isSpeakingResponse = true;
                this._setMicSpeakingState(true);
            };
            this.ttsPlayer.onPlaybackEnd = () => {
                this._isSpeakingResponse = false;
                this._setMicSpeakingState(false);
                this._triggerAutoListen();
            };
        }
    }
    
    _setMicSpeakingState(speaking) {
        if (!this.micBtn || this.isRecording) return;
        if (speaking) {
            this.micBtn.classList.remove('processing');
            this.micBtn.classList.add('ai-speaking');
            const t = this.micBtn.querySelector('.btn-text');
            if (t) t.textContent = 'Detective Ray speaking...';
            this._setConversationState('speaking');
        } else {
            this.micBtn.classList.remove('ai-speaking');
            const t = this.micBtn.querySelector('.btn-text');
            if (t && !this.micBtn.classList.contains('connecting') && !this.micBtn.classList.contains('disconnected')) {
                t.textContent = 'Tap to Report';
            }
            this._setConversationState('ready');
            this._showRayListeningCue();
        }
        this._syncVoiceDockMicLabel();
    }
    
    _triggerAutoListen() {
        if (!this.autoListenEnabled) return;
        if (this._autoListenPausedUntilManual) return;
        if (this.isRecording) return;
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        if (this.micBtn && (this.micBtn.classList.contains('connecting') || this.micBtn.classList.contains('disconnected'))) return;
        // On iOS, getUserMedia requires a user gesture. Only auto-listen if
        // the user has already granted mic permission via a manual tap.
        if (!this._micPermissionGranted) return;
        
        // Brief 1-second pause, then auto-start recording
        if (this._autoListenTimer) clearTimeout(this._autoListenTimer);
        this._autoListenTimer = setTimeout(() => {
            this._autoListenTimer = null;
            if (!this.isRecording && !this._isSpeakingResponse && this.ws && this.ws.readyState === WebSocket.OPEN) {
                console.debug('[VoiceConversation] Auto-listen: starting recording');
                this.startRecording({ trigger: 'auto_listen' });
            }
        }, 1000);
    }

    _isLikelySilentAutoCapture(qualityMetrics, audioBlob) {
        const sizeKB = (audioBlob?.size || 0) / 1024;
        if (!qualityMetrics) {
            return sizeKB < 12;
        }

        const totalSamples = Math.max(
            1,
            Number(qualityMetrics.totalSamples || qualityMetrics.volumeSamples || 0),
        );
        const quietRatio = Number(qualityMetrics.tooQuietSamples || 0) / totalSamples;
        const avgVolume = Number(qualityMetrics.avgVolume || 0);
        const qualityScore = Number(qualityMetrics.qualityScore || 100);
        const durationMs = Number(qualityMetrics.duration || 0);

        if (durationMs > 0 && durationMs < 700) {
            return true;
        }

        return (
            quietRatio >= 0.9
            || avgVolume < 0.018
            || (qualityScore <= 20 && sizeKB < 32)
        );
    }

    _pauseAutoListenUntilManual(reason = 'silence_detected') {
        if (this._autoListenPausedUntilManual) return;
        this._autoListenPausedUntilManual = true;
        if (this._autoListenTimer) {
            clearTimeout(this._autoListenTimer);
            this._autoListenTimer = null;
        }
        this._setConversationState('ready');
        this.ui?.setStatus('Waiting for witness input...', 'default');
        this._syncAutoListenButtonState();
        this.ui?.showToast('⏸️ Auto-listen paused. Tap the mic when ready.', 'info', 2800);
        this.recordCallEvent('auto_listen_paused', { reason });
    }
    
    toggleTTS() {
        if (!this.ttsPlayer) {
            this.ui.showToast('Text-to-Speech not available', 'warning', 2000);
            return;
        }

        if (this.audioOutputDisabled) {
            this.setAudioOutputDisabled(false, { notify: false, restoreTTS: false });
        }
        
        const newState = !this.ttsPlayer.isEnabled();
        this.ttsPlayer.setEnabled(newState);
        
        const ttsBtn = document.getElementById('tts-toggle-btn');
        if (ttsBtn) {
            ttsBtn.innerHTML = newState ? '🔈' : '🔇';
        }
        this._syncSpeakerChip();
        this._syncVoiceSettingsMenu();
        
        this.ui.showToast(
            newState ? '🔈 Text-to-Speech enabled - AI responses will be spoken' : '🔇 Text-to-Speech disabled',
            'success',
            3000
        );
        
        // If enabled, speak a confirmation
        if (newState) {
            this.ttsPlayer.speak('Text to speech is now enabled. I will read AI responses aloud.', true);
        }
        this._syncSpeedButtons();
        this.syncVoicePreferencesToSession();
    }
    
    // Speak AI response using TTS (called when agent responds)
    speakAIResponse(text) {
        if (this.audioOutputDisabled) {
            if (this.autoListenEnabled) this._triggerAutoListen();
            return;
        }
        if (this.ttsPlayer && this.ttsPlayer.isEnabled()) {
            // TTS will manage mic state via onPlaybackStart/onPlaybackEnd callbacks
            this.ttsPlayer.speak(text);
        } else if (this.autoListenEnabled) {
            // No TTS — still trigger auto-listen after a brief pause
            this._triggerAutoListen();
        }
    }
    
    toggleSound() {
        if (this.audioOutputDisabled) {
            this.setAudioOutputDisabled(false, { notify: false });
        }
        this.soundEnabled = !this.soundEnabled;
        localStorage.setItem('soundEnabled', this.soundEnabled);
        if (this.ui) this.ui.soundEnabled = this.soundEnabled;
        
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
        if (this.audioOutputDisabled || !this.soundEnabled || !this.audioContext) return;
        
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
            const isTypingField =
                e.target.tagName === 'INPUT' ||
                e.target.tagName === 'TEXTAREA' ||
                e.target.isContentEditable;
            
            // Slash: focus chat input (unless already typing)
            if (!isTypingField && e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                this.focusChatInput();
                return;
            }
            
            // Ignore if typing in input field
            if (isTypingField) {
                return;
            }
            
            // Space: Toggle recording (only if mic button is not disabled)
            if (e.code === 'Space' && !this.micBtn.disabled) {
                e.preventDefault();
                this.toggleRecording();
            }
            
            // Escape: Close any open modal or shortcuts overlay, or stop recording
            if (e.code === 'Escape') {
                e.preventDefault();
                if (this.isRecording) { this.stopRecording(); return; }
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

    focusChatInput() {
        const bar = document.getElementById('text-input-bar');
        if (bar && bar.classList.contains('text-input-collapsed')) {
            bar.classList.remove('text-input-collapsed');
            bar.classList.add('text-input-expanded');
        }
        if (this.textInput && !this.textInput.disabled) {
            this.textInput.focus();
        }
    }

    _updateCharCounter() {
        if (!this.charCounter || !this.textInput) return;
        const length = this.textInput.value.length;
        this.charCounter.textContent = `${length} chars`;
        this.charCounter.classList.toggle('warning', length > 400);
    }

    _updateRetryButton() {
        if (!this.retryLastBtn) return;
        const hasLastMessage = !!this.lastUserMessage;
        this.retryLastBtn.disabled = !hasLastMessage;
        this.retryLastBtn.title = hasLastMessage ? 'Retry last message' : 'No message to retry';
        this._syncTextToolsMenu();
    }

    retryLastMessage() {
        if (!this.lastUserMessage) {
            this.ui?.showToast('No previous message to retry yet.', 'info', 1800);
            return;
        }
        this.textInput.value = this.lastUserMessage;
        this._updateCharCounter();
        this.sendTextMessage();
    }

    setAutoScroll(enabled, save = true) {
        this.autoScrollEnabled = !!enabled;
        if (save) {
            localStorage.setItem('witnessreplay-auto-scroll', this.autoScrollEnabled.toString());
        }
        if (this.autoScrollToggleBtn) {
            this.autoScrollToggleBtn.classList.toggle('is-off', !this.autoScrollEnabled);
            this.autoScrollToggleBtn.setAttribute('aria-pressed', String(this.autoScrollEnabled));
            this.autoScrollToggleBtn.title = this.autoScrollEnabled ? 'Auto-scroll on' : 'Auto-scroll off';
            this.autoScrollToggleBtn.textContent = this.autoScrollEnabled ? '⇣' : '⏸';
        }
        if (this.chatTranscript) {
            this.chatTranscript.classList.toggle('auto-scroll-off', !this.autoScrollEnabled);
        }
        this._syncTextToolsMenu();
    }

    toggleAutoScroll() {
        this.setAutoScroll(!this.autoScrollEnabled);
    }

    _scrollChatToBottom(behavior = 'smooth') {
        if (!this.chatTranscript || !this.autoScrollEnabled) return;
        this.chatTranscript.scrollTo({ top: this.chatTranscript.scrollHeight, behavior });
    }

    setCompactMode(enabled, save = true) {
        this.compactMode = !!enabled;
        document.body.classList.toggle('compact-chat', this.compactMode);
        if (save) {
            localStorage.setItem('witnessreplay-compact-chat', this.compactMode.toString());
        }
        if (this.compactModeBtn) {
            this.compactModeBtn.classList.toggle('active', this.compactMode);
            this.compactModeBtn.setAttribute('aria-pressed', String(this.compactMode));
            this.compactModeBtn.title = this.compactMode ? 'Compact mode on' : 'Compact mode off';
        }
        this._syncTextToolsMenu();
    }

    toggleCompactMode() {
        this.setCompactMode(!this.compactMode);
    }

    _updateConnectionQualityBadge(status = this.connectionStatus) {
        const badge = this.connectionQualityBadge || document.getElementById('connection-quality-badge');
        if (!badge) return;
        let level = 'unstable';
        if (status === 'disconnected') {
            level = 'disconnected';
        } else if (status === 'connected' && this._reconnectAttempt === 0) {
            level = 'good';
        }
        badge.dataset.level = level;
        badge.textContent = level === 'good' ? 'Good' : level === 'disconnected' ? 'Disconnected' : 'Unstable';
    }

    toggleAnonymousWitness(isAnonymous) {
        const nameInput = document.getElementById('witness-name');
        const contactInput = document.getElementById('witness-contact');
        [nameInput, contactInput].forEach((input) => {
            if (!input) return;
            if (isAnonymous) input.value = '';
            input.disabled = !!isAnonymous;
        });
        if (isAnonymous) {
            localStorage.removeItem('witnessreplay-witness-name');
            localStorage.removeItem('witnessreplay-witness-contact');
        }
    }

    _addAssistantCopyButton(messageDiv, text) {
        if (!messageDiv || messageDiv.querySelector('.msg-copy-btn')) return;
        const actions = document.createElement('div');
        actions.className = 'message-actions';
        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'msg-copy-btn';
        copyBtn.textContent = 'Copy';
        copyBtn.setAttribute('aria-label', 'Copy assistant message');
        copyBtn.addEventListener('click', async (event) => {
            event.preventDefault();
            event.stopPropagation();
            const copied = await this._copyToClipboard(text);
            this.ui?.showToast(copied ? 'Copied response to clipboard' : 'Copy failed', copied ? 'success' : 'error', 1600);
        });
        actions.appendChild(copyBtn);
        messageDiv.appendChild(actions);
    }

    async _copyToClipboard(text) {
        if (!text) return false;
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (_) {
            try {
                const area = document.createElement('textarea');
                area.value = text;
                area.setAttribute('readonly', '');
                area.style.position = 'absolute';
                area.style.left = '-9999px';
                document.body.appendChild(area);
                area.select();
                const ok = document.execCommand('copy');
                area.remove();
                return ok;
            } catch (e) {
                return false;
            }
        }
    }
    
    initializeAudio() {
        if (window.AudioRecorder) {
            this.audioRecorder = new AudioRecorder();
        }
        
        if (window.EnhancedAudioVisualizer) {
            this.audioVisualizer = new EnhancedAudioVisualizer('audio-visualizer');
        }
        
        // Initialize Audio Quality Analyzer
        if (window.AudioQualityAnalyzer) {
            this.audioQualityAnalyzer = new AudioQualityAnalyzer();
        }
        if (window.AudioQualityIndicator) {
            this.audioQualityIndicator = new AudioQualityIndicator('audio-quality-container');
            if (this.audioQualityAnalyzer && this.audioQualityIndicator) {
                this.audioQualityIndicator.attachAnalyzer(this.audioQualityAnalyzer);
            }
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
    
    initializeVAD() {
        // VAD UI elements
        this.vadToggle = document.getElementById('vad-enabled');
        this.vadIndicator = document.getElementById('vad-indicator');
        this.vadSettings = document.getElementById('vad-settings');
        this.vadSensitivity = document.getElementById('vad-sensitivity');
        this.vadSilence = document.getElementById('vad-silence');
        this.vadSensitivityValue = document.getElementById('vad-sensitivity-value');
        this.vadSilenceValue = document.getElementById('vad-silence-value');
        
        if (!window.VoiceActivityDetector) {
            console.warn('VoiceActivityDetector not available');
            return;
        }
        
        // Restore saved settings
        const savedSensitivity = localStorage.getItem('vadSensitivity');
        const savedSilence = localStorage.getItem('vadSilenceThreshold');
        
        if (savedSensitivity && this.vadSensitivity) {
            this.vadSensitivity.value = savedSensitivity;
        }
        if (savedSilence && this.vadSilence) {
            this.vadSilence.value = savedSilence;
        }
        
        // Update displayed values
        this.updateVADSettingsDisplay();
        
        // Set initial toggle state
        if (this.vadToggle) {
            this.vadToggle.checked = this.vadEnabled;
            
            // Toggle event listener
            this.vadToggle.addEventListener('change', (e) => {
                this.vadEnabled = e.target.checked;
                localStorage.setItem('vadEnabled', this.vadEnabled);
                
                if (this.vadEnabled) {
                    this.startVADListening();
                } else {
                    this.stopVADListening();
                }
            });
        }
        
        // Settings sliders
        if (this.vadSensitivity) {
            this.vadSensitivity.addEventListener('input', (e) => {
                const value = parseFloat(e.target.value);
                if (this.vad) {
                    this.vad.setSensitivity(value);
                }
                localStorage.setItem('vadSensitivity', value);
                this.updateVADSettingsDisplay();
            });
        }
        
        if (this.vadSilence) {
            this.vadSilence.addEventListener('input', (e) => {
                const value = parseFloat(e.target.value);
                if (this.vad) {
                    this.vad.setSilenceThreshold(value);
                }
                localStorage.setItem('vadSilenceThreshold', value);
                this.updateVADSettingsDisplay();
            });
        }
        
        // Show settings when VAD is enabled (click on label area)
        const vadLabel = document.querySelector('.vad-label');
        if (vadLabel && this.vadSettings) {
            vadLabel.style.cursor = 'pointer';
            vadLabel.addEventListener('click', () => {
                this.vadSettings.classList.toggle('hidden');
            });
        }
    }
    
    updateVADSettingsDisplay() {
        if (this.vadSensitivity && this.vadSensitivityValue) {
            const value = parseFloat(this.vadSensitivity.value);
            let label = 'Medium';
            if (value <= 0.01) label = 'High';
            else if (value >= 0.03) label = 'Low';
            this.vadSensitivityValue.textContent = label;
        }
        
        if (this.vadSilence && this.vadSilenceValue) {
            const value = parseFloat(this.vadSilence.value);
            this.vadSilenceValue.textContent = `${value.toFixed(1)}s`;
        }
    }
    
    async startVADListening() {
        if (this.vadListening || this.isRecording) return;
        
        try {
            const sensitivity = this.vadSensitivity ? parseFloat(this.vadSensitivity.value) : 0.015;
            const silenceThreshold = this.vadSilence ? parseFloat(this.vadSilence.value) : 2.0;
            
            this.vad = new VoiceActivityDetector({
                sensitivity: sensitivity,
                silenceThreshold: silenceThreshold,
                onSpeechStart: () => this.onVADSpeechStart(),
                onSpeechEnd: (silenceDuration) => this.onVADSpeechEnd(silenceDuration),
                onVolumeChange: (smoothed, raw) => this.onVADVolumeChange(smoothed, raw)
            });
            
            await this.vad.start();
            this.vadListening = true;
            
            // Update indicator
            if (this.vadIndicator) {
                this.vadIndicator.classList.add('listening');
                this.vadIndicator.classList.remove('speech-detected', 'recording');
            }
            
            this.setStatus('Listening for voice...');
            this._setConversationState('listening');
            console.debug('[VAD] Started listening');
            
        } catch (error) {
            console.error('[VAD] Failed to start:', error);
            this.ui?.showToast('Could not start voice detection: ' + error.message, 'error');
            
            // Reset toggle
            if (this.vadToggle) {
                this.vadToggle.checked = false;
            }
            this.vadEnabled = false;
        }
    }
    
    stopVADListening() {
        if (!this.vadListening) return;
        
        if (this.vad) {
            this.vad.stop();
            this.vad = null;
        }
        
        this.vadListening = false;
        this.vadAutoRecording = false;
        
        // Update indicator
        if (this.vadIndicator) {
            this.vadIndicator.classList.remove('listening', 'speech-detected', 'recording');
        }
        
        this.setStatus('Ready to listen');
        this._setConversationState('ready');
        console.debug('[VAD] Stopped listening');
    }
    
    onVADSpeechStart() {
        if (this.isRecording || this.vadAutoRecording) return;
        
        console.debug('[VAD] Speech detected - starting recording');
        this.vadAutoRecording = true;
        
        // Update indicator
        if (this.vadIndicator) {
            this.vadIndicator.classList.remove('listening');
            this.vadIndicator.classList.add('recording');
        }
        
        // Start actual recording
        this.startRecording();
    }
    
    onVADSpeechEnd(silenceDuration) {
        if (!this.vadAutoRecording || !this.isRecording) return;
        
        console.debug(`[VAD] Silence detected (${silenceDuration.toFixed(1)}s) - stopping recording`);
        this.vadAutoRecording = false;
        
        // Update indicator back to listening
        if (this.vadIndicator) {
            this.vadIndicator.classList.remove('recording');
            this.vadIndicator.classList.add('listening');
        }
        
        // Stop recording
        this.stopRecording();
    }
    
    onVADVolumeChange(smoothed, raw) {
        // Update visual indicator based on volume
        if (this.vadIndicator && this.vadListening && !this.isRecording) {
            const hasVoice = smoothed > (this.vad?.config.sensitivity || 0.015);
            if (hasVoice) {
                this.vadIndicator.classList.add('speech-detected');
                this.vadIndicator.classList.remove('listening');
            } else {
                this.vadIndicator.classList.remove('speech-detected');
                this.vadIndicator.classList.add('listening');
            }
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
        
        // Comparison version selectors and compare button
        document.getElementById('compare-versions-btn')?.addEventListener('click', () => {
            this.executeVersionComparison();
        });
        document.getElementById('toggle-comparison-mode-btn')?.addEventListener('click', () => {
            this.toggleComparisonMode();
            this.ui.hideModal('comparison-modal');
        });
        
        // Template modal close buttons and handlers
        document.getElementById('close-template-modal-btn')?.addEventListener('click', () => {
            this.ui.hideModal('template-modal');
        });
        document.getElementById('template-modal')?.addEventListener('click', (e) => {
            if (e.target.id === 'template-modal') {
                this.ui.hideModal('template-modal');
            }
        });
        document.getElementById('skip-template-btn')?.addEventListener('click', () => {
            this.selectedTemplateId = null;
            this.ui.hideModal('template-modal');
            this._createSessionWithTemplate(null);
        });
    }
    
    async createNewSession() {
        // Show template selector modal first
        await this.showTemplateSelector();
    }
    
    async showTemplateSelector() {
        // Fetch templates if not cached
        if (this.templates.length === 0) {
            try {
                const response = await this.fetchWithTimeout('/api/templates');
                if (response.ok) {
                    const data = await response.json();
                    this.templates = data.templates || [];
                }
            } catch (error) {
                console.error('Error fetching templates:', error);
                // Fall back to creating session without template
                this._createSessionWithTemplate(null);
                return;
            }
        }
        
        // Render templates in the modal
        const templateGrid = document.getElementById('template-grid');
        if (templateGrid && this.templates.length > 0) {
            templateGrid.innerHTML = this.templates.map(template => `
                <div class="template-card" data-template-id="${template.id}" tabindex="0" role="button">
                    <div class="template-icon">${this._sanitizeHTML(template.icon)}</div>
                    <div class="template-name">${this._sanitizeHTML(template.name)}</div>
                    <div class="template-description">${this._sanitizeHTML(template.description)}</div>
                    <span class="template-category ${this._sanitizeHTML(template.category)}">${this._sanitizeHTML(template.category)}</span>
                </div>
            `).join('');
            
            // Add click handlers to template cards
            templateGrid.querySelectorAll('.template-card').forEach(card => {
                card.addEventListener('click', () => {
                    this.selectedTemplateId = card.dataset.templateId;
                    this.ui.hideModal('template-modal');
                    this._createSessionWithTemplate(this.selectedTemplateId);
                });
                card.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        card.click();
                    }
                });
            });
        }
        
        this.ui.showModal('template-modal');
    }
    
    async _createSessionWithTemplate(templateId) {
        try {
            this.ui.setStatus('Creating session...', 'processing');
            
            // Build request body
            const requestBody = {
                title: `Session ${new Date().toLocaleString()}`
            };
            if (templateId) {
                requestBody.template_id = templateId;
            }
            if (window.location.search.includes('anonymous')) {
                requestBody.is_anonymous = true;
            }
            
            // Call API to create session
            const response = await this.fetchWithTimeout('/api/sessions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(requestBody)
            });
            
            if (!response.ok) throw new Error('Failed to create session');
            
            const session = await response.json();
            this.sessionId = session.id;
            this.sessionIdEl.textContent = `Session: ${session.id.substring(0, 8)}...`;
            
            // Reset state
            this.currentVersion = 0;
            this.statementCount = 0;
            this.sessionStartTime = Date.now();
            this._reconnectAttempt = 0;
            this.hasReceivedGreeting = false;
            this.lastUserMessage = '';
            this.selectedTemplateId = null;
            this._clearAutoSave();
            this._updateRetryButton();
            
            // Start duration timer
            this.startDurationTimer();
            
            // Start comfort manager interview tracking
            if (this.comfortManager) {
                this.comfortManager.startInterview();
            }
            
            // Clear UI
            const emptyCopy = this.isMobileVoiceUI
                ? 'Tap the big mic below and talk naturally with Officer Ray. Quick phrase chips can help you start fast.'
                : 'Your conversation will appear here. Start by describing what happened.';
            this.chatTranscript.innerHTML = `<p class="empty-state">${this._escapeHtml(emptyCopy)}</p>`;
            this.timeline.innerHTML = '<p class="empty-state">No versions yet</p>';
            
            // Update stats
            this.ui.updateStats({
                versionCount: 0,
                statementCount: 0,
                duration: 0
            });

            // Keep session-scoped voice preferences in sync with persistent local experience settings.
            this.syncVoicePreferencesToSession();
            this._syncAutoListenChip();
            this._syncSpeakerChip();
            this._syncSpeedButtons();
            
            // Connect WebSocket
            this.connectWebSocket();
            
            // Item 27: Show witness info form for first session if not previously shown
            if (!localStorage.getItem('witnessreplay-witness-info-shown')) {
                const overlay = document.getElementById('witness-info-overlay');
                if (overlay) {
                    if (this.anonymousToggle) {
                        this.anonymousToggle.checked = false;
                        this.toggleAnonymousWitness(false);
                    }
                    // Pre-fill from localStorage if returning user
                    const savedName = localStorage.getItem('witnessreplay-witness-name');
                    const savedContact = localStorage.getItem('witnessreplay-witness-contact');
                    const savedLocation = localStorage.getItem('witnessreplay-witness-location');
                    if (savedName) document.getElementById('witness-name').value = savedName;
                    if (savedContact) document.getElementById('witness-contact').value = savedContact;
                    if (savedLocation) document.getElementById('witness-location').value = savedLocation;
                    overlay.style.display = 'flex';
                }
            }
            
            // Reset interview progress
            this.updateInterviewProgress();
            
            // Show toast indicating template if selected
            if (templateId) {
                const template = this.templates.find(t => t.id === templateId);
                if (template) {
                    this.ui.showToast(`${template.icon} Started ${template.name} interview`, 'success');
                }
            }
            
        } catch (error) {
            console.error('Error creating session:', error);
            this.connectionError = error.message || 'Failed to create session';
            this.ui.setStatus('Error creating session', 'default');
            this.ui.showToast('Failed to create session. Please try again.', 'error');
            this.updateConnectionStatus('disconnected');
            this._updateMicState('disconnected');
        }
    }
    
    _formatElapsedDuration(seconds) {
        const s = Math.max(0, Math.floor(seconds || 0));
        const hours = Math.floor(s / 3600);
        const minutes = Math.floor((s % 3600) / 60);
        const secs = s % 60;
        if (hours > 0) {
            return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
        }
        return `${minutes}:${String(secs).padStart(2, '0')}`;
    }

    startDurationTimer() {
        if (this.durationTimer) {
            clearInterval(this.durationTimer);
        }

        const tick = () => {
            if (!this.sessionStartTime) return;
            const elapsed = Math.floor((Date.now() - this.sessionStartTime) / 1000);
            this.ui.updateStats({ duration: elapsed });
            const durationDisplay = document.getElementById('interview-duration-display');
            if (durationDisplay) {
                durationDisplay.textContent = this._formatElapsedDuration(elapsed);
            }
            this._updateInterviewStatsBadge();
        };

        tick();
        this.durationTimer = setInterval(tick, 1000);
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
        
        this._addConnectionStep(`WebSocket → ${wsUrl}`);
        
        // Show WS URL in popup
        const wsUrlEl = document.getElementById('popup-ws-url');
        if (wsUrlEl) {
            wsUrlEl.textContent = `WS: ${wsUrl}`;
            wsUrlEl.style.display = '';
        }
        
        this.ui.setStatus('Connecting to Detective Ray...', 'processing');
        this.updateConnectionStatus('connecting');
        this._updateMicState('connecting');
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            this._isPageClosing = false;
            this._autoListenPausedUntilManual = false;
            this._syncAutoListenButtonState();
            this._reconnectAttempt = 0;
            this.connectionError = null;
            this._addConnectionStep('✅ Connected!');
            this.ui.setStatus('Ready — Press Space to speak', 'default');
            this.micBtn.disabled = false;
            if (this.chatMicBtn) this.chatMicBtn.disabled = false;
            this.textInput.disabled = false;
            this.sendBtn.disabled = false;
            
            // Update connection status indicator and mic state
            this.updateConnectionStatus('connected');
            this._updateMicState('connected');
            this._setConversationState('ready', { silent: true });
            
            // Load witnesses for multi-witness support
            this.loadWitnesses();
            
            this.ui.showToast('🔌 Connected to Detective Ray', 'success', 2000);
        };
        
        this.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            if (message.type === 'ping') {
                this.ws.send(JSON.stringify({type: 'pong', data: {}}));
                return;
            }
            this.handleWebSocketMessage(message);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.connectionError = `WebSocket failed to connect to ${window.location.host}. This may be a CORS/origin issue.`;
            this._addConnectionStep(`❌ WebSocket error (check browser console)`);
            this.ui.setStatus('Connection error', 'default');
            this._setConversationState('ready', { silent: true });
        };
        
        this.ws.onclose = (event) => {
            if (this._isPageClosing) {
                return;
            }
            const reason = event.code === 1006 ? 'Connection refused (CORS or server down)' 
                         : event.code === 403 ? 'Forbidden - origin not allowed'
                         : event.reason || `Code: ${event.code}`;
            this._addConnectionStep(`🔌 Closed: ${reason}`);
            this.connectionError = reason;
            
            this.ui.setStatus('Disconnected', 'default');
            this.micBtn.disabled = true;
            if (this.chatMicBtn) this.chatMicBtn.disabled = true;
            this.textInput.disabled = true;
            this.sendBtn.disabled = true;
            
            // Update connection status indicator
            this.updateConnectionStatus('reconnecting');
            this._updateMicState('connecting');
            this._setConversationState('ready', { silent: true });
            
            // Reconnect with exponential backoff
            if (this.sessionId) {
                this._scheduleReconnect();
            } else {
                
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
    
    _scheduleReconnect() {
        if (this._reconnectAttempt >= 10) {
            this.ui?.showToast('❌ Connection lost. Please refresh the page.', 'error', 0);
            this.updateConnectionStatus('disconnected');
            this._updateMicState('disconnected');
            this.ui.setStatus('Connection lost - Please reload', 'default');
            // Show inline reconnect banner
            this._showReconnectBanner();
            return;
        }
        const delay = Math.min(1000 * Math.pow(2, this._reconnectAttempt), this._maxReconnectDelay);
        this._reconnectAttempt++;
        console.debug(`WebSocket reconnect attempt ${this._reconnectAttempt} in ${delay}ms`);
        
        // Show countdown in status bar
        const secs = Math.ceil(delay / 1000);
        this.ui.setStatus(`Reconnecting in ${secs}s (attempt ${this._reconnectAttempt}/10)...`, 'processing');
        
        // Live countdown
        let remaining = secs;
        if (this._reconnectCountdown) clearInterval(this._reconnectCountdown);
        this._reconnectCountdown = setInterval(() => {
            remaining--;
            if (remaining > 0) {
                this.ui.setStatus(`Reconnecting in ${remaining}s (attempt ${this._reconnectAttempt}/10)...`, 'processing');
            } else {
                clearInterval(this._reconnectCountdown);
                this._reconnectCountdown = null;
            }
        }, 1000);
        
        this.reconnectTimer = setTimeout(() => this.connectWebSocket(), delay);
    }

    _showReconnectBanner() {
        if (document.getElementById('reconnect-banner')) return;
        const banner = document.createElement('div');
        banner.id = 'reconnect-banner';
        banner.style.cssText = 'position:fixed;top:0;left:0;right:0;background:linear-gradient(135deg,#1e40af,#7c3aed);color:#fff;padding:12px 20px;text-align:center;z-index:99999;font-size:0.9rem;display:flex;align-items:center;justify-content:center;gap:12px;box-shadow:0 4px 20px rgba(0,0,0,0.3);';
        banner.innerHTML = `
            <span>📡 Connection to Detective Ray was lost</span>
            <button onclick="location.reload()" style="background:#fff;color:#1e40af;border:none;padding:6px 16px;border-radius:8px;font-weight:600;cursor:pointer;">Reconnect</button>
            <button onclick="this.parentElement.remove()" style="background:transparent;color:rgba(255,255,255,0.7);border:1px solid rgba(255,255,255,0.3);padding:6px 12px;border-radius:8px;cursor:pointer;">Dismiss</button>
        `;
        document.body.appendChild(banner);
    }
    
    updateConnectionStatus(status) {
        const indicator = document.getElementById('connection-status');
        if (!indicator) return;
        this.connectionStatus = status;
        const text = indicator.querySelector('.status-text');
        const popupState = document.getElementById('popup-state');
        const popupSession = document.getElementById('popup-session');
        const popupError = document.getElementById('popup-error');
        
        // Remove all status classes
        indicator.classList.remove('connected', 'reconnecting', 'disconnected', 'connecting');
        indicator.classList.add(status);
        
        // Update popup details
        if (popupSession) {
            if (this.sessionId) {
                popupSession.textContent = `Session: ${this.sessionId}`;
                popupSession.style.display = '';
            } else {
                popupSession.style.display = 'none';
            }
        }
        if (popupError) {
            if (this.connectionError) {
                popupError.textContent = this.connectionError;
                popupError.style.display = '';
            } else {
                popupError.style.display = 'none';
            }
        }
        
        switch(status) {
            case 'connecting':
                if (text) text.textContent = 'Connecting...';
                if (popupState) popupState.textContent = '⏳ Connecting to server...';
                break;
            case 'connected':
                if (text) text.textContent = 'Ready';
                if (popupState) popupState.textContent = '✅ Connected and ready';
                this.connectionError = null;
                if (popupError) popupError.style.display = 'none';
                break;
            case 'reconnecting':
                if (text) text.textContent = 'Reconnecting...';
                if (popupState) popupState.textContent = '🔄 Reconnecting...';
                break;
            case 'disconnected':
                if (text) text.textContent = 'Disconnected';
                if (popupState) popupState.textContent = '❌ Disconnected';
                break;
        }
        this._updateConnectionQualityBadge(status);
    }
    
    handleWebSocketMessage(message) {
        switch (message.type) {
            case 'text':
                const speaker = message.data.speaker || 'agent';
                const originalText = message.data.original_text;
                const language = message.data.language;
                if (speaker === 'agent' && message.data.text) {
                    this.lastAgentMessage = message.data.text;
                }
                
                // Update mic button state for voice-first UX when agent responds
                if (speaker === 'agent' && this.micBtn && !this.isRecording) {
                    this.micBtn.classList.remove('processing');
                    this.micBtn.classList.add('ai-speaking');
                    const micBtnText = this.micBtn.querySelector('.btn-text');
                    if (micBtnText) micBtnText.textContent = 'Detective Ray speaking...';
                    this._setConversationState('speaking');
                    // If TTS is enabled, callbacks will manage mic state reset.
                    // Otherwise, reset to idle after a short delay.
                    if (!(this.ttsPlayer && this.ttsPlayer.isEnabled())) {
                        clearTimeout(this._aiSpeakingTimeout);
                        this._aiSpeakingTimeout = setTimeout(() => {
                            if (this.micBtn && !this.isRecording && !this._isSpeakingResponse) {
                                this.micBtn.classList.remove('ai-speaking');
                                const t = this.micBtn.querySelector('.btn-text');
                                if (t && !this.micBtn.classList.contains('connecting') && !this.micBtn.classList.contains('disconnected')) {
                                    t.textContent = 'Tap to Report';
                                }
                                this._setConversationState('ready');
                                this._showRayListeningCue();
                            }
                        }, 3000);
                    }
                }
                
                // Prevent duplicate greetings on reconnect
                if (speaker === 'agent' && !this.hasReceivedGreeting) {
                    this.hasReceivedGreeting = true;
                    this.displayMessageWithTranslation(message.data.text, speaker, originalText, language);
                    this.ui.playSound('notification');
                    // TTS: Speak agent response for accessibility
                    this.speakAIResponse(message.data.text);
                } else if (speaker === 'agent' && this.hasReceivedGreeting) {
                    // Check if this is the same greeting text (duplicate from reconnect)
                    const isGreeting = message.data.text && message.data.text.includes("I'm Detective Ray");
                    if (!isGreeting) {
                        this.displayMessageWithTranslation(message.data.text, speaker, originalText, language);
                        this.ui.playSound('notification');
                        // TTS: Speak agent response for accessibility
                        this.speakAIResponse(message.data.text);
                    }
                } else {
                    this.displayMessageWithTranslation(message.data.text, speaker, originalText, language);
                }
                break;
            
            case 'scene_update':
                this.updateScene(message.data);
                this.ui.playSound('sceneGenerated');
                this.ui.showToast('Scene updated', 'success', 2000);
                
                // Item 24: Update scene preview from scene_update
                if (message.data.image_data) {
                    const previewPanel = document.getElementById('scene-preview-panel');
                    const previewImage = document.getElementById('scene-preview-image');
                    if (previewPanel) previewPanel.style.display = 'block';
                    if (previewImage) previewImage.src = 'data:image/png;base64,' + message.data.image_data;
                }
                
                // Update mobile scene preview strip
                this._updateMobileSceneStrip(message.data);
                
                // Display inline scene card in chat transcript
                this._displaySceneCard(message.data);
                
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
                if (state === 'listening') {
                    this._setConversationState('listening');
                } else if (state === 'processing' || state === 'generating') {
                    this._setConversationState('thinking');
                } else if (!this.isRecording && !this._isSpeakingResponse) {
                    this._setConversationState('ready');
                }
                
                // Update mic button state for voice-first UX
                if (this.micBtn && !this.isRecording) {
                    this.micBtn.classList.remove('processing', 'ai-speaking');
                    const micBtnText = this.micBtn.querySelector('.btn-text');
                    if (state === 'processing') {
                        this.micBtn.classList.add('processing');
                        if (micBtnText) micBtnText.textContent = 'Processing...';
                    }
                }
                
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

            case 'call_state': {
                const callState = message.data || {};
                if (typeof callState.statement_count === 'number' && this.ui) {
                    this.statementCount = callState.statement_count;
                    this.ui.updateStats({ statementCount: callState.statement_count });
                }
                if (callState.is_speaking) {
                    this._setConversationState('speaking', { silent: true });
                } else if (callState.is_recording) {
                    this._setConversationState('listening', { silent: true });
                } else {
                    const mappedState = this.getStatusState(String(callState.status || ''));
                    if (mappedState === 'listening') this._setConversationState('listening', { silent: true });
                    else if (mappedState === 'processing' || mappedState === 'generating') this._setConversationState('thinking', { silent: true });
                    else this._setConversationState('ready', { silent: true });
                }
                if (Number.isFinite(callState.elapsed_sec) && this.mobileCallElapsed) {
                    this.mobileCallElapsed.textContent = this._formatElapsedDuration(callState.elapsed_sec);
                }
                break;
            }

            case 'voice_hint': {
                const hintState = message.data?.state;
                const hintMessage = message.data?.message;
                if (hintState === 'ready_to_talk') {
                    this._showRayListeningCue();
                } else if (hintState === 'agent_speaking') {
                    this._hideRayListeningCue();
                }

                const now = Date.now();
                const stateChanged = !!hintState && hintState !== this._lastVoiceHintState;
                if (hintState) {
                    this._lastVoiceHintState = hintState;
                }
                const toastCooldownPassed = now - this._lastVoiceHintToastAt > 4500;
                if (hintMessage && this.isMobileVoiceUI && (stateChanged || toastCooldownPassed)) {
                    this.ui?.showToast(hintMessage, 'info', 1200);
                    this._lastVoiceHintToastAt = now;
                }
                break;
            }

            case 'call_metrics':
                this.lastCallMetrics = message.data || null;
                if (Number.isFinite(this.lastCallMetrics?.elapsed_sec) && this.mobileCallElapsed) {
                    this.mobileCallElapsed.textContent = this._formatElapsedDuration(this.lastCallMetrics.elapsed_sec);
                }
                break;
            
            case 'error':
                const errorMsg = `Error: ${message.data.message}`;
                this.ui.setStatus(errorMsg, 'default');
                this.displaySystemMessage(errorMsg);
                this.ui.showToast(message.data.message, 'error');
                this._hideTyping();
                this._setConversationState('ready');
                break;
            
            case 'pong':
                // Heartbeat response
                break;
            
            case 'text_stream':
                this.handleStreamingText(message.data);
                break;
            
            case 'language_changed':
                this.handleLanguageChanged(message.data);
                break;
            
            case 'evidence_tags':
                const tags = message.data?.tags || [];
                if (tags.length) {
                    const tagHtml = tags.map(t => `<span class="evidence-tag">${t}</span>`).join(' ');
                    this.displaySystemMessage(`🏷️ Evidence detected: ${tagHtml}`);
                }
                break;
            
            default:
                console.warn('Unknown message type:', message.type);
        }
    }
    
    handleStreamingText(data) {
        const { chunk, is_final, speaker, message_id } = data;
        
        // Hide typing indicator when streaming starts
        this._hideTyping();
        
        if (!this.streamingMessages[message_id]) {
            // Create new message element for this stream
            if (this.chatTranscript.querySelector('.empty-state')) {
                this.chatTranscript.innerHTML = '';
            }
            
            const messageDiv = document.createElement('div');
            messageDiv.className = `message message-${speaker} streaming`;
            messageDiv.setAttribute('role', 'listitem');
            messageDiv.setAttribute('data-message-id', message_id);
            
            const avatar = speaker === 'user' ? '👤' : speaker === 'agent' ? '🔍' : 'ℹ️';
            const labelText = speaker === 'user' ? 'You' : speaker === 'agent' ? 'Detective Ray' : 'System';
            const now = new Date();
            const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            
            messageDiv.innerHTML = `<span class="msg-avatar">${avatar}</span><strong>${labelText}</strong><span class="msg-time">${timeStr}</span><br><span class="stream-content"></span><span class="stream-cursor">▋</span>`;
            
            this.chatTranscript.appendChild(messageDiv);
            this.streamingMessages[message_id] = {
                element: messageDiv,
                content: ''
            };
            if (speaker === 'agent') {
                this._setConversationState('speaking');
            }
        }
        
        const streamData = this.streamingMessages[message_id];
        
        if (chunk) {
            // Append chunk to content
            streamData.content += chunk;
            const contentSpan = streamData.element.querySelector('.stream-content');
            if (contentSpan) {
                contentSpan.textContent = streamData.content;
            }
            // Scroll to show new content
            this._scrollChatToBottom();
        }
        
        if (is_final) {
            // Remove streaming class and cursor
            streamData.element.classList.remove('streaming');
            const cursor = streamData.element.querySelector('.stream-cursor');
            if (cursor) cursor.remove();
            if (speaker === 'agent') {
                this._addAssistantCopyButton(streamData.element, streamData.content);
            }
            
            // Play notification sound
            this.ui.playSound('notification');
            
            // Clean up tracking
            const finalContent = streamData.content;
            delete this.streamingMessages[message_id];
            
            // TTS: Speak completed streamed agent response
            if (speaker === 'agent' && finalContent) {
                this.lastAgentMessage = finalContent;
                this.speakAIResponse(finalContent);
                if (!(this.ttsPlayer && this.ttsPlayer.isEnabled())) {
                    setTimeout(() => {
                        if (!this.isRecording && !this._isSpeakingResponse) {
                            this._setConversationState('ready');
                            this._showRayListeningCue();
                        }
                    }, 400);
                }
            }
            
            // Update interview progress
            this.updateInterviewProgress();
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
        // If disconnected, attempt reconnect instead of recording
        if (this.micBtn.classList.contains('disconnected')) {
            this._reconnectAttempt = 0;
            this.connectionError = null;
            this._autoCreateSession();
            return;
        }
        
        // Cancel pending auto-listen timer
        if (this._autoListenTimer) {
            clearTimeout(this._autoListenTimer);
            this._autoListenTimer = null;
        }
        
        // Interrupt TTS if speaking (user wants to talk)
        if (this.ttsPlayer && this.ttsPlayer.isCurrentlyPlaying()) {
            this.ttsPlayer.interrupt?.('toggle_recording');
            this._isSpeakingResponse = false;
            this._setMicSpeakingState(false);
            this.recordBargeIn('toggle_recording');
        }
        
        if (this.isRecording) {
            this._autoListenPausedUntilManual = false;
            this._syncAutoListenButtonState();
            this.stopRecording();
        } else {
            this.startRecording({ trigger: 'manual' });
        }
    }
    
    async startRecording(options = {}) {
        const trigger = options?.trigger === 'auto_listen' ? 'auto_listen' : 'manual';
        this._recordingTrigger = trigger;
        if (trigger !== 'auto_listen') {
            this._autoListenPausedUntilManual = false;
            this._syncAutoListenButtonState();
        }
        try {
            if (this.ttsPlayer?.isCurrentlyPlaying()) {
                this.ttsPlayer.interrupt?.('start_recording');
                this._isSpeakingResponse = false;
                this._setMicSpeakingState(false);
                this.recordBargeIn('start_recording');
            }

            // Check secure context first
            if (!window.isSecureContext && 
                window.location.hostname !== 'localhost' && 
                window.location.hostname !== '127.0.0.1') {
                this.ui.showToast('⚠️ Microphone requires HTTPS. Use text input or access via localhost.', 'error', 5000);
                this.displaySystemMessage('⚠️ Voice recording requires a secure connection (HTTPS). Please type your statement instead.');
                this._setConversationState('ready');
                return;
            }
            
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                this.ui.showToast('Microphone not supported in this browser', 'error');
                this._setConversationState('ready');
                return;
            }
            
            // Stop VAD listening to avoid conflicts (we'll restart after recording)
            if (this.vadListening) {
                this.stopVADListening();
            }
            
            // Show "initializing" state on mic button
            if (this.micBtn && trigger !== 'auto_listen') {
                this.micBtn.classList.add('processing');
                this.micBtn.setAttribute('aria-busy', 'true');
                const btnText = this.micBtn.querySelector('.btn-text');
                if (btnText) btnText.textContent = 'Starting mic...';
            }

            // Request permission explicitly — this triggers the browser popup
            try {
                const testStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                testStream.getTracks().forEach(t => t.stop());
                this._micPermissionGranted = true;
            } catch (permErr) {
                console.error('Microphone permission denied:', permErr);
                if (this.micBtn) {
                    this.micBtn.classList.remove('processing');
                    this.micBtn.removeAttribute('aria-busy');
                }
                // Distinguish between "never asked" (no user gesture) vs actually denied
                if (!this._micPermissionGranted && trigger === 'auto_listen') {
                    // Auto-listen tried without prior permission — silently skip
                    console.debug('[AutoListen] Skipping — mic permission not yet granted via user gesture');
                    this._setConversationState('ready');
                    return;
                }
                this.ui.showToast('🎤 Microphone access denied. Check browser permissions.', 'error', 5000);
                this.displaySystemMessage('🎤 Microphone access was denied. Please allow microphone access in your browser settings, or type your statement below.');
                this._setConversationState('ready');
                return;
            }
            
            if (this.audioRecorder) {
                const stream = await this.audioRecorder.start();
                this.isRecording = true;
                
                // Start audio quality analysis on raw stream
                if (this.audioQualityAnalyzer && stream) {
                    this.audioQualityAnalyzer.onWarning = (type, message) => {
                        console.debug(`[AudioQuality] ${type}: ${message}`);
                    };
                    await this.audioQualityAnalyzer.start(stream);
                }
                
                // Wire AGC stats to quality indicator if processor available
                const processor = this.audioRecorder.processor;
                if (processor && this.audioQualityIndicator) {
                    processor.onStatsUpdate = (stats) => {
                        // Override quality label with AGC info
                        const label = this.audioQualityIndicator.label;
                        if (label) {
                            if (stats.isNoiseGated) {
                                label.textContent = 'Ready';
                            } else if (stats.currentGain > 2.0) {
                                label.textContent = 'Boosting';
                            } else if (stats.currentGain < 0.8) {
                                label.textContent = 'Reducing';
                            } else {
                                label.textContent = 'Good';
                            }
                        }
                    };
                }
                if (this.audioQualityIndicator) {
                    this.audioQualityIndicator.show();
                }
                
                // Show voice controls panel
                const voiceControls = document.getElementById('voice-controls');
                if (voiceControls) voiceControls.classList.add('expanded');
                
                this.micBtn.classList.remove('processing');
                this.micBtn.removeAttribute('aria-busy');
                this.micBtn.classList.add('recording');
                const btnText = this.micBtn.querySelector('.btn-text');
                if (btnText) btnText.textContent = 'Listening...';
                if (this.chatMicBtn) {
                    this.chatMicBtn.classList.add('recording');
                    this.chatMicBtn.textContent = '⏹';
                }
                if (this.stopBtn) this.stopBtn.style.display = 'inline-block';
                this.setStatus('Listening...');
                this._setConversationState('listening');
                this.recordCallEvent('recording_started', {
                    auto_listen: this.autoListenEnabled,
                    trigger: this._recordingTrigger,
                });
                this._syncVoiceDockMicLabel();
                
                // Play recording start sound
                this.playSound('recording-start');
                this._vibrate([20, 40, 20]);
                
                // Add pulsing animation to Detective Ray avatar
                const detectiveAvatar = document.querySelector('.detective-avatar');
                if (detectiveAvatar) {
                    detectiveAvatar.classList.add('listening');
                }
                
                // Update VAD indicator to show recording state
                if (this.vadIndicator) {
                    this.vadIndicator.classList.remove('listening', 'speech-detected');
                    this.vadIndicator.classList.add('recording');
                }
            } else {
                this.ui.showToast('Audio recorder not available. Use text input.', 'warning');
            }
        } catch (error) {
            console.error('Error starting recording:', error);
            this.ui.showToast('Microphone error: ' + error.message, 'error');
            this.playSound('error');
            this.displaySystemMessage('🎤 Could not access microphone. Please type your statement instead.');
            this._setConversationState('ready');
        }
    }
    
    async stopRecording() {
        if (!this.isRecording) return;
        
        // Get quality metrics before stopping analyzer
        let qualityMetrics = null;
        if (this.audioQualityAnalyzer) {
            this.audioQualityAnalyzer.stop();
            qualityMetrics = this.audioQualityAnalyzer.getMetrics();
        }
        if (this.audioQualityIndicator) {
            this.audioQualityIndicator.hide();
            this.audioQualityIndicator.reset();
        }
        
        try {
            if (this.audioRecorder) {
                const audioBlob = await this.audioRecorder.stop();
                this.isRecording = false;
                this.micBtn.classList.remove('recording');
                const btnText2 = this.micBtn.querySelector('.btn-text');
                if (btnText2) btnText2.textContent = 'Tap to Report';
                
                // Hide voice controls panel
                const voiceControls = document.getElementById('voice-controls');
                if (voiceControls) voiceControls.classList.remove('expanded');
                if (this.chatMicBtn) {
                    this.chatMicBtn.classList.remove('recording');
                    this.chatMicBtn.textContent = '🎤';
                }
                if (this.stopBtn) this.stopBtn.style.display = 'none';
                this._syncVoiceDockMicLabel();
                
                // Play recording stop sound
                this.playSound('recording-stop');
                this._vibrate(18);
                
                // Remove pulsing animation from Detective Ray avatar
                const detectiveAvatar = document.querySelector('.detective-avatar');
                if (detectiveAvatar) {
                    detectiveAvatar.classList.remove('listening');
                }
                
                const wasAutoListen = this._recordingTrigger === 'auto_listen';
                if (wasAutoListen && this._isLikelySilentAutoCapture(qualityMetrics, audioBlob)) {
                    this._pauseAutoListenUntilManual('silent_auto_capture');
                    this.recordCallEvent('auto_listen_silence', {
                        audio_bytes: audioBlob?.size || 0,
                        quality_score: qualityMetrics?.qualityScore ?? null,
                    });

                    // Restart VAD listening if enabled
                    if (this.vadEnabled && !this.vadListening && this._micPermissionGranted) {
                        setTimeout(() => this.startVADListening(), 500);
                    }
                    return;
                }

                // Convert to base64 and send with quality metrics
                this.sendAudioMessage(audioBlob, qualityMetrics);
                this._setConversationState('thinking');
                this.recordCallEvent('recording_stopped', { has_quality_metrics: !!qualityMetrics });
                
                // Restart VAD listening if enabled
                if (this.vadEnabled && !this.vadListening && this._micPermissionGranted) {
                    setTimeout(() => this.startVADListening(), 500);
                }
            }
        } catch (error) {
            console.error('Error stopping recording:', error);
            this.setStatus('Error processing audio');
            this.playSound('error');
            this._setConversationState('ready');
        }
    }
    
    async sendAudioMessage(audioBlob, qualityMetrics = null) {
        try {
            const reader = new FileReader();
            reader.onloadend = () => {
                const base64Audio = reader.result.split(',')[1];
                
                if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
                    this._queueOfflineMessage({ type: 'audio', data: { audio: base64Audio, format: 'webm' } });
                    return;
                }
                
                const audioSizeKB = Math.round(base64Audio.length * 0.75 / 1024);
                console.debug(`[Audio] Sending ${audioSizeKB}KB audio via WebSocket`);
                
                const messageData = {
                    type: 'audio',
                    data: {
                        audio: base64Audio,
                        format: 'webm',
                        capture_mode: this._recordingTrigger === 'auto_listen' ? 'auto_listen' : 'manual',
                    }
                };
                
                // Include quality metrics if available
                if (qualityMetrics) {
                    messageData.data.quality = {
                        score: qualityMetrics.qualityScore,
                        avgVolume: Math.round(qualityMetrics.avgVolume * 100) / 100,
                        peakVolume: Math.round(qualityMetrics.peakVolume * 100) / 100,
                        clippingEvents: qualityMetrics.clippingEvents,
                        tooQuietSamples: qualityMetrics.tooQuietSamples,
                        tooLoudSamples: qualityMetrics.tooLoudSamples,
                        duration: qualityMetrics.duration
                    };
                }
                
                this.ws.send(JSON.stringify(messageData));
                this.setStatus('Detective Ray is thinking...');
                this._setConversationState('thinking');
            };
            reader.onerror = (err) => {
                console.error('[Audio] FileReader error:', err);
                this.setStatus('Error processing audio');
            };
            reader.readAsDataURL(audioBlob);
        } catch (error) {
            console.error('Error sending audio:', error);
        }
    }
    
    sendTextMessage() {
        const text = this.textInput.value.trim();
        if (!text) return;
        
        // Remove quick reply suggestions when user sends
        const quickReplies = document.querySelector('.quick-reply-container');
        if (quickReplies) quickReplies.remove();
        
        // Slash command support
        if (text.startsWith('/')) {
            this._handleSlashCommand(text);
            return;
        }
        
        this._autoListenPausedUntilManual = false;
        this._syncAutoListenButtonState();
        this.lastUserMessage = text;
        this._updateRetryButton();
        
        // Feature 8: Auto-detect language on first user message
        if (this.statementCount === 0) {
            const detected = this._detectLanguage(text);
            if (detected !== 'en') {
                this.setWitnessLanguage(detected);
                const sel = document.getElementById('language-selector');
                if (sel) sel.value = detected;
                this._showLangDetectBadge(detected);
            }
        }
        
        // Check for distress signals and provide support
        if (this.comfortManager) {
            this.comfortManager.detectDistress(text);
        }
        
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            const messageData = { text: text };
            if (this.activeWitnessId) messageData.witness_id = this.activeWitnessId;
            this._queueOfflineMessage({ type: 'text', data: messageData });
            this.displayMessage(text, 'user');
            this.textInput.value = '';
            this._updateCharCounter();
            return;
        }
        
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            // Include active witness ID for multi-witness support
            const messageData = { text: text };
            if (this.activeWitnessId) {
                messageData.witness_id = this.activeWitnessId;
            }
            
            this.ws.send(JSON.stringify({
                type: 'text',
                data: messageData
            }));
            
            this._showSaveState?.('saving');
            this.displayMessage(text, 'user');
            this.textInput.value = '';
            this._updateCharCounter();
            this.setStatus('Detective Ray is thinking...');
            this._setConversationState('thinking');
            
            // Feature 7: Advance guided mode step
            if (this.guidedMode) this._advanceGuidedStep();
            
            // Refresh witness statement counts after a brief delay
            setTimeout(() => this.loadWitnesses(), 1500);
        }
    }
    
    displayMessage(text, speaker) {
        if (this.chatTranscript.querySelector('.empty-state')) {
            this.chatTranscript.innerHTML = '';
        }
        
        // Hide typing indicator
        this._hideTyping();
        if (speaker === 'agent') this._showSaveState?.('saved');
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${speaker}`;
        messageDiv.setAttribute('role', 'listitem');
        
        const avatar = speaker === 'user' ? '👤' : speaker === 'agent' ? '🔍' : 'ℹ️';
        let labelText = speaker === 'user' ? 'You' : speaker === 'agent' ? 'Detective Ray' : 'System';
        const now = new Date();
        const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        
        // Add witness badge for multi-witness sessions
        let witnessBadge = '';
        if (speaker === 'user' && this.witnesses.length > 0 && this.activeWitnessId) {
            const activeWitness = this.witnesses.find(w => w.id === this.activeWitnessId);
            if (activeWitness) {
                witnessBadge = `<span class="msg-witness-badge">${this.escapeHtmlAttr(activeWitness.name)}</span>`;
            }
        }
        
        messageDiv.innerHTML = `<span class="msg-avatar">${avatar}</span><strong>${labelText}</strong>${witnessBadge}<span class="msg-time">${timeStr}</span>${speaker === 'user' ? `<span class="emotion-badge">${this._getEmotionEmoji(text)}</span>` : ''}<br>${this._escapeHtml(text)}`;
        if (speaker === 'agent') {
            this._addAssistantCopyButton(messageDiv, text);
            this._addMessageReactions(messageDiv, text);
            this._addPinButton?.(messageDiv, text, speaker);
            this.lastAgentMessage = text;
            if (!this._isSpeakingResponse && !this.isRecording) {
                this._setConversationState('ready');
                this._showRayListeningCue();
            }
        }
        if (speaker === 'user') {
            this._addPinButton?.(messageDiv, text, speaker);
        }
        this.chatTranscript.appendChild(messageDiv);
        this._scrollChatToBottom();
        
        // Add timestamp & update phase progress
        this._addMessageTimestamp?.(messageDiv);
        if (speaker === 'user') this._updatePhaseProgress?.();
        if (speaker === 'agent') this._addReadAloudButton?.(messageDiv);
        
        // Update quality score periodically (every 3 user messages)
        if (speaker === 'user') {
            this._qualityMsgCount = (this._qualityMsgCount || 0) + 1;
            if (this._qualityMsgCount % 3 === 0) {
                this._updateQualityScore?.().then(() => {
                    if (this._lastQualityData) this._updateInfoChecklist?.(this._lastQualityData);
                });
            }
        }
        
        // Show quick reply suggestions after agent messages
        if (speaker === 'agent') {
            this._showQuickReplies(text);
        }
        
        // Track statement count for user messages
        if (speaker === 'user') {
            this.statementCount++;
            if (this.statementCountEl) this.statementCountEl.textContent = this.statementCount;
        }
        
        // Update interview progress phases
        this.updateInterviewProgress();
        this._updateInterviewStatsBadge();
    }
    
    /**
     * Display a message with optional translation information
     */
    displayMessageWithTranslation(text, speaker, originalText = null, language = null) {
        if (this.chatTranscript.querySelector('.empty-state')) {
            this.chatTranscript.innerHTML = '';
        }
        
        // Hide typing indicator
        this._hideTyping();
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${speaker}`;
        messageDiv.setAttribute('role', 'listitem');
        
        const avatar = speaker === 'user' ? '👤' : speaker === 'agent' ? '🔍' : 'ℹ️';
        let labelText = speaker === 'user' ? 'You' : speaker === 'agent' ? 'Detective Ray' : 'System';
        const now = new Date();
        const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        
        // Add witness badge for multi-witness sessions
        let witnessBadge = '';
        if (speaker === 'user' && this.witnesses.length > 0 && this.activeWitnessId) {
            const activeWitness = this.witnesses.find(w => w.id === this.activeWitnessId);
            if (activeWitness) {
                witnessBadge = `<span class="msg-witness-badge">${this.escapeHtmlAttr(activeWitness.name)}</span>`;
            }
        }
        
        // Add language badge if translated
        let languageBadge = '';
        if (language && language !== 'en') {
            const languageNames = {
                'es': 'ES', 'zh': 'ZH', 'vi': 'VI', 'ko': 'KO', 'tl': 'TL',
                'ar': 'AR', 'fr': 'FR', 'de': 'DE', 'pt': 'PT', 'ru': 'RU',
                'ja': 'JA', 'hi': 'HI', 'it': 'IT', 'pl': 'PL', 'uk': 'UK',
                'fa': 'FA', 'th': 'TH', 'he': 'HE'
            };
            languageBadge = `<span class="language-badge">🌐 ${languageNames[language] || language.toUpperCase()}</span>`;
        }
        
        // Build translation toggle if original text exists
        let translationInfo = '';
        if (originalText && originalText !== text) {
            const escapedOriginal = this._escapeHtml(originalText);
            translationInfo = `
                <div class="translation-indicator">
                    <span class="translation-toggle" onclick="this.parentElement.querySelector('.original-text').classList.toggle('hidden')">
                        📝 Show original
                    </span>
                    <span class="original-text hidden">${escapedOriginal}</span>
                </div>`;
        }
        
        // Emotion badge for user messages (Feature 6)
        let emotionBadge = speaker === 'user' ? `<span class="emotion-badge">${this._getEmotionEmoji(text)}</span>` : '';
        
        messageDiv.innerHTML = `
            <span class="msg-avatar">${avatar}</span>
            <strong>${labelText}</strong>${witnessBadge}${languageBadge}${emotionBadge}
            <span class="msg-time">${timeStr}</span><br>
            ${this._escapeHtml(text)}
            ${translationInfo}`;
        if (speaker === 'agent') {
            this._addAssistantCopyButton(messageDiv, text);
            this._addMessageReactions(messageDiv, text);
            this._addPinButton?.(messageDiv, text, speaker);
            this.lastAgentMessage = text;
            if (!this._isSpeakingResponse && !this.isRecording) {
                this._setConversationState('ready');
                this._showRayListeningCue();
            }
        }
        if (speaker === 'user') {
            this._addPinButton?.(messageDiv, text, speaker);
        }
        this.chatTranscript.appendChild(messageDiv);
        this._scrollChatToBottom();
        
        // Show quick reply suggestions after agent messages
        if (speaker === 'agent') {
            this._showQuickReplies(text);
        }
        
        // Track statement count for user messages
        if (speaker === 'user') {
            this.statementCount++;
            if (this.statementCountEl) this.statementCountEl.textContent = this.statementCount;
        }
        
        // Update interview progress phases
        this.updateInterviewProgress();
        this._updateInterviewStatsBadge();
    }
    
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    _sanitizeHTML(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
    
    _showTyping() {
        const el = document.getElementById('typing-indicator');
        if (el) {
            el.classList.remove('hidden');
            // Cycle through contextual thinking messages
            const label = el.querySelector('.typing-label');
            if (label) {
                const messages = [
                    'Detective Ray is analyzing...',
                    'Reviewing your statement...',
                    'Reconstructing the scene...',
                    'Processing details...',
                    'Thinking carefully...'
                ];
                label.textContent = messages[0];
                let idx = 0;
                this._typingMsgInterval = setInterval(() => {
                    idx = (idx + 1) % messages.length;
                    label.textContent = messages[idx];
                }, 3000);
            }
        }
        this._scrollChatToBottom();
    }
    
    _hideTyping() {
        const el = document.getElementById('typing-indicator');
        if (el) el.classList.add('hidden');
        if (this._typingMsgInterval) {
            clearInterval(this._typingMsgInterval);
            this._typingMsgInterval = null;
        }
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
            this.sceneDescription.innerHTML = `<p>${this._sanitizeHTML(data.description)}</p>`;
        }
        
        // Update stats
        this.currentVersion = data.version || this.currentVersion + 1;
        if (this.versionCountEl) this.versionCountEl.textContent = this.currentVersion;
        
        if (data.statement_count) {
            if (this.statementCountEl) this.statementCountEl.textContent = data.statement_count;
        }
        
        // Load environmental conditions for this version
        if (this.sessionId && this.currentVersion > 0) {
            loadEnvironmentalConditions(this.sessionId, this.currentVersion);
        }
        
        // Update complexity if available
        if (data.complexity !== undefined) {
            if (this.complexityCard) this.complexityCard.style.display = 'block';
            if (this.complexityScoreEl) this.complexityScoreEl.textContent = (data.complexity * 100).toFixed(0) + '%';
        }
        
        // Update contradictions if available (with severity info)
        if (data.contradictions && data.contradictions.length > 0) {
            if (this.contradictionCard) this.contradictionCard.style.display = 'block';
            if (this.contradictionCountEl) this.contradictionCountEl.textContent = data.contradictions.length;
            
            // Count severity levels
            const severityCounts = { low: 0, medium: 0, high: 0, critical: 0 };
            data.contradictions.forEach(c => {
                const level = c.severity?.level || 'medium';
                severityCounts[level] = (severityCounts[level] || 0) + 1;
            });
            
            // Show toast with severity breakdown
            const criticalCount = severityCounts.critical + severityCounts.high;
            if (criticalCount > 0) {
                this.ui.showToast(`🚨 ${criticalCount} critical/high severity contradiction(s) detected!`, 'error', 5000);
            } else {
                this.ui.showToast(`⚠️ ${data.contradictions.length} contradiction(s) detected`, 'warning', 4000);
            }
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
            img.loading = 'lazy';
            
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
            img.loading = 'lazy';
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
            img.loading = 'lazy';
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
    
    /**
     * Open the comparison modal with version selectors populated
     */
    async openComparisonModal() {
        if (!this.sessionId) {
            this.ui.showToast('No active session', 'warning');
            return;
        }
        
        try {
            // Fetch scene versions from API
            const response = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/scene-versions`);
            if (!response.ok) throw new Error('Failed to fetch versions');
            
            const data = await response.json();
            const versions = data.versions || [];
            
            if (versions.length < 2) {
                this.ui.showToast('Need at least 2 versions to compare', 'warning');
                return;
            }
            
            // Cache versions for later use
            this._sceneVersions = versions;
            
            // Populate version selectors
            const selectA = document.getElementById('comparison-version-a');
            const selectB = document.getElementById('comparison-version-b');
            
            // Clear and populate options
            selectA.innerHTML = '<option value="">Select version...</option>';
            selectB.innerHTML = '<option value="">Select version...</option>';
            
            versions.forEach(v => {
                const ts = v.timestamp ? new Date(v.timestamp).toLocaleString() : '';
                const label = `Version ${v.version} - ${v.element_count} elements${ts ? ' (' + ts + ')' : ''}`;
                selectA.innerHTML += `<option value="${v.version}">${label}</option>`;
                selectB.innerHTML += `<option value="${v.version}">${label}</option>`;
            });
            
            // Default to comparing last two versions
            if (versions.length >= 2) {
                selectA.value = versions[versions.length - 2].version;
                selectB.value = versions[versions.length - 1].version;
            }
            
            // Hide diff summary until comparison is done
            document.getElementById('comparison-diff-summary')?.classList.add('hidden');
            document.getElementById('comparison-changes-panel')?.classList.add('hidden');
            
            // Clear existing content
            document.getElementById('comparison-before').innerHTML = '<p class="empty-state">Select versions to compare</p>';
            document.getElementById('comparison-after').innerHTML = '<p class="empty-state">Select versions to compare</p>';
            document.getElementById('comparison-before-description').textContent = '';
            document.getElementById('comparison-after-description').textContent = '';
            document.getElementById('comparison-elements-a').innerHTML = '';
            document.getElementById('comparison-elements-b').innerHTML = '';
            
            // Show modal
            this.ui.showModal('comparison-modal');
            this.playSound('click');
            
        } catch (err) {
            console.error('Error opening comparison modal:', err);
            this.ui.showToast('Failed to load versions', 'error');
        }
    }
    
    /**
     * Execute the version comparison based on selected versions
     */
    async executeVersionComparison() {
        const selectA = document.getElementById('comparison-version-a');
        const selectB = document.getElementById('comparison-version-b');
        
        const versionA = parseInt(selectA.value);
        const versionB = parseInt(selectB.value);
        
        if (!versionA || !versionB) {
            this.ui.showToast('Select both versions to compare', 'warning');
            return;
        }
        
        if (versionA === versionB) {
            this.ui.showToast('Select different versions to compare', 'warning');
            return;
        }
        
        try {
            // Fetch comparison data from API
            const response = await this.fetchWithTimeout(
                `/api/sessions/${this.sessionId}/scene-versions/compare?version_a=${versionA}&version_b=${versionB}`
            );
            
            if (!response.ok) throw new Error('Failed to compare versions');
            
            const data = await response.json();
            this._renderComparison(data);
            
        } catch (err) {
            console.error('Error comparing versions:', err);
            this.ui.showToast('Failed to compare versions', 'error');
        }
    }
    
    /**
     * Render the comparison data in the modal
     */
    _renderComparison(data) {
        const { version_a, version_b, diff } = data;
        
        // Update headers with timestamps
        document.getElementById('comparison-header-a').textContent = `Version ${version_a.version}`;
        document.getElementById('comparison-header-b').textContent = `Version ${version_b.version}`;
        document.getElementById('comparison-timestamp-a').textContent = 
            version_a.timestamp ? new Date(version_a.timestamp).toLocaleString() : '';
        document.getElementById('comparison-timestamp-b').textContent = 
            version_b.timestamp ? new Date(version_b.timestamp).toLocaleString() : '';
        
        // Update images
        const beforeContainer = document.getElementById('comparison-before');
        const afterContainer = document.getElementById('comparison-after');
        
        if (version_a.image_url) {
            beforeContainer.innerHTML = `<img src="${version_a.image_url}" alt="Version ${version_a.version}" class="comparison-image">`;
        } else {
            beforeContainer.innerHTML = '<p class="empty-state">No image available</p>';
        }
        
        if (version_b.image_url) {
            afterContainer.innerHTML = `<img src="${version_b.image_url}" alt="Version ${version_b.version}" class="comparison-image">`;
        } else {
            afterContainer.innerHTML = '<p class="empty-state">No image available</p>';
        }
        
        // Update descriptions
        document.getElementById('comparison-before-description').textContent = 
            version_a.description || version_a.changes_from_previous || 'No description';
        document.getElementById('comparison-after-description').textContent = 
            version_b.description || version_b.changes_from_previous || 'No description';
        
        // Update diff summary
        const diffSummary = document.getElementById('comparison-diff-summary');
        document.getElementById('diff-added-count').textContent = diff.summary.added_count;
        document.getElementById('diff-removed-count').textContent = diff.summary.removed_count;
        document.getElementById('diff-changed-count').textContent = diff.summary.changed_count;
        document.getElementById('diff-unchanged-count').textContent = diff.summary.unchanged_count;
        diffSummary.classList.remove('hidden');
        
        // Render element lists
        this._renderElementsList('comparison-elements-a', diff.removed, diff.unchanged, 'a');
        this._renderElementsList('comparison-elements-b', diff.added, diff.unchanged, 'b');
        
        // Render detailed changes
        this._renderChangesPanel(diff);
    }
    
    /**
     * Render elements list with diff highlighting
     */
    _renderElementsList(containerId, diffElements, unchanged, side) {
        const container = document.getElementById(containerId);
        if (!container) return;
        
        let html = '';
        
        // Show diff elements first (removed for A, added for B)
        diffElements.forEach(el => {
            const status = side === 'a' ? 'removed' : 'added';
            const icon = side === 'a' ? '➖' : '➕';
            html += `<div class="comparison-element-item ${status}">
                <span>${icon}</span>
                <span class="el-type">${el.type || 'unknown'}</span>
                <span class="el-desc">${this._escapeHtml(el.description || '')}</span>
            </div>`;
        });
        
        // Show unchanged elements
        unchanged.forEach(el => {
            html += `<div class="comparison-element-item">
                <span>•</span>
                <span class="el-type">${el.type || 'unknown'}</span>
                <span class="el-desc">${this._escapeHtml(el.description || '')}</span>
            </div>`;
        });
        
        container.innerHTML = html || '<p class="empty-state">No elements</p>';
    }
    
    /**
     * Render the detailed changes panel
     */
    _renderChangesPanel(diff) {
        const panel = document.getElementById('comparison-changes-panel');
        const list = document.getElementById('comparison-changes-list');
        
        if (!panel || !list) return;
        
        const hasChanges = diff.added.length > 0 || diff.removed.length > 0 || diff.changed.length > 0;
        
        if (!hasChanges) {
            panel.classList.add('hidden');
            return;
        }
        
        let html = '';
        
        // Added elements
        diff.added.forEach(el => {
            html += `<div class="change-item" style="border-left-color: #22c55e;">
                <div class="change-item-header">➕ Added: ${el.type}</div>
                <div class="change-item-detail">${this._escapeHtml(el.description || '')}</div>
                ${el.position ? `<div class="change-item-detail">Position: ${el.position}</div>` : ''}
            </div>`;
        });
        
        // Removed elements
        diff.removed.forEach(el => {
            html += `<div class="change-item" style="border-left-color: #ef4444;">
                <div class="change-item-header">➖ Removed: ${el.type}</div>
                <div class="change-item-detail">${this._escapeHtml(el.description || '')}</div>
            </div>`;
        });
        
        // Changed elements
        diff.changed.forEach(el => {
            let changesHtml = '';
            el.changes.forEach(ch => {
                changesHtml += `<div class="change-item-detail">
                    ${ch.field}: <span class="before">${this._sanitizeHTML(ch.before || 'none')}</span> → <span class="after">${this._sanitizeHTML(ch.after || 'none')}</span>
                </div>`;
            });
            html += `<div class="change-item" style="border-left-color: #eab308;">
                <div class="change-item-header">✏️ Changed: ${el.type}</div>
                <div class="change-item-detail">${this._escapeHtml(el.description || '')}</div>
                ${changesHtml}
            </div>`;
        });
        
        list.innerHTML = html;
        panel.classList.remove('hidden');
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
        
        const changes = data.changes ? `<div class="timeline-changes">✨ ${this._sanitizeHTML(data.changes)}</div>` : '';
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
            
            sessionList.innerHTML = sessions.map(session => {
                const priority = session.metadata?.priority || 'normal';
                const priorityBadge = {
                    'critical': '<span class="priority-badge critical" title="Critical Priority">🚨</span>',
                    'high': '<span class="priority-badge high" title="High Priority">⚠️</span>',
                    'normal': '',
                    'low': '<span class="priority-badge low" title="Low Priority">📁</span>'
                }[priority] || '';
                
                return `
                <div class="session-card ${priority !== 'normal' ? 'priority-' + priority : ''}" data-session-id="${session.id}">
                    <div class="session-details">
                        <div class="session-title">${priorityBadge}${session.title}</div>
                        <div class="session-meta">
                            <span>📅 ${new Date(session.created_at).toLocaleDateString()}</span>
                            <span>💬 ${session.statement_count} statements</span>
                            <span>🎬 ${session.version_count} versions</span>
                        </div>
                    </div>
                    <div class="session-actions">
                        <button class="btn btn-sm btn-warning" onclick="window.app.setSessionPriority('${session.id}')" title="Set priority">
                            🚨
                        </button>
                        <button class="btn btn-sm btn-primary" onclick="window.app.loadSession('${session.id}')">
                            Load
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="window.app.deleteSession('${session.id}')">
                            🗑️
                        </button>
                    </div>
                </div>
            `;
            }).join('');
            
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
            await this.loadVoicePreferencesFromSession();
            
            this.connectWebSocket();
            
            // Load measurements for this session
            this.loadMeasurements();
            
            // Load evidence markers for this session
            this.loadEvidenceMarkers();
            
            // Load sketches for this session
            this.loadSessionSketches(sessionId);
            
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
    
    async setSessionPriority(sessionId) {
        // Show priority selection dialog
        const priorities = ['critical', 'high', 'normal', 'low'];
        const priorityLabels = {
            'critical': '🚨 Critical (Police Emergency)',
            'high': '⚠️ High Priority',
            'normal': '📋 Normal Priority',
            'low': '📁 Low Priority'
        };
        
        // Create a simple selection modal
        const selection = await this._showPrioritySelector(priorityLabels);
        if (!selection) return;
        
        try {
            // Store priority in session metadata
            const response = await this.fetchWithTimeout(`/api/sessions/${sessionId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    metadata: { priority: selection }
                })
            });
            
            if (!response.ok) throw new Error('Failed to set priority');
            
            this.ui.showToast(`Session priority set to ${selection}`, 'success');
            this.showSessionsList(); // Refresh list
            
        } catch (error) {
            console.error('Error setting session priority:', error);
            this.ui.showToast('Failed to set session priority', 'error');
        }
    }
    
    _showPrioritySelector(priorityLabels) {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'modal active';
            modal.id = 'priority-modal';
            modal.innerHTML = `
                <div class="modal-content" style="max-width: 400px;">
                    <div class="modal-header">
                        <h2>Set Session Priority</h2>
                        <button class="close-btn" onclick="this.closest('.modal').remove()">×</button>
                    </div>
                    <div class="modal-body">
                        <p>Select priority level for this session:</p>
                        <div class="priority-options" style="display: flex; flex-direction: column; gap: 10px; margin-top: 15px;">
                            ${Object.entries(priorityLabels).map(([key, label]) => `
                                <button class="btn btn-secondary priority-btn" data-priority="${key}" style="text-align: left; padding: 12px 15px;">
                                    ${label}
                                </button>
                            `).join('')}
                        </div>
                    </div>
                </div>
            `;
            
            document.body.appendChild(modal);
            
            // Handle clicks
            modal.querySelectorAll('.priority-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const priority = btn.dataset.priority;
                    modal.remove();
                    resolve(priority);
                });
            });
            
            // Handle backdrop click
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.remove();
                    resolve(null);
                }
            });
        });
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
        this._scrollChatToBottom('auto');
    }
    
    async handlePhotoUpload(event) {
        const file = event.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (e) => {
            const base64 = e.target.result.split(',')[1];
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({type: 'evidence_upload', data: {file_name: file.name, file_type: file.type, file_data: base64}}));
                const img = document.createElement('img');
                img.src = e.target.result;
                img.className = 'chat-evidence-image';
                img.style.cssText = 'max-width:200px;border-radius:8px;margin:8px 0;';
                this.displayMessage(`📸 Uploaded: ${file.name}`, 'user');
                this.ui.showToast('📸 Photo uploaded', 'success', 1800);
            } else {
                this.ui.showToast('⚠️ Photo upload failed: disconnected', 'error', 2400);
            }
        };
        reader.onerror = () => this.ui.showToast('❌ Failed to read photo file', 'error', 2200);
        reader.readAsDataURL(file);
        event.target.value = '';
    }
    
    showSignaturePrompt() {
        const modal = document.getElementById('signature-modal');
        if (modal) modal.style.display = 'flex';
    }
    
    /**
     * Display an inline scene update card in the chat transcript
     */
    _displaySceneCard(data) {
        const imageUrl = data.image_url || (data.image_data ? 'data:image/png;base64,' + data.image_data : null) || (data.base64_image ? 'data:image/png;base64,' + data.base64_image : null);
        if (!imageUrl && !data.description) return;
        
        if (this.chatTranscript.querySelector('.empty-state')) {
            this.chatTranscript.innerHTML = '';
        }
        
        const card = document.createElement('div');
        card.className = 'message message-scene-card';
        card.setAttribute('role', 'listitem');
        
        const version = data.version || this.currentVersion;
        const now = new Date();
        const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        
        let html = `<div class="scene-card-header"><span class="msg-avatar">🎬</span><strong>Scene Updated</strong><span class="scene-card-version">v${version}</span><span class="msg-time">${timeStr}</span></div>`;
        
        if (imageUrl) {
            html += `<div class="scene-card-thumb"><img src="${imageUrl}" alt="Scene v${version}" class="scene-card-image" loading="lazy"></div>`;
        }
        
        if (data.description) {
            const desc = data.description.length > 120 ? data.description.substring(0, 120) + '…' : data.description;
            html += `<div class="scene-card-desc">${this._escapeHtml(desc)}</div>`;
        }
        
        card.innerHTML = html;
        
        // Make image tappable for fullscreen on mobile
        const thumb = card.querySelector('.scene-card-image');
        if (thumb) {
            thumb.addEventListener('click', () => this._showFullscreenImage(imageUrl, version));
        }
        
        this.chatTranscript.appendChild(card);
        this._scrollChatToBottom();
    }
    
    /**
     * Show a fullscreen overlay for a scene image (mobile-friendly)
     */
    _showFullscreenImage(imageUrl, version) {
        let overlay = document.getElementById('scene-fullscreen-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'scene-fullscreen-overlay';
            overlay.className = 'scene-fullscreen-overlay';
            overlay.innerHTML = `<div class="scene-fullscreen-close">&times;</div><img class="scene-fullscreen-img" alt="Scene fullscreen">`;
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay || e.target.classList.contains('scene-fullscreen-close')) {
                    overlay.classList.remove('visible');
                }
            });
            document.body.appendChild(overlay);
        }
        
        const img = overlay.querySelector('.scene-fullscreen-img');
        if (img) {
            img.src = imageUrl;
            img.alt = `Scene v${version}`;
        }
        overlay.classList.add('visible');
    }

    /**
     * Update the mobile scene preview strip with the latest scene image
     */
    _updateMobileSceneStrip(data) {
        const strip = document.getElementById('mobile-scene-strip');
        const stripImg = document.getElementById('mobile-scene-strip-img');
        if (!strip || !stripImg) return;

        let imageUrl = null;
        if (data.image_data) {
            imageUrl = 'data:image/png;base64,' + data.image_data;
        } else if (data.base64_image) {
            imageUrl = 'data:image/png;base64,' + data.base64_image;
        } else if (data.image_url) {
            imageUrl = data.image_url;
        }
        if (!imageUrl) return;

        stripImg.src = imageUrl;
        strip.classList.add('visible');
        this._triggerSceneUpdatePulse();
        this._updateMobileSceneSubtitle(data);

        // Wire up tap-to-fullscreen (once)
        if (!strip._tapWired) {
            strip._tapWired = true;
            strip.addEventListener('click', () => {
                const src = stripImg.src;
                if (src) this._showFullscreenImage(src, this.currentVersion || '');
            });
        }
    }

    _updateMobileSceneSubtitle(data = {}) {
        if (!this.mobileSceneStripSubtitle) return;
        const elements = Array.isArray(data.elements) ? data.elements : [];
        const countText = elements.length ? `${elements.length} element${elements.length === 1 ? '' : 's'}` : 'Scene refreshed';
        const confidenceValues = elements
            .map((element) => Number(element?.confidence))
            .filter((value) => Number.isFinite(value));
        const avgConfidence = confidenceValues.length
            ? Math.round((confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length) * 100)
            : null;
        this.mobileSceneStripSubtitle.textContent = avgConfidence !== null
            ? `${countText} • ${avgConfidence}% confidence`
            : countText;
    }
    _getSeverityIcon(level) {
        const icons = {
            'low': '🔵',
            'medium': '🟡',
            'high': '🔴',
            'critical': '🟣'
        };
        return icons[level] || '⚪';
    }
    
    displayContradictions(contradictions) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message message-contradiction';
        
        const count = contradictions.length;
        let html = `<strong>⚠️ ${count > 1 ? count + ' Contradictions' : 'Contradiction'} Detected</strong>`;
        html += `<div style="font-size:0.78rem;color:var(--text-muted);margin:4px 0 8px;">The witness provided conflicting details — review carefully.</div>`;
        contradictions.forEach(c => {
            const severity = c.severity || { level: 'medium', score: 0.5 };
            const severityIcon = this._getSeverityIcon(severity.level);
            const scorePercent = Math.round((severity.score || 0.5) * 100);
            const field = this._escapeHtml(c.field || c.element_type || 'Unknown field');
            const oldVal = this._escapeHtml(c.old_value || c.original_value || '');
            const newVal = this._escapeHtml(c.new_value || '');
            const context = c.context ? `<div class="contradiction-context">💡 ${this._escapeHtml(c.context)}</div>` : '';
            
            html += `<div class="contradiction-item severity-${severity.level}">
                <div class="contradiction-header">
                    <div class="contradiction-field">${field}</div>
                    <span class="severity-badge severity-${severity.level}">
                        ${severityIcon} ${severity.level} · ${scorePercent}%
                    </span>
                </div>
                <div class="contradiction-change">
                    <span class="old-value">"${oldVal}"</span>
                    <span class="arrow">→</span>
                    <span class="new-value">"${newVal}"</span>
                </div>
                ${context}
            </div>`;
        });
        
        messageDiv.innerHTML = html;
        this.chatTranscript.appendChild(messageDiv);
        this._scrollChatToBottom('auto');
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
        
        // Item 24: Update scene preview panel
        if (data.image_data) {
            const previewPanel = document.getElementById('scene-preview-panel');
            const previewImage = document.getElementById('scene-preview-image');
            const elemCount = document.getElementById('scene-elements-count');
            if (previewPanel) previewPanel.style.display = 'block';
            if (previewImage) previewImage.src = 'data:image/png;base64,' + data.image_data;
            if (elemCount) elemCount.textContent = `${(data.elements || []).length} elements detected`;
            // Update mobile scene preview strip
            this._updateMobileSceneStrip(data);
        } else if (data.elements && data.elements.length > 0) {
            const previewPanel = document.getElementById('scene-preview-panel');
            const elemCount = document.getElementById('scene-elements-count');
            if (previewPanel) previewPanel.style.display = 'block';
            if (elemCount) elemCount.textContent = `${data.elements.length} elements detected`;
            this._updateMobileSceneSubtitle(data);
        }
        
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
        
        // Build contradiction lookup with severity info
        const contradictionMap = new Map();
        (contradictions || []).forEach(c => {
            const key = c.element || c.element_type + '_' + (c.element_id || '');
            contradictionMap.set(key, c.severity || { level: 'medium', score: 0.5 });
        });
        
        let html = '';
        let needsReviewCount = 0;
        elements.forEach(e => {
            const conf = e.confidence || 0.5;
            const needsReview = e.needs_review || conf < 0.7;
            if (needsReview) needsReviewCount++;
            const confClass = conf >= 0.7 ? 'high' : conf >= 0.4 ? 'med' : 'low';
            const icon = typeIcons[e.type] || '❓';
            const elemKey = e.type + '_' + (e.description || '').substring(0, 30);
            const contradictionSeverity = contradictionMap.get(elemKey);
            const isContradiction = !!contradictionSeverity;
            const severityClass = contradictionSeverity ? `severity-${contradictionSeverity.level}` : '';
            let cardClass = isContradiction ? `evidence-card contradiction ${severityClass}` : 'evidence-card';
            if (needsReview) cardClass += ' needs-review';
            
            let meta = '';
            if (e.color) meta += `🎨 ${e.color} `;
            if (e.position) meta += `📍 ${e.position} `;
            if (e.size) meta += `📐 ${e.size}`;
            
            // Add severity badge if contradiction
            const severityBadge = isContradiction 
                ? `<span class="severity-badge severity-${contradictionSeverity.level}">${this._getSeverityIcon(contradictionSeverity.level)} ${contradictionSeverity.level}</span>`
                : '';
            
            // Add review flag badge if needs review
            const reviewBadge = needsReview && !isContradiction
                ? `<span class="review-badge">⚠️ Review</span>`
                : '';
            
            html += `<div class="${cardClass}">
                <div><span class="ev-icon">${icon}</span><span class="ev-type">${e.type}</span>${severityBadge}${reviewBadge}</div>
                <div class="ev-desc">${this._escapeHtml(e.description || '')}</div>
                <div class="ev-meta">
                    <span class="confidence-dot ${confClass}" title="Confidence: ${Math.round(conf * 100)}%"></span>${Math.round(conf * 100)}%
                    ${meta ? ' · ' + meta : ''}
                </div>
            </div>`;
        });
        
        container.innerHTML = html;
        
        // Update needs review indicator if exists
        const reviewIndicator = document.getElementById('needs-review-count');
        if (reviewIndicator) {
            reviewIndicator.textContent = needsReviewCount;
            reviewIndicator.style.display = needsReviewCount > 0 ? 'inline-flex' : 'none';
        }
        
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
        const mapped = this.getStatusState(String(status || ''));
        if (mapped === 'listening') this._setConversationState('listening');
        else if (mapped === 'processing' || mapped === 'generating') this._setConversationState('thinking');
        else if (!this._isSpeakingResponse && !this.isRecording) this._setConversationState('ready');
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
            
            // Include measurements if available
            if (this.measurementTool && this.measurementTool.measurements.length > 0) {
                data.measurements = this.measurementTool.getMeasurementsSummary();
            }
            
            // Include evidence markers if available
            if (this.evidenceMarkerTool && this.evidenceMarkerTool.markers.length > 0) {
                data.evidence_markers = this.evidenceMarkerTool.getMarkersSummary();
            }
            
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
    
    /**
     * Fetch contradictions for the current session with optional sorting
     * @param {string} sortBy - Sort order: "timestamp", "severity", "severity_desc"
     * @returns {Promise<Object>} Contradiction data with severity distribution
     */
    async fetchContradictions(sortBy = 'severity_desc') {
        if (!this.sessionId) {
            return { contradictions: [], total: 0, severity_distribution: {} };
        }
        
        try {
            const response = await this.fetchWithTimeout(
                `/api/sessions/${this.sessionId}/contradictions?sort_by=${sortBy}`
            );
            
            if (!response.ok) {
                throw new Error('Failed to fetch contradictions');
            }
            
            return await response.json();
        } catch (error) {
            console.error('Error fetching contradictions:', error);
            return { contradictions: [], total: 0, severity_distribution: {} };
        }
    }
    
    /**
     * Display contradictions panel with severity badges and sorting
     * @param {Array} contradictions - List of contradiction objects
     * @param {Object} severityDistribution - Count by severity level
     */
    displayContradictionsPanel(contradictions, severityDistribution = {}) {
        const container = document.getElementById('contradictions-panel');
        if (!container) return;
        
        if (!contradictions || contradictions.length === 0) {
            container.innerHTML = '<p class="empty-state">No contradictions detected</p>';
            return;
        }
        
        // Sort controls
        let html = `
            <div class="contradiction-sort-controls">
                <label>Sort by:</label>
                <select id="contradiction-sort-select" onchange="app.handleContradictionSort(this.value)">
                    <option value="severity_desc">Severity (High→Low)</option>
                    <option value="severity">Severity (Low→High)</option>
                    <option value="timestamp">Time (Oldest first)</option>
                </select>
            </div>
            <div class="severity-summary">
                <span class="severity-badge severity-critical">${severityDistribution.critical || 0} Critical</span>
                <span class="severity-badge severity-high">${severityDistribution.high || 0} High</span>
                <span class="severity-badge severity-medium">${severityDistribution.medium || 0} Medium</span>
                <span class="severity-badge severity-low">${severityDistribution.low || 0} Low</span>
            </div>
        `;
        
        // Contradiction items
        contradictions.forEach(c => {
            const severity = c.severity || { level: 'medium', score: 0.5 };
            const severityIcon = this._getSeverityIcon(severity.level);
            const scorePercent = Math.round((severity.score || 0.5) * 100);
            
            html += `
                <div class="contradiction-item severity-${severity.level}">
                    <div class="contradiction-header">
                        <div class="contradiction-field">${c.element_type || 'Unknown'}: ${c.element_id || ''}</div>
                        <span class="severity-badge severity-${severity.level}">
                            ${severityIcon} ${severity.level}
                        </span>
                    </div>
                    <div class="contradiction-change">
                        <span class="old-value">"${c.original_value}"</span>
                        <span class="arrow">→</span>
                        <span class="new-value">"${c.new_value}"</span>
                    </div>
                    <div class="contradiction-score">
                        Score: ${scorePercent}%
                        ${severity.factors ? ` (Time: ${Math.round((severity.factors.time_discrepancy || 0) * 100)}%, Location: ${Math.round((severity.factors.location_mismatch || 0) * 100)}%)` : ''}
                    </div>
                    ${!c.resolved ? `
                        <button class="btn btn-sm btn-secondary" onclick="app.showResolveContradictionDialog('${c.id}')">
                            Resolve
                        </button>
                    ` : `<span class="resolved-badge">✓ Resolved: ${c.resolution_note || ''}</span>`}
                </div>
            `;
        });
        
        container.innerHTML = html;
    }
    
    /**
     * Handle sort selection change for contradictions
     * @param {string} sortBy - New sort order
     */
    async handleContradictionSort(sortBy) {
        const data = await this.fetchContradictions(sortBy);
        this.displayContradictionsPanel(data.contradictions, data.severity_distribution);
    }
    
    /**
     * Show dialog to resolve a contradiction
     * @param {string} contradictionId - ID of contradiction to resolve
     */
    async showResolveContradictionDialog(contradictionId) {
        const note = prompt('Enter resolution note for this contradiction:');
        if (!note) return;
        
        try {
            const response = await this.fetchWithTimeout(
                `/api/sessions/${this.sessionId}/contradictions/${contradictionId}/resolve`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ resolution_note: note })
                }
            );
            
            if (response.ok) {
                this.ui.showToast('Contradiction resolved', 'success');
                // Refresh the panel
                const data = await this.fetchContradictions('severity_desc');
                this.displayContradictionsPanel(data.contradictions, data.severity_distribution);
            } else {
                throw new Error('Failed to resolve contradiction');
            }
        } catch (error) {
            console.error('Error resolving contradiction:', error);
            this.ui.showToast('Failed to resolve contradiction', 'error');
        }
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
        this._showKeyboardShortcutsHelp();
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
     * Initialize scene measurement tool
     */
    initializeMeasurementTool() {
        // Initialize measurement tool when SceneMeasurementTool is available
        if (typeof SceneMeasurementTool !== 'undefined') {
            this.measurementTool = new SceneMeasurementTool(this);
            
            // Bind measurement button
            const measureBtn = document.getElementById('measure-btn');
            if (measureBtn) {
                measureBtn.addEventListener('click', () => {
                    if (this.measurementTool) {
                        this.measurementTool.showMeasurementMenu();
                    }
                });
            }
        }
    }
    
    /**
     * Load measurements for current session
     */
    async loadMeasurements() {
        if (this.measurementTool && this.sessionId) {
            await this.measurementTool.loadMeasurements();
        }
    }
    
    /**
     * Initialize evidence marker tool
     */
    initializeEvidenceMarkerTool() {
        // Initialize evidence marker tool when EvidenceMarkerTool is available
        if (typeof EvidenceMarkerTool !== 'undefined') {
            this.evidenceMarkerTool = new EvidenceMarkerTool(this);
            
            // Bind evidence marker button (added dynamically by the tool)
            const markerBtn = document.getElementById('evidence-marker-btn');
            if (markerBtn) {
                markerBtn.addEventListener('click', () => {
                    if (this.evidenceMarkerTool) {
                        this.evidenceMarkerTool.showMarkerMenu();
                    }
                });
            }
        }
    }
    
    /**
     * Load evidence markers for current session
     */
    async loadEvidenceMarkers() {
        if (this.evidenceMarkerTool && this.sessionId) {
            await this.evidenceMarkerTool.loadMarkers();
        }
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

    // ==================== Interview Comfort Features ====================
    
    initializeComfortFeatures() {
        // Initialize the comfort manager
        if (window.InterviewComfortManager) {
            this.comfortManager = new InterviewComfortManager(this);
        }
        
        // Update duration display periodically
        setInterval(() => {
            if (this.comfortManager && this.sessionStartTime) {
                this.comfortManager.updateDurationDisplay();
                this.updateBreaksCount();
            }
        }, 1000);
    }
    
    updateBreaksCount() {
        if (!this.comfortManager) return;
        const progress = this.comfortManager.getProgress();
        const countEl = document.getElementById('breaks-count');
        if (countEl) {
            countEl.textContent = progress.breaksTaken;
        }
    }
    
    getInterviewProgress() {
        // Get comprehensive interview progress including comfort metrics
        const comfortProgress = this.comfortManager ? this.comfortManager.getProgress() : {};
        return {
            sessionId: this.sessionId,
            statementCount: this.statementCount,
            currentVersion: this.currentVersion,
            ...comfortProgress
        };
    }

    // ==================== Multi-Witness Management ====================
    
    initializeWitnessTabs() {
        const addWitnessBtn = document.getElementById('add-witness-btn');
        if (addWitnessBtn) {
            addWitnessBtn.addEventListener('click', () => this.showAddWitnessModal());
        }
    }
    
    /**
     * Initialize the language selector for translation support
     */
    initializeLanguageSelector() {
        this.selectedLanguage = localStorage.getItem('witnessLanguage') || 'en';
        const languageSelector = document.getElementById('language-selector');
        
        if (languageSelector) {
            // Set initial value from localStorage
            languageSelector.value = this.selectedLanguage;
            
            // Handle language change
            languageSelector.addEventListener('change', (e) => {
                const newLanguage = e.target.value;
                this.setWitnessLanguage(newLanguage);
            });
        }
    }
    
    /**
     * Set the witness language and notify the server
     */
    setWitnessLanguage(languageCode) {
        this.selectedLanguage = languageCode;
        localStorage.setItem('witnessLanguage', languageCode);
        
        // Notify server via WebSocket if connected
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'set_language',
                data: { language: languageCode }
            }));
        }
        
        // Update placeholder text based on language
        this.updatePlaceholderForLanguage(languageCode);
        
        console.debug(`Language set to: ${languageCode}`);
    }
    
    /**
     * Update input placeholder based on selected language
     */
    updatePlaceholderForLanguage(languageCode) {
        const placeholders = {
            'en': 'Describe what you witnessed...',
            'es': 'Describa lo que presenció...',
            'zh': '描述您目睹的情况...',
            'vi': 'Mô tả những gì bạn đã chứng kiến...',
            'ko': '목격한 것을 설명해 주세요...',
            'tl': 'Ilarawan ang iyong nasaksihan...',
            'ar': 'صف ما شهدته...',
            'fr': 'Décrivez ce que vous avez vu...',
            'de': 'Beschreiben Sie, was Sie gesehen haben...',
            'pt': 'Descreva o que você testemunhou...',
            'ru': 'Опишите, что вы видели...',
            'ja': '目撃したことを説明してください...',
            'hi': 'आपने जो देखा उसका वर्णन करें...',
            'it': 'Descrivi cosa hai visto...',
            'pl': 'Opisz, co widziałeś...',
            'uk': 'Опишіть, що ви бачили...',
            'fa': 'آنچه را که شاهد بودید توصیف کنید...',
            'th': 'อธิบายสิ่งที่คุณเห็น...',
            'he': 'תאר את מה שראית...'
        };
        
        const textInput = document.getElementById('text-input');
        if (textInput) {
            textInput.placeholder = placeholders[languageCode] || placeholders['en'];
        }
    }
    
    /**
     * Handle language change confirmation from server
     */
    handleLanguageChanged(data) {
        const languageName = data.language_name || data.language;
        this.ui?.showNotification(`Language set to ${languageName}`, 'success');
    }
    
    /**
     * Load witnesses for current session and update UI
     */
    async loadWitnesses() {
        if (!this.sessionId) return;
        
        try {
            // Request reliability scores with witnesses
            const response = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/witnesses?include_reliability=true`);
            if (!response.ok) return;
            
            const data = await response.json();
            this.witnesses = data.witnesses || [];
            this.activeWitnessId = data.active_witness_id;
            
            this.renderWitnessTabs();
        } catch (e) {
            console.warn('Failed to load witnesses:', e);
        }
    }
    
    /**
     * Get reliability grade color class
     */
    getReliabilityGradeClass(grade) {
        const classes = {
            'A': 'reliability-grade-a',
            'B': 'reliability-grade-b',
            'C': 'reliability-grade-c',
            'D': 'reliability-grade-d',
            'F': 'reliability-grade-f',
        };
        return classes[grade] || 'reliability-grade-c';
    }
    
    /**
     * Format reliability tooltip content
     */
    formatReliabilityTooltip(reliability) {
        if (!reliability) return 'No reliability data yet';
        const factors = reliability.factors || {};
        return `Reliability: ${reliability.overall_score?.toFixed(1) || 'N/A'}/100 (Grade ${reliability.reliability_grade || 'N/A'})
Consistency: ${((factors.consistency_score || 0) * 100).toFixed(0)}%
Evidence Alignment: ${((factors.evidence_alignment || 0) * 100).toFixed(0)}%
Contradictions: ${reliability.contradiction_count || 0}
Corrections: ${reliability.correction_count || 0}`;
    }
    
    /**
     * Render witness tabs in the UI
     */
    renderWitnessTabs() {
        const tabsContainer = document.getElementById('witness-tabs');
        const selectorBar = document.getElementById('witness-selector-bar');
        
        if (!tabsContainer || !selectorBar) return;
        
        // Show/hide witness bar based on whether we have multiple witnesses
        if (this.witnesses.length > 0) {
            selectorBar.style.display = 'flex';
            
            tabsContainer.innerHTML = this.witnesses.map(witness => {
                const reliability = witness.reliability;
                const grade = reliability?.reliability_grade || '';
                const gradeClass = grade ? this.getReliabilityGradeClass(grade) : '';
                const tooltip = this.formatReliabilityTooltip(reliability);
                const score = reliability?.overall_score;
                
                return `
                <div class="witness-tab ${witness.id === this.activeWitnessId ? 'active' : ''}"
                     data-witness-id="${witness.id}"
                     onclick="window.app.setActiveWitness('${witness.id}')"
                     title="${this.escapeHtmlAttr(tooltip)}">
                    <span class="witness-avatar">${this.getWitnessInitials(witness.name)}</span>
                    <span class="witness-tab-name">${this.escapeHtmlAttr(witness.name)}</span>
                    <span class="witness-stmt-count">${witness.statement_count || 0}</span>
                    ${grade ? `<span class="witness-reliability-badge ${gradeClass}" onclick="event.stopPropagation(); window.app.showWitnessReliabilityModal('${witness.id}')">${grade}</span>` : ''}
                </div>
            `}).join('');
        } else {
            selectorBar.style.display = 'none';
        }
    }
    
    /**
     * Get initials from witness name
     */
    getWitnessInitials(name) {
        if (!name) return '?';
        const parts = name.trim().split(/\s+/);
        if (parts.length >= 2) {
            return (parts[0][0] + parts[1][0]).toUpperCase();
        }
        return name.substring(0, 2).toUpperCase();
    }
    
    /**
     * Set the active witness for new statements
     */
    async setActiveWitness(witnessId) {
        if (!this.sessionId) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/witnesses/${witnessId}/activate`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'}
            });
            
            if (response.ok) {
                const data = await response.json();
                this.activeWitnessId = data.active_witness_id;
                this.renderWitnessTabs();
                this.ui.showToast(`👤 Switched to ${data.witness_name}`, 'success', 2000);
            }
        } catch (e) {
            console.error('Failed to set active witness:', e);
            this.ui.showToast('Failed to switch witness', 'error');
        }
    }
    
    /**
     * Show modal to add a new witness
     */
    showAddWitnessModal() {
        // Create a simple modal for adding a witness
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.id = 'add-witness-modal';
        modal.style.display = 'flex';
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 400px;">
                <div class="modal-header">
                    <h2>➕ Add Witness</h2>
                    <button class="modal-close" onclick="this.closest('.modal').remove()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label for="new-witness-name">Witness Name</label>
                        <input type="text" id="new-witness-name" placeholder="Enter witness name" autofocus>
                    </div>
                    <div class="form-group">
                        <label for="new-witness-contact">Contact (optional)</label>
                        <input type="text" id="new-witness-contact" placeholder="Phone or email">
                    </div>
                    <div class="form-group">
                        <label for="new-witness-location">Location at Incident (optional)</label>
                        <input type="text" id="new-witness-location" placeholder="Where were they?">
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">Cancel</button>
                    <button class="btn btn-primary" onclick="window.app.addWitness()">Add Witness</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        
        // Focus the name input
        document.getElementById('new-witness-name')?.focus();
        
        // Handle Enter key
        modal.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.addWitness();
            }
        });
    }
    
    /**
     * Add a new witness to the session
     */
    async addWitness() {
        const nameInput = document.getElementById('new-witness-name');
        const contactInput = document.getElementById('new-witness-contact');
        const locationInput = document.getElementById('new-witness-location');
        
        const name = nameInput?.value?.trim() || 'Anonymous Witness';
        const contact = contactInput?.value?.trim() || null;
        const location = locationInput?.value?.trim() || null;
        
        if (!this.sessionId) {
            this.ui.showToast('No active session', 'error');
            return;
        }
        
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/witnesses`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name, contact, location })
            });
            
            if (response.ok) {
                const witness = await response.json();
                this.ui.showToast(`👤 Added witness: ${witness.name}`, 'success');
                
                // Close modal
                document.getElementById('add-witness-modal')?.remove();
                
                // Reload witnesses and set as active
                await this.loadWitnesses();
                await this.setActiveWitness(witness.id);
            } else {
                throw new Error('Failed to add witness');
            }
        } catch (e) {
            console.error('Failed to add witness:', e);
            this.ui.showToast('Failed to add witness', 'error');
        }
    }
    
    /**
     * Show detailed reliability modal for a witness
     */
    async showWitnessReliabilityModal(witnessId) {
        if (!this.sessionId) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/witnesses/${witnessId}/reliability`);
            if (!response.ok) throw new Error('Failed to fetch reliability');
            
            const data = await response.json();
            const factors = data.factors || {};
            const stats = data.stats || {};
            
            // Create modal
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.id = 'reliability-modal';
            modal.style.display = 'flex';
            modal.innerHTML = `
                <div class="modal-content" style="max-width: 500px;">
                    <div class="modal-header">
                        <h2>📊 Witness Reliability</h2>
                        <button class="modal-close" onclick="this.closest('.modal').remove()">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="reliability-header">
                            <div class="reliability-score-large ${this.getReliabilityGradeClass(data.reliability_grade)}">
                                <span class="score-value">${data.overall_score?.toFixed(1) || 'N/A'}</span>
                                <span class="score-label">/100</span>
                            </div>
                            <div class="reliability-grade-badge ${this.getReliabilityGradeClass(data.reliability_grade)}">
                                Grade ${data.reliability_grade || 'N/A'}
                            </div>
                        </div>
                        
                        <div class="reliability-witness-name">${this.escapeHtmlAttr(data.witness_name || 'Unknown')}</div>
                        
                        <h3>Reliability Factors</h3>
                        <div class="reliability-factors">
                            <div class="factor-row">
                                <span class="factor-label">Consistency</span>
                                <div class="factor-bar">
                                    <div class="factor-fill" style="width: ${(factors.consistency_score || 0) * 100}%; background: var(--success-color);"></div>
                                </div>
                                <span class="factor-value">${((factors.consistency_score || 0) * 100).toFixed(0)}%</span>
                            </div>
                            <div class="factor-row">
                                <span class="factor-label">Evidence Alignment</span>
                                <div class="factor-bar">
                                    <div class="factor-fill" style="width: ${(factors.evidence_alignment || 0) * 100}%; background: var(--info-color);"></div>
                                </div>
                                <span class="factor-value">${((factors.evidence_alignment || 0) * 100).toFixed(0)}%</span>
                            </div>
                            <div class="factor-row">
                                <span class="factor-label">Statement Detail</span>
                                <div class="factor-bar">
                                    <div class="factor-fill" style="width: ${(factors.statement_detail || 0) * 100}%; background: var(--primary-color);"></div>
                                </div>
                                <span class="factor-value">${((factors.statement_detail || 0) * 100).toFixed(0)}%</span>
                            </div>
                            <div class="factor-row">
                                <span class="factor-label">Contradiction Rate</span>
                                <div class="factor-bar">
                                    <div class="factor-fill" style="width: ${(factors.contradiction_rate || 0) * 100}%; background: var(--error-color);"></div>
                                </div>
                                <span class="factor-value">${((factors.contradiction_rate || 0) * 100).toFixed(0)}%</span>
                            </div>
                            <div class="factor-row">
                                <span class="factor-label">Correction Frequency</span>
                                <div class="factor-bar">
                                    <div class="factor-fill" style="width: ${(factors.correction_frequency || 0) * 100}%; background: var(--warning-color);"></div>
                                </div>
                                <span class="factor-value">${((factors.correction_frequency || 0) * 100).toFixed(0)}%</span>
                            </div>
                        </div>
                        
                        <h3>Statistics</h3>
                        <div class="reliability-stats">
                            <div class="stat-item">
                                <span class="stat-value">${stats.total_statements || 0}</span>
                                <span class="stat-label">Statements</span>
                            </div>
                            <div class="stat-item stat-positive">
                                <span class="stat-value">${stats.confirmation_count || 0}</span>
                                <span class="stat-label">Confirmations</span>
                            </div>
                            <div class="stat-item stat-negative">
                                <span class="stat-value">${stats.contradiction_count || 0}</span>
                                <span class="stat-label">Contradictions</span>
                            </div>
                            <div class="stat-item stat-neutral">
                                <span class="stat-value">${stats.correction_count || 0}</span>
                                <span class="stat-label">Corrections</span>
                            </div>
                            <div class="stat-item">
                                <span class="stat-value">${stats.evidence_matches || 0}</span>
                                <span class="stat-label">Evidence Matches</span>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">Close</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        } catch (e) {
            console.error('Failed to show reliability modal:', e);
            this.ui.showToast('Failed to load reliability data', 'error');
        }
    }
    
    /**
     * Helper to escape HTML for attributes
     */
    escapeHtmlAttr(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    // ==================== ITEM 25: Interview Progress Phases ====================
    updateInterviewProgress() {
        const totalMessages = this.chatTranscript ? this.chatTranscript.querySelectorAll('.message').length : 0;
        const phases = document.querySelectorAll('#interview-progress .phase');
        const fill = document.getElementById('interview-progress-fill');
        if (!phases.length || !fill) return;

        let currentPhase = 'intro';
        let pct = 10;

        if (totalMessages <= 2) {
            currentPhase = 'intro';
            pct = 10;
        } else if (totalMessages <= 6) {
            currentPhase = 'narrative';
            pct = 20 + ((totalMessages - 2) / 4) * 30;
        } else if (totalMessages <= 14) {
            currentPhase = 'details';
            pct = 50 + ((totalMessages - 6) / 8) * 30;
        } else {
            currentPhase = 'review';
            pct = Math.min(80 + ((totalMessages - 14) / 4) * 20, 100);
        }

        const phaseOrder = ['intro', 'narrative', 'details', 'review'];
        const currentIdx = phaseOrder.indexOf(currentPhase);

        phases.forEach(ph => {
            const phName = ph.getAttribute('data-phase');
            const phIdx = phaseOrder.indexOf(phName);
            ph.classList.remove('active', 'completed');
            if (phIdx < currentIdx) ph.classList.add('completed');
            else if (phIdx === currentIdx) ph.classList.add('active');
        });

        fill.style.width = Math.round(pct) + '%';

        // Reveal interview progress bar on desktop once past intro
        const progressEl = document.getElementById('interview-progress');
        if (progressEl && currentPhase !== 'intro') {
            progressEl.classList.add('has-progress');
        }

        // Show review testimony button once in details or review phase
        const reviewBtn = document.getElementById('review-testimony-btn');
        if (reviewBtn && totalMessages >= 6) {
            reviewBtn.style.display = 'flex';
        }
    }

    // ==================== ITEM 29: Evidence Photo Upload ====================
    handleEvidenceUpload(event) {
        const file = event.target.files[0];
        if (!file) return;

        if (!file.type.startsWith('image/')) {
            this.ui.showToast('Please select an image file', 'warning');
            return;
        }

        if (file.size > 10 * 1024 * 1024) {
            this.ui.showToast('Image must be under 10MB', 'warning');
            return;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            const base64Data = e.target.result;

            // Display thumbnail in chat
            if (this.chatTranscript.querySelector('.empty-state')) {
                this.chatTranscript.innerHTML = '';
            }
            const msgDiv = document.createElement('div');
            msgDiv.className = 'message message-user';
            msgDiv.setAttribute('role', 'listitem');
            const now = new Date();
            const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            msgDiv.innerHTML = `<span class="msg-avatar">👤</span><strong>You</strong><span class="msg-time">${timeStr}</span><br>📎 Evidence photo attached<br><img src="${base64Data}" alt="Evidence photo uploaded by witness" class="evidence-thumbnail">`;
            this.chatTranscript.appendChild(msgDiv);
            this._scrollChatToBottom();

            // Send via WebSocket if connected
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({
                    type: 'evidence_photo',
                    data: {
                        image: base64Data.split(',')[1],
                        filename: file.name,
                        mime_type: file.type
                    }
                }));
                this.ui.showToast('📎 Evidence uploaded', 'success', 1800);
            } else {
                this.ui.showToast('⚠️ Evidence attached locally while disconnected', 'warning', 2200);
            }

            this.statementCount++;
            if (this.statementCountEl) this.statementCountEl.textContent = this.statementCount;
            this.updateInterviewProgress();
        };
        reader.onerror = () => {
            this.ui.showToast('❌ Failed to read evidence file', 'error', 2200);
        };
        reader.readAsDataURL(file);

        // Reset input so the same file can be re-selected
        event.target.value = '';
    }

    // ==================== ITEM 30: Witness Sketch Upload ====================
    async handleSketchUpload(event) {
        const file = event.target.files[0];
        if (!file) return;

        if (!file.type.startsWith('image/')) {
            this.ui.showToast('Please select an image file', 'warning');
            return;
        }

        if (file.size > 10 * 1024 * 1024) {
            this.ui.showToast('Image must be under 10MB', 'warning');
            return;
        }

        if (!this.sessionId) {
            this.ui.showToast('No active session', 'warning');
            return;
        }

        // Show uploading state
        this.ui.showToast('✏️ Uploading sketch...', 'info');

        try {
            // Create form data
            const formData = new FormData();
            formData.append('image', file);
            
            // Optional: Get description from user
            const description = prompt('Briefly describe what your sketch shows (optional):');
            if (description) {
                formData.append('description', description);
            }

            // Upload to API
            const response = await this.fetchWithTimeout(
                `/api/sessions/${this.sessionId}/sketches`,
                {
                    method: 'POST',
                    body: formData
                },
                30000 // 30 second timeout for upload + AI processing
            );

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Upload failed');
            }

            const sketch = await response.json();

            // Display in chat
            if (this.chatTranscript.querySelector('.empty-state')) {
                this.chatTranscript.innerHTML = '';
            }
            const msgDiv = document.createElement('div');
            msgDiv.className = 'message message-user';
            msgDiv.setAttribute('role', 'listitem');
            const now = new Date();
            const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            
            let interpretationHtml = '';
            if (sketch.ai_interpretation) {
                interpretationHtml = `<div class="sketch-interpretation"><strong>AI Analysis:</strong> ${sketch.ai_interpretation}</div>`;
            }
            
            msgDiv.innerHTML = `
                <span class="msg-avatar">👤</span>
                <strong>You</strong>
                <span class="msg-time">${timeStr}</span>
                <br>✏️ Hand-drawn sketch uploaded
                ${description ? `<br><em>"${description}"</em>` : ''}
                <br><img src="${sketch.image_url}" alt="Hand-drawn sketch uploaded by witness" class="sketch-thumbnail" style="max-width: 200px; border: 2px solid var(--accent-primary); border-radius: 8px; margin-top: 8px;">
                ${interpretationHtml}
            `;
            this.chatTranscript.appendChild(msgDiv);
            this._scrollChatToBottom();

            // Add to sketches gallery
            this.addSketchToGallery(sketch);

            // Update stats
            this.statementCount++;
            if (this.statementCountEl) this.statementCountEl.textContent = this.statementCount;
            this.updateInterviewProgress();

            this.ui.showToast('✏️ Sketch uploaded and analyzed!', 'success');
            this.playSound('success');

            // If AI found elements, send them as context to the conversation
            if (sketch.extracted_elements && sketch.extracted_elements.length > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
                const elementsText = sketch.extracted_elements
                    .map(e => `${e.type}: ${e.description}`)
                    .join(', ');
                this.ws.send(JSON.stringify({
                    type: 'text',
                    data: `[SKETCH ANALYSIS] The witness uploaded a sketch showing: ${elementsText}`
                }));
            }

        } catch (error) {
            console.error('[App] Sketch upload failed:', error);
            this.ui.showToast(`❌ ${error.message}`, 'error');
        }

        // Reset input so the same file can be re-selected
        event.target.value = '';
    }

    addSketchToGallery(sketch) {
        const panel = document.getElementById('witness-sketches-panel');
        const gallery = document.getElementById('sketches-gallery');
        const countEl = document.getElementById('sketches-count');
        
        if (!panel || !gallery) return;

        // Show the panel
        panel.style.display = 'block';

        // Clear empty state if present
        const emptyState = gallery.querySelector('.empty-state');
        if (emptyState) {
            gallery.innerHTML = '';
        }

        // Create sketch card
        const card = document.createElement('div');
        card.className = 'sketch-card';
        card.dataset.sketchId = sketch.id;
        card.innerHTML = `
            <div class="sketch-image-container">
                <img src="${sketch.image_url}" alt="Witness sketch" class="sketch-image" onclick="openSketchModal('${sketch.id}')">
            </div>
            <div class="sketch-info">
                ${sketch.description ? `<p class="sketch-description">${sketch.description}</p>` : ''}
                ${sketch.ai_interpretation ? `<p class="sketch-ai-interpretation"><strong>AI:</strong> ${sketch.ai_interpretation.substring(0, 100)}${sketch.ai_interpretation.length > 100 ? '...' : ''}</p>` : ''}
                <span class="sketch-timestamp">${new Date(sketch.timestamp).toLocaleTimeString()}</span>
            </div>
        `;
        gallery.appendChild(card);

        // Update count
        if (countEl) {
            const currentCount = parseInt(countEl.textContent) || 0;
            countEl.textContent = currentCount + 1;
        }
    }

    async loadSessionSketches(sessionId) {
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${sessionId}/sketches`);
            if (response.ok) {
                const data = await response.json();
                const sketches = data.sketches || [];
                
                // Clear and repopulate gallery
                const gallery = document.getElementById('sketches-gallery');
                const panel = document.getElementById('witness-sketches-panel');
                const countEl = document.getElementById('sketches-count');
                
                if (gallery) {
                    gallery.innerHTML = '';
                    if (sketches.length === 0) {
                        gallery.innerHTML = '<p class="empty-state">No sketches uploaded yet. Use the ✏️ button to upload hand-drawn sketches.</p>';
                        if (panel) panel.style.display = 'none';
                    } else {
                        if (panel) panel.style.display = 'block';
                        sketches.forEach(sketch => this.addSketchToGallery(sketch));
                    }
                }
                if (countEl) countEl.textContent = sketches.length;
            }
        } catch (error) {
            console.warn('[App] Failed to load sketches:', error);
        }
    }

    showStreetView(lat, lng) {
        const container = document.getElementById('scene-editor-canvas') || document.getElementById('scene-preview');
        if (!container) return;
        const iframe = document.createElement('iframe');
        iframe.id = 'street-view-frame';
        iframe.style.cssText = 'width:100%;height:100%;border:none;border-radius:8px;position:absolute;top:0;left:0;z-index:4;';
        // Use OpenStreetMap embed as free alternative
        iframe.src = `https://www.openstreetmap.org/export/embed.html?bbox=${lng-0.002},${lat-0.002},${lng+0.002},${lat+0.002}&layer=mapnik&marker=${lat},${lng}`;
        container.style.position = 'relative';
        container.appendChild(iframe);
        // Close button
        const closeBtn = document.createElement('button');
        closeBtn.textContent = '✕ Close Map';
        closeBtn.className = 'btn btn-sm btn-secondary';
        closeBtn.style.cssText = 'position:absolute;top:8px;right:8px;z-index:5;';
        closeBtn.onclick = () => { iframe.remove(); closeBtn.remove(); };
        container.appendChild(closeBtn);
    }
    
    // ===== Feature 6: Emotion Detection =====
    _detectEmotion(text) {
        const t = text.toLowerCase();
        if (/scared|afraid|terrified|fear|panic/.test(t)) return 'distressed';
        if (/angry|furious|mad|rage/.test(t)) return 'angry';
        if (/confused|unsure|don't know|not sure/.test(t)) return 'confused';
        if (/sad|crying|devastated|upset/.test(t)) return 'sad';
        if (/nervous|anxious|worried|shaking/.test(t)) return 'anxious';
        return 'neutral';
    }
    
    _getEmotionEmoji(text) {
        const emotion = this._detectEmotion(text);
        return this.emotionEmojis[emotion] || '😐';
    }
    
    // ===== Feature 7: Guided Walkthrough =====
    _initModeToggles() {
        const guidedBtn = document.getElementById('guided-mode-btn');
        const childBtn = document.getElementById('child-mode-btn');
        const hcBtn = document.getElementById('high-contrast-btn');
        
        if (guidedBtn) guidedBtn.addEventListener('click', () => this.toggleGuidedMode());
        if (childBtn) childBtn.addEventListener('click', () => this.toggleChildMode());
        if (hcBtn) hcBtn.addEventListener('click', () => this.toggleHighContrast());
    }
    
    toggleGuidedMode() {
        this.guidedMode = !this.guidedMode;
        const btn = document.getElementById('guided-mode-btn');
        if (btn) btn.classList.toggle('active', this.guidedMode);
        const suggestionsEl = document.getElementById('guided-suggestions');
        if (this.guidedMode) {
            this.guidedStep = 0;
            this._showGuidedChip();
        } else if (suggestionsEl) {
            suggestionsEl.style.display = 'none';
        }
        this._syncTextToolsMenu();
    }
    
    _showGuidedChip() {
        const el = document.getElementById('guided-suggestions');
        if (!el || this.guidedStep >= this.guidedQuestions.length) {
            if (el) el.style.display = 'none';
            return;
        }
        el.style.display = 'block';
        const q = this.guidedQuestions[this.guidedStep];
        el.innerHTML = `<span class="guided-chip" id="guided-chip">💡 ${q}</span>`;
        document.getElementById('guided-chip')?.addEventListener('click', () => {
            if (this.textInput) { this.textInput.value = ''; }
            this.textInput.focus();
            this.textInput.setAttribute('placeholder', q);
        });
    }
    
    _advanceGuidedStep() {
        this.guidedStep++;
        this._showGuidedChip();
    }
    
    // ===== Feature 8: Language Auto-Detection =====
    _detectLanguage(text) {
        const nonAscii = (text.match(/[^\x00-\x7F]/g) || []).length;
        if (nonAscii > text.length * 0.3) return 'auto';
        if (/\b(el|la|los|las|que|de|en|por|con|una|como)\b/i.test(text)) return 'es';
        if (/\b(le|la|les|des|une|que|dans|pour|avec)\b/i.test(text)) return 'fr';
        return 'en';
    }
    
    _showLangDetectBadge(lang) {
        const names = { es: '🇪🇸 Spanish', fr: '🇫🇷 French', auto: '🌐 Auto' };
        const header = document.querySelector('.header-left');
        if (!header || document.getElementById('lang-detect-badge')) return;
        const badge = document.createElement('span');
        badge.id = 'lang-detect-badge';
        badge.className = 'lang-detect-badge';
        badge.textContent = names[lang] || `🌐 ${lang.toUpperCase()}`;
        header.appendChild(badge);
    }
    
    // ===== Feature 9: Child-Friendly Mode =====
    toggleChildMode() {
        this.childMode = !this.childMode;
        document.body.classList.toggle('child-mode', this.childMode);
        const btn = document.getElementById('child-mode-btn');
        if (btn) btn.classList.toggle('active', this.childMode);
        if (this.childMode) {
            this.displayMessage("Hi there! 👋 I'm here to help. Can you tell me what happened? Take your time, there's no rush. 😊", 'agent');
        }
        this._syncTextToolsMenu();
    }
    
    // ===== Feature 10: Enhanced Accessibility =====
    toggleHighContrast() {
        document.body.classList.toggle('high-contrast');
        const btn = document.getElementById('high-contrast-btn');
        if (btn) btn.classList.toggle('active', document.body.classList.contains('high-contrast'));
        this._syncTextToolsMenu();
    }
    
    _initKeyboardAccessibility() {
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'm') {
                e.preventDefault();
                this.isRecording ? this.stopRecording() : this.startRecording();
            }
        });
    }
}

// ==================== GLOBAL FUNCTIONS (Items 24-30) ====================

// Item 24: Toggle scene preview panel collapse
function toggleScenePreview() {
    const panel = document.getElementById('scene-preview-panel');
    if (panel) panel.classList.toggle('collapsed');
}

// Environmental Conditions Panel toggle
function toggleConditionsPanel() {
    const content = document.getElementById('conditions-content');
    const btn = document.querySelector('.conditions-toggle-btn');
    if (content) {
        content.classList.toggle('collapsed');
        if (btn) {
            btn.textContent = content.classList.contains('collapsed') ? '▶' : '▼';
        }
    }
}

// Update environmental conditions from selectors
async function updateEnvironmentalConditions() {
    const weatherSelect = document.getElementById('weather-select');
    const lightingSelect = document.getElementById('lighting-select');
    const visibilitySelect = document.getElementById('visibility-select');
    const previewIcons = document.getElementById('preview-icons');
    const sceneDisplay = document.getElementById('scene-display');

    if (!weatherSelect || !lightingSelect || !visibilitySelect) return;

    const weather = weatherSelect.value;
    const lighting = lightingSelect.value;
    const visibility = visibilitySelect.value;

    // Update preview icons
    const weatherIcons = { clear: '☀️', rain: '🌧️', snow: '❄️', fog: '🌫️' };
    const lightingIcons = { daylight: '🌞', dusk: '🌅', night: '🌙', artificial: '💡' };
    const visibilityIcons = { good: '✅', moderate: '⚠️', poor: '❌' };

    if (previewIcons) {
        previewIcons.textContent = `${weatherIcons[weather] || '☀️'} ${lightingIcons[lighting] || '🌞'} ${visibilityIcons[visibility] || '✅'}`;
    }

    // Apply visual effects to scene display
    if (sceneDisplay) {
        // Remove all weather/lighting/visibility classes
        sceneDisplay.classList.remove(
            'weather-clear', 'weather-rain', 'weather-snow', 'weather-fog',
            'lighting-daylight', 'lighting-dusk', 'lighting-night', 'lighting-artificial',
            'visibility-good', 'visibility-moderate', 'visibility-poor'
        );

        // Add current classes
        sceneDisplay.classList.add(`weather-${weather}`);
        sceneDisplay.classList.add(`lighting-${lighting}`);
        sceneDisplay.classList.add(`visibility-${visibility}`);
    }

    // Save to backend if we have an active session
    if (window.app && window.app.sessionId && window.app.currentVersion > 0) {
        try {
            const response = await fetch(
                `/api/sessions/${window.app.sessionId}/scene-versions/${window.app.currentVersion}/environmental-conditions`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ weather, lighting, visibility })
                }
            );
            if (response.ok) {
                console.debug('[Environmental] Conditions saved:', { weather, lighting, visibility });
            }
        } catch (error) {
            console.warn('[Environmental] Failed to save conditions:', error);
        }
    }
}

// Load environmental conditions for current scene version
async function loadEnvironmentalConditions(sessionId, versionNum) {
    if (!sessionId || !versionNum) return;

    try {
        const response = await fetch(
            `/api/sessions/${sessionId}/scene-versions/${versionNum}/environmental-conditions`
        );
        if (response.ok) {
            const data = await response.json();
            const conditions = data.environmental_conditions || {};

            // Update selectors
            const weatherSelect = document.getElementById('weather-select');
            const lightingSelect = document.getElementById('lighting-select');
            const visibilitySelect = document.getElementById('visibility-select');

            if (weatherSelect) weatherSelect.value = conditions.weather || 'clear';
            if (lightingSelect) lightingSelect.value = conditions.lighting || 'daylight';
            if (visibilitySelect) visibilitySelect.value = conditions.visibility || 'good';

            // Apply visual effects
            updateEnvironmentalConditions();
        }
    } catch (error) {
        console.warn('[Environmental] Failed to load conditions:', error);
    }
}

// Item 26: Show testimony summary modal
function showTestimonySummary() {
    const modal = document.getElementById('testimony-summary-modal');
    if (!modal) return;

    // Collect user statements from chat
    const messages = document.querySelectorAll('#chat-transcript .message-user');
    const statementsEl = document.getElementById('summary-statements');
    if (statementsEl) {
        if (messages.length === 0) {
            statementsEl.innerHTML = '<p class="empty-state">No statements recorded yet.</p>';
        } else {
            let html = '';
            messages.forEach(msg => {
                const textContent = msg.textContent.replace(/^👤You\d{1,2}:\d{2}\s*(AM|PM)?/i, '').trim();
                if (textContent) {
                    html += `<div class="summary-statement">${textContent}</div>`;
                }
            });
            statementsEl.innerHTML = html || '<p class="empty-state">No statements recorded yet.</p>';
        }
    }

    // Collect evidence elements from evidence board
    const elementsEl = document.getElementById('summary-elements');
    if (elementsEl) {
        const cards = document.querySelectorAll('#evidence-cards .evidence-card');
        if (cards.length === 0) {
            elementsEl.innerHTML = '<p class="empty-state">No key details extracted yet.</p>';
        } else {
            let html = '';
            cards.forEach(card => {
                const desc = card.querySelector('.ev-desc');
                const type = card.querySelector('.ev-type');
                if (desc) {
                    html += `<span class="summary-element-tag">${type ? type.textContent + ': ' : ''}${desc.textContent}</span>`;
                }
            });
            elementsEl.innerHTML = html;
        }
    }

    modal.style.display = 'flex';
    modal.classList.remove('hidden');
    modal.classList.add('active');
}

function closeSummary() {
    const modal = document.getElementById('testimony-summary-modal');
    if (modal) {
        modal.classList.remove('active');
        modal.classList.add('hidden');
        setTimeout(() => { modal.style.display = 'none'; }, 300);
    }
}

function submitTestimony() {
    // Gather witness info
    const witnessInfo = {
        name: document.getElementById('witness-name')?.value || '',
        contact: document.getElementById('witness-contact')?.value || '',
        location: document.getElementById('witness-location')?.value || ''
    };

    // Send submit via WebSocket if connected
    if (window.app && window.app.ws && window.app.ws.readyState === WebSocket.OPEN) {
        window.app.ws.send(JSON.stringify({
            type: 'submit_testimony',
            data: { witness_info: witnessInfo }
        }));
    }

    closeSummary();
    if (window.app && window.app.ui) {
        window.app.ui.showToast('✅ Testimony submitted successfully', 'success', 3000);
    }
}

// Item 27: Witness info form
async function startInterview() {
    document.getElementById('witness-info-overlay').style.display = 'none';
    localStorage.setItem('witnessreplay-witness-info-shown', 'true');
    
    // Gather witness info from form
    const isAnonymous = !!document.getElementById('witness-anonymous-toggle')?.checked;
    const witnessName = isAnonymous ? '' : (document.getElementById('witness-name')?.value?.trim() || '');
    const witnessContact = isAnonymous ? '' : (document.getElementById('witness-contact')?.value?.trim() || '');
    const witnessLocation = document.getElementById('witness-location')?.value?.trim() || '';
    
    // Save to localStorage for pre-fill on next visit
    if (witnessName) {
        localStorage.setItem('witnessreplay-witness-name', witnessName);
    } else {
        localStorage.removeItem('witnessreplay-witness-name');
    }
    if (witnessContact) {
        localStorage.setItem('witnessreplay-witness-contact', witnessContact);
    } else {
        localStorage.removeItem('witnessreplay-witness-contact');
    }
    localStorage.setItem('witnessreplay-witness-location', witnessLocation);
    
    // Save witness info to backend database
    if (window.app?.sessionId && (witnessName || witnessContact || witnessLocation)) {
        try {
            const response = await (window.app.fetchWithTimeout || fetch).call(
                window.app,
                `/api/sessions/${window.app.sessionId}/witnesses`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: witnessName || 'Anonymous Witness',
                        contact: witnessContact || null,
                        location: witnessLocation || null
                    })
                }
            );
            if (!response.ok) {
                console.warn('Failed to save witness info:', response.status);
            }
        } catch (e) {
            console.warn('Failed to save witness info to backend:', e);
        }
    }
    
    // Save location data to session if available
    if (window.locationManager && window.app?.sessionId) {
        const locationData = locationManager.getLocationData();
        if (locationData.address || locationData.coordinates) {
            try {
                await locationManager.saveToSession(window.app.sessionId);
            } catch (e) {
                console.warn('Failed to save location:', e);
            }
        }
    }
}

function skipInfo() {
    document.getElementById('witness-info-overlay').style.display = 'none';
    localStorage.setItem('witnessreplay-witness-info-shown', 'true');
}

// Item 28: Theme toggle
function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme') || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', newTheme);
    localStorage.setItem('witnessreplay-theme', newTheme);

    const icon = document.querySelector('#theme-toggle .theme-icon');
    if (icon) icon.textContent = newTheme === 'dark' ? '🌙' : '☀️';
}

// Apply saved theme on load
(function() {
    const saved = localStorage.getItem('witnessreplay-theme');
    if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
        const icon = document.querySelector('#theme-toggle .theme-icon');
        if (icon) icon.textContent = saved === 'dark' ? '🌙' : '☀️';
    }
})();

// Item 29: Evidence upload trigger
function uploadEvidence() {
    document.getElementById('evidence-file-input')?.click();
}

function handleEvidenceUpload(event) {
    if (window.app) window.app.handleEvidenceUpload(event);
}

// Item 30: Sketch upload trigger
function uploadSketch() {
    document.getElementById('sketch-file-input')?.click();
}

function handleSketchUpload(event) {
    if (window.app) window.app.handleSketchUpload(event);
}

function openSketchModal(sketchId) {
    // Open modal to view full sketch with AI interpretation
    if (window.app && window.app.sessionId) {
        window.app.fetchWithTimeout(`/api/sessions/${window.app.sessionId}/sketches/${sketchId}`)
            .then(response => response.json())
            .then(sketch => {
                // Create modal
                const modal = document.createElement('div');
                modal.className = 'modal active';
                modal.id = 'sketch-modal';
                modal.style.cssText = 'display:flex; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.8); z-index:10000; align-items:center; justify-content:center;';
                
                let elementsHtml = '';
                if (sketch.extracted_elements && sketch.extracted_elements.length > 0) {
                    elementsHtml = '<div class="sketch-elements"><h4>Extracted Elements:</h4><ul>' +
                        sketch.extracted_elements.map(e => `<li><strong>${e.type}:</strong> ${e.description} (${e.position})</li>`).join('') +
                        '</ul></div>';
                }
                
                modal.innerHTML = `
                    <div class="modal-content" style="background:var(--bg-secondary); border-radius:16px; max-width:800px; max-height:90vh; overflow:auto; padding:24px;">
                        <div class="modal-header" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                            <h3 style="margin:0;">✏️ Witness Sketch</h3>
                            <button onclick="this.closest('.modal').remove()" style="background:none; border:none; font-size:24px; cursor:pointer; color:var(--text-primary);">×</button>
                        </div>
                        <div class="modal-body">
                            <img src="${sketch.image_url}" alt="Witness sketch" style="max-width:100%; border-radius:8px; border:2px solid var(--accent-primary);">
                            ${sketch.description ? `<p style="margin-top:16px;"><strong>Description:</strong> ${sketch.description}</p>` : ''}
                            ${sketch.ai_interpretation ? `<div style="margin-top:16px; padding:12px; background:var(--bg-tertiary); border-radius:8px;"><strong>🤖 AI Interpretation:</strong><br>${sketch.ai_interpretation}</div>` : ''}
                            ${elementsHtml}
                        </div>
                    </div>
                `;
                
                modal.addEventListener('click', (e) => {
                    if (e.target === modal) modal.remove();
                });
                
                document.body.appendChild(modal);
            })
            .catch(err => console.error('Failed to load sketch:', err));
    }
}

// ── Feature 46: Onboarding Tour ─────────────────────────────
WitnessReplayApp.prototype._showOnboardingTour = function() {
    if (localStorage.getItem('wr_tour_done')) return;
    const steps = [
        { target: '.mic-main-btn', text: '🎤 Tap the microphone to start recording your witness statement' },
        { target: '.chat-input', text: '⌨️ Or type your description here' },
        { target: '#scene-canvas-container', text: '🎬 Watch your scene come to life as you describe it' },
    ];

    const overlay = document.createElement('div');
    overlay.id = 'tour-overlay';
    overlay.className = 'tour-overlay';
    let step = 0;

    const showStep = () => {
        if (step >= steps.length) {
            overlay.remove();
            localStorage.setItem('wr_tour_done', 'true');
            return;
        }
        const s = steps[step];
        const el = document.querySelector(s.target);
        overlay.innerHTML = `
            <div class="tour-backdrop"></div>
            <div class="tour-tooltip" style="${el ? `top: ${el.getBoundingClientRect().bottom + 10}px; left: ${Math.max(10, el.getBoundingClientRect().left)}px;` : 'top:50%;left:50%;transform:translate(-50%,-50%);'}">
                <div class="tour-text">${s.text}</div>
                <div class="tour-nav">
                    <span class="tour-progress">${step + 1}/${steps.length}</span>
                    <button class="tour-next-btn" onclick="document.getElementById('tour-overlay')._next()">
                        ${step < steps.length - 1 ? 'Next →' : 'Got it! ✓'}
                    </button>
                </div>
            </div>
        `;
        overlay._next = () => { step++; showStep(); };
    };

    document.body.appendChild(overlay);
    showStep();
};

// ── Feature 47: Witness Feedback Form ────────────────────────
WitnessReplayApp.prototype._showFeedbackPrompt = function(sessionId) {
    const modal = document.createElement('div');
    modal.className = 'feedback-modal-overlay';
    modal.innerHTML = `
        <div class="feedback-modal">
            <h3>📝 How was your experience?</h3>
            <div class="feedback-stars" id="feedback-stars">
                ${[1,2,3,4,5].map(i => `<span class="star" data-rating="${i}" onclick="document.querySelector('.feedback-modal')._setRating(${i})">⭐</span>`).join('')}
            </div>
            <p id="feedback-rating-text" style="color:var(--text-secondary);font-size:0.85rem;">Tap to rate</p>
            <div class="feedback-q">
                <label>How easy was it to use? (1-5)</label>
                <input type="range" id="feedback-ease" min="1" max="5" value="3">
            </div>
            <div class="feedback-q">
                <label>Did you feel heard? (1-5)</label>
                <input type="range" id="feedback-heard" min="1" max="5" value="3">
            </div>
            <textarea id="feedback-comments" placeholder="Any additional comments..." rows="2" style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:8px;color:var(--text-primary);padding:8px;resize:none;"></textarea>
            <div style="display:flex;gap:8px;margin-top:12px;">
                <button class="btn-primary" onclick="document.querySelector('.feedback-modal-overlay')._submit()">Submit</button>
                <button class="btn-secondary" onclick="document.querySelector('.feedback-modal-overlay').remove()">Skip</button>
            </div>
        </div>
    `;
    let rating = 0;
    modal.querySelector('.feedback-modal')._setRating = (r) => {
        rating = r;
        const ratingText = document.getElementById('feedback-rating-text');
        if (ratingText) ratingText.textContent = ['', 'Poor', 'Fair', 'Good', 'Very Good', 'Excellent'][r];
    };
    modal._submit = async () => {
        try {
            await fetch(`/sessions/${sessionId}/feedback`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    rating,
                    ease_of_use: parseInt(document.getElementById('feedback-ease')?.value || 3),
                    felt_heard: parseInt(document.getElementById('feedback-heard')?.value || 3),
                    comments: document.getElementById('feedback-comments')?.value || ''
                })
            });
        } catch(e) { console.error(e); }
        modal.remove();
    };
    document.body.appendChild(modal);
};

// ── Feature 48: AI Confidence Visualization ──────────────────
WitnessReplayApp.prototype._renderConfidenceBar = function(confidence) {
    if (!confidence && confidence !== 0) return '';
    const pct = Math.round(confidence * 100);
    const color = pct > 80 ? '#22c55e' : pct > 50 ? '#eab308' : '#ef4444';
    const label = pct > 80 ? 'High' : pct > 50 ? 'Medium' : 'Low';
    return `<div class="confidence-bar" title="AI Confidence: ${pct}%"><div class="confidence-fill" style="width:${pct}%;background:${color}"></div><span class="confidence-label">${label} (${pct}%)</span></div>`;
};

// ── Feature 49: Quick Action Command Palette ─────────────────
WitnessReplayApp.prototype._initCommandPalette = function() {
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            this._toggleCommandPalette();
        }
    });
};

WitnessReplayApp.prototype._toggleCommandPalette = function() {
    let palette = document.getElementById('command-palette');
    if (palette) { palette.remove(); return; }

    const actions = [
        { icon: '🎤', label: 'Start Recording', action: () => this.toggleRecording?.() },
        { icon: '📝', label: 'New Report', action: () => this.createNewSession?.() },
        { icon: '🌙', label: 'Toggle Dark Mode', action: () => document.body.classList.toggle('light-mode') },
        { icon: '📊', label: 'Open Admin', action: () => window.location.href = '/admin' },
        { icon: '❓', label: 'Help & Tutorial', action: () => this._showOnboardingTour?.() },
        { icon: '🎯', label: 'Toggle Focus Mode', action: () => this._toggleFocusMode?.() },
        { icon: '📥', label: 'Export Transcript', action: () => this._exportChatTranscript?.() },
        { icon: '📝', label: 'Session Notes', action: () => this._toggleSessionNotes?.() },
    ];

    palette = document.createElement('div');
    palette.id = 'command-palette';
    palette.className = 'command-palette';
    palette.innerHTML = `
        <input type="text" class="cmd-input" placeholder="Type a command..." autofocus oninput="this.parentElement._filter(this.value)">
        <div class="cmd-list" id="cmd-list">
            ${actions.map((a, i) => `<div class="cmd-item" data-idx="${i}" onclick="document.getElementById('command-palette')._run(${i})">${a.icon} ${a.label}</div>`).join('')}
        </div>
    `;
    palette._filter = (q) => {
        const items = palette.querySelectorAll('.cmd-item');
        items.forEach(item => { item.style.display = item.textContent.toLowerCase().includes(q.toLowerCase()) ? '' : 'none'; });
    };
    palette._run = (idx) => { actions[idx]?.action(); palette.remove(); };
    palette.addEventListener('click', (e) => { if (e.target === palette) palette.remove(); });
    document.body.appendChild(palette);
    palette.querySelector('.cmd-input').focus();
};

// ── Auto-save interview progress ─────────────────────────────
WitnessReplayApp.prototype._initAutoSave = function() {
    this._autoSaveInterval = setInterval(() => this._autoSave(), 30000);
};

WitnessReplayApp.prototype._autoSave = function() {
    if (!this.sessionId) return;
    const messages = document.getElementById('chat-messages');
    if (!messages) return;
    const saveData = {
        sessionId: this.sessionId,
        timestamp: Date.now(),
        messageCount: messages.children.length,
        recentMessages: Array.from(messages.querySelectorAll('.message')).slice(-20).map(m => ({
            role: m.classList.contains('user') ? 'user' : 'assistant',
            text: m.querySelector('.message-text')?.textContent?.substring(0, 500) || ''
        }))
    };
    try {
        localStorage.setItem('wr_autosave', JSON.stringify(saveData));
    } catch(e) { /* localStorage full */ }
};

WitnessReplayApp.prototype._checkAutoSave = function() {
    try {
        const saved = JSON.parse(localStorage.getItem('wr_autosave'));
        if (saved && Date.now() - saved.timestamp < 3600000) {
            return saved;
        }
    } catch(e) {}
    return null;
};

WitnessReplayApp.prototype._clearAutoSave = function() {
    localStorage.removeItem('wr_autosave');
};

// Orphaned class methods wrapped as standalone functions
async function uploadReferencePhoto(file) {
    if (!window.app) return;
    const reader = new FileReader();
    reader.onload = async (e) => {
        const base64 = e.target.result.split(',')[1];
        try {
            await fetch(`/api/sessions/${window.app.sessionId}/photo-overlay`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({photo: base64})
            });
            window.app.ui?.showToast('📸 Reference photo uploaded', 'success', 3000);
        } catch(err) { console.error('Photo overlay error:', err); }
    };
    reader.readAsDataURL(file);
}

function renderEvidenceHeatmap(elements) {
        const canvas = document.createElement('canvas');
        canvas.id = 'evidence-heatmap';
        canvas.width = 400; canvas.height = 300;
        canvas.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;opacity:0.5;pointer-events:none;z-index:3;';
        const ctx = canvas.getContext('2d');
        (elements || []).forEach(el => {
            const x = (el.x || Math.random()) * 400;
            const y = (el.y || Math.random()) * 300;
            const gradient = ctx.createRadialGradient(x, y, 0, x, y, 60);
            gradient.addColorStop(0, 'rgba(239,68,68,0.6)');
            gradient.addColorStop(1, 'rgba(239,68,68,0)');
            ctx.fillStyle = gradient;
            ctx.fillRect(x-60, y-60, 120, 120);
        });
        const container = document.getElementById('scene-editor-canvas');
        if (container) { container.style.position = 'relative'; container.appendChild(canvas); }
}

// App is initialized from index.html inline script.
// Do NOT add a second instantiation here to avoid duplicate toasts/notifications.

function toggleAerialView() {
    const container = document.getElementById('scene-editor-canvas') || document.getElementById('scene-preview');
    if (!container) return;
    const existing = document.getElementById('aerial-diagram');
    if (existing) { existing.remove(); return; }
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.id = 'aerial-diagram';
    svg.setAttribute('viewBox', '0 0 400 300');
    svg.style.cssText = 'width:100%;height:100%;position:absolute;top:0;left:0;background:rgba(0,0,0,0.8);z-index:5;';
    for (let i = 0; i <= 400; i += 40) {
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', i); line.setAttribute('y1', 0); line.setAttribute('x2', i); line.setAttribute('y2', 300);
        line.setAttribute('stroke', 'rgba(96,165,250,0.15)'); line.setAttribute('stroke-width', '0.5');
        svg.appendChild(line);
    }
    for (let i = 0; i <= 300; i += 40) {
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', 0); line.setAttribute('y1', i); line.setAttribute('x2', 400); line.setAttribute('y2', i);
        line.setAttribute('stroke', 'rgba(96,165,250,0.15)'); line.setAttribute('stroke-width', '0.5');
        svg.appendChild(line);
    }
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', 200); text.setAttribute('y', 20); text.setAttribute('text-anchor', 'middle');
    text.setAttribute('fill', '#60a5fa'); text.setAttribute('font-size', '12');
    text.textContent = 'Aerial View — Scene elements will appear here';
    svg.appendChild(text);
    container.style.position = 'relative';
    container.appendChild(svg);
}

// ── Slash Commands — Quick actions from chat input ─────────────────
WitnessReplayApp.prototype._handleSlashCommand = function(text) {
    const cmd = text.split(/\s+/)[0].toLowerCase();
    const arg = text.slice(cmd.length).trim();
    
    const commands = {
        '/help': () => {
            this.displaySystemMessage(
                '📋 <b>Available Commands</b><br>' +
                '<code>/summary</code> — Get a summary of the current interview<br>' +
                '<code>/timeline</code> — Show event timeline<br>' +
                '<code>/export</code> — Export chat transcript<br>' +
                '<code>/scene</code> — Generate a scene reconstruction<br>' +
                '<code>/new</code> — Start a new report<br>' +
                '<code>/clear</code> — Clear chat display<br>' +
                '<code>/status</code> — Show connection status<br>' +
                '<code>/shortcuts</code> — Show keyboard shortcuts<br>' +
                '<code>/focus</code> — Toggle focus mode<br>' +
                '<code>/notes</code> — Open session notes<br>' +
                '<code>/search</code> — Search chat messages<br>' +
                '<code>/pins</code> — View pinned messages<br>' +
                '<code>/stats</code> — Interview word stats<br>' +
                '<code>/evidence</code> — Extract evidence items<br>' +
                '<code>/undo</code> — Remove last message<br>' +
                '<code>/quality</code> — Interview quality score<br>' +
                '<code>/sentiment</code> — Witness sentiment timeline<br>' +
                '<code>/tag [name]</code> — Add/view session tags<br>' +
                '<code>/report</code> — Generate investigation report<br>' +
                '<code>/credibility</code> — Witness credibility score<br>' +
                '<code>/timeline</code> — Extract event timeline<br>' +
                '<code>/wordcloud</code> — Word frequency cloud<br>' +
                '<code>/compare [id]</code> — Compare with another session<br>' +
                '<code>/autosummary</code> — Quick auto-summary<br>' +
                '<code>/bookmark [note]</code> — Bookmark current statement<br>' +
                '<code>/bookmarks</code> — View all bookmarks<br>' +
                '<code>/contradictions</code> — Detect inconsistencies<br>' +
                '<code>/markdown</code> — Export as markdown<br>' +
                '<code>/evidence-links</code> — Find evidence references<br>' +
                '<code>/diff [a b]</code> — Compare two statements<br>' +
                '<code>/completeness</code> — Interview coverage check<br>' +
                '<code>/help</code> — Show this help'
            );
        },
        '/summary': () => {
            if (this.ws?.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'text', data: { text: 'Please provide a concise summary of everything discussed so far.' } }));
                this.displayMessage('/summary', 'user');
                this.setStatus('Generating summary...');
                this._setConversationState('thinking');
                setTimeout(() => this._showContextualFollowUps?.('summary'), 500);
            } else {
                this.displaySystemMessage('⚠️ Not connected. Please wait for connection.');
            }
        },
        '/timeline': () => {
            if (this.ws?.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'text', data: { text: 'Please reconstruct a detailed timeline of events based on everything described so far.' } }));
                this.displayMessage('/timeline', 'user');
                this.setStatus('Building timeline...');
                this._setConversationState('thinking');
                setTimeout(() => this._showContextualFollowUps?.('timeline'), 500);
            } else {
                this.displaySystemMessage('⚠️ Not connected. Please wait for connection.');
            }
        },
        '/scene': () => {
            if (this.ws?.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'text', data: { text: 'Generate a detailed scene reconstruction image based on everything described.' } }));
                this.displayMessage('/scene', 'user');
                this.setStatus('Generating scene...');
                this._setConversationState('thinking');
            } else {
                this.displaySystemMessage('⚠️ Not connected. Please wait for connection.');
            }
        },
        '/new': () => {
            this.createNewSession();
        },
        '/clear': () => {
            const transcript = document.getElementById('chat-transcript');
            if (transcript) {
                const empty = transcript.querySelector('.empty-state');
                transcript.innerHTML = '';
                if (empty) transcript.appendChild(empty);
            }
            this.displaySystemMessage('🧹 Chat display cleared. Session data is preserved.');
        },
        '/status': () => {
            const wsState = this.ws ? ['CONNECTING','OPEN','CLOSING','CLOSED'][this.ws.readyState] : 'NONE';
            this.displaySystemMessage(
                `🔗 <b>Connection Status</b><br>` +
                `WebSocket: ${wsState}<br>` +
                `Session: ${this.sessionId || 'none'}<br>` +
                `Messages: ${this.statementCount || 0}`
            );
        },
        '/shortcuts': () => {
            this._showKeyboardShortcutsHelp();
        },
        '/focus': () => {
            this._toggleFocusMode();
        },
        '/notes': () => {
            this._toggleSessionNotes();
        },
        '/export': () => {
            this._exportChatTranscript();
        },
        '/search': () => {
            this._openChatSearch();
        },
        '/pins': () => {
            this._showPinnedMessages();
        },
        '/stats': () => {
            this._showInterviewWordStats();
        },
        '/evidence': () => {
            this._showEvidence();
        },
        '/undo': () => {
            this._undoLastMessage();
        },
        '/quality': () => {
            this._showQualityDetails();
        },
        '/sentiment': () => {
            this._showSentimentTimeline();
        },
        '/tag': () => {
            const rest = text.slice(4).trim();
            this._handleTagCommand(rest);
        },
        '/report': () => {
            this._generateReport();
        },
        '/credibility': () => {
            this._showCredibilityScore();
        },
        '/wordcloud': () => {
            this._showWordCloud();
        },
        '/compare': () => {
            const rest = text.slice(8).trim();
            this._compareSession(rest);
        },
        '/autosummary': () => {
            this._showAutoSummary();
        },
        '/events': () => {
            this._showExtractedTimeline();
        },
        '/bookmark': () => {
            const note = text.slice(9).trim();
            this._addBookmark(note);
        },
        '/bookmarks': () => {
            this._showBookmarks();
        },
        '/contradictions': () => {
            this._detectContradictions();
        },
        '/markdown': () => {
            this._exportMarkdown();
        },
        '/evidence-links': () => {
            this._showEvidenceLinks();
        },
        '/diff': () => {
            const darg = text.slice(5).trim();
            this._showStatementDiff(darg);
        },
        '/completeness': () => {
            this._checkCompleteness();
        }
    };
    
    const handler = commands[cmd];
    if (handler) {
        handler();
    } else {
        this.displaySystemMessage(`❓ Unknown command: <code>${cmd}</code>. Type <code>/help</code> for available commands.`);
    }
    this.textInput.value = '';
    this._updateCharCounter();
};

// ── Keyboard Shortcuts Help Panel ─────────────────
WitnessReplayApp.prototype._showKeyboardShortcutsHelp = function() {
    let overlay = document.getElementById('shortcuts-overlay');
    if (overlay) { overlay.remove(); return; }
    
    overlay = document.createElement('div');
    overlay.id = 'shortcuts-overlay';
    overlay.className = 'shortcuts-overlay';
    overlay.innerHTML = `
        <div class="shortcuts-panel">
            <div class="shortcuts-header">
                <h3>⌨️ Keyboard Shortcuts</h3>
                <button class="shortcuts-close" aria-label="Close">&times;</button>
            </div>
            <div class="shortcuts-grid">
                <div class="shortcut-group">
                    <h4>General</h4>
                    <div class="shortcut-row"><kbd>Ctrl</kbd>+<kbd>K</kbd> <span>Command palette</span></div>
                    <div class="shortcut-row"><kbd>?</kbd> <span>This help panel</span></div>
                    <div class="shortcut-row"><kbd>Esc</kbd> <span>Close dialogs</span></div>
                    <div class="shortcut-row"><kbd>Enter</kbd> <span>Send message</span></div>
                </div>
                <div class="shortcut-group">
                    <h4>Chat Commands</h4>
                    <div class="shortcut-row"><kbd>/help</kbd> <span>Show all commands</span></div>
                    <div class="shortcut-row"><kbd>/summary</kbd> <span>Get interview summary</span></div>
                    <div class="shortcut-row"><kbd>/timeline</kbd> <span>Reconstruct timeline</span></div>
                    <div class="shortcut-row"><kbd>/scene</kbd> <span>Generate scene image</span></div>
                    <div class="shortcut-row"><kbd>/export</kbd> <span>Export session</span></div>
                    <div class="shortcut-row"><kbd>/new</kbd> <span>New report</span></div>
                    <div class="shortcut-row"><kbd>/status</kbd> <span>Connection info</span></div>
                </div>
            </div>
        </div>
    `;
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay || e.target.classList.contains('shortcuts-close')) overlay.remove();
    });
    document.body.appendChild(overlay);
};

// ── Slash Command Autocomplete Hint ─────────────────
WitnessReplayApp.prototype._showSlashHint = function() {
    const existing = document.getElementById('slash-hint');
    if (existing) existing.remove();
    
    const val = this.textInput.value;
    if (!val.startsWith('/') || val.includes(' ')) return;
    
    const cmds = [
        { cmd: '/help', desc: 'Show all commands' },
        { cmd: '/summary', desc: 'Interview summary' },
        { cmd: '/timeline', desc: 'Reconstruct timeline' },
        { cmd: '/scene', desc: 'Generate scene image' },
        { cmd: '/export', desc: 'Export transcript' },
        { cmd: '/new', desc: 'New report' },
        { cmd: '/clear', desc: 'Clear chat display' },
        { cmd: '/status', desc: 'Connection info' },
        { cmd: '/shortcuts', desc: 'Keyboard shortcuts' },
        { cmd: '/focus', desc: 'Toggle focus mode' },
        { cmd: '/notes', desc: 'Session notes' },
        { cmd: '/search', desc: 'Search chat messages' },
        { cmd: '/pins', desc: 'View pinned messages' },
        { cmd: '/stats', desc: 'Interview word stats' },
        { cmd: '/quality', desc: 'Quality score' },
        { cmd: '/sentiment', desc: 'Sentiment timeline' },
        { cmd: '/tag', desc: 'Session tags' },
        { cmd: '/report', desc: 'Investigation report' },
        { cmd: '/credibility', desc: 'Credibility score' },
        { cmd: '/wordcloud', desc: 'Word frequency cloud' },
        { cmd: '/compare', desc: 'Compare sessions' },
        { cmd: '/autosummary', desc: 'Quick auto-summary' },
        { cmd: '/events', desc: 'Extract timeline events' },
        { cmd: '/bookmark', desc: 'Bookmark statement' },
        { cmd: '/bookmarks', desc: 'View bookmarks' },
        { cmd: '/contradictions', desc: 'Detect inconsistencies' },
        { cmd: '/markdown', desc: 'Export as markdown' },
        { cmd: '/evidence-links', desc: 'Evidence references' },
        { cmd: '/diff', desc: 'Compare statements' },
        { cmd: '/completeness', desc: 'Coverage check' }
    ];
    
    const filter = val.toLowerCase();
    const matches = cmds.filter(c => c.cmd.startsWith(filter));
    if (!matches.length) return;
    
    const hint = document.createElement('div');
    hint.id = 'slash-hint';
    hint.className = 'slash-hint';
    matches.forEach((m, i) => {
        const item = document.createElement('div');
        item.className = 'slash-hint-item' + (i === 0 ? ' active' : '');
        item.innerHTML = `<span class="slash-hint-cmd">${m.cmd}</span><span class="slash-hint-desc">${m.desc}</span>`;
        item.addEventListener('click', () => {
            this.textInput.value = m.cmd;
            this.textInput.focus();
            hint.remove();
        });
        hint.appendChild(item);
    });
    
    // Position relative to text input area
    const inputBar = this.textInput.closest('.text-input-row') || this.textInput.parentElement;
    if (inputBar) {
        inputBar.style.position = 'relative';
        inputBar.appendChild(hint);
    }
    
    // Close when clicking outside
    const closeOnClick = (e) => {
        if (!hint.contains(e.target) && e.target !== this.textInput) {
            hint.remove();
            document.removeEventListener('click', closeOnClick);
        }
    };
    setTimeout(() => document.addEventListener('click', closeOnClick), 50);
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 1: Quick Reply Suggestion Chips
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._showQuickReplies = function(agentText) {
    // Remove existing quick replies
    const existing = document.querySelector('.quick-reply-container');
    if (existing) existing.remove();
    
    const suggestions = this._generateQuickReplies(agentText);
    if (!suggestions.length) return;
    
    const container = document.createElement('div');
    container.className = 'quick-reply-container';
    
    suggestions.forEach(s => {
        const chip = document.createElement('button');
        chip.className = 'quick-reply-chip';
        chip.innerHTML = `<span class="chip-icon">${s.icon}</span>${s.text}`;
        chip.addEventListener('click', () => {
            container.remove();
            if (this.textInput) {
                this.textInput.value = s.text;
                this.textInput.dispatchEvent(new Event('input'));
                this.textInput.focus();
                // Auto-send
                const sendBtn = document.getElementById('send-btn');
                if (sendBtn && !sendBtn.disabled) sendBtn.click();
            }
        });
        container.appendChild(chip);
    });
    
    this.chatTranscript.appendChild(container);
    this._scrollChatToBottom();
};

WitnessReplayApp.prototype._generateQuickReplies = function(text) {
    const lower = (text || '').toLowerCase();
    
    // Context-sensitive suggestions based on what the agent asked
    if (lower.includes('where') || lower.includes('location') || lower.includes('address')) {
        return [
            { icon: '📍', text: 'It was at an intersection' },
            { icon: '🏢', text: 'Near a building' },
            { icon: '🅿️', text: 'In a parking lot' }
        ];
    }
    if (lower.includes('when') || lower.includes('time') || lower.includes('what time')) {
        return [
            { icon: '🌅', text: 'It was in the morning' },
            { icon: '☀️', text: 'Around midday' },
            { icon: '🌙', text: 'Late at night' }
        ];
    }
    if (lower.includes('vehicle') || lower.includes('car') || lower.includes('drove')) {
        return [
            { icon: '🚗', text: 'It was a dark sedan' },
            { icon: '🚙', text: 'An SUV' },
            { icon: '🚐', text: 'A van or truck' }
        ];
    }
    if (lower.includes('person') || lower.includes('people') || lower.includes('describe') || lower.includes('individual')) {
        return [
            { icon: '👤', text: 'One person, average height' },
            { icon: '👥', text: 'There were multiple people' },
            { icon: '🧥', text: 'They were wearing dark clothing' }
        ];
    }
    if (lower.includes('weapon') || lower.includes('gun') || lower.includes('knife')) {
        return [
            { icon: '⚠️', text: 'I saw a weapon' },
            { icon: '❌', text: 'No weapons that I saw' },
            { icon: '🤔', text: "I'm not sure" }
        ];
    }
    if (lower.includes('accurate') || lower.includes('compare') || lower.includes('correct') || lower.includes('right')) {
        return [
            { icon: '✅', text: "Yes, that looks right" },
            { icon: '✏️', text: 'I need to correct something' },
            { icon: '➕', text: "There's more to add" }
        ];
    }
    if (lower.includes('anything else') || lower.includes('more to add') || lower.includes('missing')) {
        return [
            { icon: '💡', text: "I just remembered something" },
            { icon: '✅', text: "That's everything I remember" },
            { icon: '🎬', text: 'Can you generate a scene?' }
        ];
    }
    // Default suggestions
    return [
        { icon: '💬', text: 'Let me describe what I saw' },
        { icon: '🎬', text: 'Generate a scene' },
        { icon: '��', text: 'Summarize so far' }
    ];
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 2: Session Notes Panel
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initSessionNotes = function() {
    this._sessionNotes = JSON.parse(localStorage.getItem('wr_session_notes_' + (this.sessionId || 'default')) || '[]');
    
    // Create toggle button
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'session-notes-toggle';
    toggleBtn.id = 'session-notes-toggle';
    toggleBtn.innerHTML = '📝';
    toggleBtn.title = 'Session Notes';
    toggleBtn.setAttribute('aria-label', 'Toggle session notes');
    
    if (this._sessionNotes.length > 0) {
        const badge = document.createElement('span');
        badge.className = 'notes-badge';
        badge.textContent = this._sessionNotes.length;
        toggleBtn.appendChild(badge);
    }
    
    toggleBtn.addEventListener('click', () => this._toggleSessionNotes());
    document.body.appendChild(toggleBtn);
    
    // Create panel
    const panel = document.createElement('div');
    panel.className = 'session-notes-panel hidden';
    panel.id = 'session-notes-panel';
    panel.innerHTML = `
        <div class="session-notes-header">
            <h3>📝 Notes</h3>
            <button class="session-notes-close" id="session-notes-close">&times;</button>
        </div>
        <div class="session-notes-body" id="session-notes-body"></div>
        <div class="session-notes-input">
            <input type="text" id="session-note-input" placeholder="Add a private note..." maxlength="500">
            <button id="session-note-add-btn">Add</button>
        </div>
    `;
    document.body.appendChild(panel);
    
    document.getElementById('session-notes-close').addEventListener('click', () => this._toggleSessionNotes());
    document.getElementById('session-note-add-btn').addEventListener('click', () => this._addSessionNote());
    document.getElementById('session-note-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this._addSessionNote();
    });
    
    this._renderSessionNotes();
};

WitnessReplayApp.prototype._toggleSessionNotes = function() {
    const panel = document.getElementById('session-notes-panel');
    if (panel) panel.classList.toggle('hidden');
};

WitnessReplayApp.prototype._addSessionNote = function() {
    const input = document.getElementById('session-note-input');
    const text = (input?.value || '').trim();
    if (!text) return;
    
    const note = {
        id: Date.now(),
        text: text,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    this._sessionNotes.push(note);
    localStorage.setItem('wr_session_notes_' + (this.sessionId || 'default'), JSON.stringify(this._sessionNotes));
    input.value = '';
    this._renderSessionNotes();
    this._updateNotesBadge();
};

WitnessReplayApp.prototype._deleteSessionNote = function(noteId) {
    this._sessionNotes = this._sessionNotes.filter(n => n.id !== noteId);
    localStorage.setItem('wr_session_notes_' + (this.sessionId || 'default'), JSON.stringify(this._sessionNotes));
    this._renderSessionNotes();
    this._updateNotesBadge();
};

WitnessReplayApp.prototype._renderSessionNotes = function() {
    const body = document.getElementById('session-notes-body');
    if (!body) return;
    
    if (this._sessionNotes.length === 0) {
        body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:0.82rem;">No notes yet.<br>Add private notes during the interview.</div>';
        return;
    }
    
    body.innerHTML = this._sessionNotes.map(n => `
        <div class="session-note-item">
            ${this._escapeHtml(n.text)}
            <div class="note-time">${n.time}</div>
            <button class="note-delete" onclick="window.app?._deleteSessionNote(${n.id})" title="Delete note">&times;</button>
        </div>
    `).join('');
};

WitnessReplayApp.prototype._updateNotesBadge = function() {
    const toggle = document.getElementById('session-notes-toggle');
    if (!toggle) return;
    const existing = toggle.querySelector('.notes-badge');
    if (existing) existing.remove();
    if (this._sessionNotes.length > 0) {
        const badge = document.createElement('span');
        badge.className = 'notes-badge';
        badge.textContent = this._sessionNotes.length;
        toggle.appendChild(badge);
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 4: Interview Stats Badge in Header
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initInterviewStatsBadge = function() {
    const sessionInfo = document.querySelector('.session-info');
    if (!sessionInfo) return;
    
    const badge = document.createElement('div');
    badge.className = 'interview-stats-badge';
    badge.id = 'interview-stats-badge';
    badge.innerHTML = `
        <div class="stat-item"><span class="stat-icon">⏱️</span><span class="stat-val" id="stats-duration">0:00</span></div>
        <div class="stat-divider"></div>
        <div class="stat-item"><span class="stat-icon">💬</span><span class="stat-val" id="stats-statements">0</span></div>
        <div class="stat-divider"></div>
        <div class="stat-item"><span class="stat-icon">📊</span><span class="stat-val" id="stats-phase">Intro</span></div>
    `;
    
    // Insert before theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        sessionInfo.insertBefore(badge, themeToggle);
    } else {
        sessionInfo.appendChild(badge);
    }
};

WitnessReplayApp.prototype._updateInterviewStatsBadge = function() {
    const badge = document.getElementById('interview-stats-badge');
    if (!badge) return;
    
    const stmts = this.statementCount || 0;
    if (stmts === 0) return;
    
    badge.classList.add('visible');
    
    // Update duration
    const durEl = document.getElementById('stats-duration');
    if (durEl && this.sessionStartTime) {
        const elapsed = Math.floor((Date.now() - this.sessionStartTime) / 1000);
        const m = Math.floor(elapsed / 60);
        const s = elapsed % 60;
        durEl.textContent = `${m}:${String(s).padStart(2, '0')}`;
    }
    
    // Update statement count
    const stmtEl = document.getElementById('stats-statements');
    if (stmtEl) stmtEl.textContent = stmts;
    
    // Update phase
    const phaseEl = document.getElementById('stats-phase');
    if (phaseEl) {
        const totalMessages = this.chatTranscript ? this.chatTranscript.querySelectorAll('.message').length : 0;
        if (totalMessages <= 2) phaseEl.textContent = 'Intro';
        else if (totalMessages <= 6) phaseEl.textContent = 'Narrative';
        else if (totalMessages <= 14) phaseEl.textContent = 'Details';
        else phaseEl.textContent = 'Review';
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 5: Message Reactions (thumbs up/down)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._addMessageReactions = function(messageDiv, messageText) {
    const reactionsDiv = document.createElement('div');
    reactionsDiv.className = 'msg-reactions';
    
    const thumbsUp = document.createElement('button');
    thumbsUp.className = 'msg-reaction-btn';
    thumbsUp.innerHTML = '👍';
    thumbsUp.title = 'Helpful response';
    thumbsUp.addEventListener('click', () => {
        thumbsUp.classList.toggle('active');
        thumbsDown.classList.remove('active');
        this._sendReactionFeedback(messageText, thumbsUp.classList.contains('active') ? 'positive' : null);
    });
    
    const thumbsDown = document.createElement('button');
    thumbsDown.className = 'msg-reaction-btn';
    thumbsDown.innerHTML = '👎';
    thumbsDown.title = 'Not helpful';
    thumbsDown.addEventListener('click', () => {
        thumbsDown.classList.toggle('active');
        thumbsDown.classList.toggle('negative', thumbsDown.classList.contains('active'));
        thumbsUp.classList.remove('active');
        this._sendReactionFeedback(messageText, thumbsDown.classList.contains('active') ? 'negative' : null);
    });
    
    reactionsDiv.appendChild(thumbsUp);
    reactionsDiv.appendChild(thumbsDown);
    messageDiv.appendChild(reactionsDiv);
};

WitnessReplayApp.prototype._sendReactionFeedback = function(messageText, reaction) {
    if (!this.sessionId || !reaction) return;
    fetch(`/api/sessions/${this.sessionId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message_preview: (messageText || '').substring(0, 100),
            reaction: reaction,
            timestamp: new Date().toISOString()
        })
    }).catch(() => {});
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 6: Export Chat Transcript
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initExportChatBtn = function() {
    const btn = document.createElement('button');
    btn.className = 'export-chat-btn';
    btn.id = 'export-chat-btn';
    btn.innerHTML = '📥';
    btn.title = 'Export chat transcript';
    btn.setAttribute('aria-label', 'Export chat transcript');
    btn.addEventListener('click', () => this._exportChatTranscript());
    document.body.appendChild(btn);
};

WitnessReplayApp.prototype._exportChatTranscript = function() {
    const messages = this.chatTranscript?.querySelectorAll('.message');
    if (!messages || messages.length === 0) {
        this.ui?.showToast('No messages to export', 'warning', 2000);
        return;
    }
    
    let transcript = `WITNESSREPLAY — Interview Transcript\n`;
    transcript += `Session: ${this.sessionId || 'N/A'}\n`;
    transcript += `Exported: ${new Date().toLocaleString()}\n`;
    transcript += `${'═'.repeat(50)}\n\n`;
    
    messages.forEach(msg => {
        const isUser = msg.classList.contains('message-user');
        const isAgent = msg.classList.contains('message-agent');
        const isSystem = msg.classList.contains('message-system');
        
        let speaker = 'System';
        if (isUser) speaker = 'Witness';
        else if (isAgent) speaker = 'Detective Ray';
        
        // Get the text content, stripping UI elements
        const clone = msg.cloneNode(true);
        clone.querySelectorAll('.msg-reactions, .msg-reaction-btn, .quick-reply-container, .copy-btn, .msg-avatar, .emotion-badge').forEach(el => el.remove());
        const text = clone.textContent.replace(/\s+/g, ' ').trim();
        
        transcript += `[${speaker}] ${text}\n\n`;
    });
    
    transcript += `${'═'.repeat(50)}\n`;
    transcript += `Total messages: ${messages.length}\n`;
    transcript += `Statements: ${this.statementCount || 0}\n`;
    
    // Download as text file
    const blob = new Blob([transcript], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `witnessreplay-transcript-${this.sessionId || 'session'}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    this.ui?.showToast('📥 Transcript exported', 'success', 2000);
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 7: Focus Mode
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initFocusMode = function() {
    // Add focus mode indicator
    const sessionInfo = document.querySelector('.session-info');
    if (!sessionInfo) return;
    
    const indicator = document.createElement('div');
    indicator.className = 'focus-mode-indicator';
    indicator.id = 'focus-mode-indicator';
    indicator.innerHTML = '<span class="focus-dot"></span>Focus Mode';
    sessionInfo.insertBefore(indicator, sessionInfo.firstChild);
    
    this._focusModeActive = false;
};

WitnessReplayApp.prototype._toggleFocusMode = function() {
    this._focusModeActive = !this._focusModeActive;
    const indicator = document.getElementById('focus-mode-indicator');
    
    if (this._focusModeActive) {
        // Enter focus mode: hide distracting elements
        document.body.classList.add('focus-mode');
        if (indicator) indicator.classList.add('active');
        
        // Hide non-essential UI
        const hideElements = [
            '.challenge-badge', '.scene-panel', '.interview-comfort-panel',
            '.keyboard-hint', '#hamburger-menu-btn'
        ];
        hideElements.forEach(sel => {
            document.querySelectorAll(sel).forEach(el => el.style.display = 'none');
        });
        
        this.ui?.showToast('🎯 Focus Mode ON — distractions hidden', 'success', 2000);
    } else {
        document.body.classList.remove('focus-mode');
        if (indicator) indicator.classList.remove('active');
        
        // Restore elements
        const restoreElements = [
            '.challenge-badge', '.scene-panel', '.interview-comfort-panel',
            '.keyboard-hint', '#hamburger-menu-btn'
        ];
        restoreElements.forEach(sel => {
            document.querySelectorAll(sel).forEach(el => el.style.display = '');
        });
        
        this.ui?.showToast('Focus Mode OFF', 'info', 1500);
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 8: Chat Message Search Overlay
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initChatSearch = function() {
    // Ctrl+F override for chat search
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
            const transcript = document.getElementById('chat-transcript');
            if (transcript && transcript.querySelectorAll('.message').length > 0) {
                e.preventDefault();
                this._openChatSearch();
            }
        }
    });
};

WitnessReplayApp.prototype._openChatSearch = function() {
    let overlay = document.getElementById('chat-search-overlay');
    if (overlay) { overlay.querySelector('.chat-search-input')?.focus(); return; }
    
    overlay = document.createElement('div');
    overlay.id = 'chat-search-overlay';
    overlay.className = 'chat-search-overlay';
    overlay.innerHTML = `
        <div class="chat-search-bar">
            <span class="chat-search-icon">🔍</span>
            <input type="text" class="chat-search-input" placeholder="Search messages..." autofocus>
            <span class="chat-search-count" id="chat-search-count"></span>
            <button class="chat-search-nav" id="chat-search-prev" title="Previous">▲</button>
            <button class="chat-search-nav" id="chat-search-next" title="Next">▼</button>
            <button class="chat-search-close" title="Close">&times;</button>
        </div>
    `;
    
    const chatPanel = document.querySelector('.chat-panel') || document.body;
    chatPanel.appendChild(overlay);
    
    const input = overlay.querySelector('.chat-search-input');
    const countEl = overlay.querySelector('#chat-search-count');
    let matches = [];
    let currentIdx = -1;
    
    const clearHighlights = () => {
        document.querySelectorAll('.chat-search-highlight').forEach(el => {
            el.classList.remove('chat-search-highlight', 'chat-search-active');
        });
    };
    
    const doSearch = (query) => {
        clearHighlights();
        matches = [];
        currentIdx = -1;
        if (!query || query.length < 2) { countEl.textContent = ''; return; }
        
        const q = query.toLowerCase();
        const msgs = document.querySelectorAll('#chat-transcript .message');
        msgs.forEach(msg => {
            if (msg.textContent.toLowerCase().includes(q)) {
                msg.classList.add('chat-search-highlight');
                matches.push(msg);
            }
        });
        
        countEl.textContent = matches.length ? `${matches.length} found` : 'No results';
        if (matches.length) { currentIdx = 0; goTo(0); }
    };
    
    const goTo = (idx) => {
        matches.forEach(m => m.classList.remove('chat-search-active'));
        if (idx >= 0 && idx < matches.length) {
            currentIdx = idx;
            matches[idx].classList.add('chat-search-active');
            matches[idx].scrollIntoView({ behavior: 'smooth', block: 'center' });
            countEl.textContent = `${idx + 1} / ${matches.length}`;
        }
    };
    
    input.addEventListener('input', () => doSearch(input.value));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { goTo(e.shiftKey ? currentIdx - 1 : currentIdx + 1); }
        if (e.key === 'Escape') { clearHighlights(); overlay.remove(); }
    });
    overlay.querySelector('#chat-search-prev').addEventListener('click', () => goTo(currentIdx > 0 ? currentIdx - 1 : matches.length - 1));
    overlay.querySelector('#chat-search-next').addEventListener('click', () => goTo(currentIdx < matches.length - 1 ? currentIdx + 1 : 0));
    overlay.querySelector('.chat-search-close').addEventListener('click', () => { clearHighlights(); overlay.remove(); });
    
    input.focus();
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 9: Message Pinning / Bookmarking
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initMessagePinning = function() {
    this._pinnedMessages = JSON.parse(localStorage.getItem('wr_pinned_' + (this.sessionId || 'default')) || '[]');
};

WitnessReplayApp.prototype._addPinButton = function(messageDiv, text, speaker) {
    const pinBtn = document.createElement('button');
    pinBtn.className = 'msg-pin-btn';
    pinBtn.innerHTML = '📌';
    pinBtn.title = 'Pin this message';
    pinBtn.setAttribute('aria-label', 'Pin message');
    
    const msgId = Date.now() + Math.random();
    pinBtn.addEventListener('click', () => {
        const isPinned = pinBtn.classList.contains('pinned');
        if (isPinned) {
            this._pinnedMessages = this._pinnedMessages.filter(p => p.text !== text);
            pinBtn.classList.remove('pinned');
            pinBtn.title = 'Pin this message';
            this.ui?.showToast('📌 Unpinned', 'info', 1500);
        } else {
            this._pinnedMessages.push({
                id: msgId,
                text: text,
                speaker: speaker,
                time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                date: new Date().toLocaleDateString()
            });
            pinBtn.classList.add('pinned');
            pinBtn.title = 'Unpin this message';
            this.ui?.showToast('📌 Message pinned!', 'success', 1500);
        }
        localStorage.setItem('wr_pinned_' + (this.sessionId || 'default'), JSON.stringify(this._pinnedMessages));
    });
    
    // Check if already pinned
    if (this._pinnedMessages.some(p => p.text === text)) {
        pinBtn.classList.add('pinned');
        pinBtn.title = 'Unpin this message';
    }
    
    messageDiv.appendChild(pinBtn);
};

WitnessReplayApp.prototype._showPinnedMessages = function() {
    if (!this._pinnedMessages || this._pinnedMessages.length === 0) {
        this.displaySystemMessage('📌 No pinned messages yet. Click the 📌 button on any message to pin it.');
        return;
    }
    
    let html = '📌 <b>Pinned Messages</b> (' + this._pinnedMessages.length + ')<br><br>';
    this._pinnedMessages.forEach((p, i) => {
        const speaker = p.speaker === 'user' ? '👤 You' : '🔍 Detective Ray';
        const preview = (p.text || '').substring(0, 120) + ((p.text || '').length > 120 ? '...' : '');
        html += `<div style="margin-bottom:8px;padding:6px 10px;background:rgba(96,165,250,0.08);border-radius:8px;border-left:3px solid var(--accent-blue);">
            <strong>${speaker}</strong> <span style="opacity:0.6;font-size:0.78rem;">${p.time || ''}</span><br>
            <span style="font-size:0.88rem;">${this._escapeHtml(preview)}</span>
        </div>`;
    });
    this.displaySystemMessage(html);
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 10: Interview Word Stats (/stats command)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._showInterviewWordStats = function() {
    const messages = this.chatTranscript?.querySelectorAll('.message');
    if (!messages || messages.length === 0) {
        this.displaySystemMessage('📊 No messages yet. Start the interview first.');
        return;
    }
    
    let userWords = 0, agentWords = 0, userMsgs = 0, agentMsgs = 0;
    const wordFreq = {};
    const stopWords = new Set(['the','a','an','is','was','are','were','i','you','he','she','it','we','they','my','your','his','her','its','our','their','and','or','but','in','on','at','to','for','of','with','that','this','from','by','as','not','have','has','had','do','does','did','be','been','being','will','would','could','should','can','may','might','just','so','very','also','about','up','out','if','no','when','what','where','who','how','than','then','there','here','all','some','any','each','every','more','most','other','into','over','after','before','between','under','again','once','during','while','now','only','me','him','them','us','am','which']);
    
    messages.forEach(msg => {
        const isUser = msg.classList.contains('message-user');
        const isAgent = msg.classList.contains('message-agent');
        if (!isUser && !isAgent) return;
        
        const clone = msg.cloneNode(true);
        clone.querySelectorAll('.msg-reactions, .msg-reaction-btn, .quick-reply-container, .copy-btn, .msg-avatar, .emotion-badge, .msg-pin-btn, .message-actions').forEach(el => el.remove());
        const text = clone.textContent.replace(/\s+/g, ' ').trim();
        const words = text.split(/\s+/).filter(w => w.length > 0);
        
        if (isUser) { userWords += words.length; userMsgs++; }
        else { agentWords += words.length; agentMsgs++; }
        
        // Count meaningful words from user
        if (isUser) {
            words.forEach(w => {
                const clean = w.toLowerCase().replace(/[^a-z']/g, '');
                if (clean.length > 2 && !stopWords.has(clean)) {
                    wordFreq[clean] = (wordFreq[clean] || 0) + 1;
                }
            });
        }
    });
    
    // Top keywords
    const topWords = Object.entries(wordFreq).sort((a, b) => b[1] - a[1]).slice(0, 10);
    const totalWords = userWords + agentWords;
    const readingTime = Math.max(1, Math.ceil(totalWords / 200));
    
    let html = '📊 <b>Interview Statistics</b><br><br>';
    html += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
        <div style="padding:8px;background:rgba(96,165,250,0.08);border-radius:8px;text-align:center;">
            <div style="font-size:1.4rem;font-weight:700;">${totalWords}</div>
            <div style="font-size:0.75rem;opacity:0.7;">Total Words</div>
        </div>
        <div style="padding:8px;background:rgba(74,222,128,0.08);border-radius:8px;text-align:center;">
            <div style="font-size:1.4rem;font-weight:700;">${readingTime} min</div>
            <div style="font-size:0.75rem;opacity:0.7;">Reading Time</div>
        </div>
        <div style="padding:8px;background:rgba(167,139,250,0.08);border-radius:8px;text-align:center;">
            <div style="font-size:1.4rem;font-weight:700;">${userMsgs}</div>
            <div style="font-size:0.75rem;opacity:0.7;">Witness Msgs</div>
        </div>
        <div style="padding:8px;background:rgba(251,191,36,0.08);border-radius:8px;text-align:center;">
            <div style="font-size:1.4rem;font-weight:700;">${agentMsgs}</div>
            <div style="font-size:0.75rem;opacity:0.7;">Ray Msgs</div>
        </div>
    </div>`;
    
    if (topWords.length > 0) {
        html += '<b>🔑 Key Terms:</b><br>';
        html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">';
        topWords.forEach(([word, count]) => {
            const size = Math.min(1.1, 0.75 + count * 0.05);
            html += `<span style="padding:3px 8px;background:rgba(96,165,250,0.12);border-radius:12px;font-size:${size}rem;">${this._escapeHtml(word)} <sup style="opacity:0.5">${count}</sup></span>`;
        });
        html += '</div>';
    }
    
    this.displaySystemMessage(html);
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 11: Auto-Save Indicator
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initAutoSaveIndicator = function() {
    const sessionInfo = document.querySelector('.session-info');
    if (!sessionInfo) return;
    
    const indicator = document.createElement('div');
    indicator.className = 'auto-save-indicator';
    indicator.id = 'auto-save-indicator';
    indicator.innerHTML = '<span class="save-icon">💾</span><span class="save-text">Saved</span>';
    
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        sessionInfo.insertBefore(indicator, themeToggle);
    } else {
        sessionInfo.appendChild(indicator);
    }
    
    this._saveState = 'saved';
};

WitnessReplayApp.prototype._showSaveState = function(state) {
    const el = document.getElementById('auto-save-indicator');
    if (!el) return;
    this._saveState = state;
    el.className = 'auto-save-indicator ' + state;
    const icon = el.querySelector('.save-icon');
    const text = el.querySelector('.save-text');
    if (state === 'saving') {
        if (icon) icon.textContent = '⏳';
        if (text) text.textContent = 'Saving...';
    } else if (state === 'saved') {
        if (icon) icon.textContent = '✅';
        if (text) text.textContent = 'Saved';
        setTimeout(() => { if (this._saveState === 'saved' && el) el.classList.add('fade'); }, 3000);
    } else if (state === 'error') {
        if (icon) icon.textContent = '⚠️';
        if (text) text.textContent = 'Save error';
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 12: Double-Click to Copy Messages
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initMessageDoubleClickCopy = function() {
    const transcript = document.getElementById('chat-transcript');
    if (!transcript) return;
    
    transcript.addEventListener('dblclick', (e) => {
        const msg = e.target.closest('.message');
        if (!msg) return;
        
        // Get clean text
        const clone = msg.cloneNode(true);
        clone.querySelectorAll('.msg-reactions, .msg-reaction-btn, .quick-reply-container, .copy-btn, .msg-avatar, .emotion-badge, .msg-pin-btn, .message-actions').forEach(el => el.remove());
        const text = clone.textContent.replace(/\s+/g, ' ').trim();
        
        this._copyToClipboard(text).then(ok => {
            if (ok) {
                msg.classList.add('copy-flash');
                setTimeout(() => msg.classList.remove('copy-flash'), 600);
                this.ui?.showToast('📋 Copied to clipboard', 'success', 1500);
            }
        });
    });
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 13: Enhanced /summary & /timeline Follow-up Actions
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._showContextualFollowUps = function(commandType) {
    const existing = document.querySelector('.followup-actions');
    if (existing) existing.remove();
    
    const actions = [];
    if (commandType === 'summary') {
        actions.push(
            { icon: '🎬', text: 'Generate scene from summary', cmd: '/scene' },
            { icon: '⏱️', text: 'Build timeline', cmd: '/timeline' },
            { icon: '📥', text: 'Export transcript', cmd: '/export' },
            { icon: '📌', text: 'View pinned messages', cmd: '/pins' }
        );
    } else if (commandType === 'timeline') {
        actions.push(
            { icon: '🎬', text: 'Generate scene image', cmd: '/scene' },
            { icon: '📋', text: 'Get full summary', cmd: '/summary' },
            { icon: '📊', text: 'Interview stats', cmd: '/stats' },
            { icon: '📥', text: 'Export transcript', cmd: '/export' }
        );
    }
    
    if (actions.length === 0) return;
    
    const container = document.createElement('div');
    container.className = 'followup-actions';
    container.innerHTML = '<span class="followup-label">Next steps:</span>';
    
    actions.forEach(a => {
        const btn = document.createElement('button');
        btn.className = 'followup-btn';
        btn.innerHTML = `${a.icon} ${a.text}`;
        btn.addEventListener('click', () => {
            container.remove();
            this._handleSlashCommand(a.cmd);
        });
        container.appendChild(btn);
    });
    
    this.chatTranscript.appendChild(container);
    this._scrollChatToBottom();
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 14: Interview Phase Progress Bar
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initPhaseProgressBar = function() {
    const header = document.querySelector('.header-content');
    if (!header || document.getElementById('phase-progress')) return;

    const bar = document.createElement('div');
    bar.id = 'phase-progress';
    bar.className = 'phase-progress';
    const phases = [
        { id: 'intro', label: 'Introduction', icon: '👋' },
        { id: 'details', label: 'Detail Collection', icon: '📝' },
        { id: 'clarify', label: 'Clarification', icon: '🔍' },
        { id: 'closing', label: 'Summary & Closing', icon: '✅' }
    ];
    bar.innerHTML = phases.map((p, i) =>
        `<div class="phase-step ${i === 0 ? 'active' : ''}" data-phase="${p.id}">` +
        `<span class="phase-icon">${p.icon}</span>` +
        `<span class="phase-label">${p.label}</span>` +
        `${i < phases.length - 1 ? '<span class="phase-connector"></span>' : ''}` +
        `</div>`
    ).join('');
    header.after(bar);

    this._currentPhase = 'intro';
    this._phaseMessageCount = 0;
};

WitnessReplayApp.prototype._updatePhaseProgress = function() {
    this._phaseMessageCount = (this._phaseMessageCount || 0) + 1;
    const count = this._phaseMessageCount;
    let newPhase = 'intro';
    if (count >= 20) newPhase = 'closing';
    else if (count >= 12) newPhase = 'clarify';
    else if (count >= 4) newPhase = 'details';

    if (newPhase === this._currentPhase) return;
    this._currentPhase = newPhase;

    const steps = document.querySelectorAll('.phase-step');
    const order = ['intro', 'details', 'clarify', 'closing'];
    const idx = order.indexOf(newPhase);
    steps.forEach((step, i) => {
        step.classList.toggle('active', i === idx);
        step.classList.toggle('completed', i < idx);
    });
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 15: Smart Dynamic Input Placeholder
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initSmartPlaceholder = function() {
    this._placeholderHints = [
        { phase: 'intro', hints: [
            'Describe what happened...',
            'Tell me about the incident...',
            'Where and when did this occur?'
        ]},
        { phase: 'details', hints: [
            'Can you describe the person(s) involved?',
            'What did you see or hear next?',
            'Were there any distinguishing features?',
            'What direction did they go?'
        ]},
        { phase: 'clarify', hints: [
            'Can you clarify that last point?',
            'How certain are you about the timing?',
            'Was there anything else you noticed?',
            'Any additional details about the vehicle?'
        ]},
        { phase: 'closing', hints: [
            'Anything else you want to add?',
            'Type /summary for a full summary',
            'Type /timeline to see the timeline',
            'Type /export to save transcript'
        ]}
    ];
    this._rotatePlaceholder();
    this._placeholderInterval = setInterval(() => this._rotatePlaceholder(), 12000);
};

WitnessReplayApp.prototype._rotatePlaceholder = function() {
    const input = document.getElementById('user-input');
    if (!input || document.activeElement === input) return;
    const phase = this._currentPhase || 'intro';
    const group = this._placeholderHints?.find(g => g.phase === phase);
    if (!group) return;
    const hint = group.hints[Math.floor(Math.random() * group.hints.length)];
    input.setAttribute('placeholder', hint);
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 16: Evidence Extraction (/evidence command)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._showEvidence = async function() {
    if (!this.sessionId) {
        this.displaySystemMessage('⚠️ No active session. Start a conversation first.');
        return;
    }
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/extract-evidence`);
        const data = await resp.json();
        if (!data.items || data.items.length === 0) {
            this.displaySystemMessage('🔍 <b>No evidence items detected yet.</b><br>Mention physical items, vehicles, weapons, or other objects to see them listed here.');
            return;
        }
        let html = `🗂️ <b>Evidence Items Found (${data.evidence_count})</b><br><div class="evidence-grid">`;
        data.items.forEach(item => {
            html += `<div class="evidence-card">` +
                `<span class="evidence-icon">${item.icon}</span>` +
                `<div class="evidence-info">` +
                `<span class="evidence-name">${item.item}</span>` +
                `<span class="evidence-context">${this._escapeHtml(item.context)}</span>` +
                `<span class="evidence-speaker">Mentioned by: ${item.speaker}</span>` +
                `</div></div>`;
        });
        html += '</div>';
        this.displaySystemMessage(html);
    } catch (e) {
        this.displaySystemMessage('⚠️ Could not load evidence items.');
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 17: Session Duration Live Timer
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initSessionTimer = function() {
    const sessionInfo = document.querySelector('.session-info');
    if (!sessionInfo || document.getElementById('session-timer')) return;

    const timer = document.createElement('div');
    timer.id = 'session-timer';
    timer.className = 'session-timer';
    timer.innerHTML = '<span class="timer-icon">⏱️</span><span class="timer-value">00:00</span>';
    sessionInfo.insertBefore(timer, sessionInfo.firstChild);

    this._sessionStartTime = Date.now();
    this._sessionTimerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - this._sessionStartTime) / 1000);
        const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
        const secs = String(elapsed % 60).padStart(2, '0');
        const val = timer.querySelector('.timer-value');
        if (val) val.textContent = `${mins}:${secs}`;
    }, 1000);
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 18: Message Timestamps
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._addMessageTimestamp = function(msgEl) {
    if (!msgEl || msgEl.querySelector('.msg-timestamp')) return;
    const now = new Date();
    const ts = document.createElement('span');
    ts.className = 'msg-timestamp';
    ts.title = now.toLocaleString();
    ts.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    ts.dataset.time = now.toISOString();

    const content = msgEl.querySelector('.message-content') || msgEl;
    content.appendChild(ts);
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 19: Admin Activity Heatmap
// (Implemented in admin.js below)
// ═══════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 20: Undo Last Message (/undo command)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._undoLastMessage = function() {
    const transcript = document.getElementById('chat-transcript');
    if (!transcript) return;
    const messages = transcript.querySelectorAll('.message.user');
    if (messages.length === 0) {
        this.displaySystemMessage('⚠️ No user messages to undo.');
        return;
    }
    const last = messages[messages.length - 1];
    const text = last.textContent.substring(0, 50).trim();
    last.remove();
    this.displaySystemMessage(`↩️ Removed last message: "<i>${this._escapeHtml(text)}...</i>"`);
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 21: Interview Quality Score (/quality)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initQualityScore = function() {
    const header = document.querySelector('.header-content');
    if (!header || document.getElementById('quality-score-widget')) return;

    const widget = document.createElement('div');
    widget.id = 'quality-score-widget';
    widget.className = 'quality-score-widget';
    widget.innerHTML = '<span class="qs-icon">📊</span><span class="qs-label">Quality</span>' +
        '<div class="qs-ring"><svg viewBox="0 0 36 36"><circle class="qs-bg" cx="18" cy="18" r="15.9"/>' +
        '<circle class="qs-fill" cx="18" cy="18" r="15.9" stroke-dasharray="0 100"/></svg>' +
        '<span class="qs-value">0</span></div>';
    widget.title = 'Interview quality score — click for details';
    widget.addEventListener('click', () => this._showQualityDetails());
    const sessionInfo = document.querySelector('.session-info');
    if (sessionInfo) sessionInfo.insertBefore(widget, sessionInfo.firstChild);
};

WitnessReplayApp.prototype._updateQualityScore = async function() {
    if (!this.sessionId) return;
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/quality-score`);
        const data = await resp.json();
        const score = data.score || 0;
        const fill = document.querySelector('.qs-fill');
        const val = document.querySelector('.qs-value');
        if (fill) fill.setAttribute('stroke-dasharray', `${score} ${100 - score}`);
        if (val) val.textContent = score;
        this._lastQualityData = data;
    } catch (e) { /* silent */ }
};

WitnessReplayApp.prototype._showQualityDetails = async function() {
    if (!this.sessionId) {
        this.displaySystemMessage('⚠️ No active session.');
        return;
    }
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/quality-score`);
        const data = await resp.json();
        let html = `📊 <b>Interview Quality Score: ${data.score}%</b><br>` +
            '<div class="quality-grid">';
        (data.categories || []).forEach(cat => {
            html += `<div class="quality-cat ${cat.covered ? 'covered' : 'missing'}">` +
                `<span class="qc-icon">${cat.covered ? '✅' : '⬜'}</span>` +
                `<span class="qc-label">${cat.label}</span></div>`;
        });
        html += '</div><br><small>💡 Cover more categories to improve your score.</small>';
        this.displaySystemMessage(html);
    } catch (e) {
        this.displaySystemMessage('⚠️ Could not load quality score.');
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 22: Per-message Read Aloud Button
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._addReadAloudButton = function(msgEl) {
    if (!msgEl || !msgEl.classList.contains('agent') || msgEl.querySelector('.read-aloud-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'read-aloud-btn';
    btn.title = 'Read this message aloud';
    btn.innerHTML = '🔊';
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const content = msgEl.querySelector('.message-content');
        const text = content ? content.textContent : msgEl.textContent;
        if ('speechSynthesis' in window) {
            window.speechSynthesis.cancel();
            const utt = new SpeechSynthesisUtterance(text.substring(0, 500));
            utt.rate = 0.95;
            utt.pitch = 1;
            btn.classList.add('speaking');
            utt.onend = () => btn.classList.remove('speaking');
            utt.onerror = () => btn.classList.remove('speaking');
            window.speechSynthesis.speak(utt);
        }
    });
    const actions = msgEl.querySelector('.message-actions');
    if (actions) {
        actions.appendChild(btn);
    } else {
        msgEl.appendChild(btn);
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 23: Sentiment Timeline (/sentiment)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._showSentimentTimeline = async function() {
    if (!this.sessionId) {
        this.displaySystemMessage('⚠️ No active session.');
        return;
    }
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/sentiment-timeline`);
        const data = await resp.json();
        if (!data.points || data.points.length === 0) {
            this.displaySystemMessage('📈 <b>No witness messages to analyze yet.</b><br>Continue the interview to build a sentiment timeline.');
            return;
        }
        let html = `📈 <b>Sentiment Timeline</b> (${data.total_statements} witness statements)<br>` +
            '<div class="sentiment-timeline">';
        data.points.forEach((pt, i) => {
            const cls = pt.sentiment === 'positive' ? 'pos' : pt.sentiment === 'negative' ? 'neg' : 'neu';
            html += `<div class="st-point ${cls}" title="${this._escapeHtml(pt.snippet)}">` +
                `<span class="st-dot"></span>` +
                `<span class="st-emoji">${pt.emoji}</span>` +
                `<span class="st-num">#${i + 1}</span>` +
                `</div>`;
            if (i < data.points.length - 1) html += '<span class="st-connector"></span>';
        });
        html += '</div>';

        const posCount = data.points.filter(p => p.sentiment === 'positive').length;
        const negCount = data.points.filter(p => p.sentiment === 'negative').length;
        const neuCount = data.points.filter(p => p.sentiment === 'neutral').length;
        html += `<div class="st-summary">` +
            `<span class="st-stat">😊 Positive: ${posCount}</span>` +
            `<span class="st-stat">😐 Neutral: ${neuCount}</span>` +
            `<span class="st-stat">😰 Negative: ${negCount}</span>` +
            `</div>`;
        this.displaySystemMessage(html);
    } catch (e) {
        this.displaySystemMessage('⚠️ Could not load sentiment data.');
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 24: Interview Info Checklist
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initInfoChecklist = function() {
    const container = document.querySelector('.container');
    if (!container || document.getElementById('info-checklist')) return;

    const panel = document.createElement('div');
    panel.id = 'info-checklist';
    panel.className = 'info-checklist collapsed';
    panel.innerHTML = '<div class="ic-header" id="ic-toggle">' +
        '<span class="ic-title">📋 Info Gathered</span>' +
        '<span class="ic-count">0/7</span>' +
        '<span class="ic-arrow">▶</span></div>' +
        '<div class="ic-body">' +
        ['who|👤 People/Suspects', 'what|📌 What Happened', 'when|🕐 Time/Date',
         'where|📍 Location', 'why|💡 Motive/Reason', 'how|⚙️ Method/Weapon',
         'description|🔎 Physical Description'].map(item => {
            const [key, label] = item.split('|');
            return `<div class="ic-item" data-cat="${key}"><span class="ic-check">⬜</span><span>${label}</span></div>`;
        }).join('') + '</div>';

    container.appendChild(panel);

    document.getElementById('ic-toggle').addEventListener('click', () => {
        panel.classList.toggle('collapsed');
        const arrow = panel.querySelector('.ic-arrow');
        if (arrow) arrow.textContent = panel.classList.contains('collapsed') ? '▶' : '▼';
    });
};

WitnessReplayApp.prototype._updateInfoChecklist = function(qualityData) {
    if (!qualityData || !qualityData.categories) return;
    let covered = 0;
    qualityData.categories.forEach(cat => {
        const item = document.querySelector(`.ic-item[data-cat="${cat.category}"]`);
        if (item) {
            const check = item.querySelector('.ic-check');
            if (cat.covered) {
                if (check) check.textContent = '✅';
                item.classList.add('checked');
                covered++;
            }
        }
    });
    const countEl = document.querySelector('.ic-count');
    if (countEl) countEl.textContent = `${covered}/7`;
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 25: Session Tags (/tag)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._handleTagCommand = async function(args) {
    if (!this.sessionId) {
        this.displaySystemMessage('⚠️ No active session.');
        return;
    }
    const tagName = args.trim();
    if (!tagName) {
        try {
            const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/tags`);
            const data = await resp.json();
            const tags = data.tags || [];
            if (tags.length === 0) {
                this.displaySystemMessage('🏷️ <b>No tags.</b> Use <code>/tag robbery</code> to add one.');
            } else {
                let html = '🏷️ <b>Session Tags</b><br><div class="tag-list">';
                tags.forEach(t => {
                    html += `<span class="session-tag">${this._escapeHtml(t)} <button class="tag-remove" data-tag="${this._escapeHtml(t)}">×</button></span>`;
                });
                html += '</div>';
                this.displaySystemMessage(html);
                document.querySelectorAll('.tag-remove').forEach(btn => {
                    btn.addEventListener('click', async (e) => {
                        const tag = e.target.dataset.tag;
                        try {
                            await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/tags/${encodeURIComponent(tag)}`, { method: 'DELETE' });
                            e.target.closest('.session-tag')?.remove();
                        } catch (err) { /* silent */ }
                    });
                });
            }
        } catch (e) {
            this.displaySystemMessage('⚠️ Could not load tags.');
        }
        return;
    }
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag: tagName }),
        });
        const data = await resp.json();
        this.displaySystemMessage(`🏷️ Tag added: <b>${this._escapeHtml(tagName)}</b> (${data.tags.length} total)`);
    } catch (e) {
        this.displaySystemMessage('⚠️ Could not add tag.');
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 26: Scroll Navigation Buttons
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initScrollNav = function() {
    const transcript = document.getElementById('chat-transcript');
    if (!transcript || document.getElementById('scroll-nav')) return;

    const nav = document.createElement('div');
    nav.id = 'scroll-nav';
    nav.className = 'scroll-nav';
    nav.innerHTML = '<button class="scroll-btn scroll-top" title="Scroll to top">⬆</button>' +
        '<button class="scroll-btn scroll-bottom" title="Scroll to bottom">⬇</button>';
    transcript.parentElement.appendChild(nav);

    nav.querySelector('.scroll-top').addEventListener('click', () => {
        transcript.scrollTo({ top: 0, behavior: 'smooth' });
    });
    nav.querySelector('.scroll-bottom').addEventListener('click', () => {
        transcript.scrollTo({ top: transcript.scrollHeight, behavior: 'smooth' });
    });

    let scrollTimeout;
    transcript.addEventListener('scroll', () => {
        clearTimeout(scrollTimeout);
        const show = transcript.scrollHeight > transcript.clientHeight + 200;
        nav.classList.toggle('visible', show);
        scrollTimeout = setTimeout(() => {
            if (!transcript.matches(':hover')) nav.classList.remove('visible');
        }, 2000);
    });
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 27: Admin Data Retention Panel
// (Implemented in admin.js)
// ═══════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 28: Key Fact Auto-Highlighting
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._highlightKeyFacts = function(text) {
    if (!text || typeof text !== 'string') return text;
    let html = this._escapeHtml(text);

    // Time patterns: 3:30 PM, 15:30, around 3pm, etc.
    html = html.replace(/\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?|\d{1,2}\s*(?:AM|PM|am|pm)|(?:around|about|approximately)\s+\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)\b/g,
        '<span class="fact-highlight fact-time" title="Time">⏰ $1</span>');

    // Date patterns: January 5, 02/14/2025, last Monday, etc.
    html = html.replace(/\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,?\s*\d{4})?|\d{1,2}\/\d{1,2}\/\d{2,4}|(?:last|this|next)\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday))\b/gi,
        '<span class="fact-highlight fact-date" title="Date">📅 $1</span>');

    // Location patterns: street names, intersections
    html = html.replace(/\b(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Place|Pl|Court|Ct))\b/g,
        '<span class="fact-highlight fact-location" title="Location">📍 $1</span>');

    // Numbers with units: 6 feet, 200 pounds, etc.
    html = html.replace(/\b(\d+(?:\.\d+)?\s*(?:feet|foot|ft|inches|inch|in|pounds|lbs|miles|mph|km|meters|yards|yd))\b/gi,
        '<span class="fact-highlight fact-measure" title="Measurement">📏 $1</span>');

    // Color descriptions for suspects/vehicles
    html = html.replace(/\b((?:black|white|red|blue|green|gray|grey|silver|brown|yellow|dark|light)\s+(?:car|truck|van|SUV|sedan|jacket|shirt|hoodie|pants|hat|mask|bag|backpack))\b/gi,
        '<span class="fact-highlight fact-desc" title="Description">🔎 $1</span>');

    return html;
};

// Override displayMessage to use highlighting for agent messages
(function() {
    const origDisplay = WitnessReplayApp.prototype.displayMessage;
    WitnessReplayApp.prototype.displayMessage = function(text, speaker) {
        if (speaker === 'user' && text && !text.startsWith('/')) {
            // Save original for data, show highlighted in DOM
            const msgDiv = origDisplay.call(this, text, speaker);
            // Re-highlight after render
            setTimeout(() => {
                const msgs = this.chatTranscript?.querySelectorAll('.message-user:last-child');
                if (msgs && msgs.length > 0) {
                    const last = msgs[msgs.length - 1];
                    const content = last.querySelector('.message-content') || last;
                    // Apply highlighting to the text node portion
                    const textNodes = Array.from(content.childNodes).filter(n => n.nodeType === 3);
                    textNodes.forEach(node => {
                        const highlighted = this._highlightKeyFacts(node.textContent);
                        if (highlighted !== this._escapeHtml(node.textContent)) {
                            const span = document.createElement('span');
                            span.innerHTML = highlighted;
                            node.replaceWith(span);
                        }
                    });
                }
            }, 50);
            return msgDiv;
        }
        return origDisplay.call(this, text, speaker);
    };
})();

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 29: Witness Profile Card
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initWitnessProfileCard = function() {
    if (document.getElementById('witness-profile-card')) return;

    const card = document.createElement('div');
    card.id = 'witness-profile-card';
    card.className = 'witness-profile-card collapsed';
    card.innerHTML = `
        <div class="wpc-header" id="wpc-toggle">
            <span class="wpc-icon">👤</span>
            <span class="wpc-title">Witness Profile</span>
            <span class="wpc-expand">▶</span>
        </div>
        <div class="wpc-body">
            <div class="wpc-field"><label>Name</label><span id="wpc-name">Unknown</span></div>
            <div class="wpc-field"><label>Age/Gender</label><span id="wpc-age">—</span></div>
            <div class="wpc-field"><label>Role</label><span id="wpc-role">Witness</span></div>
            <div class="wpc-field"><label>Location</label><span id="wpc-location">—</span></div>
            <div class="wpc-field"><label>Key Details</label><span id="wpc-details">—</span></div>
            <div class="wpc-field"><label>Statements</label><span id="wpc-stmts">0</span></div>
        </div>
    `;

    const container = document.querySelector('.container') || document.body;
    container.appendChild(card);

    document.getElementById('wpc-toggle').addEventListener('click', () => {
        card.classList.toggle('collapsed');
        card.querySelector('.wpc-expand').textContent = card.classList.contains('collapsed') ? '▶' : '▼';
    });
};

WitnessReplayApp.prototype._updateWitnessProfile = function(text) {
    if (!text) return;
    const lower = text.toLowerCase();

    // Extract name patterns: "my name is X", "I'm X", "call me X"
    const nameMatch = text.match(/(?:my name is|i'm|i am|call me|name's)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)/i);
    if (nameMatch) {
        const el = document.getElementById('wpc-name');
        if (el) el.textContent = nameMatch[1];
    }

    // Extract age: "I'm 35", "35 years old", "age 35"
    const ageMatch = text.match(/(?:i'm|i am|age|aged)\s*(\d{1,3})\b|\b(\d{1,3})\s*years?\s*old/i);
    if (ageMatch) {
        const el = document.getElementById('wpc-age');
        if (el) el.textContent = (ageMatch[1] || ageMatch[2]) + ' years old';
    }

    // Extract role: "I was the victim", "I'm a bystander"
    const roleMatch = lower.match(/i(?:'m| am| was)\s+(?:a |the )?(victim|witness|bystander|suspect|officer|driver|passenger|neighbor|employee|manager|owner|security guard)/);
    if (roleMatch) {
        const el = document.getElementById('wpc-role');
        if (el) el.textContent = roleMatch[1].charAt(0).toUpperCase() + roleMatch[1].slice(1);
    }

    // Location extraction
    const locMatch = text.match(/(?:at|on|near|outside|inside|in front of)\s+(?:the\s+)?([A-Z][a-zA-Z\s]+(?:Street|St|Ave|Avenue|Road|Rd|Park|Mall|Store|Building|Hotel|Restaurant|Bar|Station))/);
    if (locMatch) {
        const el = document.getElementById('wpc-location');
        if (el) el.textContent = locMatch[1].trim();
    }

    // Update statement count
    const stmtEl = document.getElementById('wpc-stmts');
    if (stmtEl) stmtEl.textContent = this.statementCount || 0;
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 30: AI Follow-up Question Suggestions
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._fetchAndShowSuggestions = async function() {
    if (!this.sessionId) return;
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/suggest-questions`);
        const data = await resp.json();
        if (data.suggestions && data.suggestions.length > 0) {
            this._showAISuggestionChips(data.suggestions);
        }
    } catch (e) { /* silent */ }
};

WitnessReplayApp.prototype._showAISuggestionChips = function(suggestions) {
    // Remove existing
    document.querySelectorAll('.ai-suggestion-bar').forEach(el => el.remove());

    const bar = document.createElement('div');
    bar.className = 'ai-suggestion-bar';
    bar.innerHTML = '<span class="aisb-label">💡 Suggested questions:</span>';

    suggestions.forEach(q => {
        const chip = document.createElement('button');
        chip.className = 'ai-suggestion-chip';
        chip.textContent = q.length > 60 ? q.substring(0, 57) + '...' : q;
        chip.title = q;
        chip.addEventListener('click', () => {
            if (this.textInput) {
                this.textInput.value = q;
                this.textInput.focus();
            }
            bar.remove();
        });
        bar.appendChild(chip);
    });

    const dismiss = document.createElement('button');
    dismiss.className = 'ai-suggestion-dismiss';
    dismiss.innerHTML = '✕';
    dismiss.title = 'Dismiss suggestions';
    dismiss.addEventListener('click', () => bar.remove());
    bar.appendChild(dismiss);

    const input = document.querySelector('.input-area') || document.querySelector('.chat-input-container');
    if (input) {
        input.parentNode.insertBefore(bar, input);
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 31: Message Context Menu
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initContextMenu = function() {
    if (document.getElementById('msg-context-menu')) return;

    const menu = document.createElement('div');
    menu.id = 'msg-context-menu';
    menu.className = 'msg-context-menu';
    menu.style.display = 'none';
    menu.innerHTML = `
        <button class="ctx-item" data-action="copy">📋 Copy Text</button>
        <button class="ctx-item" data-action="pin">📌 Pin Message</button>
        <button class="ctx-item" data-action="read">🔊 Read Aloud</button>
        <button class="ctx-item" data-action="highlight">🖍️ Highlight</button>
        <button class="ctx-item" data-action="delete">🗑️ Remove</button>
    `;
    document.body.appendChild(menu);

    this._ctxTarget = null;

    document.addEventListener('click', () => {
        menu.style.display = 'none';
    });

    menu.querySelectorAll('.ctx-item').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const action = btn.dataset.action;
            this._handleContextAction(action, this._ctxTarget);
            menu.style.display = 'none';
        });
    });

    const transcript = document.getElementById('chat-transcript');
    if (transcript) {
        transcript.addEventListener('contextmenu', (e) => {
            const msg = e.target.closest('.message');
            if (!msg) return;
            e.preventDefault();
            this._ctxTarget = msg;
            menu.style.left = Math.min(e.pageX, window.innerWidth - 180) + 'px';
            menu.style.top = Math.min(e.pageY, window.innerHeight - 200) + 'px';
            menu.style.display = 'flex';
        });
    }
};

WitnessReplayApp.prototype._handleContextAction = function(action, msgEl) {
    if (!msgEl) return;
    const textContent = msgEl.textContent || '';

    switch (action) {
        case 'copy':
            navigator.clipboard?.writeText(textContent).then(() => {
                this.displaySystemMessage('📋 Message copied to clipboard.');
            });
            break;
        case 'pin':
            this._pinMessage?.(msgEl);
            break;
        case 'read':
            if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
                const utt = new SpeechSynthesisUtterance(textContent.substring(0, 500));
                utt.rate = 0.95;
                window.speechSynthesis.speak(utt);
            }
            break;
        case 'highlight':
            msgEl.classList.toggle('msg-highlighted');
            break;
        case 'delete':
            msgEl.remove();
            this.displaySystemMessage('🗑️ Message removed from view.');
            break;
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 32: Investigation Report (/report command)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._generateReport = async function() {
    if (!this.sessionId) {
        this.displaySystemMessage('⚠️ No active session.');
        return;
    }
    this.displaySystemMessage('📄 Generating investigation report...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/investigation-report`);
        const report = await resp.json();

        let html = `<div class="investigation-report">`;
        html += `<h3>📋 ${this._escapeHtml(report.report_title)}</h3>`;
        html += `<div class="ir-section"><b>Case Info</b>`;
        html += `<div class="ir-row"><span>Case ID:</span> ${this._escapeHtml(report.case_info.case_id || 'N/A')}</div>`;
        html += `<div class="ir-row"><span>Status:</span> ${this._escapeHtml(report.case_info.status)}</div>`;
        html += `<div class="ir-row"><span>Type:</span> ${this._escapeHtml(report.case_info.incident_type)}</div>`;
        html += `<div class="ir-row"><span>Created:</span> ${report.case_info.created ? new Date(report.case_info.created).toLocaleString() : 'N/A'}</div>`;
        html += `</div>`;

        html += `<div class="ir-section"><b>Interview Summary</b>`;
        html += `<div class="ir-row"><span>Statements:</span> ${report.interview_summary.total_statements}</div>`;
        html += `<div class="ir-row"><span>Words:</span> ${report.interview_summary.total_words}</div>`;
        html += `<div class="ir-row"><span>Corrections:</span> ${report.interview_summary.corrections_made}</div>`;
        html += `<div class="ir-row"><span>Avg Confidence:</span> ${(report.interview_summary.avg_confidence * 100).toFixed(0)}%</div>`;
        html += `<div class="ir-row"><span>Duration:</span> ~${report.interview_summary.duration_estimate}</div>`;
        html += `</div>`;

        if (report.witness_statements && report.witness_statements.length > 0) {
            html += `<div class="ir-section"><b>Statements (${report.witness_statements.length})</b>`;
            report.witness_statements.slice(0, 10).forEach(s => {
                html += `<div class="ir-stmt">#${s.sequence}: "${this._escapeHtml(s.text.substring(0, 120))}${s.text.length > 120 ? '...' : ''}"${s.is_correction ? ' <em>(correction)</em>' : ''}</div>`;
            });
            if (report.witness_statements.length > 10) {
                html += `<div class="ir-stmt"><em>...and ${report.witness_statements.length - 10} more</em></div>`;
            }
            html += `</div>`;
        }

        if (report.tags && report.tags.length > 0) {
            html += `<div class="ir-section"><b>Tags:</b> ${report.tags.map(t => `<span class="session-tag">${this._escapeHtml(t)}</span>`).join(' ')}</div>`;
        }

        html += `<div class="ir-footer">Generated ${new Date(report.generated_at).toLocaleString()} • WitnessReplay AI</div>`;
        html += `</div>`;

        this.displaySystemMessage(html);
    } catch (e) {
        this.displaySystemMessage('⚠️ Could not generate report.');
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 33: Quick Incident Templates
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initQuickTemplates = function() {
    // Only show on empty/new sessions
    const transcript = document.getElementById('chat-transcript');
    if (!transcript) return;

    const existing = document.getElementById('quick-templates-bar');
    if (existing) existing.remove();

    const templates = [
        { icon: '🔫', label: 'Robbery', prompt: 'I want to report a robbery that I witnessed.' },
        { icon: '🚗', label: 'Traffic Accident', prompt: 'I want to report a traffic accident that I saw.' },
        { icon: '👊', label: 'Assault', prompt: 'I want to report an assault that I witnessed.' },
        { icon: '🏠', label: 'Burglary', prompt: 'I want to report a burglary at my property.' },
        { icon: '🔥', label: 'Arson/Fire', prompt: 'I want to report a suspicious fire I witnessed.' },
        { icon: '💊', label: 'Drug Activity', prompt: 'I want to report suspicious drug activity in my area.' },
        { icon: '🚨', label: 'Suspicious Activity', prompt: 'I want to report suspicious activity I observed.' },
        { icon: '📝', label: 'Other', prompt: 'I want to report an incident.' },
    ];

    const bar = document.createElement('div');
    bar.id = 'quick-templates-bar';
    bar.className = 'quick-templates-bar';
    bar.innerHTML = '<div class="qt-label">🚀 Quick Start — Select incident type:</div><div class="qt-grid"></div>';
    const grid = bar.querySelector('.qt-grid');

    templates.forEach(t => {
        const btn = document.createElement('button');
        btn.className = 'qt-btn';
        btn.innerHTML = `<span class="qt-icon">${t.icon}</span><span class="qt-text">${t.label}</span>`;
        btn.title = t.prompt;
        btn.addEventListener('click', () => {
            if (this.textInput) {
                this.textInput.value = t.prompt;
                this.textInput.focus();
            }
            bar.classList.add('qt-fade');
            setTimeout(() => bar.remove(), 300);
        });
        grid.appendChild(btn);
    });

    // Insert at top of transcript area
    transcript.parentNode.insertBefore(bar, transcript);
};

// Hook: Remove quick templates after first user message
(function() {
    const origSend = WitnessReplayApp.prototype.sendMessage;
    if (origSend) {
        WitnessReplayApp.prototype.sendMessage = function() {
            const bar = document.getElementById('quick-templates-bar');
            if (bar) {
                bar.classList.add('qt-fade');
                setTimeout(() => bar.remove(), 300);
            }
            return origSend.apply(this, arguments);
        };
    }
})();

// Hook: Show AI suggestion chips after agent messages + update witness profile
(function() {
    const origDisplay2 = WitnessReplayApp.prototype.displayMessage;
    WitnessReplayApp.prototype.displayMessage = function(text, speaker) {
        const result = origDisplay2.call(this, text, speaker);
        if (speaker === 'agent' && this.sessionId) {
            // Fetch follow-up suggestions after a short delay
            setTimeout(() => this._fetchAndShowSuggestions?.(), 800);
        }
        if (speaker === 'user' && text && !text.startsWith('/')) {
            this._updateWitnessProfile?.(text);
        }
        // Auto-summary check
        if (speaker === 'user' && text && !text.startsWith('/')) {
            this._autoSummaryMsgCount = (this._autoSummaryMsgCount || 0) + 1;
            if (this._autoSummaryMsgCount % 10 === 0) {
                setTimeout(() => this._triggerAutoSummary?.(), 1200);
            }
        }
        return result;
    };
})();

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 34: Witness Credibility Score
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initCredibilityGauge = function() {
    const sidebar = document.querySelector('.sidebar') || document.querySelector('.right-panel');
    if (!sidebar) return;

    const gauge = document.createElement('div');
    gauge.id = 'credibility-gauge';
    gauge.className = 'credibility-gauge collapsed';
    gauge.innerHTML = `
        <div class="cg-header" id="cg-toggle">
            <span>🛡️ Credibility</span>
            <span class="cg-score" id="cg-score-val">--</span>
        </div>
        <div class="cg-body" id="cg-body">
            <div class="cg-bar-wrap">
                <div class="cg-bar" id="cg-bar" style="width: 0%"></div>
            </div>
            <div class="cg-assessment" id="cg-assessment">Awaiting data...</div>
            <div class="cg-breakdown" id="cg-breakdown"></div>
        </div>
    `;
    sidebar.appendChild(gauge);

    document.getElementById('cg-toggle')?.addEventListener('click', () => {
        gauge.classList.toggle('collapsed');
    });
};

WitnessReplayApp.prototype._showCredibilityScore = async function() {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    this.displaySystemMessage('🛡️ Calculating credibility score...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/credibility-score`);
        const data = await resp.json();
        const s = data.credibility_score;
        const b = data.breakdown;
        const color = s >= 75 ? '#22c55e' : s >= 50 ? '#eab308' : '#ef4444';

        // Update gauge widget
        const bar = document.getElementById('cg-bar');
        const scoreEl = document.getElementById('cg-score-val');
        const assessEl = document.getElementById('cg-assessment');
        const brkEl = document.getElementById('cg-breakdown');
        if (bar) { bar.style.width = s + '%'; bar.style.background = color; }
        if (scoreEl) scoreEl.textContent = s + '%';
        if (assessEl) assessEl.textContent = data.assessment;
        if (brkEl) {
            brkEl.innerHTML = Object.entries(b).map(([k, v]) =>
                `<div class="cg-row"><span>${k.replace('_', ' ')}</span><span>${v}%</span></div>`
            ).join('');
        }
        const gauge = document.getElementById('credibility-gauge');
        if (gauge) gauge.classList.remove('collapsed');

        // Also show in chat
        let html = `<div class="credibility-report">`;
        html += `<h4>🛡️ Witness Credibility: <span style="color:${color}">${s}%</span> — ${data.assessment}</h4>`;
        html += `<div class="cr-bars">`;
        Object.entries(b).forEach(([k, v]) => {
            const c = v >= 75 ? '#22c55e' : v >= 50 ? '#eab308' : '#ef4444';
            html += `<div class="cr-bar-row"><span class="cr-label">${k.replace('_', ' ')}</span><div class="cr-track"><div class="cr-fill" style="width:${v}%;background:${c}"></div></div><span class="cr-val">${v}%</span></div>`;
        });
        html += `</div>`;
        if (data.flags.corrections > 0) html += `<div class="cr-flag">⚠️ ${data.flags.corrections} correction(s) detected</div>`;
        if (data.flags.hedge_words > 3) html += `<div class="cr-flag">⚠️ ${data.flags.hedge_words} hedging phrases found</div>`;
        html += `</div>`;

        this.displaySystemMessage(html);
    } catch (e) { this.displaySystemMessage('❌ Could not calculate credibility score.'); }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 35: Testimony Timeline Extraction (/timeline visual)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._showExtractedTimeline = async function() {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    this.displaySystemMessage('⏱️ Extracting timeline from testimony...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/extract-timeline`);
        const data = await resp.json();
        if (!data.events || data.events.length === 0) {
            this.displaySystemMessage('⏱️ No time references found yet. Keep describing events with specific times.');
            return;
        }

        let html = `<div class="extracted-timeline">`;
        html += `<h4>⏱️ Testimony Timeline (${data.event_count} events)</h4>`;
        html += `<div class="et-track">`;
        data.events.forEach((e, i) => {
            const precIcon = { exact: '🕐', approximate: '🕑', relative: '🕒', sequential: '🔗' }[e.precision] || '📌';
            html += `<div class="et-event">`;
            html += `<div class="et-dot"></div>`;
            html += `<div class="et-content">`;
            html += `<div class="et-time">${precIcon} ${this._escapeHtml(e.time_reference)}</div>`;
            html += `<div class="et-ctx">${this._escapeHtml(e.context)}</div>`;
            html += `</div></div>`;
        });
        html += `</div></div>`;

        this.displaySystemMessage(html);
    } catch (e) { this.displaySystemMessage('❌ Could not extract timeline.'); }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 36: Session Comparison (/compare command)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._compareSession = async function(otherSessionId) {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    if (!otherSessionId) {
        this.displaySystemMessage('💡 Usage: <code>/compare [session-id]</code><br>Paste the ID of another session to compare testimonies side by side.');
        return;
    }
    this.displaySystemMessage('🔄 Comparing sessions...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/compare/${this.sessionId}/${otherSessionId}`);
        const data = await resp.json();
        const c = data.comparison;

        let html = `<div class="session-comparison">`;
        html += `<h4>🔄 Session Comparison</h4>`;
        html += `<div class="sc-pair">`;
        html += `<div class="sc-card"><b>Session A</b><div>${this._escapeHtml(data.session_a.title)}</div><small>${data.session_a.statements} stmts · ${data.session_a.words} words</small></div>`;
        html += `<div class="sc-vs">VS</div>`;
        html += `<div class="sc-card"><b>Session B</b><div>${this._escapeHtml(data.session_b.title)}</div><small>${data.session_b.statements} stmts · ${data.session_b.words} words</small></div>`;
        html += `</div>`;

        html += `<div class="sc-stat"><span>Vocabulary Overlap</span><span>${c.overlap_pct}%</span></div>`;
        html += `<div class="sc-stat"><span>Shared Keywords</span><span>${c.shared_keyword_count}</span></div>`;
        html += `<div class="sc-stat"><span>Unique to A</span><span>${c.unique_to_a} words</span></div>`;
        html += `<div class="sc-stat"><span>Unique to B</span><span>${c.unique_to_b} words</span></div>`;

        if (c.shared_times.length > 0) html += `<div class="sc-match">🕐 Matching times: ${c.shared_times.join(', ')}</div>`;
        if (c.shared_locations.length > 0) html += `<div class="sc-match">📍 Matching locations: ${c.shared_locations.join(', ')}</div>`;
        if (c.shared_keywords.length > 0) html += `<div class="sc-keywords">Common terms: ${c.shared_keywords.slice(0, 15).join(', ')}</div>`;
        html += `</div>`;

        this.displaySystemMessage(html);
    } catch (e) { this.displaySystemMessage('❌ Could not compare sessions. Check the session ID.'); }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 37: Word Cloud Visualization (/wordcloud)
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._showWordCloud = async function() {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    this.displaySystemMessage('☁️ Generating word cloud...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/wordcloud`);
        const data = await resp.json();
        if (!data.cloud || data.cloud.length === 0) {
            this.displaySystemMessage('☁️ Not enough words yet. Keep talking!');
            return;
        }

        const colors = ['#60a5fa', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#fb923c', '#22d3ee', '#e879f9'];
        let html = `<div class="word-cloud">`;
        html += `<h4>☁️ Word Cloud (${data.total_words} total, ${data.unique_words} unique)</h4>`;
        html += `<div class="wc-container">`;
        data.cloud.forEach((w, i) => {
            const color = colors[i % colors.length];
            const size = Math.max(0.65, Math.min(2.2, w.size));
            const opacity = 0.6 + (w.size / 3) * 0.4;
            html += `<span class="wc-word" style="font-size:${size}em;color:${color};opacity:${opacity}" title="${w.word}: ${w.count} times">${this._escapeHtml(w.word)}</span> `;
        });
        html += `</div></div>`;

        this.displaySystemMessage(html);
    } catch (e) { this.displaySystemMessage('❌ Could not generate word cloud.'); }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 39: Auto-Summary System
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._initAutoSummaryTracker = function() {
    this._autoSummaryMsgCount = 0;
};

WitnessReplayApp.prototype._triggerAutoSummary = async function() {
    if (!this.sessionId) return;
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/auto-summary`);
        const data = await resp.json();
        if (!data.summary) return;

        let html = `<div class="auto-summary">`;
        html += `<div class="as-header" onclick="this.parentElement.classList.toggle('as-collapsed')">`;
        html += `<span>📝 Auto-Summary (${data.stats?.statements || 0} statements)</span>`;
        html += `<span class="as-toggle">▼</span></div>`;
        html += `<div class="as-body">`;
        html += `<p>${this._escapeHtml(data.summary)}</p>`;
        if (data.key_points && data.key_points.length) {
            html += `<ul class="as-points">`;
            data.key_points.forEach(p => { html += `<li>${this._escapeHtml(p)}</li>`; });
            html += `</ul>`;
        }
        html += `</div></div>`;

        this.displaySystemMessage(html);
    } catch (e) { /* silent */ }
};

WitnessReplayApp.prototype._showAutoSummary = async function() {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    this.displaySystemMessage('📝 Generating summary...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/auto-summary`);
        const data = await resp.json();

        let html = `<div class="auto-summary">`;
        html += `<h4>📝 Interview Summary</h4>`;
        html += `<p>${this._escapeHtml(data.summary)}</p>`;
        if (data.key_points && data.key_points.length) {
            html += `<ul class="as-points">`;
            data.key_points.forEach(p => { html += `<li>${this._escapeHtml(p)}</li>`; });
            html += `</ul>`;
        }
        html += `</div>`;
        this.displaySystemMessage(html);
    } catch (e) { this.displaySystemMessage('❌ Could not generate summary.'); }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 40: Enhanced Keyboard Shortcuts
// ═══════════════════════════════════════════════════════════════════
(function() {
    document.addEventListener('keydown', function(e) {
        // Ctrl+Enter sends message
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            const sendBtn = document.querySelector('.send-btn') || document.getElementById('send-btn');
            if (sendBtn) { sendBtn.click(); e.preventDefault(); }
        }
        // Ctrl+Shift+C — credibility
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'C') {
            if (window.app?._showCredibilityScore) { window.app._showCredibilityScore(); e.preventDefault(); }
        }
        // Ctrl+Shift+W — word cloud
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'W') {
            if (window.app?._showWordCloud) { window.app._showWordCloud(); e.preventDefault(); }
        }
        // Ctrl+Shift+B — bookmark current
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'B') {
            if (window.app?._addBookmark) { window.app._addBookmark(); e.preventDefault(); }
        }
    });
})();

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 41: Testimony Bookmark System
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._addBookmark = async function(note) {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    const body = { note: note || '', label: 'important' };
    try {
        const resp = await fetch(`/api/sessions/${this.sessionId}/bookmarks`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
        });
        const data = await resp.json();
        const bm = data.bookmark;
        this.displaySystemMessage(`🔖 Bookmark added! (${data.total} total)${bm.text_preview ? '<br><small>"' + this._escapeHtml(bm.text_preview) + '"</small>' : ''}${note ? '<br>📝 ' + this._escapeHtml(note) : ''}`);
    } catch (e) { this.displaySystemMessage('❌ Could not add bookmark.'); }
};

WitnessReplayApp.prototype._showBookmarks = async function() {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/bookmarks`);
        const data = await resp.json();
        if (!data.bookmarks || data.bookmarks.length === 0) {
            this.displaySystemMessage('🔖 No bookmarks yet. Use <code>/bookmark [note]</code> or <b>Ctrl+Shift+B</b> to bookmark the latest statement.');
            return;
        }
        let html = `<div class="bookmarks-list">`;
        html += `<h4>🔖 Bookmarks (${data.total})</h4>`;
        data.bookmarks.forEach(bm => {
            html += `<div class="bm-item">`;
            html += `<div class="bm-meta"><span class="bm-label">#${bm.statement_index + 1}</span>`;
            html += `<span class="bm-time">${new Date(bm.created_at).toLocaleTimeString()}</span></div>`;
            if (bm.text_preview) html += `<div class="bm-preview">"${this._escapeHtml(bm.text_preview)}"</div>`;
            if (bm.note) html += `<div class="bm-note">📝 ${this._escapeHtml(bm.note)}</div>`;
            html += `</div>`;
        });
        html += `</div>`;
        this.displaySystemMessage(html);
    } catch (e) { this.displaySystemMessage('❌ Could not load bookmarks.'); }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 42: AI Contradiction Detector
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._detectContradictions = async function() {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    this.displaySystemMessage('🔍 Analyzing testimony for contradictions...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/contradictions`);
        const data = await resp.json();

        let html = `<div class="contradiction-report">`;
        html += `<h4>🔍 Contradiction Analysis</h4>`;
        html += `<div class="ctr-summary">`;
        const sevColor = data.severity_score > 8 ? '#ef4444' : data.severity_score > 3 ? '#eab308' : '#22c55e';
        html += `<div class="ctr-score" style="border-color:${sevColor}">`;
        html += `<span class="ctr-count">${data.count}</span>`;
        html += `<span class="ctr-label">Issues</span></div>`;
        html += `<div class="ctr-assess">${this._escapeHtml(data.assessment)}</div>`;
        html += `</div>`;

        if (data.contradictions && data.contradictions.length > 0) {
            html += `<div class="ctr-list">`;
            data.contradictions.forEach(c => {
                const icon = c.type === 'quantity_mismatch' ? '🔢' : c.type === 'time_reference' ? '🕐' : '↔️';
                const sevBadge = c.severity === 'high' ? '<span class="ctr-sev-high">HIGH</span>' : '<span class="ctr-sev-med">MED</span>';
                html += `<div class="ctr-item">`;
                html += `<div class="ctr-head">${icon} ${sevBadge} ${this._escapeHtml(c.description)}</div>`;
                html += `<div class="ctr-excerpts">`;
                html += `<div class="ctr-ex-a"><b>Stmt #${c.statement_a.index + 1}:</b> "${this._escapeHtml(c.statement_a.excerpt)}"</div>`;
                html += `<div class="ctr-ex-b"><b>Stmt #${c.statement_b.index + 1}:</b> "${this._escapeHtml(c.statement_b.excerpt)}"</div>`;
                html += `</div></div>`;
            });
            html += `</div>`;
        }

        if (data.corrections && data.corrections.length > 0) {
            html += `<div class="ctr-corrections"><h5>⚠️ Self-Corrections (${data.correction_count})</h5>`;
            data.corrections.forEach(c => {
                html += `<div class="ctr-corr-item">Stmt #${c.index + 1}: "${this._escapeHtml(c.excerpt)}"</div>`;
            });
            html += `</div>`;
        }

        html += `</div>`;
        this.displaySystemMessage(html);
    } catch (e) { this.displaySystemMessage('❌ Could not analyze contradictions.'); }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 43: Session Export to Markdown
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._exportMarkdown = async function() {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    this.displaySystemMessage('📄 Generating markdown export...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/export/markdown`);
        const data = await resp.json();
        if (!data.markdown) { this.displaySystemMessage('⚠️ No content to export.'); return; }

        // Copy to clipboard
        try {
            await navigator.clipboard.writeText(data.markdown);
            this.displaySystemMessage(`📄 Markdown exported! (${data.statements} statements)<br><b>✅ Copied to clipboard</b><br><small>Paste into any markdown editor or note-taking app.</small>`);
        } catch (clipErr) {
            // Fallback: show in a copyable text area
            let html = `<div class="md-export">`;
            html += `<h4>📄 Markdown Export</h4>`;
            html += `<textarea class="md-export-area" rows="10" readonly onclick="this.select()">${this._escapeHtml(data.markdown)}</textarea>`;
            html += `<small>Select all and copy (Ctrl+A, Ctrl+C)</small>`;
            html += `</div>`;
            this.displaySystemMessage(html);
        }
    } catch (e) { this.displaySystemMessage('❌ Could not export markdown.'); }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 44: Smart Evidence Linker
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._showEvidenceLinks = async function() {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    this.displaySystemMessage('🔗 Scanning for evidence references...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/evidence-links`);
        const data = await resp.json();
        if (!data.evidence_refs || data.evidence_refs.length === 0) {
            this.displaySystemMessage('🔗 No evidence references found yet. Mention exhibits, documents, photos, or files in your testimony.');
            return;
        }

        let html = `<div class="evidence-links">`;
        html += `<h4>🔗 Evidence References (${data.count} found)</h4>`;

        if (data.cross_referenced && data.cross_referenced.length > 0) {
            html += `<div class="evl-cross"><b>🔄 Cross-Referenced (mentioned multiple times):</b>`;
            data.cross_referenced.forEach(r => {
                html += `<div class="evl-item evl-cross-item">`;
                html += `<span class="evl-ref">${this._escapeHtml(r.reference)}</span>`;
                html += `<span class="evl-type">${r.type}</span>`;
                html += `<span class="evl-count">Mentioned in ${r.mentioned_in.length} statements</span>`;
                html += `</div>`;
            });
            html += `</div>`;
        }

        html += `<div class="evl-all">`;
        data.evidence_refs.forEach(r => {
            const icon = { exhibit: '📑', document: '📄', photo: '📸', video: '🎥', recording: '🎙️', report: '📊', evidence: '🔬', file: '📁', item: '📦' }[r.type] || '📌';
            html += `<div class="evl-item">`;
            html += `<span class="evl-icon">${icon}</span>`;
            html += `<span class="evl-ref">${this._escapeHtml(r.reference)}</span>`;
            html += `<span class="evl-type">${r.type}</span>`;
            html += `<span class="evl-stmts">Stmts: ${r.mentioned_in.map(i => '#' + (i + 1)).join(', ')}</span>`;
            html += `</div>`;
        });
        html += `</div></div>`;

        this.displaySystemMessage(html);
    } catch (e) { this.displaySystemMessage('❌ Could not scan evidence references.'); }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 46: Witness Statement Diff
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._showStatementDiff = async function(arg) {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    let a = 0, b = -1;
    if (arg) {
        const parts = arg.split(/[\s,]+/);
        if (parts.length >= 2) { a = parseInt(parts[0]) - 1; b = parseInt(parts[1]) - 1; }
        else if (parts.length === 1) { b = parseInt(parts[0]) - 1; }
    }
    this.displaySystemMessage('📝 Comparing statements...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/diff?a=${a}&b=${b}`);
        const data = await resp.json();
        if (data.error) { this.displaySystemMessage(`⚠️ ${data.error}`); return; }

        const simColor = data.similarity_pct > 70 ? '#22c55e' : data.similarity_pct > 40 ? '#eab308' : '#ef4444';
        let html = `<div class="stmt-diff">`;
        html += `<h4>📝 Statement Diff</h4>`;
        html += `<div class="sd-pair">`;
        html += `<div class="sd-card sd-card-a"><b>Statement #${data.statement_a.index + 1}</b> (${data.statement_a.word_count} words)<p>${this._escapeHtml(data.statement_a.text)}</p></div>`;
        html += `<div class="sd-card sd-card-b"><b>Statement #${data.statement_b.index + 1}</b> (${data.statement_b.word_count} words)<p>${this._escapeHtml(data.statement_b.text)}</p></div>`;
        html += `</div>`;
        html += `<div class="sd-stats">`;
        html += `<div class="sd-sim" style="color:${simColor}">Similarity: ${data.similarity_pct}%</div>`;
        html += `<div class="sd-changes">`;
        html += `<span class="sd-added">+${data.added_count} new words</span>`;
        html += `<span class="sd-removed">-${data.removed_count} removed words</span>`;
        html += `</div></div>`;
        if (data.added_words.length > 0) {
            html += `<div class="sd-words-added"><b>Added:</b> ${data.added_words.slice(0, 15).map(w => '<span class="sd-w-add">' + this._escapeHtml(w) + '</span>').join(' ')}</div>`;
        }
        if (data.removed_words.length > 0) {
            html += `<div class="sd-words-removed"><b>Removed:</b> ${data.removed_words.slice(0, 15).map(w => '<span class="sd-w-rem">' + this._escapeHtml(w) + '</span>').join(' ')}</div>`;
        }
        html += `</div>`;
        this.displaySystemMessage(html);
    } catch (e) { this.displaySystemMessage('❌ Could not compare statements.'); }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 47: Interview Completeness Checker
// ═══════════════════════════════════════════════════════════════════
WitnessReplayApp.prototype._checkCompleteness = async function() {
    if (!this.sessionId) { this.displaySystemMessage('⚠️ No active session.'); return; }
    this.displaySystemMessage('✅ Checking interview completeness...');
    try {
        const resp = await this.fetchWithTimeout(`/api/sessions/${this.sessionId}/completeness`);
        const data = await resp.json();

        const pctColor = data.completeness_pct >= 70 ? '#22c55e' : data.completeness_pct >= 40 ? '#eab308' : '#ef4444';
        let html = `<div class="completeness-check">`;
        html += `<h4>✅ Interview Completeness</h4>`;
        html += `<div class="cc-score">`;
        html += `<div class="cc-ring" style="--pct:${data.completeness_pct};--color:${pctColor}">`;
        html += `<span class="cc-pct">${data.completeness_pct}%</span></div>`;
        html += `<div class="cc-assess">${this._escapeHtml(data.assessment)}</div>`;
        html += `<div class="cc-ratio">${data.areas_covered}/${data.total_areas} areas covered</div>`;
        html += `</div>`;

        html += `<div class="cc-areas">`;
        Object.entries(data.coverage).forEach(([key, area]) => {
            const barColor = area.covered ? '#22c55e' : '#374151';
            const checkmark = area.covered ? '✅' : '❌';
            html += `<div class="cc-area ${area.covered ? 'cc-covered' : 'cc-missing'}">`;
            html += `<span class="cc-icon">${area.icon}</span>`;
            html += `<span class="cc-name">${area.label}</span>`;
            html += `<span class="cc-check">${checkmark}</span>`;
            html += `<div class="cc-bar"><div class="cc-fill" style="width:${area.depth_score}%;background:${barColor}"></div></div>`;
            html += `</div>`;
        });
        html += `</div>`;

        if (data.suggestions && data.suggestions.length > 0) {
            html += `<div class="cc-suggestions"><b>💡 Suggestions:</b>`;
            data.suggestions.forEach(s => { html += `<div class="cc-sug">${this._escapeHtml(s)}</div>`; });
            html += `</div>`;
        }
        html += `</div>`;
        this.displaySystemMessage(html);
    } catch (e) { this.displaySystemMessage('❌ Could not check completeness.'); }
};
