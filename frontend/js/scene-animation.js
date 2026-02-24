/**
 * Scene Animation - Animated Timeline of Events in Scene
 * WitnessReplay - Professional Law Enforcement Tool
 * 
 * Provides play/pause/scrub controls with speed adjustment
 * to animate the sequence of events in a scene reconstruction.
 */

class SceneAnimator {
    constructor(options = {}) {
        this.containerId = options.containerId || 'scene-animation-container';
        this.sceneCanvasId = options.sceneCanvasId || 'scene-editor-canvas';
        this.sessionId = null;
        this.sceneVersion = null;
        this.animation = null;
        this.elements = [];
        
        // Playback state
        this.isPlaying = false;
        this.currentTime = 0;
        this.playbackSpeed = 1.0;
        this.animationFrame = null;
        this.lastFrameTime = 0;
        
        // UI elements
        this.container = null;
        this.progressBar = null;
        this.timeDisplay = null;
        this.playBtn = null;
        this.speedSelect = null;
        
        this.eventCallbacks = {
            onPlay: options.onPlay || null,
            onPause: options.onPause || null,
            onSeek: options.onSeek || null,
            onComplete: options.onComplete || null,
            onKeyframe: options.onKeyframe || null
        };
        
        this.init();
    }

    init() {
        this.container = document.getElementById(this.containerId);
        if (!this.container) {
            console.warn('[SceneAnimator] Container not found, creating controls');
            this.createContainer();
        }
        this.render();
        this.setupEventListeners();
        console.debug('[SceneAnimator] Initialized');
    }

    createContainer() {
        // Create container if it doesn't exist
        const parent = document.getElementById(this.sceneCanvasId)?.parentElement;
        if (parent) {
            this.container = document.createElement('div');
            this.container.id = this.containerId;
            this.container.className = 'scene-animation-container';
            parent.appendChild(this.container);
        }
    }

    render() {
        if (!this.container) return;
        
        this.container.innerHTML = `
            <div class="animation-controls">
                <div class="animation-playback">
                    <button class="anim-btn anim-skip-start" title="Skip to Start">⏮</button>
                    <button class="anim-btn anim-play" title="Play/Pause">▶</button>
                    <button class="anim-btn anim-skip-end" title="Skip to End">⏭</button>
                </div>
                <div class="animation-progress-wrapper">
                    <div class="animation-progress-bar">
                        <div class="animation-progress-fill"></div>
                        <div class="animation-progress-handle"></div>
                        <div class="animation-keyframe-markers"></div>
                    </div>
                </div>
                <div class="animation-time-display">
                    <span class="current-time">0:00</span>
                    <span class="time-separator">/</span>
                    <span class="total-time">0:00</span>
                </div>
                <div class="animation-speed">
                    <label>Speed:</label>
                    <select class="speed-select">
                        <option value="0.25">0.25x</option>
                        <option value="0.5">0.5x</option>
                        <option value="1" selected>1x</option>
                        <option value="1.5">1.5x</option>
                        <option value="2">2x</option>
                    </select>
                </div>
            </div>
            <div class="animation-info">
                <span class="keyframe-count">0 keyframes</span>
                <span class="animation-status">Ready</span>
            </div>
        `;
        
        // Cache references
        this.playBtn = this.container.querySelector('.anim-play');
        this.progressBar = this.container.querySelector('.animation-progress-bar');
        this.progressFill = this.container.querySelector('.animation-progress-fill');
        this.progressHandle = this.container.querySelector('.animation-progress-handle');
        this.keyframeMarkers = this.container.querySelector('.animation-keyframe-markers');
        this.timeDisplay = this.container.querySelector('.animation-time-display');
        this.speedSelect = this.container.querySelector('.speed-select');
        this.statusEl = this.container.querySelector('.animation-status');
        this.keyframeCountEl = this.container.querySelector('.keyframe-count');
    }

    setupEventListeners() {
        if (!this.container) return;
        
        // Play/Pause
        this.playBtn?.addEventListener('click', () => this.togglePlayback());
        
        // Skip buttons
        this.container.querySelector('.anim-skip-start')?.addEventListener('click', () => this.seek(0));
        this.container.querySelector('.anim-skip-end')?.addEventListener('click', () => {
            if (this.animation) this.seek(this.animation.total_duration);
        });
        
        // Speed control
        this.speedSelect?.addEventListener('change', (e) => {
            this.playbackSpeed = parseFloat(e.target.value);
        });
        
        // Progress bar interaction (scrubbing)
        let isDragging = false;
        
        this.progressBar?.addEventListener('mousedown', (e) => {
            isDragging = true;
            this.handleProgressClick(e);
        });
        
        document.addEventListener('mousemove', (e) => {
            if (isDragging) this.handleProgressClick(e);
        });
        
        document.addEventListener('mouseup', () => {
            isDragging = false;
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            
            switch (e.key) {
                case ' ':
                    if (this.animation) {
                        e.preventDefault();
                        this.togglePlayback();
                    }
                    break;
                case 'ArrowLeft':
                    this.seek(Math.max(0, this.currentTime - 1));
                    break;
                case 'ArrowRight':
                    if (this.animation) {
                        this.seek(Math.min(this.animation.total_duration, this.currentTime + 1));
                    }
                    break;
            }
        });
    }

    handleProgressClick(e) {
        if (!this.progressBar || !this.animation) return;
        
        const rect = this.progressBar.getBoundingClientRect();
        const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
        const percent = x / rect.width;
        const time = percent * this.animation.total_duration;
        
        this.seek(time);
    }

    /**
     * Load animation data for a session/scene version
     */
    async loadAnimation(sessionId, sceneVersion) {
        this.sessionId = sessionId;
        this.sceneVersion = sceneVersion;
        this.setStatus('Loading...');
        
        try {
            const response = await fetch(`/api/sessions/${sessionId}/scene-versions/${sceneVersion}/animation`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const data = await response.json();
            this.animation = data.animation;
            this.elements = await this.loadSceneElements(sessionId, sceneVersion);
            
            this.renderKeyframeMarkers();
            this.updateTimeDisplay();
            this.updateKeyframeCount();
            this.setStatus('Ready');
            this.seek(0);
            
            console.debug('[SceneAnimator] Loaded animation:', this.animation);
            return this.animation;
            
        } catch (error) {
            console.error('[SceneAnimator] Failed to load animation:', error);
            this.setStatus('Error loading');
            return null;
        }
    }

    async loadSceneElements(sessionId, sceneVersion) {
        try {
            const response = await fetch(`/api/sessions/${sessionId}/scene-versions`);
            if (!response.ok) return [];
            
            const data = await response.json();
            const version = data.versions?.find(v => v.version === sceneVersion);
            return version?.elements || [];
        } catch (error) {
            console.error('[SceneAnimator] Failed to load elements:', error);
            return [];
        }
    }

    /**
     * Generate animation from timeline if none exists
     */
    async generateAnimation() {
        if (!this.sessionId || !this.sceneVersion) {
            console.warn('[SceneAnimator] No session/version loaded');
            return null;
        }
        
        this.setStatus('Generating...');
        
        try {
            const response = await fetch(
                `/api/sessions/${this.sessionId}/scene-versions/${this.sceneVersion}/animation/generate`,
                { method: 'POST' }
            );
            
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            const data = await response.json();
            this.animation = data.animation;
            
            this.renderKeyframeMarkers();
            this.updateTimeDisplay();
            this.updateKeyframeCount();
            this.setStatus('Generated');
            this.seek(0);
            
            return this.animation;
            
        } catch (error) {
            console.error('[SceneAnimator] Failed to generate animation:', error);
            this.setStatus('Error');
            return null;
        }
    }

    renderKeyframeMarkers() {
        if (!this.keyframeMarkers || !this.animation) return;
        
        this.keyframeMarkers.innerHTML = '';
        
        const duration = this.animation.total_duration || 1;
        
        (this.animation.keyframes || []).forEach(kf => {
            const percent = (kf.time_offset / duration) * 100;
            const marker = document.createElement('div');
            marker.className = `keyframe-marker action-${kf.action}`;
            marker.style.left = `${percent}%`;
            marker.title = kf.description || `${kf.action} at ${this.formatTime(kf.time_offset)}`;
            this.keyframeMarkers.appendChild(marker);
        });
    }

    togglePlayback() {
        if (this.isPlaying) {
            this.pause();
        } else {
            this.play();
        }
    }

    play() {
        if (!this.animation || this.isPlaying) return;
        
        // Reset if at end
        if (this.currentTime >= this.animation.total_duration) {
            this.currentTime = 0;
        }
        
        this.isPlaying = true;
        this.lastFrameTime = performance.now();
        this.playBtn.textContent = '⏸';
        this.playBtn.title = 'Pause';
        this.setStatus('Playing');
        
        if (this.eventCallbacks.onPlay) {
            this.eventCallbacks.onPlay(this.currentTime);
        }
        
        this.animationLoop();
    }

    pause() {
        this.isPlaying = false;
        this.playBtn.textContent = '▶';
        this.playBtn.title = 'Play';
        this.setStatus('Paused');
        
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
        
        if (this.eventCallbacks.onPause) {
            this.eventCallbacks.onPause(this.currentTime);
        }
    }

    seek(time) {
        if (!this.animation) return;
        
        this.currentTime = Math.max(0, Math.min(time, this.animation.total_duration));
        this.updateProgressBar();
        this.updateTimeDisplay();
        this.applyKeyframesAtTime(this.currentTime);
        
        if (this.eventCallbacks.onSeek) {
            this.eventCallbacks.onSeek(this.currentTime);
        }
    }

    animationLoop() {
        if (!this.isPlaying || !this.animation) return;
        
        const now = performance.now();
        const deltaTime = (now - this.lastFrameTime) / 1000; // seconds
        this.lastFrameTime = now;
        
        // Advance time
        this.currentTime += deltaTime * this.playbackSpeed;
        
        // Check for completion
        if (this.currentTime >= this.animation.total_duration) {
            this.currentTime = this.animation.total_duration;
            this.pause();
            this.setStatus('Complete');
            
            if (this.eventCallbacks.onComplete) {
                this.eventCallbacks.onComplete();
            }
            return;
        }
        
        // Update UI
        this.updateProgressBar();
        this.updateTimeDisplay();
        
        // Apply keyframes
        this.applyKeyframesAtTime(this.currentTime);
        
        // Continue loop
        this.animationFrame = requestAnimationFrame(() => this.animationLoop());
    }

    applyKeyframesAtTime(time) {
        if (!this.animation || !this.animation.keyframes) return;
        
        const canvas = document.getElementById(this.sceneCanvasId);
        if (!canvas) return;
        
        // Find all keyframes that should be active
        const activeKeyframes = this.animation.keyframes.filter(kf => {
            const endTime = kf.time_offset + (kf.duration || 0.5);
            return kf.time_offset <= time && time <= endTime;
        });
        
        // Find all keyframes that have completed
        const completedKeyframes = this.animation.keyframes.filter(kf => {
            const endTime = kf.time_offset + (kf.duration || 0.5);
            return endTime < time;
        });
        
        // Find all keyframes that haven't started
        const futureKeyframes = this.animation.keyframes.filter(kf => kf.time_offset > time);
        
        // Reset all elements first
        canvas.querySelectorAll('.placed-element').forEach(el => {
            el.classList.remove('animating', 'anim-appear', 'anim-disappear', 'anim-highlight', 'anim-pulse');
            el.style.opacity = '0';
            el.style.transform = '';
        });
        
        // Apply completed keyframes (make elements visible)
        const visibleElements = new Set();
        completedKeyframes.forEach(kf => {
            if (kf.action === 'appear') {
                visibleElements.add(kf.element_id);
            } else if (kf.action === 'disappear') {
                visibleElements.delete(kf.element_id);
            }
        });
        
        visibleElements.forEach(elementId => {
            const el = canvas.querySelector(`[data-element-id="${elementId}"], #${elementId}`);
            if (el) {
                el.style.opacity = '1';
            }
        });
        
        // Apply active keyframes
        activeKeyframes.forEach(kf => {
            const el = canvas.querySelector(`[data-element-id="${kf.element_id}"], #${kf.element_id}`);
            if (!el) return;
            
            const progress = Math.min(1, (time - kf.time_offset) / (kf.duration || 0.5));
            
            el.classList.add('animating');
            
            switch (kf.action) {
                case 'appear':
                    el.classList.add('anim-appear');
                    el.style.opacity = progress.toString();
                    el.style.transform = `scale(${0.5 + progress * 0.5})`;
                    if (this.eventCallbacks.onKeyframe && progress === 1) {
                        this.eventCallbacks.onKeyframe(kf);
                    }
                    break;
                    
                case 'disappear':
                    el.classList.add('anim-disappear');
                    el.style.opacity = (1 - progress).toString();
                    break;
                    
                case 'highlight':
                    el.classList.add('anim-highlight');
                    el.style.boxShadow = `0 0 ${20 * progress}px ${kf.properties?.color || '#00d4ff'}`;
                    break;
                    
                case 'pulse':
                    el.classList.add('anim-pulse');
                    const scale = 1 + 0.1 * Math.sin(progress * Math.PI * 2);
                    el.style.transform = `scale(${scale})`;
                    break;
                    
                case 'move':
                    if (kf.properties?.toX !== undefined && kf.properties?.toY !== undefined) {
                        const startX = kf.properties.fromX || parseFloat(el.style.left) || 0;
                        const startY = kf.properties.fromY || parseFloat(el.style.top) || 0;
                        const x = startX + (kf.properties.toX - startX) * progress;
                        const y = startY + (kf.properties.toY - startY) * progress;
                        el.style.left = `${x}px`;
                        el.style.top = `${y}px`;
                    }
                    break;
            }
        });
    }

    updateProgressBar() {
        if (!this.progressFill || !this.progressHandle || !this.animation) return;
        
        const percent = (this.currentTime / this.animation.total_duration) * 100;
        this.progressFill.style.width = `${percent}%`;
        this.progressHandle.style.left = `${percent}%`;
    }

    updateTimeDisplay() {
        if (!this.timeDisplay) return;
        
        const current = this.formatTime(this.currentTime);
        const total = this.formatTime(this.animation?.total_duration || 0);
        
        this.timeDisplay.querySelector('.current-time').textContent = current;
        this.timeDisplay.querySelector('.total-time').textContent = total;
    }

    updateKeyframeCount() {
        if (!this.keyframeCountEl) return;
        const count = this.animation?.keyframes?.length || 0;
        this.keyframeCountEl.textContent = `${count} keyframe${count !== 1 ? 's' : ''}`;
    }

    setStatus(status) {
        if (this.statusEl) {
            this.statusEl.textContent = status;
        }
    }

    formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    /**
     * Get current animation state for saving
     */
    getAnimationData() {
        return this.animation;
    }

    /**
     * Set animation data directly (for loading saved animations)
     */
    setAnimationData(animation) {
        this.animation = animation;
        this.renderKeyframeMarkers();
        this.updateTimeDisplay();
        this.updateKeyframeCount();
        this.seek(0);
    }

    /**
     * Destroy the animator and clean up
     */
    destroy() {
        this.pause();
        if (this.container) {
            this.container.innerHTML = '';
        }
        this.animation = null;
        this.elements = [];
    }
}

// Create global instance
window.SceneAnimator = SceneAnimator;

// Export for module use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SceneAnimator;
}
