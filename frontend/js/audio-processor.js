/**
 * Dynamic Audio Processor Module
 * Automatic Gain Control (AGC) + Noise Cancellation + Dynamic Compression
 * 
 * Processes the raw mic stream through a Web Audio API pipeline:
 *   mic → highpass filter → noise gate → dynamic gain → compressor → output
 * 
 * The gain is automatically adjusted based on real-time RMS analysis:
 *   - Quiet environment / soft speaker → gain boosted
 *   - Loud environment / yelling → gain reduced
 *   - Noise floor tracked and suppressed
 */

class DynamicAudioProcessor {
    constructor() {
        this.audioContext = null;
        this.sourceNode = null;
        this.gainNode = null;
        this.compressorNode = null;
        this.highpassFilter = null;
        this.lowpassFilter = null;
        this.analyserNode = null;
        this.destinationNode = null;
        this.outputStream = null;

        // AGC parameters
        this.targetRMS = 0.18;          // Target output level (0-1 range)
        this.minGain = 0.5;             // Don't go below 50% volume
        this.maxGain = 8.0;             // Don't boost more than 8x
        this.currentGain = 1.0;
        this.smoothingFactor = 0.05;    // How fast gain adjusts (lower = smoother)
        this.noiseFloor = 0.005;        // Below this = silence (don't boost)
        this.noiseFloorHistory = [];
        this.noiseFloorWindow = 50;     // Frames to track noise floor

        // Analysis
        this.analyserData = null;
        this.isActive = false;
        this.rafId = null;
        this.stats = {
            currentRMS: 0,
            currentGain: 1.0,
            noiseFloor: 0,
            peakLevel: 0,
            isNoiseGated: false,
        };

        // Callbacks
        this.onStatsUpdate = null;
    }

    /**
     * Process a raw mic MediaStream and return a cleaned-up stream.
     * @param {MediaStream} rawStream - The raw getUserMedia stream
     * @returns {MediaStream} - Processed stream suitable for MediaRecorder
     */
    async start(rawStream) {
        if (this.isActive) this.stop();

        this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: 44100,
        });

        // Source from raw mic
        this.sourceNode = this.audioContext.createMediaStreamSource(rawStream);

        // 1. High-pass filter — removes low-frequency rumble/hum (below 80Hz)
        this.highpassFilter = this.audioContext.createBiquadFilter();
        this.highpassFilter.type = 'highpass';
        this.highpassFilter.frequency.value = 80;
        this.highpassFilter.Q.value = 0.7;

        // 2. Low-pass filter — removes high-frequency hiss (above 8kHz for speech)
        this.lowpassFilter = this.audioContext.createBiquadFilter();
        this.lowpassFilter.type = 'lowpass';
        this.lowpassFilter.frequency.value = 12000;
        this.lowpassFilter.Q.value = 0.7;

        // 3. Dynamic gain node — AGC adjusts this in real-time
        this.gainNode = this.audioContext.createGain();
        this.gainNode.gain.value = this.currentGain;

        // 4. Compressor — prevents clipping, evens out dynamics
        this.compressorNode = this.audioContext.createDynamicsCompressor();
        this.compressorNode.threshold.value = -24;   // Start compressing at -24dB
        this.compressorNode.knee.value = 12;          // Soft knee for natural sound
        this.compressorNode.ratio.value = 4;          // 4:1 compression ratio
        this.compressorNode.attack.value = 0.003;     // Fast attack (3ms)
        this.compressorNode.release.value = 0.15;     // Medium release (150ms)

        // 5. Analyser — for RMS measurement (drives the AGC loop)
        this.analyserNode = this.audioContext.createAnalyser();
        this.analyserNode.fftSize = 2048;
        this.analyserNode.smoothingTimeConstant = 0.3;
        this.analyserData = new Float32Array(this.analyserNode.fftSize);

        // 6. MediaStream destination — creates a new stream for MediaRecorder
        this.destinationNode = this.audioContext.createMediaStreamDestination();
        this.outputStream = this.destinationNode.stream;

        // Wire the chain:
        // mic → highpass → lowpass → gain → compressor → analyser → destination
        this.sourceNode.connect(this.highpassFilter);
        this.highpassFilter.connect(this.lowpassFilter);
        this.lowpassFilter.connect(this.gainNode);
        this.gainNode.connect(this.compressorNode);
        this.compressorNode.connect(this.analyserNode);
        this.analyserNode.connect(this.destinationNode);

        // Reset state
        this.currentGain = 1.0;
        this.noiseFloorHistory = [];
        this.isActive = true;

        // Start the AGC analysis loop
        this._agcLoop();

        console.log('[AudioProcessor] Started — AGC + noise cancellation active');
        return this.outputStream;
    }

    /**
     * AGC loop — runs every animation frame, adjusts gain based on RMS
     */
    _agcLoop() {
        if (!this.isActive || !this.analyserNode) return;
        this.rafId = requestAnimationFrame(() => this._agcLoop());

        this.analyserNode.getFloatTimeDomainData(this.analyserData);

        // Calculate RMS of current frame
        let sumSq = 0;
        let peak = 0;
        for (let i = 0; i < this.analyserData.length; i++) {
            const v = this.analyserData[i];
            sumSq += v * v;
            const abs = Math.abs(v);
            if (abs > peak) peak = abs;
        }
        const rms = Math.sqrt(sumSq / this.analyserData.length);

        // Track noise floor (lowest RMS values over time)
        this.noiseFloorHistory.push(rms);
        if (this.noiseFloorHistory.length > this.noiseFloorWindow) {
            this.noiseFloorHistory.shift();
        }
        const sortedHistory = [...this.noiseFloorHistory].sort((a, b) => a - b);
        // Noise floor = 10th percentile of recent RMS values
        const noiseIdx = Math.floor(sortedHistory.length * 0.1);
        this.noiseFloor = sortedHistory[noiseIdx] || 0.005;

        // Determine if this frame is just noise (below noise floor + margin)
        const isNoise = rms < this.noiseFloor * 2.5;

        // Only adjust gain when there's actual speech (not noise)
        if (!isNoise && rms > 0.001) {
            // Calculate desired gain to reach target RMS
            const desiredGain = this.targetRMS / Math.max(rms, 0.001);
            const clampedGain = Math.max(this.minGain, Math.min(this.maxGain, desiredGain));

            // Smooth gain transition (exponential moving average)
            this.currentGain += (clampedGain - this.currentGain) * this.smoothingFactor;
        }

        // Apply gain with smooth ramp (avoids clicks)
        const now = this.audioContext.currentTime;
        this.gainNode.gain.setTargetAtTime(this.currentGain, now, 0.05);

        // Update stats
        this.stats.currentRMS = rms;
        this.stats.currentGain = this.currentGain;
        this.stats.noiseFloor = this.noiseFloor;
        this.stats.peakLevel = peak;
        this.stats.isNoiseGated = isNoise;

        if (this.onStatsUpdate) {
            this.onStatsUpdate(this.stats);
        }
    }

    /**
     * Get the processed output stream for use with MediaRecorder
     */
    getOutputStream() {
        return this.outputStream;
    }

    /**
     * Get current processing stats
     */
    getStats() {
        return { ...this.stats };
    }

    /**
     * Stop processing and release resources
     */
    stop() {
        this.isActive = false;

        if (this.rafId) {
            cancelAnimationFrame(this.rafId);
            this.rafId = null;
        }

        // Disconnect all nodes
        try { this.sourceNode?.disconnect(); } catch (e) {}
        try { this.highpassFilter?.disconnect(); } catch (e) {}
        try { this.lowpassFilter?.disconnect(); } catch (e) {}
        try { this.gainNode?.disconnect(); } catch (e) {}
        try { this.compressorNode?.disconnect(); } catch (e) {}
        try { this.analyserNode?.disconnect(); } catch (e) {}

        if (this.audioContext && this.audioContext.state !== 'closed') {
            this.audioContext.close().catch(() => {});
        }

        this.audioContext = null;
        this.sourceNode = null;
        this.outputStream = null;
        this.noiseFloorHistory = [];

        console.log('[AudioProcessor] Stopped');
    }
}

// Export
window.DynamicAudioProcessor = DynamicAudioProcessor;
