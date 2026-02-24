/**
 * Voice Activity Detection (VAD) Module
 * Uses Web Audio API to detect speech and automatically control recording
 */

class VoiceActivityDetector {
    constructor(options = {}) {
        // Configuration with defaults
        this.config = {
            // Minimum RMS threshold to consider as voice (0-1 scale)
            sensitivity: options.sensitivity ?? 0.015,
            // Seconds of silence before stopping recording
            silenceThreshold: options.silenceThreshold ?? 2.0,
            // Minimum seconds of speech before considering it valid
            minSpeechDuration: options.minSpeechDuration ?? 0.3,
            // How often to check audio levels (ms)
            checkInterval: options.checkInterval ?? 50,
            // Smoothing factor for RMS (0-1, higher = more smoothing)
            smoothingFactor: options.smoothingFactor ?? 0.8,
        };
        
        this.audioContext = null;
        this.analyser = null;
        this.dataArray = null;
        this.source = null;
        this.checkIntervalId = null;
        this.stream = null;
        
        // State tracking
        this.isListening = false;
        this.isSpeechDetected = false;
        this.lastSpeechTime = 0;
        this.speechStartTime = 0;
        this.smoothedRMS = 0;
        
        // Callbacks
        this.onSpeechStart = options.onSpeechStart || (() => {});
        this.onSpeechEnd = options.onSpeechEnd || (() => {});
        this.onVolumeChange = options.onVolumeChange || (() => {});
    }
    
    /**
     * Start listening to the microphone for voice activity
     */
    async start() {
        if (this.isListening) return;
        
        try {
            // Get microphone stream
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });
            
            // Create audio context and analyser
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 2048;
            this.analyser.smoothingTimeConstant = 0.3;
            
            // Connect source to analyser
            this.source = this.audioContext.createMediaStreamSource(this.stream);
            this.source.connect(this.analyser);
            
            // Create data array for frequency data
            this.dataArray = new Float32Array(this.analyser.fftSize);
            
            // Reset state
            this.isListening = true;
            this.isSpeechDetected = false;
            this.lastSpeechTime = 0;
            this.speechStartTime = 0;
            this.smoothedRMS = 0;
            
            // Start checking for voice activity
            this.checkIntervalId = setInterval(() => this.checkVoiceActivity(), this.config.checkInterval);
            
            console.debug('[VAD] Started listening for voice activity');
            return true;
        } catch (error) {
            console.error('[VAD] Error starting:', error);
            throw error;
        }
    }
    
    /**
     * Stop listening and clean up resources
     */
    stop() {
        if (!this.isListening) return;
        
        this.isListening = false;
        
        if (this.checkIntervalId) {
            clearInterval(this.checkIntervalId);
            this.checkIntervalId = null;
        }
        
        if (this.source) {
            this.source.disconnect();
            this.source = null;
        }
        
        if (this.audioContext && this.audioContext.state !== 'closed') {
            this.audioContext.close();
            this.audioContext = null;
        }
        
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
        
        this.analyser = null;
        this.dataArray = null;
        
        console.debug('[VAD] Stopped listening');
    }
    
    /**
     * Check current audio levels for voice activity
     */
    checkVoiceActivity() {
        if (!this.analyser || !this.dataArray) return;
        
        // Get time-domain data
        this.analyser.getFloatTimeDomainData(this.dataArray);
        
        // Calculate RMS (Root Mean Square) for volume level
        let sum = 0;
        for (let i = 0; i < this.dataArray.length; i++) {
            sum += this.dataArray[i] * this.dataArray[i];
        }
        const rms = Math.sqrt(sum / this.dataArray.length);
        
        // Apply exponential smoothing
        this.smoothedRMS = this.config.smoothingFactor * this.smoothedRMS + 
                          (1 - this.config.smoothingFactor) * rms;
        
        // Notify volume change
        this.onVolumeChange(this.smoothedRMS, rms);
        
        const now = Date.now();
        const isVoice = this.smoothedRMS > this.config.sensitivity;
        
        if (isVoice) {
            this.lastSpeechTime = now;
            
            if (!this.isSpeechDetected) {
                // Speech just started
                this.speechStartTime = now;
                this.isSpeechDetected = true;
                
                // Only trigger callback if speech is longer than minimum duration
                // (callback will be triggered on continued speech)
            } else if (now - this.speechStartTime >= this.config.minSpeechDuration * 1000) {
                // Speech has been going on long enough
                if (this.speechStartTime > 0) {
                    this.onSpeechStart();
                    this.speechStartTime = 0; // Mark that we've triggered
                }
            }
        } else if (this.isSpeechDetected) {
            // Check if silence has lasted long enough
            const silenceDuration = (now - this.lastSpeechTime) / 1000;
            
            if (silenceDuration >= this.config.silenceThreshold) {
                this.isSpeechDetected = false;
                this.onSpeechEnd(silenceDuration);
            }
        }
    }
    
    /**
     * Get current audio stream for recording
     */
    getStream() {
        return this.stream;
    }
    
    /**
     * Update sensitivity setting
     */
    setSensitivity(value) {
        this.config.sensitivity = Math.max(0.001, Math.min(0.1, value));
        console.debug('[VAD] Sensitivity set to:', this.config.sensitivity);
    }
    
    /**
     * Update silence threshold setting
     */
    setSilenceThreshold(seconds) {
        this.config.silenceThreshold = Math.max(0.5, Math.min(10, seconds));
        console.debug('[VAD] Silence threshold set to:', this.config.silenceThreshold);
    }
    
    /**
     * Get current configuration
     */
    getConfig() {
        return { ...this.config };
    }
    
    /**
     * Check if currently detecting speech
     */
    isDetectingSpeech() {
        return this.isSpeechDetected;
    }
    
    /**
     * Get current volume level (0-1)
     */
    getCurrentVolume() {
        return Math.min(1, this.smoothedRMS * 20); // Scale for visualization
    }
}

// Export to global scope
window.VoiceActivityDetector = VoiceActivityDetector;
