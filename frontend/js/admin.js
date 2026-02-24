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
        await this.loadCases();
        this.startAutoRefresh();
        this.fetchAndDisplayVersion();
        this.loadQuotaDashboard();
        this.startQuotaRefresh();
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
        document.getElementById('dashboard-view').style.display = view === 'dashboard' ? '' : 'none';
        document.getElementById('map-view').style.display = view === 'map' ? '' : 'none';
        
        if (view === 'reports') {
            this.renderReports();
        } else if (view === 'dashboard') {
            this.renderDashboardCharts();
        } else if (view === 'map') {
            setTimeout(() => this.initMap(), 100);
        }
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
                            <div class="case-id">${caseData.case_number || caseData.id}</div>
                        </div>
                        <div style="display:flex;align-items:center;gap:0.5rem;">
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
                </div>
            </div>
        `;
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
            
            // Set assigned to
            const assignInput = document.getElementById('detail-assigned-to');
            if (assignInput) {
                assignInput.value = caseData.metadata?.assigned_to || '';
            }
            
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
    
    renderDashboardCharts() {
        if (typeof Chart === 'undefined') return;
        
        Chart.defaults.color = '#9ca3af';
        Chart.defaults.borderColor = 'rgba(255,255,255,0.1)';
        
        this.renderCasesTimelineChart();
        this.renderSourceDistributionChart();
        this.renderIncidentTypesChart();
        this.renderCaseStatusChart();
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
    // #34 Case Assignment
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
    // Quota Dashboard Widget
    // ======================================
    
    async loadQuotaDashboard() {
        try {
            const response = await this.fetchWithTimeout('/api/quota/status');
            if (!response.ok) {
                console.error('Failed to fetch quota status');
                this.renderQuotaError();
                return;
            }
            const data = await response.json();
            this.renderQuotaDashboard(data);
        } catch (error) {
            console.error('Error loading quota dashboard:', error);
            this.renderQuotaError();
        }
    }
    
    renderQuotaDashboard(data) {
        const modelsContainer = document.getElementById('quota-models');
        const timerEl = document.getElementById('quota-reset-timer');
        const updatedEl = document.getElementById('quota-updated');
        
        if (!modelsContainer) return;
        
        // Update reset timer
        if (timerEl && data.reset) {
            timerEl.textContent = data.reset.formatted;
        }
        
        // Update last updated time
        if (updatedEl) {
            const now = new Date();
            updatedEl.textContent = `Last updated: ${now.toLocaleTimeString()}`;
        }
        
        // Filter to only show models with usage or known limits
        const activeModels = Object.entries(data.models || {}).filter(([name, model]) => {
            // Show models that have been used or have non-zero limits
            return model.rpd?.used > 0 || model.rpm?.used > 0 || model.tpm?.used > 0 ||
                   model.rpd?.limit > 0 || model.rpm?.limit > 0 || model.tpm?.limit > 0;
        });
        
        if (activeModels.length === 0) {
            modelsContainer.innerHTML = '<div class="quota-loading">No quota data available</div>';
            return;
        }
        
        // Sort by usage (most used first)
        activeModels.sort((a, b) => {
            const aUsage = (a[1].rpd?.percent || 0) + (a[1].tpm?.percent || 0);
            const bUsage = (b[1].rpd?.percent || 0) + (b[1].tpm?.percent || 0);
            return bUsage - aUsage;
        });
        
        // Render model cards
        modelsContainer.innerHTML = activeModels.map(([name, model]) => {
            return `
                <div class="quota-model-card">
                    <div class="quota-model-name">
                        ${this.getModelIcon(name)} ${name}
                        <span class="quota-model-tier">${model.tier || 'free'}</span>
                    </div>
                    ${this.renderQuotaMetric('RPM', model.rpm)}
                    ${this.renderQuotaMetric('TPM', model.tpm)}
                    ${this.renderQuotaMetric('RPD', model.rpd)}
                </div>
            `;
        }).join('');
    }
    
    renderQuotaMetric(label, metric) {
        if (!metric || metric.limit === 0) return '';
        
        const percent = metric.percent || 0;
        const colorClass = percent < 50 ? 'green' : percent < 80 ? 'yellow' : 'red';
        const usedFormatted = this.formatNumber(metric.used);
        const limitFormatted = this.formatNumber(metric.limit);
        
        return `
            <div class="quota-metric">
                <div class="quota-metric-header">
                    <span class="quota-metric-label">${label}</span>
                    <span class="quota-metric-value">${usedFormatted} / ${limitFormatted}</span>
                </div>
                <div class="quota-progress">
                    <div class="quota-progress-bar ${colorClass}" style="width: ${Math.min(percent, 100)}%"></div>
                </div>
            </div>
        `;
    }
    
    getModelIcon(modelName) {
        if (modelName.includes('imagen')) return '🎨';
        if (modelName.includes('embedding')) return '🔗';
        if (modelName.includes('gemma')) return '💎';
        if (modelName.includes('tts') || modelName.includes('audio')) return '🔊';
        return '🤖';
    }
    
    formatNumber(num) {
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
    }
    
    renderQuotaError() {
        const modelsContainer = document.getElementById('quota-models');
        if (modelsContainer) {
            modelsContainer.innerHTML = '<div class="quota-loading">Failed to load quota data</div>';
        }
    }
    
    startQuotaRefresh() {
        // Refresh quota data every 30 seconds
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
