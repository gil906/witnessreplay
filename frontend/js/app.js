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
        
        this.initializeUI();
        this.initializeAudio();
        this.initializeModals();
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
        
        // Model & Quota button
        const quotaBtn = document.getElementById('quota-btn');
        if (quotaBtn) {
            quotaBtn.addEventListener('click', () => this.showQuotaModal());
        }
        
        // Start with a new session
        this.createNewSession();
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
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            // We'll request on first mic click instead of page load
            console.log('MediaDevices API available');
        } else {
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
            console.log('WebSocket connected');
            this.reconnectAttempts = 0;
            this.ui.setStatus('Ready — Press Space to speak', 'default');
            this.micBtn.disabled = false;
            if (this.chatMicBtn) this.chatMicBtn.disabled = false;
            this.textInput.disabled = false;
            this.sendBtn.disabled = false;
            this.ui.showToast('Connected to Detective Ray', 'success', 2000);
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
            console.log('WebSocket closed');
            this.ui.setStatus('Disconnected', 'default');
            this.micBtn.disabled = true;
            if (this.chatMicBtn) this.chatMicBtn.disabled = true;
            this.textInput.disabled = true;
            this.sendBtn.disabled = true;
            
            // Reconnect with backoff, max attempts
            if (this.sessionId && this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                const delay = Math.min(3000 * this.reconnectAttempts, 15000);
                this.ui.showToast(`Reconnecting (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`, 'info', 2000);
                this.reconnectTimer = setTimeout(() => {
                    this.connectWebSocket();
                }, delay);
            } else if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                this.ui.setStatus('Connection lost — click New Session to retry', 'default');
                this.ui.showToast('Connection lost. Please start a new session.', 'error', 5000);
            }
        };
    }
    
    handleWebSocketMessage(message) {
        console.log('Received message:', message);
        
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
            
            case 'status':
                const statusMsg = message.data.message || message.data.status;
                const state = this.getStatusState(statusMsg);
                this.ui.setStatus(statusMsg, state);
                
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
            } else {
                this.ui.showToast('Audio recorder not available. Use text input.', 'warning');
            }
        } catch (error) {
            console.error('Error starting recording:', error);
            this.ui.showToast('Microphone error: ' + error.message, 'error');
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
                
                // Convert to base64 and send
                this.sendAudioMessage(audioBlob);
            }
        } catch (error) {
            console.error('Error stopping recording:', error);
            this.setStatus('Error processing audio');
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
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${speaker}`;
        
        const label = document.createElement('strong');
        label.textContent = speaker === 'user' ? 'You: ' : 
                           speaker === 'agent' ? 'Agent: ' : 
                           'System: ';
        
        const textNode = document.createTextNode(text);
        
        messageDiv.appendChild(label);
        messageDiv.appendChild(textNode);
        
        this.chatTranscript.appendChild(messageDiv);
        this.chatTranscript.scrollTop = this.chatTranscript.scrollHeight;
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
        this.versionCountEl.textContent = this.currentVersion;
        
        if (data.statement_count) {
            this.statementCountEl.textContent = data.statement_count;
        }
        
        // Update complexity if available
        if (data.complexity !== undefined) {
            this.complexityCard.style.display = 'block';
            this.complexityScoreEl.textContent = (data.complexity * 100).toFixed(0) + '%';
        }
        
        // Update contradictions if available
        if (data.contradictions && data.contradictions.length > 0) {
            this.contradictionCard.style.display = 'block';
            this.contradictionCountEl.textContent = data.contradictions.length;
            this.ui.showToast(`⚠️ ${data.contradictions.length} contradiction(s) detected`, 'warning', 4000);
        }
        
        // Show export controls once we have a scene
        this.exportControls.style.display = 'block';
        
        // Add to timeline
        this.addTimelineVersion(data);
    }
    
    showSceneLoadingSkeleton() {
        // Show loading skeleton before scene generation
        const skeleton = document.createElement('div');
        skeleton.className = 'scene-skeleton';
        skeleton.innerHTML = `
            <svg class="progress-ring" viewBox="0 0 60 60">
                <circle cx="30" cy="30" r="26"></circle>
            </svg>
        `;
        
        this.sceneDisplay.innerHTML = '';
        this.sceneDisplay.appendChild(skeleton);
        
        this.sceneDescription.innerHTML = '<p class="text-muted">Detective Ray is generating the scene...</p>';
    }
    
    setSceneImage(data) {
        if (data.image_url) {
            // Create image with loading state
            const img = new Image();
            img.className = 'scene-image loading';
            img.alt = 'Scene reconstruction';
            
            img.onload = () => {
                // Transition from blur to sharp
                setTimeout(() => {
                    img.classList.remove('loading');
                    img.classList.add('loaded', 'crossfade-in');
                }, 50);
            };
            
            img.src = data.image_url;
            
            // Clear and add new image
            this.sceneDisplay.innerHTML = '';
            this.sceneDisplay.appendChild(img);
            
            // Re-add scene controls
            const controls = document.createElement('div');
            controls.className = 'scene-controls';
            controls.innerHTML = `
                <button class="scene-control-btn" id="zoom-btn" data-tooltip="Zoom" aria-label="Zoom scene">🔍</button>
                <button class="scene-control-btn" id="download-btn" data-tooltip="Download" aria-label="Download scene">⬇️</button>
                <button class="scene-control-btn" id="fullscreen-btn" data-tooltip="Fullscreen" aria-label="Fullscreen">⛶</button>
            `;
            this.sceneDisplay.appendChild(controls);
            
            // Re-attach event listeners
            controls.querySelector('#zoom-btn')?.addEventListener('click', () => this.toggleZoom());
            controls.querySelector('#download-btn')?.addEventListener('click', () => this.downloadScene());
            controls.querySelector('#fullscreen-btn')?.addEventListener('click', () => this.toggleFullscreen());
        }
    }
    
    addTimelineVersion(data) {
        if (this.timeline.querySelector('.empty-state')) {
            this.timeline.innerHTML = '';
        }
        
        const versionDiv = document.createElement('div');
        versionDiv.className = 'timeline-item active';
        versionDiv.dataset.version = data.version || this.currentVersion;
        
        const changes = data.changes ? `<div class="timeline-changes">✨ ${data.changes}</div>` : '';
        
        versionDiv.innerHTML = `
            <div class="timeline-version">Version ${data.version || this.currentVersion}</div>
            <div class="timeline-time">${new Date().toLocaleTimeString()}</div>
            ${data.image_url ? `<img src="${data.image_url}" alt="Version ${data.version}">` : ''}
            ${data.description ? `<p class="timeline-description">${data.description.substring(0, 100)}...</p>` : ''}
            ${changes}
        `;
        
        // Remove active class from previous versions
        this.timeline.querySelectorAll('.timeline-item').forEach(item => {
            item.classList.remove('active');
        });
        
        // Add click handler
        versionDiv.addEventListener('click', () => {
            this.showTimelineVersion(versionDiv);
        });
        
        this.timeline.insertBefore(versionDiv, this.timeline.firstChild);
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
            
            // Refresh quota after model change
            await this.refreshQuota();
            
            setTimeout(() => {
                applyBtn.textContent = 'Apply';
                applyBtn.disabled = true;
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
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new WitnessReplayApp();
});
