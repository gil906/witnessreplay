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
        
        this.initializeUI();
        this.initializeAudio();
        this.initializeModals();
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
        
        // Event listeners
        this.micBtn.addEventListener('click', () => this.toggleRecording());
        this.sendBtn.addEventListener('click', () => this.sendTextMessage());
        this.textInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendTextMessage();
        });
        this.newSessionBtn.addEventListener('click', () => this.createNewSession());
        this.sessionsListBtn.addEventListener('click', () => this.showSessionsList());
        this.helpBtn.addEventListener('click', () => this.ui.showOnboarding());
        
        // Scene controls
        document.getElementById('download-btn')?.addEventListener('click', () => this.downloadScene());
        document.getElementById('zoom-btn')?.addEventListener('click', () => this.toggleZoom());
        document.getElementById('fullscreen-btn')?.addEventListener('click', () => this.toggleFullscreen());
        
        // Start with a new session
        this.createNewSession();
    }
    
    initializeAudio() {
        if (window.AudioRecorder) {
            this.audioRecorder = new AudioRecorder();
        }
        
        if (window.AudioVisualizer) {
            this.audioVisualizer = new EnhancedAudioVisualizer('audio-visualizer');
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
    }
    
    async createNewSession() {
        try {
            this.ui.setStatus('Creating session...', 'processing');
            
            // Call API to create session
            const response = await fetch('/api/sessions', {
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
        
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/${this.sessionId}`;
        
        this.ui.setStatus('Connecting to Detective Ray...', 'processing');
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.ui.setStatus('Ready — Press Space to speak', 'default');
            this.micBtn.disabled = false;
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
            this.ui.showToast('Connection error — reconnecting...', 'error');
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket closed');
            this.ui.setStatus('Disconnected', 'default');
            this.micBtn.disabled = true;
            this.textInput.disabled = true;
            this.sendBtn.disabled = true;
            
            // Try to reconnect after a delay
            setTimeout(() => {
                if (this.sessionId) {
                    this.ui.showToast('Attempting to reconnect...', 'info');
                    this.connectWebSocket();
                }
            }, 3000);
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
                break;
            
            case 'status':
                const statusMsg = message.data.message || message.data.status;
                const state = this.getStatusState(statusMsg);
                this.ui.setStatus(statusMsg, state);
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
            if (this.audioRecorder) {
                await this.audioRecorder.start();
                this.isRecording = true;
                this.micBtn.classList.add('recording');
                this.micBtn.querySelector('.btn-text').textContent = 'Recording...';
                this.stopBtn.style.display = 'inline-block';
                this.setStatus('Listening...');
            } else {
                this.setStatus('Audio recording not available. Use text input.');
            }
        } catch (error) {
            console.error('Error starting recording:', error);
            this.setStatus('Microphone access denied');
        }
    }
    
    async stopRecording() {
        if (!this.isRecording) return;
        
        try {
            if (this.audioRecorder) {
                const audioBlob = await this.audioRecorder.stop();
                this.isRecording = false;
                this.micBtn.classList.remove('recording');
                this.micBtn.querySelector('.btn-text').textContent = 'Start Speaking';
                this.stopBtn.style.display = 'none';
                
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
        // Update scene image
        if (data.image_url) {
            this.sceneDisplay.innerHTML = `
                <img src="${data.image_url}" alt="Scene reconstruction" class="scene-image">
            `;
        }
        
        // Update description
        if (data.description) {
            this.sceneDescription.innerHTML = `<p>${data.description}</p>`;
        }
        
        // Add to timeline
        this.currentVersion = data.version || this.currentVersion + 1;
        this.addTimelineVersion(data);
    }
    
    addTimelineVersion(data) {
        if (this.timeline.querySelector('.empty-state')) {
            this.timeline.innerHTML = '';
        }
        
        const versionDiv = document.createElement('div');
        versionDiv.className = 'timeline-item';
        versionDiv.innerHTML = `
            <div class="timeline-version">Version ${data.version || this.currentVersion}</div>
            <div class="timeline-time">${new Date().toLocaleTimeString()}</div>
            ${data.image_url ? `<img src="${data.image_url}" alt="Version ${data.version}">` : ''}
            ${data.description ? `<p>${data.description.substring(0, 100)}...</p>` : ''}
        `;
        
        this.timeline.insertBefore(versionDiv, this.timeline.firstChild);
    }
    
    setStatus(status) {
        this.statusText.textContent = status;
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new WitnessReplayApp();
});
    
    toggleRecording() {
        if (this.isRecording) {
            this.stopRecording();
        } else {
            this.startRecording();
        }
    }
    
    async startRecording() {
        try {
            if (this.audioRecorder) {
                await this.audioRecorder.start();
                this.isRecording = true;
                
                // Update mic button
                this.micBtn.classList.add('recording');
                this.waveformRing?.classList.add('active');
                
                // Start visualizer
                if (this.audioVisualizer && this.audioRecorder.stream) {
                    this.audioVisualizer.start(this.audioRecorder.stream);
                }
                
                // Update status
                this.ui.setStatus('🎤 Listening...', 'listening');
                this.ui.playSound('micClick');
                
            } else {
                this.ui.setStatus('Audio recording not available. Use text input.', 'default');
                this.ui.showToast('Microphone not available', 'warning');
            }
        } catch (error) {
            console.error('Error starting recording:', error);
            this.ui.setStatus('Microphone access denied', 'default');
            this.ui.showToast('Microphone access denied. Please allow microphone access.', 'error');
        }
    }
    
    async stopRecording() {
        if (!this.isRecording) return;
        
        try {
            if (this.audioRecorder) {
                const audioBlob = await this.audioRecorder.stop();
                this.isRecording = false;
                
                // Update mic button
                this.micBtn.classList.remove('recording');
                this.micBtn.classList.add('processing');
                this.waveformRing?.classList.remove('active');
                
                // Stop visualizer
                if (this.audioVisualizer) {
                    this.audioVisualizer.stop();
                }
                
                // Send audio
                this.sendAudioMessage(audioBlob);
                
                this.ui.playSound('micClick');
            }
        } catch (error) {
            console.error('Error stopping recording:', error);
            this.ui.setStatus('Error processing audio', 'default');
            this.ui.showToast('Error processing audio', 'error');
            this.micBtn.classList.remove('recording', 'processing');
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
                    this.ui.setStatus('🤖 Detective Ray is analyzing...', 'processing');
                    this.statementCount++;
                    this.ui.updateStats({ statementCount: this.statementCount });
                }
            };
            reader.readAsDataURL(audioBlob);
        } catch (error) {
            console.error('Error sending audio:', error);
            this.micBtn.classList.remove('processing');
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
            this.ui.setStatus('🤖 Detective Ray is responding...', 'processing');
            this.statementCount++;
            this.ui.updateStats({ statementCount: this.statementCount });
        }
    }
    
    displayMessage(text, speaker) {
        if (this.chatTranscript.querySelector('.empty-state')) {
            this.chatTranscript.innerHTML = '';
        }
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${speaker}`;
        
        const label = document.createElement('strong');
        label.textContent = speaker === 'user' ? 'You' : 
                           speaker === 'agent' ? 'Detective Ray' : 
                           'System';
        
        const textNode = document.createTextNode(text);
        
        messageDiv.appendChild(label);
        messageDiv.appendChild(textNode);
        
        this.chatTranscript.appendChild(messageDiv);
        this.chatTranscript.scrollTop = this.chatTranscript.scrollHeight;
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
    
    updateScene(data) {
        // Show scene controls when scene is present
        this.ui.showSceneControls();
        
        // Update scene image
        if (data.image_url) {
            this.sceneDisplay.innerHTML = `
                <img src="${data.image_url}" 
                     alt="Scene reconstruction version ${data.version || this.currentVersion + 1}" 
                     class="scene-image"
                     id="scene-image">
            `;
            
            // Enable scene controls after image loads
            const img = this.sceneDisplay.querySelector('img');
            img.onload = () => {
                this.ui.setLoadingScene(false);
                this.micBtn.classList.remove('processing');
            };
        }
        
        // Update description
        if (data.description) {
            this.sceneDescription.innerHTML = `<p>${data.description}</p>`;
        }
        
        // Add to timeline
        this.currentVersion = data.version || this.currentVersion + 1;
        this.addTimelineVersion(data);
        
        // Update stats
        this.ui.updateStats({ versionCount: this.currentVersion });
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
            const response = await fetch('/api/sessions');
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
            const response = await fetch(`/api/sessions/${sessionId}`);
            if (!response.ok) throw new Error('Failed to load session');
            
            const session = await response.json();
            this.sessionId = session.id;
            this.sessionIdEl.textContent = `Session: ${session.id.substring(0, 8)}...`;
            
            // TODO: Load session data into UI
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
            const response = await fetch(`/api/sessions/${sessionId}`, {
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
        const img = document.getElementById('scene-image');
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
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new WitnessReplayApp();
});
