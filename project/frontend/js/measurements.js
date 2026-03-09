/**
 * Scene Measurement Tool
 * Provides distance and angle measurements on scene images
 */

class SceneMeasurementTool {
    constructor(app) {
        this.app = app;
        this.measurements = [];
        this.currentPoints = [];
        this.mode = null; // 'distance' or 'angle'
        this.isActive = false;
        this.canvas = null;
        this.ctx = null;
        this.scalePixelsPerFoot = 50; // Default scale: 50 pixels = 1 foot (adjustable)
        this.currentUnit = 'feet';
        this.selectedMeasurement = null;
        
        this.initialize();
    }
    
    initialize() {
        // Add measurement button to scene controls
        this.addMeasurementControls();
        
        // Create measurement overlay canvas
        this.createMeasurementCanvas();
        
        // Bind event handlers
        this.boundHandleClick = this.handleClick.bind(this);
        this.boundHandleMouseMove = this.handleMouseMove.bind(this);
        this.boundHandleKeyDown = this.handleKeyDown.bind(this);
    }
    
    addMeasurementControls() {
        const sceneControls = document.querySelector('.scene-controls');
        if (!sceneControls) return;
        
        // Check if measurement button already exists
        if (sceneControls.querySelector('#measure-btn')) return;
        
        // Create measurement button
        const measureBtn = document.createElement('button');
        measureBtn.id = 'measure-btn';
        measureBtn.className = 'scene-control-btn';
        measureBtn.setAttribute('data-tooltip', 'Measurement Tools');
        measureBtn.setAttribute('aria-label', 'Open measurement tools');
        measureBtn.innerHTML = '📏';
        measureBtn.addEventListener('click', () => this.showMeasurementMenu());
        
        // Insert after zoom button
        const zoomBtn = sceneControls.querySelector('#zoom-btn');
        if (zoomBtn && zoomBtn.nextSibling) {
            sceneControls.insertBefore(measureBtn, zoomBtn.nextSibling);
        } else {
            sceneControls.appendChild(measureBtn);
        }
    }
    
    createMeasurementCanvas() {
        const sceneDisplay = document.getElementById('scene-display');
        if (!sceneDisplay) return;
        
        // Remove existing canvas if present
        const existingCanvas = sceneDisplay.querySelector('.measurement-canvas');
        if (existingCanvas) existingCanvas.remove();
        
        // Create canvas overlay
        this.canvas = document.createElement('canvas');
        this.canvas.className = 'measurement-canvas';
        this.canvas.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 10;
        `;
        sceneDisplay.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');
        
        // Handle resize
        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());
        
        // Observe scene display for changes
        const observer = new MutationObserver(() => {
            this.resizeCanvas();
            this.renderMeasurements();
        });
        observer.observe(sceneDisplay, { childList: true, subtree: true });
    }
    
    resizeCanvas() {
        if (!this.canvas) return;
        const sceneDisplay = document.getElementById('scene-display');
        if (!sceneDisplay) return;
        
        const rect = sceneDisplay.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
        this.renderMeasurements();
    }
    
    showMeasurementMenu() {
        // Create or show measurement menu
        let menu = document.getElementById('measurement-menu');
        if (menu) {
            menu.classList.toggle('hidden');
            return;
        }
        
        menu = document.createElement('div');
        menu.id = 'measurement-menu';
        menu.className = 'measurement-menu';
        menu.innerHTML = `
            <div class="measurement-menu-header">
                <span>📏 Measurement Tools</span>
                <button class="measurement-menu-close" aria-label="Close">×</button>
            </div>
            <div class="measurement-menu-tools">
                <button class="measurement-tool-btn" data-tool="distance">
                    <span class="tool-icon">📐</span>
                    <span class="tool-name">Distance</span>
                    <span class="tool-desc">Click 2 points</span>
                </button>
                <button class="measurement-tool-btn" data-tool="angle">
                    <span class="tool-icon">📊</span>
                    <span class="tool-name">Angle</span>
                    <span class="tool-desc">Click 3 points</span>
                </button>
            </div>
            <div class="measurement-menu-options">
                <label>
                    Unit:
                    <select id="measurement-unit">
                        <option value="feet">Feet</option>
                        <option value="meters">Meters</option>
                    </select>
                </label>
                <label>
                    Scale (px/ft):
                    <input type="number" id="measurement-scale" value="${this.scalePixelsPerFoot}" min="1" max="500">
                </label>
            </div>
            <div class="measurement-menu-list">
                <h4>Measurements</h4>
                <div id="measurement-list-items"></div>
            </div>
            <div class="measurement-menu-actions">
                <button id="clear-measurements-btn" class="btn btn-secondary btn-sm">🗑️ Clear All</button>
                <button id="export-measurements-btn" class="btn btn-primary btn-sm">📤 Export</button>
            </div>
        `;
        
        const sceneDisplay = document.getElementById('scene-display');
        sceneDisplay.appendChild(menu);
        
        // Bind events
        menu.querySelector('.measurement-menu-close').addEventListener('click', () => {
            menu.classList.add('hidden');
            this.deactivate();
        });
        
        menu.querySelectorAll('.measurement-tool-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const tool = btn.getAttribute('data-tool');
                this.activateTool(tool);
                menu.querySelectorAll('.measurement-tool-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        });
        
        document.getElementById('measurement-unit').addEventListener('change', (e) => {
            this.currentUnit = e.target.value;
            this.updateMeasurementValues();
        });
        
        document.getElementById('measurement-scale').addEventListener('change', (e) => {
            this.scalePixelsPerFoot = parseFloat(e.target.value) || 50;
            this.updateMeasurementValues();
        });
        
        document.getElementById('clear-measurements-btn').addEventListener('click', () => {
            this.clearAllMeasurements();
        });
        
        document.getElementById('export-measurements-btn').addEventListener('click', () => {
            this.exportMeasurements();
        });
        
        this.updateMeasurementList();
    }
    
    activateTool(tool) {
        this.mode = tool;
        this.isActive = true;
        this.currentPoints = [];
        
        // Enable canvas interaction
        this.canvas.style.pointerEvents = 'auto';
        this.canvas.style.cursor = 'crosshair';
        
        // Add event listeners
        this.canvas.addEventListener('click', this.boundHandleClick);
        this.canvas.addEventListener('mousemove', this.boundHandleMouseMove);
        document.addEventListener('keydown', this.boundHandleKeyDown);
        
        // Show toast
        const pointsNeeded = tool === 'distance' ? 2 : 3;
        this.app.ui.showToast(`Click ${pointsNeeded} points to measure ${tool}. Press Esc to cancel.`, 'info', 3000);
    }
    
    deactivate() {
        this.isActive = false;
        this.mode = null;
        this.currentPoints = [];
        
        if (this.canvas) {
            this.canvas.style.pointerEvents = 'none';
            this.canvas.style.cursor = 'default';
            this.canvas.removeEventListener('click', this.boundHandleClick);
            this.canvas.removeEventListener('mousemove', this.boundHandleMouseMove);
        }
        document.removeEventListener('keydown', this.boundHandleKeyDown);
        
        this.renderMeasurements();
        
        // Remove active state from buttons
        const menu = document.getElementById('measurement-menu');
        if (menu) {
            menu.querySelectorAll('.measurement-tool-btn').forEach(b => b.classList.remove('active'));
        }
    }
    
    handleClick(e) {
        if (!this.isActive) return;
        
        const rect = this.canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width;
        const y = (e.clientY - rect.top) / rect.height;
        
        this.currentPoints.push({ x, y });
        
        const pointsNeeded = this.mode === 'distance' ? 2 : 3;
        
        if (this.currentPoints.length >= pointsNeeded) {
            this.createMeasurement();
        } else {
            this.renderMeasurements();
        }
    }
    
    handleMouseMove(e) {
        if (!this.isActive || this.currentPoints.length === 0) return;
        this.renderMeasurements(e);
    }
    
    handleKeyDown(e) {
        if (e.key === 'Escape') {
            this.deactivate();
        } else if (e.key === 'Delete' || e.key === 'Backspace') {
            if (this.selectedMeasurement) {
                this.deleteMeasurement(this.selectedMeasurement);
            }
        }
    }
    
    createMeasurement() {
        const value = this.calculateValue();
        const unit = this.mode === 'angle' ? 'degrees' : this.currentUnit;
        
        const measurement = {
            id: `m-${Date.now()}`,
            type: this.mode,
            points: [...this.currentPoints],
            value: value,
            unit: unit,
            label: null,
            color: this.getRandomColor(),
            scene_version: this.app.currentVersion || 1,
            created_at: new Date().toISOString()
        };
        
        this.measurements.push(measurement);
        this.currentPoints = [];
        
        // Save to backend
        this.saveMeasurement(measurement);
        
        // Update UI
        this.updateMeasurementList();
        this.renderMeasurements();
        
        // Show toast
        const displayValue = this.mode === 'angle' 
            ? `${value.toFixed(1)}°` 
            : `${value.toFixed(2)} ${unit}`;
        this.app.ui.showToast(`Measurement: ${displayValue}`, 'success', 2000);
    }
    
    calculateValue() {
        if (this.mode === 'distance') {
            return this.calculateDistance(this.currentPoints[0], this.currentPoints[1]);
        } else if (this.mode === 'angle') {
            return this.calculateAngle(this.currentPoints[0], this.currentPoints[1], this.currentPoints[2]);
        }
        return 0;
    }
    
    calculateDistance(p1, p2) {
        const rect = this.canvas.getBoundingClientRect();
        const dx = (p2.x - p1.x) * rect.width;
        const dy = (p2.y - p1.y) * rect.height;
        const pixelDistance = Math.sqrt(dx * dx + dy * dy);
        
        // Convert to feet
        let distance = pixelDistance / this.scalePixelsPerFoot;
        
        // Convert to meters if needed
        if (this.currentUnit === 'meters') {
            distance *= 0.3048;
        }
        
        return distance;
    }
    
    calculateAngle(p1, p2, p3) {
        // p2 is the vertex
        const rect = this.canvas.getBoundingClientRect();
        const ax = (p1.x - p2.x) * rect.width;
        const ay = (p1.y - p2.y) * rect.height;
        const bx = (p3.x - p2.x) * rect.width;
        const by = (p3.y - p2.y) * rect.height;
        
        const dot = ax * bx + ay * by;
        const magA = Math.sqrt(ax * ax + ay * ay);
        const magB = Math.sqrt(bx * bx + by * by);
        
        if (magA === 0 || magB === 0) return 0;
        
        const cosAngle = dot / (magA * magB);
        const angle = Math.acos(Math.max(-1, Math.min(1, cosAngle)));
        
        return angle * (180 / Math.PI);
    }
    
    renderMeasurements(mouseEvent = null) {
        if (!this.ctx || !this.canvas) return;
        
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // Render existing measurements
        this.measurements.forEach(m => {
            this.drawMeasurement(m, m === this.selectedMeasurement);
        });
        
        // Render in-progress measurement
        if (this.currentPoints.length > 0 && this.isActive) {
            this.drawInProgressMeasurement(mouseEvent);
        }
    }
    
    drawMeasurement(measurement, isSelected = false) {
        const { points, type, value, unit, color } = measurement;
        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;
        
        ctx.save();
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = isSelected ? 3 : 2;
        
        if (type === 'distance') {
            const p1 = { x: points[0].x * w, y: points[0].y * h };
            const p2 = { x: points[1].x * w, y: points[1].y * h };
            
            // Draw line
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
            
            // Draw endpoints
            this.drawPoint(p1.x, p1.y, color);
            this.drawPoint(p2.x, p2.y, color);
            
            // Draw label at midpoint
            const midX = (p1.x + p2.x) / 2;
            const midY = (p1.y + p2.y) / 2;
            const displayValue = unit === 'meters' ? `${value.toFixed(2)}m` : `${value.toFixed(2)}ft`;
            this.drawLabel(midX, midY - 15, displayValue, color);
            
        } else if (type === 'angle') {
            const p1 = { x: points[0].x * w, y: points[0].y * h };
            const p2 = { x: points[1].x * w, y: points[1].y * h }; // vertex
            const p3 = { x: points[2].x * w, y: points[2].y * h };
            
            // Draw lines from vertex
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.lineTo(p3.x, p3.y);
            ctx.stroke();
            
            // Draw arc at vertex
            const angle1 = Math.atan2(p1.y - p2.y, p1.x - p2.x);
            const angle2 = Math.atan2(p3.y - p2.y, p3.x - p2.x);
            const arcRadius = 30;
            
            ctx.beginPath();
            ctx.arc(p2.x, p2.y, arcRadius, angle1, angle2, angle2 < angle1);
            ctx.stroke();
            
            // Draw points
            this.drawPoint(p1.x, p1.y, color);
            this.drawPoint(p2.x, p2.y, color, true); // vertex
            this.drawPoint(p3.x, p3.y, color);
            
            // Draw label near vertex
            const displayValue = `${value.toFixed(1)}°`;
            this.drawLabel(p2.x + 40, p2.y - 10, displayValue, color);
        }
        
        ctx.restore();
    }
    
    drawInProgressMeasurement(mouseEvent) {
        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;
        
        ctx.save();
        ctx.strokeStyle = '#00d4ff';
        ctx.fillStyle = '#00d4ff';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 5]);
        
        // Draw existing points
        this.currentPoints.forEach((p, i) => {
            this.drawPoint(p.x * w, p.y * h, '#00d4ff', i === 1 && this.mode === 'angle');
        });
        
        // Draw lines between points
        if (this.currentPoints.length > 0) {
            ctx.beginPath();
            ctx.moveTo(this.currentPoints[0].x * w, this.currentPoints[0].y * h);
            
            for (let i = 1; i < this.currentPoints.length; i++) {
                ctx.lineTo(this.currentPoints[i].x * w, this.currentPoints[i].y * h);
            }
            
            // Draw line to mouse position
            if (mouseEvent) {
                const rect = this.canvas.getBoundingClientRect();
                const mouseX = mouseEvent.clientX - rect.left;
                const mouseY = mouseEvent.clientY - rect.top;
                ctx.lineTo(mouseX, mouseY);
            }
            
            ctx.stroke();
        }
        
        ctx.restore();
    }
    
    drawPoint(x, y, color, isVertex = false) {
        const ctx = this.ctx;
        ctx.save();
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x, y, isVertex ? 8 : 6, 0, Math.PI * 2);
        ctx.fill();
        
        // White inner circle
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(x, y, isVertex ? 4 : 3, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
    }
    
    drawLabel(x, y, text, color) {
        const ctx = this.ctx;
        ctx.save();
        
        ctx.font = 'bold 14px -apple-system, BlinkMacSystemFont, sans-serif';
        const metrics = ctx.measureText(text);
        const padding = 6;
        const width = metrics.width + padding * 2;
        const height = 20;
        
        // Background
        ctx.fillStyle = 'rgba(15, 25, 35, 0.9)';
        ctx.roundRect(x - width / 2, y - height / 2, width, height, 4);
        ctx.fill();
        
        // Border
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.stroke();
        
        // Text
        ctx.fillStyle = '#ffffff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(text, x, y);
        
        ctx.restore();
    }
    
    getRandomColor() {
        const colors = ['#00d4ff', '#ff6b6b', '#4ecdc4', '#ffe66d', '#95e1d3', '#f38181', '#a8d8ea'];
        return colors[Math.floor(Math.random() * colors.length)];
    }
    
    updateMeasurementList() {
        const listContainer = document.getElementById('measurement-list-items');
        if (!listContainer) return;
        
        if (this.measurements.length === 0) {
            listContainer.innerHTML = '<p class="empty-state">No measurements yet</p>';
            return;
        }
        
        listContainer.innerHTML = this.measurements.map(m => {
            const icon = m.type === 'distance' ? '📐' : '📊';
            const displayValue = m.type === 'angle' 
                ? `${m.value.toFixed(1)}°` 
                : `${m.value.toFixed(2)} ${m.unit}`;
            
            return `
                <div class="measurement-item" data-id="${m.id}" style="border-left: 3px solid ${m.color}">
                    <span class="measurement-icon">${icon}</span>
                    <span class="measurement-value">${displayValue}</span>
                    <span class="measurement-label">${m.label || ''}</span>
                    <button class="measurement-edit" data-id="${m.id}" aria-label="Edit">✏️</button>
                    <button class="measurement-delete" data-id="${m.id}" aria-label="Delete">🗑️</button>
                </div>
            `;
        }).join('');
        
        // Bind edit/delete events
        listContainer.querySelectorAll('.measurement-edit').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.editMeasurement(btn.getAttribute('data-id'));
            });
        });
        
        listContainer.querySelectorAll('.measurement-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteMeasurement(btn.getAttribute('data-id'));
            });
        });
        
        listContainer.querySelectorAll('.measurement-item').forEach(item => {
            item.addEventListener('click', () => {
                this.selectMeasurement(item.getAttribute('data-id'));
            });
        });
    }
    
    selectMeasurement(id) {
        this.selectedMeasurement = this.measurements.find(m => m.id === id) || null;
        this.renderMeasurements();
        
        // Highlight in list
        document.querySelectorAll('.measurement-item').forEach(item => {
            item.classList.toggle('selected', item.getAttribute('data-id') === id);
        });
    }
    
    editMeasurement(id) {
        const measurement = this.measurements.find(m => m.id === id);
        if (!measurement) return;
        
        const newLabel = prompt('Enter label for this measurement:', measurement.label || '');
        if (newLabel !== null) {
            measurement.label = newLabel;
            this.updateMeasurementBackend(measurement);
            this.updateMeasurementList();
            this.renderMeasurements();
        }
    }
    
    deleteMeasurement(id) {
        const idx = this.measurements.findIndex(m => m.id === id);
        if (idx === -1) return;
        
        const measurement = this.measurements[idx];
        this.measurements.splice(idx, 1);
        this.selectedMeasurement = null;
        
        // Delete from backend
        this.deleteMeasurementBackend(measurement.id);
        
        this.updateMeasurementList();
        this.renderMeasurements();
        this.app.ui.showToast('Measurement deleted', 'info', 2000);
    }
    
    clearAllMeasurements() {
        if (!confirm('Clear all measurements?')) return;
        
        // Delete each from backend
        this.measurements.forEach(m => {
            this.deleteMeasurementBackend(m.id);
        });
        
        this.measurements = [];
        this.selectedMeasurement = null;
        this.updateMeasurementList();
        this.renderMeasurements();
        this.app.ui.showToast('All measurements cleared', 'info', 2000);
    }
    
    updateMeasurementValues() {
        // Recalculate all distance measurements with new scale/unit
        this.measurements.forEach(m => {
            if (m.type === 'distance') {
                this.currentPoints = [...m.points];
                m.value = this.calculateDistance(m.points[0], m.points[1]);
                m.unit = this.currentUnit;
                this.currentPoints = [];
            }
        });
        
        this.updateMeasurementList();
        this.renderMeasurements();
    }
    
    // Backend API methods
    async saveMeasurement(measurement) {
        if (!this.app.sessionId) return;
        
        try {
            const response = await this.app.fetchWithTimeout(`/api/sessions/${this.app.sessionId}/measurements`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    type: measurement.type,
                    points: measurement.points,
                    value: measurement.value,
                    unit: measurement.unit,
                    label: measurement.label,
                    color: measurement.color,
                    scene_version: measurement.scene_version
                })
            });
            
            if (response.ok) {
                const saved = await response.json();
                measurement.id = saved.id; // Update with server ID
            }
        } catch (error) {
            console.error('Failed to save measurement:', error);
        }
    }
    
    async updateMeasurementBackend(measurement) {
        if (!this.app.sessionId) return;
        
        try {
            await this.app.fetchWithTimeout(`/api/sessions/${this.app.sessionId}/measurements/${measurement.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    value: measurement.value,
                    unit: measurement.unit,
                    label: measurement.label,
                    color: measurement.color
                })
            });
        } catch (error) {
            console.error('Failed to update measurement:', error);
        }
    }
    
    async deleteMeasurementBackend(measurementId) {
        if (!this.app.sessionId) return;
        
        try {
            await this.app.fetchWithTimeout(`/api/sessions/${this.app.sessionId}/measurements/${measurementId}`, {
                method: 'DELETE'
            });
        } catch (error) {
            console.error('Failed to delete measurement:', error);
        }
    }
    
    async loadMeasurements() {
        if (!this.app.sessionId) return;
        
        try {
            const response = await this.app.fetchWithTimeout(`/api/sessions/${this.app.sessionId}/measurements`);
            if (response.ok) {
                const data = await response.json();
                this.measurements = data.measurements || [];
                this.updateMeasurementList();
                this.renderMeasurements();
            }
        } catch (error) {
            console.error('Failed to load measurements:', error);
        }
    }
    
    exportMeasurements() {
        if (this.measurements.length === 0) {
            this.app.ui.showToast('No measurements to export', 'warning', 2000);
            return;
        }
        
        const exportData = {
            session_id: this.app.sessionId,
            scene_version: this.app.currentVersion,
            exported_at: new Date().toISOString(),
            scale_pixels_per_foot: this.scalePixelsPerFoot,
            measurements: this.measurements.map(m => ({
                type: m.type,
                value: m.value,
                unit: m.unit,
                label: m.label || '',
                points: m.points
            }))
        };
        
        // Download as JSON
        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `measurements-${this.app.sessionId}-${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
        
        this.app.ui.showToast('Measurements exported', 'success', 2000);
    }
    
    // Generate measurements summary for reports
    getMeasurementsSummary() {
        const distances = this.measurements.filter(m => m.type === 'distance');
        const angles = this.measurements.filter(m => m.type === 'angle');
        
        return {
            total: this.measurements.length,
            distances: distances.map(m => ({
                value: m.value,
                unit: m.unit,
                label: m.label
            })),
            angles: angles.map(m => ({
                value: m.value,
                label: m.label
            }))
        };
    }
}

// Initialize measurement tool when app is ready
if (typeof window !== 'undefined') {
    window.SceneMeasurementTool = SceneMeasurementTool;
}
