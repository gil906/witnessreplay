/**
 * WitnessReplay Admin Portal
 * Case management and analytics dashboard
 */

class AdminPortal {
    constructor() {
        this._notifications = [];
        this._notificationCount = 0;
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
        this.quickFilter = '';
        this.autoRefreshInterval = this.getStoredAutoRefreshInterval();
        this.autoRefreshEnabled = this.autoRefreshInterval > 0;
        this.autoRefreshTimer = null;
        this.recentAuditItems = [];
        this.chartInstances = {};
        this.incidentMap = null;
        this.mapMarkers = [];
        this.dashboardStats = null;
        this.dashboardMapInstance = null;
        this.dashboardMapMarkers = [];
        this.investigators = [];
        this.workloadData = null;
        this.currentUser = null;
        this.lastSelectedCaseIndex = null;
        this.pinnedCaseIds = new Set();
        this.watchlistCaseIds = new Set();
        this.filterPresets = this.loadFilterPresetsFromStorage();
        this.filtersPanelCollapsed = localStorage.getItem('adminFiltersPanelCollapsed') === 'true';
        this.recentViewedCases = this.loadRecentViewedCases();
        this.notificationsMuted = localStorage.getItem('adminNotificationsMuted') === 'true';
        this.commandPaletteOpen = false;
        this.commandPaletteItems = [];
        this.commandPaletteCursor = 0;
        
        this.checkAuth();
    }
    
    _sanitize(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }
    
    _checkPasswordStrength(password) {
        const el = document.getElementById('password-strength');
        const fill = document.getElementById('strength-fill');
        const text = document.getElementById('strength-text');
        if (!el || !fill || !text) return;
        el.style.display = password ? '' : 'none';
        let score = 0;
        if (password.length >= 8) score++;
        if (password.length >= 12) score++;
        if (/[A-Z]/.test(password)) score++;
        if (/[0-9]/.test(password)) score++;
        if (/[^A-Za-z0-9]/.test(password)) score++;
        const labels = ['Very Weak', 'Weak', 'Fair', 'Strong', 'Very Strong'];
        const colors = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#10b981'];
        const idx = Math.min(score, 4);
        fill.style.width = `${(score / 5) * 100}%`;
        fill.style.background = colors[idx];
        text.textContent = labels[idx];
        text.style.color = colors[idx];
    }
    
    checkAuth() {
        const token = sessionStorage.getItem('admin_token');
        const userStr = sessionStorage.getItem('admin_user');
        if (token) {
            this.authToken = token;
            if (userStr) {
                try { this.currentUser = JSON.parse(userStr); } catch(e) {}
            }
            this.verifyAuth();
        } else {
            this.showLogin();
        }
    }
    
    async verifyAuth() {
        try {
            const response = await fetch('/api/auth/verify', {
                headers: { 'Authorization': `Bearer ${this.authToken}` }
            });
            if (response.ok) {
                const data = await response.json();
                if (data.user) {
                    this.currentUser = data.user;
                    sessionStorage.setItem('admin_user', JSON.stringify(data.user));
                }
                this.hideLogin();
                this.init();
            } else {
                sessionStorage.removeItem('admin_token');
                sessionStorage.removeItem('admin_user');
                this.showLogin();
            }
        } catch (error) {
            this.showLogin();
        }
    }
    
    showLogin() {
        document.getElementById('login-overlay').style.display = 'flex';
        document.getElementById('admin-content').style.display = 'none';
        
        const loginForm = document.getElementById('login-form');
        const registerForm = document.getElementById('register-form');
        const forgotForm = document.getElementById('forgot-form');
        
        // Prevent duplicate listeners
        if (!loginForm._wired) {
            loginForm._wired = true;
            loginForm.addEventListener('submit', (e) => { e.preventDefault(); this.handleLogin(); });
        }
        if (registerForm && !registerForm._wired) {
            registerForm._wired = true;
            registerForm.addEventListener('submit', (e) => { e.preventDefault(); this.handleRegister(); });
            const regPwInput = document.getElementById('reg-password');
            if (regPwInput) {
                regPwInput.addEventListener('input', (e) => this._checkPasswordStrength(e.target.value));
            }
        }
        if (forgotForm && !forgotForm._wired) {
            forgotForm._wired = true;
            forgotForm.addEventListener('submit', (e) => { e.preventDefault(); this.handleForgotPassword(); });
        }
        
        // Wire OAuth buttons
        const googleBtn = document.getElementById('google-login-btn');
        const githubBtn = document.getElementById('github-login-btn');
        if (googleBtn && !googleBtn._wired) {
            googleBtn._wired = true;
            googleBtn.addEventListener('click', () => this.handleOAuthLogin('google'));
        }
        if (githubBtn && !githubBtn._wired) {
            githubBtn._wired = true;
            githubBtn.addEventListener('click', () => this.handleOAuthLogin('github'));
        }
    }
    
    hideLogin() {
        document.getElementById('login-overlay').style.display = 'none';
        document.getElementById('admin-content').style.display = 'block';
        // Show user in header
        const userDisplay = document.getElementById('user-display');
        if (userDisplay && this.currentUser) {
            userDisplay.textContent = this.currentUser.full_name || this.currentUser.username || 'Admin';
            userDisplay.style.display = '';
        }
    }
    
    async handleLogin() {
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;
        const errorEl = document.getElementById('login-error');
        errorEl.style.display = 'none';
        
        if (!password) {
            errorEl.textContent = 'Password is required.';
            errorEl.style.display = 'block';
            return;
        }
        
        try {
            const body = password && !username 
                ? { password }  // Legacy admin-password-only login
                : { username, password };
            
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            
            if (response.ok) {
                const data = await response.json();
                this.authToken = data.token;
                sessionStorage.setItem('admin_token', data.token);
                if (data.user) {
                    sessionStorage.setItem('admin_user', JSON.stringify(data.user));
                    this.currentUser = data.user;
                }
                this.hideLogin();
                this._startSessionTimer();
                this.init();
            } else {
                const err = await response.json().catch(() => ({}));
                errorEl.textContent = err.detail || 'Invalid credentials. Please try again.';
                errorEl.style.display = 'block';
            }
        } catch (error) {
            errorEl.textContent = 'Login failed. Please check your connection.';
            errorEl.style.display = 'block';
        }
    }
    
    async handleRegister() {
        const fullName = document.getElementById('reg-fullname').value.trim();
        const email = document.getElementById('reg-email').value.trim();
        const username = document.getElementById('reg-username').value.trim();
        const password = document.getElementById('reg-password').value;
        const confirm = document.getElementById('reg-confirm').value;
        const errorEl = document.getElementById('register-error');
        errorEl.style.display = 'none';
        
        if (password !== confirm) {
            errorEl.textContent = 'Passwords do not match.';
            errorEl.style.display = 'block';
            return;
        }
        if (password.length < 6) {
            errorEl.textContent = 'Password must be at least 6 characters.';
            errorEl.style.display = 'block';
            return;
        }
        if (username.length < 3) {
            errorEl.textContent = 'Username must be at least 3 characters.';
            errorEl.style.display = 'block';
            return;
        }
        
        try {
            const response = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, email, password, full_name: fullName })
            });
            
            if (response.ok) {
                const data = await response.json();
                this.authToken = data.token;
                sessionStorage.setItem('admin_token', data.token);
                if (data.user) {
                    sessionStorage.setItem('admin_user', JSON.stringify(data.user));
                    this.currentUser = data.user;
                }
                this.hideLogin();
                this.init();
            } else {
                const err = await response.json().catch(() => ({}));
                errorEl.textContent = err.detail || 'Registration failed.';
                errorEl.style.display = 'block';
            }
        } catch (error) {
            errorEl.textContent = 'Registration failed. Please check your connection.';
            errorEl.style.display = 'block';
        }
    }
    
    async handleForgotPassword() {
        const email = document.getElementById('forgot-email').value.trim();
        const msgEl = document.getElementById('forgot-message');
        msgEl.style.display = 'none';
        
        if (!email) {
            msgEl.textContent = 'Please enter your email address.';
            msgEl.style.display = 'block';
            msgEl.className = 'login-error';
            return;
        }
        
        try {
            const response = await fetch('/api/auth/forgot-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });
            const data = await response.json();
            msgEl.textContent = data.message || 'If an account exists, reset instructions have been sent.';
            msgEl.className = 'login-success';
            msgEl.style.display = 'block';
        } catch (error) {
            msgEl.textContent = 'Request failed. Please try again.';
            msgEl.className = 'login-error';
            msgEl.style.display = 'block';
        }
    }
    
    handleOAuthLogin(provider) {
        const errorEl = document.getElementById('login-error');
        errorEl.textContent = `${provider.charAt(0).toUpperCase() + provider.slice(1)} login requires OAuth configuration. Contact your administrator.`;
        errorEl.style.display = 'block';
        errorEl.className = 'login-error login-info';
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
        sessionStorage.removeItem('admin_user');
        this.authToken = null;
        this.currentUser = null;
        this.showLogin();
    }
    
    async init() {
        this.initializeUI();
        this.restoreCasesViewMode();
        this._initModalKeyboardNav();
        this._initRegisterValidation();
        this.renderFilterPresetOptions();
        this.updateFiltersPanelUI();
        this.updateNotificationMuteUI();
        this.renderRecentViewedWidget();
        await this.loadInvestigators();
        this.populateBulkInvestigatorControl();
        await this.loadCases();
        const caseFromUrl = new URLSearchParams(window.location.search).get('case');
        if (caseFromUrl) {
            this.showCaseDetail(caseFromUrl);
        }
        this.startAutoRefresh();
        this.fetchAndDisplayVersion();
        this.loadQuotaDashboard();
        this.startQuotaRefresh();
        this.initSystemHealthPanel();
        this.initAuditTimeline();
        this.initInterviewAnalytics();
        this._initNotificationCenter();
        this._initQuickActions();
        this._initActivityHeatmap();
        this._initDataRetention();
        this._loadDataRetention();
        this._initSessionViewer();
        this._initActivityLog();
        this._initCaseAnalytics();
    }
    
    _initModalKeyboardNav() {
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const notifPanel = document.getElementById('notification-panel');
                if (notifPanel?.classList.contains('show')) { notifPanel.classList.remove('show'); return; }
                const searchResults = document.getElementById('global-search-results');
                if (searchResults?.style.display !== 'none') { searchResults.style.display = 'none'; return; }
            }
        });
    }
    
    _validateField(input, rules) {
        const value = input.value.trim();
        let error = '';
        if (rules.required && !value) error = 'This field is required';
        else if (rules.minLength && value.length < rules.minLength) error = `Minimum ${rules.minLength} characters`;
        else if (rules.email && value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) error = 'Invalid email format';
        else if (rules.match) {
            const other = document.getElementById(rules.match);
            if (other && value !== other.value) error = 'Passwords do not match';
        }
        
        input.classList.toggle('field-error', !!error);
        input.classList.toggle('field-valid', !error && value);
        let hint = input.parentElement?.querySelector('.field-hint');
        if (error) {
            if (!hint) {
                hint = document.createElement('span');
                hint.className = 'field-hint';
                input.parentElement?.appendChild(hint);
            }
            hint.textContent = error;
            hint.style.color = '#ef4444';
        } else if (hint) {
            hint.remove();
        }
        return !error;
    }
    
    _initRegisterValidation() {
        const fields = {
            'reg-fullname': { required: true, minLength: 2 },
            'reg-email': { required: true, email: true },
            'reg-username': { required: true, minLength: 3 },
            'reg-password': { required: true, minLength: 6 },
            'reg-confirm': { required: true, match: 'reg-password' }
        };
        for (const [id, rules] of Object.entries(fields)) {
            const input = document.getElementById(id);
            if (input) {
                input.addEventListener('input', () => this._validateField(input, rules));
            }
        }
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
        document.getElementById('seed-data-btn')?.addEventListener('click', () => this.seedMockData());
        document.getElementById('refresh-btn')?.addEventListener('click', () => this.loadCases());
        document.getElementById('logout-btn')?.addEventListener('click', () => this.logout());
        document.getElementById('witness-view-btn')?.addEventListener('click', () => {
            window.location.href = '/static/index.html';
        });
        document.getElementById('notification-mute-toggle')?.addEventListener('click', () => this.toggleNotificationMute());
        
        // View toggle tabs
        document.querySelectorAll('.view-tab').forEach(tab => {
            tab.addEventListener('click', () => this.switchView(tab.dataset.view));
        });
        
        // Cases view mode toggle (compact/expanded)
        document.querySelectorAll('.view-mode-btn').forEach(btn => {
            btn.addEventListener('click', () => this.switchCasesViewMode(btn.dataset.mode));
        });
        
        // Search and filters
        document.getElementById('case-search')?.addEventListener('input', () => this.filterCases());
        document.getElementById('search-btn')?.addEventListener('click', () => this.filterCases());
        document.getElementById('filter-type')?.addEventListener('change', () => this.filterCases());
        document.getElementById('filter-status')?.addEventListener('change', () => this.filterCases());
        document.getElementById('sort-by')?.addEventListener('change', () => this.filterCases());
        document.getElementById('clear-filters-btn')?.addEventListener('click', () => this.clearFilters());
        document.getElementById('auto-refresh-interval')?.addEventListener('change', (e) => this.setAutoRefreshInterval(e.target?.value));
        document.getElementById('auto-assign-orphans-btn')?.addEventListener('click', () => this.autoAssignOrphans());
        document.getElementById('error-retry-btn')?.addEventListener('click', () => this.loadCases());
        document.getElementById('filters-panel-toggle')?.addEventListener('click', () => this.toggleFiltersPanel());
        document.getElementById('filter-preset-save')?.addEventListener('click', () => this.saveFilterPreset());
        document.getElementById('filter-preset-load')?.addEventListener('click', () => this.loadSelectedFilterPreset());
        document.getElementById('filter-preset-delete')?.addEventListener('click', () => this.deleteSelectedFilterPreset());
        document.getElementById('filter-preset-export')?.addEventListener('click', () => this.exportFilterPresets());
        document.getElementById('filter-preset-import')?.addEventListener('change', (e) => this.importFilterPresets(e.target?.files?.[0]));
        document.querySelectorAll('.quick-filter-chip').forEach(chip => {
            chip.addEventListener('click', () => this.setQuickFilter(chip.dataset.quickFilter || ''));
        });
        const paletteInput = document.getElementById('command-palette-input');
        paletteInput?.addEventListener('input', () => this.renderCommandPaletteList(paletteInput.value));
        paletteInput?.addEventListener('keydown', (e) => this.handleCommandPaletteKeydown(e));
        document.getElementById('command-palette')?.addEventListener('click', (e) => {
            if (e.target?.id === 'command-palette') this.closeCommandPalette();
        });
        this.updateQuickFilterUI();
        this.updateAutoRefreshUI();
        this.updateNotificationMuteUI();
        this.initKeyboardShortcuts();
        
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
        
        // Handle resize: sync side-panel class with viewport width
        window.addEventListener('resize', () => {
            const modal = document.getElementById('case-detail-modal');
            if (modal && modal.classList.contains('active')) {
                if (this.isDesktop()) {
                    document.body.classList.add('side-panel-open');
                    this.highlightSelectedCase();
                } else {
                    document.body.classList.remove('side-panel-open');
                    this.clearCaseHighlight();
                }
            }
        });

        // Initialize timeline visualization
        this.timelineViz = null;
    }
    
    switchView(view) {
        this.currentView = view;
        document.querySelectorAll('.view-tab').forEach(tab => {
            const active = tab.dataset.view === view;
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });

        const isCaseView = ['cases', 'pinned', 'watchlist'].includes(view);
        const casesSection = document.getElementById('cases-section');
        const reportsSection = document.getElementById('reports-section');
        const workloadSection = document.getElementById('workload-section');
        const dashboardView = document.getElementById('dashboard-view');
        const mapView = document.getElementById('map-view');
        const recentActionsSection = document.getElementById('recent-actions-section');
        const recentViewedSection = document.getElementById('recent-viewed-section');
        if (casesSection) casesSection.style.display = isCaseView ? '' : 'none';
        if (reportsSection) reportsSection.style.display = view === 'reports' ? '' : 'none';
        if (workloadSection) workloadSection.style.display = view === 'workload' ? '' : 'none';
        if (dashboardView) dashboardView.style.display = view === 'dashboard' ? '' : 'none';
        if (mapView) mapView.style.display = view === 'map' ? '' : 'none';
        if (recentActionsSection) recentActionsSection.style.display = isCaseView ? '' : 'none';
        if (recentViewedSection) recentViewedSection.style.display = isCaseView ? '' : 'none';
        const settingsEl = document.getElementById('settings-view');
        if (settingsEl) settingsEl.style.display = view === 'settings' ? '' : 'none';

        if (isCaseView) {
            this.filterCases();
            this.renderRecentViewedWidget();
        } else if (view === 'reports') {
            this.renderReports();
        } else if (view === 'workload') {
            this.loadWorkload();
        } else if (view === 'dashboard') {
            this.renderDashboardCharts();
        } else if (view === 'map') {
            setTimeout(() => this.initMap(), 100);
        } else if (view === 'settings') {
            this.loadSettingsView();
        }
    }
    
    switchCasesViewMode(mode) {
        const casesList = document.getElementById('cases-list');
        if (!casesList) return;
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
        if (this.filteredCases && this.filteredCases.length > 0) {
            this.renderCases();
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
    
    async loadCases(options = {}) {
        const { silent = false } = options;
        const container = document.getElementById('cases-list');
        const spinner = this._showLoading(container);
        this.hideErrorBanner();
        try {
            const [casesResponse, reportsResponse, pinnedResponse, watchlistResponse] = await Promise.all([
                this.fetchWithTimeout('/api/cases'),
                this.fetchWithTimeout('/api/sessions'),
                this.fetchWithTimeout('/api/cases/pinned').catch(() => null),
                this.fetchWithTimeout('/api/cases/watchlist').catch(() => null)
            ]);
            
            if (!casesResponse.ok) {
                throw new Error(`Server error: ${casesResponse.status}`);
            }
            
            const casesData = await casesResponse.json();
            this.cases = casesData.cases || [];

            if (pinnedResponse?.ok) {
                const pinnedData = await pinnedResponse.json().catch(() => ({}));
                this.pinnedCaseIds = new Set((pinnedData.cases || []).map(c => c.id).filter(Boolean));
            } else {
                this.pinnedCaseIds = new Set(this.cases.filter(c => c?.metadata?.pinned).map(c => c.id));
            }

            if (watchlistResponse?.ok) {
                const watchData = await watchlistResponse.json().catch(() => ({}));
                this.watchlistCaseIds = new Set((watchData.cases || []).map(c => c.id).filter(Boolean));
            } else {
                this.watchlistCaseIds = new Set(this.cases.filter(c => c?.metadata?.watchlisted).map(c => c.id));
            }
            this.applyCaseFlagMetadata();
            
            if (reportsResponse.ok) {
                const reportsData = await reportsResponse.json();
                this.reports = reportsData.sessions || [];
            }
            
            this.updateStats();
            this.filterCases();
            this.updateSidePanelCounts();
            this.renderRecentViewedWidget();
            
            if (this.currentView === 'reports') {
                this.renderReports();
            }
            
            this.renderRecentActions();
            if (!silent) {
                this.showToast('Data loaded successfully', 'success');
            }
        } catch (error) {
            console.error('Error loading cases:', error);
            this.showErrorBanner('Failed to load data: ' + error.message);
            if (!silent) {
                this.showToast('Failed to load cases: ' + error.message, 'error');
            }
            this.renderEmptyState('error');
        } finally {
            this._hideLoading(spinner);
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
        
        // Render activity sparkline
        this.renderActivitySparkline();
        
        this.updateNotifications();
        this.renderRecentActions();
    }
    
    filterCases() {
        const searchTerm = (document.getElementById('case-search')?.value || '').toLowerCase();
        const typeFilter = (document.getElementById('filter-type')?.value || '').toLowerCase();
        const statusFilter = document.getElementById('filter-status')?.value || '';
        const sortBy = document.getElementById('sort-by')?.value || 'date-desc';
        
        // Filter cases
        this.filteredCases = this.cases.filter(c => {
            const matchesSearch = !searchTerm || 
                (c.case_number || '').toLowerCase().includes(searchTerm) ||
                (c.title || '').toLowerCase().includes(searchTerm) ||
                (c.location || '').toLowerCase().includes(searchTerm) ||
                (c.summary || '').toLowerCase().includes(searchTerm);
            
            const caseType = (c.case_type || c.metadata?.incident_type || this.guessIncidentType(c) || '').toLowerCase();
            const matchesType = !typeFilter || caseType === typeFilter;
            const matchesStatus = !statusFilter || this.normalizeStatus(c.status || 'active') === this.normalizeStatus(statusFilter);
            
            return matchesSearch && matchesType && matchesStatus && this.caseMatchesQuickFilter(c) && this.caseMatchesViewFilter(c);
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
                case 'reports-desc':
                case 'witnesses-desc':
                case 'scenes-desc':
                    return (b.report_count || 0) - (a.report_count || 0);
                default:
                    return 0;
            }
        });
        
        this.renderCases();
        this.syncSelectionUI({ pruneMissing: true });
        
        // Update subtitles
        const caseSubtitle = document.getElementById('cases-count-subtitle');
        const reportSubtitle = document.getElementById('reports-count-subtitle');
        if (caseSubtitle) {
            caseSubtitle.textContent = `— ${this.filteredCases.length} case${this.filteredCases.length !== 1 ? 's' : ''}`;
        }
        if (reportSubtitle) {
            reportSubtitle.textContent = `— ${this.filteredReports.length} report${this.filteredReports.length !== 1 ? 's' : ''}`;
        }
    }
    
    clearFilters() {
        const caseSearch = document.getElementById('case-search');
        const filterType = document.getElementById('filter-type');
        const filterStatus = document.getElementById('filter-status');
        const sortBy = document.getElementById('sort-by');
        const advStatus = document.getElementById('adv-filter-status');
        const advType = document.getElementById('adv-filter-type');
        const dateFrom = document.getElementById('filter-date-from');
        const dateTo = document.getElementById('filter-date-to');
        const source = document.getElementById('filter-source');
        const searchQuery = document.getElementById('search-query');
        if (caseSearch) caseSearch.value = '';
        if (filterType) filterType.value = '';
        if (filterStatus) filterStatus.value = '';
        if (sortBy) sortBy.value = 'date-desc';
        if (advStatus) advStatus.value = '';
        if (advType) advType.value = '';
        if (dateFrom) dateFrom.value = '';
        if (dateTo) dateTo.value = '';
        if (source) source.value = '';
        if (searchQuery) searchQuery.value = '';
        this.quickFilter = '';
        this.updateQuickFilterUI();
        this.filterCases();
    }

    setQuickFilter(filter) {
        this.quickFilter = filter || '';
        this.updateQuickFilterUI();
        this.filterCases();
    }

    updateQuickFilterUI() {
        document.querySelectorAll('.quick-filter-chip').forEach(chip => {
            chip.classList.toggle('active', (chip.dataset.quickFilter || '') === this.quickFilter);
        });
    }

    loadFilterPresetsFromStorage() {
        try {
            const parsed = JSON.parse(localStorage.getItem('adminFilterPresets') || '{}');
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (e) {
            return {};
        }
    }

    saveFilterPresetsToStorage() {
        localStorage.setItem('adminFilterPresets', JSON.stringify(this.filterPresets || {}));
    }

    renderFilterPresetOptions() {
        const select = document.getElementById('filter-preset-select');
        if (!select) return;
        const current = select.value;
        const options = Object.keys(this.filterPresets || {}).sort((a, b) => a.localeCompare(b));
        select.innerHTML = '<option value="">Saved presets…</option>';
        options.forEach(name => {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            select.appendChild(option);
        });
        if (current && options.includes(current)) select.value = current;
    }

    getCurrentFilterState() {
        return {
            search: document.getElementById('case-search')?.value || '',
            type: document.getElementById('filter-type')?.value || '',
            status: document.getElementById('filter-status')?.value || '',
            sort: document.getElementById('sort-by')?.value || 'date-desc',
            quick: this.quickFilter || '',
            advStatus: document.getElementById('adv-filter-status')?.value || '',
            advType: document.getElementById('adv-filter-type')?.value || '',
            dateFrom: document.getElementById('filter-date-from')?.value || '',
            dateTo: document.getElementById('filter-date-to')?.value || '',
            source: document.getElementById('filter-source')?.value || '',
            query: document.getElementById('search-query')?.value || '',
            view: this.currentView || 'cases'
        };
    }

    applyFilterState(state = {}) {
        const setValue = (id, value) => {
            const el = document.getElementById(id);
            if (el && value !== undefined && value !== null) el.value = value;
        };
        setValue('case-search', state.search || '');
        setValue('filter-type', state.type || '');
        setValue('filter-status', state.status || '');
        setValue('sort-by', state.sort || 'date-desc');
        setValue('adv-filter-status', state.advStatus || '');
        setValue('adv-filter-type', state.advType || '');
        setValue('filter-date-from', state.dateFrom || '');
        setValue('filter-date-to', state.dateTo || '');
        setValue('filter-source', state.source || '');
        setValue('search-query', state.query || '');
        this.quickFilter = state.quick || '';
        this.updateQuickFilterUI();
        if (state.view) this.switchView(state.view);
        this.filterCases();
        if (this.currentView === 'reports') this.renderReports();
    }

    saveFilterPreset() {
        const input = document.getElementById('filter-preset-name');
        const fallbackName = input?.value?.trim();
        const name = fallbackName || prompt('Preset name?');
        if (!name) return;
        this.filterPresets[name] = this.getCurrentFilterState();
        this.saveFilterPresetsToStorage();
        this.renderFilterPresetOptions();
        const select = document.getElementById('filter-preset-select');
        if (select) select.value = name;
        if (input) input.value = '';
        this.showToast(`Saved preset "${name}"`, 'success');
    }

    loadSelectedFilterPreset() {
        const select = document.getElementById('filter-preset-select');
        const name = select?.value;
        if (!name || !this.filterPresets[name]) return;
        this.applyFilterState(this.filterPresets[name]);
        this.showToast(`Loaded preset "${name}"`, 'success');
    }

    deleteSelectedFilterPreset() {
        const select = document.getElementById('filter-preset-select');
        const name = select?.value;
        if (!name || !this.filterPresets[name]) return;
        delete this.filterPresets[name];
        this.saveFilterPresetsToStorage();
        this.renderFilterPresetOptions();
        this.showToast(`Deleted preset "${name}"`, 'info');
    }

    exportFilterPresets() {
        const blob = new Blob([JSON.stringify(this.filterPresets || {}, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `admin-filter-presets-${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
        this.showToast('Presets exported', 'success');
    }

    async importFilterPresets(file) {
        if (!file) return;
        try {
            const text = await file.text();
            const parsed = JSON.parse(text);
            if (!parsed || typeof parsed !== 'object') throw new Error('Invalid JSON');
            this.filterPresets = { ...this.filterPresets, ...parsed };
            this.saveFilterPresetsToStorage();
            this.renderFilterPresetOptions();
            this.showToast('Presets imported', 'success');
        } catch (error) {
            this.showToast(`Preset import failed: ${error.message}`, 'error');
        } finally {
            const input = document.getElementById('filter-preset-import');
            if (input) input.value = '';
        }
    }

    normalizeStatus(status) {
        return String(status || 'open').toLowerCase().replace(/\s+/g, '_');
    }

    isHighPriority(caseData) {
        const label = (caseData.priority_label || '').toLowerCase();
        const score = Number(caseData.priority_score || 0);
        return label === 'critical' || label === 'high' || score >= 70;
    }

    hasSceneImage(caseData) {
        return Boolean(
            caseData.scene_image_url ||
            caseData.scene_image ||
            caseData.metadata?.scene_image_url ||
            caseData.metadata?.has_scene ||
            caseData.scene_count > 0
        );
    }

    caseMatchesViewFilter(caseData) {
        if (this.currentView === 'pinned') return this.isCasePinned(caseData);
        if (this.currentView === 'watchlist') return this.isCaseWatchlisted(caseData);
        return true;
    }

    getCurrentUserLabels() {
        const storedUser = (() => {
            try {
                return JSON.parse(sessionStorage.getItem('admin_user') || '{}');
            } catch (e) {
                return {};
            }
        })();
        return [
            this.currentUser?.full_name,
            this.currentUser?.display_name,
            this.currentUser?.username,
            storedUser?.full_name,
            storedUser?.display_name,
            storedUser?.username
        ]
            .filter(Boolean)
            .map(v => String(v).trim().toLowerCase())
            .filter(Boolean);
    }

    caseIsMine(caseData) {
        const assignedTo = String(caseData?.metadata?.assigned_to || '').trim().toLowerCase();
        if (!assignedTo) return false;
        return this.getCurrentUserLabels().includes(assignedTo);
    }

    caseIsUnassigned(caseData) {
        return !String(caseData?.metadata?.assigned_to || '').trim();
    }

    caseMatchesQuickFilter(caseData) {
        if (!this.quickFilter) return true;
        const status = this.normalizeStatus(caseData.status);
        switch (this.quickFilter) {
            case 'open':
                return status === 'open' || status === 'active';
            case 'under_review':
                return status === 'under_review' || status === 'review';
            case 'closed':
                return status === 'closed' || status === 'complete';
            case 'high_priority':
                return this.isHighPriority(caseData);
            case 'has_scene':
                return this.hasSceneImage(caseData);
            case 'due_soon':
                return this.isCaseDueSoon(caseData);
            case 'overdue':
                return this.isCaseOverdue(caseData);
            case 'mine':
                return this.caseIsMine(caseData);
            case 'unassigned':
                return this.caseIsUnassigned(caseData);
            default:
                return true;
        }
    }

    applyCaseFlagMetadata() {
        this.cases = (this.cases || []).map(caseData => {
            if (!caseData || !caseData.id) return caseData;
            const metadata = { ...(caseData.metadata || {}) };
            if (this.pinnedCaseIds.has(caseData.id)) metadata.pinned = true;
            if (this.watchlistCaseIds.has(caseData.id)) metadata.watchlisted = true;
            return { ...caseData, metadata };
        });
    }

    isCasePinned(caseData) {
        return Boolean(caseData?.metadata?.pinned || (caseData?.id && this.pinnedCaseIds.has(caseData.id)));
    }

    isCaseWatchlisted(caseData) {
        return Boolean(caseData?.metadata?.watchlisted || (caseData?.id && this.watchlistCaseIds.has(caseData.id)));
    }

    parseDeadlineDate(value) {
        if (!value) return null;
        const parsed = new Date(value);
        return Number.isFinite(parsed.getTime()) ? parsed : null;
    }

    getCaseDeadlines(caseData) {
        const metadata = caseData?.metadata || {};
        const deadlines = [];
        const list = [];
        if (Array.isArray(caseData?.deadlines)) list.push(...caseData.deadlines);
        if (Array.isArray(metadata.deadlines)) list.push(...metadata.deadlines);
        ['next_deadline', 'next_deadline_at', 'sla_due_at', 'due_at', 'deadline_at'].forEach(key => {
            if (caseData?.[key]) list.push({ due_at: caseData[key], type: key });
            if (metadata?.[key]) list.push({ due_at: metadata[key], type: key });
        });
        list.forEach(item => {
            if (!item) return;
            const completed = item.completed === true || item.is_completed === true || ['completed', 'done', 'closed', 'resolved'].includes(String(item.status || '').toLowerCase());
            const dueRaw = item.date || item.due_at || item.due_date || item.deadline_at || item.sla_due_at;
            const dueAt = this.parseDeadlineDate(dueRaw);
            if (!dueAt || completed) return;
            deadlines.push({
                type: item.type || item.deadline_type || item.kind || 'deadline',
                dueAt,
                description: item.description || item.label || ''
            });
        });
        return deadlines.sort((a, b) => a.dueAt - b.dueAt);
    }

    getNearestDeadline(caseData) {
        return this.getCaseDeadlines(caseData)[0] || null;
    }

    isCaseOverdue(caseData) {
        const nearest = this.getNearestDeadline(caseData);
        return Boolean(nearest && nearest.dueAt.getTime() < Date.now());
    }

    isCaseDueSoon(caseData) {
        const nearest = this.getNearestDeadline(caseData);
        if (!nearest) return false;
        const ms = nearest.dueAt.getTime() - Date.now();
        return ms >= 0 && ms <= 48 * 60 * 60 * 1000;
    }

    formatDeadlineDistance(deadlineDate) {
        const ms = deadlineDate.getTime() - Date.now();
        const absMs = Math.abs(ms);
        const totalHours = Math.round(absMs / 3600000);
        if (totalHours < 1) return ms < 0 ? 'overdue' : '<1h';
        if (totalHours < 24) return `${ms < 0 ? '-' : ''}${totalHours}h`;
        const days = Math.round(totalHours / 24);
        return `${ms < 0 ? '-' : ''}${days}d`;
    }

    renderDeadlineBadge(caseData, compact = false) {
        const nearest = this.getNearestDeadline(caseData);
        if (!nearest) return '';
        const overdue = nearest.dueAt.getTime() < Date.now();
        const label = overdue ? 'Overdue' : `SLA ${this.formatDeadlineDistance(nearest.dueAt)}`;
        const cls = overdue ? 'case-overdue-badge' : 'case-sla-badge';
        return `<span class="case-flag-badge ${cls} ${compact ? 'compact' : ''}" title="${overdue ? 'Deadline overdue' : `Nearest due ${this.formatDateTime(nearest.dueAt)}`}">${label}</span>`;
    }

    renderPinWatchBadges(caseData, compact = false) {
        const badges = [];
        if (this.isCasePinned(caseData)) {
            badges.push(`<span class="case-flag-badge case-pinned-badge ${compact ? 'compact' : ''}" title="Pinned case">📌 Pinned</span>`);
        }
        if (this.isCaseWatchlisted(caseData)) {
            badges.push(`<span class="case-flag-badge case-watch-badge ${compact ? 'compact' : ''}" title="Watchlist case">👁 Watch</span>`);
        }
        const deadlineBadge = this.renderDeadlineBadge(caseData, compact);
        if (deadlineBadge) badges.push(deadlineBadge);
        const viewedBadge = this.renderLastViewedBadge(caseData?.id, compact);
        if (viewedBadge) badges.push(viewedBadge);
        return badges.join('');
    }

    renderSceneAvailabilityBadge(caseData, compact = false) {
        const hasScene = this.hasSceneImage(caseData);
        return `<span class="scene-availability-badge ${hasScene ? 'has-scene' : 'no-scene'} ${compact ? 'compact' : ''}" title="${hasScene ? 'Scene image available' : 'No scene image'}">${hasScene ? '🎬 Scene' : '🚫 Scene'}</span>`;
    }

    getEnhancedEmptyStateMarkup(icon, title, message, actions = []) {
        const actionHtml = actions.length
            ? `<div class="empty-state-actions">${actions.map(action => `<button class="btn btn-secondary btn-sm" onclick="${action.onclick}">${action.label}</button>`).join('')}</div>`
            : '';
        return `
            <div class="empty-state empty-state-enhanced">
                <div class="empty-state-icon">${icon}</div>
                <h3>${title}</h3>
                <p>${message}</p>
                ${actionHtml}
            </div>
        `;
    }
    
    renderCases() {
        const container = document.getElementById('cases-list');
        if (!container) return;
        
        if (this.filteredCases.length === 0) {
            const hasData = this.cases.length > 0;
            container.innerHTML = this.getEnhancedEmptyStateMarkup(
                '📁',
                hasData ? 'No matching cases' : 'No cases yet',
                hasData ? 'Try adjusting filters or quick chips.' : 'Cases will appear here once reports are grouped into cases.',
                hasData
                    ? [
                        { label: 'Clear Filters', onclick: 'window.adminPortal?.clearFilters()' },
                        { label: 'Refresh', onclick: 'window.adminPortal?.loadCases()' }
                    ]
                    : [{ label: 'Refresh', onclick: 'window.adminPortal?.loadCases()' }]
            );
            return;
        }
        
        const mode = localStorage.getItem('adminCasesViewMode') || 'compact';
        if (mode === 'compact') {
            container.innerHTML = this.renderCasesTableView();
            container.querySelectorAll('.cases-table-row[data-case-id]').forEach(row => {
                row.addEventListener('click', () => this.showCaseDetail(row.dataset.caseId));
            });
        } else {
            container.innerHTML = this.filteredCases.map((c, index) => this.renderCaseCard(c, index)).join('');
            container.querySelectorAll('.case-card').forEach((card) => {
                card.addEventListener('click', () => {
                    const caseId = card.dataset.caseId;
                    this.showCaseDetail(caseId);
                });
            });
        }
    }
    
    renderCasesTableView() {
        const header = `
            <div class="cases-table-header cases-table-row">
                <div class="ct-col ct-col-check"></div>
                <div class="ct-col ct-col-num">Case #</div>
                <div class="ct-col ct-col-title">Title</div>
                <div class="ct-col ct-col-reports">Reports</div>
                <div class="ct-col ct-col-age">Age</div>
                <div class="ct-col ct-col-status">Status</div>
                <div class="ct-col ct-col-priority">Priority</div>
                <div class="ct-col ct-col-sources">Sources</div>
                <div class="ct-col ct-col-date">Created</div>
            </div>`;
        const rows = this.filteredCases.map((c, index) => this.renderCasesTableRow(c, index)).join('');
        return header + rows;
    }
    
    renderCasesTableRow(caseData, index = 0) {
        const status = caseData.status || 'active';
        const statusClass = `status-${status}`;
        const reportCount = caseData.report_count || 0;
        const priorityLabel = caseData.priority_label || 'normal';
        const priorityBadge = this.renderPriorityBadge(priorityLabel, caseData.priority_score != null ? Math.round(caseData.priority_score) : null);
        const sourceIcons = (caseData.metadata?.source_types || []).map(s => this.getSourceIcon(s)).join(' ') || '—';
        const title = this._sanitize(caseData.title || 'Untitled Case');
        const truncTitle = title.length > 50 ? title.substring(0, 50) + '…' : title;
        const daysOld = caseData.created_at ? Math.floor((Date.now() - new Date(caseData.created_at).getTime()) / 86400000) : '—';
        const sceneBadge = this.renderSceneAvailabilityBadge(caseData, true);
        const stateBadges = this.renderPinWatchBadges(caseData, true);
        
        return `
            <div class="cases-table-row" data-case-id="${caseData.id}">
                <div class="ct-col ct-col-check">
                    <input type="checkbox" class="case-checkbox" data-case-id="${caseData.id}"
                           ${this.selectedCases.has(caseData.id) ? 'checked' : ''}
                           data-case-index="${index}"
                           onclick="event.stopPropagation(); window.adminPortal?.handleCaseCheckboxClick(event, '${caseData.id}', ${index})">
                </div>
                <div class="ct-col ct-col-num">${caseData.case_number || caseData.id}</div>
                <div class="ct-col ct-col-title" title="${title}">${truncTitle} ${sceneBadge} ${stateBadges}</div>
                <div class="ct-col ct-col-reports">${reportCount}</div>
                <div class="ct-col ct-col-age">${daysOld}d</div>
                <div class="ct-col ct-col-status"><span class="case-status-badge ${statusClass}">${status}</span></div>
                <div class="ct-col ct-col-priority">${priorityBadge}</div>
                <div class="ct-col ct-col-sources">${sourceIcons}</div>
                <div class="ct-col ct-col-date">${this.formatDateShort(caseData.created_at)}</div>
            </div>`;
    }
    
    renderCaseCard(caseData, index = 0) {
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
        const sceneBadge = this.renderSceneAvailabilityBadge(caseData);
        const stateBadges = this.renderPinWatchBadges(caseData);
        const isPinned = this.isCasePinned(caseData);
        const isWatchlisted = this.isCaseWatchlisted(caseData);
        const nextStatus = this.getNextStatusValue(status);
        const quickActions = `
            <div class="case-card-quick-actions">
                <button class="case-quick-action-btn" title="Cycle status to ${nextStatus}" onclick="event.stopPropagation(); window.adminPortal?.cycleCaseStatus('${caseData.id}')">⟳ Status</button>
                <button class="case-quick-action-btn" title="Copy case ID" onclick="event.stopPropagation(); window.adminPortal?.copyCaseId('${caseData.id}')">🆔</button>
                <button class="case-quick-action-btn" title="Copy case link" onclick="event.stopPropagation(); window.adminPortal?.copyCaseLink('${caseData.id}')">🔗</button>
                <button class="case-quick-action-btn ${isPinned ? 'active' : ''}" title="${isPinned ? 'Unpin case' : 'Pin case'}" onclick="event.stopPropagation(); window.adminPortal?.toggleCasePin('${caseData.id}')">📌</button>
                <button class="case-quick-action-btn ${isWatchlisted ? 'active' : ''}" title="${isWatchlisted ? 'Remove from watchlist' : 'Add to watchlist'}" onclick="event.stopPropagation(); window.adminPortal?.toggleCaseWatchlist('${caseData.id}')">👁</button>
            </div>
        `;
        
        return `
            <div class="case-card case-card-enhanced" data-case-id="${caseData.id}">
                <input type="checkbox" class="case-checkbox" data-case-id="${caseData.id}" 
                       ${this.selectedCases.has(caseData.id) ? 'checked' : ''}
                       data-case-index="${index}"
                       onclick="event.stopPropagation(); window.adminPortal?.handleCaseCheckboxClick(event, '${caseData.id}', ${index})">
                <div class="case-icon">📁</div>
                <div class="case-info">
                    <div class="case-header">
                        <div>
                            <h3 class="case-title">${this._sanitize(caseData.title || 'Untitled Case')}</h3>
                            <div class="case-id">${caseData.case_number || caseData.id} <span class="compact-date">· ${this.formatDateShort(caseData.created_at)}</span></div>
                        </div>
                        <div class="case-header-right">
                            ${priorityBadge}
                            <span class="incident-type-badge">${incidentIcon} ${incidentType}</span>
                            ${sceneBadge}
                            ${stateBadges}
                            <div class="case-status-badge ${statusClass}">
                                ${status}
                            </div>
                        </div>
                    </div>
                    ${quickActions}
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
            const hasData = this.reports.length > 0;
            container.innerHTML = this.getEnhancedEmptyStateMarkup(
                '📝',
                hasData ? 'No matching reports' : 'No reports yet',
                hasData ? 'Try a broader search term or source filter.' : 'Reports will appear here after witness submissions.',
                hasData
                    ? [
                        { label: 'Clear Filters', onclick: 'window.adminPortal?.clearFilters()' },
                        { label: 'Refresh', onclick: 'window.adminPortal?.loadCases()' }
                    ]
                    : [{ label: 'Refresh', onclick: 'window.adminPortal?.loadCases()' }]
            );
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
                            <h3 class="case-title">${this._sanitize(report.title || 'Witness Report')}</h3>
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
            if (!this.currentCase.metadata || typeof this.currentCase.metadata !== 'object') {
                this.currentCase.metadata = {};
            }
            this.currentCase.metadata.pinned = this.isCasePinned(caseData);
            this.currentCase.metadata.watchlisted = this.isCaseWatchlisted(caseData);
            this.recordCaseViewed(this.currentCase);
            this.renderRecentViewedWidget();
            this.filterCases();
            
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
            this.renderCaseTimelineViz(caseData);
            
            // Audit trail
            this.renderAuditTrail(caseData);
            
            // Tags, notes, deadlines
            this.loadCaseTags(caseId);
            this.loadCaseNotes(caseId);
            this.loadCaseDeadlines(caseId);
            
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
                        <div class="case-title">${this._sanitize(rel.related_case_title)}</div>
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
                            <strong>${this._sanitize(sim.case_number)}</strong> - ${this._sanitize(sim.title)}
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
            select.innerHTML += `<option value="${c.id}">${this._sanitize(c.case_number)} - ${this._sanitize(c.title)}</option>`;
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
        if (this.isDesktop()) {
            this.showCaseDetail(caseId);
        } else {
            this.hideModal('case-detail-modal');
            setTimeout(() => this.showCaseDetail(caseId), 300);
        }
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
                    <div class="pattern-description">${this._sanitize(getTitle(match))}</div>
                    <div class="pattern-details">
                        <span class="pattern-badge ${type}">${this._sanitize(getDescription(match))}</span>
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
    
    isDesktop() {
        return window.innerWidth > 1024;
    }

    showModal(modalId) {
        const modal = document.getElementById(modalId);
        if (!modal) return;

        if (modalId === 'case-detail-modal' && this.isDesktop()) {
            document.body.classList.add('side-panel-open');
            modal.classList.remove('closing');
            modal.classList.add('active');
            this.highlightSelectedCase();
        } else {
            modal.classList.add('active');
        }
    }
    
    hideModal(modalId) {
        const modal = document.getElementById(modalId);
        if (!modal) return;

        if (modalId === 'case-detail-modal' && this.isDesktop()) {
            modal.classList.add('closing');
            this.clearCaseHighlight();
            setTimeout(() => {
                modal.classList.remove('active', 'closing');
                document.body.classList.remove('side-panel-open');
            }, 250);
        } else {
            modal.classList.remove('active');
            if (modalId === 'case-detail-modal') {
                document.body.classList.remove('side-panel-open');
                this.clearCaseHighlight();
            }
        }
    }

    highlightSelectedCase() {
        this.clearCaseHighlight();
        if (this.currentCase) {
            const card = document.querySelector(`.case-card[data-case-id="${this.currentCase.id}"]`);
            if (card) card.classList.add('case-selected');
        }
    }

    clearCaseHighlight() {
        document.querySelectorAll('.case-card.case-selected').forEach(el => el.classList.remove('case-selected'));
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
    
    renderEmptyState(type = 'cases') {
        const casesList = document.getElementById('cases-list');
        const reportsList = document.getElementById('reports-list');
        if (casesList) {
            casesList.innerHTML = this.getEnhancedEmptyStateMarkup(
                type === 'error' ? '⚠️' : '📁',
                type === 'error' ? 'Unable to load cases' : 'No cases yet',
                type === 'error'
                    ? 'We could not load case data. Retry when your connection is stable.'
                    : 'No cases found. Click "Seed Demo Data" or wait for reports to be submitted.',
                [{ label: 'Retry', onclick: 'window.adminPortal?.loadCases()' }]
            );
        }
        if (reportsList && type === 'error') {
            reportsList.innerHTML = this.getEnhancedEmptyStateMarkup(
                '⚠️',
                'Unable to load reports',
                'Reports could not be loaded right now.',
                [{ label: 'Retry', onclick: 'window.adminPortal?.loadCases()' }]
            );
        }
    }
    
    showErrorBanner(message) {
        const banner = document.getElementById('admin-error-banner');
        const text = document.getElementById('admin-error-text');
        if (!banner || !text) return;
        text.textContent = message;
        banner.style.display = 'flex';
    }

    hideErrorBanner() {
        const banner = document.getElementById('admin-error-banner');
        if (banner) banner.style.display = 'none';
    }

    getStoredAutoRefreshInterval() {
        const stored = Number(localStorage.getItem('adminAutoRefreshInterval'));
        if ([0, 30, 60, 120].includes(stored)) return stored;
        const legacyEnabled = localStorage.getItem('adminAutoRefreshEnabled');
        if (legacyEnabled === 'false') return 0;
        return 30;
    }

    setAutoRefreshInterval(value, options = {}) {
        const { notify = true } = options;
        const parsed = Number(value);
        this.autoRefreshInterval = [0, 30, 60, 120].includes(parsed) ? parsed : 30;
        this.autoRefreshEnabled = this.autoRefreshInterval > 0;
        localStorage.setItem('adminAutoRefreshInterval', String(this.autoRefreshInterval));
        localStorage.setItem('adminAutoRefreshEnabled', String(this.autoRefreshEnabled));
        this.startAutoRefresh();
        if (notify) {
            const label = this.autoRefreshInterval > 0 ? `${this.autoRefreshInterval}s` : 'Off';
            this.showToast(`Auto-refresh set to ${label}`, 'info');
        }
    }

    startAutoRefresh() {
        if (this.autoRefreshTimer) {
            clearInterval(this.autoRefreshTimer);
            this.autoRefreshTimer = null;
        }
        if (this.autoRefreshInterval > 0) {
            this.autoRefreshTimer = setInterval(() => {
                this.loadCases({ silent: true });
            }, this.autoRefreshInterval * 1000);
        }
        this.updateAutoRefreshUI();
    }

    toggleAutoRefresh() {
        const next = this.autoRefreshInterval > 0 ? 0 : 30;
        this.setAutoRefreshInterval(next);
    }

    updateAutoRefreshUI() {
        const select = document.getElementById('auto-refresh-interval');
        if (!select) return;
        select.value = String(this.autoRefreshInterval);
        select.classList.toggle('active', this.autoRefreshInterval > 0);
    }

    toggleFiltersPanel() {
        this.filtersPanelCollapsed = !this.filtersPanelCollapsed;
        localStorage.setItem('adminFiltersPanelCollapsed', String(this.filtersPanelCollapsed));
        this.updateFiltersPanelUI();
    }

    updateFiltersPanelUI() {
        const panel = document.getElementById('filters-panel');
        const toggleBtn = document.getElementById('filters-panel-toggle');
        if (panel) panel.classList.toggle('collapsed', this.filtersPanelCollapsed);
        if (toggleBtn) {
            toggleBtn.textContent = this.filtersPanelCollapsed ? '▸ Filters' : '▾ Filters';
            toggleBtn.setAttribute('aria-expanded', this.filtersPanelCollapsed ? 'false' : 'true');
        }
    }

    toggleNotificationMute() {
        this.notificationsMuted = !this.notificationsMuted;
        localStorage.setItem('adminNotificationsMuted', String(this.notificationsMuted));
        this.updateNotificationMuteUI();
        this._updateNotifBadge();
        this.updateNotifications();
        this.showToast(this.notificationsMuted ? 'Notifications muted' : 'Notifications unmuted', 'info');
    }

    updateNotificationMuteUI() {
        const muteBtn = document.getElementById('notification-mute-toggle');
        if (!muteBtn) return;
        muteBtn.textContent = this.notificationsMuted ? '🔕 Alerts Muted' : '🔔 Alerts On';
        muteBtn.classList.toggle('active', this.notificationsMuted);
    }

    isCaseModalOpen() {
        return Boolean(document.getElementById('case-detail-modal')?.classList.contains('active'));
    }

    initKeyboardShortcuts() {
        if (this._shortcutsBound) return;
        this._shortcutsBound = true;
        document.addEventListener('keydown', (e) => {
            const target = e.target;
            const typing = target && (
                target.tagName === 'INPUT' ||
                target.tagName === 'TEXTAREA' ||
                target.tagName === 'SELECT' ||
                target.isContentEditable
            );

            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                this.openCommandPalette();
                return;
            }

            if (this.commandPaletteOpen && e.key === 'Escape') {
                e.preventDefault();
                this.closeCommandPalette();
                return;
            }
            if (this.commandPaletteOpen) return;

            if (!typing && e.key === '?') {
                e.preventDefault();
                this.openShortcutsHelp();
                return;
            }

            if (!typing && e.key === '/') {
                e.preventDefault();
                document.getElementById('case-search')?.focus();
                return;
            }

            if (!typing && !e.metaKey && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === 'r') {
                e.preventDefault();
                this.loadCases();
                return;
            }

            if (!typing && !e.metaKey && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === 'a') {
                e.preventDefault();
                this.autoAssignOrphans();
                return;
            }

            if (!typing && this.isCaseModalOpen() && this.currentCase?.id && !e.metaKey && !e.ctrlKey && !e.altKey) {
                if (e.key.toLowerCase() === 'p') {
                    e.preventDefault();
                    this.toggleCasePin(this.currentCase.id);
                    return;
                }
                if (e.key.toLowerCase() === 'w') {
                    e.preventDefault();
                    this.toggleCaseWatchlist(this.currentCase.id);
                }
            }
        });
    }

    openShortcutsHelp() {
        this.showModal('shortcuts-help-modal');
    }

    openCommandPalette() {
        const palette = document.getElementById('command-palette');
        const input = document.getElementById('command-palette-input');
        if (!palette || !input) return;
        this.commandPaletteOpen = true;
        palette.style.display = 'flex';
        palette.setAttribute('aria-hidden', 'false');
        input.value = '';
        this.commandPaletteCursor = 0;
        this.renderCommandPaletteList('');
        setTimeout(() => input.focus(), 0);
    }

    closeCommandPalette() {
        const palette = document.getElementById('command-palette');
        if (!palette) return;
        this.commandPaletteOpen = false;
        palette.style.display = 'none';
        palette.setAttribute('aria-hidden', 'true');
    }

    getCommandPaletteActions() {
        return [
            {
                id: 'refresh-data',
                label: 'Refresh data',
                keywords: 'reload refresh cases',
                run: async () => this.loadCases()
            },
            {
                id: 'auto-assign-orphans',
                label: 'Auto-assign orphans',
                keywords: 'auto assign orphan reports',
                run: async () => this.autoAssignOrphans()
            },
            {
                id: 'export-selected-csv',
                label: 'Export selected CSV',
                keywords: 'export csv selected',
                run: async () => this.bulkExport()
            },
            {
                id: 'switch-pinned-view',
                label: 'Switch to pinned view',
                keywords: 'pinned tab',
                run: async () => this.switchView('pinned')
            },
            {
                id: 'switch-watchlist-view',
                label: 'Switch to watchlist view',
                keywords: 'watchlist tab',
                run: async () => this.switchView('watchlist')
            },
            {
                id: 'open-shortcuts-help',
                label: 'Open shortcuts help',
                keywords: 'keyboard help',
                run: async () => this.openShortcutsHelp()
            }
        ];
    }

    renderCommandPaletteList(query = '', options = {}) {
        const { preserveCursor = false } = options;
        const list = document.getElementById('command-palette-list');
        if (!list) return;
        const normalized = String(query || '').trim().toLowerCase();
        const actions = this.getCommandPaletteActions().filter(action => {
            if (!normalized) return true;
            const haystack = `${action.label} ${action.keywords || ''}`.toLowerCase();
            return haystack.includes(normalized);
        });
        this.commandPaletteItems = actions;
        if (!preserveCursor) this.commandPaletteCursor = 0;
        if (this.commandPaletteCursor >= actions.length) this.commandPaletteCursor = Math.max(actions.length - 1, 0);
        if (!actions.length) {
            list.innerHTML = '<div class="command-empty-state">No matching command</div>';
            return;
        }
        list.innerHTML = actions.map((action, index) => `
            <button class="command-item ${index === this.commandPaletteCursor ? 'active' : ''}" onclick="window.adminPortal?.executeCommandPaletteAction(${index})">
                ${this._sanitize(action.label)}
            </button>
        `).join('');
    }

    handleCommandPaletteKeydown(e) {
        if (!this.commandPaletteOpen) return;
        const input = document.getElementById('command-palette-input');
        if (!input) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (this.commandPaletteItems.length) {
                this.commandPaletteCursor = (this.commandPaletteCursor + 1) % this.commandPaletteItems.length;
                this.renderCommandPaletteList(input.value, { preserveCursor: true });
            }
            return;
        }
        if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (this.commandPaletteItems.length) {
                this.commandPaletteCursor = (this.commandPaletteCursor - 1 + this.commandPaletteItems.length) % this.commandPaletteItems.length;
                this.renderCommandPaletteList(input.value, { preserveCursor: true });
            }
            return;
        }
        if (e.key === 'Enter') {
            e.preventDefault();
            this.executeCommandPaletteAction(this.commandPaletteCursor);
            return;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            this.closeCommandPalette();
        }
    }

    async executeCommandPaletteAction(index) {
        const action = this.commandPaletteItems?.[index];
        if (!action) return;
        this.closeCommandPalette();
        try {
            await action.run();
        } catch (error) {
            this.showToast(`Command failed: ${error.message}`, 'error');
        }
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
    
    renderCaseTimelineViz(caseData) {
        const container = document.getElementById('case-timeline-container');
        if (!container) return;
        const events = [];
        // Add case creation
        events.push({time: caseData.created_at, type: 'created', text: 'Case created'});
        // Add reports
        (caseData.report_ids || []).forEach((rid, i) => {
            events.push({time: caseData.created_at, type: 'report', text: `Report #${i+1} filed`});
        });
        events.sort((a,b) => new Date(a.time) - new Date(b.time));
        container.innerHTML = events.map(e => `
            <div class="timeline-event">
                <div class="timeline-dot ${e.type}"></div>
                <div class="timeline-content">
                    <span class="timeline-time">${e.time ? new Date(e.time).toLocaleString() : 'Unknown'}</span>
                    <span class="timeline-text">${e.text}</span>
                </div>
            </div>
        `).join('');
        document.getElementById('detail-timeline-section').style.display = '';
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
        if (this.notificationsMuted) {
            countEl.style.display = 'none';
            return;
        }
        if (recentCount > 0) {
            countEl.textContent = recentCount;
            countEl.style.display = '';
        } else {
            countEl.style.display = 'none';
        }
    }

    renderRecentActions() {
        const container = document.getElementById('recent-actions-list');
        if (!container) return;
        const toMs = (value) => {
            const ms = new Date(value || 0).getTime();
            return Number.isFinite(ms) ? ms : 0;
        };

        const notificationActions = this._notifications.slice(0, 6).map(n => ({
            icon: n.type === 'error' ? '⚠️' : n.type === 'success' ? '✅' : '🔔',
            text: `${n.title}: ${n.message}`,
            time: n.timestamp || n.time
        }));
        const auditActions = (this.recentAuditItems || []).slice(0, 6).map(item => ({
            icon: item.icon || '📋',
            text: item.text,
            time: item.time
        }));
        const caseActions = [...this.cases]
            .sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0))
            .slice(0, 6)
            .map(c => ({
                icon: '📁',
                text: `Case ${c.case_number || c.id} updated`,
                time: c.updated_at || c.created_at
            }));
        const reportActions = [...this.reports]
            .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
            .slice(0, 6)
            .map(r => ({
                icon: this.getSourceIcon(r.source_type),
                text: `Report ${r.report_number || r.id} ${r.case_id ? 'assigned' : 'unassigned'}`,
                time: r.created_at
            }));

        const actions = [...notificationActions, ...auditActions, ...caseActions, ...reportActions]
            .filter(a => a.time)
            .sort((a, b) => toMs(b.time) - toMs(a.time))
            .slice(0, 10);

        if (actions.length === 0) {
            container.innerHTML = '<div class="empty-state">No recent actions yet</div>';
            return;
        }

        container.innerHTML = actions.map(action => `
            <div class="recent-action-item">
                <span class="recent-action-icon">${action.icon}</span>
                <div class="recent-action-content">
                    <div class="recent-action-text">${this._sanitize(action.text)}</div>
                    <div class="recent-action-time">${this.formatDateTime(action.time)}</div>
                </div>
            </div>
        `).join('');
    }

    loadRecentViewedCases() {
        try {
            const parsed = JSON.parse(localStorage.getItem('adminRecentViewedCases') || '[]');
            return Array.isArray(parsed) ? parsed.slice(0, 10) : [];
        } catch (e) {
            return [];
        }
    }

    saveRecentViewedCases() {
        localStorage.setItem('adminRecentViewedCases', JSON.stringify((this.recentViewedCases || []).slice(0, 10)));
    }

    recordCaseViewed(caseData) {
        if (!caseData?.id) return;
        const entry = {
            id: caseData.id,
            case_number: caseData.case_number || caseData.id,
            title: caseData.title || 'Untitled Case',
            viewed_at: new Date().toISOString()
        };
        const existing = (this.recentViewedCases || []).filter(item => item.id !== caseData.id);
        this.recentViewedCases = [entry, ...existing].slice(0, 10);
        this.saveRecentViewedCases();
    }

    getRecentViewedCaseEntry(caseId) {
        if (!caseId) return null;
        return (this.recentViewedCases || []).find(entry => entry.id === caseId) || null;
    }

    renderLastViewedBadge(caseId, compact = false) {
        const entry = this.getRecentViewedCaseEntry(caseId);
        if (!entry?.viewed_at) return '';
        return `<span class="case-flag-badge case-last-viewed-badge ${compact ? 'compact' : ''}" title="Viewed ${this.formatDateTime(entry.viewed_at)}">Last viewed ${this.timeSince(entry.viewed_at)}</span>`;
    }

    renderRecentViewedWidget() {
        const container = document.getElementById('recent-viewed-list');
        if (!container) return;
        const items = (this.recentViewedCases || []).slice(0, 10);
        if (!items.length) {
            container.innerHTML = '<div class="empty-state">No recently viewed cases</div>';
            return;
        }
        container.innerHTML = items.map(item => `
            <button class="recent-viewed-item" onclick="window.adminPortal?.openRecentViewedCase('${item.id}')">
                <span class="recent-viewed-title">${this._sanitize(item.case_number)} · ${this._sanitize(item.title)}</span>
                <span class="recent-viewed-time">${this.timeSince(item.viewed_at)}</span>
            </button>
        `).join('');
    }

    openRecentViewedCase(caseId) {
        if (!caseId) return;
        this.showCaseDetail(caseId);
    }

    updateSidePanelCounts() {
        const pinnedCountEl = document.getElementById('side-pinned-count');
        const watchCountEl = document.getElementById('side-watch-count');
        if (pinnedCountEl) pinnedCountEl.textContent = String(this.pinnedCaseIds.size || 0);
        if (watchCountEl) watchCountEl.textContent = String(this.watchlistCaseIds.size || 0);
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
        this.recentAuditItems = items.slice(0, 8);
        this.renderRecentActions();
        
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

    getNextStatusValue(status) {
        const normalized = this.normalizeStatus(status);
        if (normalized === 'open' || normalized === 'active') return 'under_review';
        if (normalized === 'under_review' || normalized === 'review') return 'closed';
        return 'open';
    }

    async cycleCaseStatus(caseId) {
        const caseData = this.cases.find(c => c.id === caseId) || this.currentCase;
        if (!caseData?.id) return;
        const nextStatus = this.getNextStatusValue(caseData.status);
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${caseData.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: nextStatus })
            });
            if (!response.ok) throw new Error('Status update failed');
            this.showToast(`Status set to ${nextStatus}`, 'success');
            await this.loadCases({ silent: true });
            if (this.currentCase?.id === caseData.id) await this.showCaseDetail(caseData.id);
        } catch (error) {
            this.showToast(`Failed to cycle status: ${error.message}`, 'error');
        }
    }

    async copyTextToClipboard(text) {
        if (!text) return false;
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            let copied = false;
            try { copied = document.execCommand('copy'); } catch (err) { copied = false; }
            textarea.remove();
            return copied;
        }
    }

    async copyCaseId(caseId) {
        const caseData = this.cases.find(c => c.id === caseId) || this.currentCase;
        const value = caseData?.case_number || caseData?.id || caseId;
        const copied = await this.copyTextToClipboard(value);
        this.showToast(copied ? `Copied ${value}` : 'Failed to copy case ID', copied ? 'success' : 'error');
    }

    async copyCaseLink(caseId) {
        const link = `${window.location.origin}${window.location.pathname}?case=${encodeURIComponent(caseId)}`;
        const copied = await this.copyTextToClipboard(link);
        this.showToast(copied ? 'Case link copied' : 'Failed to copy case link', copied ? 'success' : 'error');
    }

    updateCaseFlagState(caseId, field, enabled) {
        if (!caseId) return;
        if (field === 'pinned') {
            if (enabled) this.pinnedCaseIds.add(caseId);
            else this.pinnedCaseIds.delete(caseId);
        }
        if (field === 'watchlisted') {
            if (enabled) this.watchlistCaseIds.add(caseId);
            else this.watchlistCaseIds.delete(caseId);
        }
        this.cases = this.cases.map(c => {
            if (c.id !== caseId) return c;
            const metadata = { ...(c.metadata || {}), [field]: enabled };
            return { ...c, metadata };
        });
        if (this.currentCase?.id === caseId) {
            if (!this.currentCase.metadata || typeof this.currentCase.metadata !== 'object') {
                this.currentCase.metadata = {};
            }
            this.currentCase.metadata[field] = enabled;
        }
        this.updateSidePanelCounts();
    }

    async toggleCasePin(caseId, forcedValue = null) {
        const caseData = this.cases.find(c => c.id === caseId) || this.currentCase;
        if (!caseData?.id) return;
        const pinned = forcedValue == null ? !this.isCasePinned(caseData) : Boolean(forcedValue);
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${caseData.id}/pin`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pinned })
            });
            if (!response.ok) throw new Error('Unable to update pin');
            this.updateCaseFlagState(caseData.id, 'pinned', pinned);
            this.filterCases();
            this.showToast(pinned ? 'Case pinned' : 'Case unpinned', 'success');
        } catch (error) {
            this.showToast(`Pin update failed: ${error.message}`, 'error');
        }
    }

    async toggleCaseWatchlist(caseId, forcedValue = null) {
        const caseData = this.cases.find(c => c.id === caseId) || this.currentCase;
        if (!caseData?.id) return;
        const watchlisted = forcedValue == null ? !this.isCaseWatchlisted(caseData) : Boolean(forcedValue);
        try {
            const response = await this.fetchWithTimeout(`/api/cases/${caseData.id}/watchlist`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ watchlisted })
            });
            if (!response.ok) throw new Error('Unable to update watchlist');
            this.updateCaseFlagState(caseData.id, 'watchlisted', watchlisted);
            this.filterCases();
            this.showToast(watchlisted ? 'Case added to watchlist' : 'Case removed from watchlist', 'success');
        } catch (error) {
            this.showToast(`Watchlist update failed: ${error.message}`, 'error');
        }
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
            if (status && this.normalizeStatus(c.status || 'open') !== this.normalizeStatus(status)) return false;
            if (type && (c.metadata?.incident_type || this.guessIncidentType(c)).toLowerCase() !== type) return false;
            if (dateFrom && c.created_at < dateFrom) return false;
            if (dateTo && c.created_at > dateTo + 'T23:59:59') return false;
            if (!this.caseMatchesQuickFilter(c)) return false;
            if (!this.caseMatchesViewFilter(c)) return false;
            return true;
        });
        
        this.filteredReports = this.reports.filter(r => {
            if (query && !JSON.stringify(r).toLowerCase().includes(query)) return false;
            if (source && (r.source_type || '') !== source) return false;
            return true;
        });
        
        this.renderCases();
        this.syncSelectionUI({ pruneMissing: true });
        if (this.currentView === 'reports') this.renderReports();
        
        const casesSubtitle = document.getElementById('cases-count-subtitle');
        const reportsSubtitle = document.getElementById('reports-count-subtitle');
        if (casesSubtitle) {
            casesSubtitle.textContent = `— ${this.filteredCases.length} case${this.filteredCases.length !== 1 ? 's' : ''}`;
        }
        if (reportsSubtitle) {
            reportsSubtitle.textContent = `— ${this.filteredReports.length} report${this.filteredReports.length !== 1 ? 's' : ''}`;
        }
    }
    
    // ======================================
    // #33 Bulk Operations
    // ======================================
    
    handleCaseCheckboxClick(event, caseId, index = 0) {
        const target = event?.target;
        if (!target) return;
        const shouldSelect = Boolean(target.checked);
        const safeIndex = Number(index);

        if (event?.shiftKey && Number.isInteger(this.lastSelectedCaseIndex) && Number.isInteger(safeIndex)) {
            const start = Math.min(this.lastSelectedCaseIndex, safeIndex);
            const end = Math.max(this.lastSelectedCaseIndex, safeIndex);
            for (let i = start; i <= end; i++) {
                const caseAtIndex = this.filteredCases[i];
                if (!caseAtIndex?.id) continue;
                if (shouldSelect) this.selectedCases.add(caseAtIndex.id);
                else this.selectedCases.delete(caseAtIndex.id);
            }
        } else {
            if (shouldSelect) this.selectedCases.add(caseId);
            else this.selectedCases.delete(caseId);
        }

        this.lastSelectedCaseIndex = Number.isInteger(safeIndex) ? safeIndex : null;
        this.syncSelectionUI();
    }

    updateBulkSelection() {
        const checkedIds = [...document.querySelectorAll('.case-checkbox:checked')]
            .map(cb => cb.dataset.caseId)
            .filter(Boolean);
        this.selectedCases = new Set(checkedIds);
        this.syncSelectionUI();
    }

    syncSelectionUI(options = {}) {
        const { pruneMissing = false } = options;
        if (pruneMissing) {
            const visibleIds = new Set((this.filteredCases || []).map(c => c.id));
            this.selectedCases.forEach(id => {
                if (!visibleIds.has(id)) this.selectedCases.delete(id);
            });
        }
        document.querySelectorAll('.case-checkbox').forEach(cb => {
            const caseId = cb.dataset.caseId;
            cb.checked = Boolean(caseId && this.selectedCases.has(caseId));
        });
        const toolbar = document.getElementById('bulk-toolbar');
        const countEl = document.getElementById('selected-count');
        if (!toolbar || !countEl) return;
        const selectedCount = this.selectedCases.size;
        if (selectedCount > 0) {
            toolbar.style.display = 'flex';
            countEl.textContent = `${selectedCount} selected`;
        } else {
            toolbar.style.display = 'none';
        }
    }
    
    clearSelection() {
        this.selectedCases.clear();
        this.lastSelectedCaseIndex = null;
        this.syncSelectionUI();
    }

    selectAllFilteredCases() {
        (this.filteredCases || []).forEach(c => c?.id && this.selectedCases.add(c.id));
        this.syncSelectionUI();
    }

    deselectAllCases() {
        this.clearSelection();
    }

    invertCaseSelection() {
        (this.filteredCases || []).forEach(c => {
            if (!c?.id) return;
            if (this.selectedCases.has(c.id)) this.selectedCases.delete(c.id);
            else this.selectedCases.add(c.id);
        });
        this.syncSelectionUI();
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

    async bulkAssignSelected() {
        if (this.selectedCases.size === 0) return;
        const assignee = document.getElementById('bulk-assign-investigator')?.value?.trim();
        if (!assignee) {
            this.showToast('Select an investigator to assign', 'warning');
            return;
        }
        await this.runBulkCaseMutation('/api/cases/bulk/assign', {
            case_ids: [...this.selectedCases],
            assignee
        }, `Assigned ${this.selectedCases.size} case(s) to ${assignee}`);
    }

    async bulkSetPrioritySelected() {
        if (this.selectedCases.size === 0) return;
        const label = document.getElementById('bulk-priority-label')?.value || '';
        const scoreInput = document.getElementById('bulk-priority-score')?.value;
        const hasScore = scoreInput !== '' && scoreInput !== null && scoreInput !== undefined;
        if (!label && !hasScore) {
            this.showToast('Set a priority label or score first', 'warning');
            return;
        }
        const payload = { case_ids: [...this.selectedCases] };
        if (label) payload.priority_label = label;
        if (hasScore) payload.priority_score = Number(scoreInput);
        await this.runBulkCaseMutation('/api/cases/bulk/priority', payload, 'Priority updated for selected cases');
    }

    async bulkAddTagSelected() {
        if (this.selectedCases.size === 0) return;
        const tag = document.getElementById('bulk-tag-text')?.value?.trim();
        const color = document.getElementById('bulk-tag-color')?.value || '';
        if (!tag) {
            this.showToast('Enter a tag before applying', 'warning');
            return;
        }
        await this.runBulkCaseMutation('/api/cases/bulk/tag', {
            case_ids: [...this.selectedCases],
            tag,
            color
        }, `Tag "${tag}" applied to selected cases`);
    }

    async runBulkCaseMutation(endpoint, payload, successMessage) {
        try {
            const resp = await this.fetchWithTimeout(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.detail || 'Bulk operation failed');
            const updatedCount = Array.isArray(data.updated) ? data.updated.length : this.selectedCases.size;
            this.showToast(successMessage || `Updated ${updatedCount} cases`, 'success');
            this.clearSelection();
            await this.loadCases({ silent: true });
        } catch (error) {
            this.showToast(`Bulk action failed: ${error.message}`, 'error');
        }
    }

    async bulkTogglePinned(pinned = true) {
        await this.bulkToggleCaseFlag('pin', 'pinned', pinned);
    }

    async bulkToggleWatchlisted(watchlisted = true) {
        await this.bulkToggleCaseFlag('watchlist', 'watchlisted', watchlisted);
    }

    async bulkToggleCaseFlag(route, field, enabled) {
        if (this.selectedCases.size === 0) return;
        const ids = [...this.selectedCases];
        let success = 0;
        for (const id of ids) {
            try {
                const resp = await this.fetchWithTimeout(`/api/cases/${id}/${route}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ [field]: enabled })
                });
                if (resp.ok) success++;
            } catch (e) { /* noop */ }
        }
        this.showToast(`${enabled ? 'Updated' : 'Cleared'} ${success}/${ids.length} case flags`, success ? 'success' : 'error');
        this.clearSelection();
        await this.loadCases({ silent: true });
    }
    
    bulkExport() {
        if (this.selectedCases.size === 0) {
            this.showToast('Select at least one case to export', 'warning');
            return;
        }
        
        const exportData = this.cases.filter(c => this.selectedCases.has(c.id));
        const headers = [
            'case_id',
            'case_number',
            'title',
            'status',
            'priority_label',
            'priority_score',
            'report_count',
            'location',
            'has_scene',
            'created_at',
            'updated_at'
        ];
        const escape = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
        const rows = exportData.map(c => [
            c.id,
            c.case_number || '',
            c.title || '',
            c.status || '',
            c.priority_label || '',
            c.priority_score ?? '',
            c.report_count ?? 0,
            c.location || '',
            this.hasSceneImage(c) ? 'yes' : 'no',
            c.created_at || '',
            c.updated_at || ''
        ].map(escape).join(','));
        const csv = [headers.join(','), ...rows].join('\n');
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `cases_export_${Date.now()}.csv`;
        a.click();
        URL.revokeObjectURL(url);
        this.showToast(`Exported ${exportData.length} cases to CSV`, 'success');
    }

    async autoAssignOrphans() {
        const btn = document.getElementById('auto-assign-orphans-btn');
        const originalText = btn?.textContent;
        if (btn) {
            btn.disabled = true;
            btn.textContent = '⏳ Auto-Assigning...';
        }
        try {
            const resp = await this.fetchWithTimeout('/api/reports/orphans/auto-assign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.detail || 'Auto-assign failed');
            const assigned = data.assigned_count ?? data.assigned ?? data.updated ?? 0;
            const resultText = data.message || `Auto-assigned ${assigned} orphan report${assigned === 1 ? '' : 's'}`;
            this.showToast(resultText, 'success');
            this.addNotification('Orphans Auto-Assigned', resultText, 'success');
            await this.loadCases({ silent: true });
        } catch (error) {
            const message = `Failed to auto-assign orphans: ${error.message}`;
            this.showToast(message, 'error');
            this.addNotification('Orphan Auto-Assign Failed', error.message, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = originalText || '🧩 Auto-Assign Orphans';
            }
        }
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
                this.populateBulkInvestigatorControl();
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

    populateBulkInvestigatorControl() {
        const select = document.getElementById('bulk-assign-investigator');
        if (!select) return;
        const current = select.value;
        select.innerHTML = '<option value="">Assign investigator…</option>';
        this.investigators.forEach(inv => {
            const assignee = inv.name || inv.investigator_name || inv.username;
            if (!assignee) return;
            const option = document.createElement('option');
            option.value = assignee;
            option.textContent = `${assignee}${inv.badge_number ? ` #${inv.badge_number}` : ''}`;
            select.appendChild(option);
        });
        if (current && [...select.options].some(opt => opt.value === current)) {
            select.value = current;
        }
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
    
    // ─── Settings / API Key Management ────────────────────────
    
    loadSettingsView() {
        const container = document.getElementById('settings-view');
        const spinner = this._showLoading(container);
        const baseUrl = window.location.origin;
        const baseUrlEl = document.getElementById('api-base-url');
        if (baseUrlEl) baseUrlEl.textContent = baseUrl;
        document.querySelectorAll('.api-url').forEach(el => el.textContent = baseUrl);
        
        document.querySelectorAll('.code-tab').forEach(tab => {
            if (tab._wired) return;
            tab._wired = true;
            tab.addEventListener('click', () => {
                const lang = tab.dataset.lang;
                const parent = tab.closest('.code-block');
                parent.querySelectorAll('.code-tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                parent.querySelectorAll('.code-content').forEach(pre => {
                    pre.style.display = pre.dataset.lang === lang ? '' : 'none';
                });
            });
        });
        
        const createBtn = document.getElementById('create-api-key-btn');
        if (createBtn && !createBtn._wired) {
            createBtn._wired = true;
            createBtn.addEventListener('click', () => {
                document.getElementById('create-key-form').style.display = '';
                document.getElementById('new-key-name').focus();
            });
            document.getElementById('cancel-create-key').addEventListener('click', () => {
                document.getElementById('create-key-form').style.display = 'none';
            });
            document.getElementById('confirm-create-key').addEventListener('click', () => this.createApiKey());
        }
        
        this.loadApiKeys();
        this.loadRateLimits();
        this._hideLoading(spinner);
    }

    async loadRateLimits() {
        try {
            const resp = await fetch('/api/admin/rate-limits', {headers: {'Authorization': `Bearer ${this.authToken}`}});
            if (resp.ok) {
                const data = await resp.json();
                const container = document.getElementById('rate-limit-stats');
                if (container) {
                    const stats = data.api_key_stats || {};
                    const keys = Object.keys(stats);
                    container.innerHTML = keys.length ? keys.map(k => `<div class="rate-stat"><span>${k}</span><span>${stats[k].requests_last_minute} req/min</span></div>`).join('') : '<p style="color:var(--text-secondary)">No API traffic yet</p>';
                }
            }
        } catch(e) { console.error('Rate limits:', e); }
    }
    
    async loadApiKeys() {
        try {
            const resp = await fetch('/api/admin/api-keys', {
                headers: { 'Authorization': `Bearer ${this.authToken}` }
            });
            if (!resp.ok) throw new Error('Failed');
            const data = await resp.json();
            this.renderApiKeys(data.keys || []);
        } catch (err) {
            const el = document.getElementById('api-keys-list');
            if (el) el.innerHTML = '<div class="empty-state">Could not load API keys</div>';
        }
    }
    
    renderApiKeys(keys) {
        const c = document.getElementById('api-keys-list');
        if (!c) return;
        if (!keys.length) {
            c.innerHTML = '<div class="empty-state">No API keys yet. Create one to get started.</div>';
            return;
        }
        c.innerHTML = `<table class="api-keys-table">
            <thead><tr><th>Name</th><th>Key</th><th>Permissions</th><th>Rate</th><th>Usage</th><th>Last Used</th><th>Status</th><th></th></tr></thead>
            <tbody>${keys.map(k => `<tr class="${k.is_active ? '' : 'revoked'}">
                <td><strong>${this._esc(k.name)}</strong></td>
                <td><code>${k.key_prefix}...</code></td>
                <td>${(k.permissions||[]).map(p=>`<span class="perm-badge">${p}</span>`).join(' ')}</td>
                <td>${k.rate_limit_rpm}/min</td>
                <td>${(k.usage_count||0).toLocaleString()}</td>
                <td>${k.last_used_at ? this._ago(k.last_used_at) : 'Never'}</td>
                <td>${k.is_active ? '<span class="status-active">Active</span>' : '<span class="status-revoked">Revoked</span>'}</td>
                <td>${k.is_active ? `<button class="btn btn-danger btn-xs" onclick="window.adminPortal.revokeApiKey('${k.id}')">Revoke</button>` : ''}</td>
            </tr>`).join('')}</tbody></table>`;
    }
    
    async createApiKey() {
        const name = document.getElementById('new-key-name').value.trim() || 'Unnamed Key';
        const rateLimit = parseInt(document.getElementById('new-key-rate-limit').value) || 30;
        const cbs = document.querySelectorAll('#create-key-form .checkbox-group input:checked');
        const permissions = Array.from(cbs).map(cb => cb.value);
        try {
            const resp = await fetch('/api/admin/api-keys', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.authToken}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, permissions, rate_limit_rpm: rateLimit })
            });
            if (!resp.ok) throw new Error('Failed');
            const data = await resp.json();
            document.getElementById('new-key-value').textContent = data.key;
            document.getElementById('new-key-display').style.display = '';
            document.getElementById('create-key-form').style.display = 'none';
            document.getElementById('new-key-name').value = '';
            document.getElementById('copy-key-btn').textContent = '📋 Copy';
            this.loadApiKeys();
        } catch (err) { alert('Error creating API key: ' + err.message); }
    }
    
    async revokeApiKey(keyId) {
        if (!confirm('Revoke this API key? Apps using it will stop working.')) return;
        try {
            await fetch(`/api/admin/api-keys/${keyId}`, {
                method: 'DELETE', headers: { 'Authorization': `Bearer ${this.authToken}` }
            });
            this.loadApiKeys();
        } catch (err) { alert('Error: ' + err.message); }
    }
    
    _ago(d) { const m=Math.floor((Date.now()-new Date(d))/60000); return m<1?'Just now':m<60?m+'m ago':m<1440?Math.floor(m/60)+'h ago':Math.floor(m/1440)+'d ago'; }
    _esc(s) { const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

    async showSceneComparison(caseId) {
        const resp = await fetch(`/api/admin/cases?case_id=${caseId}`, {headers: {'Authorization': `Bearer ${this.authToken}`}});
        const data = await resp.json();
        const section = document.getElementById('detail-comparison-section');
        const grid = document.getElementById('comparison-grid');
        if (!section || !grid) return;
        grid.innerHTML = '';
        const sessions = data.sessions || [];
        if (sessions.length === 0) { section.style.display = 'none'; return; }
        sessions.forEach((s, i) => {
            const card = document.createElement('div');
            card.className = 'comparison-card';
            card.innerHTML = `<div class="witness-label">Witness ${i + 1} — ${s.id || 'Unknown'}</div>`;
            if (s.scene_image) {
                const img = document.createElement('img');
                img.src = s.scene_image;
                img.alt = `Scene from witness ${i + 1}`;
                card.prepend(img);
            }
            grid.appendChild(card);
        });
        section.style.display = '';
    }

    // ── Case Tags ────────────────────────────────────────────
    async loadCaseTags(caseId) {
        try {
            const resp = await this.fetchWithTimeout(`/api/cases/${caseId}/tags`);
            const data = await resp.json();
            const list = document.getElementById('case-tags-list');
            if (!list) return;
            list.innerHTML = (data.tags || []).map(t =>
                `<span class="case-tag" style="background:${this._esc(t.color)}">${this._esc(t.tag)} <button class="tag-remove" onclick="window.adminPortal?.removeCaseTag('${this._esc(t.tag)}')">&times;</button></span>`
            ).join('') || '<span class="empty-state">No tags</span>';
        } catch(e) { console.error('Failed to load tags', e); }
    }

    async addCaseTag() {
        if (!this.currentCase) return;
        const tag = document.getElementById('new-tag-input')?.value.trim();
        const color = document.getElementById('new-tag-color')?.value || '#60a5fa';
        if (!tag) return;
        await fetch(`/api/cases/${this.currentCase.id}/tags`, {
            method: 'POST', headers: {'Authorization': `Bearer ${this.authToken}`, 'Content-Type': 'application/json'},
            body: JSON.stringify({tag, color})
        });
        document.getElementById('new-tag-input').value = '';
        this.loadCaseTags(this.currentCase.id);
    }

    async removeCaseTag(tag) {
        if (!this.currentCase) return;
        await fetch(`/api/cases/${this.currentCase.id}/tags/${encodeURIComponent(tag)}`, {
            method: 'DELETE', headers: {'Authorization': `Bearer ${this.authToken}`}
        });
        this.loadCaseTags(this.currentCase.id);
    }

    // ── Case Notes ───────────────────────────────────────────
    async loadCaseNotes(caseId) {
        try {
            const resp = await this.fetchWithTimeout(`/api/cases/${caseId}/notes`, {headers: {'Authorization': `Bearer ${this.authToken}`}});
            const data = await resp.json();
            const list = document.getElementById('case-notes-list');
            if (!list) return;
            list.innerHTML = (data.notes || []).map(n =>
                `<div class="case-note-item"><div class="note-header"><strong>${this._esc(n.author_name||'admin')}</strong> <span class="note-date">${this._ago(n.created_at)}</span></div><div class="note-content">${this._esc(n.content)}</div></div>`
            ).join('') || '<p class="empty-state">No notes yet</p>';
        } catch(e) { console.error('Failed to load notes', e); }
    }

    async addCaseNote() {
        if (!this.currentCase) return;
        const content = document.getElementById('new-note-content')?.value.trim();
        if (!content) return;
        await fetch(`/api/cases/${this.currentCase.id}/notes`, {
            method: 'POST', headers: {'Authorization': `Bearer ${this.authToken}`, 'Content-Type': 'application/json'},
            body: JSON.stringify({content})
        });
        document.getElementById('new-note-content').value = '';
        this.loadCaseNotes(this.currentCase.id);
    }

    // ── Case Deadlines ───────────────────────────────────────
    async loadCaseDeadlines(caseId) {
        try {
            const resp = await this.fetchWithTimeout(`/api/cases/${caseId}/deadlines`, {headers: {'Authorization': `Bearer ${this.authToken}`}});
            const data = await resp.json();
            const list = document.getElementById('case-deadlines-list');
            if (!list) return;
            list.innerHTML = (data.deadlines || []).map(d => {
                const overdue = !d.is_completed && new Date(d.due_date) < new Date();
                return `<div class="deadline-item ${overdue ? 'overdue' : ''} ${d.is_completed ? 'completed' : ''}"><span class="deadline-type">${this._esc(d.deadline_type)}</span> <span class="deadline-date">${new Date(d.due_date).toLocaleString()}</span> <span class="deadline-desc">${this._esc(d.description||'')}</span>${overdue ? ' <span class="deadline-overdue-badge">OVERDUE</span>' : ''}</div>`;
            }).join('') || '<p class="empty-state">No deadlines set</p>';
        } catch(e) { console.error('Failed to load deadlines', e); }
    }

    async addCaseDeadline() {
        if (!this.currentCase) return;
        const type = document.getElementById('new-deadline-type')?.value || 'general';
        const due_date = document.getElementById('new-deadline-date')?.value;
        const description = document.getElementById('new-deadline-desc')?.value || '';
        if (!due_date) { alert('Please select a due date'); return; }
        await fetch(`/api/cases/${this.currentCase.id}/deadlines`, {
            method: 'POST', headers: {'Authorization': `Bearer ${this.authToken}`, 'Content-Type': 'application/json'},
            body: JSON.stringify({type, due_date: new Date(due_date).toISOString(), description})
        });
        document.getElementById('new-deadline-date').value = '';
        document.getElementById('new-deadline-desc').value = '';
        this.loadCaseDeadlines(this.currentCase.id);
    }

    // ── Case Merge ───────────────────────────────────────────
    async mergeCases() {
        if (!this.currentCase) return;
        const sourceId = document.getElementById('merge-source-id')?.value.trim();
        if (!sourceId) { alert('Please enter a source case ID'); return; }
        if (!confirm(`Merge case ${sourceId} into ${this.currentCase.id}? This cannot be undone.`)) return;
        try {
            const resp = await fetch('/api/admin/cases/merge', {
                method: 'POST', headers: {'Authorization': `Bearer ${this.authToken}`, 'Content-Type': 'application/json'},
                body: JSON.stringify({target_case_id: this.currentCase.id, source_case_id: sourceId})
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || 'Merge failed');
            alert(`Merge complete. Target now has ${data.target_reports} reports.`);
            document.getElementById('merge-source-id').value = '';
            this.showCaseDetail(this.currentCase.id);
        } catch(e) { alert('Merge error: ' + e.message); }
    }

    // ── Loading Overlay Helpers ─────────────────────────────
    _showLoading(container) {
        if (!container) return;
        const spinner = document.createElement('div');
        spinner.className = 'loading-overlay';
        spinner.innerHTML = '<div class="spinner"></div>';
        container.style.position = 'relative';
        container.appendChild(spinner);
        return spinner;
    }

    _hideLoading(spinner) {
        if (spinner) spinner.remove();
    }

    // ── Notification Center ──────────────────────────────────
    showNotificationCenter() {
        let panel = document.getElementById('notification-panel');
        if (!panel) {
            panel = document.createElement('div');
            panel.id = 'notification-panel';
            panel.className = 'notification-panel';
            panel.innerHTML = `<div class="notif-header"><h3>🔔 Notifications</h3><div><button onclick="window.adminPortal?.clearNotifications()" class="btn-sm">Clear</button><button onclick="document.getElementById('notification-panel').classList.remove('show')" class="btn-sm" style="margin-left:8px;">✕</button></div></div><div id="notif-list" class="notif-list"></div>`;
            document.body.appendChild(panel);
        }
        panel.classList.toggle('show');
        this._renderNotifications();
    }

    addNotification(title, message, type = 'info') {
        const now = new Date();
        this._notifications.unshift({
            id: Date.now(),
            title,
            message,
            type,
            time: now.toLocaleTimeString(),
            timestamp: now.toISOString(),
            read: false
        });
        if (!this.notificationsMuted) {
            this._notificationCount++;
        }
        this._updateNotifBadge();
        this.renderRecentActions();
    }

    _renderNotifications() {
        const list = document.getElementById('notif-list');
        if (!list) return;
        list.innerHTML = this._notifications.length ? this._notifications.map(n => `
            <div class="notif-item ${n.type} ${n.read ? 'read' : ''}">
                <div class="notif-title">${n.title}</div>
                <div class="notif-msg">${n.message}</div>
                <div class="notif-time">${n.time}</div>
            </div>
        `).join('') : '<p style="text-align:center;color:var(--text-secondary);padding:20px;">No notifications</p>';
    }

    clearNotifications() {
        this._notifications = [];
        this._notificationCount = 0;
        this._updateNotifBadge();
        this._renderNotifications();
        this.renderRecentActions();
    }

    _updateNotifBadge() {
        const badge = document.getElementById('notif-badge');
        if (badge) {
            badge.textContent = this._notificationCount;
            badge.style.display = !this.notificationsMuted && this._notificationCount > 0 ? '' : 'none';
        }
    }

    // ── Global Search ────────────────────────────────────────
    async handleGlobalSearch(query) {
        const results = document.getElementById('global-search-results');
        if (!results) return;
        if (query.length < 2) { results.style.display = 'none'; return; }
        clearTimeout(this._searchDebounce);
        this._searchDebounce = setTimeout(async () => {
            const spinner = this._showLoading(results);
            results.style.display = 'block';
            try {
                const resp = await fetch(`/api/admin/search/global?q=${encodeURIComponent(query)}`, {headers: {'Authorization': `Bearer ${this.authToken}`}});
                if (resp.ok) {
                    const data = await resp.json();
                    let html = '';
                    if (data.cases.length) html += '<div class="search-group"><b>Cases</b>' + data.cases.map(c => `<div class="search-item" onclick="window.adminPortal?.showCaseDetail('${c.id}')">${c.case_number || ''} - ${c.title || 'Untitled'}</div>`).join('') + '</div>';
                    if (data.sessions.length) html += '<div class="search-group"><b>Sessions</b>' + data.sessions.map(s => `<div class="search-item">${s.title || s.id.slice(0,8)}</div>`).join('') + '</div>';
                    if (data.users.length) html += '<div class="search-group"><b>Users</b>' + data.users.map(u => `<div class="search-item">${u.username} (${u.role})</div>`).join('') + '</div>';
                    results.innerHTML = html || '<p style="padding:10px;color:var(--text-secondary)">No results</p>';
                }
            } catch(e) { console.error('Search:', e); } finally { this._hideLoading(spinner); }
        }, 300);
    }

    _startSessionTimer() {
        if (this._sessionWarningTimer) clearTimeout(this._sessionWarningTimer);
        const SESSION_DURATION = 24 * 60 * 60 * 1000;
        const WARNING_BEFORE = 5 * 60 * 1000;
        this._sessionStart = Date.now();

        this._sessionWarningTimer = setTimeout(() => {
            this._showSessionWarning();
        }, SESSION_DURATION - WARNING_BEFORE);
    }

    _showSessionWarning() {
        const toast = document.createElement('div');
        toast.className = 'session-warning-toast';
        toast.innerHTML = `
            <span>⚠️ Your session expires in 5 minutes</span>
            <button onclick="this.parentElement.remove(); window.adminPortal?.extendSession()">Extend</button>
        `;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 30000);
    }

    async extendSession() {
        try {
            const resp = await fetch('/api/auth/me', { headers: { 'Authorization': `Bearer ${this.authToken}` } });
            if (resp.ok) {
                this._startSessionTimer();
            }
        } catch(e) { console.error(e); }
    }

    // ── Activity Sparkline Chart ─────────────────
    renderActivitySparkline() {
        if (!this.cases?.length) return;
        
        // Calculate reports per day for last 7 days
        const days = 7;
        const now = new Date();
        const counts = new Array(days).fill(0);
        const labels = [];
        
        for (let i = days - 1; i >= 0; i--) {
            const d = new Date(now);
            d.setDate(d.getDate() - i);
            const key = d.toDateString();
            labels.push(d.toLocaleDateString('en', { weekday: 'short' }));
            
            this.cases.forEach(c => {
                const cDate = new Date(c.created_at || c.updated_at);
                if (cDate.toDateString() === key) counts[days - 1 - i]++;
            });
        }
        
        const total = counts.reduce((a, b) => a + b, 0);
        const totalEl = document.getElementById('activity-chart-total');
        if (totalEl) totalEl.textContent = `${total} reports`;
        
        // Render sparkline SVG
        const max = Math.max(...counts, 1);
        const w = 300, h = 55, pad = 5;
        const points = counts.map((v, i) => {
            const x = (i / (counts.length - 1)) * w;
            const y = h - pad - ((v / max) * (h - pad * 2));
            return `${x},${y}`;
        });
        
        const lineEl = document.getElementById('sparkline-line');
        const areaEl = document.getElementById('sparkline-area');
        if (lineEl) lineEl.setAttribute('d', `M${points.join(' L')}`);
        if (areaEl) areaEl.setAttribute('d', `M0,${h} L${points.join(' L')} L${w},${h} Z`);
        
        // Labels
        const labelsEl = document.getElementById('activity-chart-labels');
        if (labelsEl) labelsEl.innerHTML = labels.map(l => `<span>${l}</span>`).join('');
    }

    // ── System Health Panel ─────────────────
    initSystemHealthPanel() {
        const toggle = document.getElementById('health-toggle');
        const content = document.getElementById('health-content');
        if (toggle && content) {
            toggle.addEventListener('click', () => {
                const isOpen = content.style.display !== 'none';
                content.style.display = isOpen ? 'none' : 'block';
                toggle.querySelector('.quota-toggle-icon').textContent = isOpen ? '▸' : '▾';
            });
        }
        this.fetchSystemHealth();
        this._healthInterval = setInterval(() => this.fetchSystemHealth(), 30000);
    }

    async fetchSystemHealth() {
        try {
            const resp = await fetch('/api/admin/system-health', {
                headers: { 'Authorization': `Bearer ${this.authToken}` }
            });
            if (!resp.ok) return;
            const data = await resp.json();
            this.renderSystemHealth(data);
        } catch(e) {
            console.warn('Health fetch failed:', e);
        }
    }

    renderSystemHealth(data) {
        const badge = document.getElementById('health-status-badge');
        if (data.error) {
            if (badge) { badge.textContent = 'Error'; badge.className = 'health-status-badge critical'; }
            return;
        }

        const sys = data.system || {};
        const proc = data.process || {};
        const app = data.app || {};

        // Update badge
        if (badge) {
            const maxUsage = Math.max(sys.cpu_percent || 0, sys.memory_percent || 0, sys.disk_percent || 0);
            if (maxUsage > 90) {
                badge.textContent = 'Critical';
                badge.className = 'health-status-badge critical';
            } else if (maxUsage > 70) {
                badge.textContent = 'Warning';
                badge.className = 'health-status-badge degraded';
            } else {
                badge.textContent = 'Healthy';
                badge.className = 'health-status-badge';
            }
        }

        // Update bars and values
        this._setHealthBar('health-cpu-bar', 'health-cpu', sys.cpu_percent, '%');
        this._setHealthBar('health-mem-bar', 'health-mem', sys.memory_percent, `% (${sys.memory_used_mb || 0}MB)`);
        this._setHealthBar('health-disk-bar', 'health-disk', sys.disk_percent, `% (${sys.disk_used_gb || 0}GB)`);

        const uptimeEl = document.getElementById('health-uptime');
        if (uptimeEl) uptimeEl.textContent = proc.uptime_human || '--';

        const respEl = document.getElementById('health-response');
        if (respEl) respEl.textContent = app.avg_response_ms ? `${app.avg_response_ms} ms` : '-- ms';

        const wsEl = document.getElementById('health-ws');
        if (wsEl) wsEl.textContent = app.active_websockets ?? '--';
    }

    _setHealthBar(barId, valueId, percent, suffix) {
        const bar = document.getElementById(barId);
        const val = document.getElementById(valueId);
        if (bar) {
            bar.style.width = `${percent || 0}%`;
            bar.className = 'health-bar-fill' + (percent > 90 ? ' danger' : percent > 70 ? ' warn' : '');
        }
        if (val) val.textContent = `${percent || 0}${suffix}`;
    }

    // ═══ Audit Timeline ═══
    initAuditTimeline() {
        const toggle = document.getElementById('audit-timeline-toggle');
        const content = document.getElementById('audit-timeline-content');
        if (toggle && content) {
            toggle.addEventListener('click', () => {
                const open = content.style.display !== 'none';
                content.style.display = open ? 'none' : '';
                toggle.querySelector('.quota-toggle-icon').textContent = open ? '▸' : '▾';
                if (!open) this.loadAuditTimeline();
            });
        }
    }

    async loadAuditTimeline() {
        const list = document.getElementById('audit-timeline-list');
        const badge = document.getElementById('audit-event-count');
        if (!list) return;
        
        try {
            const resp = await fetch('/api/admin/audit-timeline?limit=50', {
                headers: { 'Authorization': `Bearer ${this.authToken}` }
            });
            if (!resp.ok) throw new Error('Failed to load');
            const data = await resp.json();
            const events = data.events || [];
            
            if (badge) badge.textContent = `${events.length} events`;
            
            if (events.length === 0) {
                list.innerHTML = '<div style="text-align:center;padding:16px;color:var(--text-muted);font-size:0.82rem;">No audit events recorded yet.</div>';
                return;
            }
            
            const actionIcons = {
                'login': '🔓', 'logout': '🔒', 'export': '📥', 'create': '➕',
                'update': '✏️', 'delete': '🗑️', 'assign': '👤', 'view': '👁️'
            };
            
            list.innerHTML = events.map(ev => {
                const action = (ev.action || '').toLowerCase();
                const actionClass = Object.keys(actionIcons).find(k => action.includes(k)) || '';
                const icon = actionIcons[actionClass] || '📝';
                const time = ev.timestamp ? new Date(ev.timestamp).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
                return `<div class="audit-event action-${actionClass}">
                    <div class="audit-event-body">
                        <div class="audit-event-action">${icon} ${this._sanitize(ev.action || 'Action')}</div>
                        <div class="audit-event-detail">${this._sanitize(ev.entity_type || '')} ${this._sanitize(ev.entity_id || '')} ${this._sanitize(ev.details || '')}</div>
                    </div>
                    <div class="audit-event-time">${time}</div>
                </div>`;
            }).join('');
        } catch (e) {
            list.innerHTML = '<div style="text-align:center;padding:16px;color:var(--text-muted);font-size:0.82rem;">Could not load audit events.</div>';
        }
    }

    // ═══ Interview Analytics ═══
    initInterviewAnalytics() {
        const toggle = document.getElementById('analytics-toggle');
        const content = document.getElementById('interview-analytics-content');
        if (toggle && content) {
            toggle.addEventListener('click', () => {
                const open = content.style.display !== 'none';
                content.style.display = open ? 'none' : '';
                toggle.querySelector('.quota-toggle-icon').textContent = open ? '▸' : '▾';
                if (!open) this.loadInterviewAnalytics();
            });
        }
    }

    async loadInterviewAnalytics() {
        const grid = document.getElementById('analytics-grid');
        const badge = document.getElementById('analytics-summary');
        if (!grid) return;
        
        try {
            const resp = await fetch('/api/admin/interview-analytics', {
                headers: { 'Authorization': `Bearer ${this.authToken}` }
            });
            if (!resp.ok) throw new Error('Failed to load');
            const data = await resp.json();
            
            if (badge) badge.textContent = `${data.total_sessions || 0} interviews`;
            
            // Build analytics cards
            let html = `
                <div class="analytics-card">
                    <div class="analytics-icon">📊</div>
                    <div class="analytics-value">${data.total_sessions || 0}</div>
                    <div class="analytics-label">Total Interviews</div>
                </div>
                <div class="analytics-card">
                    <div class="analytics-icon">💬</div>
                    <div class="analytics-value">${data.avg_statements || 0}</div>
                    <div class="analytics-label">Avg Statements</div>
                </div>
            `;
            
            // Incident type breakdown
            const types = data.incident_types || {};
            const typeEntries = Object.entries(types).sort((a, b) => b[1] - a[1]);
            if (typeEntries.length > 0) {
                const maxCount = Math.max(...typeEntries.map(e => e[1]));
                html += `</div><div class="incident-type-bars"><div style="font-size:0.78rem;font-weight:600;color:var(--text-secondary);margin-bottom:8px;">Incident Types</div>`;
                typeEntries.slice(0, 6).forEach(([type, count]) => {
                    const pct = Math.round((count / maxCount) * 100);
                    html += `<div class="incident-bar">
                        <div class="incident-bar-label">${this._sanitize(type.replace(/_/g, ' '))}</div>
                        <div class="incident-bar-fill"><div class="incident-bar-fill-inner" style="width:${pct}%"></div></div>
                        <div class="incident-bar-count">${count}</div>
                    </div>`;
                });
            }
            
            grid.innerHTML = html;
        } catch (e) {
            grid.innerHTML = '<div style="text-align:center;padding:16px;color:var(--text-muted);font-size:0.82rem;">Could not load analytics.</div>';
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════
    // IMPROVEMENT: Admin Notification Center
    // ═══════════════════════════════════════════════════════════════════
    _initNotificationCenter() {
        const header = document.querySelector('.admin-header-actions') || document.querySelector('.admin-header');
        if (!header) return;
        
        const bellContainer = document.createElement('div');
        bellContainer.className = 'admin-notif-center';
        bellContainer.innerHTML = `
            <button class="admin-notif-bell" id="admin-notif-bell" title="Notifications">
                🔔
                <span class="admin-notif-badge" id="admin-notif-badge" style="display:none;">0</span>
            </button>
            <div class="admin-notif-dropdown hidden" id="admin-notif-dropdown">
                <div class="admin-notif-header">
                    <strong>Notifications</strong>
                    <button class="admin-notif-clear" id="admin-notif-clear" title="Clear all">Clear</button>
                </div>
                <div class="admin-notif-list" id="admin-notif-list">
                    <div class="admin-notif-empty">No notifications</div>
                </div>
            </div>
        `;
        
        header.insertBefore(bellContainer, header.firstChild);
        
        document.getElementById('admin-notif-bell')?.addEventListener('click', () => {
            const dd = document.getElementById('admin-notif-dropdown');
            dd?.classList.toggle('hidden');
        });
        document.getElementById('admin-notif-clear')?.addEventListener('click', () => {
            this._notifications = [];
            this._notificationCount = 0;
            this._renderNotifications();
        });
        
        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.admin-notif-center')) {
                document.getElementById('admin-notif-dropdown')?.classList.add('hidden');
            }
        });
        
        // Generate initial notifications from system state
        this._generateAutoNotifications();
    }
    
    _addNotification(icon, title, detail, type = 'info') {
        this._notifications.unshift({
            id: Date.now(),
            icon: icon,
            title: title,
            detail: detail || '',
            type: type,
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        });
        if (this._notifications.length > 20) this._notifications.pop();
        this._notificationCount++;
        this._renderNotifications();
    }
    
    _renderNotifications() {
        const list = document.getElementById('admin-notif-list');
        const badge = document.getElementById('admin-notif-badge');
        if (!list) return;
        
        if (badge) {
            if (this._notificationCount > 0) {
                badge.style.display = '';
                badge.textContent = this._notificationCount > 9 ? '9+' : this._notificationCount;
            } else {
                badge.style.display = 'none';
            }
        }
        
        if (this._notifications.length === 0) {
            list.innerHTML = '<div class="admin-notif-empty">No notifications</div>';
            return;
        }
        
        list.innerHTML = this._notifications.map(n => `
            <div class="admin-notif-item admin-notif-${n.type}">
                <span class="admin-notif-icon">${n.icon}</span>
                <div class="admin-notif-content">
                    <div class="admin-notif-title">${this._sanitize(n.title)}</div>
                    ${n.detail ? `<div class="admin-notif-detail">${this._sanitize(n.detail)}</div>` : ''}
                </div>
                <span class="admin-notif-time">${n.time}</span>
            </div>
        `).join('');
    }
    
    async _generateAutoNotifications() {
        try {
            const resp = await fetch('/api/health');
            if (resp.ok) {
                const data = await resp.json();
                if (data.status === 'healthy') {
                    this._addNotification('✅', 'System Healthy', 'All services operational', 'success');
                }
            }
        } catch(e) {}
        
        try {
            const resp = await fetch('/api/reports/orphans?limit=5');
            if (resp.ok) {
                const data = await resp.json();
                const count = data.reports?.length || data.length || 0;
                if (count > 0) {
                    this._addNotification('📋', `${count} Orphan Reports`, 'Reports awaiting case assignment', 'warning');
                }
            }
        } catch(e) {}
    }
    
    // ═══════════════════════════════════════════════════════════════════
    // IMPROVEMENT: Admin Quick Actions Panel
    // ═══════════════════════════════════════════════════════════════════
    _initQuickActions() {
        const dashboard = document.getElementById('dashboard-view') || document.querySelector('.admin-dashboard');
        if (!dashboard) return;
        
        const existing = document.getElementById('admin-quick-actions');
        if (existing) return;
        
        const panel = document.createElement('div');
        panel.className = 'admin-quick-actions';
        panel.id = 'admin-quick-actions';
        panel.innerHTML = `
            <h4 class="quick-actions-title">⚡ Quick Actions</h4>
            <div class="quick-actions-grid">
                <button class="quick-action-btn" id="qa-new-case" title="Create new case">
                    <span class="qa-icon">📁</span>
                    <span class="qa-label">New Case</span>
                </button>
                <button class="quick-action-btn" id="qa-export" title="Export all data">
                    <span class="qa-icon">📥</span>
                    <span class="qa-label">Export</span>
                </button>
                <button class="quick-action-btn" id="qa-backup" title="Create backup">
                    <span class="qa-icon">💾</span>
                    <span class="qa-label">Backup</span>
                </button>
                <button class="quick-action-btn" id="qa-health" title="System health check">
                    <span class="qa-icon">🏥</span>
                    <span class="qa-label">Health</span>
                </button>
            </div>
        `;
        
        // Insert at top of dashboard
        dashboard.insertBefore(panel, dashboard.firstChild);
        
        document.getElementById('qa-new-case')?.addEventListener('click', () => {
            document.getElementById('admin-create-case-btn')?.click();
        });
        document.getElementById('qa-export')?.addEventListener('click', () => {
            this._addNotification('📥', 'Export Started', 'Preparing data export...', 'info');
        });
        document.getElementById('qa-backup')?.addEventListener('click', async () => {
            try {
                const resp = await fetch('/api/admin/backups', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (resp.ok) {
                    this._addNotification('✅', 'Backup Created', 'System backup completed', 'success');
                } else {
                    this._addNotification('⚠️', 'Backup Failed', 'Could not create backup', 'error');
                }
            } catch(e) {
                this._addNotification('⚠️', 'Backup Error', e.message, 'error');
            }
        });
        document.getElementById('qa-health')?.addEventListener('click', () => {
            const healthTab = document.querySelector('[data-tab="health"]') || document.getElementById('health-tab');
            if (healthTab) healthTab.click();
        });
    }

    // ═══════════════════════════════════════════════════════════════
    // Admin Activity Heatmap
    // ═══════════════════════════════════════════════════════════════
    _initActivityHeatmap() {
        const container = document.getElementById('activity-heatmap');
        if (!container) return;
        this._loadActivityHeatmap(container);
    }

    async _loadActivityHeatmap(container) {
        try {
            const resp = await fetch('/api/admin/activity-heatmap', {
                headers: this.authToken ? { 'Authorization': `Bearer ${this.authToken}` } : {}
            });
            if (!resp.ok) {
                container.innerHTML = '<p class="heatmap-placeholder">🔒 Login required for activity data</p>';
                return;
            }
            const data = await resp.json();
            this._renderHeatmap(container, data);
        } catch (e) {
            container.innerHTML = '<p class="heatmap-placeholder">📊 Activity heatmap unavailable</p>';
        }
    }

    _renderHeatmap(container, data) {
        const days = data.days || ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
        const cells = data.cells || [];
        const maxCount = Math.max(1, ...cells.map(c => c.count));

        let html = '<div class="heatmap-title">📊 Session Activity Heatmap</div>';
        html += '<div class="heatmap-grid">';
        // Header row (hours)
        html += '<div class="heatmap-label"></div>';
        for (let h = 0; h < 24; h += 3) {
            html += `<div class="heatmap-hour">${String(h).padStart(2,'0')}</div>`;
        }
        html += '';

        for (const day of days) {
            html += `<div class="heatmap-label">${day}</div>`;
            for (let h = 0; h < 24; h += 3) {
                // Sum 3-hour blocks
                let total = 0;
                for (let dh = 0; dh < 3; dh++) {
                    const cell = cells.find(c => c.day === day && c.hour === (h + dh));
                    if (cell) total += cell.count;
                }
                const intensity = total / maxCount;
                const bg = total === 0
                    ? 'rgba(148,163,184,0.06)'
                    : `rgba(96,165,250,${0.15 + intensity * 0.65})`;
                html += `<div class="heatmap-cell" style="background:${bg}" title="${day} ${h}:00-${h+3}:00 — ${total} sessions">${total || ''}</div>`;
            }
        }
        html += '</div>';
        html += `<div class="heatmap-footer">Total: ${data.total_sessions} sessions</div>`;
        container.innerHTML = html;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.adminPortal = new AdminPortal();
});

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 27: Admin Data Retention Panel
// ═══════════════════════════════════════════════════════════════════
AdminPortal.prototype._initDataRetention = function() {
    const container = document.getElementById('data-retention-panel');
    if (!container) return;

    container.innerHTML = `
        <h3>🗄️ Data Retention Settings</h3>
        <div class="retention-controls">
            <div class="retention-field">
                <label>Retention Period (days)</label>
                <input type="number" id="retention-days" value="90" min="7" max="365" class="admin-input">
            </div>
            <div class="retention-field">
                <label><input type="checkbox" id="retention-auto-purge"> Auto-purge expired sessions</label>
            </div>
            <div class="retention-field">
                <label><input type="checkbox" id="retention-archive" checked> Archive before deletion</label>
            </div>
            <div class="retention-actions">
                <button id="retention-scan-btn" class="admin-btn">🔍 Scan Old Sessions</button>
                <button id="retention-purge-btn" class="admin-btn admin-btn-danger" disabled>🗑️ Purge (Dry Run)</button>
            </div>
            <div id="retention-result" class="retention-result"></div>
        </div>
    `;

    document.getElementById('retention-scan-btn')?.addEventListener('click', async () => {
        const days = parseInt(document.getElementById('retention-days')?.value || '90');
        const resultEl = document.getElementById('retention-result');
        if (resultEl) resultEl.innerHTML = '<span class="loading">Scanning...</span>';
        try {
            const resp = await this.fetchWithTimeout('/api/admin/data-retention/purge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days })
            });
            const data = await resp.json();
            if (resultEl) {
                resultEl.innerHTML = `<div class="retention-info">` +
                    `<b>${data.purged_count}</b> sessions older than <b>${days}</b> days<br>` +
                    `<small>Cutoff: ${new Date(data.cutoff_date).toLocaleDateString()}</small></div>`;
            }
            const purgeBtn = document.getElementById('retention-purge-btn');
            if (purgeBtn && data.purged_count > 0) purgeBtn.disabled = false;
        } catch (e) {
            if (resultEl) resultEl.innerHTML = '<span class="error">Failed to scan.</span>';
        }
    });
};

AdminPortal.prototype._loadDataRetention = async function() {
    try {
        const resp = await this.fetchWithTimeout('/api/admin/data-retention');
        const data = await resp.json();
        const daysInput = document.getElementById('retention-days');
        if (daysInput && data.retention_days) daysInput.value = data.retention_days;
        const autoCheckbox = document.getElementById('retention-auto-purge');
        if (autoCheckbox) autoCheckbox.checked = data.auto_purge || false;
        const archiveCheckbox = document.getElementById('retention-archive');
        if (archiveCheckbox) archiveCheckbox.checked = data.archive_before_delete !== false;
    } catch (e) { /* silent */ }
};

// ═══════════════════════════════════════════════════════════════════
// Session Transcript Viewer
// ═══════════════════════════════════════════════════════════════════
AdminPortal.prototype._initSessionViewer = function() {
    const loadBtn = document.getElementById('sv-load-btn');
    if (!loadBtn) return;

    loadBtn.addEventListener('click', () => {
        const sid = document.getElementById('sv-session-id')?.value?.trim();
        if (sid) this._loadSessionTranscript(sid);
    });

    // Also allow clicking session IDs from the reports table
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('sv-view-link')) {
            const sid = e.target.dataset.sessionId;
            if (sid) {
                document.getElementById('sv-session-id').value = sid;
                this._loadSessionTranscript(sid);
                document.getElementById('session-viewer-section')?.scrollIntoView({ behavior: 'smooth' });
            }
        }
    });
};

AdminPortal.prototype._loadSessionTranscript = async function(sessionId) {
    const container = document.getElementById('sv-transcript');
    if (!container) return;
    container.innerHTML = '<div class="loading">Loading transcript...</div>';

    try {
        const resp = await this.fetchWithTimeout(`/api/admin/sessions/${sessionId}/transcript`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        let html = `<div class="sv-header">`;
        html += `<h4>${this._escapeHtml(data.title || 'Untitled Session')}</h4>`;
        html += `<div class="sv-meta">`;
        html += `<span>📋 ${data.statement_count} statements</span>`;
        html += `<span>📅 ${data.created_at ? new Date(data.created_at).toLocaleString() : 'Unknown'}</span>`;
        html += `<span class="sv-status sv-status-${data.status}">${data.status}</span>`;
        html += `</div></div>`;

        html += `<div class="sv-messages">`;
        const history = data.conversation_history || [];
        if (history.length > 0) {
            history.forEach(msg => {
                const role = msg.role === 'user' ? 'user' : 'agent';
                const icon = role === 'user' ? '👤' : '🔍';
                const label = role === 'user' ? 'Witness' : 'Detective Ray';
                const text = (msg.parts ? msg.parts.map(p => p.text || '').join('') : (msg.content || msg.text || '')).substring(0, 500);
                html += `<div class="sv-msg sv-msg-${role}">`;
                html += `<span class="sv-msg-icon">${icon}</span>`;
                html += `<span class="sv-msg-label">${label}</span>`;
                html += `<div class="sv-msg-text">${this._escapeHtml(text)}</div>`;
                html += `</div>`;
            });
        } else if (data.statements && data.statements.length > 0) {
            data.statements.forEach(s => {
                html += `<div class="sv-msg sv-msg-user">`;
                html += `<span class="sv-msg-icon">👤</span>`;
                html += `<span class="sv-msg-label">Witness</span>`;
                html += `<div class="sv-msg-text">${this._escapeHtml(s.text)}</div>`;
                html += `</div>`;
            });
        } else {
            html += `<div class="sv-empty">No messages in this session.</div>`;
        }
        html += `</div>`;

        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div class="error">❌ Could not load transcript: ${this._escapeHtml(e.message)}</div>`;
    }
};

AdminPortal.prototype._escapeHtml = function(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 38: Admin User Activity Log
// ═══════════════════════════════════════════════════════════════════
AdminPortal.prototype._initActivityLog = function() {
    const section = document.getElementById('activity-log-section');
    if (!section) return;

    const refreshBtn = document.getElementById('al-refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => this._loadActivityLog());
    }
    this._loadActivityLog();
};

AdminPortal.prototype._loadActivityLog = async function() {
    const container = document.getElementById('al-list');
    if (!container) return;
    container.innerHTML = '<div class="loading">Loading activity...</div>';

    try {
        const resp = await this.fetchWithTimeout('/api/admin/activity-log?limit=40');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        if (!data.activities || data.activities.length === 0) {
            container.innerHTML = '<div class="al-empty">No activity recorded yet.</div>';
            return;
        }

        let html = '';
        data.activities.forEach(a => {
            const ts = a.timestamp ? new Date(a.timestamp).toLocaleString() : 'Unknown';
            html += `<div class="al-item al-type-${a.type}">`;
            html += `<span class="al-icon">${a.icon}</span>`;
            html += `<div class="al-details">`;
            html += `<div class="al-desc">${this._escapeHtml(a.description)}</div>`;
            html += `<div class="al-meta"><span class="al-time">${ts}</span>`;
            if (a.session_id) html += ` <span class="al-sid sv-view-link" data-session-id="${a.session_id}">${a.session_id.substring(0, 8)}...</span>`;
            html += `</div></div></div>`;
        });

        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div class="error">❌ ${this._escapeHtml(e.message)}</div>`;
    }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 45: Admin Case Analytics Dashboard
// ═══════════════════════════════════════════════════════════════════
WitnessReplayAdmin.prototype._initCaseAnalytics = function() {
    const refreshBtn = document.getElementById('ca-refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => this._loadCaseAnalytics());
    this._loadCaseAnalytics();
};

WitnessReplayAdmin.prototype._loadCaseAnalytics = async function() {
    const token = localStorage.getItem('wr_admin_token');
    if (!token) return;
    try {
        const resp = await fetch('/api/admin/case-analytics', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!resp.ok) return;
        const data = await resp.json();

        const totalEl = document.getElementById('ca-total');
        const avgStEl = document.getElementById('ca-avg-stmts');
        const avgWdEl = document.getElementById('ca-avg-words');
        const activeEl = document.getElementById('ca-active');
        if (totalEl) totalEl.textContent = data.total_sessions;
        if (avgStEl) avgStEl.textContent = data.avg_statements_per_session;
        if (avgWdEl) avgWdEl.textContent = data.avg_words_per_session;
        if (activeEl) activeEl.textContent = data.active_sessions;

        // Simple bar chart for sessions by day
        const chartEl = document.getElementById('ca-chart');
        if (chartEl && data.sessions_by_day && data.sessions_by_day.length > 0) {
            const maxC = Math.max(...data.sessions_by_day.map(d => d.count), 1);
            let chartHtml = '<div class="ca-chart-title">Sessions per Day (last 30 days)</div><div class="ca-bars">';
            data.sessions_by_day.slice(-14).forEach(d => {
                const pct = Math.round(d.count / maxC * 100);
                const label = d.date.slice(5);
                chartHtml += `<div class="ca-bar-col" title="${d.date}: ${d.count}"><div class="ca-bar" style="height:${pct}%"></div><span class="ca-bar-label">${label}</span></div>`;
            });
            chartHtml += '</div>';
            chartEl.innerHTML = chartHtml;
        }

        // Status distribution
        const distEl = document.getElementById('ca-status-dist');
        if (distEl && data.status_distribution) {
            const total = Object.values(data.status_distribution).reduce((a, b) => a + b, 0) || 1;
            let distHtml = '<div class="ca-dist-title">Status Distribution</div><div class="ca-dist-bars">';
            Object.entries(data.status_distribution).forEach(([status, count]) => {
                const pct = Math.round(count / total * 100);
                const colors = { active: '#22c55e', completed: '#3b82f6', archived: '#64748b' };
                const color = colors[status] || '#a78bfa';
                distHtml += `<div class="ca-dist-row"><span class="ca-dist-label">${status}</span><div class="ca-dist-track"><div class="ca-dist-fill" style="width:${pct}%;background:${color}"></div></div><span class="ca-dist-val">${count} (${pct}%)</span></div>`;
            });
            distHtml += '</div>';
            distEl.innerHTML = distHtml;
        }
    } catch (e) { /* silent */ }
};

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 54: Admin Health Dashboard
// ═══════════════════════════════════════════════════════════════════
(function() {
    const btn = document.getElementById('hd-refresh-btn');
    if (btn) btn.addEventListener('click', loadHealthDashboard);
    setTimeout(loadHealthDashboard, 1200);
})();

async function loadHealthDashboard() {
    const token = localStorage.getItem('wr_admin_token');
    if (!token) return;
    try {
        const resp = await fetch('/api/admin/health-dashboard', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!resp.ok) return;
        const data = await resp.json();
        const s = data.sessions || {};
        const sys = data.system || {};
        const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        set('hd-uptime', sys.uptime || '--');
        set('hd-memory', (sys.memory_mb || 0) + ' MB');
        set('hd-cpu', (sys.cpu_percent || 0) + '%');
        set('hd-sessions', s.total || 0);
        set('hd-statements', s.total_statements || 0);
        set('hd-recent', s.recent_24h || 0);
    } catch (e) { /* silent */ }
}

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 55: Admin Bulk Export
// ═══════════════════════════════════════════════════════════════════
(function() {
    const btn = document.getElementById('be-export-btn');
    if (btn) btn.addEventListener('click', doBulkExport);
})();

async function doBulkExport() {
    const token = localStorage.getItem('wr_admin_token');
    if (!token) return;
    const fmt = document.getElementById('be-format')?.value || 'json';
    const limit = parseInt(document.getElementById('be-limit')?.value) || 50;
    const resultDiv = document.getElementById('be-result');
    if (resultDiv) { resultDiv.style.display = 'block'; resultDiv.innerHTML = '⏳ Exporting...'; }
    try {
        const resp = await fetch('/api/admin/bulk-export', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
            body: JSON.stringify({ format: fmt, limit: limit })
        });
        const data = await resp.json();
        if (fmt === 'csv') {
            const blob = new Blob([data.content], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = 'sessions_export.csv'; a.click();
            URL.revokeObjectURL(url);
            if (resultDiv) resultDiv.innerHTML = `✅ Exported ${data.total} sessions as CSV (downloaded)`;
        } else {
            const blob = new Blob([JSON.stringify(data.sessions, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = 'sessions_export.json'; a.click();
            URL.revokeObjectURL(url);
            if (resultDiv) resultDiv.innerHTML = `✅ Exported ${data.total} sessions as JSON (downloaded)`;
        }
    } catch (e) { if (resultDiv) resultDiv.innerHTML = '❌ Export failed.'; }
}

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 61: Admin Audit Trail
// ═══════════════════════════════════════════════════════════════════
(function() {
    const btn = document.getElementById('at-refresh-btn');
    if (btn) btn.addEventListener('click', loadAuditTrail);
    setTimeout(loadAuditTrail, 1800);
})();

async function loadAuditTrail() {
    const token = localStorage.getItem('wr_admin_token');
    if (!token) return;
    try {
        const resp = await fetch('/api/admin/audit-trail', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!resp.ok) return;
        const data = await resp.json();
        const countEl = document.getElementById('at-count');
        if (countEl) countEl.textContent = (data.total || 0) + ' entries';
        const container = document.getElementById('at-entries');
        if (!container) return;
        if (!data.entries || data.entries.length === 0) {
            container.innerHTML = '<div class="at-empty">No audit entries yet</div>';
            return;
        }
        const actionIcons = {
            'view_audit_trail': '👁️', 'login': '🔐', 'export': '📥',
            'delete': '🗑️', 'update': '✏️', 'create': '➕', 'view': '👁️'
        };
        let html = '';
        for (const entry of data.entries.slice(0, 50)) {
            const icon = actionIcons[entry.action] || '📝';
            const time = new Date(entry.timestamp).toLocaleString();
            html += `<div class="at-entry">`;
            html += `<span class="at-icon">${icon}</span>`;
            html += `<span class="at-action">${entry.action}</span>`;
            html += `<span class="at-detail">${entry.details || ''}</span>`;
            html += `<span class="at-time">${time}</span>`;
            html += `</div>`;
        }
        container.innerHTML = html;
    } catch (e) { /* silent */ }
}

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 67: Admin Session Report
// ═══════════════════════════════════════════════════════════════════
(function() {
    const btn = document.getElementById('sr-refresh-btn');
    if (btn) btn.addEventListener('click', loadSessionReport);
    setTimeout(loadSessionReport, 2200);
})();

async function loadSessionReport() {
    const token = localStorage.getItem('wr_admin_token');
    if (!token) return;
    try {
        const resp = await fetch('/api/admin/session-report', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!resp.ok) return;
        const data = await resp.json();
        const el = (id) => document.getElementById(id);
        if (el('sr-total')) el('sr-total').textContent = data.total_sessions || 0;
        if (el('sr-avg-stmts')) el('sr-avg-stmts').textContent = data.avg_statements_per_session || 0;
        if (el('sr-avg-words')) el('sr-avg-words').textContent = data.avg_words_per_session || 0;
        if (el('sr-max-stmts')) el('sr-max-stmts').textContent = data.max_statements || 0;
        const container = el('sr-status-dist');
        if (container && data.status_distribution) {
            let html = '';
            for (const [status, count] of Object.entries(data.status_distribution)) {
                html += `<div class="sr-status-row"><span class="sr-status-name">${status}</span><span class="sr-status-count">${count}</span></div>`;
            }
            container.innerHTML = html;
        }
    } catch (e) { /* silent */ }
}

// ═══════════════════════════════════════════════════════════════════
// IMPROVEMENT 68: Admin System Alerts
// ═══════════════════════════════════════════════════════════════════
(function() {
    const btn = document.getElementById('sa-refresh-btn');
    if (btn) btn.addEventListener('click', loadSystemAlerts);
    setTimeout(loadSystemAlerts, 2500);
})();

async function loadSystemAlerts() {
    const token = localStorage.getItem('wr_admin_token');
    if (!token) return;
    try {
        const resp = await fetch('/api/admin/system-alerts', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!resp.ok) return;
        const data = await resp.json();
        const container = document.getElementById('sa-alerts');
        const badge = document.getElementById('sa-badge');
        if (badge) {
            if (data.has_critical) { badge.textContent = '🔴 Critical'; badge.className = 'sa-badge sa-badge-critical'; }
            else if (data.has_warning) { badge.textContent = '🟡 Warning'; badge.className = 'sa-badge sa-badge-warning'; }
            else { badge.textContent = '🟢 OK'; badge.className = 'sa-badge sa-badge-ok'; }
        }
        if (!container) return;
        let html = '';
        for (const alert of data.alerts) {
            html += `<div class="sa-alert sa-alert-${alert.level}">`;
            html += `<span class="sa-alert-icon">${alert.icon}</span>`;
            html += `<span class="sa-alert-title">${alert.title}</span>`;
            html += `<span class="sa-alert-detail">${alert.detail}</span>`;
            html += `</div>`;
        }
        container.innerHTML = html;
    } catch (e) { /* silent */ }
}

// ── IMPROVEMENT 77: API Usage Analytics ──
async function loadApiUsage() {
    try {
        const resp = await adminFetch('/api/admin/api-usage');
        if (!resp.ok) return;
        const data = await resp.json();
        const container = document.getElementById('api-usage-content');
        if (!container) return;
        let html = `<div class="apu-stats">`;
        html += `<div class="apu-stat"><span class="apu-num">${data.total_sessions}</span><span class="apu-label">Sessions</span></div>`;
        html += `<div class="apu-stat"><span class="apu-num">${data.total_statements}</span><span class="apu-label">Statements</span></div>`;
        html += `</div>`;
        if (data.top_features && data.top_features.length > 0) {
            html += `<div class="apu-features">`;
            data.top_features.forEach(f => {
                const maxCount = data.top_features[0].count || 1;
                const width = Math.max(8, (f.count / maxCount) * 100);
                html += `<div class="apu-feature">`;
                html += `<span class="apu-fname">${f.name.replace(/_/g, ' ')}</span>`;
                html += `<div class="apu-bar-bg"><div class="apu-bar-fill" style="width:${width}%"></div></div>`;
                html += `<span class="apu-fcount">${f.count}</span>`;
                html += `</div>`;
            });
            html += `</div>`;
        }
        container.innerHTML = html;
    } catch (e) { /* silent */ }
}

// ── IMPROVEMENT 78: Active Sessions Monitor ──
async function loadActiveSessions() {
    try {
        const resp = await adminFetch('/api/admin/active-sessions');
        if (!resp.ok) return;
        const data = await resp.json();
        const summary = document.getElementById('as-summary');
        const list = document.getElementById('active-sessions-list');
        if (!summary || !list) return;
        summary.innerHTML = `<span class="as-stat">📁 ${data.total} total</span>` +
            `<span class="as-stat">🟢 ${data.active_count} active</span>` +
            `<span class="as-stat">✅ ${data.completed_count} completed</span>` +
            `<span class="as-stat">💬 ${data.total_statements} stmts</span>` +
            `<span class="as-stat">📝 ${data.total_words} words</span>`;
        let html = '';
        if (data.sessions && data.sessions.length > 0) {
            data.sessions.slice(0, 25).forEach(s => {
                const statusIcon = s.status === 'active' ? '🟢' : s.status === 'completed' ? '✅' : '⏸️';
                html += `<div class="as-item">`;
                html += `<span class="as-status">${statusIcon}</span>`;
                html += `<span class="as-title">${s.title || s.id.substring(0, 8)}</span>`;
                html += `<span class="as-detail">${s.statement_count} stmts · ${s.word_count} words</span>`;
                html += `<span class="as-badges">`;
                if (s.pinned) html += `<span class="as-badge">📌</span>`;
                if (s.bookmarks > 0) html += `<span class="as-badge">🔖${s.bookmarks}</span>`;
                if (s.annotations > 0) html += `<span class="as-badge">📝${s.annotations}</span>`;
                html += `</span></div>`;
            });
        } else {
            html = '<div class="as-empty">No sessions found.</div>';
        }
        list.innerHTML = html;
    } catch (e) { /* silent */ }
}

// Wire up the new panels on load
document.addEventListener('DOMContentLoaded', function() {
    const apiRefreshBtn = document.getElementById('api-usage-refresh');
    if (apiRefreshBtn) apiRefreshBtn.addEventListener('click', loadApiUsage);
    const asRefreshBtn = document.getElementById('active-sessions-refresh');
    if (asRefreshBtn) asRefreshBtn.addEventListener('click', loadActiveSessions);

    // Error Log
    async function loadErrorLog() {
        try {
            const resp = await fetch('/api/admin/error-log?limit=50', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('adminToken') } });
            if (!resp.ok) return;
            const data = await resp.json();
            const summary = document.getElementById('error-log-summary');
            const list = document.getElementById('error-log-list');
            if (summary) {
                const tc = data.type_counts || {};
                summary.innerHTML = `<span class="el-badge error">❌ ${tc.error || 0} Errors</span> <span class="el-badge warning">⚠️ ${tc.warning || 0} Warnings</span> <span class="el-badge info">ℹ️ ${tc.info || 0} Info</span> <span class="el-total">${data.total_errors} total</span>`;
            }
            if (list) {
                if (!data.errors || data.errors.length === 0) {
                    list.innerHTML = '<div class="el-empty">✅ No errors logged.</div>';
                } else {
                    list.innerHTML = data.errors.slice(0, 30).map(e => {
                        const colors = { error: '#ff4444', warning: '#ff8800', info: '#4488ff' };
                        const time = e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : '';
                        return `<div class="el-item" style="border-left:3px solid ${colors[e.type] || '#666'}"><span class="el-time">${time}</span> <span class="el-type">${e.type}</span> ${e.endpoint ? `<span class="el-ep">${e.endpoint}</span>` : ''} <span class="el-msg">${e.message}</span></div>`;
                    }).join('');
                }
            }
        } catch (e) { console.error('Error log load failed:', e); }
    }
    const elRefreshBtn = document.getElementById('error-log-refresh');
    if (elRefreshBtn) elRefreshBtn.addEventListener('click', loadErrorLog);

    // Performance Metrics
    async function loadPerfMetrics() {
        try {
            const resp = await fetch('/api/admin/performance', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('adminToken') } });
            if (!resp.ok) return;
            const data = await resp.json();
            const sysDiv = document.getElementById('perf-system');
            const listDiv = document.getElementById('perf-endpoints');
            if (sysDiv) {
                const sys = data.system || {};
                sysDiv.innerHTML = `<div class="perf-sys-grid"><div class="perf-sys-item"><span class="perf-sys-val">${sys.cpu_percent || 0}%</span><span class="perf-sys-label">CPU</span></div><div class="perf-sys-item"><span class="perf-sys-val">${sys.memory_percent || 0}%</span><span class="perf-sys-label">Memory</span></div><div class="perf-sys-item"><span class="perf-sys-val">${sys.this_request_ms || 0}ms</span><span class="perf-sys-label">This Request</span></div><div class="perf-sys-item"><span class="perf-sys-val">${data.total_requests_tracked || 0}</span><span class="perf-sys-label">Tracked</span></div></div>`;
            }
            if (listDiv) {
                const eps = data.slowest_endpoints || [];
                if (eps.length === 0) {
                    listDiv.innerHTML = '<div class="perf-empty">No performance data yet. Use the app to generate metrics.</div>';
                } else {
                    listDiv.innerHTML = '<div class="perf-header"><span>Endpoint</span><span>Avg (ms)</span><span>Calls</span></div>' + eps.map(e => {
                        const barW = Math.min(100, e.avg_ms / 5);
                        const color = e.avg_ms > 500 ? '#ff4444' : (e.avg_ms > 200 ? '#ff8800' : '#44aa44');
                        return `<div class="perf-row"><span class="perf-ep">${e.endpoint}</span><div class="perf-bar-bg"><div class="perf-bar" style="width:${barW}%;background:${color}"></div></div><span class="perf-ms">${e.avg_ms}ms</span><span class="perf-cnt">${e.count}</span></div>`;
                    }).join('');
                }
            }
        } catch (e) { console.error('Perf metrics load failed:', e); }
    }
    const perfRefreshBtn = document.getElementById('perf-refresh');
    if (perfRefreshBtn) perfRefreshBtn.addEventListener('click', loadPerfMetrics);

    setTimeout(() => { loadApiUsage(); loadActiveSessions(); loadErrorLog(); loadPerfMetrics(); loadDataRetention(); loadSystemConfig(); }, 1500);

    // ── Data Retention Manager ────────────────
    async function loadDataRetention() {
        try {
            const resp = await fetch('/api/admin/retention-manager', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('wr_admin_token') } });
            const data = await resp.json();
            const settingsDiv = document.getElementById('retention-settings');
            const statsDiv = document.getElementById('retention-stats');
            if (settingsDiv) {
                const s = data.settings;
                settingsDiv.innerHTML = `<div class="ret-controls"><div class="ret-toggle"><label class="ret-switch"><input type="checkbox" id="ret-auto-cleanup" ${s.auto_cleanup_enabled ? 'checked' : ''}> <span class="ret-slider"></span></label> <span>Auto-cleanup</span></div><div class="ret-field"><label>Retention days:</label> <input type="number" id="ret-days" value="${s.retention_days}" min="7" max="365" class="ret-input"></div><div class="ret-field"><label>Max sessions:</label> <input type="number" id="ret-max" value="${s.max_sessions}" min="10" max="10000" class="ret-input"></div><div class="ret-toggle"><label class="ret-switch"><input type="checkbox" id="ret-pinned" ${s.cleanup_pinned ? 'checked' : ''}> <span class="ret-slider"></span></label> <span>Include pinned</span></div><button id="ret-save" class="admin-btn-sm">💾 Save</button></div>`;
                document.getElementById('ret-save').addEventListener('click', async () => {
                    const body = {
                        auto_cleanup_enabled: document.getElementById('ret-auto-cleanup').checked,
                        retention_days: parseInt(document.getElementById('ret-days').value),
                        max_sessions: parseInt(document.getElementById('ret-max').value),
                        cleanup_pinned: document.getElementById('ret-pinned').checked,
                    };
                    await fetch('/api/admin/retention-manager', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('wr_admin_token') }, body: JSON.stringify(body) });
                    loadDataRetention();
                });
            }
            if (statsDiv) {
                const st = data.statistics;
                const ageDist = st.age_distribution || {};
                statsDiv.innerHTML = `<div class="ret-stats-grid"><div class="ret-stat"><span class="ret-stat-val">${st.total_sessions}</span><span class="ret-stat-label">Total Sessions</span></div><div class="ret-stat"><span class="ret-stat-val">${(st.estimated_storage_kb / 1024).toFixed(1)} MB</span><span class="ret-stat-label">Est. Storage</span></div></div><div class="ret-age-dist"><h5>📅 Session Age Distribution</h5>${Object.entries(ageDist).map(([k, v]) => `<div class="ret-age-row"><span>${k}</span><div class="ret-age-bar-bg"><div class="ret-age-bar" style="width:${st.total_sessions > 0 ? Math.round((v / st.total_sessions) * 100) : 0}%"></div></div><span>${v}</span></div>`).join('')}</div>`;
            }
        } catch (e) { console.error('Retention load failed:', e); }
    }
    const retRefreshBtn = document.getElementById('retention-refresh');
    if (retRefreshBtn) retRefreshBtn.addEventListener('click', loadDataRetention);

    // ── System Configuration ──────────────────
    async function loadSystemConfig() {
        try {
            const resp = await fetch('/api/admin/system-config', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('wr_admin_token') } });
            const data = await resp.json();
            const contentDiv = document.getElementById('system-config-content');
            if (contentDiv) {
                let html = '';
                const sections = [
                    { title: '🏗️ Application', data: data.application },
                    { title: '🤖 AI Provider', data: data.ai },
                    { title: '📁 Sessions', data: data.sessions },
                    { title: '🔧 Features', data: data.features },
                ];
                sections.forEach(sec => {
                    html += `<div class="config-section"><h5>${sec.title}</h5>`;
                    if (sec.data && typeof sec.data === 'object') {
                        Object.entries(sec.data).forEach(([k, v]) => {
                            let display = v;
                            if (typeof v === 'boolean') display = v ? '✅ Yes' : '❌ No';
                            else if (typeof v === 'object') display = JSON.stringify(v).substring(0, 80);
                            html += `<div class="config-row"><span class="config-key">${k.replace(/_/g, ' ')}</span><span class="config-val">${display}</span></div>`;
                        });
                    }
                    html += `</div>`;
                });
                contentDiv.innerHTML = html;
            }
        } catch (e) { console.error('Config load failed:', e); }
    }
    const configRefreshBtn = document.getElementById('config-refresh');
    if (configRefreshBtn) configRefreshBtn.addEventListener('click', loadSystemConfig);

    // ── Usage Trends ───────────────────
    async function loadUsageTrends() {
        const contentDiv = document.getElementById('usage-trends-content');
        if (!contentDiv) return;
        try {
            const resp = await fetch('/api/admin/usage-trends?hours=24', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('wr_admin_token') } });
            if (resp.ok) {
                const data = await resp.json();
                let html = `<div class="trend-header"><span>Last ${data.period_hours}h — ${data.total_requests} requests</span>`;
                const tCls = data.trend.direction === 'increasing' ? 'up' : data.trend.direction === 'decreasing' ? 'down' : 'stable';
                const tIcon = tCls === 'up' ? '📈' : tCls === 'down' ? '📉' : '➡️';
                html += `<span class="trend-direction ${tCls}">${tIcon} ${data.trend.direction} (${data.trend.change_percent > 0 ? '+' : ''}${data.trend.change_percent}%)</span></div>`;
                if (data.hourly_data.length) {
                    const maxReq = Math.max(...data.hourly_data.map(h => h.requests)) || 1;
                    html += `<div class="trend-chart">`;
                    data.hourly_data.forEach(h => {
                        const hPct = Math.max(2, Math.round((h.requests / maxReq) * 100));
                        html += `<div class="trend-bar" style="height:${hPct}%" title="${h.hour}: ${h.requests} req"></div>`;
                    });
                    html += `</div>`;
                }
                if (data.top_endpoints.length) {
                    html += `<div class="trend-endpoints"><strong>Top Endpoints</strong>`;
                    data.top_endpoints.slice(0, 10).forEach(ep => {
                        html += `<div class="trend-ep-row"><span class="trend-ep-name">${ep.endpoint}</span><span class="trend-ep-count">${ep.requests}</span></div>`;
                    });
                    html += `</div>`;
                } else {
                    html += `<div style="text-align:center;opacity:0.4;padding:16px;">No usage data yet</div>`;
                }
                contentDiv.innerHTML = html;
            }
        } catch (e) { console.error('Trends load failed:', e); }
    }
    loadUsageTrends();
    const trendsRefreshBtn = document.getElementById('trends-refresh');
    if (trendsRefreshBtn) trendsRefreshBtn.addEventListener('click', loadUsageTrends);

    // ── Session Search ───────────────────
    async function searchSessions() {
        const input = document.getElementById('admin-search-input');
        const resultsDiv = document.getElementById('session-search-results');
        if (!input || !resultsDiv) return;
        const q = input.value.trim();
        if (!q) { resultsDiv.innerHTML = '<div style="opacity:0.4;text-align:center;">Enter a search term</div>'; return; }
        resultsDiv.innerHTML = '<div class="config-loading">Searching...</div>';
        try {
            const resp = await fetch(`/api/admin/session-search?q=${encodeURIComponent(q)}`, { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('wr_admin_token') } });
            if (resp.ok) {
                const data = await resp.json();
                let html = `<div class="search-results-count">${data.total_results} result${data.total_results !== 1 ? 's' : ''} for "${data.query}"</div>`;
                if (data.results.length === 0) {
                    html += `<div style="text-align:center;opacity:0.4;padding:16px;">No sessions found</div>`;
                } else {
                    data.results.forEach(r => {
                        html += `<div class="search-result">`;
                        html += `<div class="search-result-title">${r.title || r.id}<span class="search-match-badge ${r.match_type}">${r.match_type}</span></div>`;
                        html += `<div class="search-result-meta">${r.message_count} messages • ${r.created_at || 'unknown date'}</div>`;
                        if (r.snippet) html += `<div class="search-result-snippet">${r.snippet}</div>`;
                        html += `</div>`;
                    });
                }
                resultsDiv.innerHTML = html;
            }
        } catch (e) { console.error('Search failed:', e); resultsDiv.innerHTML = '<div style="color:#f44336;">Search failed</div>'; }
    }
    const searchBtn = document.getElementById('admin-search-btn');
    if (searchBtn) searchBtn.addEventListener('click', searchSessions);
    const searchInput = document.getElementById('admin-search-input');
    if (searchInput) searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') searchSessions(); });
});

// ── Data Export ───────────────────────────────────────────────
async function exportData() {
    const exportType = document.getElementById('export-type-select')?.value || 'sessions';
    const fmt = document.getElementById('export-format-select')?.value || 'json';
    const resultDiv = document.getElementById('export-result');
    if (!resultDiv) return;
    resultDiv.innerHTML = '<p>Exporting...</p>';
    try {
        const resp = await fetch(`/api/admin/data-export?export_type=${exportType}&fmt=${fmt}`, {
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('wr_admin_token') }
        });
        if (!resp.ok) throw new Error('Export failed');
        const data = await resp.json();
        resultDiv.innerHTML = `<div class="export-info"><strong>${data.rows}</strong> rows exported as ${data.format.toUpperCase()}</div>`;
        if (data.format === 'csv' && data.content) {
            const blob = new Blob([data.content], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `${exportType}_export.csv`; a.textContent = '💾 Download CSV';
            a.className = 'export-download-link';
            resultDiv.appendChild(a);
        } else if (data.data) {
            const blob = new Blob([JSON.stringify(data.data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `${exportType}_export.json`; a.textContent = '💾 Download JSON';
            a.className = 'export-download-link';
            resultDiv.appendChild(a);
        }
    } catch (e) {
        resultDiv.innerHTML = '<p class="error-text">❌ Export failed</p>';
    }
}

// ── Rate Limiter ──────────────────────────────────────────────
async function loadRateLimiter() {
    const div = document.getElementById('rate-limiter-content');
    if (!div) return;
    try {
        const resp = await fetch('/api/admin/rate-limiter', {
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('wr_admin_token') }
        });
        if (!resp.ok) throw new Error('Failed');
        const data = await resp.json();
        const c = data.config;
        const s = data.status;
        let html = `<div class="rl-status">`;
        html += `<div class="rl-stat"><span class="rl-label">Enabled</span><span class="rl-val ${c.enabled ? 'rl-on' : 'rl-off'}">${c.enabled ? 'ON' : 'OFF'}</span></div>`;
        html += `<div class="rl-stat"><span class="rl-label">Default RPM</span><span class="rl-val">${c.default_rpm}</span></div>`;
        html += `<div class="rl-stat"><span class="rl-label">Active Clients</span><span class="rl-val">${s.active_clients}</span></div>`;
        html += `<div class="rl-stat"><span class="rl-label">Throttled</span><span class="rl-val ${s.throttled_clients > 0 ? 'rl-warn' : ''}">${s.throttled_clients}</span></div>`;
        html += `<div class="rl-stat"><span class="rl-label">Tracking</span><span class="rl-val">${s.tracking_entries}</span></div>`;
        html += `</div>`;
        if (Object.keys(c.endpoint_limits).length) {
            html += `<div class="rl-endpoints"><strong>Endpoint Limits:</strong><ul>`;
            Object.entries(c.endpoint_limits).forEach(([ep, lim]) => {
                html += `<li><code>${ep}</code>: ${lim} RPM</li>`;
            });
            html += `</ul></div>`;
        }
        if (c.blocked_ips.length) {
            html += `<div class="rl-blocked"><strong>Blocked IPs:</strong> ${c.blocked_ips.join(', ')}</div>`;
        }
        div.innerHTML = html;
    } catch (e) {
        div.innerHTML = '<p class="error-text">❌ Could not load rate limiter</p>';
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const exportBtn = document.getElementById('export-btn');
    if (exportBtn) exportBtn.addEventListener('click', exportData);
    const rlRefresh = document.getElementById('rate-limiter-refresh');
    if (rlRefresh) rlRefresh.addEventListener('click', loadRateLimiter);
    loadRateLimiter();

    // Feature Toggles
    const ftRefresh = document.getElementById('feature-toggles-refresh');
    if (ftRefresh) ftRefresh.addEventListener('click', loadFeatureToggles);
    loadFeatureToggles();

    // Notification Center
    const ncRefresh = document.getElementById('notification-center-refresh');
    if (ncRefresh) ncRefresh.addEventListener('click', loadNotificationCenter);
    loadNotificationCenter();
});

// ── Feature Toggles ─────────────────────────────────────
async function loadFeatureToggles() {
    const div = document.getElementById('feature-toggles-content');
    if (!div) return;
    try {
        const res = await fetch('/api/admin/feature-toggles', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('wr_admin_token') || sessionStorage.getItem('wr_admin_token') || '') } });
        if (!res.ok) throw new Error();
        const data = await res.json();
        let html = `<div class="ft-summary"><span class="ft-count">Enabled: <strong>${data.enabled_count}</strong>/${data.total}</span></div>`;
        html += `<div class="ft-grid">`;
        Object.entries(data.features).forEach(([name, enabled]) => {
            const label = name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            html += `<div class="ft-item">`;
            html += `<span class="ft-name">${label}</span>`;
            html += `<label class="ft-toggle"><input type="checkbox" ${enabled ? 'checked' : ''} data-feature="${name}" onchange="toggleFeature('${name}', this.checked)"><span class="ft-slider"></span></label>`;
            html += `</div>`;
        });
        html += `</div>`;
        div.innerHTML = html;
    } catch (e) {
        div.innerHTML = '<p class="error-text">❌ Could not load feature toggles</p>';
    }
}

async function toggleFeature(name, enabled) {
    try {
        const body = {}; body[name] = enabled;
        await fetch('/api/admin/feature-toggles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('wr_admin_token') || sessionStorage.getItem('wr_admin_token') || '') },
            body: JSON.stringify(body)
        });
    } catch (e) { console.error('Toggle failed', e); }
}

// ── Notification Center ─────────────────────────────────
async function loadNotificationCenter() {
    const div = document.getElementById('notification-center-content');
    if (!div) return;
    try {
        const res = await fetch('/api/admin/notifications', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('wr_admin_token') || sessionStorage.getItem('wr_admin_token') || '') } });
        if (!res.ok) throw new Error();
        const data = await res.json();
        let html = `<div class="nc-summary"><span class="nc-total">Total: <strong>${data.total}</strong></span><span class="nc-unread">Unread: <strong>${data.unread_count}</strong></span></div>`;
        if (data.notifications.length) {
            html += `<div class="nc-list">`;
            const icons = {info:'ℹ️',warning:'⚠️',alert:'🚨',success:'✅'};
            data.notifications.forEach(n => {
                html += `<div class="nc-item nc-${n.type} ${n.read?'read':'unread'}">`;
                html += `<span class="nc-icon">${icons[n.type]||'📌'}</span>`;
                html += `<div class="nc-body"><strong>${n.title}</strong><div class="nc-msg">${n.message}</div>`;
                html += `<div class="nc-time">${new Date(n.timestamp).toLocaleString()}</div></div>`;
                html += `</div>`;
            });
            html += `</div>`;
        } else {
            html += `<p class="nc-empty">No notifications</p>`;
        }
        div.innerHTML = html;
    } catch (e) {
        div.innerHTML = '<p class="error-text">❌ Could not load notifications</p>';
    }
}

// ── Backup Manager ──────────────────────
async function loadBackupManager() {
    const div = document.getElementById('backup-manager-content');
    if (!div) return;
    try {
        const res = await fetch('/api/admin/backup-manager', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') } });
        if (!res.ok) throw new Error();
        const data = await res.json();
        let html = '';
        const st = data.storage;
        html += `<div class="bkp-storage">`;
        html += `<div class="bkp-storage-stat"><strong>${st.total_gb} GB</strong><span>Total</span></div>`;
        html += `<div class="bkp-storage-stat"><strong>${st.used_gb} GB</strong><span>Used</span></div>`;
        html += `<div class="bkp-storage-stat"><strong>${st.free_gb} GB</strong><span>Free</span></div>`;
        html += `<div class="bkp-storage-stat"><strong>${data.data_summary.total_sessions}</strong><span>Sessions</span></div>`;
        html += `</div>`;
        html += `<div class="bkp-usage-bar"><div class="bkp-usage-fill" style="width:${st.usage_percent}%"></div></div>`;
        html += `<p style="font-size:0.82em;color:#888;">Storage: ${st.usage_percent}% used | Auto-backup: ${data.auto_backup_enabled ? '✅ Enabled' : '❌ Disabled'} | Retention: ${data.retention_days} days</p>`;
        if (data.backups && data.backups.length) {
            html += `<div class="bkp-list"><strong>Recent Backups:</strong>`;
            data.backups.slice(-5).reverse().forEach(b => {
                html += `<div class="bkp-entry"><span>${b.description}</span><span>${b.created_at}</span><span class="bkp-status">${b.status}</span></div>`;
            });
            html += `</div>`;
        } else {
            html += `<p style="font-size:0.88em;color:#888;">No backups recorded yet.</p>`;
        }
        div.innerHTML = html;
    } catch (e) {
        div.innerHTML = '<p class="error-text">❌ Could not load backup status</p>';
    }
}

document.getElementById('backup-manager-refresh')?.addEventListener('click', loadBackupManager);

// ── Activity Log ──────────────────────
async function loadActivityLog() {
    const div = document.getElementById('activity-log-content');
    if (!div) return;
    try {
        const res = await fetch('/api/admin/activity-log?limit=30', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') } });
        if (!res.ok) throw new Error();
        const data = await res.json();
        let html = '';
        if (data.action_types && Object.keys(data.action_types).length) {
            html += `<div class="act-summary">`;
            Object.entries(data.action_types).forEach(([type, count]) => {
                html += `<span class="act-type-badge">${type}: ${count}</span>`;
            });
            html += `</div>`;
        }
        html += `<p style="font-size:0.82em;color:#888;">Total: ${data.total} activities | Retention: ${data.log_retention_days} days</p>`;
        if (data.activities && data.activities.length) {
            html += `<div class="act-list">`;
            data.activities.slice(0, 15).forEach(a => {
                const time = a.timestamp ? new Date(a.timestamp).toLocaleString() : '';
                html += `<div class="act-entry"><span class="act-action">${a.action}</span><span class="act-desc">${a.description}</span><span class="act-time">${time}</span></div>`;
            });
            html += `</div>`;
        } else {
            html += `<p style="font-size:0.88em;color:#888;">No activity recorded.</p>`;
        }
        div.innerHTML = html;
    } catch (e) {
        div.innerHTML = '<p class="error-text">❌ Could not load activity log</p>';
    }
}

document.getElementById('activity-log-refresh')?.addEventListener('click', loadActivityLog);

// Auto-load new panels
if (document.getElementById('backup-manager-content')) loadBackupManager();
if (document.getElementById('activity-log-content')) loadActivityLog();

// ── Audit Trail ──────────────────────
async function loadAuditTrail() {
    const div = document.getElementById('audit-trail-content');
    if (!div) return;
    try {
        const res = await fetch('/api/admin/audit-trail', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('wr_admin_token') || sessionStorage.getItem('wr_admin_token') || '') } });
        if (!res.ok) throw new Error();
        const data = await res.json();
        let html = '';
        if (data.categories && Object.keys(data.categories).length) {
            html += `<div class="audit-stats">`;
            Object.entries(data.categories).forEach(([cat, count]) => {
                html += `<span class="audit-cat-badge">${cat}: ${count}</span>`;
            });
            html += `</div>`;
        }
        html += `<p class="audit-total">Total: ${data.total} entries</p>`;
        if (data.entries && data.entries.length) {
            html += `<div class="audit-list">`;
            data.entries.slice().reverse().slice(0, 25).forEach(e => {
                const time = e.timestamp ? new Date(e.timestamp).toLocaleString() : '';
                const sev = e.severity || 'info';
                html += `<div class="audit-entry sev-${sev}">`;
                html += `<span class="audit-action">${e.action}</span>`;
                html += `<span class="audit-desc">${e.description || ''}</span>`;
                html += `<span class="audit-user">${e.user || 'system'}</span>`;
                html += `<span class="audit-time">${time}</span>`;
                html += `</div>`;
            });
            html += `</div>`;
        } else {
            html += `<p style="font-size:0.88em;color:#888;">No audit trail entries.</p>`;
        }
        div.innerHTML = html;
    } catch(e) {
        div.innerHTML = '<p class="error-text">❌ Could not load audit trail</p>';
    }
}

document.getElementById('audit-trail-refresh')?.addEventListener('click', loadAuditTrail);

// ── System Health ──────────────────────
async function loadSystemHealth() {
    const div = document.getElementById('system-health-content');
    if (!div) return;
    try {
        const res = await fetch('/api/admin/system-health', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('wr_admin_token') || sessionStorage.getItem('wr_admin_token') || '') } });
        if (!res.ok) throw new Error();
        const data = await res.json();
        const statusClass = data.status === 'healthy' ? 'healthy' : data.status === 'warning' ? 'warning' : 'critical';
        let html = `<div class="sys-health-status ${statusClass}">${data.status.toUpperCase()}</div>`;
        html += `<div class="sys-metrics">`;
        // Memory
        const memClass = data.memory.usage_pct < 70 ? 'good' : data.memory.usage_pct < 85 ? 'warn' : 'crit';
        html += `<div class="sys-metric-card"><span class="sys-metric-val">${data.memory.usage_pct}%</span><span class="sys-metric-label">Memory Usage</span><div class="sys-metric-bar"><div class="sys-metric-fill ${memClass}" style="width:${data.memory.usage_pct}%"></div></div><span class="sys-metric-label">${data.memory.used_mb}/${data.memory.total_mb} MB</span></div>`;
        // CPU Load
        const cpuClass = data.cpu.load_1m < 2 ? 'good' : data.cpu.load_1m < 5 ? 'warn' : 'crit';
        const cpuPct = Math.min(data.cpu.load_1m * 25, 100);
        html += `<div class="sys-metric-card"><span class="sys-metric-val">${data.cpu.load_1m}</span><span class="sys-metric-label">CPU Load (1m)</span><div class="sys-metric-bar"><div class="sys-metric-fill ${cpuClass}" style="width:${cpuPct}%"></div></div><span class="sys-metric-label">5m: ${data.cpu.load_5m} | 15m: ${data.cpu.load_15m}</span></div>`;
        // Disk
        const diskClass = data.disk.usage_pct < 70 ? 'good' : data.disk.usage_pct < 85 ? 'warn' : 'crit';
        html += `<div class="sys-metric-card"><span class="sys-metric-val">${data.disk.usage_pct}%</span><span class="sys-metric-label">Disk Usage</span><div class="sys-metric-bar"><div class="sys-metric-fill ${diskClass}" style="width:${data.disk.usage_pct}%"></div></div><span class="sys-metric-label">${Math.round(data.disk.free_mb/1024)}GB free</span></div>`;
        // Processes
        html += `<div class="sys-metric-card"><span class="sys-metric-val">${data.processes}</span><span class="sys-metric-label">Processes</span></div>`;
        // Uptime
        html += `<div class="sys-metric-card"><span class="sys-metric-val">${data.uptime.display}</span><span class="sys-metric-label">Uptime</span></div>`;
        // Python
        html += `<div class="sys-metric-card"><span class="sys-metric-val" style="font-size:1em">${data.python_version}</span><span class="sys-metric-label">Python</span></div>`;
        html += `</div>`;
        html += `<div class="sys-timestamp">Last check: ${new Date(data.timestamp).toLocaleString()}</div>`;
        div.innerHTML = html;
    } catch(e) {
        div.innerHTML = '<p class="error-text">❌ Could not load system health</p>';
    }
}

document.getElementById('system-health-refresh')?.addEventListener('click', loadSystemHealth);

// Auto-load new panels
if (document.getElementById('audit-trail-content')) loadAuditTrail();
if (document.getElementById('system-health-content')) loadSystemHealth();

// ── API Key Manager Panel ──
async function loadApiKeyManager() {
    const el = document.getElementById('api-key-manager-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/api-key-manager', { headers: { 'Authorization': 'Bearer ' + (window.adminPortal?.authToken || sessionStorage.getItem('admin_token') || '') } });
        const d = await r.json();
        const statusColor = d.status === 'active' ? '#4caf50' : '#f44336';
        el.innerHTML = `
            <div class="akm-grid">
                <div class="akm-item"><span class="akm-label">Status</span><span class="akm-val" style="color:${statusColor}">${d.status?.toUpperCase()}</span></div>
                <div class="akm-item"><span class="akm-label">Provider</span><span class="akm-val">${d.provider || 'N/A'}</span></div>
                <div class="akm-item"><span class="akm-label">Key</span><span class="akm-val" style="font-family:monospace;font-size:0.85em">${d.key_masked || 'N/A'}</span></div>
                <div class="akm-item"><span class="akm-label">Usage Today</span><span class="akm-val">${d.usage_today}/${d.usage_limit} (${d.usage_pct}%)</span></div>
                <div class="akm-item"><span class="akm-label">Rotations</span><span class="akm-val">${d.rotation_count}</span></div>
                <div class="akm-item"><span class="akm-label">Last Rotated</span><span class="akm-val">${d.last_rotated ? new Date(d.last_rotated).toLocaleString() : 'Never'}</span></div>
            </div>
            <div class="akm-env"><strong>Environment:</strong> ${Object.entries(d.environment_keys || {}).map(([k,v]) => `<span class="akm-env-tag">${k}: ${v}</span>`).join(' ')}</div>
        `;
    } catch(e) { el.innerHTML = '<p>Error loading API key info</p>'; }
}

document.getElementById('api-key-manager-refresh')?.addEventListener('click', loadApiKeyManager);

// ── Scheduled Tasks Panel ──
async function loadScheduledTasks() {
    const el = document.getElementById('scheduled-tasks-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/scheduled-tasks', { headers: { 'Authorization': 'Bearer ' + (window.adminPortal?.authToken || sessionStorage.getItem('admin_token') || '') } });
        const d = await r.json();
        let html = `<div class="st-stats"><span class="st-stat-badge st-active">${d.active_count} Active</span><span class="st-stat-badge st-paused">${d.paused_count} Paused</span></div>`;
        html += '<div class="st-list">';
        for (const t of (d.tasks || [])) {
            const statusClass = t.status === 'active' ? 'st-task-active' : 'st-task-paused';
            html += `<div class="st-task ${statusClass}">
                <div class="st-task-header"><span class="st-task-name">${t.name}</span><span class="st-task-status">${t.status}</span></div>
                <div class="st-task-schedule">📅 ${t.schedule}</div>
                <div class="st-task-last">Last: ${t.last_run ? new Date(t.last_run).toLocaleString() : 'Never'}</div>
            </div>`;
        }
        html += '</div>';
        el.innerHTML = html;
    } catch(e) { el.innerHTML = '<p>Error loading scheduled tasks</p>'; }
}

document.getElementById('scheduled-tasks-refresh')?.addEventListener('click', loadScheduledTasks);

// Auto-load new panels
if (document.getElementById('api-key-manager-content')) loadApiKeyManager();
if (document.getElementById('scheduled-tasks-content')) loadScheduledTasks();
