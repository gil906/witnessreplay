/**
 * Audio Quality Analyzer Module
 * Uses Web Audio API to analyze audio quality during recording
 * - Volume level detection (too quiet/loud)
 * - Noise level detection
 * - Clipping detection
 */

class AudioQualityAnalyzer {
    constructor() {
        this.audioContext = null;
        this.analyser = null;
        this.source = null;
        this.dataArray = null;
        this.isAnalyzing = false;
        this.animationId = null;
        
        // Quality thresholds
        this.thresholds = {
            volumeMin: 0.05,      // Below this is too quiet
            volumeMax: 0.95,      // Above this risks clipping
            volumeIdeal: 0.3,     // Ideal volume level
            noiseFloor: 0.02,     // Background noise threshold
            clippingThreshold: 0.98  // Clipping detection threshold
        };
        
        // Quality metrics (accumulated during recording)
        this.metrics = this.resetMetrics();
        
        // Current real-time values
        this.currentValues = {
            volume: 0,
            peak: 0,
            noiseLevel: 0,
            isClipping: false
        };
        
        // Callbacks
        this.onQualityUpdate = null;
        this.onWarning = null;
        
        // Warning cooldowns (prevent spam)
        this.lastWarnings = {};
        this.warningCooldown = 3000; // 3 seconds between same warnings
    }
    
    resetMetrics() {
        return {
            avgVolume: 0,
            volumeSamples: 0,
            peakVolume: 0,
            clippingEvents: 0,
            tooQuietSamples: 0,
            tooLoudSamples: 0,
            totalSamples: 0,
            noiseFloorAvg: 0,
            noiseSamples: 0,
            qualityScore: 100,
            startTime: null,
            endTime: null
        };
    }
    
    async start(stream) {
        if (this.isAnalyzing) return;
        
        try {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            this.analyser = this.audioContext.createAnalyser();
            
            // Configure analyser for quality detection
            this.analyser.fftSize = 2048;
            this.analyser.smoothingTimeConstant = 0.3;
            
            this.source = this.audioContext.createMediaStreamSource(stream);
            this.source.connect(this.analyser);
            
            this.dataArray = new Float32Array(this.analyser.fftSize);
            this.metrics = this.resetMetrics();
            this.metrics.startTime = Date.now();
            this.isAnalyzing = true;
            
            this.analyze();
            
        } catch (error) {
            console.error('AudioQualityAnalyzer: Failed to start', error);
        }
    }
    
    analyze() {
        if (!this.isAnalyzing || !this.analyser) return;
        
        this.animationId = requestAnimationFrame(() => this.analyze());
        
        // Get time-domain data for volume analysis
        this.analyser.getFloatTimeDomainData(this.dataArray);
        
        // Calculate RMS volume
        let sum = 0;
        let peak = 0;
        let clippingCount = 0;
        
        for (let i = 0; i < this.dataArray.length; i++) {
            const sample = Math.abs(this.dataArray[i]);
            sum += sample * sample;
            if (sample > peak) peak = sample;
            if (sample >= this.thresholds.clippingThreshold) clippingCount++;
        }
        
        const rms = Math.sqrt(sum / this.dataArray.length);
        const isClipping = clippingCount > 5;
        
        // Update current values
        this.currentValues = {
            volume: rms,
            peak: peak,
            noiseLevel: this.estimateNoiseLevel(rms),
            isClipping: isClipping
        };
        
        // Update metrics
        this.updateMetrics(rms, peak, isClipping);
        
        // Check for warnings
        this.checkWarnings(rms, peak, isClipping);
        
        // Notify quality update
        if (this.onQualityUpdate) {
            this.onQualityUpdate(this.getQualityStatus());
        }
    }
    
    updateMetrics(rms, peak, isClipping) {
        this.metrics.totalSamples++;
        
        // Volume tracking
        this.metrics.avgVolume = 
            (this.metrics.avgVolume * this.metrics.volumeSamples + rms) / 
            (this.metrics.volumeSamples + 1);
        this.metrics.volumeSamples++;
        
        if (peak > this.metrics.peakVolume) {
            this.metrics.peakVolume = peak;
        }
        
        // Issue tracking
        if (isClipping) {
            this.metrics.clippingEvents++;
        }
        
        if (rms < this.thresholds.volumeMin) {
            this.metrics.tooQuietSamples++;
        }
        
        if (rms > this.thresholds.volumeMax) {
            this.metrics.tooLoudSamples++;
        }
        
        // Calculate quality score (0-100)
        this.metrics.qualityScore = this.calculateQualityScore();
    }
    
    estimateNoiseLevel(currentRms) {
        // Simple noise estimation - track minimum RMS over time
        if (currentRms < this.thresholds.volumeMin && currentRms > 0) {
            this.metrics.noiseFloorAvg = 
                (this.metrics.noiseFloorAvg * this.metrics.noiseSamples + currentRms) / 
                (this.metrics.noiseSamples + 1);
            this.metrics.noiseSamples++;
        }
        return this.metrics.noiseFloorAvg;
    }
    
    calculateQualityScore() {
        let score = 100;
        const total = this.metrics.totalSamples || 1;
        
        // Penalize clipping heavily (-30 points max)
        const clippingRatio = this.metrics.clippingEvents / total;
        score -= Math.min(30, clippingRatio * 1000);
        
        // Penalize too quiet (-25 points max)
        const quietRatio = this.metrics.tooQuietSamples / total;
        score -= Math.min(25, quietRatio * 50);
        
        // Penalize too loud (-20 points max)
        const loudRatio = this.metrics.tooLoudSamples / total;
        score -= Math.min(20, loudRatio * 100);
        
        // Penalize high noise floor (-15 points max)
        const noiseRatio = this.metrics.noiseFloorAvg / this.thresholds.volumeMin;
        score -= Math.min(15, noiseRatio * 10);
        
        return Math.max(0, Math.round(score));
    }
    
    checkWarnings(rms, peak, isClipping) {
        const now = Date.now();
        
        // Clipping warning
        if (isClipping && this.canWarn('clipping', now)) {
            this.emitWarning('clipping', '⚠️ Audio clipping detected! Move away from the microphone.');
        }
        
        // Too quiet warning
        if (rms < this.thresholds.volumeMin && rms > 0.001 && this.canWarn('quiet', now)) {
            this.emitWarning('quiet', '🔇 Volume is very low. Speak closer to the microphone.');
        }
        
        // Too loud warning
        if (rms > this.thresholds.volumeMax && !isClipping && this.canWarn('loud', now)) {
            this.emitWarning('loud', '🔊 Volume is too high. Move away from the microphone.');
        }
    }
    
    canWarn(type, now) {
        if (!this.lastWarnings[type] || (now - this.lastWarnings[type]) > this.warningCooldown) {
            this.lastWarnings[type] = now;
            return true;
        }
        return false;
    }
    
    emitWarning(type, message) {
        if (this.onWarning) {
            this.onWarning(type, message);
        }
    }
    
    getQualityStatus() {
        const { volume, peak, isClipping } = this.currentValues;
        const score = this.metrics.qualityScore;
        
        let level, label, color;
        
        if (score >= 80) {
            level = 'good';
            label = 'Good';
            color = '#22c55e'; // green
        } else if (score >= 50) {
            level = 'fair';
            label = 'Fair';
            color = '#f59e0b'; // amber
        } else {
            level = 'poor';
            label = 'Poor';
            color = '#ef4444'; // red
        }
        
        // Determine volume bar state
        let volumeState;
        if (volume < this.thresholds.volumeMin) {
            volumeState = 'quiet';
        } else if (volume > this.thresholds.volumeMax || isClipping) {
            volumeState = 'loud';
        } else {
            volumeState = 'normal';
        }
        
        return {
            level,
            label,
            color,
            score,
            volume: Math.min(1, volume * 3), // Scale for display
            peak: peak,
            volumeState,
            isClipping,
            metrics: this.metrics
        };
    }
    
    stop() {
        this.isAnalyzing = false;
        
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        
        this.metrics.endTime = Date.now();
        
        if (this.audioContext) {
            this.audioContext.close().catch(() => {});
            this.audioContext = null;
        }
        
        this.analyser = null;
        this.source = null;
        this.lastWarnings = {};
    }
    
    getMetrics() {
        return {
            ...this.metrics,
            duration: this.metrics.endTime 
                ? this.metrics.endTime - this.metrics.startTime 
                : Date.now() - this.metrics.startTime
        };
    }
}

/**
 * Audio Quality Indicator UI Component
 * Displays visual quality feedback during recording
 */
class AudioQualityIndicator {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.analyzer = null;
        this.isVisible = false;
        
        if (this.container) {
            this.render();
        }
    }
    
    render() {
        this.container.innerHTML = `
            <div class="audio-quality-indicator">
                <div class="quality-badge" id="quality-badge">
                    <span class="quality-dot"></span>
                    <span class="quality-label">--</span>
                </div>
                <div class="volume-meter" id="volume-meter">
                    <div class="volume-bar" id="volume-bar"></div>
                    <div class="volume-peak" id="volume-peak"></div>
                </div>
                <div class="quality-warnings" id="quality-warnings"></div>
            </div>
        `;
        
        this.badge = this.container.querySelector('#quality-badge');
        this.label = this.container.querySelector('.quality-label');
        this.dot = this.container.querySelector('.quality-dot');
        this.volumeBar = this.container.querySelector('#volume-bar');
        this.volumePeak = this.container.querySelector('#volume-peak');
        this.warnings = this.container.querySelector('#quality-warnings');
    }
    
    attachAnalyzer(analyzer) {
        this.analyzer = analyzer;
        
        analyzer.onQualityUpdate = (status) => {
            this.updateDisplay(status);
        };
        
        analyzer.onWarning = (type, message) => {
            this.showWarning(message);
        };
    }
    
    updateDisplay(status) {
        if (!this.container) return;
        
        // Update quality badge
        this.label.textContent = status.label;
        this.dot.style.backgroundColor = status.color;
        this.badge.dataset.level = status.level;
        
        // Update volume meter
        const volumePercent = Math.min(100, status.volume * 100);
        this.volumeBar.style.width = `${volumePercent}%`;
        this.volumeBar.dataset.state = status.volumeState;
        
        // Update peak indicator
        const peakPercent = Math.min(100, status.peak * 100);
        this.volumePeak.style.left = `${peakPercent}%`;
        
        // Clipping indicator
        if (status.isClipping) {
            this.volumeBar.classList.add('clipping');
        } else {
            this.volumeBar.classList.remove('clipping');
        }
    }
    
    showWarning(message) {
        if (!this.warnings) return;
        
        const warningEl = document.createElement('div');
        warningEl.className = 'quality-warning';
        warningEl.textContent = message;
        
        this.warnings.appendChild(warningEl);
        
        // Remove after animation
        setTimeout(() => {
            warningEl.classList.add('fade-out');
            setTimeout(() => warningEl.remove(), 300);
        }, 3000);
    }
    
    show() {
        if (this.container) {
            this.container.classList.add('active');
            this.isVisible = true;
        }
    }
    
    hide() {
        if (this.container) {
            this.container.classList.remove('active');
            this.isVisible = false;
        }
    }
    
    reset() {
        if (this.label) this.label.textContent = '--';
        if (this.dot) this.dot.style.backgroundColor = '';
        if (this.volumeBar) {
            this.volumeBar.style.width = '0%';
            this.volumeBar.classList.remove('clipping');
        }
        if (this.volumePeak) this.volumePeak.style.left = '0%';
        if (this.warnings) this.warnings.innerHTML = '';
    }
}

// Export to global scope
window.AudioQualityAnalyzer = AudioQualityAnalyzer;
window.AudioQualityIndicator = AudioQualityIndicator;
