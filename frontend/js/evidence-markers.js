/**
 * Evidence Marker Tool
 * Provides numbered evidence markers (1-20) for scene annotation
 */

class EvidenceMarkerTool {
    constructor(app) {
        this.app = app;
        this.markers = [];
        this.isActive = false;
        this.selectedMarkerNumber = 1;
        this.selectedMarker = null;
        this.canvas = null;
        this.ctx = null;
        this.nextAvailableNumber = 1;
        
        this.categories = [
            { id: 'general', name: 'General', icon: '🔷', color: '#fbbf24' },
            { id: 'physical', name: 'Physical', icon: '📦', color: '#ef4444' },
            { id: 'biological', name: 'Biological', icon: '🧬', color: '#22c55e' },
            { id: 'digital', name: 'Digital', icon: '💾', color: '#3b82f6' },
            { id: 'trace', name: 'Trace', icon: '🔬', color: '#a855f7' }
        ];
        this.selectedCategory = 'general';
        
        this.initialize();
    }
    
    initialize() {
        this.addMarkerControls();
        this.createMarkerCanvas();
        this.boundHandleClick = this.handleClick.bind(this);
        this.boundHandleKeyDown = this.handleKeyDown.bind(this);
    }
    
    addMarkerControls() {
        const sceneControls = document.querySelector('.scene-controls');
        if (!sceneControls) return;
        
        // Check if marker button already exists
        if (sceneControls.querySelector('#evidence-marker-btn')) return;
        
        // Create evidence marker button
        const markerBtn = document.createElement('button');
        markerBtn.id = 'evidence-marker-btn';
        markerBtn.className = 'scene-control-btn';
        markerBtn.setAttribute('data-tooltip', 'Evidence Markers');
        markerBtn.setAttribute('aria-label', 'Add evidence markers');
        markerBtn.innerHTML = '📍';
        markerBtn.addEventListener('click', () => this.showMarkerMenu());
        
        // Insert after measure button
        const measureBtn = sceneControls.querySelector('#measure-btn');
        if (measureBtn && measureBtn.nextSibling) {
            sceneControls.insertBefore(markerBtn, measureBtn.nextSibling);
        } else {
            sceneControls.appendChild(markerBtn);
        }
    }
    
    createMarkerCanvas() {
        const sceneDisplay = document.getElementById('scene-display');
        if (!sceneDisplay) return;
        
        // Remove existing canvas if present
        const existingCanvas = sceneDisplay.querySelector('.evidence-marker-canvas');
        if (existingCanvas) existingCanvas.remove();
        
        // Create canvas overlay
        this.canvas = document.createElement('canvas');
        this.canvas.className = 'evidence-marker-canvas';
        this.canvas.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 11;
        `;
        sceneDisplay.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');
        
        // Handle resize
        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());
        
        // Observe scene display for changes
        const observer = new MutationObserver(() => {
            this.resizeCanvas();
            this.renderMarkers();
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
        this.renderMarkers();
    }
    
    showMarkerMenu() {
        let menu = document.getElementById('evidence-marker-menu');
        if (menu) {
            menu.classList.toggle('hidden');
            return;
        }
        
        menu = document.createElement('div');
        menu.id = 'evidence-marker-menu';
        menu.className = 'evidence-marker-menu';
        menu.innerHTML = `
            <div class="marker-menu-header">
                <span>📍 Evidence Markers</span>
                <button class="marker-menu-close" aria-label="Close">×</button>
            </div>
            <div class="marker-menu-numbers">
                <label>Select Marker Number:</label>
                <div class="marker-number-grid" id="marker-number-grid">
                    ${this.renderNumberGrid()}
                </div>
            </div>
            <div class="marker-menu-categories">
                <label>Category:</label>
                <div class="marker-category-btns" id="marker-category-btns">
                    ${this.categories.map(c => `
                        <button class="marker-category-btn ${c.id === this.selectedCategory ? 'active' : ''}" 
                                data-category="${c.id}" 
                                style="--cat-color: ${c.color}"
                                title="${c.name}">
                            ${c.icon}
                        </button>
                    `).join('')}
                </div>
            </div>
            <div class="marker-menu-actions">
                <button id="place-marker-btn" class="btn btn-primary btn-sm">📍 Place Marker #${this.selectedMarkerNumber}</button>
                <button id="cancel-marker-btn" class="btn btn-secondary btn-sm">Cancel</button>
            </div>
            <div class="marker-menu-list">
                <h4>Placed Markers</h4>
                <div id="marker-list-items"></div>
            </div>
            <div class="marker-menu-footer">
                <button id="clear-markers-btn" class="btn btn-secondary btn-sm">🗑️ Clear All</button>
                <button id="export-markers-btn" class="btn btn-primary btn-sm">📤 Export</button>
            </div>
        `;
        
        const sceneDisplay = document.getElementById('scene-display');
        sceneDisplay.appendChild(menu);
        
        // Bind events
        menu.querySelector('.marker-menu-close').addEventListener('click', () => {
            menu.classList.add('hidden');
            this.deactivate();
        });
        
        // Number selection
        menu.querySelectorAll('.marker-number-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.selectedMarkerNumber = parseInt(btn.dataset.number);
                this.updateNumberSelection();
                document.getElementById('place-marker-btn').textContent = `📍 Place Marker #${this.selectedMarkerNumber}`;
            });
        });
        
        // Category selection
        menu.querySelectorAll('.marker-category-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.selectedCategory = btn.dataset.category;
                menu.querySelectorAll('.marker-category-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        });
        
        // Place marker button
        document.getElementById('place-marker-btn').addEventListener('click', () => {
            this.activatePlacement();
        });
        
        // Cancel button
        document.getElementById('cancel-marker-btn').addEventListener('click', () => {
            this.deactivate();
        });
        
        // Clear all
        document.getElementById('clear-markers-btn').addEventListener('click', () => {
            this.clearAllMarkers();
        });
        
        // Export
        document.getElementById('export-markers-btn').addEventListener('click', () => {
            this.exportMarkers();
        });
        
        this.updateMarkerList();
        this.updateNextAvailableNumber();
    }
    
    renderNumberGrid() {
        let html = '';
        for (let i = 1; i <= 20; i++) {
            const isUsed = this.markers.some(m => m.number === i);
            const isSelected = i === this.selectedMarkerNumber;
            html += `
                <button class="marker-number-btn ${isSelected ? 'selected' : ''} ${isUsed ? 'used' : ''}" 
                        data-number="${i}" 
                        ${isUsed ? 'disabled' : ''}>
                    ${i}
                </button>
            `;
        }
        return html;
    }
    
    updateNumberSelection() {
        document.querySelectorAll('.marker-number-btn').forEach(btn => {
            btn.classList.toggle('selected', parseInt(btn.dataset.number) === this.selectedMarkerNumber);
        });
    }
    
    updateNextAvailableNumber() {
        const usedNumbers = this.markers.map(m => m.number);
        for (let i = 1; i <= 20; i++) {
            if (!usedNumbers.includes(i)) {
                this.nextAvailableNumber = i;
                this.selectedMarkerNumber = i;
                break;
            }
        }
        this.updateNumberSelection();
        const btn = document.getElementById('place-marker-btn');
        if (btn) btn.textContent = `📍 Place Marker #${this.selectedMarkerNumber}`;
    }
    
    activatePlacement() {
        // Check if number is already used
        if (this.markers.some(m => m.number === this.selectedMarkerNumber)) {
            this.app.ui.showToast(`Marker #${this.selectedMarkerNumber} is already placed`, 'warning', 2000);
            return;
        }
        
        this.isActive = true;
        
        // Enable canvas interaction
        this.canvas.style.pointerEvents = 'auto';
        this.canvas.style.cursor = 'crosshair';
        
        // Add event listeners
        this.canvas.addEventListener('click', this.boundHandleClick);
        document.addEventListener('keydown', this.boundHandleKeyDown);
        
        // Visual feedback
        const category = this.categories.find(c => c.id === this.selectedCategory);
        this.app.ui.showToast(`Click to place Marker #${this.selectedMarkerNumber} (${category.name}). Press Esc to cancel.`, 'info', 3000);
    }
    
    deactivate() {
        this.isActive = false;
        
        if (this.canvas) {
            this.canvas.style.pointerEvents = 'none';
            this.canvas.style.cursor = 'default';
            this.canvas.removeEventListener('click', this.boundHandleClick);
        }
        document.removeEventListener('keydown', this.boundHandleKeyDown);
        
        this.renderMarkers();
    }
    
    handleClick(e) {
        if (!this.isActive) return;
        
        const rect = this.canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width;
        const y = (e.clientY - rect.top) / rect.height;
        
        this.placeMarker(x, y);
    }
    
    handleKeyDown(e) {
        if (e.key === 'Escape') {
            this.deactivate();
        }
    }
    
    placeMarker(x, y) {
        const category = this.categories.find(c => c.id === this.selectedCategory);
        
        const marker = {
            id: `em-${Date.now()}`,
            number: this.selectedMarkerNumber,
            position: { x, y },
            label: '',
            description: '',
            category: this.selectedCategory,
            color: category.color,
            scene_version: this.app.currentVersion || 1,
            created_at: new Date().toISOString()
        };
        
        this.markers.push(marker);
        this.deactivate();
        
        // Save to backend
        this.saveMarker(marker);
        
        // Update UI
        this.updateMarkerList();
        this.updateNumberGridUsed();
        this.renderMarkers();
        
        // Prompt for description
        this.showEditDialog(marker);
        
        this.app.ui.showToast(`Marker #${marker.number} placed`, 'success', 2000);
        this.updateNextAvailableNumber();
    }
    
    showEditDialog(marker) {
        const label = prompt(`Label for Marker #${marker.number}:`, marker.label || '');
        if (label !== null) {
            marker.label = label;
            const desc = prompt(`Description for Marker #${marker.number}:`, marker.description || '');
            if (desc !== null) {
                marker.description = desc;
                this.updateMarkerBackend(marker);
                this.updateMarkerList();
                this.renderMarkers();
            }
        }
    }
    
    renderMarkers() {
        if (!this.ctx || !this.canvas) return;
        
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // Sort by number for consistent rendering
        const sortedMarkers = [...this.markers].sort((a, b) => a.number - b.number);
        
        sortedMarkers.forEach(marker => {
            this.drawMarker(marker, marker === this.selectedMarker);
        });
    }
    
    drawMarker(marker, isSelected = false) {
        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;
        
        const x = marker.position.x * w;
        const y = marker.position.y * h;
        const radius = isSelected ? 22 : 18;
        
        ctx.save();
        
        // Shadow
        ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
        ctx.shadowBlur = 8;
        ctx.shadowOffsetY = 3;
        
        // Outer circle
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fillStyle = marker.color;
        ctx.fill();
        
        // White inner circle
        ctx.shadowColor = 'transparent';
        ctx.beginPath();
        ctx.arc(x, y, radius - 4, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.fill();
        
        // Number
        ctx.fillStyle = marker.color;
        ctx.font = `bold ${radius - 4}px -apple-system, BlinkMacSystemFont, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(marker.number.toString(), x, y);
        
        // Selection ring
        if (isSelected) {
            ctx.strokeStyle = '#00d4ff';
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.arc(x, y, radius + 4, 0, Math.PI * 2);
            ctx.stroke();
        }
        
        // Label if exists
        if (marker.label) {
            const labelY = y + radius + 15;
            ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, sans-serif';
            const metrics = ctx.measureText(marker.label);
            const padding = 6;
            const labelW = Math.min(metrics.width + padding * 2, 150);
            
            // Background
            ctx.fillStyle = 'rgba(15, 25, 35, 0.9)';
            ctx.beginPath();
            ctx.roundRect(x - labelW / 2, labelY - 10, labelW, 20, 4);
            ctx.fill();
            
            // Border
            ctx.strokeStyle = marker.color;
            ctx.lineWidth = 1;
            ctx.stroke();
            
            // Text
            ctx.fillStyle = '#ffffff';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            const displayLabel = marker.label.length > 18 ? marker.label.substring(0, 15) + '...' : marker.label;
            ctx.fillText(displayLabel, x, labelY);
        }
        
        ctx.restore();
    }
    
    updateNumberGridUsed() {
        const grid = document.getElementById('marker-number-grid');
        if (!grid) return;
        grid.innerHTML = this.renderNumberGrid();
        
        // Rebind click handlers
        grid.querySelectorAll('.marker-number-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.selectedMarkerNumber = parseInt(btn.dataset.number);
                this.updateNumberSelection();
                document.getElementById('place-marker-btn').textContent = `📍 Place Marker #${this.selectedMarkerNumber}`;
            });
        });
    }
    
    updateMarkerList() {
        const listContainer = document.getElementById('marker-list-items');
        if (!listContainer) return;
        
        if (this.markers.length === 0) {
            listContainer.innerHTML = '<p class="empty-state">No markers placed</p>';
            return;
        }
        
        const sortedMarkers = [...this.markers].sort((a, b) => a.number - b.number);
        
        listContainer.innerHTML = sortedMarkers.map(m => {
            const category = this.categories.find(c => c.id === m.category);
            return `
                <div class="marker-item" data-id="${m.id}" style="border-left: 3px solid ${m.color}">
                    <span class="marker-num">#${m.number}</span>
                    <span class="marker-cat" title="${category.name}">${category.icon}</span>
                    <span class="marker-label">${m.label || '(no label)'}</span>
                    <button class="marker-edit" data-id="${m.id}" aria-label="Edit">✏️</button>
                    <button class="marker-delete" data-id="${m.id}" aria-label="Delete">🗑️</button>
                </div>
            `;
        }).join('');
        
        // Bind edit/delete events
        listContainer.querySelectorAll('.marker-edit').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.editMarker(btn.getAttribute('data-id'));
            });
        });
        
        listContainer.querySelectorAll('.marker-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteMarker(btn.getAttribute('data-id'));
            });
        });
        
        listContainer.querySelectorAll('.marker-item').forEach(item => {
            item.addEventListener('click', () => {
                this.selectMarker(item.getAttribute('data-id'));
            });
        });
    }
    
    selectMarker(id) {
        this.selectedMarker = this.markers.find(m => m.id === id) || null;
        this.renderMarkers();
        
        document.querySelectorAll('.marker-item').forEach(item => {
            item.classList.toggle('selected', item.getAttribute('data-id') === id);
        });
    }
    
    editMarker(id) {
        const marker = this.markers.find(m => m.id === id);
        if (!marker) return;
        
        this.showEditDialog(marker);
    }
    
    deleteMarker(id) {
        const idx = this.markers.findIndex(m => m.id === id);
        if (idx === -1) return;
        
        const marker = this.markers[idx];
        this.markers.splice(idx, 1);
        this.selectedMarker = null;
        
        // Delete from backend
        this.deleteMarkerBackend(marker.id);
        
        this.updateMarkerList();
        this.updateNumberGridUsed();
        this.renderMarkers();
        this.updateNextAvailableNumber();
        this.app.ui.showToast(`Marker #${marker.number} deleted`, 'info', 2000);
    }
    
    clearAllMarkers() {
        if (!confirm('Clear all evidence markers?')) return;
        
        // Delete each from backend
        this.markers.forEach(m => {
            this.deleteMarkerBackend(m.id);
        });
        
        this.markers = [];
        this.selectedMarker = null;
        this.updateMarkerList();
        this.updateNumberGridUsed();
        this.renderMarkers();
        this.updateNextAvailableNumber();
        this.app.ui.showToast('All markers cleared', 'info', 2000);
    }
    
    // Backend API methods
    async saveMarker(marker) {
        if (!this.app.sessionId) return;
        
        try {
            const response = await this.app.fetchWithTimeout(`/api/sessions/${this.app.sessionId}/evidence-markers`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    number: marker.number,
                    position: marker.position,
                    label: marker.label,
                    description: marker.description,
                    category: marker.category,
                    color: marker.color,
                    scene_version: marker.scene_version
                })
            });
            
            if (response.ok) {
                const saved = await response.json();
                marker.id = saved.id; // Update with server ID
            }
        } catch (error) {
            console.error('Failed to save evidence marker:', error);
        }
    }
    
    async updateMarkerBackend(marker) {
        if (!this.app.sessionId) return;
        
        try {
            await this.app.fetchWithTimeout(`/api/sessions/${this.app.sessionId}/evidence-markers/${marker.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    number: marker.number,
                    position: marker.position,
                    label: marker.label,
                    description: marker.description,
                    category: marker.category,
                    color: marker.color
                })
            });
        } catch (error) {
            console.error('Failed to update evidence marker:', error);
        }
    }
    
    async deleteMarkerBackend(markerId) {
        if (!this.app.sessionId) return;
        
        try {
            await this.app.fetchWithTimeout(`/api/sessions/${this.app.sessionId}/evidence-markers/${markerId}`, {
                method: 'DELETE'
            });
        } catch (error) {
            console.error('Failed to delete evidence marker:', error);
        }
    }
    
    async loadMarkers() {
        if (!this.app.sessionId) return;
        
        try {
            const response = await this.app.fetchWithTimeout(`/api/sessions/${this.app.sessionId}/evidence-markers`);
            if (response.ok) {
                const data = await response.json();
                this.markers = data.evidence_markers || [];
                this.updateMarkerList();
                this.updateNumberGridUsed();
                this.renderMarkers();
                this.updateNextAvailableNumber();
            }
        } catch (error) {
            console.error('Failed to load evidence markers:', error);
        }
    }
    
    exportMarkers() {
        if (this.markers.length === 0) {
            this.app.ui.showToast('No markers to export', 'warning', 2000);
            return;
        }
        
        const exportData = {
            session_id: this.app.sessionId,
            scene_version: this.app.currentVersion,
            exported_at: new Date().toISOString(),
            evidence_markers: this.markers.map(m => ({
                number: m.number,
                label: m.label,
                description: m.description,
                category: m.category,
                position: m.position
            }))
        };
        
        // Download as JSON
        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `evidence-markers-${this.app.sessionId}-${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
        
        this.app.ui.showToast('Evidence markers exported', 'success', 2000);
    }
    
    // Generate markers summary for reports
    getMarkersSummary() {
        return {
            total: this.markers.length,
            markers: this.markers.map(m => ({
                number: m.number,
                label: m.label,
                description: m.description,
                category: m.category
            }))
        };
    }
}

// Initialize evidence marker tool when app is ready
if (typeof window !== 'undefined') {
    window.EvidenceMarkerTool = EvidenceMarkerTool;
}
