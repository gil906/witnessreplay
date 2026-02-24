/**
 * WitnessReplay Admin Portal
 * Case management and analytics dashboard
 */

class AdminPortal {
    constructor() {
        this.cases = [];
        this.filteredCases = [];
        this.currentCase = null;
        this.fetchTimeout = 10000; // 10 second timeout
        
        this.init();
    }
    
    async init() {
        this.initializeUI();
        await this.loadCases();
        this.startAutoRefresh();
        this.fetchAndDisplayVersion(); // Fetch version from API
    }
    
    initializeUI() {
        // Modal handlers
        document.querySelectorAll('.modal-close, [data-modal]').forEach(el => {
            el.addEventListener('click', (e) => {
                const modalId = e.target.dataset.modal;
                if (modalId) {
                    this.hideModal(modalId);
                }
            });
        });
        
        // Header actions
        document.getElementById('refresh-btn').addEventListener('click', () => this.loadCases());
        document.getElementById('witness-view-btn').addEventListener('click', () => {
            window.location.href = '/static/index.html';
        });
        
        // Search and filters
        document.getElementById('case-search').addEventListener('input', (e) => {
            this.filterCases();
        });
        document.getElementById('search-btn').addEventListener('click', () => this.filterCases());
        document.getElementById('filter-type').addEventListener('change', () => this.filterCases());
        document.getElementById('filter-status').addEventListener('change', () => this.filterCases());
        document.getElementById('sort-by').addEventListener('change', () => this.filterCases());
        document.getElementById('clear-filters-btn').addEventListener('click', () => this.clearFilters());
        
        // Case creation
        document.getElementById('new-case-btn').addEventListener('click', () => {
            this.showModal('create-case-modal');
        });
        document.getElementById('create-case-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.createCase();
        });
        
        // Case detail actions
        document.getElementById('export-case-btn')?.addEventListener('click', () => this.exportCase());
        document.getElementById('export-evidence-btn')?.addEventListener('click', () => this.exportEvidence());
        document.getElementById('mark-complete-btn')?.addEventListener('click', () => this.markComplete());
        document.getElementById('delete-case-btn')?.addEventListener('click', () => this.deleteCase());
    }
    
    async fetchWithTimeout(url, options = {}) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.fetchTimeout);
        
        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            return response;
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                throw new Error('Request timeout');
            }
            throw error;
        }
    }
    
    async loadCases() {
        try {
            const response = await this.fetchWithTimeout('/api/sessions');
            
            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }
            
            const data = await response.json();
            this.cases = data.sessions || [];
            this.updateStats();
            this.filterCases();
            this.showToast('Cases loaded successfully', 'success');
        } catch (error) {
            console.error('Error loading cases:', error);
            this.showToast('Failed to load cases: ' + error.message, 'error');
            this.renderEmptyState();
        }
    }
    
    updateStats() {
        const totalCases = this.cases.length;
        const totalStatements = this.cases.reduce((sum, c) => sum + (c.statement_count || 0), 0);
        const totalScenes = this.cases.reduce((sum, c) => sum + (c.version_count || 0), 0);
        
        const today = new Date().toDateString();
        const activeToday = this.cases.filter(c => {
            if (!c.created_at) return false;
            return new Date(c.created_at).toDateString() === today;
        }).length;
        
        document.getElementById('total-cases').textContent = totalCases;
        document.getElementById('total-witnesses').textContent = totalStatements;
        document.getElementById('active-today').textContent = activeToday;
        document.getElementById('total-scenes').textContent = totalScenes;
    }
    
    filterCases() {
        const searchTerm = document.getElementById('case-search').value.toLowerCase();
        const typeFilter = document.getElementById('filter-type').value;
        const statusFilter = document.getElementById('filter-status').value;
        const sortBy = document.getElementById('sort-by').value;
        
        this.filteredCases = this.cases.filter(c => {
            const matchesSearch = !searchTerm || 
                c.id.toLowerCase().includes(searchTerm) ||
                (c.case_type || '').toLowerCase().includes(searchTerm) ||
                (c.metadata?.location || '').toLowerCase().includes(searchTerm);
            
            const matchesType = !typeFilter || c.case_type === typeFilter;
            const matchesStatus = !statusFilter || (c.metadata?.status || 'active') === statusFilter;
            
            return matchesSearch && matchesType && matchesStatus;
        });
        
        // Sort
        this.filteredCases.sort((a, b) => {
            switch (sortBy) {
                case 'date-desc':
                    return new Date(b.created_at || 0) - new Date(a.created_at || 0);
                case 'date-asc':
                    return new Date(a.created_at || 0) - new Date(b.created_at || 0);
                case 'witnesses-desc':
                    return (b.statement_count || 0) - (a.statement_count || 0);
                case 'scenes-desc':
                    return (b.version_count || 0) - (a.version_count || 0);
                default:
                    return 0;
            }
        });
        
        this.renderCases();
    }
    
    clearFilters() {
        document.getElementById('case-search').value = '';
        document.getElementById('filter-type').value = '';
        document.getElementById('filter-status').value = '';
        document.getElementById('sort-by').value = 'date-desc';
        this.filterCases();
    }
    
    renderCases() {
        const container = document.getElementById('cases-list');
        
        if (this.filteredCases.length === 0) {
            container.innerHTML = '<div class="empty-state">No cases found matching your criteria</div>';
            return;
        }
        
        container.innerHTML = this.filteredCases.map(c => this.renderCaseCard(c)).join('');
        
        // Add click handlers
        container.querySelectorAll('.case-card').forEach((card, index) => {
            card.addEventListener('click', () => {
                this.showCaseDetail(this.filteredCases[index]);
            });
        });
    }
    
    renderCaseCard(caseData) {
        const caseType = caseData.case_type || 'incident';
        const status = caseData.metadata?.status || 'active';
        const icon = this.getCaseIcon(caseType);
        const statusClass = `status-${status}`;
        
        const created = new Date(caseData.created_at || Date.now());
        const updated = new Date(caseData.updated_at || caseData.created_at || Date.now());
        
        return `
            <div class="case-card" data-case-id="${caseData.id}">
                <div class="case-icon">${icon}</div>
                <div class="case-info">
                    <div class="case-header">
                        <div>
                            <h3 class="case-title">${this.formatCaseType(caseType)}</h3>
                            <div class="case-id">${caseData.id}</div>
                        </div>
                        <div class="case-status-badge ${statusClass}">
                            ${status}
                        </div>
                    </div>
                    <div class="case-meta">
                        <div class="case-meta-item">
                            <span>📅</span>
                            <span>${this.formatDate(created)}</span>
                        </div>
                        <div class="case-meta-item">
                            <span>🕐</span>
                            <span>${this.formatDuration(caseData.total_duration || 0)}</span>
                        </div>
                        ${caseData.metadata?.location ? `
                        <div class="case-meta-item">
                            <span>📍</span>
                            <span>${caseData.metadata.location}</span>
                        </div>
                        ` : ''}
                    </div>
                    ${caseData.metadata?.description ? `
                    <p class="case-description">${caseData.metadata.description}</p>
                    ` : ''}
                </div>
                <div class="case-stats">
                    <div class="case-stat">
                        <span class="case-stat-value">${caseData.statement_count || 0}</span>
                        <span class="case-stat-label">Statements</span>
                    </div>
                    <div class="case-stat">
                        <span class="case-stat-value">${caseData.version_count || 0}</span>
                        <span class="case-stat-label">Scenes</span>
                    </div>
                </div>
            </div>
        `;
    }
    
    async showCaseDetail(caseData) {
        this.currentCase = caseData;
        
        // Populate basic info
        document.getElementById('detail-case-id').textContent = caseData.id;
        document.getElementById('detail-case-type').textContent = this.formatCaseType(caseData.case_type);
        document.getElementById('detail-case-status').textContent = caseData.metadata?.status || 'active';
        document.getElementById('detail-created').textContent = this.formatDateTime(caseData.created_at);
        document.getElementById('detail-updated').textContent = this.formatDateTime(caseData.updated_at || caseData.created_at);
        document.getElementById('detail-duration').textContent = this.formatDuration(caseData.total_duration || 0);
        
        // Load full session data
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${caseData.id}`);
            if (response.ok) {
                const fullData = await response.json();
                this.renderWitnessStatements(fullData);
                this.renderSceneGallery(fullData);
                this.renderAnalytics(fullData);
            }
        } catch (error) {
            console.error('Error loading case details:', error);
            this.showToast('Failed to load full case details', 'warning');
        }
        
        this.showModal('case-detail-modal');
    }
    
    renderWitnessStatements(caseData) {
        const container = document.getElementById('witness-statements');
        const statements = caseData.statements || [];
        
        document.getElementById('witness-count').textContent = statements.length;
        
        if (statements.length === 0) {
            container.innerHTML = '<p class="empty-state">No statements recorded yet</p>';
            return;
        }
        
        container.innerHTML = statements.map((stmt, i) => `
            <div class="statement-item">
                <div class="statement-header">
                    <span class="statement-number">Statement #${i + 1}</span>
                    <span class="statement-time">${stmt.timestamp ? this.formatTime(stmt.timestamp) : ''}</span>
                </div>
                <p class="statement-text">${stmt.text || stmt.content || 'No content'}</p>
            </div>
        `).join('');
    }
    
    renderSceneGallery(caseData) {
        const container = document.getElementById('scene-versions');
        const scenes = caseData.scene_versions || [];
        
        document.getElementById('scene-count').textContent = scenes.length;
        
        if (scenes.length === 0) {
            container.innerHTML = '<p class="empty-state">No scenes generated yet</p>';
            return;
        }
        
        container.innerHTML = scenes.map((scene, i) => `
            <div class="scene-item">
                <img src="${scene.image_url}" alt="Scene version ${i + 1}" loading="lazy">
                <div class="scene-version-badge">v${i + 1}</div>
            </div>
        `).join('');
    }
    
    renderAnalytics(caseData) {
        const insights = caseData.insights || {};
        
        // Completeness
        const completeness = insights.completeness_score || 0;
        document.getElementById('completeness-bar').style.width = `${completeness}%`;
        document.getElementById('completeness-text').textContent = `${completeness}%`;
        
        // Contradictions
        const contradictions = insights.contradictions || [];
        const contradictionsContainer = document.getElementById('contradictions-list');
        if (contradictions.length === 0) {
            contradictionsContainer.innerHTML = '<p class="empty-state">No contradictions detected</p>';
        } else {
            contradictionsContainer.innerHTML = contradictions.map(c => `
                <div class="contradiction-item">• ${c}</div>
            `).join('');
        }
        
        // Key elements
        const elements = insights.key_elements || [];
        const elementsContainer = document.getElementById('key-elements-list');
        if (elements.length === 0) {
            elementsContainer.innerHTML = '<p class="empty-state">No elements extracted</p>';
        } else {
            elementsContainer.innerHTML = elements.map(e => `
                <span class="tag">${e}</span>
            `).join('');
        }
    }
    
    async createCase() {
        const caseType = document.getElementById('new-case-type').value;
        const location = document.getElementById('new-case-location').value;
        const description = document.getElementById('new-case-description').value;
        
        if (!caseType) {
            this.showToast('Please select a case type', 'warning');
            return;
        }
        
        try {
            const response = await this.fetchWithTimeout('/api/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    case_type: caseType,
                    metadata: {
                        location,
                        description,
                        status: 'active'
                    }
                })
            });
            
            if (!response.ok) {
                throw new Error('Failed to create case');
            }
            
            const data = await response.json();
            this.showToast('Case created successfully', 'success');
            this.hideModal('create-case-modal');
            document.getElementById('create-case-form').reset();
            await this.loadCases();
            
            // Open the new case
            const newCase = this.cases.find(c => c.id === data.session_id);
            if (newCase) {
                this.showCaseDetail(newCase);
            }
        } catch (error) {
            console.error('Error creating case:', error);
            this.showToast('Failed to create case: ' + error.message, 'error');
        }
    }
    
    async exportCase() {
        if (!this.currentCase) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${this.currentCase.id}/export/json`);
            if (!response.ok) throw new Error('Export failed');
            
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `case_${this.currentCase.id}_${Date.now()}.json`;
            a.click();
            window.URL.revokeObjectURL(url);
            
            this.showToast('Case exported successfully', 'success');
        } catch (error) {
            console.error('Error exporting case:', error);
            this.showToast('Failed to export case', 'error');
        }
    }
    
    async exportEvidence() {
        if (!this.currentCase) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${this.currentCase.id}/export`);
            if (!response.ok) throw new Error('Export failed');
            
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `evidence_${this.currentCase.id}_${Date.now()}.pdf`;
            a.click();
            window.URL.revokeObjectURL(url);
            
            this.showToast('Evidence exported successfully', 'success');
        } catch (error) {
            console.error('Error exporting evidence:', error);
            this.showToast('Failed to export evidence', 'error');
        }
    }
    
    async markComplete() {
        if (!this.currentCase) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${this.currentCase.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    metadata: {
                        ...this.currentCase.metadata,
                        status: 'complete'
                    }
                })
            });
            
            if (!response.ok) throw new Error('Update failed');
            
            this.showToast('Case marked as complete', 'success');
            this.hideModal('case-detail-modal');
            await this.loadCases();
        } catch (error) {
            console.error('Error updating case:', error);
            this.showToast('Failed to update case status', 'error');
        }
    }
    
    async deleteCase() {
        if (!this.currentCase) return;
        
        if (!confirm(`Are you sure you want to delete case ${this.currentCase.id}? This cannot be undone.`)) {
            return;
        }
        
        try {
            const response = await this.fetchWithTimeout(`/api/sessions/${this.currentCase.id}`, {
                method: 'DELETE'
            });
            
            if (!response.ok) throw new Error('Delete failed');
            
            this.showToast('Case deleted successfully', 'success');
            this.hideModal('case-detail-modal');
            await this.loadCases();
        } catch (error) {
            console.error('Error deleting case:', error);
            this.showToast('Failed to delete case', 'error');
        }
    }
    
    showModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('active');
        }
    }
    
    hideModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('active');
        }
    }
    
    showToast(message, type = 'info', duration = 3000) {
        const container = document.getElementById('toast-container') || this.createToastContainer();
        
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.classList.add('show');
        }, 10);
        
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
    
    createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
        return container;
    }
    
    renderEmptyState() {
        document.getElementById('cases-list').innerHTML = `
            <div class="empty-state">
                <p>No cases found. Create a new case to get started.</p>
                <button class="btn btn-primary" onclick="document.getElementById('new-case-btn').click()">
                    ➕ Create First Case
                </button>
            </div>
        `;
    }
    
    startAutoRefresh() {
        setInterval(() => {
            this.loadCases();
        }, 30000); // Refresh every 30 seconds
    }
    
    // Utility functions
    getCaseIcon(type) {
        const icons = {
            accident: '🚗',
            crime: '🔪',
            incident: '⚠️',
            other: '📝'
        };
        return icons[type] || icons.other;
    }
    
    formatCaseType(type) {
        const types = {
            accident: 'Traffic Accident',
            crime: 'Criminal Investigation',
            incident: 'General Incident',
            other: 'Other Case'
        };
        return types[type] || type;
    }
    
    formatDate(date) {
        if (!date) return 'Unknown';
        const d = new Date(date);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }
    
    formatDateTime(date) {
        if (!date) return 'Unknown';
        const d = new Date(date);
        return d.toLocaleString('en-US', { 
            month: 'short', 
            day: 'numeric', 
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }
    
    formatTime(time) {
        if (!time) return '';
        const d = new Date(time);
        return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    }
    
    formatDuration(seconds) {
        if (!seconds || seconds < 60) return `${Math.round(seconds)}s`;
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m`;
        const hours = Math.floor(minutes / 60);
        const remainingMinutes = minutes % 60;
        return `${hours}h ${remainingMinutes}m`;
    }
    
    // ======================================
    // Version Display
    // ======================================
    
    async fetchAndDisplayVersion() {
        try {
            const response = await this.fetchWithTimeout('/api/version', {}, 5000);
            if (!response.ok) {
                console.error('Failed to fetch version');
                return;
            }
            const data = await response.json();
            const versionEl = document.querySelector('.version-number');
            if (versionEl && data.version) {
                versionEl.textContent = data.version;
            }
        } catch (error) {
            console.error('Error fetching version:', error);
            // Keep default version shown in HTML
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.adminPortal = new AdminPortal();
});
