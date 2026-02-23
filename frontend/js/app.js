/**
 * WitnessReplay - Main Application
 * Handles WebSocket communication, UI updates, and session management
 */

class WitnessReplayApp {
    constructor() {
        this.ws = null;
        this.sessionId = null;
        this.audioRecorder = null;
        this.isRecording = false;
        this.currentVersion = 0;
        
        this.initializeUI();
        this.initializeAudio();
    }
    
    initializeUI() {
        // Get UI elements
        this.micBtn = document.getElementById('mic-btn');
        this.stopBtn = document.getElementById('stop-btn');
        this.sendBtn = document.getElementById('send-btn');
        this.textInput = document.getElementById('text-input');
        this.statusText = document.getElementById('status-text');
        this.sceneDisplay = document.getElementById('scene-display');
        this.sceneDescription = document.getElementById('scene-description');
        this.chatTranscript = document.getElementById('chat-transcript');
        this.timeline = document.getElementById('timeline');
        this.sessionIdEl = document.getElementById('session-id');
        this.newSessionBtn = document.getElementById('new-session-btn');
        
        // Event listeners
        this.micBtn.addEventListener('click', () => this.toggleRecording());
        this.stopBtn.addEventListener('click', () => this.stopRecording());
        this.sendBtn.addEventListener('click', () => this.sendTextMessage());
        this.textInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendTextMessage();
        });
        this.newSessionBtn.addEventListener('click', () => this.createNewSession());
        
        // Start with a new session
        this.createNewSession();
    }
    
    initializeAudio() {
        if (window.AudioRecorder) {
            this.audioRecorder = new AudioRecorder();
        }
    }
    
    async createNewSession() {
        try {
            this.setStatus('Creating session...');
            
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
            
            // Clear UI
            this.chatTranscript.innerHTML = '<p class="empty-state">Conversation will appear here</p>';
            this.timeline.innerHTML = '<p class="empty-state">No versions yet</p>';
            this.currentVersion = 0;
            
            // Connect WebSocket
            this.connectWebSocket();
            
        } catch (error) {
            console.error('Error creating session:', error);
            this.setStatus('Error creating session');
        }
    }
    
    connectWebSocket() {
        if (this.ws) {
            this.ws.close();
        }
        
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/${this.sessionId}`;
        
        this.setStatus('Connecting...');
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.setStatus('Connected - Ready to listen');
            this.micBtn.disabled = false;
            this.textInput.disabled = false;
            this.sendBtn.disabled = false;
        };
        
        this.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            this.handleWebSocketMessage(message);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.setStatus('Connection error');
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket closed');
            this.setStatus('Disconnected');
            this.micBtn.disabled = true;
            this.textInput.disabled = true;
            this.sendBtn.disabled = true;
        };
    }
    
    handleWebSocketMessage(message) {
        console.log('Received message:', message);
        
        switch (message.type) {
            case 'text':
                this.displayMessage(message.data.text, message.data.speaker || 'agent');
                break;
            
            case 'scene_update':
                this.updateScene(message.data);
                break;
            
            case 'status':
                this.setStatus(message.data.message || message.data.status);
                break;
            
            case 'error':
                this.setStatus(`Error: ${message.data.message}`);
                this.displayMessage(`Error: ${message.data.message}`, 'system');
                break;
            
            case 'pong':
                // Heartbeat response
                break;
            
            default:
                console.warn('Unknown message type:', message.type);
        }
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
