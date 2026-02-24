/**
 * Audio Recording Module
 * Handles microphone access and audio recording using MediaRecorder API
 */

class AudioRecorder {
    constructor() {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.stream = null;
        this.isRecording = false;
    }
    
    async start() {
        try {
            // Request microphone access
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    sampleRate: 44100
                }
            });
            
            // Create MediaRecorder
            const mimeType = this.getSupportedMimeType();
            this.mediaRecorder = new MediaRecorder(this.stream, {
                mimeType: mimeType
            });
            
            this.audioChunks = [];
            
            // Handle data available
            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };
            
            // Start recording
            this.mediaRecorder.start(100); // Collect data every 100ms
            this.isRecording = true;
            
            // Return the stream for quality analysis
            return this.stream;
            
        } catch (error) {
            console.error('Error accessing microphone:', error);
            throw error;
        }
    }
    
    getStream() {
        return this.stream;
    }
    
    async stop() {
        return new Promise((resolve, reject) => {
            if (!this.mediaRecorder || !this.isRecording) {
                reject(new Error('Not recording'));
                return;
            }
            
            this.mediaRecorder.onstop = () => {
                // Create blob from chunks
                const mimeType = this.mediaRecorder.mimeType;
                const audioBlob = new Blob(this.audioChunks, {type: mimeType});
                
                // Stop all tracks
                if (this.stream) {
                    this.stream.getTracks().forEach(track => track.stop());
                }
                
                this.isRecording = false;
                
                resolve(audioBlob);
            };
            
            this.mediaRecorder.stop();
        });
    }
    
    getSupportedMimeType() {
        // Try different mime types in order of preference
        const types = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/ogg;codecs=opus',
            'audio/mp4',
            'audio/wav'
        ];
        
        for (const type of types) {
            if (MediaRecorder.isTypeSupported(type)) {
                return type;
            }
        }
        
        return 'audio/webm'; // Fallback
    }
    
    isSupported() {
        return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    }
}

// Audio Visualizer (enhanced with circular waveform)
class EnhancedAudioVisualizer {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.canvasContext = this.canvas ? this.canvas.getContext('2d') : null;
        this.audioContext = null;
        this.analyser = null;
        this.dataArray = null;
        this.animationId = null;
        this.isActive = false;
    }
    
    start(stream) {
        if (!this.canvas || !stream) return;
        
        this.canvas.classList.add('active');
        this.isActive = true;
        
        this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        this.analyser = this.audioContext.createAnalyser();
        
        const source = this.audioContext.createMediaStreamSource(stream);
        source.connect(this.analyser);
        
        this.analyser.fftSize = 256;
        const bufferLength = this.analyser.frequencyBinCount;
        this.dataArray = new Uint8Array(bufferLength);
        
        this.draw();
    }
    
    draw() {
        if (!this.isActive || !this.analyser || !this.canvasContext) return;
        
        this.animationId = requestAnimationFrame(() => this.draw());
        
        this.analyser.getByteFrequencyData(this.dataArray);
        
        const { width, height } = this.canvas;
        const centerX = width / 2;
        const centerY = height / 2;
        const radius = 50;
        
        // Clear canvas
        this.canvasContext.fillStyle = 'rgba(10, 10, 15, 0.3)';
        this.canvasContext.fillRect(0, 0, width, height);
        
        // Draw circular waveform
        const barCount = this.dataArray.length / 2;
        const angleStep = (Math.PI * 2) / barCount;
        
        this.canvasContext.strokeStyle = '#00d4ff';
        this.canvasContext.lineWidth = 3;
        this.canvasContext.shadowBlur = 10;
        this.canvasContext.shadowColor = '#00d4ff';
        
        this.canvasContext.beginPath();
        
        for (let i = 0; i < barCount; i++) {
            const value = this.dataArray[i];
            const amplitude = (value / 255) * 30;
            const angle = i * angleStep;
            
            const x = centerX + Math.cos(angle) * (radius + amplitude);
            const y = centerY + Math.sin(angle) * (radius + amplitude);
            
            if (i === 0) {
                this.canvasContext.moveTo(x, y);
            } else {
                this.canvasContext.lineTo(x, y);
            }
        }
        
        this.canvasContext.closePath();
        this.canvasContext.stroke();
        
        // Draw center circle
        this.canvasContext.beginPath();
        this.canvasContext.arc(centerX, centerY, radius - 5, 0, Math.PI * 2);
        this.canvasContext.strokeStyle = 'rgba(0, 212, 255, 0.3)';
        this.canvasContext.lineWidth = 1;
        this.canvasContext.stroke();
    }
    
    stop() {
        this.isActive = false;
        
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
        }
        if (this.audioContext) {
            this.audioContext.close();
        }
        if (this.canvas) {
            this.canvas.classList.remove('active');
            
            // Clear canvas
            if (this.canvasContext) {
                this.canvasContext.clearRect(0, 0, this.canvas.width, this.canvas.height);
            }
        }
    }
}

/**
 * TTS Player Module
 * Handles text-to-speech playback for AI responses (accessibility feature)
 */
class TTSPlayer {
    constructor() {
        this.audioContext = null;
        this.currentSource = null;
        this.isPlaying = false;
        this.enabled = localStorage.getItem('ttsEnabled') === 'true';
        this.voice = localStorage.getItem('ttsVoice') || 'Puck';
        this.availableVoices = [];
        this.queue = [];
        this.isProcessing = false;
        
        // Voice conversation callbacks
        this.onPlaybackStart = null;
        this.onPlaybackEnd = null;
        
        // Fetch available voices on init
        this.fetchVoices();
    }
    
    async fetchVoices() {
        try {
            const response = await fetch('/api/tts/voices');
            if (response.ok) {
                const data = await response.json();
                this.availableVoices = data.voices || [];
            }
        } catch (error) {
            console.warn('Could not fetch TTS voices:', error);
        }
    }
    
    setEnabled(enabled) {
        this.enabled = enabled;
        localStorage.setItem('ttsEnabled', enabled.toString());
    }
    
    isEnabled() {
        return this.enabled;
    }
    
    setVoice(voice) {
        this.voice = voice;
        localStorage.setItem('ttsVoice', voice);
    }
    
    getVoice() {
        return this.voice;
    }
    
    getAvailableVoices() {
        return this.availableVoices;
    }
    
    /**
     * Speak text using TTS API
     * @param {string} text - Text to speak
     * @param {boolean} immediate - If true, interrupt current playback
     */
    async speak(text, immediate = false) {
        if (!this.enabled || !text || !text.trim()) {
            return;
        }
        
        // Clean text for TTS (remove emojis, special formatting)
        const cleanText = this._cleanTextForTTS(text);
        if (!cleanText) return;
        
        if (immediate) {
            this.stop();
            this.queue = [];
        }
        
        this.queue.push(cleanText);
        this._processQueue();
    }
    
    async _processQueue() {
        if (this.isProcessing || this.queue.length === 0) {
            return;
        }
        
        this.isProcessing = true;
        if (this.onPlaybackStart) this.onPlaybackStart();
        
        while (this.queue.length > 0) {
            const text = this.queue.shift();
            try {
                await this._playText(text);
            } catch (error) {
                console.error('TTS playback error:', error);
            }
        }
        
        this.isProcessing = false;
        if (this.onPlaybackEnd) this.onPlaybackEnd();
    }
    
    async _playText(text) {
        try {
            const response = await fetch('/api/tts/generate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    text: text,
                    voice: this.voice,
                }),
            });
            
            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || `TTS API error: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.audio_base64) {
                await this._playAudioBase64(data.audio_base64, data.mime_type);
            }
        } catch (error) {
            console.error('TTS generation failed:', error);
            // Show user-friendly message for quota errors
            if (error.message.includes('429') || error.message.includes('quota')) {
                console.warn('TTS quota reached, speech disabled temporarily');
            }
        }
    }
    
    async _playAudioBase64(base64Data, mimeType = 'audio/wav') {
        return new Promise((resolve, reject) => {
            try {
                // Create audio context if needed
                if (!this.audioContext) {
                    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
                }
                
                // Resume audio context if suspended (browser autoplay policy)
                if (this.audioContext.state === 'suspended') {
                    this.audioContext.resume();
                }
                
                // Decode base64 to array buffer
                const binaryString = atob(base64Data);
                const bytes = new Uint8Array(binaryString.length);
                for (let i = 0; i < binaryString.length; i++) {
                    bytes[i] = binaryString.charCodeAt(i);
                }
                
                // Decode audio data
                this.audioContext.decodeAudioData(
                    bytes.buffer,
                    (audioBuffer) => {
                        // Stop any current playback
                        if (this.currentSource) {
                            try {
                                this.currentSource.stop();
                            } catch (e) {}
                        }
                        
                        // Create and play buffer source
                        this.currentSource = this.audioContext.createBufferSource();
                        this.currentSource.buffer = audioBuffer;
                        this.currentSource.connect(this.audioContext.destination);
                        
                        this.isPlaying = true;
                        
                        this.currentSource.onended = () => {
                            this.isPlaying = false;
                            this.currentSource = null;
                            resolve();
                        };
                        
                        this.currentSource.start(0);
                    },
                    (error) => {
                        console.error('Audio decode error:', error);
                        reject(error);
                    }
                );
            } catch (error) {
                reject(error);
            }
        });
    }
    
    _cleanTextForTTS(text) {
        if (!text) return '';
        
        // Remove emojis
        let clean = text.replace(/[\u{1F600}-\u{1F64F}]/gu, '');
        clean = clean.replace(/[\u{1F300}-\u{1F5FF}]/gu, '');
        clean = clean.replace(/[\u{1F680}-\u{1F6FF}]/gu, '');
        clean = clean.replace(/[\u{1F1E0}-\u{1F1FF}]/gu, '');
        clean = clean.replace(/[\u{2600}-\u{26FF}]/gu, '');
        clean = clean.replace(/[\u{2700}-\u{27BF}]/gu, '');
        
        // Remove markdown-style formatting
        clean = clean.replace(/\*\*(.*?)\*\*/g, '$1');
        clean = clean.replace(/__(.*?)__/g, '$1');
        clean = clean.replace(/\*(.*?)\*/g, '$1');
        clean = clean.replace(/_(.*?)_/g, '$1');
        
        // Remove multiple spaces/newlines
        clean = clean.replace(/\s+/g, ' ');
        
        return clean.trim();
    }
    
    stop() {
        if (this.currentSource) {
            try {
                this.currentSource.stop();
            } catch (e) {}
            this.currentSource = null;
        }
        this.isPlaying = false;
    }
    
    isCurrentlyPlaying() {
        return this.isPlaying;
    }
}

// Export to global scope
window.AudioRecorder = AudioRecorder;
window.EnhancedAudioVisualizer = EnhancedAudioVisualizer;
window.TTSPlayer = TTSPlayer;
