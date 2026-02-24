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
    
    async loadClarifiedTimeline(sessionId) {
        /**
         * Load the disambiguated timeline with clarity indicators.
         */
        try {
            const response = await fetch(`/api/sessions/${sessionId}/timeline/clarified`, {
                headers: this.authToken ? { 'Authorization': `Bearer ${this.authToken}` } : {}
            });
            if (!response.ok) throw new Error('Failed to load clarified timeline');
            const clarifiedData = await response.json();
            this.clarifiedTimeline = clarifiedData;
            this.renderClarityOverlay();
            return clarifiedData;
        } catch (error) {
            console.error('Error loading clarified timeline:', error);
            return null;
        }
    }
    
    async getDisambiguationPrompt(sessionId) {
        /**
         * Get any pending disambiguation prompts for the timeline.
         */
        try {
            const response = await fetch(`/api/sessions/${sessionId}/timeline/disambiguation`, {
                headers: this.authToken ? { 'Authorization': `Bearer ${this.authToken}` } : {}
            });
            if (!response.ok) return null;
            return await response.json();
        } catch (error) {
            console.error('Error getting disambiguation prompt:', error);
            return null;
        }
    }
    
    renderClarityOverlay() {
        /**
         * Render clarity indicators over timeline events.
         */
        if (!this.clarifiedTimeline || !this.container) return;
        
        // Remove existing overlay
        const existingOverlay = this.container.querySelector('.clarity-overlay');
        if (existingOverlay) existingOverlay.remove();
        
        const overlay = document.createElement('div');
        overlay.className = 'clarity-overlay';
        
        // Add clarity summary
        const { overall_clarity, clarity_score, events_needing_clarification, total_events } = this.clarifiedTimeline;
        
        const clarityClass = overall_clarity === 'high' ? 'clarity-high' : 
                            overall_clarity === 'medium' ? 'clarity-medium' : 'clarity-low';
        
        overlay.innerHTML = `
            <div class="clarity-summary ${clarityClass}">
                <span class="clarity-label">Timeline Clarity:</span>
                <span class="clarity-score">${Math.round(clarity_score * 100)}%</span>
                <span class="clarity-level">(${overall_clarity})</span>
                ${events_needing_clarification > 0 ? `
                    <span class="clarity-warning">⚠️ ${events_needing_clarification} event(s) need clarification</span>
                ` : ''}
            </div>
        `;
        
        // Add event clarity markers
        if (this.clarifiedTimeline.events) {
            const markersContainer = document.createElement('div');
            markersContainer.className = 'clarity-markers';
            
            this.clarifiedTimeline.events.forEach((event, idx) => {
                if (event.needs_clarification) {
                    const marker = document.createElement('div');
                    marker.className = 'clarity-marker needs-clarification';
                    marker.title = event.clarification_question || 'Needs timeline clarification';
                    marker.dataset.eventId = event.id;
                    marker.innerHTML = `
                        <span class="marker-icon">⏱️</span>
                        <span class="marker-text">${this.escapeHtml(event.description.substring(0, 30))}...</span>
                        <span class="marker-clarity clarity-${event.clarity}">${event.clarity}</span>
                    `;
                    
                    // Click to show clarification dialog
                    marker.addEventListener('click', () => {
                        this.showClarificationDialog(event);
                    });
                    
                    markersContainer.appendChild(marker);
                }
            });
            
            if (markersContainer.children.length > 0) {
                overlay.appendChild(markersContainer);
            }
        }
        
        // Insert overlay before the timeline viewport
        const viewport = this.container.querySelector('.timeline-viewport');
        if (viewport) {
            viewport.parentNode.insertBefore(overlay, viewport);
        }
    }
    
    showClarificationDialog(event) {
        /**
         * Show a dialog for clarifying a vague timeline event.
         */
        const panel = this.container.querySelector('.timeline-detail-panel');
        const content = panel.querySelector('.detail-content');
        
        content.innerHTML = `
            <div class="detail-header clarification-header">
                <span class="detail-type">⏱️ Timeline Clarification Needed</span>
            </div>
            <div class="clarification-context">
                <strong>Event:</strong>
                <p>${this.escapeHtml(event.description)}</p>
            </div>
            <div class="clarification-issue">
                <strong>Time Reference:</strong>
                <span class="time-ref">${this.escapeHtml(event.original_time_ref || 'Not specified')}</span>
                <span class="clarity-badge clarity-${event.clarity}">${event.clarity}</span>
            </div>
            ${event.clarification_question ? `
                <div class="clarification-prompt">
                    <strong>Suggested Question:</strong>
                    <p class="suggested-question">"${this.escapeHtml(event.clarification_question)}"</p>
                </div>
            ` : ''}
            <div class="clarification-input">
                <label>Clarified Timing:</label>
                <input type="text" class="clarify-offset-input" 
                       placeholder="e.g., 'about 2 minutes after the car arrived'">
                <button class="btn btn-primary apply-clarification-btn" data-event-id="${event.id}">
                    Apply Clarification
                </button>
            </div>
            <div class="sequence-position">
                <label>Sequence Position:</label>
                <input type="number" class="clarify-sequence-input" 
                       value="${event.sequence}" min="1">
            </div>
        `;
        
        // Setup apply handler
        const applyBtn = content.querySelector('.apply-clarification-btn');
        applyBtn.addEventListener('click', async () => {
            const offsetInput = content.querySelector('.clarify-offset-input');
            const sequenceInput = content.querySelector('.clarify-sequence-input');
            
            await this.applyClarification(event.id, {
                offset_description: offsetInput.value,
                sequence: parseInt(sequenceInput.value, 10)
            });
        });
        
        panel.style.display = 'block';
    }
    
    async applyClarification(eventId, clarification) {
        /**
         * Apply a clarification to a timeline event.
         */
        if (!this.data?.session_id && !this.clarifiedTimeline?.session_id) {
            console.error('No session ID available');
            return false;
        }
        
        const sessionId = this.data?.session_id || this.clarifiedTimeline?.session_id;
        
        try {
            const response = await fetch(`/api/sessions/${sessionId}/timeline/clarify`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(this.authToken ? { 'Authorization': `Bearer ${this.authToken}` } : {})
                },
                body: JSON.stringify({
                    event_id: eventId,
                    offset_description: clarification.offset_description,
                    sequence: clarification.sequence
                })
            });
            
            if (!response.ok) throw new Error('Failed to apply clarification');
            
            const result = await response.json();
            
            // Refresh the clarified timeline
            await this.loadClarifiedTimeline(sessionId);
            this.hideDetailPanel();
            
            // Show success
            if (window.adminPortal?.showToast) {
                window.adminPortal.showToast('Timeline clarification applied', 'success');
            }
            
            return true;
        } catch (error) {
            console.error('Error applying clarification:', error);
            if (window.adminPortal?.showToast) {
                window.adminPortal.showToast('Failed to apply clarification', 'error');
            }
            return false;
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
        
        // Check for low confidence / needs review
        const confidence = event.confidence || 0.5;
        const needsReview = event.needs_review || confidence < 0.7;
        if (needsReview) {
            marker.classList.add('needs-review');
        }
        
        // Add confidence class for styling
        const confClass = confidence >= 0.7 ? 'conf-high' : confidence >= 0.4 ? 'conf-med' : 'conf-low';
        marker.classList.add(confClass);
        
        // Tooltip on hover with confidence
        const confText = needsReview ? ` [${Math.round(confidence * 100)}% - Needs Review]` : ` [${Math.round(confidence * 100)}%]`;
        marker.title = `${event.type}: ${event.description}\n${this.formatTime(eventTime)}${confText}`;
        
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
        
        // Calculate confidence display
        const confidence = event.confidence || 0.5;
        const needsReview = event.needs_review || confidence < 0.7;
        const confPercent = Math.round(confidence * 100);
        const confClass = confidence >= 0.7 ? 'high' : confidence >= 0.4 ? 'med' : 'low';
        const confLabel = confidence >= 0.7 ? 'High' : confidence >= 0.4 ? 'Medium' : 'Low';
        
        content.innerHTML = `
            <div class="detail-header">
                <span class="detail-type ${event.type}">${this.getEventIcon(event.type)} ${event.type}</span>
                <span class="detail-time">${this.formatTime(new Date(event.event_time))}</span>
            </div>
            <div class="detail-confidence">
                <strong>Confidence:</strong>
                <span class="confidence-badge ${confClass}">${confPercent}% (${confLabel})</span>
                ${needsReview ? '<span class="review-badge">⚠️ Needs Review</span>' : ''}
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
