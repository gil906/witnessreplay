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
            
            console.log('Recording started with', mimeType);
            
        } catch (error) {
            console.error('Error accessing microphone:', error);
            throw error;
        }
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
                console.log('Recording stopped, blob size:', audioBlob.size);
                
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

// Export to global scope
window.AudioRecorder = AudioRecorder;
window.EnhancedAudioVisualizer = EnhancedAudioVisualizer;
