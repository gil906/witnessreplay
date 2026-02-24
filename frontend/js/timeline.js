/**
 * WitnessReplay - Interactive Timeline Visualization
 * Shows events chronologically with witness swim lanes, contradiction highlighting,
 * zoom controls, and editable event times.
 */

class TimelineVisualization {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.error(`Timeline container #${containerId} not found`);
            return;
        }
        
        this.options = {
            swimLaneHeight: 80,
            eventRadius: 12,
            minZoom: 0.5,
            maxZoom: 3,
            defaultZoom: 1,
            timeFormat: 'short',
            showContradictions: true,
            editable: true,
            ...options
        };
        
        this.data = null;
        this.zoom = this.options.defaultZoom;
        this.panOffset = 0;
        this.isDragging = false;
        this.dragStartX = 0;
        this.selectedEvent = null;
        this.authToken = null;
        
        this.init();
    }
    
    init() {
        this.container.innerHTML = `
            <div class="timeline-viz-wrapper">
                <div class="timeline-controls">
                    <button class="timeline-btn zoom-in" title="Zoom In">🔍+</button>
                    <button class="timeline-btn zoom-out" title="Zoom Out">🔍−</button>
                    <button class="timeline-btn zoom-reset" title="Reset Zoom">↺</button>
                    <span class="zoom-level">100%</span>
                    <div class="timeline-legend">
                        <span class="legend-item statement">● Statement</span>
                        <span class="legend-item correction">● Correction</span>
                        <span class="legend-item scene">● Scene</span>
                        <span class="legend-item conflict">⚠ Conflict</span>
                    </div>
                </div>
                <div class="timeline-viewport">
                    <div class="timeline-canvas">
                        <div class="timeline-lanes"></div>
                        <div class="timeline-axis"></div>
                    </div>
                </div>
                <div class="timeline-detail-panel" style="display:none;">
                    <button class="detail-close">✕</button>
                    <div class="detail-content"></div>
                </div>
            </div>
        `;
        
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        const wrapper = this.container.querySelector('.timeline-viz-wrapper');
        const viewport = this.container.querySelector('.timeline-viewport');
        
        // Zoom controls
        wrapper.querySelector('.zoom-in').addEventListener('click', () => this.zoomIn());
        wrapper.querySelector('.zoom-out').addEventListener('click', () => this.zoomOut());
        wrapper.querySelector('.zoom-reset').addEventListener('click', () => this.resetZoom());
        
        // Pan with mouse drag
        viewport.addEventListener('mousedown', (e) => this.startDrag(e));
        viewport.addEventListener('mousemove', (e) => this.drag(e));
        viewport.addEventListener('mouseup', () => this.endDrag());
        viewport.addEventListener('mouseleave', () => this.endDrag());
        
        // Zoom with wheel
        viewport.addEventListener('wheel', (e) => {
            e.preventDefault();
            if (e.deltaY < 0) this.zoomIn(0.1);
            else this.zoomOut(0.1);
        }, { passive: false });
        
        // Close detail panel
        wrapper.querySelector('.detail-close').addEventListener('click', () => {
            this.hideDetailPanel();
        });
    }
    
    setAuthToken(token) {
        this.authToken = token;
    }
    
    async loadCaseTimeline(caseId) {
        try {
            const response = await fetch(`/api/cases/${caseId}/timeline/visualization`, {
                headers: this.authToken ? { 'Authorization': `Bearer ${this.authToken}` } : {}
            });
            if (!response.ok) throw new Error('Failed to load timeline');
            this.data = await response.json();
            this.render();
        } catch (error) {
            console.error('Error loading case timeline:', error);
            this.showError('Failed to load timeline data');
        }
    }
    
    async loadSessionTimeline(sessionId) {
        try {
            const response = await fetch(`/api/sessions/${sessionId}/timeline/visualization`, {
                headers: this.authToken ? { 'Authorization': `Bearer ${this.authToken}` } : {}
            });
            if (!response.ok) throw new Error('Failed to load timeline');
            this.data = await response.json();
            this.render();
        } catch (error) {
            console.error('Error loading session timeline:', error);
            this.showError('Failed to load timeline data');
        }
    }
    
    setData(data) {
        this.data = data;
        this.render();
    }
    
    render() {
        if (!this.data) return;
        
        const lanesContainer = this.container.querySelector('.timeline-lanes');
        const axisContainer = this.container.querySelector('.timeline-axis');
        
        if (!lanesContainer || !axisContainer) return;
        
        const { witnesses, events, contradictions, time_bounds } = this.data;
        
        // Calculate time scale
        const timeRange = this.calculateTimeRange(time_bounds);
        const canvasWidth = Math.max(800, timeRange.durationMinutes * 10 * this.zoom);
        
        // Render swim lanes
        lanesContainer.innerHTML = '';
        lanesContainer.style.width = `${canvasWidth}px`;
        
        witnesses.forEach((witness, index) => {
            const lane = this.createSwimLane(witness, index, events, contradictions, canvasWidth, timeRange);
            lanesContainer.appendChild(lane);
        });
        
        // Render time axis
        this.renderTimeAxis(axisContainer, timeRange, canvasWidth);
        
        // Update zoom display
        this.container.querySelector('.zoom-level').textContent = `${Math.round(this.zoom * 100)}%`;
    }
    
    calculateTimeRange(time_bounds) {
        const now = new Date();
        let earliest = time_bounds.earliest ? new Date(time_bounds.earliest) : now;
        let latest = time_bounds.latest ? new Date(time_bounds.latest) : now;
        
        // Add padding
        const padding = Math.max(5, (latest - earliest) * 0.1);
        earliest = new Date(earliest.getTime() - padding);
        latest = new Date(latest.getTime() + padding);
        
        const durationMs = latest - earliest;
        const durationMinutes = durationMs / 60000;
        
        return { earliest, latest, durationMs, durationMinutes };
    }
    
    createSwimLane(witness, index, events, contradictions, canvasWidth, timeRange) {
        const lane = document.createElement('div');
        lane.className = 'swim-lane';
        lane.style.height = `${this.options.swimLaneHeight}px`;
        
        // Lane label
        const label = document.createElement('div');
        label.className = 'swim-lane-label';
        label.innerHTML = `
            <span class="witness-name">${this.escapeHtml(witness.name)}</span>
            <span class="witness-source">${witness.source_type || 'chat'}</span>
        `;
        lane.appendChild(label);
        
        // Lane track
        const track = document.createElement('div');
        track.className = 'swim-lane-track';
        track.style.width = `${canvasWidth}px`;
        
        // Timeline line
        const line = document.createElement('div');
        line.className = 'lane-timeline-line';
        track.appendChild(line);
        
        // Events for this witness
        const witnessEvents = events.filter(e => e.witness_id === witness.id);
        
        witnessEvents.forEach(event => {
            const eventEl = this.createEventMarker(event, timeRange, canvasWidth, contradictions);
            if (eventEl) track.appendChild(eventEl);
        });
        
        lane.appendChild(track);
        return lane;
    }
    
    createEventMarker(event, timeRange, canvasWidth, contradictions) {
        if (!event.event_time) return null;
        
        const eventTime = new Date(event.event_time);
        const position = ((eventTime - timeRange.earliest) / timeRange.durationMs) * canvasWidth;
        
        if (position < 0 || position > canvasWidth) return null;
        
        const marker = document.createElement('div');
        marker.className = `event-marker event-${event.type}`;
        marker.style.left = `${position}px`;
        marker.dataset.eventId = event.id;
        
        // Check for contradictions
        const hasContradiction = contradictions.some(c => c.event_ids.includes(event.id));
        if (hasContradiction) {
            marker.classList.add('has-conflict');
        }
        
        // Tooltip on hover
        marker.title = `${event.type}: ${event.description}\n${this.formatTime(eventTime)}`;
        
        // Click to show details
        marker.addEventListener('click', (e) => {
            e.stopPropagation();
            this.showEventDetail(event, contradictions);
        });
        
        // Event icon/content
        const icon = this.getEventIcon(event.type);
        marker.innerHTML = `<span class="event-icon">${icon}</span>`;
        
        return marker;
    }
    
    renderTimeAxis(container, timeRange, canvasWidth) {
        container.innerHTML = '';
        container.style.width = `${canvasWidth}px`;
        
        // Calculate tick intervals based on duration
        const durationMinutes = timeRange.durationMinutes;
        let tickIntervalMinutes;
        
        if (durationMinutes <= 30) tickIntervalMinutes = 5;
        else if (durationMinutes <= 120) tickIntervalMinutes = 15;
        else if (durationMinutes <= 480) tickIntervalMinutes = 60;
        else tickIntervalMinutes = 240;
        
        const tickIntervalMs = tickIntervalMinutes * 60000;
        let tickTime = new Date(Math.ceil(timeRange.earliest.getTime() / tickIntervalMs) * tickIntervalMs);
        
        while (tickTime <= timeRange.latest) {
            const position = ((tickTime - timeRange.earliest) / timeRange.durationMs) * canvasWidth;
            
            const tick = document.createElement('div');
            tick.className = 'time-tick';
            tick.style.left = `${position}px`;
            
            const label = document.createElement('span');
            label.className = 'tick-label';
            label.textContent = this.formatAxisTime(tickTime);
            tick.appendChild(label);
            
            container.appendChild(tick);
            
            tickTime = new Date(tickTime.getTime() + tickIntervalMs);
        }
    }
    
    showEventDetail(event, contradictions) {
        const panel = this.container.querySelector('.timeline-detail-panel');
        const content = panel.querySelector('.detail-content');
        
        // Find related contradictions
        const relatedContradictions = contradictions.filter(c => c.event_ids.includes(event.id));
        
        content.innerHTML = `
            <div class="detail-header">
                <span class="detail-type ${event.type}">${this.getEventIcon(event.type)} ${event.type}</span>
                <span class="detail-time">${this.formatTime(new Date(event.event_time))}</span>
            </div>
            <div class="detail-witness">
                <strong>Witness:</strong> ${this.escapeHtml(event.witness_name)}
            </div>
            <div class="detail-text">
                <strong>Description:</strong>
                <p>${this.escapeHtml(event.full_text || event.description)}</p>
            </div>
            ${event.image_url ? `
                <div class="detail-image">
                    <img src="${event.image_url}" alt="Scene" loading="lazy">
                </div>
            ` : ''}
            ${relatedContradictions.length > 0 ? `
                <div class="detail-contradictions">
                    <strong>⚠️ Potential Contradictions:</strong>
                    ${relatedContradictions.map(c => `
                        <div class="contradiction-item">
                            <span class="severity-${c.severity}">${c.severity}</span>
                            ${this.escapeHtml(c.description)}
                        </div>
                    `).join('')}
                </div>
            ` : ''}
            ${event.editable && this.options.editable ? `
                <div class="detail-edit">
                    <label>Edit Time:</label>
                    <input type="datetime-local" class="edit-time-input" 
                           value="${event.event_time.slice(0, 16)}">
                    <button class="btn btn-primary save-time-btn" data-event-id="${event.id}">
                        Save Time
                    </button>
                </div>
            ` : ''}
        `;
        
        // Setup edit handler
        const saveBtn = content.querySelector('.save-time-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => {
                const input = content.querySelector('.edit-time-input');
                this.updateEventTime(event.id, input.value);
            });
        }
        
        panel.style.display = 'block';
        this.selectedEvent = event;
    }
    
    hideDetailPanel() {
        const panel = this.container.querySelector('.timeline-detail-panel');
        panel.style.display = 'none';
        this.selectedEvent = null;
    }
    
    async updateEventTime(eventId, newTime) {
        if (!this.data) return;
        
        const caseId = this.data.case_id;
        if (!caseId) {
            console.error('No case ID available for update');
            return;
        }
        
        try {
            const response = await fetch(`/api/cases/${caseId}/timeline/events/${eventId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    ...(this.authToken ? { 'Authorization': `Bearer ${this.authToken}` } : {})
                },
                body: JSON.stringify({ event_time: new Date(newTime).toISOString() })
            });
            
            if (!response.ok) throw new Error('Failed to update event time');
            
            // Refresh the timeline
            await this.loadCaseTimeline(caseId);
            this.hideDetailPanel();
            
            // Show success toast if available
            if (window.adminPortal?.showToast) {
                window.adminPortal.showToast('Event time updated', 'success');
            }
        } catch (error) {
            console.error('Error updating event time:', error);
            if (window.adminPortal?.showToast) {
                window.adminPortal.showToast('Failed to update event time', 'error');
            }
        }
    }
    
    // Zoom controls
    zoomIn(amount = 0.2) {
        this.zoom = Math.min(this.options.maxZoom, this.zoom + amount);
        this.render();
    }
    
    zoomOut(amount = 0.2) {
        this.zoom = Math.max(this.options.minZoom, this.zoom - amount);
        this.render();
    }
    
    resetZoom() {
        this.zoom = this.options.defaultZoom;
        this.panOffset = 0;
        this.render();
    }
    
    // Pan controls
    startDrag(e) {
        this.isDragging = true;
        this.dragStartX = e.clientX - this.panOffset;
        this.container.querySelector('.timeline-viewport').style.cursor = 'grabbing';
    }
    
    drag(e) {
        if (!this.isDragging) return;
        this.panOffset = e.clientX - this.dragStartX;
        const canvas = this.container.querySelector('.timeline-canvas');
        canvas.style.transform = `translateX(${this.panOffset}px)`;
    }
    
    endDrag() {
        this.isDragging = false;
        this.container.querySelector('.timeline-viewport').style.cursor = 'grab';
    }
    
    // Utility methods
    getEventIcon(type) {
        const icons = {
            'statement': '💬',
            'correction': '✏️',
            'timeline_event': '📌',
            'scene_generation': '🎬',
        };
        return icons[type] || '●';
    }
    
    formatTime(date) {
        return date.toLocaleString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }
    
    formatAxisTime(date) {
        return date.toLocaleTimeString(undefined, {
            hour: '2-digit',
            minute: '2-digit'
        });
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }
    
    showError(message) {
        this.container.innerHTML = `
            <div class="timeline-error">
                <span class="error-icon">⚠️</span>
                <p>${this.escapeHtml(message)}</p>
            </div>
        `;
    }
}

// Export for use in other modules
window.TimelineVisualization = TimelineVisualization;
