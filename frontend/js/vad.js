/**
 * Voice Activity Detection (VAD) Module
 * Uses Web Audio API plus lightweight speech heuristics to distinguish
 * nearby speech from ambient noise before starting a recording.
 */

class VoiceActivityDetector {
    constructor(options = {}) {
        this.config = {
            sensitivity: options.sensitivity ?? 0.018,
            silenceThreshold: options.silenceThreshold ?? 2.2,
            minSpeechDuration: options.minSpeechDuration ?? 0.4,
            checkInterval: options.checkInterval ?? 60,
            smoothingFactor: options.smoothingFactor ?? 0.86,
            calibrationDurationMs: options.calibrationDurationMs ?? 700,
            noiseFloorMargin: options.noiseFloorMargin ?? 2.35,
            minSignalToNoise: options.minSignalToNoise ?? 2.2,
            minPeakLevel: options.minPeakLevel ?? 0.026,
            minSpeechBandRatio: options.minSpeechBandRatio ?? 0.28,
            maxLowBandRatio: options.maxLowBandRatio ?? 0.6,
            startTriggerFrames: options.startTriggerFrames ?? 4,
            endTriggerFrames: options.endTriggerFrames ?? 5,
            rearmDelayMs: options.rearmDelayMs ?? 350,
        };

        this.audioContext = null;
        this.source = null;
        this.stream = null;
        this.checkIntervalId = null;

        this.rawAnalyser = null;
        this.filteredAnalyser = null;
        this.highpassFilter = null;
        this.lowpassFilter = null;
        this.timeDataArray = null;
        this.frequencyDataArray = null;
        this.frequencyBinWidth = 0;

        this.isListening = false;
        this.isSpeechDetected = false;
        this.lastSpeechTime = 0;
        this.lastSpeechEndAt = 0;
        this.listeningStartedAt = 0;
        this.smoothedRMS = 0;
        this.noiseFloor = Math.max(0.0015, this.config.sensitivity * 0.6);
        this.noiseFloorHistory = [];
        this.noiseFloorWindow = 90;
        this.speechFrames = 0;
        this.silenceFrames = 0;

        this.onSpeechStart = options.onSpeechStart || (() => {});
        this.onSpeechEnd = options.onSpeechEnd || (() => {});
        this.onVolumeChange = options.onVolumeChange || (() => {});
    }

    async start() {
        if (this.isListening) return true;

        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    channelCount: 1,
                    sampleRate: 48000,
                }
            });

            this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: 48000,
            });

            this.source = this.audioContext.createMediaStreamSource(this.stream);

            this.rawAnalyser = this.audioContext.createAnalyser();
            this.rawAnalyser.fftSize = 2048;
            this.rawAnalyser.smoothingTimeConstant = 0.2;

            this.highpassFilter = this.audioContext.createBiquadFilter();
            this.highpassFilter.type = 'highpass';
            this.highpassFilter.frequency.value = 120;
            this.highpassFilter.Q.value = 0.7;

            this.lowpassFilter = this.audioContext.createBiquadFilter();
            this.lowpassFilter.type = 'lowpass';
            this.lowpassFilter.frequency.value = 4300;
            this.lowpassFilter.Q.value = 0.8;

            this.filteredAnalyser = this.audioContext.createAnalyser();
            this.filteredAnalyser.fftSize = 2048;
            this.filteredAnalyser.smoothingTimeConstant = 0.2;

            this.source.connect(this.rawAnalyser);
            this.source.connect(this.highpassFilter);
            this.highpassFilter.connect(this.lowpassFilter);
            this.lowpassFilter.connect(this.filteredAnalyser);

            this.timeDataArray = new Float32Array(this.filteredAnalyser.fftSize);
            this.frequencyDataArray = new Uint8Array(this.rawAnalyser.frequencyBinCount);
            this.frequencyBinWidth = (this.audioContext.sampleRate / 2) / this.rawAnalyser.frequencyBinCount;

            if (typeof this.audioContext.resume === 'function' && this.audioContext.state === 'suspended') {
                await this.audioContext.resume().catch(() => {});
            }

            this.isListening = true;
            this.isSpeechDetected = false;
            this.lastSpeechTime = 0;
            this.lastSpeechEndAt = 0;
            this.listeningStartedAt = Date.now();
            this.smoothedRMS = 0;
            this.noiseFloor = Math.max(0.0015, this.config.sensitivity * 0.6);
            this.noiseFloorHistory = [];
            this.speechFrames = 0;
            this.silenceFrames = 0;

            this.checkIntervalId = setInterval(() => this.checkVoiceActivity(), this.config.checkInterval);

            console.debug('[VAD] Started listening for voice activity');
            return true;
        } catch (error) {
            console.error('[VAD] Error starting:', error);
            throw error;
        }
    }

    stop() {
        if (!this.isListening) return;

        this.isListening = false;

        if (this.checkIntervalId) {
            clearInterval(this.checkIntervalId);
            this.checkIntervalId = null;
        }

        try { this.source?.disconnect(); } catch (_) {}
        try { this.rawAnalyser?.disconnect(); } catch (_) {}
        try { this.filteredAnalyser?.disconnect(); } catch (_) {}
        try { this.highpassFilter?.disconnect(); } catch (_) {}
        try { this.lowpassFilter?.disconnect(); } catch (_) {}

        if (this.audioContext && this.audioContext.state !== 'closed') {
            this.audioContext.close().catch(() => {});
        }

        if (this.stream) {
            this.stream.getTracks().forEach((track) => track.stop());
        }

        this.audioContext = null;
        this.source = null;
        this.stream = null;
        this.rawAnalyser = null;
        this.filteredAnalyser = null;
        this.highpassFilter = null;
        this.lowpassFilter = null;
        this.timeDataArray = null;
        this.frequencyDataArray = null;
        this.frequencyBinWidth = 0;
        this.noiseFloorHistory = [];
        this.speechFrames = 0;
        this.silenceFrames = 0;

        console.debug('[VAD] Stopped listening');
    }

    _bandEnergy(minHz, maxHz) {
        if (!this.frequencyDataArray || !this.frequencyDataArray.length || !this.frequencyBinWidth) {
            return 0;
        }

        const start = Math.max(0, Math.floor(minHz / this.frequencyBinWidth));
        const end = Math.min(
            this.frequencyDataArray.length - 1,
            Math.ceil(maxHz / this.frequencyBinWidth)
        );

        let sum = 0;
        for (let i = start; i <= end; i++) {
            sum += this.frequencyDataArray[i];
        }
        return sum;
    }

    _updateNoiseFloor(rms, stats) {
        if (!Number.isFinite(rms) || rms <= 0) return;

        const listeningAge = Date.now() - this.listeningStartedAt;
        const allowCalibrationUpdate = listeningAge <= this.config.calibrationDurationMs;
        const looksLikeAmbient = allowCalibrationUpdate
            || !stats.isSpeechCandidate
            || stats.speechBandRatio < this.config.minSpeechBandRatio
            || stats.lowBandRatio > this.config.maxLowBandRatio
            || stats.peak < this.config.minPeakLevel;

        if (!looksLikeAmbient) return;

        this.noiseFloorHistory.push(Math.max(0.0015, Math.min(rms, 0.08)));
        if (this.noiseFloorHistory.length > this.noiseFloorWindow) {
            this.noiseFloorHistory.shift();
        }

        const sorted = [...this.noiseFloorHistory].sort((a, b) => a - b);
        const percentileIndex = Math.max(0, Math.floor(sorted.length * 0.2) - 1);
        this.noiseFloor = Math.max(0.0015, sorted[percentileIndex] || this.noiseFloor);
    }

    checkVoiceActivity() {
        if (!this.filteredAnalyser || !this.rawAnalyser || !this.timeDataArray || !this.frequencyDataArray) {
            return;
        }

        this.filteredAnalyser.getFloatTimeDomainData(this.timeDataArray);
        this.rawAnalyser.getByteFrequencyData(this.frequencyDataArray);

        let sum = 0;
        let peak = 0;
        for (let i = 0; i < this.timeDataArray.length; i++) {
            const sample = this.timeDataArray[i];
            sum += sample * sample;
            const abs = Math.abs(sample);
            if (abs > peak) peak = abs;
        }
        const rms = Math.sqrt(sum / this.timeDataArray.length);
        this.smoothedRMS = this.smoothedRMS === 0
            ? rms
            : (this.config.smoothingFactor * this.smoothedRMS) + ((1 - this.config.smoothingFactor) * rms);

        const speechEnergy = this._bandEnergy(180, 4200);
        const lowBandEnergy = this._bandEnergy(0, 180);
        const totalEnergy = Math.max(1, this._bandEnergy(0, 6000));
        const speechBandRatio = speechEnergy / totalEnergy;
        const lowBandRatio = lowBandEnergy / totalEnergy;
        const dynamicThreshold = Math.max(this.config.sensitivity, this.noiseFloor * this.config.noiseFloorMargin);
        const signalToNoise = this.smoothedRMS / Math.max(this.noiseFloor, 0.0015);
        const listeningAge = Date.now() - this.listeningStartedAt;

        const isSpeechCandidate = listeningAge >= this.config.calibrationDurationMs
            && this.smoothedRMS >= dynamicThreshold
            && peak >= Math.max(this.config.minPeakLevel, dynamicThreshold * 1.35)
            && signalToNoise >= this.config.minSignalToNoise
            && speechBandRatio >= this.config.minSpeechBandRatio
            && lowBandRatio <= this.config.maxLowBandRatio;

        const stats = {
            peak,
            noiseFloor: this.noiseFloor,
            dynamicThreshold,
            speechBandRatio,
            lowBandRatio,
            signalToNoise,
            isSpeechCandidate,
        };

        this._updateNoiseFloor(rms, stats);
        stats.noiseFloor = this.noiseFloor;
        stats.dynamicThreshold = Math.max(this.config.sensitivity, this.noiseFloor * this.config.noiseFloorMargin);
        this.onVolumeChange(this.smoothedRMS, rms, stats);

        const now = Date.now();
        const minSpeechFrames = Math.max(
            this.config.startTriggerFrames,
            Math.ceil((this.config.minSpeechDuration * 1000) / this.config.checkInterval)
        );

        if (isSpeechCandidate) {
            this.lastSpeechTime = now;
            this.speechFrames += 1;
            this.silenceFrames = 0;

            if (
                !this.isSpeechDetected
                && now - this.lastSpeechEndAt >= this.config.rearmDelayMs
                && this.speechFrames >= minSpeechFrames
            ) {
                this.isSpeechDetected = true;
                this.onSpeechStart();
            }
            return;
        }

        this.speechFrames = 0;
        if (!this.isSpeechDetected) {
            return;
        }

        this.silenceFrames += 1;
        const silenceDuration = (now - this.lastSpeechTime) / 1000;
        if (
            this.silenceFrames >= this.config.endTriggerFrames
            && silenceDuration >= this.config.silenceThreshold
        ) {
            this.isSpeechDetected = false;
            this.silenceFrames = 0;
            this.lastSpeechEndAt = now;
            this.onSpeechEnd(silenceDuration);
        }
    }

    getStream() {
        return this.stream;
    }

    setSensitivity(value) {
        this.config.sensitivity = Math.max(0.001, Math.min(0.1, value));
        console.debug('[VAD] Sensitivity set to:', this.config.sensitivity);
    }

    setSilenceThreshold(seconds) {
        this.config.silenceThreshold = Math.max(0.5, Math.min(10, seconds));
        console.debug('[VAD] Silence threshold set to:', this.config.silenceThreshold);
    }

    getConfig() {
        return { ...this.config };
    }

    isDetectingSpeech() {
        return this.isSpeechDetected;
    }

    getCurrentVolume() {
        return Math.min(1, this.smoothedRMS * 18);
    }
}

window.VoiceActivityDetector = VoiceActivityDetector;
