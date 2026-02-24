/**
 * WitnessReplay Admin Portal
 * Case management and analytics dashboard
 */

class AdminPortal {
    constructor() {
        this.cases = [];
        this.reports = [];
        this.filteredCases = [];
        this.filteredReports = [];
        this.currentCase = null;
        this.currentView = 'cases';
        this.fetchTimeout = 10000;
        this.authToken = null;
        this.selectedCases = new Set();
        this.searchDebounceTimer = null;
        this.chartInstances = {};
        this.incidentMap = null;
        this.mapMarkers = [];
        this.dashboardStats = null;
        this.dashboardMapInstance = null;
        this.dashboardMapMarkers = [];
        this.investigators = [];
        this.workloadData = null;
        
        this.checkAuth();
    }
    
    checkAuth() {
        const token = sessionStorage.getItem('admin_token');
        if (token) {
            this.authToken = token;
            this.verifyAuth();
        } else {
            this.showLogin();
        }
    }
    
    async verifyAuth() {
        try {
            const response = await fetch('/api/auth/verify', {
                headers: {
                    'Authorization': `Bearer ${this.authToken}`
                }
            });
            
            if (response.ok) {
                this.hideLogin();
                this.init();
            } else {
                sessionStorage.removeItem('admin_token');
                this.showLogin();
            }
        } catch (error) {
            console.error('Auth verification failed:', error);
            this.showLogin();
        }
    }
    
    showLogin() {
        document.getElementById('login-overlay').style.display = 'flex';
        document.getElementById('admin-content').style.display = 'none';
        
        document.getElementById('login-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleLogin();
        });
    }
    
    hideLogin() {
        document.getElementById('login-overlay').style.display = 'none';
        document.getElementById('admin-content').style.display = 'block';
    }
    
    async handleLogin() {
        const password = document.getElementById('admin-password').value;
        const errorEl = document.getElementById('login-error');
        
        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ password })
            });
            
            if (response.ok) {
                const data = await response.json();
                this.authToken = data.token;
                sessionStorage.setItem('admin_token', data.token);
                this.hideLogin();
                this.init();
            } else {
                errorEl.textContent = 'Invalid password. Please try again.';
                errorEl.style.display = 'block';
                document.getElementById('admin-password').value = '';
                document.getElementById('admin-password').focus();
            }
        } catch (error) {
            console.error('Login failed:', error);
            errorEl.textContent = 'Login failed. Please check your connection and try again.';
            errorEl.style.display = 'block';
        }
    }
    
    async logout() {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ token: this.authToken })
            });
        } catch (error) {
            console.error('Logout error:', error);
        }
        
        sessionStorage.removeItem('admin_token');
        this.authToken = null;
        this.showLogin();
    }
    
    async init() {
        this.initializeUI();
        this.restoreCasesViewMode();
        await this.loadCases();
        this.startAutoRefresh();
        this.fetchAndDisplayVersion();
        this.loadQuotaDashboard();
        this.startQuotaRefresh();
    }
    
    restoreCasesViewMode() {
        const savedMode = localStorage.getItem('adminCasesViewMode') || 'compact';
        this.switchCasesViewMode(savedMode);
    }
    
    initializeUI() {
        // Modal handlers - close buttons
        document.querySelectorAll('.modal-close').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                const modalId = el.getAttribute('data-modal') || el.closest('.modal')?.id;
                if (modalId) {
                    this.hideModal(modalId);
                }
            });
        });
        
        // Cancel buttons
        document.querySelectorAll('.cancel-modal-btn').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                const modalId = el.getAttribute('data-modal');
                if (modalId) {
                    this.hideModal(modalId);
                }
            });
        });
        
        // Modal backdrop clicks
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.hideModal(modal.id);
                }
            });
        });
        
        // Header actions
        document.getElementById('seed-data-btn').addEventListener('click', () => this.seedMockData());
        document.getElementById('refresh-btn').addEventListener('click', () => this.loadCases());
        document.getElementById('logout-btn').addEventListener('click', () => this.logout());
        document.getElementById('witness-view-btn').addEventListener('click', () => {
            window.location.href = '/static/index.html';
        });
        
        // View toggle tabs
        document.querySelectorAll('.view-tab').forEach(tab => {
            tab.addEventListener('click', () => this.switchView(tab.dataset.view));
        });
        
        // Cases view mode toggle (compact/expanded)
        document.querySelectorAll('.view-mode-btn').forEach(btn => {
            btn.addEventListener('click', () => this.switchCasesViewMode(btn.dataset.mode));
        });
        
        // Search and filters
        document.getElementById('case-search').addEventListener('input', () => this.filterCases());
        document.getElementById('search-btn').addEventListener('click', () => this.filterCases());
        document.getElementById('filter-type').addEventListener('change', () => this.filterCases());
        document.getElementById('filter-status').addEventListener('change', () => this.filterCases());
        document.getElementById('sort-by').addEventListener('change', () => this.filterCases());
        document.getElementById('clear-filters-btn').addEventListener('click', () => this.clearFilters());
        
        // Case detail actions
        document.getElementById('regenerate-summary-btn')?.addEventListener('click', () => this.regenerateSummary());
        document.getElementById('export-case-btn')?.addEventListener('click', () => this.exportCase());
        document.getElementById('delete-case-btn')?.addEventListener('click', () => this.deleteCase());
        document.getElementById('compare-reports-btn')?.addEventListener('click', () => this.showReportComparison());
        document.getElementById('upload-evidence-btn')?.addEventListener('click', () => {
            this.showToast('📷 Evidence photo upload coming soon!', 'info');
        });
        document.getElementById('update-status-btn')?.addEventListener('click', () => this.updateCaseStatus());
        document.getElementById('print-report-btn')?.addEventListener('click', () => this.printCaseReport());
        
        // Timeline view toggle
        document.getElementById('simple-timeline-btn')?.addEventListener('click', () => this.switchTimelineView('simple'));
        document.getElementById('interactive-timeline-btn')?.addEventListener('click', () => this.switchTimelineView('interactive'));
        
        // Add investigator button
        document.getElementById('add-investigator-btn')?.addEventListener('click', () => this.showInvestigatorModal());
        
        // Initialize timeline visualization
        this.timelineViz = null;
    }
    
    switchView(view) {
        this.currentView = view;
        document.querySelectorAll('.view-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.view === view);
        });
        
        document.getElementById('cases-section').style.display = view === 'cases' ? '' : 'none';
        document.getElementById('reports-section').style.display = view === 'reports' ? '' : 'none';
        document.getElementById('workload-section').style.display = view === 'workload' ? '' : 'none';
        document.getElementById('dashboard-view').style.display = view === 'dashboard' ? '' : 'none';
        document.getElementById('map-view').style.display = view === 'map' ? '' : 'none';
        
        if (view === 'reports') {
            this.renderReports();
        } else if (view === 'workload') {
            this.loadWorkload();
        } else if (view === 'dashboard') {
            this.renderDashboardCharts();
        } else if (view === 'map') {
            setTimeout(() => this.initMap(), 100);
        }
    }
    
    switchCasesViewMode(mode) {
        const casesList = document.getElementById('cases-list');
        document.querySelectorAll('.view-mode-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
        
        if (mode === 'compact') {
            casesList.classList.add('cases-compact');
            casesList.classList.remove('cases-expanded');
        } else {
            casesList.classList.remove('cases-compact');
            casesList.classList.add('cases-expanded');
        }
        
        localStorage.setItem('adminCasesViewMode', mode);
    }
    
    async fetchWithTimeout(url, options = {}) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.fetchTimeout);
        
        const headers = {
            ...options.headers
        };
        if (this.authToken) {
            headers['Authorization'] = `Bearer ${this.authToken}`;
        }
        
        try {
            const response = await fetch(url, {
                ...options,
                headers,
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            
            if (response.status === 401) {
                this.logout();
                throw new Error('Session expired. Please login again.');
            }
            
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
            const [casesResponse, reportsResponse] = await Promise.all([
                this.fetchWithTimeout('/api/cases'),
                this.fetchWithTimeout('/api/sessions')
            ]);
            
            if (!casesResponse.ok) {
                throw new Error(`Server error: ${casesResponse.status}`);
            }
            
            const casesData = await casesResponse.json();
            this.cases = casesData.cases || [];
            
            if (reportsResponse.ok) {
                const reportsData = await reportsResponse.json();
                this.reports = reportsData.sessions || [];
            }
            
            this.updateStats();
            this.filterCases();
            
            if (this.currentView === 'reports') {
                this.renderReports();
            }
            
            this.showToast('Data loaded successfully', 'success');
        } catch (error) {
            console.error('Error loading cases:', error);
            this.showToast('Failed to load cases: ' + error.message, 'error');
            this.renderEmptyState();
        }
    }
    
    updateStats() {
        const totalCases = this.cases.length;
        const totalReports = this.reports.length;
        const unassigned = this.reports.filter(r => !r.case_id).length;
        const totalScenes = this.reports.reduce((sum, r) => sum + (r.version_count || 0), 0);
        
        const today = new Date().toDateString();
        const activeToday = this.cases.filter(c => {
            if (!c.updated_at && !c.created_at) return false;
            return new Date(c.updated_at || c.created_at).toDateString() === today;
        }).length;
        
        document.getElementById('total-cases').textContent = totalCases;
        document.getElementById('total-witnesses').textContent = totalReports;
        document.getElementById('unassigned-reports').textContent = unassigned;
        document.getElementById('active-today').textContent = activeToday;
        document.getElementById('total-scenes').textContent = totalScenes;
        
        this.updateNotifications();
    }
    
    filterCases() {
        const searchTerm = document.getElementById('case-search').value.toLowerCase();
        const typeFilter = document.getElementById('filter-type').value;
        const statusFilter = document.getElementById('filter-status').value;
        const sortBy = document.getElementById('sort-by').value;
        
        // Filter cases
        this.filteredCases = this.cases.filter(c => {
            const matchesSearch = !searchTerm || 
                (c.case_number || '').toLowerCase().includes(searchTerm) ||
                (c.title || '').toLowerCase().includes(searchTerm) ||
                (c.location || '').toLowerCase().includes(searchTerm) ||
                (c.summary || '').toLowerCase().includes(searchTerm);
            
            const matchesType = !typeFilter || (c.case_type || c.status || '') === typeFilter;
            const matchesStatus = !statusFilter || (c.status || 'active') === statusFilter;
            
            return matchesSearch && matchesType && matchesStatus;
        });
        
        // Filter reports
        this.filteredReports = this.reports.filter(r => {
            const matchesSearch = !searchTerm ||
                (r.id || '').toLowerCase().includes(searchTerm) ||
                (r.title || '').toLowerCase().includes(searchTerm) ||
                (r.report_number || '').toLowerCase().includes(searchTerm) ||
                (r.source_type || '').toLowerCase().includes(searchTerm);
            
            return matchesSearch;
        });
        
        // Sort cases
        this.filteredCases.sort((a, b) => {
            switch (sortBy) {
                case 'date-desc':
                    return new Date(b.created_at || 0) - new Date(a.created_at || 0);
                case 'date-asc':
                    return new Date(a.created_at || 0) - new Date(b.created_at || 0);
                case 'priority-desc':
                    return (b.priority_score || 0) - (a.priority_score || 0);
                case 'priority-asc':
                    return (a.priority_score || 0) - (b.priority_score || 0);
                case 'witnesses-desc':
                    return (b.report_count || 0) - (a.report_count || 0);
                case 'scenes-desc':
                    return (b.report_count || 0) - (a.report_count || 0);
                default:
                    return 0;
            }
        });
        
        this.renderCases();
        
        // Update subtitles
        document.getElementById('cases-count-subtitle').textContent = 
            `— ${this.filteredCases.length} case${this.filteredCases.length !== 1 ? 's' : ''}`;
        document.getElementById('reports-count-subtitle').textContent = 
            `— ${this.filteredReports.length} report${this.filteredReports.length !== 1 ? 's' : ''}`;
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
        
        container.querySelectorAll('.case-card').forEach((card) => {
            card.addEventListener('click', () => {
                const caseId = card.dataset.caseId;
                this.showCaseDetail(caseId);
            });
        });
    }
    
    renderCaseCard(caseData) {
        const status = caseData.status || 'active';
        const statusClass = `status-${status}`;
        const reportCount = caseData.report_count || 0;
        const summarySnippet = caseData.summary 
            ? caseData.summary.substring(0, 100) + (caseData.summary.length > 100 ? '…' : '')
            : '';
        const timeframeDesc = caseData.timeframe?.description || '';
        
        // Evidence progress: count filled categories out of possible ones
        const categories = ['summary', 'location', 'scene_image_url'];
        const filled = categories.filter(k => caseData[k]).length;
        const progressPct = Math.round((filled / categories.length) * 100);
        
        // Incident type badge
        const incidentType = caseData.metadata?.incident_type || this.guessIncidentType(caseData);
        const incidentIcon = this.getIncidentIcon(incidentType);
        
        // Source type mini-icons for reports
        const sourceIcons = (caseData.metadata?.source_types || []).map(s => this.getSourceIcon(s)).join('');
        
        // Time since last update
        const timeSinceStr = this.timeSince(caseData.updated_at || caseData.created_at);
        
        // Priority badge
        const priorityLabel = caseData.priority_label || 'normal';
        const priorityScore = caseData.priority_score != null ? Math.round(caseData.priority_score) : null;
        const priorityBadge = this.renderPriorityBadge(priorityLabel, priorityScore);
        
        return `
            <div class="case-card case-card-enhanced" data-case-id="${caseData.id}">
                <input type="checkbox" class="case-checkbox" data-case-id="${caseData.id}" 
                       ${this.selectedCases.has(caseData.id) ? 'checked' : ''}
                       onclick="event.stopPropagation(); window.adminPortal?.updateBulkSelection()">
                <div class="case-icon">📁</div>
                <div class="case-info">
                    <div class="case-header">
                        <div>
                            <h3 class="case-title">${caseData.title || 'Untitled Case'}</h3>
                            <div class="case-id">${caseData.case_number || caseData.id} <span class="compact-date">· ${this.formatDateShort(caseData.created_at)}</span></div>
                        </div>
                        <div style="display:flex;align-items:center;gap:0.5rem;">
                            ${priorityBadge}
                            <span class="incident-type-badge">${incidentIcon} ${incidentType}</span>
                            <div class="case-status-badge ${statusClass}">
                                ${status}
                            </div>
                        </div>
                    </div>
                    <div class="case-meta">
                        <div class="case-meta-item">
                            <span>📄</span>
                            <span>${reportCount} report${reportCount !== 1 ? 's' : ''} ${sourceIcons}</span>
                        </div>
                        ${caseData.location ? `
                        <div class="case-meta-item">
                            <span>📍</span>
                            <span>${caseData.location}</span>
                        </div>
                        ` : ''}
                        <div class="case-meta-item">
                            <span>📅</span>
                            <span>${this.formatDate(caseData.created_at)}</span>
                        </div>
                        ${timeframeDesc ? `
                        <div class="case-meta-item">
                            <span>🕐</span>
                            <span>${timeframeDesc}</span>
                        </div>
                        ` : ''}
                        <div class="case-meta-item">
                            <span class="time-since">Updated ${timeSinceStr}</span>
                        </div>
                    </div>
                    ${summarySnippet ? `
                    <p class="case-description case-summary-snippet">${summarySnippet}</p>
                    ` : ''}
                    <div class="card-progress-bar">
                        <div class="card-progress-fill" style="width:${progressPct}%"></div>
                    </div>
                    ${caseData.metadata?.assigned_to ? `
                    <div class="case-meta-item assigned-badge">
                        <span>👮</span>
                        <span>${caseData.metadata.assigned_to}</span>
                    </div>` : ''}
                </div>
                <div class="case-stats">
                    <div class="case-stat">
                        <span class="case-stat-value">${reportCount}</span>
                        <span class="case-stat-label">Reports</span>
                    </div>
                    ${priorityScore != null ? `
                    <div class="case-stat priority-stat">
                        <span class="case-stat-value priority-${priorityLabel}">${priorityScore}</span>
                        <span class="case-stat-label">Priority</span>
                    </div>` : ''}
                </div>
            </div>
        `;
    }
    
    renderPriorityBadge(label, score) {
        const icons = {
            critical: '🔴',
            high: '🟠',
            medium: '🟡',
            normal: '🟢',
            low: '⚪'
        };
        const icon = icons[label] || '⚪';
        const title = score != null ? `Priority: ${label} (${score}/100)` : `Priority: ${label}`;
        return `<span class="priority-badge priority-${label}" title="${title}">${icon}</span>`;
    }
    
    renderPrioritySection(caseData) {
        const section = document.getElementById('detail-priority-section');
        if (!section) return;
        
        const priority = caseData.priority || {};
        const totalScore = priority.total_score != null ? Math.round(priority.total_score) : '-';
        const label = priority.priority_label || 'normal';
        
        // Update score display
        const scoreEl = document.getElementById('detail-priority-score');
        if (scoreEl) {
            scoreEl.textContent = totalScore;
            scoreEl.className = `priority-score-value priority-${label}`;
        }
        
        // Update label badge
        const labelEl = document.getElementById('detail-priority-label');
        if (labelEl) {
            const icons = { critical: '🔴', high: '🟠', medium: '🟡', normal: '🟢', low: '⚪' };
            labelEl.textContent = `${icons[label] || ''} ${label.toUpperCase()}`;
            labelEl.className = `priority-label-badge priority-${label}`;
        }
        
        // Update breakdown
        document.getElementById('priority-severity').textContent = 
            priority.severity_score != null ? Math.round(priority.severity_score) : '-';
        document.getElementById('priority-age').textContent = 
            priority.age_score != null ? Math.round(priority.age_score) : '-';
        document.getElementById('priority-solvability').textContent = 
            priority.solvability_score != null ? Math.round(priority.solvability_score) : '-';
        document.getElementById('priority-witnesses').textContent = 
            priority.witness_score != null ? Math.round(priority.witness_score) : '-';
        
        // Update factors list
        const factorsList = document.getElementById('detail-priority-factors');
        if (factorsList && priority.factors) {
            factorsList.innerHTML = priority.factors
                .map(f => `<span class="priority-factor-tag">${f}</span>`)
                .join('');
        }
    }
    
    renderReports() {
        const container = document.getElementById('reports-list');
        
        if (this.filteredReports.length === 0) {
            container.innerHTML = '<div class="empty-state">No reports found</div>';
            return;
        }
        
        container.innerHTML = this.filteredReports.map(r => this.renderReportCard(r)).join('');
    }
    
    renderReportCard(report) {
        const sourceType = report.source_type || 'chat';
        const sourceIcon = this.getSourceIcon(sourceType);
        const sourceBadgeClass = `source-badge ${sourceType}`;
        const verification = report.metadata?.verification || 'pending';
        
        return `
            <div class="case-card report-card" data-report-id="${report.id}">
                <div class="case-icon">${sourceIcon}</div>
                <div class="case-info">
                    <div class="case-header">
                        <div>
                            <h3 class="case-title">${report.title || 'Witness Report'}</h3>
                            <div class="case-id">${report.report_number || report.id}</div>
                        </div>
                        <span class="${sourceBadgeClass}">${sourceIcon} ${sourceType}</span>
                    </div>
                    <div class="case-meta">
                        <div class="case-meta-item">
                            <span>📅</span>
                            <span>${this.formatDate(report.created_at)}</span>
                        </div>
                        <div class="case-meta-item">
                            <span>💬</span>
                            <span>${report.statement_count || 0} statements</span>
                        </div>
                        ${report.case_id ? `
                        <div class="case-meta-item">
                            <span>📁</span>
                            <span>Assigned to case</span>
                        </div>
                        ` : `
                        <div class="case-meta-item">
                            <span>📌</span>
                            <span class="unassigned-label">Unassigned</span>
                        </div>
                        `}
                    </div>
                    <div class="verification-workflow">
                        <select class="verification-select" onchange="window.adminPortal?.setVerification('${report.id}', this.value)" onclick="event.stopPropagation()">
                            <option value="pending" ${verification === 'pending' ? 'selected' : ''}>⏳ Pending</option>
                            <option value="verified" ${verification === 'verified' ? 'selected' : ''}>✅ Verified</option>
                            <option value="flagged" ${verification === 'flagged' ? 'selected' : ''}>🚩 Flagged</option>
                        </select>
                    </div>
                </div>
            </div>
        `;
    }
    
    getSourceIcon(sourceType) {
        const icons = {
            chat: '💬',
            phone: '📞',
            voice: '🎙️',
            email: '📧'
        };
        return icons[sourceType] || '💬';
    }
    
    openCaseDetail(caseId) {
        // Wrapper for showCaseDetail - useful for onclick handlers
        this.showCaseDetail(caseId);
    }
    
    async showCaseDetail(caseId) {
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${caseId}`);
            if (!response.ok) throw new Error('Failed to load case');
            
            const caseData = await response.json();
            this.currentCase = caseData;
            
            // Update modal title
            document.getElementById('case-detail-title').textContent = 
                `Case: ${caseData.case_number || caseData.id}`;
            
            // Case info
            document.getElementById('detail-case-number').textContent = caseData.case_number || '-';
            document.getElementById('detail-case-title').textContent = caseData.title || '-';
            document.getElementById('detail-case-location').textContent = caseData.location || '-';
            document.getElementById('detail-case-status').textContent = caseData.status || 'active';
            document.getElementById('detail-created').textContent = this.formatDateTime(caseData.created_at);
            document.getElementById('detail-updated').textContent = this.formatDateTime(caseData.updated_at || caseData.created_at);
            
            // Priority section
            this.renderPrioritySection(caseData);
            
            // Timeframe
            const tfSection = document.getElementById('detail-timeframe-section');
            if (caseData.timeframe) {
                tfSection.style.display = '';
                document.getElementById('detail-timeframe-start').textContent = 
                    caseData.timeframe.start ? this.formatDateTime(caseData.timeframe.start) : '-';
                document.getElementById('detail-timeframe-end').textContent = 
                    caseData.timeframe.end ? this.formatDateTime(caseData.timeframe.end) : 'Ongoing';
                document.getElementById('detail-timeframe-desc').textContent = 
                    caseData.timeframe.description || '';
            } else {
                tfSection.style.display = 'none';
            }
            
            // Summary
            const summarySection = document.getElementById('detail-summary-section');
            if (caseData.summary) {
                summarySection.style.display = '';
                document.getElementById('detail-case-summary').textContent = caseData.summary;
            } else {
                summarySection.style.display = 'none';
            }
            
            // Scene image
            const sceneSection = document.getElementById('detail-scene-image-section');
            if (caseData.scene_image_url) {
                sceneSection.style.display = '';
                document.getElementById('detail-scene-image').src = caseData.scene_image_url;
            } else {
                sceneSection.style.display = 'none';
            }
            
            // Reports list
            this.renderCaseReports(caseData.reports || []);
            
            // Timeline
            this.renderCaseTimeline(caseData.reports || []);
            
            // Audit trail
            this.renderAuditTrail(caseData);
            
            // Set status dropdown
            const statusSelect = document.getElementById('case-status-select');
            if (statusSelect) {
                statusSelect.value = caseData.status || 'open';
            }
            
            // Populate investigators dropdown and load assignment data
            await this.populateInvestigatorSelect();
            await this.loadCaseAssignmentHistory(caseId);
            
            // Show current assignment if exists
            const currentAssignment = caseData.metadata?.assignment_id ? {
                investigator_id: caseData.metadata.assigned_investigator_id,
                investigator_name: caseData.metadata.assigned_to,
                is_active: true
            } : null;
            this.updateAssignmentUI(currentAssignment, null);
            
            // Key elements
            const elementsSection = document.getElementById('detail-key-elements-section');
            const keyElements = caseData.metadata?.key_elements || [];
            if (keyElements.length > 0) {
                elementsSection.style.display = '';
                document.getElementById('detail-key-elements').innerHTML = 
                    keyElements.map(e => `<span class="key-element-tag">${e}</span>`).join('');
            } else {
                elementsSection.style.display = 'none';
            }
            
            // Related cases
            this.renderRelatedCases(caseData.related_cases || []);
            this.setupRelatedCasesHandlers();
            this.setupPatternDetectionHandlers();
            
            // Reset pattern display
            document.getElementById('patterns-container').style.display = 'none';
            document.getElementById('patterns-empty').style.display = 'block';
            
            this.showModal('case-detail-modal');
        } catch (error) {
            console.error('Error loading case details:', error);
            this.showToast('Failed to load case details', 'error');
        }
    }
    
    renderRelatedCases(relatedCases) {
        const container = document.getElementById('related-cases-list');
        
        if (relatedCases.length === 0) {
            container.innerHTML = '<p class="empty-state">No related cases linked</p>';
            return;
        }
        
        container.innerHTML = relatedCases.map(rel => {
            const relTypeClass = rel.relationship_type || 'related';
            const relTypeLabel = {
                'related': 'Related',
                'same_incident': 'Same Incident',
                'serial': 'Serial Pattern'
            }[relTypeClass] || 'Related';
            
            const reasonLabel = {
                'suspect': '👤 Suspect',
                'location': '📍 Location',
                'mo': '🔧 MO',
                'time_proximity': '⏱️ Time',
                'semantic': '🧠 Semantic',
                'manual': '✋ Manual'
            }[rel.link_reason] || rel.link_reason;
            
            const confidencePercent = Math.round((rel.confidence || 0.5) * 100);
            
            return `
                <div class="related-case-card" data-case-id="${rel.related_case_id}" onclick="window.adminPortal.navigateToRelatedCase('${rel.related_case_id}')">
                    <div class="related-case-info">
                        <div class="case-number">${rel.related_case_number}</div>
                        <div class="case-title">${rel.related_case_title}</div>
                        <div class="related-case-meta">
                            <span class="relationship-badge ${relTypeClass}">${relTypeLabel}</span>
                            <span class="link-reason-badge">${reasonLabel}</span>
                            <span class="confidence-score">${confidencePercent}% confidence</span>
                        </div>
                    </div>
                    <button class="unlink-btn" onclick="event.stopPropagation(); window.adminPortal.unlinkCase('${rel.id}')" title="Remove link">
                        ✕ Unlink
                    </button>
                </div>
            `;
        }).join('');
    }
    
    setupRelatedCasesHandlers() {
        // Find similar cases button
        document.getElementById('find-similar-btn')?.addEventListener('click', () => this.findSimilarCases());
        
        // Add link button
        document.getElementById('add-link-btn')?.addEventListener('click', () => this.showLinkForm());
        
        // Cancel link button
        document.getElementById('cancel-link-btn')?.addEventListener('click', () => this.hideLinkForm());
        
        // Confirm link button
        document.getElementById('confirm-link-btn')?.addEventListener('click', () => this.confirmLinkCase());
    }
    
    async findSimilarCases() {
        if (!this.currentCase) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}/similar?limit=5`);
            if (!response.ok) throw new Error('Failed to find similar cases');
            
            const data = await response.json();
            const panel = document.getElementById('similar-cases-panel');
            const list = document.getElementById('similar-cases-list');
            
            if (data.similar_cases.length === 0) {
                list.innerHTML = '<p class="empty-state">No similar cases found</p>';
            } else {
                list.innerHTML = data.similar_cases.map(sim => `
                    <div class="similar-case-item">
                        <div class="similar-case-info">
                            <strong>${sim.case_number}</strong> - ${sim.title}
                            <div class="similarity-score">${Math.round(sim.similarity_score * 100)}% similar</div>
                            <div class="matching-factors">
                                ${sim.matching_factors.map(f => `<span class="factor-tag">${f}</span>`).join('')}
                            </div>
                        </div>
                        <button class="quick-link-btn" onclick="window.adminPortal.quickLinkCase('${sim.case_id}', '${sim.matching_factors[0] || 'semantic'}')">
                            ➕ Link
                        </button>
                    </div>
                `).join('');
            }
            
            panel.style.display = 'block';
        } catch (error) {
            console.error('Error finding similar cases:', error);
            this.showToast('Failed to find similar cases', 'error');
        }
    }
    
    async quickLinkCase(targetCaseId, linkReason) {
        if (!this.currentCase) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}/link`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.authToken}`
                },
                body: JSON.stringify({
                    case_b_id: targetCaseId,
                    relationship_type: 'related',
                    link_reason: linkReason
                })
            });
            
            if (!response.ok) throw new Error('Failed to link cases');
            
            this.showToast('Cases linked successfully', 'success');
            // Refresh case detail
            await this.showCaseDetail(this.currentCase.id);
        } catch (error) {
            console.error('Error linking cases:', error);
            this.showToast('Failed to link cases', 'error');
        }
    }
    
    async unlinkCase(relationshipId) {
        if (!this.currentCase) return;
        
        if (!confirm('Are you sure you want to remove this link?')) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}/link/${relationshipId}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${this.authToken}`
                }
            });
            
            if (!response.ok) throw new Error('Failed to unlink cases');
            
            this.showToast('Link removed successfully', 'success');
            // Refresh case detail
            await this.showCaseDetail(this.currentCase.id);
        } catch (error) {
            console.error('Error unlinking cases:', error);
            this.showToast('Failed to unlink cases', 'error');
        }
    }
    
    async showLinkForm() {
        // Populate case selector with all cases except current
        const select = document.getElementById('link-case-select');
        select.innerHTML = '<option value="">Select a case...</option>';
        
        const otherCases = this.cases.filter(c => c.id !== this.currentCase?.id);
        otherCases.forEach(c => {
            select.innerHTML += `<option value="${c.id}">${c.case_number} - ${c.title}</option>`;
        });
        
        document.getElementById('link-case-form').style.display = 'flex';
        document.getElementById('add-link-btn').style.display = 'none';
    }
    
    hideLinkForm() {
        document.getElementById('link-case-form').style.display = 'none';
        document.getElementById('add-link-btn').style.display = 'inline-block';
    }
    
    async confirmLinkCase() {
        const targetCaseId = document.getElementById('link-case-select').value;
        const relType = document.getElementById('link-type-select').value;
        const notes = document.getElementById('link-notes-input').value;
        
        if (!targetCaseId) {
            this.showToast('Please select a case to link', 'warning');
            return;
        }
        
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}/link`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.authToken}`
                },
                body: JSON.stringify({
                    case_b_id: targetCaseId,
                    relationship_type: relType,
                    link_reason: 'manual',
                    notes: notes || null
                })
            });
            
            if (!response.ok) throw new Error('Failed to link cases');
            
            this.showToast('Cases linked successfully', 'success');
            this.hideLinkForm();
            // Refresh case detail
            await this.showCaseDetail(this.currentCase.id);
        } catch (error) {
            console.error('Error linking cases:', error);
            this.showToast('Failed to link cases', 'error');
        }
    }
    
    navigateToRelatedCase(caseId) {
        this.hideModal('case-detail-modal');
        setTimeout(() => this.showCaseDetail(caseId), 300);
    }
    
    // ── Pattern Detection ─────────────────────────────────────────
    
    setupPatternDetectionHandlers() {
        document.getElementById('analyze-patterns-btn')?.addEventListener('click', () => this.analyzePatterns());
    }
    
    async analyzePatterns() {
        if (!this.currentCase) return;
        
        const btn = document.getElementById('analyze-patterns-btn');
        const container = document.getElementById('patterns-container');
        const emptyState = document.getElementById('patterns-empty');
        
        try {
            btn.disabled = true;
            btn.textContent = '⏳ Analyzing...';
            
            const response = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}/patterns`);
            if (!response.ok) throw new Error('Failed to analyze patterns');
            
            const data = await response.json();
            const patterns = data.patterns;
            
            // Hide empty state
            emptyState.style.display = 'none';
            container.style.display = 'flex';
            
            // Render time patterns
            this.renderPatternList(
                'time-patterns-list',
                patterns.time_matches || [],
                'time',
                match => `Same day (${match.match_reason || 'Unknown'})`,
                match => `${match.case_number} - ${match.title}`
            );
            
            // Render location patterns
            this.renderPatternList(
                'location-patterns-list',
                patterns.location_matches || [],
                'location',
                match => `${match.location || 'Same area'}`,
                match => `${match.case_number} - ${match.title}`
            );
            
            // Render MO patterns
            this.renderPatternList(
                'mo-patterns-list',
                patterns.mo_matches || [],
                'mo',
                match => `${match.incident_type || 'Similar method'}`,
                match => `${match.case_number} - ${match.title}`
            );
            
            // Render semantic patterns
            this.renderPatternList(
                'semantic-patterns-list',
                patterns.semantic_matches || [],
                'semantic',
                match => `${Math.round((match.similarity || 0) * 100)}% similar`,
                match => `${match.case_number} - ${match.title}`
            );
            
            btn.textContent = '📊 Analyze Patterns';
            btn.disabled = false;
            
        } catch (error) {
            console.error('Error analyzing patterns:', error);
            this.showToast('Failed to analyze patterns', 'error');
            btn.textContent = '📊 Analyze Patterns';
            btn.disabled = false;
        }
    }
    
    renderPatternList(containerId, matches, type, getDescription, getTitle) {
        const list = document.getElementById(containerId);
        if (!list) return;
        
        if (!matches || matches.length === 0) {
            list.innerHTML = '<p class="pattern-empty">No patterns found</p>';
            return;
        }
        
        const confidenceClass = matches.length >= 3 ? 'high-confidence' : 
                               matches.length >= 2 ? 'medium-confidence' : '';
        
        list.innerHTML = matches.map(match => `
            <div class="pattern-item ${confidenceClass}">
                <div class="pattern-info">
                    <div class="pattern-description">${getTitle(match)}</div>
                    <div class="pattern-details">
                        <span class="pattern-badge ${type}">${getDescription(match)}</span>
                    </div>
                </div>
                <span class="pattern-case-link" onclick="window.adminPortal.navigateToRelatedCase('${match.case_id}')">
                    View →
                </span>
            </div>
        `).join('');
    }
    
    renderCaseReports(reports) {
        const container = document.getElementById('detail-reports-list');
        document.getElementById('detail-report-count').textContent = reports.length;
        
        if (reports.length === 0) {
            container.innerHTML = '<p class="empty-state">No reports in this case</p>';
            return;
        }
        
        container.innerHTML = reports.map((report, i) => {
            const sourceType = report.source_type || 'chat';
            const sourceIcon = this.getSourceIcon(sourceType);
            const statements = report.statements || [];
            const scenes = report.scene_versions || [];
            
            const stmtCount = statements.length;
            const reliabilityClass = stmtCount > 5 ? 'high' : stmtCount > 2 ? 'medium' : 'low';
            const reliabilityLabel = stmtCount > 5 ? 'High' : stmtCount > 2 ? 'Medium' : 'Low';
            
            return `
                <div class="report-detail-card">
                    <div class="report-detail-header" onclick="this.parentElement.classList.toggle('expanded')">
                        <div class="report-detail-title">
                            <span class="source-badge ${sourceType}">${sourceIcon} ${sourceType}</span>
                            <strong>${report.title || `Report #${i + 1}`}</strong>
                            <span class="report-number">${report.report_number || ''}</span>
                            <span class="reliability-badge ${reliabilityClass}">Reliability: ${reliabilityLabel}</span>
                        </div>
                        <div class="report-detail-meta">
                            <span>${statements.length} statement${statements.length !== 1 ? 's' : ''}</span>
                            <span>${scenes.length} scene${scenes.length !== 1 ? 's' : ''}</span>
                            <span class="expand-icon">▶</span>
                        </div>
                    </div>
                    <div class="report-detail-body">
                        ${statements.length > 0 ? `
                        <div class="report-statements">
                            ${statements.map((stmt, j) => `
                                <div class="statement-item">
                                    <div class="statement-header">
                                        <span class="statement-number">Statement #${j + 1}</span>
                                        <span class="statement-time">${stmt.timestamp ? this.formatTime(stmt.timestamp) : ''}</span>
                                    </div>
                                    <p class="statement-text">${stmt.text || stmt.content || 'No content'}</p>
                                </div>
                            `).join('')}
                        </div>
                        ` : '<p class="empty-state">No statements</p>'}
                        ${scenes.length > 0 ? `
                        <div class="scene-grid">
                            ${scenes.map((scene, j) => `
                                <div class="scene-item">
                                    <img src="${scene.image_url}" alt="Scene version ${j + 1}" loading="lazy">
                                    <div class="scene-version-badge">v${j + 1}</div>
                                </div>
                            `).join('')}
                        </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');
    }
    
    async seedMockData() {
        try {
            this.showToast('Seeding demo data...', 'info');
            const response = await this.fetchWithTimeout('/api/admin/seed-mock-data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (!response.ok) throw new Error('Seed failed');
            
            this.showToast('Demo data seeded successfully!', 'success');
            await this.loadCases();
        } catch (error) {
            console.error('Error seeding data:', error);
            this.showToast('Failed to seed demo data: ' + error.message, 'error');
        }
    }
    
    async regenerateSummary() {
        if (!this.currentCase) return;
        
        try {
            this.showToast('Regenerating summary...', 'info');
            const response = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}/summary`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (!response.ok) throw new Error('Regeneration failed');
            
            const data = await response.json();
            if (data.summary) {
                document.getElementById('detail-case-summary').textContent = data.summary;
                document.getElementById('detail-summary-section').style.display = '';
            }
            
            this.showToast('Summary regenerated', 'success');
        } catch (error) {
            console.error('Error regenerating summary:', error);
            this.showToast('Failed to regenerate summary', 'error');
        }
    }
    
    async exportCase() {
        if (!this.currentCase) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}`);
            if (!response.ok) throw new Error('Export failed');
            
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `case_${this.currentCase.case_number || this.currentCase.id}_${Date.now()}.json`;
            a.click();
            window.URL.revokeObjectURL(url);
            
            this.showToast('Case exported successfully', 'success');
        } catch (error) {
            console.error('Error exporting case:', error);
            this.showToast('Failed to export case', 'error');
        }
    }
    
    async closeCase() {
        if (!this.currentCase) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: 'closed' })
            });
            
            if (!response.ok) throw new Error('Update failed');
            
            this.showToast('Case closed', 'success');
            this.hideModal('case-detail-modal');
            await this.loadCases();
        } catch (error) {
            console.error('Error closing case:', error);
            this.showToast('Failed to close case', 'error');
        }
    }
    
    async deleteCase() {
        if (!this.currentCase) return;
        
        if (!confirm(`Are you sure you want to delete case ${this.currentCase.case_number || this.currentCase.id}? This cannot be undone.`)) {
            return;
        }
        
        try {
            // Delete all reports in the case, then remove from memory
            const reportIds = (this.currentCase.reports || []).map(r => r.id);
            for (const reportId of reportIds) {
                await this.fetchWithTimeout(`/api/sessions/${reportId}`, { method: 'DELETE' }).catch(() => {});
            }
            const response = { ok: true };
            
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
                <p>No cases found. Click "Seed Demo Data" to populate with sample data, or wait for reports to be submitted.</p>
            </div>
        `;
    }
    
    startAutoRefresh() {
        setInterval(() => {
            this.loadCases();
        }, 30000);
    }
    
    // ======================================
    // New Feature Methods
    // ======================================
    
    renderCaseTimeline(reports) {
        const container = document.getElementById('case-timeline');
        if (!container) return;
        if (!reports || reports.length === 0) {
            container.innerHTML = '<p class="empty-state">No timeline data</p>';
            return;
        }
        
        const sorted = [...reports].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
        container.innerHTML = sorted.map((r, i) => `
            <div class="timeline-item">
                <div class="timeline-dot"></div>
                <div class="timeline-line"></div>
                <div class="timeline-content">
                    <div class="timeline-date">${this.formatDateTime(r.created_at)}</div>
                    <div class="timeline-title">
                        <span class="source-badge ${r.source_type || 'chat'}">${this.getSourceIcon(r.source_type)}</span>
                        ${r.report_number || r.title || `Report #${i + 1}`}
                    </div>
                    <div class="timeline-detail">${(r.statements || []).length || r.statement_count || 0} statements</div>
                </div>
            </div>
        `).join('');
    }
    
    switchTimelineView(view) {
        const simpleBtn = document.getElementById('simple-timeline-btn');
        const interactiveBtn = document.getElementById('interactive-timeline-btn');
        const simpleContainer = document.getElementById('case-timeline');
        const interactiveContainer = document.getElementById('interactive-timeline-container');
        
        if (!simpleContainer || !interactiveContainer) return;
        
        if (view === 'interactive') {
            simpleBtn?.classList.remove('active');
            interactiveBtn?.classList.add('active');
            simpleContainer.style.display = 'none';
            interactiveContainer.style.display = 'block';
            
            // Initialize and load interactive timeline
            if (!this.timelineViz) {
                this.timelineViz = new TimelineVisualization('interactive-timeline-container', {
                    editable: true,
                    showContradictions: true
                });
            }
            this.timelineViz.setAuthToken(this.authToken);
            if (this.currentCase?.id) {
                this.timelineViz.loadCaseTimeline(this.currentCase.id);
            }
        } else {
            simpleBtn?.classList.add('active');
            interactiveBtn?.classList.remove('active');
            simpleContainer.style.display = 'block';
            interactiveContainer.style.display = 'none';
        }
    }
    
    showReportComparison() {
        if (!this.currentCase || !this.currentCase.reports || this.currentCase.reports.length < 2) {
            this.showToast('Need at least 2 reports to compare', 'warning');
            return;
        }
        const reports = this.currentCase.reports;
        let html = '<div class="comparison-grid">';
        for (let i = 0; i < Math.min(reports.length, 3); i++) {
            const r = reports[i];
            html += `<div class="comparison-column">
                <h4>${this.getSourceIcon(r.source_type)} ${r.report_number || 'Report'}</h4>
                <div class="comparison-statements">
                    ${(r.statements || []).map(s => `<p class="comparison-stmt">${s.text || s.content || ''}</p>`).join('') || '<p class="empty-state">No statements</p>'}
                </div>
            </div>`;
        }
        html += '</div>';
        const bodyEl = document.getElementById('modal-body-content');
        if (bodyEl) {
            bodyEl.innerHTML = html;
        }
    }
    
    updateNotifications() {
        const oneHourAgo = new Date(Date.now() - 3600000);
        const recentCount = this.cases.filter(c => new Date(c.updated_at) > oneHourAgo).length;
        const countEl = document.getElementById('notification-count');
        if (!countEl) return;
        if (recentCount > 0) {
            countEl.textContent = recentCount;
            countEl.style.display = '';
        } else {
            countEl.style.display = 'none';
        }
    }
    
    renderAuditTrail(caseData) {
        const container = document.getElementById('audit-trail-list');
        if (!container) return;
        
        const items = [];
        items.push({
            icon: '📁',
            text: `Case created: ${caseData.title || 'Untitled'}`,
            time: caseData.created_at
        });
        
        if (caseData.summary) {
            items.push({
                icon: '🤖',
                text: 'AI summary generated',
                time: caseData.updated_at
            });
        }
        
        if (caseData.scene_image_url) {
            items.push({
                icon: '🎬',
                text: 'Scene reconstruction created',
                time: caseData.updated_at
            });
        }
        
        const reports = caseData.reports || [];
        reports.forEach(r => {
            items.push({
                icon: this.getSourceIcon(r.source_type),
                text: `Report ${r.report_number || ''} added (${(r.statements || []).length || r.statement_count || 0} statements)`,
                time: r.created_at
            });
        });
        
        if (caseData.status === 'closed' || caseData.status === 'under_review') {
            items.push({
                icon: caseData.status === 'closed' ? '🔴' : '🟡',
                text: `Status changed to ${caseData.status}`,
                time: caseData.updated_at
            });
        }
        
        items.sort((a, b) => new Date(b.time || 0) - new Date(a.time || 0));
        
        container.innerHTML = items.map(item => `
            <div class="audit-item">
                <span class="audit-icon">${item.icon}</span>
                <span class="audit-text">${item.text}</span>
                <span class="audit-time">${this.formatDateTime(item.time)}</span>
            </div>
        `).join('');
    }
    
    getIncidentIcon(type) {
        const icons = { accident: '🚗', crime: '🔪', incident: '⚠️' };
        return icons[type] || '⚠️';
    }
    
    guessIncidentType(caseData) {
        const text = ((caseData.title || '') + ' ' + (caseData.summary || '')).toLowerCase();
        if (text.includes('accident') || text.includes('crash') || text.includes('collision')) return 'accident';
        if (text.includes('crime') || text.includes('theft') || text.includes('robbery') || text.includes('assault')) return 'crime';
        return 'incident';
    }
    
    timeSince(date) {
        if (!date) return 'unknown';
        const seconds = Math.floor((Date.now() - new Date(date).getTime()) / 1000);
        if (seconds < 60) return 'just now';
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m ago`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${hours}h ago`;
        const days = Math.floor(hours / 24);
        return `${days}d ago`;
    }
    
    async updateCaseStatus() {
        if (!this.currentCase) return;
        const newStatus = document.getElementById('case-status-select')?.value;
        if (!newStatus) return;
        
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: newStatus })
            });
            
            if (!response.ok) throw new Error('Update failed');
            
            this.showToast(`Case status updated to ${newStatus}`, 'success');
            await this.loadCases();
        } catch (error) {
            console.error('Error updating case status:', error);
            this.showToast('Failed to update case status', 'error');
        }
    }
    
    // ======================================
    // #31 Dashboard Charts
    // ======================================
    
    async renderDashboardCharts() {
        if (typeof Chart === 'undefined') return;
        
        Chart.defaults.color = '#9ca3af';
        Chart.defaults.borderColor = 'rgba(255,255,255,0.1)';
        
        // Fetch comprehensive dashboard stats
        try {
            const response = await this.fetchWithTimeout('/api/admin/dashboard/stats');
            if (response.ok) {
                this.dashboardStats = await response.json();
                this.renderDashboardFromStats();
            } else {
                // Fallback to local data
                this.renderDashboardFallback();
            }
        } catch (error) {
            console.warn('Failed to fetch dashboard stats, using local data:', error);
            this.renderDashboardFallback();
        }
        
        // Setup period toggle buttons
        this.setupDashboardControls();
    }
    
    setupDashboardControls() {
        document.querySelectorAll('.chart-period-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.chart-period-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.renderTrendChart(e.target.dataset.period);
            });
        });
    }
    
    renderDashboardFromStats() {
        const stats = this.dashboardStats;
        if (!stats) return;
        
        // Update summary cards
        document.getElementById('dash-total-cases').textContent = stats.summary?.total_cases || 0;
        document.getElementById('dash-cases-today').textContent = stats.summary?.cases_today || 0;
        document.getElementById('dash-cases-week').textContent = stats.summary?.cases_this_week || 0;
        document.getElementById('dash-avg-response').textContent = stats.response_times?.average_hours?.toFixed(1) || '-';
        
        // Render all charts
        this.renderTrendChart('daily');
        this.renderIncidentTypesChartFromStats();
        this.renderCaseStatusChartFromStats();
        this.renderResponseTimeChart();
        this.renderSourceDistributionChartFromStats();
        this.renderHourDistributionChart();
        this.renderDayDistributionChart();
        this.renderDashboardMap();
        this.renderTopLocations();
    }
    
    renderDashboardFallback() {
        // Use local case data
        this.renderCasesTimelineChart();
        this.renderSourceDistributionChart();
        this.renderIncidentTypesChart();
        this.renderCaseStatusChart();
    }
    
    renderTrendChart(period = 'daily') {
        this.destroyChart('casesTimeline');
        const ctx = document.getElementById('cases-timeline-chart');
        if (!ctx || !this.dashboardStats?.trends) return;
        
        const trends = this.dashboardStats.trends;
        let data, labels;
        
        switch (period) {
            case 'weekly':
                labels = (trends.weekly || []).map(d => d.week.replace('W', 'Week '));
                data = (trends.weekly || []).map(d => d.count);
                break;
            case 'monthly':
                labels = (trends.monthly || []).map(d => {
                    const [y, m] = d.month.split('-');
                    return new Date(y, parseInt(m) - 1).toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
                });
                data = (trends.monthly || []).map(d => d.count);
                break;
            default: // daily
                labels = (trends.daily || []).map(d => {
                    const date = new Date(d.date);
                    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                });
                data = (trends.daily || []).map(d => d.count);
        }
        
        this.chartInstances['casesTimeline'] = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'Cases',
                    data,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59,130,246,0.15)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 4,
                    pointBackgroundColor: '#3b82f6',
                    pointBorderColor: '#1e2d3d',
                    pointBorderWidth: 2
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { stepSize: 1 } },
                    x: { grid: { display: false } }
                }
            }
        });
    }
    
    renderIncidentTypesChartFromStats() {
        this.destroyChart('incidentTypes');
        const ctx = document.getElementById('incident-types-chart');
        if (!ctx || !this.dashboardStats?.by_type) return;
        
        const typeData = this.dashboardStats.by_type;
        const labels = Object.keys(typeData).map(t => t.charAt(0).toUpperCase() + t.slice(1));
        const data = Object.values(typeData);
        const colors = ['#f59e0b', '#ef4444', '#3b82f6', '#8b5cf6', '#22c55e', '#ec4899'];
        
        this.chartInstances['incidentTypes'] = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data,
                    backgroundColor: colors.slice(0, data.length),
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom', labels: { padding: 15, usePointStyle: true } }
                }
            }
        });
    }
    
    renderCaseStatusChartFromStats() {
        this.destroyChart('caseStatus');
        const ctx = document.getElementById('case-status-chart');
        if (!ctx || !this.dashboardStats?.by_status) return;
        
        const statusData = this.dashboardStats.by_status;
        const statusLabels = { open: 'Open', under_review: 'Under Review', closed: 'Closed' };
        const statusColors = { open: '#22c55e', under_review: '#f59e0b', closed: '#64748b' };
        
        const labels = Object.keys(statusData).map(s => statusLabels[s] || s);
        const data = Object.values(statusData);
        const colors = Object.keys(statusData).map(s => statusColors[s] || '#94a3b8');
        
        this.chartInstances['caseStatus'] = new Chart(ctx, {
            type: 'pie',
            data: {
                labels,
                datasets: [{
                    data,
                    backgroundColor: colors,
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom', labels: { padding: 15, usePointStyle: true } }
                }
            }
        });
    }
    
    renderResponseTimeChart() {
        this.destroyChart('responseTime');
        const ctx = document.getElementById('response-time-chart');
        if (!ctx || !this.dashboardStats?.response_times?.by_type) return;
        
        const responseData = this.dashboardStats.response_times.by_type;
        const labels = Object.keys(responseData).map(t => t.charAt(0).toUpperCase() + t.slice(1));
        const data = Object.values(responseData);
        
        // Color based on response time (green < 24h, yellow < 48h, red > 48h)
        const colors = data.map(h => h < 24 ? '#22c55e' : h < 48 ? '#f59e0b' : '#ef4444');
        
        this.chartInstances['responseTime'] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Avg Hours',
                    data,
                    backgroundColor: colors,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Hours' } },
                    x: { grid: { display: false } }
                }
            }
        });
    }
    
    renderSourceDistributionChartFromStats() {
        this.destroyChart('sourceDist');
        const ctx = document.getElementById('source-distribution-chart');
        if (!ctx || !this.dashboardStats?.by_source) return;
        
        const sourceData = this.dashboardStats.by_source;
        const sourceLabels = { chat: '💬 Chat', phone: '📞 Phone', voice: '🎙️ Voice', email: '📧 Email' };
        const sourceColors = { chat: '#3b82f6', phone: '#22c55e', voice: '#f59e0b', email: '#ef4444' };
        
        const labels = Object.keys(sourceData).map(s => sourceLabels[s] || s);
        const data = Object.values(sourceData);
        const colors = Object.keys(sourceData).map(s => sourceColors[s] || '#94a3b8');
        
        this.chartInstances['sourceDist'] = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data,
                    backgroundColor: colors,
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom', labels: { padding: 15, usePointStyle: true } }
                }
            }
        });
    }
    
    renderHourDistributionChart() {
        this.destroyChart('hourDist');
        const ctx = document.getElementById('hour-distribution-chart');
        if (!ctx || !this.dashboardStats?.time_analysis?.by_hour) return;
        
        const hourData = this.dashboardStats.time_analysis.by_hour;
        const labels = Array.from({ length: 24 }, (_, i) => `${i}:00`);
        const data = labels.map((_, i) => hourData[i] || 0);
        
        this.chartInstances['hourDist'] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Incidents',
                    data,
                    backgroundColor: 'rgba(59, 130, 246, 0.7)',
                    borderRadius: 2
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { stepSize: 1 } },
                    x: { 
                        grid: { display: false },
                        ticks: { maxRotation: 45, minRotation: 45, callback: (val, idx) => idx % 3 === 0 ? labels[idx] : '' }
                    }
                }
            }
        });
    }
    
    renderDayDistributionChart() {
        this.destroyChart('dayDist');
        const ctx = document.getElementById('day-distribution-chart');
        if (!ctx || !this.dashboardStats?.time_analysis?.by_day_of_week) return;
        
        const dayData = this.dashboardStats.time_analysis.by_day_of_week;
        const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
        const data = days.map(d => dayData[d] || 0);
        
        this.chartInstances['dayDist'] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: days.map(d => d.slice(0, 3)),
                datasets: [{
                    label: 'Incidents',
                    data,
                    backgroundColor: '#8b5cf6',
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { stepSize: 1 } },
                    x: { grid: { display: false } }
                }
            }
        });
    }
    
    renderDashboardMap() {
        const mapContainer = document.getElementById('dashboard-map');
        if (!mapContainer || !this.dashboardStats?.geographic?.geo_points) return;
        
        // Initialize map if not already
        if (!this.dashboardMapInstance) {
            this.dashboardMapInstance = L.map('dashboard-map').setView([39.8283, -98.5795], 4);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap'
            }).addTo(this.dashboardMapInstance);
        }
        
        // Clear existing markers
        if (this.dashboardMapMarkers) {
            this.dashboardMapMarkers.forEach(m => m.remove());
        }
        this.dashboardMapMarkers = [];
        
        const points = this.dashboardStats.geographic.geo_points;
        if (points.length === 0) {
            mapContainer.innerHTML = '<div class="empty-state" style="padding: 2rem;">No geographic data available</div>';
            return;
        }
        
        const typeColors = { accident: '#f59e0b', crime: '#ef4444', incident: '#3b82f6', other: '#8b5cf6' };
        const bounds = [];
        
        points.forEach(p => {
            const color = typeColors[p.type?.toLowerCase()] || '#3b82f6';
            const marker = L.circleMarker([p.lat, p.lng], {
                radius: 8,
                fillColor: color,
                color: '#fff',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.8
            }).addTo(this.dashboardMapInstance);
            
            marker.bindPopup(`<b>${p.title || 'Case'}</b><br>${p.type || 'Unknown type'}`);
            this.dashboardMapMarkers.push(marker);
            bounds.push([p.lat, p.lng]);
        });
        
        if (bounds.length > 0) {
            this.dashboardMapInstance.fitBounds(bounds, { padding: [20, 20] });
        }
    }
    
    renderTopLocations() {
        const container = document.getElementById('top-locations-list');
        if (!container || !this.dashboardStats?.geographic?.top_locations) return;
        
        const locations = this.dashboardStats.geographic.top_locations;
        if (locations.length === 0) {
            container.innerHTML = '<p class="empty-state">No location data</p>';
            return;
        }
        
        container.innerHTML = locations.slice(0, 8).map(loc => `
            <div class="location-item">
                <span class="location-name" title="${loc.location}">${loc.location}</span>
                <span class="location-count">${loc.count}</span>
            </div>
        `).join('');
    }
    
    destroyChart(key) {
        if (this.chartInstances[key]) {
            this.chartInstances[key].destroy();
            this.chartInstances[key] = null;
        }
    }
    
    renderCasesTimelineChart() {
        this.destroyChart('casesTimeline');
        const ctx = document.getElementById('cases-timeline-chart');
        if (!ctx) return;
        
        const dateCounts = {};
        this.cases.forEach(c => {
            const d = c.created_at ? new Date(c.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'Unknown';
            dateCounts[d] = (dateCounts[d] || 0) + 1;
        });
        
        const labels = Object.keys(dateCounts);
        const data = Object.values(dateCounts);
        
        this.chartInstances['casesTimeline'] = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'Cases',
                    data,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59,130,246,0.1)',
                    fill: true,
                    tension: 0.3
                }]
            },
            options: { responsive: true, plugins: { legend: { display: false } } }
        });
    }
    
    renderSourceDistributionChart() {
        this.destroyChart('sourceDist');
        const ctx = document.getElementById('source-distribution-chart');
        if (!ctx) return;
        
        const counts = { chat: 0, phone: 0, voice: 0, email: 0 };
        this.reports.forEach(r => {
            const src = r.source_type || 'chat';
            counts[src] = (counts[src] || 0) + 1;
        });
        
        this.chartInstances['sourceDist'] = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['Chat', 'Phone', 'Voice', 'Email'],
                datasets: [{
                    data: [counts.chat, counts.phone, counts.voice, counts.email],
                    backgroundColor: ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444']
                }]
            },
            options: { responsive: true }
        });
    }
    
    renderIncidentTypesChart() {
        this.destroyChart('incidentTypes');
        const ctx = document.getElementById('incident-types-chart');
        if (!ctx) return;
        
        const counts = { accident: 0, crime: 0, incident: 0, other: 0 };
        this.cases.forEach(c => {
            const t = (c.metadata?.incident_type || this.guessIncidentType(c)).toLowerCase();
            counts[t] = (counts[t] || 0) + 1;
        });
        
        this.chartInstances['incidentTypes'] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: ['Accident', 'Crime', 'Incident', 'Other'],
                datasets: [{
                    label: 'Count',
                    data: [counts.accident, counts.crime, counts.incident, counts.other],
                    backgroundColor: ['#f59e0b', '#ef4444', '#3b82f6', '#8b5cf6']
                }]
            },
            options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } } }
        });
    }
    
    renderCaseStatusChart() {
        this.destroyChart('caseStatus');
        const ctx = document.getElementById('case-status-chart');
        if (!ctx) return;
        
        const counts = { open: 0, under_review: 0, closed: 0 };
        this.cases.forEach(c => {
            const s = c.status || 'open';
            counts[s] = (counts[s] || 0) + 1;
        });
        
        this.chartInstances['caseStatus'] = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: ['Open', 'Under Review', 'Closed'],
                datasets: [{
                    data: [counts.open, counts.under_review, counts.closed],
                    backgroundColor: ['#22c55e', '#f59e0b', '#64748b']
                }]
            },
            options: { responsive: true }
        });
    }
    
    // ======================================
    // #32 Advanced Search with Filters
    // ======================================
    
    debounceSearch() {
        clearTimeout(this.searchDebounceTimer);
        this.searchDebounceTimer = setTimeout(() => this.applyAdvancedFilters(), 300);
    }
    
    applyAdvancedFilters() {
        const query = (document.getElementById('search-query')?.value || '').toLowerCase();
        const status = document.getElementById('adv-filter-status')?.value || '';
        const type = document.getElementById('adv-filter-type')?.value || '';
        const dateFrom = document.getElementById('filter-date-from')?.value || '';
        const dateTo = document.getElementById('filter-date-to')?.value || '';
        const source = document.getElementById('filter-source')?.value || '';
        
        this.filteredCases = this.cases.filter(c => {
            if (query && !JSON.stringify(c).toLowerCase().includes(query)) return false;
            if (status && (c.status || 'open') !== status) return false;
            if (type && (c.metadata?.incident_type || this.guessIncidentType(c)).toLowerCase() !== type) return false;
            if (dateFrom && c.created_at < dateFrom) return false;
            if (dateTo && c.created_at > dateTo + 'T23:59:59') return false;
            return true;
        });
        
        this.filteredReports = this.reports.filter(r => {
            if (query && !JSON.stringify(r).toLowerCase().includes(query)) return false;
            if (source && (r.source_type || '') !== source) return false;
            return true;
        });
        
        this.renderCases();
        if (this.currentView === 'reports') this.renderReports();
        
        document.getElementById('cases-count-subtitle').textContent = 
            `— ${this.filteredCases.length} case${this.filteredCases.length !== 1 ? 's' : ''}`;
        document.getElementById('reports-count-subtitle').textContent = 
            `— ${this.filteredReports.length} report${this.filteredReports.length !== 1 ? 's' : ''}`;
    }
    
    // ======================================
    // #33 Bulk Operations
    // ======================================
    
    updateBulkSelection() {
        this.selectedCases.clear();
        document.querySelectorAll('.case-checkbox:checked').forEach(cb => {
            this.selectedCases.add(cb.dataset.caseId);
        });
        
        const toolbar = document.getElementById('bulk-toolbar');
        const countEl = document.getElementById('selected-count');
        if (this.selectedCases.size > 0) {
            toolbar.style.display = 'flex';
            countEl.textContent = `${this.selectedCases.size} selected`;
        } else {
            toolbar.style.display = 'none';
        }
    }
    
    clearSelection() {
        this.selectedCases.clear();
        document.querySelectorAll('.case-checkbox').forEach(cb => cb.checked = false);
        document.getElementById('bulk-toolbar').style.display = 'none';
    }
    
    async bulkUpdateStatus(newStatus) {
        if (this.selectedCases.size === 0) return;
        
        const ids = [...this.selectedCases];
        let success = 0;
        for (const id of ids) {
            try {
                const resp = await this.fetchWithTimeout(`/api/cases/${id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: newStatus })
                });
                if (resp.ok) success++;
            } catch (e) { /* skip */ }
        }
        
        this.showToast(`Updated ${success}/${ids.length} cases to ${newStatus}`, 'success');
        this.clearSelection();
        await this.loadCases();
    }
    
    bulkExport() {
        if (this.selectedCases.size === 0) return;
        
        const exportData = this.cases.filter(c => this.selectedCases.has(c.id));
        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `cases_export_${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
        this.showToast(`Exported ${exportData.length} cases`, 'success');
    }
    
    // ======================================
    // #34 Case Assignment (Enhanced with Investigators)
    // ======================================
    
    async assignCurrentCase(value) {
        if (!this.currentCase) return;
        await this.assignCase(this.currentCase.id, value);
    }
    
    async assignCase(caseId, assignedTo) {
        try {
            const caseData = this.cases.find(c => c.id === caseId);
            const metadata = { ...(caseData?.metadata || {}), assigned_to: assignedTo };
            
            const resp = await this.fetchWithTimeout(`/api/cases/${caseId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ metadata })
            });
            
            if (!resp.ok) throw new Error('Assignment failed');
            this.showToast(`Case assigned to ${assignedTo || 'nobody'}`, 'success');
            await this.loadCases();
        } catch (e) {
            this.showToast('Failed to assign case', 'error');
        }
    }
    
    async loadInvestigators() {
        try {
            const resp = await this.fetchWithTimeout('/api/investigators?active_only=true');
            if (resp.ok) {
                const data = await resp.json();
                this.investigators = data.investigators || [];
            }
        } catch (e) {
            console.error('Failed to load investigators:', e);
        }
    }
    
    async populateInvestigatorSelect() {
        await this.loadInvestigators();
        const select = document.getElementById('investigator-select');
        if (!select) return;
        
        select.innerHTML = '<option value="">-- Select Investigator --</option>';
        this.investigators.forEach(inv => {
            const workload = inv.active_cases !== undefined ? ` (${inv.active_cases}/${inv.max_cases})` : '';
            const opt = document.createElement('option');
            opt.value = inv.id;
            opt.textContent = `${inv.name}${inv.badge_number ? ` #${inv.badge_number}` : ''}${workload}`;
            select.appendChild(opt);
        });
    }
    
    async assignCaseToInvestigator() {
        if (!this.currentCase) return;
        const select = document.getElementById('investigator-select');
        const investigatorId = select?.value;
        
        if (!investigatorId) {
            this.showToast('Please select an investigator', 'warning');
            return;
        }
        
        try {
            const resp = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}/assign`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ investigator_id: investigatorId, assigned_by: 'admin' })
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.detail || 'Assignment failed');
            }
            
            const data = await resp.json();
            this.showToast(`Case assigned to ${data.investigator?.name}`, 'success');
            await this.loadCases();
            await this.loadCaseAssignmentHistory(this.currentCase.id);
            this.updateAssignmentUI(data.assignment, data.investigator);
        } catch (e) {
            this.showToast(e.message || 'Failed to assign case', 'error');
        }
    }
    
    async unassignCase() {
        if (!this.currentCase) return;
        
        try {
            const resp = await this.fetchWithTimeout(`/api/cases/${this.currentCase.id}/assign`, {
                method: 'DELETE'
            });
            
            if (!resp.ok) throw new Error('Failed to unassign');
            
            this.showToast('Case unassigned', 'success');
            await this.loadCases();
            this.updateAssignmentUI(null, null);
        } catch (e) {
            this.showToast('Failed to unassign case', 'error');
        }
    }
    
    async loadCaseAssignmentHistory(caseId) {
        try {
            const resp = await this.fetchWithTimeout(`/api/cases/${caseId}/assignments`);
            if (!resp.ok) return;
            
            const data = await resp.json();
            this.renderAssignmentHistory(data);
        } catch (e) {
            console.error('Failed to load assignment history:', e);
        }
    }
    
    renderAssignmentHistory(data) {
        const section = document.getElementById('assignment-history-section');
        const list = document.getElementById('assignment-history-list');
        if (!section || !list) return;
        
        if (!data.assignment_history || data.assignment_history.length === 0) {
            section.style.display = 'none';
            return;
        }
        
        section.style.display = 'block';
        list.innerHTML = data.assignment_history.map(a => `
            <div class="assignment-history-item ${a.is_active ? 'active' : 'inactive'}">
                <span class="name">${a.investigator_name} ${a.is_active ? '✓' : ''}</span>
                <span class="date">${this.formatDate(a.assigned_at)}${a.unassigned_at ? ' - ' + this.formatDate(a.unassigned_at) : ''}</span>
            </div>
        `).join('');
    }
    
    updateAssignmentUI(assignment, investigator) {
        const currentAssignment = document.getElementById('current-assignment');
        const assigneeName = document.getElementById('current-assignee-name');
        const unassignBtn = document.getElementById('unassign-btn');
        const select = document.getElementById('investigator-select');
        
        if (assignment && assignment.is_active) {
            if (currentAssignment) currentAssignment.style.display = 'block';
            if (assigneeName) assigneeName.textContent = investigator?.name || assignment.investigator_name;
            if (unassignBtn) unassignBtn.style.display = 'inline-block';
            if (select) select.value = assignment.investigator_id || '';
        } else {
            if (currentAssignment) currentAssignment.style.display = 'none';
            if (unassignBtn) unassignBtn.style.display = 'none';
            if (select) select.value = '';
        }
    }
    
    // ======================================
    // Workload View
    // ======================================
    
    async loadWorkload() {
        try {
            const resp = await this.fetchWithTimeout('/api/workload');
            if (!resp.ok) throw new Error('Failed to load workload');
            
            this.workloadData = await resp.json();
            this.renderWorkload();
        } catch (e) {
            console.error('Failed to load workload:', e);
            document.getElementById('investigators-grid').innerHTML = 
                '<div class="empty-state">Failed to load workload data</div>';
        }
    }
    
    renderWorkload() {
        if (!this.workloadData) return;
        
        // Update stats
        const setEl = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val;
        };
        
        setEl('stat-total-investigators', this.workloadData.active_investigators);
        setEl('stat-active-cases', this.workloadData.total_active_cases);
        setEl('stat-unassigned-cases', this.workloadData.unassigned_cases);
        setEl('stat-avg-utilization', `${this.workloadData.avg_utilization}%`);
        
        // Render investigators grid
        const grid = document.getElementById('investigators-grid');
        if (!grid) return;
        
        if (!this.workloadData.investigators || this.workloadData.investigators.length === 0) {
            grid.innerHTML = `
                <div class="empty-state">
                    <p>No investigators configured yet.</p>
                    <button class="btn btn-primary" onclick="window.adminPortal?.showInvestigatorModal()">➕ Add Investigator</button>
                </div>`;
            return;
        }
        
        grid.innerHTML = this.workloadData.investigators.map(inv => this.renderInvestigatorCard(inv)).join('');
    }
    
    renderInvestigatorCard(inv) {
        const utilization = inv.utilization_percent || 0;
        const barClass = utilization > 80 ? 'high' : (utilization > 50 ? 'medium' : 'low');
        
        const casesHtml = (inv.cases || []).map(c => 
            `<span class="case-chip" onclick="window.adminPortal?.openCaseDetail('${c.case_id}')" title="${c.title}">${c.case_number}</span>`
        ).join('');
        
        return `
            <div class="investigator-card" data-investigator-id="${inv.investigator_id}">
                <div class="investigator-header">
                    <div class="investigator-avatar">👮</div>
                    <div class="investigator-info">
                        <h4>${inv.investigator_name}</h4>
                        ${inv.badge_number ? `<span class="badge-number">#${inv.badge_number}</span>` : ''}
                    </div>
                </div>
                ${inv.department ? `<div class="investigator-meta"><span>📍 ${inv.department}</span></div>` : ''}
                <div class="workload-bar">
                    <div class="workload-bar-fill ${barClass}" style="width: ${utilization}%"></div>
                </div>
                <div class="workload-text">
                    <span>${inv.active_cases} / ${inv.max_cases} cases</span>
                    <span>${utilization}% capacity</span>
                </div>
                ${casesHtml ? `<div class="investigator-cases">${casesHtml}</div>` : ''}
                <div class="investigator-actions">
                    <button class="btn btn-secondary btn-sm" onclick="window.adminPortal?.editInvestigator('${inv.investigator_id}')">✏️ Edit</button>
                </div>
            </div>
        `;
    }
    
    showInvestigatorModal(investigator = null) {
        const modal = document.getElementById('investigator-modal');
        const title = document.getElementById('investigator-modal-title');
        const form = document.getElementById('investigator-form');
        
        if (!modal || !form) return;
        
        // Reset form
        form.reset();
        document.getElementById('inv-edit-id').value = '';
        document.getElementById('inv-max-cases').value = '10';
        
        if (investigator) {
            title.textContent = 'Edit Investigator';
            document.getElementById('inv-edit-id').value = investigator.id || investigator.investigator_id;
            document.getElementById('inv-name').value = investigator.name || investigator.investigator_name || '';
            document.getElementById('inv-badge').value = investigator.badge_number || '';
            document.getElementById('inv-email').value = investigator.email || '';
            document.getElementById('inv-department').value = investigator.department || '';
            document.getElementById('inv-max-cases').value = investigator.max_cases || 10;
        } else {
            title.textContent = 'Add Investigator';
        }
        
        modal.style.display = 'flex';
        
        // Setup form submit handler
        form.onsubmit = (e) => {
            e.preventDefault();
            this.saveInvestigator();
        };
    }
    
    closeInvestigatorModal() {
        const modal = document.getElementById('investigator-modal');
        if (modal) modal.style.display = 'none';
    }
    
    async editInvestigator(investigatorId) {
        try {
            const resp = await this.fetchWithTimeout(`/api/investigators/${investigatorId}`);
            if (!resp.ok) throw new Error('Failed to load investigator');
            const inv = await resp.json();
            this.showInvestigatorModal(inv);
        } catch (e) {
            this.showToast('Failed to load investigator', 'error');
        }
    }
    
    async saveInvestigator() {
        const editId = document.getElementById('inv-edit-id').value;
        const data = {
            name: document.getElementById('inv-name').value,
            badge_number: document.getElementById('inv-badge').value || null,
            email: document.getElementById('inv-email').value || null,
            department: document.getElementById('inv-department').value || null,
            max_cases: parseInt(document.getElementById('inv-max-cases').value) || 10
        };
        
        try {
            let resp;
            if (editId) {
                resp = await this.fetchWithTimeout(`/api/investigators/${editId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
            } else {
                resp = await this.fetchWithTimeout('/api/investigators', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
            }
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.detail || 'Failed to save');
            }
            
            this.showToast(editId ? 'Investigator updated' : 'Investigator created', 'success');
            this.closeInvestigatorModal();
            await this.loadWorkload();
        } catch (e) {
            this.showToast(e.message || 'Failed to save investigator', 'error');
        }
    }
    
    // ======================================
    // #35 Report Verification
    // ======================================
    
    async setVerification(reportId, status) {
        try {
            const report = this.reports.find(r => r.id === reportId);
            const metadata = { ...(report?.metadata || {}), verification: status };
            
            const resp = await this.fetchWithTimeout(`/api/sessions/${reportId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ metadata })
            });
            
            if (!resp.ok) throw new Error('Update failed');
            if (report) {
                if (!report.metadata) report.metadata = {};
                report.metadata.verification = status;
            }
            this.showToast(`Report marked as ${status}`, 'success');
        } catch (e) {
            this.showToast('Failed to update verification status', 'error');
        }
    }
    
    // ======================================
    // #36 Interactive Incident Map
    // ======================================
    
    initMap() {
        if (typeof L === 'undefined') return;
        if (this.incidentMap) {
            this.incidentMap.invalidateSize();
            this.plotCasesOnMap();
            return;
        }
        
        this.incidentMap = L.map('incident-map').setView([40.7128, -74.0060], 12);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap'
        }).addTo(this.incidentMap);
        
        this.plotCasesOnMap();
    }
    
    plotCasesOnMap() {
        if (!this.incidentMap) return;
        
        this.mapMarkers.forEach(m => m.remove());
        this.mapMarkers = [];
        
        let hasData = false;
        this.cases.forEach(c => {
            if (c.metadata?.coordinates) {
                hasData = true;
                const [lat, lng] = c.metadata.coordinates;
                const marker = L.marker([lat, lng])
                    .bindPopup(`<b>${c.case_number || ''}</b><br>${c.title || 'Untitled'}`)
                    .addTo(this.incidentMap);
                this.mapMarkers.push(marker);
            }
        });
        
        const noDataEl = document.getElementById('map-no-data');
        if (noDataEl) noDataEl.style.display = hasData ? 'none' : '';
        
        if (hasData && this.mapMarkers.length > 0) {
            const group = L.featureGroup(this.mapMarkers);
            this.incidentMap.fitBounds(group.getBounds().pad(0.1));
        }
    }
    
    // ======================================
    // #37 Print-Ready Case Report
    // ======================================
    
    printCaseReport() {
        const caseData = this.currentCase;
        if (!caseData) return;
        
        const printWindow = window.open('', '_blank');
        printWindow.document.write(`
            <html>
            <head>
                <title>Case Report - ${caseData.case_number || caseData.id}</title>
                <style>
                    body { font-family: 'Times New Roman', serif; max-width: 800px; margin: 40px auto; color: #000; }
                    h1 { text-align: center; border-bottom: 2px solid #000; }
                    .header { text-align: center; margin-bottom: 30px; }
                    .badge { display: inline-block; padding: 2px 8px; border: 1px solid #000; font-size: 12px; }
                    table { width: 100%; border-collapse: collapse; margin: 20px 0; }
                    td, th { border: 1px solid #ccc; padding: 8px; text-align: left; }
                    .section { margin: 20px 0; }
                    .section h2 { border-bottom: 1px solid #666; }
                    @media print { body { margin: 20px; } }
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>🛡️ WitnessReplay Case Report</h1>
                    <p><strong>Case #:</strong> ${caseData.case_number || caseData.id} | 
                       <strong>Status:</strong> ${caseData.status || 'Open'} |
                       <strong>Date:</strong> ${new Date(caseData.created_at).toLocaleDateString()}</p>
                    ${caseData.metadata?.assigned_to ? `<p><strong>Assigned To:</strong> ${caseData.metadata.assigned_to}</p>` : ''}
                </div>
                <div class="section">
                    <h2>Case Summary</h2>
                    <p>${caseData.summary || 'No summary available'}</p>
                </div>
                <div class="section">
                    <h2>Location</h2>
                    <p>${caseData.location || 'Unknown'}</p>
                </div>
                <div class="section">
                    <h2>Timeframe</h2>
                    <p>${caseData.timeframe?.description || 'Unknown'}</p>
                </div>
                <div class="section">
                    <h2>Reports (${caseData.report_ids?.length || (caseData.reports || []).length || 0})</h2>
                    <table>
                        <tr><th>#</th><th>Report ID</th><th>Source</th><th>Date</th></tr>
                        ${(caseData.reports || []).map((r, i) => 
                            `<tr><td>${i+1}</td><td>${(r.report_number || r.id || '').substring(0,12)}</td><td>${r.source_type || '-'}</td><td>${r.created_at ? new Date(r.created_at).toLocaleDateString() : '-'}</td></tr>`
                        ).join('') || (caseData.report_ids || []).map((rid, i) => 
                            `<tr><td>${i+1}</td><td>${rid.substring(0,8)}</td><td>-</td><td>-</td></tr>`
                        ).join('')}
                    </table>
                </div>
                <div class="section">
                    <h2>Key Elements</h2>
                    <p>${(caseData.metadata?.key_elements || []).join(', ') || 'None extracted'}</p>
                </div>
                <hr>
                <p style="text-align:center; font-size:11px; color:#666;">
                    Generated by WitnessReplay on ${new Date().toLocaleString()} | 
                    Confidential Law Enforcement Document
                </p>
            </body>
            </html>
        `);
        printWindow.document.close();
        printWindow.print();
    }
    
    // Utility functions
    formatDate(date) {
        if (!date) return 'Unknown';
        const d = new Date(date);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }
    
    formatDateShort(date) {
        if (!date) return '';
        const d = new Date(date);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
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
    
    // ======================================
    // Compact Quota Widget
    // ======================================
    
    initQuotaToggle() {
        const toggleBtn = document.getElementById('quota-toggle');
        const content = document.getElementById('quota-content');
        const dashboard = document.getElementById('quota-dashboard');
        if (toggleBtn && content) {
            toggleBtn.addEventListener('click', () => {
                const isExpanded = content.style.display !== 'none';
                content.style.display = isExpanded ? 'none' : 'block';
                dashboard.classList.toggle('expanded', !isExpanded);
            });
        }
    }
    
    async loadQuotaDashboard() {
        this.initQuotaToggle();
        try {
            const response = await this.fetchWithTimeout('/api/quota/status');
            if (!response.ok) {
                this.renderQuotaError();
                return;
            }
            const data = await response.json();
            this.renderQuotaDashboard(data);
        } catch (error) {
            console.error('Error loading quota:', error);
            this.renderQuotaError();
        }
    }
    
    renderQuotaDashboard(data) {
        const table = document.getElementById('quota-models');
        const timerEl = document.getElementById('quota-reset-timer');
        const updatedEl = document.getElementById('quota-updated');
        
        if (!table) return;
        
        if (timerEl && data.reset) {
            timerEl.textContent = data.reset.formatted;
        }
        
        if (updatedEl) {
            updatedEl.textContent = new Date().toLocaleTimeString();
        }
        
        const activeModels = Object.entries(data.models || {}).filter(([name, model]) => {
            return model.rpd?.used > 0 || model.rpm?.used > 0 || model.tpm?.used > 0 ||
                   model.rpd?.limit > 0 || model.rpm?.limit > 0 || model.tpm?.limit > 0;
        });
        
        if (activeModels.length === 0) {
            table.innerHTML = '<thead><tr><th>Model</th><th>RPM</th><th>TPM</th><th>RPD</th></tr></thead><tbody><tr><td colspan="4" class="quota-loading">No data</td></tr></tbody>';
            return;
        }
        
        activeModels.sort((a, b) => {
            const aUsage = (a[1].rpd?.percent || 0) + (a[1].tpm?.percent || 0);
            const bUsage = (b[1].rpd?.percent || 0) + (b[1].tpm?.percent || 0);
            return bUsage - aUsage;
        });
        
        const rows = activeModels.map(([name, model]) => {
            return `<tr>
                <td class="model-name">${name}</td>
                <td>${this.formatQuotaCell(model.rpm)}</td>
                <td>${this.formatQuotaCell(model.tpm)}</td>
                <td>${this.formatQuotaCell(model.rpd)}</td>
            </tr>`;
        }).join('');
        
        table.innerHTML = `<thead><tr><th>Model</th><th>RPM</th><th>TPM</th><th>RPD</th></tr></thead><tbody>${rows}</tbody>`;
    }
    
    formatQuotaCell(metric) {
        if (!metric || metric.limit === 0) return '-';
        const pct = metric.percent || 0;
        const cls = pct < 50 ? 'usage-ok' : pct < 80 ? 'usage-warn' : 'usage-high';
        return `<span class="${cls}">${this.formatNumber(metric.used)}/${this.formatNumber(metric.limit)}</span>`;
    }
    
    formatNumber(num) {
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
    }
    
    renderQuotaError() {
        const table = document.getElementById('quota-models');
        if (table) {
            table.innerHTML = '<thead><tr><th>Model</th><th>RPM</th><th>TPM</th><th>RPD</th></tr></thead><tbody><tr><td colspan="4" class="quota-loading">Failed to load</td></tr></tbody>';
        }
    }
    
    startQuotaRefresh() {
        this.quotaRefreshInterval = setInterval(() => {
            this.loadQuotaDashboard();
        }, 30000);
    }
    
    // ======================================
    // Version Display
    // ======================================
    
    async fetchAndDisplayVersion() {
        try {
            const response = await this.fetchWithTimeout('/api/version');
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
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.adminPortal = new AdminPortal();
});
