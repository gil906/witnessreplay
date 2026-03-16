/**
 * Audio Recording Module
 * Handles microphone access and audio recording using MediaRecorder API
 */

class AudioRecorder {
    constructor() {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.stream = null;          // raw mic stream
        this.processedStream = null; // after AGC + noise cancellation
        this.processor = null;       // DynamicAudioProcessor instance
        this.isRecording = false;
        this.stopPromise = null;
        this.mimeType = 'audio/webm';
    }
    
    async start() {
        try {
            if (this.isRecording && this.stream) {
                return this.stream;
            }

            // Request microphone access (raw stream)
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    channelCount: 1,
                    sampleRate: 48000
                }
            });
            
            // Apply dynamic audio processing (AGC + noise cancellation)
            if (window.DynamicAudioProcessor) {
                this.processor = new DynamicAudioProcessor();
                this.processedStream = await this.processor.start(this.stream);
            } else {
                this.processedStream = this.stream;
            }
            
            // Create MediaRecorder on the PROCESSED stream
            const mimeType = this.getSupportedMimeType();
            this.mimeType = mimeType;
            this.mediaRecorder = new MediaRecorder(this.processedStream, {
                mimeType: mimeType
            });
            
            this.audioChunks = [];
            this.stopPromise = null;
            
            // Handle data available
            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };
            
            // Start recording
            this.mediaRecorder.start(100); // Collect data every 100ms
            this.isRecording = true;
            
            // Return the RAW stream for quality visualization (green bar)
            return this.stream;
            
        } catch (error) {
            console.error('Error accessing microphone:', error);
            throw error;
        }
    }
    
    getStream() {
        return this.stream;
    }

    _cleanupMediaResources() {
        if (this.processor) {
            this.processor.stop();
            this.processor = null;
        }

        if (this.processedStream && this.processedStream !== this.stream) {
            this.processedStream.getTracks().forEach(track => track.stop());
        }

        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
        }

        this.stream = null;
        this.processedStream = null;
        this.mediaRecorder = null;
        this.isRecording = false;
        this.stopPromise = null;
    }
    
    async stop() {
        if (this.stopPromise) {
            return this.stopPromise;
        }

        const recorder = this.mediaRecorder;
        if (!recorder || (!this.isRecording && recorder.state === 'inactive')) {
            throw new Error('Not recording');
        }

        this.stopPromise = new Promise((resolve, reject) => {
            let settled = false;

            const finish = (callback) => {
                if (settled) return;
                settled = true;
                try {
                    callback();
                } finally {
                    recorder.onstop = null;
                    recorder.onerror = null;
                }
            };

            recorder.onstop = () => finish(() => {
                try {
                    const finalMimeType = recorder.mimeType || this.mimeType || this.getSupportedMimeType();
                    const audioBlob = new Blob(this.audioChunks, { type: finalMimeType });
                    this._cleanupMediaResources();
                    resolve(audioBlob);
                } catch (error) {
                    this._cleanupMediaResources();
                    reject(error);
                }
            });

            recorder.onerror = (event) => finish(() => {
                const error = event?.error || new Error('MediaRecorder error');
                this._cleanupMediaResources();
                reject(error);
            });

            try {
                if (recorder.state === 'recording') {
                    recorder.requestData();
                }
            } catch (error) {
                console.debug('AudioRecorder requestData failed before stop:', error);
            }

            setTimeout(() => {
                try {
                    if (recorder.state !== 'inactive') {
                        recorder.stop();
                    } else {
                        recorder.onstop?.();
                    }
                } catch (error) {
                    recorder.onerror?.({ error });
                }
            }, 60);
        });

        return this.stopPromise;
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
        if (this.audioContext && this.audioContext.state !== 'closed') {
            this.audioContext.close().catch(() => {});
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
        this.currentUtterance = null;
        this.isPlaying = false;
        this._storageOk = this._storageAvailable();
        const savedEnabled = this._readStorage('ttsEnabled');
        // Voice-first app — TTS enabled by default on ALL devices
        this.enabled = savedEnabled === null ? true : savedEnabled === 'true';
        if (savedEnabled === null) {
            this._writeStorage('ttsEnabled', 'true');
        }
        this.voice = this._readStorage('ttsVoice') || 'Charon';
        this.playbackSpeed = this._normalizePlaybackSpeed(this._readStorage('ttsPlaybackSpeed'));
        this._writeStorage('ttsPlaybackSpeed', this.playbackSpeed.toString());
        this.availableVoices = [];
        this.queue = [];
        this.isProcessing = false;
        this._playbackCallbackActive = false;
        this.webSpeechSupported = typeof window !== 'undefined'
            && 'speechSynthesis' in window
            && typeof window.SpeechSynthesisUtterance !== 'undefined';
        
        // Voice conversation callbacks
        this.onPlaybackStart = null;
        this.onPlaybackEnd = null;
        this.onPlaybackUnavailable = null;
        this._generationController = null;
        // Keep Detective Ray on the configured Gemini voice during the main
        // conversation. Browser speech remains a last-resort fallback only if
        // generated audio actually fails.
        this.fastStartFallbackMs = 0;
        
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

    _storageAvailable() {
        try {
            if (typeof window === 'undefined' || !window.localStorage) return false;
            const key = '__tts_probe__';
            window.localStorage.setItem(key, '1');
            window.localStorage.removeItem(key);
            return true;
        } catch (_) {
            return false;
        }
    }

    _readStorage(key) {
        if (!this._storageOk) return null;
        try {
            return window.localStorage.getItem(key);
        } catch (_) {
            return null;
        }
    }

    _writeStorage(key, value) {
        if (!this._storageOk) return;
        try {
            window.localStorage.setItem(key, value);
        } catch (_) {}
    }

    _normalizePlaybackSpeed(value) {
        const parsed = Number.parseFloat(value);
        if (!Number.isFinite(parsed)) return 1.0;
        const clamped = Math.max(0.8, Math.min(1.25, parsed));
        return Math.round(clamped * 100) / 100;
    }
    
    setEnabled(enabled) {
        this.enabled = enabled;
        this._writeStorage('ttsEnabled', enabled.toString());
    }
    
    isEnabled() {
        return this.enabled;
    }
    
    setVoice(voice) {
        this.voice = voice;
        this._writeStorage('ttsVoice', voice);
    }
    
    getVoice() {
        return this.voice;
    }

    setPlaybackSpeed(speed) {
        this.playbackSpeed = this._normalizePlaybackSpeed(speed);
        this._writeStorage('ttsPlaybackSpeed', this.playbackSpeed.toString());
    }

    getPlaybackSpeed() {
        return this.playbackSpeed;
    }
    
    getAvailableVoices() {
        return this.availableVoices;
    }

    hasPendingPlayback() {
        return this.isPlaying
            || this.isProcessing
            || this.queue.length > 0
            || !!this.currentSource
            || !!this.currentUtterance
            || !!this._generationController;
    }

    _abortActiveGeneration() {
        if (!this._generationController) return;
        try {
            this._generationController.abort();
        } catch (_) {}
        this._generationController = null;
    }

    async primePlayback() {
        try {
            if (!this.audioContext || this.audioContext.state === 'closed') {
                this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (this.audioContext.state === 'suspended') {
                await this.audioContext.resume();
            }
            if (this.webSpeechSupported && window.speechSynthesis?.getVoices) {
                window.speechSynthesis.getVoices();
            }
            return !!this.audioContext && this.audioContext.state === 'running';
        } catch (error) {
            console.debug('Unable to prime playback:', error);
            return false;
        }
    }
    
    /**
     * Speak text using TTS API
     * @param {string} text - Text to speak
     * @param {boolean} immediate - If true, interrupt current playback
     */
    async speak(text, immediate = false) {
        if (!this.enabled || !text || !text.trim()) {
            return false;
        }
        
        // Clean text for TTS (remove emojis, special formatting)
        const cleanText = this._cleanTextForTTS(text);
        if (!cleanText) return false;
        
        if (immediate) {
            this.interrupt('immediate');
        }

        return new Promise((resolve) => {
            this.queue.push({ text: cleanText, resolve });
            void this._processQueue();
        });
    }
    
    async _processQueue() {
        if (this.isProcessing || this.queue.length === 0) {
            return;
        }
        
        this.isProcessing = true;
        
        while (this.queue.length > 0) {
            const item = this.queue.shift();
            const text = item?.text;
            let result = { played: false, interrupted: false };
            try {
                result = await this._playText(text);
            } catch (error) {
                console.error('TTS playback error:', error);
            } finally {
                item?.resolve?.(result.played);
            }

            if (!result.played && !result.interrupted) {
                this.onPlaybackUnavailable?.(text);
            }
        }
        
        this.isProcessing = false;
        if (this._playbackCallbackActive) {
            this._playbackCallbackActive = false;
            this.onPlaybackEnd?.();
        }
    }

    _notifyPlaybackStart() {
        if (this._playbackCallbackActive) return;
        this._playbackCallbackActive = true;
        this.onPlaybackStart?.();
    }

    async _requestGeneratedAudio(text, signal) {
        const response = await fetch('/api/tts/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                text: text,
                voice: this.voice,
            }),
            signal,
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            const message = error.detail || `TTS API error: ${response.status}`;
            const requestError = new Error(message);
            requestError.status = response.status;
            throw requestError;
        }

        const data = await response.json();
        if (!data.audio_base64) {
            throw new Error('TTS API returned no audio payload');
        }

        return {
            audio_base64: data.audio_base64,
            mime_type: data.mime_type,
        };
    }
    
    async _playText(text) {
        let controller = null;
        try {
            let audioPayload = null;
            if (this.webSpeechSupported && this.fastStartFallbackMs > 0) {
                controller = new AbortController();
                this._generationController = controller;
                const audioRequest = this._requestGeneratedAudio(text, controller.signal);
                audioRequest.catch(() => null);
                audioPayload = await Promise.race([
                    audioRequest,
                    new Promise((resolve) => setTimeout(() => resolve(null), this.fastStartFallbackMs)),
                ]);

                if (!audioPayload) {
                    controller.abort();
                    if (this._generationController === controller) {
                        this._generationController = null;
                    }

                    const fallbackPlayed = await this._playWithWebSpeech(text);
                    if (fallbackPlayed) {
                        return { played: true, interrupted: false };
                    }

                    controller = new AbortController();
                    this._generationController = controller;
                    audioPayload = await this._requestGeneratedAudio(text, controller.signal);
                }
            } else {
                controller = new AbortController();
                this._generationController = controller;
                audioPayload = await this._requestGeneratedAudio(text, controller.signal);
            }

            if (this._generationController === controller) {
                this._generationController = null;
            }

            await this._playAudioBase64(audioPayload.audio_base64, audioPayload.mime_type);
            return { played: true, interrupted: false };
        } catch (error) {
            if (error?.name === 'AbortError') {
                return { played: false, interrupted: true };
            }
            console.error('TTS generation failed:', error);
            const fallbackPlayed = await this._playWithWebSpeech(text);
            if (!fallbackPlayed && (String(error.message || '').includes('429') || String(error.message || '').toLowerCase().includes('quota'))) {
                console.warn('TTS quota reached and browser speech fallback unavailable');
            }
            return { played: fallbackPlayed, interrupted: false };
        } finally {
            if (this._generationController === controller) {
                this._generationController = null;
            }
        }
    }
    
    async _playAudioBase64(base64Data, mimeType = 'audio/wav') {
        // Create audio context if needed (or recreate if closed)
        if (!this.audioContext || this.audioContext.state === 'closed') {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        
        // Resume audio context if suspended (browser autoplay policy) — retry up to 3 times
        if (this.audioContext.state === 'suspended') {
            for (let attempt = 0; attempt < 3; attempt++) {
                try {
                    await this.audioContext.resume();
                    if (this.audioContext.state === 'running') break;
                } catch (e) {
                    if (attempt === 2) console.warn('AudioContext resume failed after retries');
                }
                await new Promise(r => setTimeout(r, 100 * (attempt + 1)));
            }
        }

        if (this.audioContext.state !== 'running') {
            throw new Error('Audio playback blocked until the browser allows audio output');
        }
        
        return new Promise((resolve, reject) => {
            let settled = false;
            let playbackTimeout = null;

            const finish = (callback) => {
                if (settled) return;
                settled = true;
                if (playbackTimeout) {
                    clearTimeout(playbackTimeout);
                    playbackTimeout = null;
                }
                callback();
            };

            try {
                
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
                        this.currentSource.playbackRate.value = this.playbackSpeed;
                        this.currentSource.connect(this.audioContext.destination);
                        
                        this.isPlaying = true;
                        this.currentSource.onended = () => finish(() => {
                            this.isPlaying = false;
                            this.currentSource = null;
                            resolve(true);
                        });

                        const timeoutMs = Math.max(
                            5000,
                            Math.round((audioBuffer.duration / Math.max(this.playbackSpeed, 0.1)) * 1000) + 3000,
                        );
                        playbackTimeout = setTimeout(() => finish(() => {
                            try {
                                this.currentSource?.stop();
                            } catch (_) {}
                            this.isPlaying = false;
                            this.currentSource = null;
                            reject(new Error('Audio playback timed out before finishing'));
                        }), timeoutMs);

                        try {
                            this.currentSource.start(0);
                            this._notifyPlaybackStart();
                        } catch (error) {
                            finish(() => {
                                this.isPlaying = false;
                                this.currentSource = null;
                                reject(error);
                            });
                        }
                    },
                    (error) => {
                        console.error('Audio decode error:', error);
                        finish(() => reject(error));
                    }
                );
            } catch (error) {
                finish(() => reject(error));
            }
        });
    }

    async _playWithWebSpeech(text) {
        if (!this.webSpeechSupported || !text) return false;
        return new Promise((resolve) => {
            let settled = false;
            let speechTimeout = null;

            const finish = (played) => {
                if (settled) return;
                settled = true;
                if (speechTimeout) {
                    clearTimeout(speechTimeout);
                    speechTimeout = null;
                }
                this.isPlaying = false;
                this.currentUtterance = null;
                resolve(played);
            };

            try {
                const synth = window.speechSynthesis;
                synth.cancel();
                const utterance = new window.SpeechSynthesisUtterance(text);
                utterance.rate = this.playbackSpeed;
                utterance.pitch = 1.0;

                const voices = synth.getVoices ? synth.getVoices() : [];
                const preferredVoice = voices.find((voice) =>
                    this.voice && voice.name && voice.name.toLowerCase().includes(this.voice.toLowerCase())
                );
                if (preferredVoice) {
                    utterance.voice = preferredVoice;
                }

                this.currentUtterance = utterance;
                this.isPlaying = true;
                let started = false;

                utterance.onstart = () => {
                    started = true;
                    this._notifyPlaybackStart();
                };

                utterance.onend = () => {
                    finish(started);
                };
                utterance.onerror = () => {
                    finish(false);
                };

                const estimatedDurationMs = Math.max(
                    5000,
                    Math.min(30000, Math.round((text.length * 65) / Math.max(this.playbackSpeed, 0.1))),
                );
                speechTimeout = setTimeout(() => {
                    try {
                        synth.cancel();
                    } catch (_) {}
                    finish(false);
                }, estimatedDurationMs);

                synth.speak(utterance);
            } catch (error) {
                console.warn('Web Speech fallback failed:', error);
                finish(false);
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
        this._abortActiveGeneration();
        if (this.currentSource) {
            try {
                this.currentSource.stop();
            } catch (e) {}
            this.currentSource = null;
        }
        if (this.webSpeechSupported && window.speechSynthesis) {
            try {
                window.speechSynthesis.cancel();
            } catch (_) {}
        }
        this.currentUtterance = null;
        this.isPlaying = false;
    }

    interrupt(reason = 'user_speaking') {
        while (this.queue.length) {
            const item = this.queue.shift();
            item?.resolve?.(false);
        }
        this.stop();
        this.lastInterruptReason = reason;
    }
    
    isCurrentlyPlaying() {
        return this.isPlaying;
    }
}

// Export to global scope
window.AudioRecorder = AudioRecorder;
window.EnhancedAudioVisualizer = EnhancedAudioVisualizer;
window.TTSPlayer = TTSPlayer;
