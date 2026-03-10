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
        this.fetchTimeout = 30000;
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
        document.getElementById('fix-reports-btn')?.addEventListener('click', () => this.fixOrphanReports());
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
    
    async fetchWithTimeout(url, options = {}, customTimeout = null) {
        const controller = new AbortController();
        const timeoutMs = customTimeout || this.fetchTimeout;
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
        
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
                ${caseData.scene_image_url ? `
                <div class="case-thumbnail">
                    <img src="${caseData.scene_image_url}" alt="Scene" loading="lazy" onerror="this.parentElement.innerHTML='<div class=\\'case-icon\\'>📁</div>'">
                </div>
                ` : '<div class="case-icon">📁</div>'}
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

            // Get AI-generated report image from image_url field or scene_versions
            const reportImageUrl = report.image_url || (scenes.length > 0 ? scenes[scenes.length - 1].image_url : null);
            
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
                            ${reportImageUrl ? '<span class="has-image-badge" title="Has AI scene image">🎬</span>' : ''}
                            <span class="expand-icon">▶</span>
                        </div>
                    </div>
                    <div class="report-detail-body">
                        ${reportImageUrl ? `
                        <div class="report-scene-image-section">
                            <h4>🤖 AI Scene Reconstruction</h4>
                            <div class="report-scene-image-container">
                                <img src="${reportImageUrl}" alt="AI scene reconstruction for ${report.title || 'report'}" 
                                     class="report-scene-image" loading="lazy"
                                     onerror="this.parentElement.style.display='none'">
                            </div>
                        </div>
                        ` : `
                        <div class="report-scene-image-section no-image">
                            <div class="no-image-placeholder">
                                <span class="no-image-icon">🎬</span>
                                <p>No AI scene image generated yet</p>
                                <button class="btn-small btn-generate-scene" onclick="window.adminPortal?.generateReportScene('${report.id}')">
                                    Generate Scene Image
                                </button>
                            </div>
                        </div>
                        `}
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
            const btn = document.getElementById('seed-data-btn');
            if (btn) { btn.disabled = true; btn.querySelector('strong').textContent = '⏳ Seeding...'; }
            this.showToast('Seeding demo data (this takes ~2 minutes)...', 'info');
            const response = await this.fetchWithTimeout('/api/admin/seed-mock-data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            }, 300000);
            
            if (!response.ok) throw new Error('Seed failed');
            
            const data = await response.json();
            this.showToast(data.message || 'Demo data seeded successfully!', 'success');
            await this.loadCases();
        } catch (error) {
            console.error('Error seeding data:', error);
            this.showToast('Failed to seed demo data: ' + error.message, 'error');
        } finally {
            const btn = document.getElementById('seed-data-btn');
            if (btn) { btn.disabled = false; const s = btn.querySelector('strong'); if (s) s.textContent = 'Seed Demo Data'; }
        }
    }

    async fixOrphanReports() {
        try {
            const btn = document.getElementById('fix-reports-btn');
            if (btn) { btn.disabled = true; btn.textContent = '⏳ Processing...'; }
            
            this.showToast('Fixing reports: assigning cases, generating images (takes ~2 min)...', 'info');
            const response = await this.fetchWithTimeout('/api/admin/fix-orphan-reports', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            }, 300000);
            
            if (!response.ok) throw new Error('Fix failed');
            
            const data = await response.json();
            this.showToast(data.message || 'Reports fixed!', 'success');
            await this.loadCases();
        } catch (error) {
            console.error('Error fixing reports:', error);
            this.showToast('Failed to fix reports: ' + error.message, 'error');
        } finally {
            const btn = document.getElementById('fix-reports-btn');
            if (btn) { btn.disabled = false; btn.textContent = '🔧 Fix Reports'; }
        }
    }

    async generateReportScene(reportId) {
        try {
            this.showToast('Generating AI scene image...', 'info');
            const response = await this.fetchWithTimeout(`/api/sessions/${reportId}/generate-scene`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            }, 120000);

            if (!response.ok) throw new Error('Scene generation failed');

            const data = await response.json();
            this.showToast('Scene image generation started! It will appear shortly.', 'success');

            // Refresh case detail after a short delay to show the new image
            setTimeout(async () => {
                if (this.currentCase) {
                    await this.showCaseDetail(this.currentCase.id);
                }
            }, 8000);
        } catch (error) {
            console.error('Error generating report scene:', error);
            this.showToast('Failed to generate scene: ' + error.message, 'error');
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
    if (btn) btn.addEventListener('click', loadAuditTrailCompact);
    setTimeout(loadAuditTrailCompact, 1800);
})();

async function loadAuditTrailCompact() {
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

// ── User Management Panel ──
async function loadUserManagement() {
    const el = document.getElementById('user-mgmt-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/user-management', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') } });
        const data = await r.json();
        let html = `<div class="um-stats">`;
        html += `<div class="um-stat"><span class="um-val">${data.total_sessions}</span><span class="um-label">Total Sessions</span></div>`;
        html += `<div class="um-stat"><span class="um-val">${data.storage_summary.total_size_kb} KB</span><span class="um-label">Storage Used</span></div>`;
        html += `<div class="um-stat"><span class="um-val">${data.storage_summary.total_files}</span><span class="um-label">Data Files</span></div>`;
        html += `</div>`;
        if (data.recent_sessions && data.recent_sessions.length > 0) {
            html += `<div class="um-sessions"><h4>Recent Sessions</h4><table class="um-table"><thead><tr><th>Session ID</th><th>Modified</th><th>Size</th></tr></thead><tbody>`;
            for (const s of data.recent_sessions.slice(0, 10)) {
                html += `<tr><td class="um-sid">${s.session_id.substring(0,12)}...</td><td>${new Date(s.modified).toLocaleString()}</td><td>${s.size_kb} KB</td></tr>`;
            }
            html += `</tbody></table></div>`;
        } else {
            html += `<p>No sessions found.</p>`;
        }
        el.innerHTML = html;
    } catch(e) { el.innerHTML = '<p class="error">Failed to load user management data.</p>'; }
}
document.getElementById('user-mgmt-refresh')?.addEventListener('click', loadUserManagement);
if (document.getElementById('user-mgmt-content')) loadUserManagement();

// ── Performance Metrics Panel ──
async function loadPerfMetricsPanel() {
    const el = document.getElementById('perf-metrics-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/performance-metrics', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') } });
        const data = await r.json();
        let html = `<div class="pm-stats">`;
        html += `<div class="pm-stat"><span class="pm-val">${data.requests_total}</span><span class="pm-label">Total Requests</span></div>`;
        html += `<div class="pm-stat"><span class="pm-val">${data.error_rate_pct}%</span><span class="pm-label">Error Rate</span></div>`;
        html += `<div class="pm-stat"><span class="pm-val">${data.response_times.avg_ms}ms</span><span class="pm-label">Avg Response</span></div>`;
        html += `<div class="pm-stat"><span class="pm-val">${data.uptime_hours}h</span><span class="pm-label">Uptime</span></div>`;
        html += `</div>`;
        html += `<div class="pm-detail">`;
        html += `<div class="pm-row"><span>Throughput</span><span>${data.throughput.requests_per_hour} req/h</span></div>`;
        html += `<div class="pm-row"><span>Max Response</span><span>${data.response_times.max_ms}ms</span></div>`;
        html += `<div class="pm-row"><span>Min Response</span><span>${data.response_times.min_ms}ms</span></div>`;
        html += `<div class="pm-row"><span>Errors</span><span>${data.errors_total}</span></div>`;
        html += `</div>`;
        if (data.top_endpoints && data.top_endpoints.length > 0) {
            html += `<div class="pm-endpoints"><h4>Top Endpoints</h4>`;
            for (const ep of data.top_endpoints.slice(0, 5)) {
                html += `<div class="pm-ep-row"><span class="pm-ep-name">${ep.endpoint}</span><span class="pm-ep-hits">${ep.hits}</span></div>`;
            }
            html += `</div>`;
        }
        el.innerHTML = html;
    } catch(e) { el.innerHTML = '<p class="error">Failed to load performance metrics.</p>'; }
}
async function resetPerfMetrics() {
    try {
        await fetch('/api/admin/performance-metrics', { method: 'POST', headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || ''), 'Content-Type': 'application/json' } });
        loadPerfMetricsPanel();
    } catch(e) { console.error('Failed to reset metrics'); }
}
document.getElementById('perf-metrics-refresh')?.addEventListener('click', loadPerfMetricsPanel);
document.getElementById('perf-metrics-reset')?.addEventListener('click', resetPerfMetrics);
if (document.getElementById('perf-metrics-content')) loadPerfMetricsPanel();

// ============================================================
// Admin: Environment Config Panel
// ============================================================
async function loadEnvConfig() {
    try {
        const r = await fetch('/api/admin/environment-config', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('admin_token') } });
        const data = await r.json();
        const el = document.getElementById('env-config-content');
        if (!el) return;
        let html = '<div class="env-config-grid">';
        html += '<div class="env-config-stat"><span class="env-config-val">' + data.total_configured + '</span><span class="env-config-label">Configured</span></div>';
        html += '<div class="env-config-stat"><span class="env-config-val">' + Object.keys(data.defaults).length + '</span><span class="env-config-label">Available</span></div>';
        html += '<div class="env-config-stat"><span class="env-config-val">' + Object.keys(data.overrides).length + '</span><span class="env-config-label">Overrides</span></div>';
        html += '</div>';
        html += '<table class="env-config-table"><tr><th>Key</th><th>Value</th><th>Default</th><th>Status</th></tr>';
        for (const [key, def] of Object.entries(data.defaults)) {
            const current = data.environment[key] || '';
            const isOverride = data.overrides[key] !== undefined;
            const status = isOverride ? '<span class="env-override">override</span>' : (current ? '<span class="env-active">active</span>' : '<span class="env-default">default</span>');
            html += '<tr><td><code>' + key + '</code></td><td>' + (current || '<em>' + def + '</em>') + '</td><td>' + def + '</td><td>' + status + '</td></tr>';
        }
        html += '</table>';
        el.innerHTML = html;
    } catch(e) { console.error('Env config load error:', e); }
}
document.getElementById('env-config-refresh')?.addEventListener('click', loadEnvConfig);
setTimeout(loadEnvConfig, 2200);

// ============================================================
// Admin: Session Analytics Dashboard
// ============================================================
async function loadSessionAnalytics() {
    try {
        const r = await fetch('/api/admin/session-analytics', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('admin_token') } });
        const data = await r.json();
        const el = document.getElementById('session-analytics-content');
        if (!el) return;
        let html = '<div class="sa-stats-grid">';
        html += '<div class="sa-stat"><span class="sa-stat-val">' + data.total_sessions + '</span><span class="sa-stat-label">Sessions</span></div>';
        html += '<div class="sa-stat"><span class="sa-stat-val">' + data.total_messages + '</span><span class="sa-stat-label">Messages</span></div>';
        html += '<div class="sa-stat"><span class="sa-stat-val">' + data.avg_messages_per_session + '</span><span class="sa-stat-label">Avg Msgs/Session</span></div>';
        html += '<div class="sa-stat"><span class="sa-stat-val">' + (data.storage.total_bytes / 1024).toFixed(1) + 'KB</span><span class="sa-stat-label">Total Storage</span></div>';
        html += '</div>';
        // Distribution bar
        const dist = data.sessions_distribution;
        const total = Math.max(data.total_sessions, 1);
        html += '<div class="sa-dist-section"><h4>Session Distribution</h4><div class="sa-dist-bar">';
        html += '<div class="sa-dist-seg sa-dist-empty" style="width:' + (dist.empty/total*100) + '%" title="Empty: ' + dist.empty + '"></div>';
        html += '<div class="sa-dist-seg sa-dist-short" style="width:' + (dist.short/total*100) + '%" title="Short: ' + dist.short + '"></div>';
        html += '<div class="sa-dist-seg sa-dist-medium" style="width:' + (dist.medium/total*100) + '%" title="Medium: ' + dist.medium + '"></div>';
        html += '<div class="sa-dist-seg sa-dist-long" style="width:' + (dist.long/total*100) + '%" title="Long: ' + dist.long + '"></div>';
        html += '</div><div class="sa-dist-legend">';
        html += '<span class="sa-legend sa-dist-empty">Empty: ' + dist.empty + '</span>';
        html += '<span class="sa-legend sa-dist-short">Short: ' + dist.short + '</span>';
        html += '<span class="sa-legend sa-dist-medium">Medium: ' + dist.medium + '</span>';
        html += '<span class="sa-legend sa-dist-long">Long: ' + dist.long + '</span>';
        html += '</div></div>';
        // Popular features
        if (data.popular_analysis_features.length) {
            html += '<div class="sa-features"><h4>Popular Analysis Features</h4>';
            for (const f of data.popular_analysis_features) {
                const name = f.endpoint.split('/').pop().replace(/-/g, ' ');
                html += '<div class="sa-feat-row"><span class="sa-feat-name">' + name + '</span><span class="sa-feat-hits">' + f.hits + ' hits</span></div>';
            }
            html += '</div>';
        }
        el.innerHTML = html;
    } catch(e) { console.error('Session analytics load error:', e); }
}
document.getElementById('session-analytics-refresh')?.addEventListener('click', loadSessionAnalytics);
setTimeout(loadSessionAnalytics, 2400);

// ============================================================
// Admin Feature: Content Moderation
// ============================================================
async function loadContentModeration() {
    try {
        const r = await fetch('/api/admin/content-moderation', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') } });
        const data = await r.json();
        const el = document.getElementById('content-moderation-content');
        if (!el) return;
        let html = '<div class="admin-metric-grid">';
        html += '<div class="admin-metric"><span class="admin-metric-val">' + data.totals.total_flags + '</span><span>Total Flags</span></div>';
        html += '<div class="admin-metric"><span class="admin-metric-val" style="color:#fbbf24">' + data.totals.pending + '</span><span>Pending</span></div>';
        html += '<div class="admin-metric"><span class="admin-metric-val" style="color:#34d399">' + data.totals.reviewed + '</span><span>Reviewed</span></div>';
        html += '<div class="admin-metric"><span class="admin-metric-val">' + data.totals.dismissed + '</span><span>Dismissed</span></div>';
        html += '</div>';
        html += '<h4 style="margin:12px 0 6px;color:#e2e8f0;">Moderation Rules</h4>';
        html += '<div style="font-size:0.85em;color:#9ca3af;">Max message length: <strong>' + data.rules.max_message_length + '</strong></div>';
        html += '<div style="font-size:0.85em;color:#9ca3af;">Auto-review threshold: <strong>' + data.rules.auto_review_threshold + '</strong></div>';
        html += '<div style="font-size:0.85em;color:#9ca3af;">Keywords: <strong>' + data.rules.auto_flag_keywords.join(', ') + '</strong></div>';
        if (data.recent_flags.length) {
            html += '<h4 style="margin:12px 0 6px;color:#e2e8f0;">Recent Flags</h4>';
            for (const f of data.recent_flags.slice(-5)) {
                html += '<div style="padding:3px 0;font-size:0.8em;color:#6b7280;">' + f.status + ' — ' + f.reason + ' — ' + (f.session_id || '').substring(0,8) + '...</div>';
            }
        }
        el.innerHTML = html;
    } catch(e) { console.error('Content moderation load error:', e); }
}
document.getElementById('content-moderation-refresh')?.addEventListener('click', loadContentModeration);
document.getElementById('content-moderation-clear')?.addEventListener('click', async function() {
    try {
        await fetch('/api/admin/content-moderation', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') }, body: JSON.stringify({ action: 'clear' }) });
        loadContentModeration();
    } catch(e) { console.error('Content moderation clear error:', e); }
});
setTimeout(loadContentModeration, 2600);

// ============================================================
// Admin Feature: Export Manager
// ============================================================
async function loadExportManager() {
    try {
        const r = await fetch('/api/admin/export-manager', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') } });
        const data = await r.json();
        const el = document.getElementById('export-manager-content');
        if (!el) return;
        let html = '<div class="admin-metric-grid">';
        html += '<div class="admin-metric"><span class="admin-metric-val">' + data.total_exports + '</span><span>Total Exports</span></div>';
        html += '<div class="admin-metric"><span class="admin-metric-val">' + data.today_exports + '</span><span>Today</span></div>';
        html += '<div class="admin-metric"><span class="admin-metric-val">' + data.available_formats.length + '</span><span>Formats</span></div>';
        html += '</div>';
        const fmts = data.format_distribution;
        if (Object.keys(fmts).length) {
            html += '<h4 style="margin:12px 0 6px;color:#e2e8f0;">Format Distribution</h4><ul style="list-style:none;padding:0;margin:0;">';
            for (const [fmt, count] of Object.entries(fmts)) {
                html += '<li style="padding:3px 0;font-size:0.85em;color:#9ca3af;">' + fmt.toUpperCase() + ' — <strong>' + count + '</strong></li>';
            }
            html += '</ul>';
        }
        if (data.recent_exports.length) {
            html += '<h4 style="margin:12px 0 6px;color:#e2e8f0;">Recent Exports</h4>';
            for (const ex of data.recent_exports.slice(-5)) {
                html += '<div style="padding:3px 0;font-size:0.8em;color:#6b7280;">' + (ex.format || 'json').toUpperCase() + ' — ' + ex.session_id.substring(0,8) + '... — ' + ex.timestamp + '</div>';
            }
        }
        html += '<div style="margin-top:10px;font-size:0.8em;color:#6b7280;">Available: ' + data.available_formats.join(', ').toUpperCase() + '</div>';
        el.innerHTML = html;
    } catch(e) { console.error('Export manager load error:', e); }
}
document.getElementById('export-manager-refresh')?.addEventListener('click', loadExportManager);
document.getElementById('export-manager-clear')?.addEventListener('click', async function() {
    try {
        await fetch('/api/admin/export-manager', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') }, body: JSON.stringify({ action: 'clear' }) });
        loadExportManager();
    } catch(e) { console.error('Export manager clear error:', e); }
});
setTimeout(loadExportManager, 2800);

// ============================================================
// Admin Feature: Backup Manager (Create button)
// ============================================================
document.getElementById('backup-manager-create')?.addEventListener('click', async function() {
    try {
        const token = localStorage.getItem('admin_token') || '';
        await fetch('/api/admin/backup-manager', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token }, body: JSON.stringify({ action: 'create', type: 'manual' }) });
        if (typeof loadBackupManager === 'function') loadBackupManager();
    } catch(e) { console.error('Backup create error:', e); }
});

// ============================================================
// Admin Feature: Rate Limit Dashboard
// ============================================================
async function loadRateLimitsPanel() {
    try {
        const token = localStorage.getItem('admin_token') || '';
        const res = await fetch('/api/admin/rate-limits', { headers: { 'Authorization': 'Bearer ' + token } });
        const data = await res.json();
        const el = document.getElementById('rate-limits-content');
        if (!el) return;
        let html = '';
        if (data.api_key_stats) {
            // Existing format
            const stats = data.api_key_stats;
            const keys = Object.keys(stats);
            html += '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:14px;">';
            html += '<div style="background:rgba(59,130,246,0.1);padding:10px;border-radius:8px;text-align:center;"><div style="font-size:1.4em;font-weight:700;color:#3b82f6;">' + keys.length + '</div><div style="font-size:0.75em;color:#94a3b8;">Tracked Keys</div></div>';
            const totalReqs = keys.reduce((s, k) => s + (stats[k].requests_last_minute || 0), 0);
            html += '<div style="background:rgba(34,197,94,0.1);padding:10px;border-radius:8px;text-align:center;"><div style="font-size:1.4em;font-weight:700;color:#22c55e;">' + totalReqs + '</div><div style="font-size:0.75em;color:#94a3b8;">Requests/min</div></div>';
            html += '</div>';
            if (keys.length) {
                html += '<h4 style="margin:8px 0 4px;color:#e2e8f0;font-size:0.9em;">API Key Activity</h4>';
                for (const k of keys) {
                    html += '<div style="font-size:0.8em;color:#94a3b8;padding:2px 0;">🔑 ' + k + ' — ' + stats[k].requests_last_minute + ' req/min · ' + stats[k].total_tracked + ' tracked</div>';
                }
            }
            html += '<div style="margin-top:8px;font-size:0.75em;color:#475569;">Updated: ' + (data.timestamp || 'now') + '</div>';
        } else {
            html += '<div style="font-size:0.85em;color:#94a3b8;">No rate limit data available</div>';
        }
        el.innerHTML = html;
    } catch(e) { console.error('Rate limits load error:', e); }
}
document.getElementById('rate-limits-refresh')?.addEventListener('click', loadRateLimitsPanel);
setTimeout(loadRateLimitsPanel, 3200);

// ── Database Stats Panel ────────────────────────────────
async function loadDbStatsPanel() {
    try {
        const r = await fetch('/api/admin/database-stats', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') } });
        const d = await r.json();
        const el = document.getElementById('db-stats-content');
        if (!el) return;
        let html = '<div class="db-stats-grid">';
        html += `<div class="db-stat-card"><span class="db-stat-val">${d.database.total_sessions}</span><span class="db-stat-lbl">Sessions</span></div>`;
        html += `<div class="db-stat-card"><span class="db-stat-val">${d.memory.session_store_entries}</span><span class="db-stat-lbl">Store Entries</span></div>`;
        html += `<div class="db-stat-card"><span class="db-stat-val">${d.memory.api_keys_count}</span><span class="db-stat-lbl">API Keys</span></div>`;
        html += `<div class="db-stat-card"><span class="db-stat-val">${d.storage.total_size_mb} MB</span><span class="db-stat-lbl">Storage Used</span></div>`;
        html += `<div class="db-stat-card"><span class="db-stat-val">${d.storage.total_files}</span><span class="db-stat-lbl">Data Files</span></div>`;
        html += `<div class="db-stat-card"><span class="db-stat-val">${d.memory.rate_limit_entries}</span><span class="db-stat-lbl">Rate Entries</span></div>`;
        html += '</div>';
        html += `<div class="db-stat-health"><span class="db-stat-badge db-stat-${d.health.status}">● ${d.health.status.toUpperCase()}</span></div>`;
        el.innerHTML = html;
    } catch(e) { console.error('DB stats load error:', e); }
}
document.getElementById('db-stats-refresh')?.addEventListener('click', loadDbStatsPanel);
setTimeout(loadDbStatsPanel, 3400);

// ── System Notifications Panel ──────────────────────────
async function loadSysNotifPanel() {
    try {
        const r = await fetch('/api/admin/system-notifications', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') } });
        const d = await r.json();
        const el = document.getElementById('sys-notif-content');
        if (!el) return;
        let html = '<div class="sys-notif-counts">';
        html += `<span class="sys-notif-sev sys-notif-critical">🔴 Critical: ${d.severity_counts.critical}</span>`;
        html += `<span class="sys-notif-sev sys-notif-warning">🟡 Warning: ${d.severity_counts.warning}</span>`;
        html += `<span class="sys-notif-sev sys-notif-info">🔵 Info: ${d.severity_counts.info}</span>`;
        html += `<span class="sys-notif-total">Total: ${d.total}</span></div>`;
        html += '<div class="sys-notif-list">';
        (d.notifications || []).slice(0, 10).forEach(n => {
            const sevIcon = n.severity === 'critical' ? '🔴' : n.severity === 'warning' ? '🟡' : '🔵';
            html += `<div class="sys-notif-item sys-notif-item-${n.severity}"><span class="sys-notif-icon">${sevIcon}</span>`;
            html += `<div class="sys-notif-body"><strong>${n.title}</strong><span class="sys-notif-msg">${n.message}</span></div>`;
            html += `<span class="sys-notif-time">${n.auto ? 'Auto' : 'Custom'}</span></div>`;
        });
        html += '</div>';
        el.innerHTML = html;
    } catch(e) { console.error('Sys notif load error:', e); }
}
document.getElementById('sys-notif-refresh')?.addEventListener('click', loadSysNotifPanel);
document.getElementById('sys-notif-add')?.addEventListener('click', async () => {
    const title = prompt('Notification title:');
    if (!title) return;
    const message = prompt('Message:') || '';
    const severity = prompt('Severity (info/warning/critical):', 'info') || 'info';
    try {
        await fetch('/api/admin/system-notifications', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('admin_token') || '') },
            body: JSON.stringify({ title, message, severity })
        });
        loadSysNotifPanel();
    } catch(e) { console.error('Add notification error:', e); }
});
setTimeout(loadSysNotifPanel, 3600);

// ── Audit Log Panel ─────────────────────────
async function loadAuditLogPanel() {
    try {
        const r = await fetch('/api/admin/audit-log', {headers:{'Authorization':'Bearer '+(sessionStorage.getItem('admin_token')||localStorage.getItem('admin_token')||'')}});
        if (!r.ok) return;
        const d = await r.json();
        const el = document.getElementById('audit-log-content');
        if (!el) return;
        const sevIcons = {info:'ℹ️',warning:'⚠️',error:'❌',critical:'🚨'};
        let html = `<div class="audit-summary"><span>ℹ️ Info: ${d.summary.info_count}</span><span>⚠️ Warn: ${d.summary.warning_count}</span><span>❌ Error: ${d.summary.error_count}</span><span>🚨 Critical: ${d.summary.critical_count}</span></div>`;
        html += '<div class="audit-events">';
        (d.events || []).slice(0, 15).forEach(e => {
            html += `<div class="audit-event audit-${e.severity}"><span class="audit-icon">${sevIcons[e.severity]||'📝'}</span><span class="audit-time">${new Date(e.timestamp).toLocaleTimeString()}</span><span class="audit-action">${e.action}</span><span class="audit-detail">${e.detail}</span></div>`;
        });
        html += '</div>';
        el.innerHTML = html;
    } catch(e) { console.error('Audit log error:', e); }
}
document.getElementById('audit-log-refresh')?.addEventListener('click', loadAuditLogPanel);
setTimeout(loadAuditLogPanel, 2400);

// ── Infrastructure Monitor Panel ────────────────
async function loadSysHealthPanel() {
    try {
        const r = await fetch('/api/admin/infrastructure-monitor', {headers:{'Authorization':'Bearer '+(sessionStorage.getItem('admin_token')||localStorage.getItem('admin_token')||'')}});
        if (!r.ok) return;
        const d = await r.json();
        const el = document.getElementById('sys-health-content');
        if (!el) return;
        const statusColors = {healthy:'#22c55e',degraded:'#eab308',critical:'#ef4444'};
        const sc = statusColors[d.status] || '#666';
        let html = `<div class="shealth-status" style="border-left:4px solid ${sc};padding:8px 12px;margin-bottom:10px;background:rgba(0,0,0,.2);border-radius:4px"><strong style="color:${sc}">${d.status.toUpperCase()}</strong> — Uptime: ${d.uptime.human}</div>`;
        if (d.warnings.length > 0) {
            html += `<div class="shealth-warnings">${d.warnings.map(w=>`<span class="shealth-warn">⚠️ ${w}</span>`).join('')}</div>`;
        }
        html += '<div class="shealth-grid">';
        html += `<div class="shealth-card"><div class="shealth-card-title">🖥️ CPU</div><div class="shealth-card-val">${d.cpu.usage_pct}%</div><div class="shealth-card-sub">${d.cpu.cores} cores</div></div>`;
        html += `<div class="shealth-card"><div class="shealth-card-title">🧠 Memory</div><div class="shealth-card-val">${d.memory.usage_pct}%</div><div class="shealth-card-sub">${d.memory.used_mb}/${d.memory.total_mb} MB</div></div>`;
        html += `<div class="shealth-card"><div class="shealth-card-title">💾 Disk</div><div class="shealth-card-val">${d.disk.usage_pct}%</div><div class="shealth-card-sub">${d.disk.free_gb} GB free</div></div>`;
        html += `<div class="shealth-card"><div class="shealth-card-title">🌐 Network</div><div class="shealth-card-val">${d.network.recv_mb} MB</div><div class="shealth-card-sub">↑ ${d.network.sent_mb} MB sent</div></div>`;
        html += `<div class="shealth-card"><div class="shealth-card-title">📂 Sessions</div><div class="shealth-card-val">${d.application.active_sessions}</div><div class="shealth-card-sub">active</div></div>`;
        html += `<div class="shealth-card"><div class="shealth-card-title">🔧 Process</div><div class="shealth-card-val">${d.memory.process_mb} MB</div><div class="shealth-card-sub">RSS memory</div></div>`;
        html += '</div>';
        el.innerHTML = html;
    } catch(e) { console.error('System health error:', e); }
}
document.getElementById('sys-health-refresh')?.addEventListener('click', loadSysHealthPanel);
setTimeout(loadSysHealthPanel, 2600);

// ── API Usage Analytics Panel ────────────────────
async function loadApiAnalyticsPanel() {
    try {
        const r = await fetch('/api/admin/api-usage-analytics', {headers:{'Authorization':'Bearer '+(sessionStorage.getItem('admin_token')||localStorage.getItem('admin_token')||'')}});
        if (!r.ok) return;
        const d = await r.json();
        const el = document.getElementById('api-analytics-content');
        if (!el) return;
        const s = d.summary;
        let html = '<div class="aanalytics-summary">';
        html += `<div class="aanalytics-card"><div class="aanalytics-card-val">${s.total_requests}</div><div class="aanalytics-card-lbl">Total Requests</div></div>`;
        html += `<div class="aanalytics-card"><div class="aanalytics-card-val">${s.avg_response_ms}ms</div><div class="aanalytics-card-lbl">Avg Response</div></div>`;
        html += `<div class="aanalytics-card"><div class="aanalytics-card-val" style="color:${s.error_rate_pct > 5 ? '#ef4444' : '#22c55e'}">${s.error_rate_pct}%</div><div class="aanalytics-card-lbl">Error Rate</div></div>`;
        html += `<div class="aanalytics-card"><div class="aanalytics-card-val">${s.active_sessions}</div><div class="aanalytics-card-lbl">Sessions</div></div>`;
        html += '</div>';
        // Top endpoints
        html += '<div class="aanalytics-endpoints"><strong>Top Endpoints:</strong>';
        (d.endpoints || []).slice(0, 6).forEach(ep => {
            const errClr = ep.errors > 0 ? '#ef4444' : '#22c55e';
            html += `<div class="aanalytics-ep"><span class="aanalytics-ep-method">${ep.method}</span><span class="aanalytics-ep-path">${ep.endpoint}</span><span class="aanalytics-ep-calls">${ep.calls} calls</span><span class="aanalytics-ep-ms">${ep.avg_ms}ms</span><span style="color:${errClr}">${ep.errors} err</span></div>`;
        });
        html += '</div>';
        // Status codes
        html += '<div class="aanalytics-codes"><strong>Status Codes:</strong> ';
        Object.entries(d.status_codes || {}).forEach(([code, count]) => {
            const cClr = code.startsWith('2') ? '#22c55e' : code.startsWith('4') ? '#eab308' : '#ef4444';
            html += `<span class="aanalytics-code" style="border-color:${cClr}">${code}: ${count}</span> `;
        });
        html += '</div>';
        el.innerHTML = html;
    } catch(e) { console.error('API analytics error:', e); }
}
document.getElementById('api-analytics-refresh')?.addEventListener('click', loadApiAnalyticsPanel);
setTimeout(loadApiAnalyticsPanel, 2800);

// ── User Activity Panel ──────────────────────────
async function loadUserActivityPanel() {
    try {
        const r = await fetch('/api/admin/user-activity', {headers:{'Authorization':'Bearer '+(sessionStorage.getItem('admin_token')||localStorage.getItem('admin_token')||'')}});
        if (!r.ok) return;
        const d = await r.json();
        const el = document.getElementById('user-activity-content');
        if (!el) return;
        const e = d.engagement;
        let html = '<div class="uactivity-summary">';
        html += `<div class="uactivity-card"><div class="uactivity-card-val">${e.total_sessions}</div><div class="uactivity-card-lbl">Total Sessions</div></div>`;
        html += `<div class="uactivity-card"><div class="uactivity-card-val">${e.active_sessions}</div><div class="uactivity-card-lbl">Active</div></div>`;
        html += `<div class="uactivity-card"><div class="uactivity-card-val">${e.total_messages}</div><div class="uactivity-card-lbl">Messages</div></div>`;
        html += `<div class="uactivity-card"><div class="uactivity-card-val">${e.avg_messages_per_session}</div><div class="uactivity-card-lbl">Avg Msgs</div></div>`;
        html += `<div class="uactivity-card"><div class="uactivity-card-val">${e.engagement_rate_pct}%</div><div class="uactivity-card-lbl">Engagement</div></div>`;
        html += '</div>';
        // Action breakdown
        const ab = d.action_breakdown;
        html += '<div class="uactivity-actions"><strong>Action Breakdown:</strong>';
        html += `<span>💬 Chat: ${ab.chat_messages}</span><span>📁 Sessions: ${ab.sessions_created}</span><span>📤 Exports: ${ab.exports}</span><span>🔬 Analyses: ${ab.analyses_run}</span><span>🔍 Searches: ${ab.searches}</span>`;
        html += '</div>';
        // Recent activity
        if (d.recent_activity && d.recent_activity.length > 0) {
            html += '<div class="uactivity-recent"><strong>Recent Sessions:</strong>';
            d.recent_activity.slice(0, 8).forEach(a => {
                const stClr = a.status === 'active' ? '#22c55e' : '#94a3b8';
                html += `<div class="uactivity-row"><span class="uactivity-sid">${a.session_id}</span><span style="color:${stClr}">${a.status}</span><span>${a.messages} msgs</span><span>${a.created}</span></div>`;
            });
            html += '</div>';
        }
        el.innerHTML = html;
    } catch(e) { console.error('User activity error:', e); }
}
document.getElementById('user-activity-refresh')?.addEventListener('click', loadUserActivityPanel);
setTimeout(loadUserActivityPanel, 3000);

// ── Feature Usage Stats Panel (upgraded to analytics API) ───────────────────────
// Defined below in the Feature Usage Analytics section
document.getElementById('feature-usage-refresh')?.addEventListener('click', function(){if(typeof loadFeatureUsagePanel==='function')loadFeatureUsagePanel();});

// ── Error Tracker Panel ─────────────────────────────
async function loadErrorTrackerPanel() {
    const el = document.getElementById('error-tracker-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/error-tracker', {headers:{'Authorization':'Bearer '+(sessionStorage.getItem('admin_token')||localStorage.getItem('admin_token')||'')}});
        const d = await r.json();
        const hColors = {healthy:'#22c55e',degraded:'#eab308',unhealthy:'#ef4444'};
        const hc = hColors[d.health] || '#666';
        let html = `<div class="errtrack-health" style="border-left:3px solid ${hc}"><span class="errtrack-hlbl">System Health</span><span class="errtrack-hval" style="color:${hc}">${d.health.toUpperCase()}</span><span class="errtrack-rate">${d.error_rate_pct}% error rate</span></div>`;
        html += '<div class="errtrack-grid">';
        html += `<div class="errtrack-stat"><span class="errtrack-num">${d.total_errors_24h}</span><span class="errtrack-lbl">Errors (24h)</span></div>`;
        html += `<div class="errtrack-stat"><span class="errtrack-num">${d.total_requests_24h}</span><span class="errtrack-lbl">Requests (24h)</span></div>`;
        html += '</div>';
        html += '<div class="errtrack-sev"><strong>Severity</strong>';
        Object.entries(d.severity_breakdown).forEach(([k, v]) => {
            const sc = k === 'high' || k === 'critical' ? '#ef4444' : k === 'medium' ? '#eab308' : '#22c55e';
            html += `<span class="errtrack-sev-badge" style="color:${sc}">${k}: ${v}</span>`;
        });
        html += '</div>';
        html += '<div class="errtrack-types"><strong>Error Types</strong>';
        d.error_types.forEach(t => { html += `<div class="errtrack-type-row"><span>${t.icon} ${t.type}</span><span>${t.count}</span></div>`; });
        html += '</div>';
        html += '<div class="errtrack-recent"><strong>Recent Errors</strong>';
        d.recent_errors.slice(0, 5).forEach(e => {
            html += `<div class="errtrack-err-row"><span>${e.icon} ${e.message}</span><span class="errtrack-ago">${e.minutes_ago}m ago</span></div>`;
        });
        html += '</div>';
        el.innerHTML = html;
    } catch(e) { console.error('Error tracker error:', e); }
}
document.getElementById('error-tracker-refresh')?.addEventListener('click', loadErrorTrackerPanel);
setTimeout(loadErrorTrackerPanel, 4000);

// ── Gemini AI Usage Panel ───────────────────────────
async function loadGeminiUsagePanel() {
    const el = document.getElementById('gemini-usage-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/gemini-usage', {headers:{'Authorization':'Bearer '+(sessionStorage.getItem('admin_token')||localStorage.getItem('admin_token')||'')}});
        const d = await r.json();
        let html = '<div class="gemuse-grid">';
        html += `<div class="gemuse-stat"><span class="gemuse-num">${d.total_requests_24h.toLocaleString()}</span><span class="gemuse-lbl">Requests</span></div>`;
        html += `<div class="gemuse-stat"><span class="gemuse-num">${(d.total_tokens_in/1000).toFixed(0)}k</span><span class="gemuse-lbl">Tokens In</span></div>`;
        html += `<div class="gemuse-stat"><span class="gemuse-num">${(d.total_tokens_out/1000).toFixed(0)}k</span><span class="gemuse-lbl">Tokens Out</span></div>`;
        html += `<div class="gemuse-stat"><span class="gemuse-num">$${d.total_cost_estimate}</span><span class="gemuse-lbl">Est. Cost</span></div>`;
        html += `<div class="gemuse-stat"><span class="gemuse-num">${d.avg_latency_ms}ms</span><span class="gemuse-lbl">Avg Latency</span></div>`;
        html += '</div>';
        html += '<div class="gemuse-models"><strong>🧠 Model Breakdown</strong>';
        d.models.forEach(m => {
            const ec = m.error_rate_pct > 2 ? '#ef4444' : '#22c55e';
            html += `<div class="gemuse-model"><span class="gemuse-mname">${m.model}</span><span>${m.requests_24h} req</span><span class="gemuse-mcost">$${m.cost_estimate}</span><span class="gemuse-merr" style="color:${ec}">${m.error_rate_pct}% err</span></div>`;
        });
        html += '</div>';
        el.innerHTML = html;
    } catch(e) { console.error('Gemini usage error:', e); }
}
document.getElementById('gemini-usage-refresh')?.addEventListener('click', loadGeminiUsagePanel);
setTimeout(loadGeminiUsagePanel, 4500);

// ── Session Insights Panel ──────────────────────────
async function loadSessionInsightsPanel() {
    const el = document.getElementById('session-insights-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/session-insights', {headers:{'Authorization':'Bearer '+(sessionStorage.getItem('admin_token')||localStorage.getItem('admin_token')||'')}});
        const d = await r.json();
        let html = '<div class="sesins-grid">';
        html += `<div class="sesins-stat"><span class="sesins-num">${d.total_sessions}</span><span class="sesins-lbl">Total</span></div>`;
        html += `<div class="sesins-stat"><span class="sesins-num">${d.active_now}</span><span class="sesins-lbl">Active</span></div>`;
        html += `<div class="sesins-stat"><span class="sesins-num">${d.completed_today}</span><span class="sesins-lbl">Today</span></div>`;
        html += `<div class="sesins-stat"><span class="sesins-num">${d.avg_duration_minutes}m</span><span class="sesins-lbl">Avg Duration</span></div>`;
        html += `<div class="sesins-stat"><span class="sesins-num">${d.completion_rate_pct}%</span><span class="sesins-lbl">Completion</span></div>`;
        html += `<div class="sesins-stat"><span class="sesins-num">⭐${d.satisfaction_score}</span><span class="sesins-lbl">Satisfaction</span></div>`;
        html += '</div>';
        html += '<div class="sesins-features"><strong>🔥 Top Features Used</strong>';
        d.top_features_used.forEach(f => {
            html += `<div class="sesins-feat"><span>${f.icon} ${f.feature}</span><div class="sesins-featbar"><div class="sesins-featfill" style="width:${f.usage_pct}%"></div></div><span>${f.usage_pct}%</span></div>`;
        });
        html += '</div>';
        html += '<div class="sesins-peak"><strong>📈 Peak Hours</strong>';
        d.peak_hours.forEach(h => {
            html += `<div class="sesins-hour"><span>${h.hour}</span><span>${h.sessions} sessions</span></div>`;
        });
        html += '</div>';
        el.innerHTML = html;
    } catch(e) { console.error('Session insights error:', e); }
}
document.getElementById('session-insights-refresh')?.addEventListener('click', loadSessionInsightsPanel);
setTimeout(loadSessionInsightsPanel, 5000);

// ═══════════════════════════════════════════════════════════════
// Admin: Model Performance Dashboard
// ═══════════════════════════════════════════════════════════════
async function loadModelPerformancePanel() {
    const el = document.getElementById('model-performance-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/model-performance', {headers:{'Authorization':'Bearer '+(sessionStorage.getItem('admin_token')||localStorage.getItem('admin_token')||'')}});
        const d = await r.json();
        const tierColors = { primary: '#3b82f6', secondary: '#22c55e', premium: '#f59e0b' };
        let html = `<div class="modperf-summary"><div class="modperf-stat"><span class="modperf-num">${d.total_requests_7d.toLocaleString()}</span><span class="modperf-lbl">Total Requests (7d)</span></div>`;
        html += `<div class="modperf-stat"><span class="modperf-num">$${d.total_cost_7d.toFixed(2)}</span><span class="modperf-lbl">Est. Cost (7d)</span></div>`;
        html += `<div class="modperf-stat"><span class="modperf-num">${d.avg_quality_score}</span><span class="modperf-lbl">Avg Quality Score</span></div></div>`;
        html += '<div class="modperf-models">';
        d.models.forEach(m => {
            const tc = tierColors[m.tier] || '#666';
            const errColor = m.error_rate_pct > 2 ? '#ef4444' : m.error_rate_pct > 1 ? '#eab308' : '#22c55e';
            html += `<div class="modperf-model" style="border-left:4px solid ${tc}">`;
            html += `<div class="modperf-model-head"><span class="modperf-icon">${m.icon}</span><div><strong>${m.display_name}</strong><span class="modperf-tier" style="color:${tc}">${m.tier}</span></div>`;
            html += `<span class="modperf-uptime">${m.uptime_pct}% uptime</span></div>`;
            html += `<div class="modperf-grid">`;
            html += `<div class="modperf-cell"><span class="modperf-val">${m.requests_7d.toLocaleString()}</span><span class="modperf-cell-lbl">Requests</span></div>`;
            html += `<div class="modperf-cell"><span class="modperf-val">${m.avg_latency_ms}ms</span><span class="modperf-cell-lbl">Avg Latency</span></div>`;
            html += `<div class="modperf-cell"><span class="modperf-val">${m.p95_latency_ms}ms</span><span class="modperf-cell-lbl">P95 Latency</span></div>`;
            html += `<div class="modperf-cell"><span class="modperf-val" style="color:${errColor}">${m.error_rate_pct}%</span><span class="modperf-cell-lbl">Error Rate</span></div>`;
            html += `<div class="modperf-cell"><span class="modperf-val">${m.quality_score}</span><span class="modperf-cell-lbl">Quality</span></div>`;
            html += `<div class="modperf-cell"><span class="modperf-val">$${m.total_cost_7d}</span><span class="modperf-cell-lbl">Cost 7d</span></div>`;
            html += '</div>';
            const qW = Math.min(m.quality_score, 100);
            html += `<div class="modperf-quality-bar"><div style="width:${qW}%;background:${tc};height:6px;border-radius:3px"></div></div>`;
            html += '</div>';
        });
        html += '</div>';
        if (d.daily_trends && d.daily_trends.length > 0) {
            html += '<div class="modperf-trends"><strong>📈 7-Day Request Trend</strong><div class="modperf-trend-bars">';
            const maxReqs = Math.max(...d.daily_trends.map(t => t.requests), 1);
            d.daily_trends.forEach(t => {
                const h = Math.round((t.requests / maxReqs) * 60);
                html += `<div class="modperf-trend-bar"><div class="modperf-tbar-fill" style="height:${h}px;background:#3b82f6"></div><span class="modperf-tbar-lbl">${t.date}</span><span class="modperf-tbar-val">${t.requests}</span></div>`;
            });
            html += '</div></div>';
        }
        el.innerHTML = html;
    } catch(e) { if(el) el.innerHTML = '<p class="admin-error">Could not load model performance data.</p>'; console.error(e); }
}
document.getElementById('model-performance-refresh')?.addEventListener('click', loadModelPerformancePanel);
setTimeout(loadModelPerformancePanel, 5500);

// ═══════════════════════════════════════════════════════════════
// Admin: Witness Behavior Trends
// ═══════════════════════════════════════════════════════════════
async function loadWitnessTrendsPanel() {
    const el = document.getElementById('witness-trends-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/witness-trends', {headers:{'Authorization':'Bearer '+(sessionStorage.getItem('admin_token')||localStorage.getItem('admin_token')||'')}});
        const d = await r.json();
        const dirColors = { improving: '#22c55e', worsening: '#ef4444', stable: '#6b7280' };
        let html = `<div class="wtrend-summary">`;
        html += `<div class="wtrend-stat" style="color:#22c55e"><span class="wtrend-num">${d.improving_trends}</span><span class="wtrend-lbl">Improving</span></div>`;
        html += `<div class="wtrend-stat" style="color:#ef4444"><span class="wtrend-num">${d.worsening_trends}</span><span class="wtrend-lbl">Worsening</span></div>`;
        html += `<div class="wtrend-stat"><span class="wtrend-num">${d.stable_trends}</span><span class="wtrend-lbl">Stable</span></div>`;
        html += `<div class="wtrend-stat"><span class="wtrend-num">${d.total_sessions_analyzed}</span><span class="wtrend-lbl">Sessions Analyzed</span></div></div>`;
        html += '<div class="wtrend-metrics">';
        Object.values(d.trends).forEach(t => {
            const tc = dirColors[t.trend_direction] || '#666';
            const changeSign = t.change > 0 ? '+' : '';
            html += `<div class="wtrend-metric"><div class="wtrend-metric-head"><span>${t.icon} ${t.label}</span><span class="wtrend-dir" style="color:${tc}">${t.trend_icon} ${t.trend_direction}</span></div>`;
            html += `<div class="wtrend-vals"><span class="wtrend-cur">${t.current}${t.unit}</span><span class="wtrend-chg" style="color:${tc}">${changeSign}${t.change}${t.unit}</span></div></div>`;
        });
        html += '</div>';
        if (d.top_patterns && d.top_patterns.length > 0) {
            html += '<div class="wtrend-patterns"><strong>🔍 Common Behavior Patterns</strong>';
            d.top_patterns.forEach(p => {
                const barW = Math.min(p.frequency_pct, 100);
                html += `<div class="wtrend-pattern"><div class="wtrend-pat-head"><span>${p.icon} ${p.pattern}</span><span>${p.frequency_pct}% of sessions</span></div>`;
                html += `<div class="wtrend-pat-bar"><div style="width:${barW}%;background:#3b82f6;height:8px;border-radius:4px"></div></div></div>`;
            });
            html += '</div>';
        }
        el.innerHTML = html;
    } catch(e) { if(el) el.innerHTML = '<p class="admin-error">Could not load witness trends.</p>'; console.error(e); }
}
document.getElementById('witness-trends-refresh')?.addEventListener('click', loadWitnessTrendsPanel);
setTimeout(loadWitnessTrendsPanel, 6000);

// ─── Admin Case Complexity Dashboard ─────────────────────────────────────────
async function loadCaseComplexity() {
    const token = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || '';
    const r = await fetch('/api/admin/case-complexity', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { return '<p class="admin-error">Could not load case complexity data.</p>'; }
    const d = await r.json();
    const distColors = { simple: '#22c55e', moderate: '#eab308', complex: '#f97316', highly_complex: '#ef4444' };
    let html = `<div class="admin-widget"><h3>🧩 Case Complexity Dashboard</h3>`;
    html += `<div class="complexity-summary-bar">`;
    html += `<div class="complexity-kpi"><span class="complexity-num">${d.total_cases}</span><span class="complexity-lbl">Total Cases</span></div>`;
    html += `<div class="complexity-kpi"><span class="complexity-num" style="color:#ef4444">${d.high_complexity_pct}%</span><span class="complexity-lbl">High/Complex</span></div>`;
    html += `<div class="complexity-kpi"><span class="complexity-num">${d.avg_overall_complexity_score}</span><span class="complexity-lbl">Avg Score</span></div>`;
    html += `</div>`;
    html += `<div class="complexity-dist-grid">`;
    Object.entries(d.complexity_distribution).forEach(([k, v]) => {
        const c = distColors[k] || '#94a3b8';
        html += `<div class="complexity-dist-card" style="border-color:${c}">`;
        html += `<div class="complexity-dist-icon">${v.icon}</div>`;
        html += `<div class="complexity-dist-count" style="color:${c}">${v.count}</div>`;
        html += `<div class="complexity-dist-label">${v.label}</div>`;
        html += `<div class="complexity-dist-meta">~${v.avg_sessions} sessions · ${v.avg_duration_min}min avg</div>`;
        html += `</div>`;
    });
    html += `</div>`;
    html += `<h4>📊 Complexity Drivers</h4><div class="complexity-drivers">`;
    d.complexity_drivers.forEach(dr => {
        html += `<div class="complexity-driver-row">`;
        html += `<span class="complexity-driver-name">${dr.driver}</span>`;
        html += `<div class="complexity-bar-wrap"><div class="complexity-bar-fill" style="width:${dr.impact_score}%"></div></div>`;
        html += `<span class="complexity-driver-pct">${dr.affected_cases_pct}% of cases</span>`;
        html += `</div>`;
    });
    html += `</div>`;
    html += `<div class="complexity-summary">${d.summary}</div>`;
    html += `<div class="complexity-recs"><h4>💡 Recommendations</h4><ul>`;
    d.recommendations.forEach(rec => { html += `<li>${rec}</li>`; });
    html += `</ul></div></div>`;
    return html;
}

// ─── Admin Investigation Quality Report ───────────────────────────────────────
async function loadInvestigationQuality() {
    const token = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || '';
    const r = await fetch('/api/admin/investigation-quality', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { return '<p class="admin-error">Could not load investigation quality data.</p>'; }
    const d = await r.json();
    const statusColors = { above: '#22c55e', 'on-target': '#eab308', below: '#ef4444' };
    let html = `<div class="admin-widget"><h3>🏆 Investigation Quality Report</h3>`;
    html += `<div class="iq-header">`;
    html += `<div class="iq-score" style="color:${d.quality_color}">${d.overall_quality_score}<span class="iq-unit">/100</span></div>`;
    html += `<div class="iq-label" style="color:${d.quality_color}">${d.quality_label}</div>`;
    html += `<div class="iq-meta"><span>✅ ${d.above_benchmark_count} above benchmark</span><span>❌ ${d.below_benchmark_count} below benchmark</span></div>`;
    html += `</div>`;
    html += `<div class="iq-dims">`;
    Object.values(d.quality_dimensions).forEach(dim => {
        const sc = statusColors[dim.status] || '#94a3b8';
        const vs = dim.vs_benchmark >= 0 ? `+${dim.vs_benchmark}` : `${dim.vs_benchmark}`;
        html += `<div class="iq-dim-row">`;
        html += `<span class="iq-dim-icon">${dim.icon}</span>`;
        html += `<span class="iq-dim-label">${dim.label}</span>`;
        html += `<div class="iq-dim-bar-wrap"><div class="iq-dim-bar-fill" style="width:${dim.score}%;background:${sc}"></div>`;
        html += `<div class="iq-dim-bench" style="left:${dim.benchmark}%"></div></div>`;
        html += `<span class="iq-dim-score">${dim.score}</span>`;
        html += `<span class="iq-dim-vs" style="color:${sc}">(${vs})</span>`;
        html += `</div>`;
    });
    html += `</div>`;
    html += `<div class="iq-trend"><h4>📈 Weekly Quality Trend</h4><div class="iq-trend-bars">`;
    d.weekly_quality_trend.forEach(w => {
        const h = Math.round(w.quality_score * 0.8);
        html += `<div class="iq-trend-bar-group"><div class="iq-trend-bar" style="height:${h}px" title="Score: ${w.quality_score}"></div><span class="iq-trend-week">${w.week}</span></div>`;
    });
    html += `</div></div>`;
    html += `<div class="iq-summary">${d.summary}</div>`;
    html += `<div class="iq-recs"><h4>💡 Recommendations</h4><ul>`;
    d.recommendations.forEach(rec => { html += `<li>${rec}</li>`; });
    html += `</ul></div></div>`;
    return html;
}

// ─── Wire Case Complexity & Investigation Quality panels ──────────────────────
async function loadCaseComplexityPanel() {
    const el = document.getElementById('case-complexity-content');
    if (!el) return;
    try {
        el.innerHTML = await loadCaseComplexity();
    } catch(e) { if(el) el.innerHTML = '<p class="admin-error">Could not load case complexity.</p>'; console.error(e); }
}

async function loadInvestigationQualityPanel() {
    const el = document.getElementById('investigation-quality-content');
    if (!el) return;
    try {
        el.innerHTML = await loadInvestigationQuality();
    } catch(e) { if(el) el.innerHTML = '<p class="admin-error">Could not load investigation quality.</p>'; console.error(e); }
}

document.getElementById('case-complexity-refresh')?.addEventListener('click', loadCaseComplexityPanel);
document.getElementById('investigation-quality-refresh')?.addEventListener('click', loadInvestigationQualityPanel);
setTimeout(loadCaseComplexityPanel, 7000);
setTimeout(loadInvestigationQualityPanel, 8500);

// ─── Testimony Length Distribution ────────────────────────────────────────────
async function loadTestimonyDistribution() {
    const token = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || '';
    const res = await fetch('/api/admin/testimony-distribution', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!res.ok) { return '<p class="admin-error">Could not load testimony distribution.</p>'; }
    const d = await res.json();
    let html = `<div class="admin-metric-grid">`;
    html += `<div class="admin-metric"><span class="admin-metric-val">${d.avg_session_duration_min} min</span><span class="admin-metric-lbl">Avg Duration</span></div>`;
    html += `<div class="admin-metric"><span class="admin-metric-val">${d.avg_exchanges_per_session}</span><span class="admin-metric-lbl">Avg Exchanges</span></div>`;
    html += `<div class="admin-metric"><span class="admin-metric-val">${d.longest_session_min} min</span><span class="admin-metric-lbl">Longest</span></div>`;
    html += `<div class="admin-metric"><span class="admin-metric-val">${d.peak_bucket}</span><span class="admin-metric-lbl">Peak Range</span></div>`;
    html += `</div>`;
    html += `<p style="font-size:0.85rem;color:#94a3b8;margin-bottom:0.75rem">${d.summary}</p>`;
    html += `<h4 style="font-size:0.9rem;margin-bottom:0.5rem">📊 Length Distribution (${d.total_sessions} sessions)</h4>`;
    html += `<div style="display:flex;flex-direction:column;gap:0.4rem;margin-bottom:0.75rem">`;
    const maxCount = Math.max(...d.length_distribution.map(b => b.count));
    d.length_distribution.forEach(b => {
        const pct = maxCount > 0 ? Math.round(100 * b.count / maxCount) : 0;
        html += `<div style="display:flex;align-items:center;gap:0.5rem;font-size:0.82rem">`;
        html += `<span style="min-width:70px;color:#94a3b8">${b.label}</span>`;
        html += `<div style="flex:1;height:14px;background:rgba(255,255,255,0.08);border-radius:3px">`;
        html += `<div style="width:${pct}%;height:100%;background:${b.color};border-radius:3px"></div></div>`;
        html += `<span style="min-width:35px;text-align:right">${b.count}</span>`;
        html += `<span style="color:#64748b;min-width:50px">${b.avg_exchanges} exch</span></div>`;
    });
    html += `</div>`;
    html += `<h4 style="font-size:0.9rem;margin-bottom:0.5rem">📝 Verbosity Breakdown</h4>`;
    html += `<div style="display:flex;gap:0.6rem;flex-wrap:wrap;margin-bottom:0.75rem">`;
    Object.values(d.verbosity_breakdown).forEach(v => {
        html += `<div style="background:rgba(255,255,255,0.06);border-radius:6px;padding:0.4rem 0.7rem;font-size:0.82rem">`;
        html += `<div style="font-weight:700;color:${v.color}">${v.pct}%</div><div style="color:#94a3b8">${v.label}</div></div>`;
    });
    html += `</div>`;
    html += `<div style="font-size:0.78rem;color:#64748b;border-top:1px solid rgba(255,255,255,0.06);padding-top:0.5rem">`;
    d.recommendations.forEach(r => { html += `<div>• ${r}</div>`; });
    html += `</div>`;
    return html;
}

async function loadTestimonyDistributionPanel() {
    const el = document.getElementById('testimony-distribution-content');
    if (!el) return;
    try {
        el.innerHTML = await loadTestimonyDistribution();
    } catch(e) { if(el) el.innerHTML = '<p class="admin-error">Could not load testimony distribution.</p>'; console.error(e); }
}

document.getElementById('testimony-distribution-refresh')?.addEventListener('click', loadTestimonyDistributionPanel);
setTimeout(loadTestimonyDistributionPanel, 10000);

// ─── ADMIN TOKEN HELPER ────────────────────────────────────────────────────────
function getAdminToken() {
    return sessionStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || localStorage.getItem('admin_token') || '';
}

// ─── EVIDENCE ANALYTICS ──────────────────────────────────────────────────────
async function loadEvidenceAnalytics() {
    const res = await fetch('/api/admin/evidence-analytics', { headers: { 'Authorization': 'Bearer ' + getAdminToken() } });
    if (!res.ok) throw new Error('Auth failed');
    const d = await res.json();
    let html = `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.5rem;margin-bottom:0.75rem">`;
    html += `<div class="admin-metric-box"><div class="admin-metric-val">${d.total_evidence_items.toLocaleString()}</div><div class="admin-metric-lbl">Total Evidence Items</div></div>`;
    html += `<div class="admin-metric-box"><div class="admin-metric-val" style="color:#22c55e">${d.top_reliability_type.score}/100</div><div class="admin-metric-lbl">Best: ${d.top_reliability_type.type}</div></div>`;
    html += `<div class="admin-metric-box"><div class="admin-metric-val" style="color:#f97316">${d.lowest_reliability_type.score}/100</div><div class="admin-metric-lbl">Lowest: ${d.lowest_reliability_type.type}</div></div>`;
    html += `</div>`;
    html += `<div style="margin-bottom:0.75rem"><h4 style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.5rem">Evidence Type Distribution</h4>`;
    d.evidence_types.forEach(e => {
        const c = e.avg_reliability_score >= 80 ? '#22c55e' : e.avg_reliability_score >= 65 ? '#eab308' : '#f97316';
        html += `<div style="margin-bottom:0.3rem">`;
        html += `<div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#cbd5e1;margin-bottom:0.15rem">`;
        html += `<span>${e.icon} ${e.type}</span><span>${e.count} items (${e.percentage}%) — Reliability: <span style="color:${c}">${e.avg_reliability_score}/100</span></span></div>`;
        html += `<div style="height:5px;background:rgba(255,255,255,0.08);border-radius:3px">`;
        html += `<div style="height:100%;width:${e.percentage}%;background:${e.color};border-radius:3px"></div></div></div>`;
    });
    html += `</div>`;
    html += `<div style="font-size:0.78rem;color:#64748b;border-top:1px solid rgba(255,255,255,0.06);padding-top:0.5rem">`;
    d.insights.forEach(ins => { html += `<div>• ${ins}</div>`; });
    html += `</div>`;
    return html;
}

async function loadEvidenceAnalyticsPanel() {
    const el = document.getElementById('evidence-analytics-content');
    if (!el) return;
    try {
        el.innerHTML = await loadEvidenceAnalytics();
    } catch(e) { if(el) el.innerHTML = '<p class="admin-error">Could not load evidence analytics.</p>'; console.error(e); }
}

// ─── RESOLUTION FORECAST ─────────────────────────────────────────────────────
async function loadResolutionForecast() {
    const res = await fetch('/api/admin/resolution-forecast', { headers: { 'Authorization': 'Bearer ' + getAdminToken() } });
    if (!res.ok) throw new Error('Auth failed');
    const d = await res.json();
    let html = `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.5rem;margin-bottom:0.75rem">`;
    html += `<div class="admin-metric-box"><div class="admin-metric-val">${d.most_likely_probability}%</div><div class="admin-metric-lbl">${d.most_likely_outcome}</div></div>`;
    html += `<div class="admin-metric-box"><div class="admin-metric-val">${d.resolution_timeline.avg_days_to_resolution}d</div><div class="admin-metric-lbl">Avg Resolution Time</div></div>`;
    html += `<div class="admin-metric-box"><div class="admin-metric-val" style="color:#eab308">${d.resolution_timeline.cases_pending}</div><div class="admin-metric-lbl">Cases Pending</div></div>`;
    html += `</div>`;
    html += `<div style="margin-bottom:0.75rem"><h4 style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.5rem">Outcome Probability Distribution</h4>`;
    d.outcome_probabilities.forEach(o => {
        html += `<div style="margin-bottom:0.3rem">`;
        html += `<div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#cbd5e1;margin-bottom:0.15rem">`;
        html += `<span>${o.icon} ${o.outcome}</span><span style="color:${o.color};font-weight:600">${o.probability_pct}%</span></div>`;
        html += `<div style="height:6px;background:rgba(255,255,255,0.08);border-radius:3px">`;
        html += `<div style="height:100%;width:${o.probability_pct}%;background:${o.color};border-radius:3px"></div></div></div>`;
    });
    html += `</div>`;
    html += `<div style="margin-bottom:0.75rem"><h4 style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.3rem">Predictive Factors</h4>`;
    d.predictive_factors.forEach(pf => {
        const c = pf.current_score >= 75 ? '#22c55e' : pf.current_score >= 50 ? '#eab308' : '#f97316';
        const impC = pf.impact === 'High' ? '#ef4444' : pf.impact === 'Medium' ? '#eab308' : '#64748b';
        html += `<div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#cbd5e1;padding:0.2rem 0;border-bottom:1px solid rgba(255,255,255,0.04)">`;
        html += `<span>${pf.factor} <span style="color:${impC};font-size:0.7rem">[${pf.impact}]</span></span>`;
        html += `<span style="color:${c};font-weight:600">${pf.current_score}/100</span></div>`;
    });
    html += `</div>`;
    const rt = d.resolution_timeline;
    html += `<div style="font-size:0.75rem;color:#64748b;display:grid;grid-template-columns:1fr 1fr;gap:0.25rem">`;
    html += `<div>⚡ Fastest: ${rt.fastest_resolution_days}d</div><div>🐌 Longest pending: ${rt.longest_pending_days}d</div>`;
    html += `<div>✅ Resolved (30d): ${rt.cases_resolved_30d}</div><div>⚠️ Stalled (60d+): ${rt.cases_stalled_60d}</div>`;
    html += `</div>`;
    return html;
}

async function loadResolutionForecastPanel() {
    const el = document.getElementById('resolution-forecast-content');
    if (!el) return;
    try {
        el.innerHTML = await loadResolutionForecast();
    } catch(e) { if(el) el.innerHTML = '<p class="admin-error">Could not load resolution forecast.</p>'; console.error(e); }
}

document.getElementById('evidence-analytics-refresh')?.addEventListener('click', loadEvidenceAnalyticsPanel);
document.getElementById('resolution-forecast-refresh')?.addEventListener('click', loadResolutionForecastPanel);
setTimeout(loadEvidenceAnalyticsPanel, 13000);
setTimeout(loadResolutionForecastPanel, 14500);

// ─── ADMIN PLEA DEAL TRENDS ───────────────────────────────────────────────────
async function loadPleaTrends() {
    const token = getAdminToken();
    const res = await fetch('/api/admin/plea-trends', { headers: { 'Authorization': 'Bearer ' + token } });
    const d = await res.json();
    const trendColor = d.trend_direction === 'rising' ? '#22c55e' : '#f97316';
    let html = '<div style="margin-bottom:0.75rem;display:flex;gap:1.5rem;align-items:center">';
    html += '<div style="font-size:1.5rem;font-weight:800;color:#60a5fa">' + d.overall_plea_rate_pct + '%</div>';
    html += '<div><div style="font-size:0.78rem;color:#94a3b8">Overall Plea Rate</div>';
    html += '<div style="font-size:0.73rem;color:' + trendColor + ';font-weight:600">Trend: ' + d.trend_direction + ' · Avg reduction: ' + d.avg_sentence_reduction_pct + '%</div></div></div>';
    html += '<div style="margin-bottom:0.75rem"><h4 style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.3rem">📂 By Charge Category</h4>';
    d.charge_categories.forEach(cat => {
        const c = cat.plea_rate_pct >= 60 ? '#22c55e' : cat.plea_rate_pct >= 40 ? '#eab308' : '#f97316';
        html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#cbd5e1;padding:0.2rem 0;border-bottom:1px solid rgba(255,255,255,0.04)">';
        html += '<span>' + cat.category + ' (' + cat.count + ' cases)</span>';
        html += '<span style="color:' + c + ';font-weight:700">' + cat.plea_rate_pct + '% · -' + cat.avg_reduction_pct + '% sentence</span></div>';
    });
    html += '</div>';
    html += '<div style="margin-bottom:0.75rem"><h4 style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.3rem">📅 Monthly Trend (last 12 months)</h4>';
    html += '<div style="display:flex;gap:2px;align-items:flex-end;height:50px">';
    const maxRate = Math.max(...d.monthly_data.map(m => m.plea_rate_pct));
    d.monthly_data.forEach(m => {
        const h = Math.max(4, Math.round(50 * m.plea_rate_pct / maxRate));
        const c = m.plea_rate_pct >= 60 ? '#22c55e' : m.plea_rate_pct >= 40 ? '#eab308' : '#f97316';
        html += '<div style="flex:1;background:' + c + ';height:' + h + 'px;border-radius:2px 2px 0 0;opacity:0.85" title="' + m.month + ': ' + m.plea_rate_pct + '%"></div>';
    });
    html += '</div></div>';
    html += '<div style="margin-bottom:0.5rem"><h4 style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.3rem">💡 Insights</h4>';
    d.insights.forEach(ins => { html += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:0.15rem">• ' + ins + '</div>'; });
    html += '</div>';
    return html;
}

async function loadPleaTrendsPanel() {
    const el = document.getElementById('plea-trends-content');
    try {
        el.innerHTML = await loadPleaTrends();
    } catch(e) { if(el) el.innerHTML = '<p class="admin-error">Could not load plea deal trends.</p>'; console.error(e); }
}

// ─── ADMIN WITNESS BACKGROUND RISK ────────────────────────────────────────────
async function loadBackgroundRisk() {
    const token = getAdminToken();
    const res = await fetch('/api/admin/background-risk', { headers: { 'Authorization': 'Bearer ' + token } });
    const d = await res.json();
    let html = '<div style="margin-bottom:0.75rem;display:flex;gap:1.5rem;align-items:center">';
    html += '<div style="font-size:1.5rem;font-weight:800;color:#ef4444">' + d.high_risk_count + '</div>';
    html += '<div><div style="font-size:0.78rem;color:#94a3b8">High-Risk Witnesses</div>';
    html += '<div style="font-size:0.73rem;color:#94a3b8">of ' + d.total_witnesses_analyzed + ' total analyzed</div></div>';
    html += '</div>';
    html += '<div style="margin-bottom:0.75rem"><h4 style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.3rem">🎯 Risk Distribution</h4>';
    html += '<div style="display:flex;gap:0.4rem">';
    d.risk_distribution.forEach(rd => {
        html += '<div style="flex:' + rd.pct + ';background:' + rd.color + ';border-radius:4px;padding:0.4rem;min-width:0">';
        html += '<div style="font-size:0.7rem;color:#fff;font-weight:700">' + rd.pct + '%</div>';
        html += '<div style="font-size:0.65rem;color:rgba(255,255,255,0.75)">' + rd.tier + '</div>';
        html += '<div style="font-size:0.65rem;color:rgba(255,255,255,0.6)">' + rd.count + ' witnesses</div></div>';
    });
    html += '</div></div>';
    html += '<div style="margin-bottom:0.75rem"><h4 style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.3rem">⚠️ Risk Factors</h4>';
    d.risk_factors.forEach(rf => {
        const trendColor = rf.trend === 'rising' ? '#ef4444' : rf.trend === 'falling' ? '#22c55e' : '#64748b';
        const trendIcon = rf.trend === 'rising' ? '↑' : rf.trend === 'falling' ? '↓' : '→';
        const ic = rf.avg_impact_score >= 75 ? '#ef4444' : rf.avg_impact_score >= 55 ? '#f97316' : '#eab308';
        html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#cbd5e1;padding:0.2rem 0;border-bottom:1px solid rgba(255,255,255,0.04)">';
        html += '<span>' + rf.icon + ' ' + rf.factor + ' <span style="color:' + trendColor + ';font-size:0.65rem">' + trendIcon + '</span></span>';
        html += '<span><span style="color:#64748b">' + rf.affected_pct + '% affected</span> · <span style="color:' + ic + ';font-weight:700">impact:' + rf.avg_impact_score + '</span></span></div>';
    });
    html += '</div>';
    html += '<div style="margin-bottom:0.5rem"><h4 style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.3rem">📈 Weekly Flagged (8 weeks)</h4>';
    html += '<div style="display:flex;gap:3px;align-items:flex-end;height:40px">';
    const maxF = Math.max(...d.weekly_flagged_trend.map(w => w.flagged));
    d.weekly_flagged_trend.forEach(w => {
        const h = Math.max(4, Math.round(40 * w.flagged / maxF));
        html += '<div style="flex:1;background:#ef4444;height:' + h + 'px;border-radius:2px 2px 0 0;opacity:0.75" title="' + w.week + ': ' + w.flagged + ' flagged, ' + w.cleared + ' cleared"></div>';
    });
    html += '</div></div>';
    html += '<div style="margin-bottom:0.5rem"><h4 style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.3rem">💡 Recommendations</h4>';
    d.recommendations.forEach(rec => { html += '<div style="font-size:0.73rem;color:#94a3b8;margin-bottom:0.15rem">• ' + rec + '</div>'; });
    html += '</div>';
    return html;
}

async function loadBackgroundRiskPanel() {
    const el = document.getElementById('background-risk-content');
    try {
        el.innerHTML = await loadBackgroundRisk();
    } catch(e) { if(el) el.innerHTML = '<p class="admin-error">Could not load background risk data.</p>'; console.error(e); }
}

document.getElementById('plea-trends-refresh')?.addEventListener('click', loadPleaTrendsPanel);
document.getElementById('background-risk-refresh')?.addEventListener('click', loadBackgroundRiskPanel);
setTimeout(loadPleaTrendsPanel, 16000);
setTimeout(loadBackgroundRiskPanel, 17500);

// ─── GEMINI COST TRACKER PANEL ────────────────────────────────────────────────
async function loadGeminiCostTrackerPanel() {
    const token = getAdminToken();
    const res = await fetch('/api/admin/gemini-cost-tracker', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!res.ok) { document.getElementById('gemini-cost-tracker-content').innerHTML = '<p style="color:#ef4444">Failed to load.</p>'; return; }
    const d = await res.json();
    const budgetColor = d.budget_status === 'Critical' ? '#ef4444' : d.budget_status === 'Warning' ? '#eab308' : '#22c55e';
    let html = '<div style="display:flex;flex-direction:column;gap:0.6rem">';
    html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.5rem">';
    [
        ['💰 Total Cost', '$' + d.total_cost_usd, '#eab308'],
        ['📞 API Calls', d.total_api_calls.toLocaleString(), '#60a5fa'],
        ['📥 Input Tokens', d.total_input_tokens.toLocaleString(), '#a78bfa'],
        ['📤 Output Tokens', d.total_output_tokens.toLocaleString(), '#f472b6'],
    ].forEach(([label, val, color]) => {
        html += '<div style="background:rgba(255,255,255,0.04);border-radius:6px;padding:0.5rem;text-align:center">';
        html += '<div style="font-size:1.1rem;font-weight:700;color:' + color + '">' + val + '</div>';
        html += '<div style="font-size:0.65rem;color:#64748b">' + label + '</div></div>';
    });
    html += '</div>';
    html += '<div style="background:rgba(255,255,255,0.03);border-radius:6px;padding:0.5rem">';
    html += '<div style="font-size:0.7rem;color:#94a3b8;margin-bottom:0.3rem">Budget: $' + d.mtd_cost_usd + ' / $' + d.budget_limit_usd + ' (' + d.budget_used_pct + '%)</div>';
    html += '<div style="background:rgba(255,255,255,0.08);border-radius:3px;height:6px"><div style="width:' + Math.min(100, d.budget_used_pct) + '%;height:100%;border-radius:3px;background:' + budgetColor + '"></div></div>';
    html += '<div style="font-size:0.65rem;color:' + budgetColor + ';margin-top:0.2rem">Status: ' + d.budget_status + '</div></div>';
    html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-top:0.2rem">Model Breakdown</div>';
    d.model_breakdown.forEach(m => {
        html += '<div style="background:rgba(255,255,255,0.03);border-radius:5px;padding:0.4rem;font-size:0.7rem">';
        html += '<div style="display:flex;justify-content:space-between"><strong>' + m.model + '</strong><span style="color:#eab308">$' + m.cost_usd + '</span></div>';
        html += '<div style="color:#64748b">' + m.calls + ' calls · ' + m.input_tokens.toLocaleString() + ' in + ' + m.output_tokens.toLocaleString() + ' out tokens · ' + m.avg_latency_ms + 'ms avg</div></div>';
    });
    html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-top:0.2rem">Cost by Analysis Type</div>';
    d.analysis_type_costs.forEach(a => {
        html += '<div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:0.15rem">';
        html += '<span style="color:#cbd5e1">' + a.type + '</span><span style="color:#eab308">$' + a.avg_cost_usd + '/call · ' + a.call_count + ' calls</span></div>';
    });
    html += '<div style="font-size:0.7rem;color:#64748b;margin-top:0.3rem">';
    d.insights.forEach(i => { html += '• ' + i + '<br>'; });
    html += '</div></div>';
    const el = document.getElementById('gemini-cost-tracker-content');
    if (el) el.innerHTML = html;
}

// ─── WITNESS QUALITY INDEX PANEL ─────────────────────────────────────────────
async function loadWitnessQualityIndexPanel() {
    const token = getAdminToken();
    const res = await fetch('/api/admin/witness-quality-index', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!res.ok) { document.getElementById('witness-quality-index-content').innerHTML = '<p style="color:#ef4444">Failed to load.</p>'; return; }
    const d = await res.json();
    const qc = d.overall_quality_index >= 75 ? '#22c55e' : d.overall_quality_index >= 55 ? '#eab308' : '#ef4444';
    const trendIcon = d.quality_trend === 'improving' ? '📈' : '📉';
    let html = '<div style="display:flex;flex-direction:column;gap:0.6rem">';
    html += '<div style="display:flex;align-items:center;gap:1rem;background:rgba(255,255,255,0.04);border-radius:8px;padding:0.6rem 1rem;border:2px solid ' + qc + '">';
    html += '<div style="font-size:1.6rem;font-weight:800;color:' + qc + '">' + d.overall_quality_index + '<span style="font-size:0.85rem">/100</span></div>';
    html += '<div><div style="font-size:0.8rem;font-weight:600;color:' + qc + '">' + trendIcon + ' ' + d.quality_trend.charAt(0).toUpperCase() + d.quality_trend.slice(1) + '</div>';
    html += '<div style="font-size:0.68rem;color:#94a3b8">' + d.total_witnesses_analyzed + ' witnesses analyzed</div></div></div>';
    html += '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:0.3rem">';
    d.score_distribution.forEach(b => {
        html += '<div style="background:rgba(255,255,255,0.03);border-radius:5px;padding:0.4rem;text-align:center">';
        html += '<div style="font-size:1rem;font-weight:700;color:' + b.color + '">' + b.pct + '%</div>';
        html += '<div style="font-size:0.58rem;color:#64748b">' + b.bracket + '</div></div>';
    });
    html += '</div>';
    html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8">Quality Dimensions</div>';
    d.quality_dimensions.forEach(dim => {
        const dc = dim.avg_score >= 70 ? '#22c55e' : dim.avg_score >= 50 ? '#eab308' : '#ef4444';
        const tc = dim.trend === 'improving' ? '#22c55e' : dim.trend === 'declining' ? '#ef4444' : '#64748b';
        html += '<div style="display:grid;grid-template-columns:1fr 70px 35px 60px;gap:0.3rem;align-items:center;margin-bottom:0.2rem">';
        html += '<span style="font-size:0.7rem;color:#cbd5e1">' + dim.dimension + '</span>';
        html += '<div style="background:rgba(255,255,255,0.08);border-radius:3px;height:5px"><div style="width:' + dim.avg_score + '%;height:100%;border-radius:3px;background:' + dc + '"></div></div>';
        html += '<span style="font-size:0.7rem;font-weight:700;color:' + dc + '">' + dim.avg_score + '</span>';
        html += '<span style="font-size:0.62rem;color:' + tc + '">' + dim.trend + '</span></div>';
    });
    html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-top:0.2rem">Quality by Case Type</div>';
    d.case_type_quality.forEach(c => {
        const cc = c.avg_quality >= 70 ? '#22c55e' : c.avg_quality >= 55 ? '#eab308' : '#ef4444';
        html += '<div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:0.15rem">';
        html += '<span style="color:#cbd5e1">' + c.case_type + '</span><span style="color:' + cc + '">' + c.avg_quality + '/100 · ' + c.sample_size + ' witnesses</span></div>';
    });
    html += '<div style="font-size:0.7rem;color:#64748b;margin-top:0.3rem">';
    d.insights.forEach(i => { html += '• ' + i + '<br>'; });
    html += '</div></div>';
    const el = document.getElementById('witness-quality-index-content');
    if (el) el.innerHTML = html;
}

document.getElementById('gemini-cost-tracker-refresh')?.addEventListener('click', loadGeminiCostTrackerPanel);
document.getElementById('witness-quality-index-refresh')?.addEventListener('click', loadWitnessQualityIndexPanel);
setTimeout(loadGeminiCostTrackerPanel, 19000);
setTimeout(loadWitnessQualityIndexPanel, 20500);

// ── Sentencing Analytics ─────────────────────────────────────────────────
async function loadSentencingAnalyticsPanel() {
    const el = document.getElementById('sentencing-analytics-content');
    if (!el) return;
    try {
        const token = getAdminToken();
        const r = await fetch('/api/admin/sentencing-analytics', { headers: { 'Authorization': 'Bearer ' + token } });
        const d = await r.json();
        if (!r.ok) { el.innerHTML = `<p class="error-msg">${d.detail || 'Error'}</p>`; return; }
        let html = `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.5rem;margin-bottom:0.8rem;">`;
        html += `<div class="stat-box"><div class="stat-val">${d.total_cases_analyzed}</div><div class="stat-lbl">Cases Analyzed</div></div>`;
        html += `<div class="stat-box"><div class="stat-val">${d.overall_avg_sentence_years}y</div><div class="stat-lbl">Avg Sentence</div></div>`;
        html += `<div class="stat-box"><div class="stat-val">${d.testimony_impact_on_sentence_pct}%</div><div class="stat-lbl">Testimony Impact</div></div>`;
        html += '</div>';
        if (d.charge_categories?.length) {
            html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-bottom:0.4rem;">By Charge Category:</div>';
            d.charge_categories.forEach(c => {
                html += `<div style="display:grid;grid-template-columns:1fr auto auto;gap:0.4rem;align-items:center;padding:0.25rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">`;
                html += `<div style="font-size:0.73rem;color:#e2e8f0;">${c.category}</div>`;
                html += `<div style="font-size:0.7rem;color:#94a3b8;">${c.avg_sentence_years}y avg</div>`;
                html += `<div style="font-size:0.7rem;background:rgba(255,255,255,0.06);color:#cbd5e1;border-radius:4px;padding:0.05rem 0.3rem;">Impact: ${c.testimony_impact}%</div>`;
                html += '</div>';
            });
        }
        if (d.testimony_impact_factors?.length) {
            html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin:0.6rem 0 0.3rem;">Testimony Impact Factors:</div>';
            d.testimony_impact_factors.forEach(f => {
                const inc = f.avg_sentence_increase_pct;
                const color = inc > 0 ? '#f87171' : '#4ade80';
                html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:0.2rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">`;
                html += `<div style="font-size:0.72rem;color:#e2e8f0;">${f.factor}</div>`;
                html += `<div style="font-size:0.7rem;color:${color};font-weight:600;">${inc > 0 ? '+' : ''}${inc}%</div>`;
                html += '</div>';
            });
        }
        if (d.insights?.length) {
            html += '<div style="margin-top:0.6rem;">';
            d.insights.forEach(i => { html += `<div style="font-size:0.7rem;color:#64748b;padding:0.1rem 0;">• ${i}</div>`; });
            html += '</div>';
        }
        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Load error: ${e.message}</p>`; }
}

// ── Corroboration Health Dashboard ────────────────────────────────────────
async function loadCorroborationHealthPanel() {
    const el = document.getElementById('corroboration-health-content');
    if (!el) return;
    try {
        const token = getAdminToken();
        const r = await fetch('/api/admin/corroboration-health', { headers: { 'Authorization': 'Bearer ' + token } });
        const d = await r.json();
        if (!r.ok) { el.innerHTML = `<p class="error-msg">${d.detail || 'Error'}</p>`; return; }
        let html = `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.5rem;margin-bottom:0.8rem;">`;
        html += `<div class="stat-box"><div class="stat-val">${d.overall_corroboration_health}/100</div><div class="stat-lbl">Health Score</div></div>`;
        html += `<div class="stat-box"><div class="stat-val">${d.fully_corroborated_pct}%</div><div class="stat-lbl">Fully Corroborated</div></div>`;
        html += `<div class="stat-box"><div class="stat-val stat-val-warn">${d.uncorroborated_pct}%</div><div class="stat-lbl">Uncorroborated</div></div>`;
        html += '</div>';
        if (d.evidence_type_breakdown?.length) {
            html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-bottom:0.4rem;">Evidence Type Performance:</div>';
            d.evidence_type_breakdown.forEach(t => {
                html += `<div style="margin-bottom:0.3rem;">`;
                html += `<div style="display:flex;justify-content:space-between;font-size:0.72rem;margin-bottom:0.1rem;">`;
                html += `<span style="color:#e2e8f0;">${t.icon} ${t.type}</span>`;
                html += `<span style="color:#94a3b8;">Corr: ${t.corroboration_rate}% | Str: ${t.avg_strength}/100</span>`;
                html += '</div>';
                html += `<div style="height:4px;background:rgba(255,255,255,0.08);border-radius:2px;"><div style="height:100%;width:${t.avg_strength}%;background:#22d3ee;border-radius:2px;"></div></div>`;
                html += '</div>';
            });
        }
        if (d.corroboration_health_distribution?.length) {
            html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin:0.6rem 0 0.3rem;">Distribution:</div>';
            d.corroboration_health_distribution.forEach(h => {
                html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:0.2rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">`;
                html += `<div style="font-size:0.7rem;color:#e2e8f0;">${h.level}</div>`;
                html += `<div style="font-size:0.7rem;color:${h.color};font-weight:600;">${h.count} (${h.pct}%)</div>`;
                html += '</div>';
            });
        }
        if (d.insights?.length) {
            html += '<div style="margin-top:0.6rem;">';
            d.insights.forEach(i => { html += `<div style="font-size:0.7rem;color:#64748b;padding:0.1rem 0;">• ${i}</div>`; });
            html += '</div>';
        }
        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Load error: ${e.message}</p>`; }
}

document.getElementById('sentencing-analytics-refresh')?.addEventListener('click', loadSentencingAnalyticsPanel);
document.getElementById('corroboration-health-refresh')?.addEventListener('click', loadCorroborationHealthPanel);
setTimeout(loadSentencingAnalyticsPanel, 21500);
setTimeout(loadCorroborationHealthPanel, 23000);

// ── Trial Outcome Analytics ──────────────────────────────────────────────────
async function loadTrialOutcomesPanel() {
    const el = document.getElementById('trial-outcomes-content');
    if (!el) return;
    try {
        const token = getAdminToken();
        const resp = await fetch('/api/admin/trial-outcomes', { headers: { 'Authorization': 'Bearer ' + token } });
        const d = await resp.json();
        let html = `<div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:0.8rem;">`;
        html += `<div style="background:rgba(34,197,94,0.1);border:1px solid #22c55e;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#22c55e;">${d.overall_conviction_rate}%</div><div style="font-size:0.68rem;color:#94a3b8;">Conviction Rate</div></div>`;
        html += `<div style="background:rgba(239,68,68,0.1);border:1px solid #ef4444;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#ef4444;">${d.acquittal_rate}%</div><div style="font-size:0.68rem;color:#94a3b8;">Acquittal Rate</div></div>`;
        html += `<div style="background:rgba(234,179,8,0.1);border:1px solid #eab308;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#eab308;">${d.hung_jury_rate}%</div><div style="font-size:0.68rem;color:#94a3b8;">Hung Jury</div></div>`;
        html += `<div style="background:rgba(59,130,246,0.1);border:1px solid #3b82f6;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#3b82f6;">${d.total_cases_tracked}</div><div style="font-size:0.68rem;color:#94a3b8;">Total Cases</div></div>`;
        html += '</div>';
        if (d.verdict_breakdown?.length) {
            html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-bottom:0.3rem;">Verdict Breakdown:</div>';
            d.verdict_breakdown.forEach(v => {
                html += `<div style="margin-bottom:0.3rem;">`;
                html += `<div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:0.1rem;">`;
                html += `<span style="color:#e2e8f0;">${v.verdict}</span><span style="color:${v.color};font-weight:600;">${v.count} (${v.pct}%)</span>`;
                html += '</div>';
                html += `<div style="height:5px;background:rgba(255,255,255,0.08);border-radius:3px;"><div style="height:100%;width:${v.pct}%;background:${v.color};border-radius:3px;"></div></div>`;
                html += '</div>';
            });
        }
        if (d.by_charge_type?.length) {
            html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin:0.6rem 0 0.3rem;">By Charge Type:</div>';
            d.by_charge_type.forEach(c => {
                html += `<div style="display:flex;justify-content:space-between;font-size:0.7rem;padding:0.2rem 0;border-bottom:1px solid rgba(255,255,255,0.05);">`;
                html += `<span style="color:#e2e8f0;">${c.charge_type}</span>`;
                html += `<span style="color:#22d3ee;">${c.conviction_rate}% conv. | ${c.cases} cases</span>`;
                html += '</div>';
            });
        }
        const ti = d.testimony_impact_on_outcome;
        if (ti) {
            html += `<div style="margin-top:0.6rem;padding:0.5rem;background:rgba(255,255,255,0.03);border-radius:6px;border:1px solid rgba(255,255,255,0.07);">`;
            html += `<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-bottom:0.25rem;">Testimony Impact on Conviction:</div>`;
            html += `<div style="font-size:0.7rem;color:#e2e8f0;">High-Credibility: <b style="color:#22c55e;">${ti.high_credibility_conviction_rate}%</b> | Low-Credibility: <b style="color:#ef4444;">${ti.low_credibility_conviction_rate}%</b></div>`;
            html += `<div style="font-size:0.7rem;color:#94a3b8;margin-top:0.2rem;">Credibility Swing Factor: ±${ti.credibility_swing_factor}%</div>`;
            html += '</div>';
        }
        if (d.insights?.length) {
            html += '<div style="margin-top:0.5rem;">';
            d.insights.forEach(i => { html += `<div style="font-size:0.68rem;color:#64748b;padding:0.1rem 0;">• ${i}</div>`; });
            html += '</div>';
        }
        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Load error: ${e.message}</p>`; }
}

// ── Case Velocity Dashboard ──────────────────────────────────────────────────
async function loadCaseVelocityPanel() {
    const el = document.getElementById('case-velocity-content');
    if (!el) return;
    try {
        const token = getAdminToken();
        const resp = await fetch('/api/admin/case-velocity', { headers: { 'Authorization': 'Bearer ' + token } });
        const d = await resp.json();
        const tp = d.throughput;
        let html = `<div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:0.8rem;">`;
        html += `<div style="background:rgba(34,211,238,0.1);border:1px solid #22d3ee;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#22d3ee;">${d.avg_end_to_end_days}d</div><div style="font-size:0.68rem;color:#94a3b8;">Avg Cycle Time</div></div>`;
        html += `<div style="background:rgba(249,115,22,0.1);border:1px solid #f97316;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#f97316;">${tp?.on_time_delivery_rate}%</div><div style="font-size:0.68rem;color:#94a3b8;">On-Time Rate</div></div>`;
        html += `<div style="background:rgba(139,92,246,0.1);border:1px solid #8b5cf6;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#8b5cf6;">${tp?.cases_per_week_avg}</div><div style="font-size:0.68rem;color:#94a3b8;">Cases/Week</div></div>`;
        html += `<div style="background:rgba(239,68,68,0.1);border:1px solid #ef4444;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#ef4444;">${tp?.current_backlog}</div><div style="font-size:0.68rem;color:#94a3b8;">Backlog</div></div>`;
        html += '</div>';
        if (d.pipeline_stages?.length) {
            html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-bottom:0.3rem;">Pipeline Stages:</div>';
            d.pipeline_stages.forEach(s => {
                const riskColor = s.bottleneck_risk === 'High' ? '#ef4444' : s.bottleneck_risk === 'Medium' ? '#f97316' : '#22c55e';
                html += `<div style="margin-bottom:0.35rem;padding:0.3rem 0.5rem;background:rgba(255,255,255,0.03);border-left:3px solid ${riskColor};border-radius:3px;">`;
                html += `<div style="display:flex;justify-content:space-between;font-size:0.7rem;"><span style="color:#e2e8f0;">${s.stage}</span><span style="color:${riskColor};">${s.bottleneck_risk}</span></div>`;
                html += `<div style="font-size:0.67rem;color:#94a3b8;">Avg: ${s.avg_hours}h | p95: ${s.p95_hours}h</div>`;
                html += '</div>';
            });
        }
        const sla = d.sla_compliance;
        if (sla) {
            html += `<div style="margin-top:0.4rem;padding:0.4rem 0.6rem;background:rgba(255,255,255,0.03);border-radius:6px;border:1px solid rgba(255,255,255,0.07);">`;
            html += `<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-bottom:0.2rem;">SLA Compliance (target: ${sla.sla_target_days}d):</div>`;
            html += `<div style="font-size:0.7rem;color:#e2e8f0;">Within SLA: <b style="color:#22c55e;">${sla.within_sla_pct}%</b> | Breaches: <b style="color:#ef4444;">${sla.breached_sla_count}</b> | Avg breach: ${sla.avg_breach_days}d</div>`;
            html += '</div>';
        }
        if (d.recommendations?.length) {
            html += '<div style="margin-top:0.5rem;"><div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-bottom:0.2rem;">Recommendations:</div>';
            d.recommendations.forEach(r => { html += `<div style="font-size:0.68rem;color:#64748b;padding:0.1rem 0;">• ${r}</div>`; });
            html += '</div>';
        }
        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Load error: ${e.message}</p>`; }
}

document.getElementById('trial-outcomes-refresh')?.addEventListener('click', loadTrialOutcomesPanel);
document.getElementById('case-velocity-refresh')?.addEventListener('click', loadCaseVelocityPanel);
setTimeout(loadTrialOutcomesPanel, 24500);
setTimeout(loadCaseVelocityPanel, 26000);

// ── Witness Network Analysis ─────────────────────────────────────────────────
async function loadWitnessNetworkPanel() {
    const el = document.getElementById('witness-network-content');
    if (!el) return;
    try {
        const token = getAdminToken();
        const resp = await fetch('/api/admin/witness-network', { headers: { 'Authorization': 'Bearer ' + token } });
        const d = await resp.json();
        let html = `<div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:0.8rem;">`;
        html += `<div style="background:rgba(99,179,237,0.1);border:1px solid #63b3ed;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#63b3ed;">${d.total_witnesses_tracked}</div><div style="font-size:0.68rem;color:#94a3b8;">Witnesses</div></div>`;
        html += `<div style="background:rgba(246,173,85,0.1);border:1px solid #f6ad55;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#f6ad55;">${d.total_relationships_mapped}</div><div style="font-size:0.68rem;color:#94a3b8;">Relationships</div></div>`;
        html += `<div style="background:rgba(104,211,145,0.1);border:1px solid #68d391;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#68d391;">${(d.clustering_coefficient * 100).toFixed(0)}%</div><div style="font-size:0.68rem;color:#94a3b8;">Clustering</div></div>`;
        const riskColor = d.network_health?.coaching_cluster_risk === 'High' ? '#ef4444' : (d.network_health?.coaching_cluster_risk === 'Medium' ? '#f6ad55' : '#22c55e');
        html += `<div style="background:rgba(239,68,68,0.1);border:1px solid ${riskColor};border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:${riskColor};">${d.network_health?.coaching_cluster_risk}</div><div style="font-size:0.68rem;color:#94a3b8;">Coaching Risk</div></div>`;
        html += '</div>';
        if (d.witness_clusters?.length) {
            html += '<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-bottom:0.3rem;">Witness Clusters:</div>';
            d.witness_clusters.forEach(c => {
                const posColor = c.dominant_type === 'Prosecution' ? '#63b3ed' : (c.dominant_type === 'Defense' ? '#fc8181' : '#a0aec0');
                html += `<div style="margin-bottom:0.35rem;padding:0.3rem 0.5rem;background:rgba(255,255,255,0.03);border-left:3px solid ${posColor};border-radius:3px;">`;
                html += `<div style="display:flex;justify-content:space-between;font-size:0.7rem;"><span style="color:#e2e8f0;">${c.cluster_id} (${c.witness_count} witnesses)</span><span style="color:${posColor};">${c.dominant_type}</span></div>`;
                html += `<div style="font-size:0.67rem;color:#94a3b8;">Alignment: ${c.avg_alignment}% | Coherence: ${c.coherence_score}</div>`;
                html += '</div>';
            });
        }
        if (d.contradiction_pairs?.length) {
            html += '<div style="margin-top:0.4rem;font-size:0.72rem;font-weight:600;color:#fc8181;margin-bottom:0.3rem;">Contradiction Pairs:</div>';
            d.contradiction_pairs.forEach(p => {
                html += `<div style="font-size:0.7rem;color:#e2e8f0;padding:0.2rem 0.4rem;background:rgba(252,129,129,0.07);border-radius:4px;margin-bottom:0.2rem;">`;
                html += `⚡ ${p.pair[0]} ↔ ${p.pair[1]} — ${p.topic} (conflict: ${p.conflict_score})`;
                html += '</div>';
            });
        }
        const nh = d.network_health;
        if (nh) {
            html += `<div style="margin-top:0.4rem;padding:0.4rem 0.6rem;background:rgba(255,255,255,0.03);border-radius:6px;border:1px solid rgba(255,255,255,0.07);">`;
            html += `<div style="font-size:0.7rem;color:#e2e8f0;">Coherence: <b style="color:#68d391;">${nh.coherence_rate}%</b> | Contradictions: <b style="color:#fc8181;">${nh.contradiction_rate}%</b> | Independent: <b style="color:#63b3ed;">${nh.independent_testimony_pct}%</b></div>`;
            html += '</div>';
        }
        if (d.insights?.length) {
            html += '<div style="margin-top:0.5rem;">';
            d.insights.forEach(i => { html += `<div style="font-size:0.68rem;color:#64748b;padding:0.1rem 0;">• ${i}</div>`; });
            html += '</div>';
        }
        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Load error: ${e.message}</p>`; }
}

// ── Case Outcome Predictor ────────────────────────────────────────────────────
async function loadOutcomePredictorPanel() {
    const el = document.getElementById('outcome-predictor-content');
    if (!el) return;
    try {
        const token = getAdminToken();
        const resp = await fetch('/api/admin/outcome-predictor', { headers: { 'Authorization': 'Bearer ' + token } });
        const d = await resp.json();
        let html = `<div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:0.8rem;">`;
        html += `<div style="background:rgba(139,92,246,0.1);border:1px solid #8b5cf6;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#8b5cf6;">${d.model_accuracy_rate}%</div><div style="font-size:0.68rem;color:#94a3b8;">Model Accuracy</div></div>`;
        html += `<div style="background:rgba(34,211,238,0.1);border:1px solid #22d3ee;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#22d3ee;">${d.overall_predicted_conviction_rate}%</div><div style="font-size:0.68rem;color:#94a3b8;">Conviction Rate</div></div>`;
        html += `<div style="background:rgba(104,211,145,0.1);border:1px solid #68d391;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#68d391;">${d.total_predictions_made}</div><div style="font-size:0.68rem;color:#94a3b8;">Total Predictions</div></div>`;
        html += `<div style="background:rgba(249,115,22,0.1);border:1px solid #f97316;border-radius:6px;padding:0.5rem 0.9rem;flex:1;text-align:center;">`;
        html += `<div style="font-size:1.3rem;font-weight:700;color:#f97316;">${d.prediction_confidence_avg}%</div><div style="font-size:0.68rem;color:#94a3b8;">Avg Confidence</div></div>`;
        html += '</div>';
        html += `<div style="font-size:0.72rem;font-weight:600;color:#94a3b8;margin-bottom:0.3rem;">Top Prediction Drivers:</div>`;
        (d.predictor_weights || []).forEach(p => {
            const corrColor = p.conviction_correlation > 0 ? '#68d391' : '#fc8181';
            const wPct = Math.round(p.weight * 100);
            html += `<div style="margin-bottom:0.35rem;padding:0.3rem 0.5rem;background:rgba(255,255,255,0.03);border-radius:3px;display:flex;align-items:center;gap:8px;">`;
            html += `<div style="min-width:8px;height:8px;border-radius:50%;background:${corrColor};"></div>`;
            html += `<div style="flex:1;font-size:0.7rem;color:#e2e8f0;">${p.predictor}</div>`;
            html += `<div style="font-size:0.68rem;color:#94a3b8;">w:${wPct}%</div>`;
            html += `<div style="font-size:0.68rem;color:${corrColor};">r=${p.conviction_correlation.toFixed(2)}</div>`;
            html += '</div>';
        });
        if (d.by_charge_type_predictions?.length) {
            html += '<div style="margin-top:0.5rem;font-size:0.72rem;font-weight:600;color:#94a3b8;margin-bottom:0.3rem;">By Charge Type:</div>';
            d.by_charge_type_predictions.forEach(c => {
                html += `<div style="font-size:0.7rem;display:flex;justify-content:space-between;padding:0.2rem 0.4rem;border-bottom:1px solid rgba(255,255,255,0.05);">`;
                html += `<span style="color:#e2e8f0;">${c.charge_type}</span>`;
                html += `<span style="color:#22d3ee;">${c.predicted_conviction_rate}%</span>`;
                html += `<span style="color:#8b5cf6;">${c.model_confidence}% conf</span>`;
                html += '</div>';
            });
        }
        html += `<div style="margin-top:0.4rem;font-size:0.72rem;color:#94a3b8;">Most impactful: <b style="color:#8b5cf6;">${d.most_impactful_predictor}</b></div>`;
        if (d.model_insights?.length) {
            html += '<div style="margin-top:0.5rem;">';
            d.model_insights.forEach(i => { html += `<div style="font-size:0.68rem;color:#64748b;padding:0.1rem 0;">• ${i}</div>`; });
            html += '</div>';
        }
        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Load error: ${e.message}</p>`; }
}

document.getElementById('witness-network-refresh')?.addEventListener('click', loadWitnessNetworkPanel);
document.getElementById('outcome-predictor-refresh')?.addEventListener('click', loadOutcomePredictorPanel);
setTimeout(loadWitnessNetworkPanel, 27500);
setTimeout(loadOutcomePredictorPanel, 29000);

// ── Admin: Witness Reliability Trends ────────────────────────────────────────
async function loadReliabilityTrendsPanel() {
    const el = document.getElementById('reliability-trends-content');
    if (!el) return;
    const token = localStorage.getItem('admin_token') || '';
    try {
        const resp = await fetch('/api/admin/reliability-trends', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!resp.ok) { el.innerHTML = '<p class="error-msg">⚠️ Auth required</p>'; return; }
        const d = await resp.json();
        const trendColor = d.reliability_trend === 'Improving' ? '#68d391' : '#fc8181';

        let html = `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">`;
        html += `<div class="stat-card"><div class="stat-value" style="color:#a78bfa;">${d.overall_avg_reliability}</div><div class="stat-label">Avg Reliability Score</div></div>`;
        html += `<div class="stat-card"><div class="stat-value" style="color:#63b3ed;">${d.total_witnesses_assessed.toLocaleString()}</div><div class="stat-label">Witnesses Assessed</div></div>`;
        html += `<div class="stat-card"><div class="stat-value" style="color:${trendColor};">${d.reliability_trend}</div><div class="stat-label">12-Week Trend</div></div>`;
        html += '</div>';

        // Score band distribution
        html += '<div style="margin-bottom:16px;"><div style="font-size:0.8rem;font-weight:700;color:#a78bfa;margin-bottom:8px;">RELIABILITY SCORE DISTRIBUTION</div>';
        d.score_band_distribution.forEach(band => {
            const pct = band.pct;
            const barColor = band.band.includes('Highly') ? '#68d391' : (band.band.includes('Reliable') ? '#a78bfa' : (band.band.includes('Question') ? '#f6ad55' : '#fc8181'));
            html += `<div style="display:flex;align-items:center;gap:10px;margin-bottom:7px;">`;
            html += `<div style="min-width:200px;font-size:0.78rem;color:#a0aec0;">${band.band}</div>`;
            html += `<div style="flex:1;height:10px;background:#2d3748;border-radius:5px;overflow:hidden;"><div style="width:${pct}%;height:100%;background:${barColor};border-radius:5px;"></div></div>`;
            html += `<div style="min-width:55px;font-size:0.78rem;color:#e2e8f0;text-align:right;">${band.count} (${pct}%)</div>`;
            html += '</div>';
        });
        html += '</div>';

        // By case type
        html += '<div style="margin-bottom:16px;"><div style="font-size:0.8rem;font-weight:700;color:#63b3ed;margin-bottom:8px;">RELIABILITY BY CASE TYPE</div>';
        d.reliability_by_case_type.forEach(ct => {
            const scColor = ct.avg_score >= 70 ? '#68d391' : (ct.avg_score >= 55 ? '#f6ad55' : '#fc8181');
            html += `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;padding:8px;background:rgba(255,255,255,0.03);border-radius:6px;">`;
            html += `<span style="font-size:0.8rem;color:#a0aec0;">${ct.case_type}</span>`;
            html += `<div style="display:flex;align-items:center;gap:10px;"><span style="font-size:0.75rem;color:#718096;">n=${ct.sample_size}</span><span style="font-weight:700;color:${scColor};font-size:0.9rem;">${ct.avg_score}</span></div>`;
            html += '</div>';
        });
        html += '</div>';

        // Risk factors
        if (d.reliability_risk_factors?.length) {
            html += '<div style="font-size:0.8rem;font-weight:700;color:#fc8181;margin-bottom:8px;">RISK FACTORS</div>';
            d.reliability_risk_factors.forEach(f => { html += `<div style="font-size:0.78rem;color:#a0aec0;margin-bottom:5px;padding:6px;background:rgba(252,129,129,0.06);border-radius:6px;">⚠️ ${f}</div>`; });
        }

        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Error: ${e.message}</p>`; }
}

// ── Admin: Evidence Quality Dashboard ────────────────────────────────────────
async function loadEvidenceQualityPanel() {
    const el = document.getElementById('evidence-quality-content');
    if (!el) return;
    const token = localStorage.getItem('admin_token') || '';
    try {
        const resp = await fetch('/api/admin/evidence-quality', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!resp.ok) { el.innerHTML = '<p class="error-msg">⚠️ Auth required</p>'; return; }
        const d = await resp.json();

        let html = `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">`;
        html += `<div class="stat-card"><div class="stat-value" style="color:#68d391;">${d.overall_evidence_quality_score}</div><div class="stat-label">Quality Score</div></div>`;
        html += `<div class="stat-card"><div class="stat-value" style="color:#63b3ed;">${d.total_evidence_items.toLocaleString()}</div><div class="stat-label">Total Evidence Items</div></div>`;
        html += `<div class="stat-card"><div class="stat-value" style="color:${d.critical_issues_count > 0 ? '#fc8181' : '#68d391'};">${d.critical_issues_count}</div><div class="stat-label">Critical Issues</div></div>`;
        html += '</div>';

        // Evidence by type
        html += '<div style="margin-bottom:16px;"><div style="font-size:0.8rem;font-weight:700;color:#68d391;margin-bottom:8px;">EVIDENCE QUALITY BY TYPE</div>';
        d.evidence_by_type.forEach(et => {
            const qColor = et.avg_quality >= 75 ? '#68d391' : (et.avg_quality >= 60 ? '#f6ad55' : '#fc8181');
            html += `<div style="margin-bottom:9px;padding:10px;background:rgba(104,211,145,0.06);border-radius:8px;">`;
            html += `<div style="display:flex;justify-content:space-between;margin-bottom:5px;">`;
            html += `<span style="font-size:0.82rem;color:#e2e8f0;font-weight:600;">${et.icon} ${et.type}</span>`;
            html += `<div style="display:flex;gap:10px;"><span style="font-size:0.75rem;color:#718096;">${et.total_items} items</span><span style="font-weight:700;color:${qColor};">${et.avg_quality}</span></div></div>`;
            html += `<div style="height:6px;background:#2d3748;border-radius:3px;overflow:hidden;"><div style="width:${et.avg_quality}%;height:100%;background:${qColor};border-radius:3px;"></div></div>`;
            html += `<div style="font-size:0.72rem;color:#718096;margin-top:4px;">Admissibility: ${et.admissibility_rate}%</div>`;
            html += '</div>';
        });
        html += '</div>';

        // Chain of custody issues
        if (d.chain_of_custody_issues?.length) {
            html += '<div style="margin-bottom:14px;"><div style="font-size:0.8rem;font-weight:700;color:#fc8181;margin-bottom:8px;">CHAIN OF CUSTODY ISSUES</div>';
            d.chain_of_custody_issues.forEach(issue => {
                const sevColor = issue.severity === 'Critical' ? '#fc8181' : (issue.severity === 'High' ? '#f6ad55' : '#a0aec0');
                html += `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;padding:7px 10px;background:rgba(252,129,129,0.06);border-radius:6px;">`;
                html += `<span style="font-size:0.8rem;color:#a0aec0;">${issue.issue}</span>`;
                html += `<div style="display:flex;gap:8px;align-items:center;"><span style="font-size:0.75rem;color:#718096;">${issue.frequency}x</span><span style="font-size:0.72rem;padding:2px 7px;border-radius:4px;background:rgba(252,129,129,0.1);color:${sevColor};font-weight:700;">${issue.severity}</span></div>`;
                html += '</div>';
            });
            html += '</div>';
        }

        // Suppression risks
        if (d.top_suppression_risks?.length) {
            html += '<div style="font-size:0.8rem;font-weight:700;color:#f6ad55;margin-bottom:8px;">TOP SUPPRESSION RISKS</div>';
            d.top_suppression_risks.forEach(risk => { html += `<div style="font-size:0.78rem;color:#a0aec0;margin-bottom:5px;padding:6px;background:rgba(246,173,85,0.06);border-radius:6px;">⚠️ ${risk}</div>`; });
        }

        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Error: ${e.message}</p>`; }
}

document.getElementById('reliability-trends-refresh')?.addEventListener('click', loadReliabilityTrendsPanel);
document.getElementById('evidence-quality-refresh')?.addEventListener('click', loadEvidenceQualityPanel);
setTimeout(loadReliabilityTrendsPanel, 30500);
setTimeout(loadEvidenceQualityPanel, 32000);

// ── Settlement Analytics Panel ────────────────────────────────────────────────
async function loadSettlementAnalyticsPanel() {
    const el = document.getElementById('settlement-analytics-content');
    if (!el) return;
    try {
        const resp = await fetch('/api/admin/settlement-analytics', { headers: getAuthHeaders() });
        if (!resp.ok) { el.innerHTML = '<p class="error-msg">Unauthorized</p>'; return; }
        const d = await resp.json();
        const trendColor = d.settlement_trend === 'Rising' ? '#68d391' : '#fc8181';
        let html = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;">`;
        html += `<div class="admin-stat-card"><div class="stat-value" style="color:#63b3ed;">${d.overall_settlement_rate_pct}%</div><div class="stat-label">Settlement Rate</div></div>`;
        html += `<div class="admin-stat-card"><div class="stat-value" style="color:#68d391;">$${d.avg_settlement_value_k}k</div><div class="stat-label">Avg. Value</div></div>`;
        html += `<div class="admin-stat-card"><div class="stat-value" style="color:#f6ad55;">${d.total_settled_cases}</div><div class="stat-label">Settled</div></div>`;
        html += `<div class="admin-stat-card"><div class="stat-value" style="color:${trendColor};">${d.settlement_trend}</div><div class="stat-label">Trend</div></div>`;
        html += '</div>';

        // By case type
        html += '<div style="font-size:0.8rem;font-weight:700;color:#63b3ed;margin-bottom:8px;">SETTLEMENT BY CASE TYPE</div>';
        (d.by_case_type || []).forEach(ct => {
            const rateColor = ct.settlement_rate_pct >= 65 ? '#68d391' : (ct.settlement_rate_pct >= 40 ? '#f6ad55' : '#fc8181');
            html += `<div style="display:flex;align-items:center;gap:8px;margin-bottom:7px;">`;
            html += `<div style="min-width:160px;font-size:0.78rem;color:#e2e8f0;">${ct.case_type}</div>`;
            html += `<div style="flex:1;height:6px;background:#2d3748;border-radius:3px;"><div style="width:${ct.settlement_rate_pct}%;height:100%;background:${rateColor};border-radius:3px;"></div></div>`;
            html += `<span style="font-size:0.75rem;color:${rateColor};min-width:35px;">${ct.settlement_rate_pct}%</span>`;
            html += `<span style="font-size:0.72rem;color:#718096;min-width:65px;">$${ct.avg_value_k}k avg</span>`;
            html += '</div>';
        });

        // Settlement pressure factors
        html += '<div style="font-size:0.8rem;font-weight:700;color:#b794f4;margin:12px 0 8px;">SETTLEMENT PRESSURE FACTORS</div>';
        (d.settlement_pressure_factors || []).forEach(f => {
            const impColor = f.impact === 'High' ? '#fc8181' : (f.impact === 'Medium' ? '#f6ad55' : '#718096');
            html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.78rem;">`;
            html += `<span style="color:#e2e8f0;">${f.factor}</span>`;
            html += `<div style="display:flex;gap:8px;align-items:center;"><span style="color:${impColor};">${f.impact}</span><span style="color:#63b3ed;">+${f.settlement_push_pct}%</span></div>`;
            html += '</div>';
        });

        // Key insights
        if (d.key_insights?.length) {
            html += '<div style="font-size:0.8rem;font-weight:700;color:#f6ad55;margin:12px 0 8px;">KEY INSIGHTS</div>';
            d.key_insights.forEach(i => { html += `<div style="font-size:0.78rem;color:#a0aec0;margin-bottom:5px;padding:6px;background:rgba(246,173,85,0.06);border-radius:6px;">💡 ${i}</div>`; });
        }

        html += `<div style="font-size:0.75rem;color:#718096;margin-top:10px;">Mediation Success: ${d.mediation_success_rate_pct}% · Pre-trial Window: ${d.pre_trial_settlement_window_days}d · High-Value Cases: ${d.high_value_settlement_count}</div>`;
        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Error: ${e.message}</p>`; }
}

// ── Deposition Quality Panel ──────────────────────────────────────────────────
async function loadDepositionQualityPanel() {
    const el = document.getElementById('deposition-quality-content');
    if (!el) return;
    try {
        const resp = await fetch('/api/admin/deposition-quality', { headers: getAuthHeaders() });
        if (!resp.ok) { el.innerHTML = '<p class="error-msg">Unauthorized</p>'; return; }
        const d = await resp.json();
        const qualColor = d.overall_deposition_quality_score >= 80 ? '#68d391' : (d.overall_deposition_quality_score >= 65 ? '#63b3ed' : (d.overall_deposition_quality_score >= 50 ? '#f6ad55' : '#fc8181'));
        let html = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;">`;
        html += `<div class="admin-stat-card"><div class="stat-value" style="color:${qualColor};">${d.overall_deposition_quality_score}</div><div class="stat-label">Quality Score</div></div>`;
        html += `<div class="admin-stat-card"><div class="stat-value" style="color:#63b3ed;">${d.quality_rating}</div><div class="stat-label">Rating</div></div>`;
        html += `<div class="admin-stat-card"><div class="stat-value" style="color:#b794f4;">${d.total_depositions_analyzed}</div><div class="stat-label">Analyzed</div></div>`;
        html += `<div class="admin-stat-card"><div class="stat-value" style="color:#fc8181;">${d.critical_deficiency_count}</div><div class="stat-label">Critical Issues</div></div>`;
        html += '</div>';

        // Quality dimensions
        html += '<div style="font-size:0.8rem;font-weight:700;color:#63b3ed;margin-bottom:8px;">QUALITY DIMENSIONS</div>';
        (d.quality_dimensions || []).forEach(dim => {
            const dc = dim.avg_score >= 75 ? '#68d391' : (dim.avg_score >= 55 ? '#f6ad55' : '#fc8181');
            const trendIcon = dim.trend === 'Up' ? '↑' : (dim.trend === 'Down' ? '↓' : '→');
            const trendColor = dim.trend === 'Up' ? '#68d391' : (dim.trend === 'Down' ? '#fc8181' : '#718096');
            html += `<div style="margin-bottom:7px;"><div style="display:flex;justify-content:space-between;font-size:0.78rem;margin-bottom:3px;">`;
            html += `<span style="color:#e2e8f0;">${dim.dimension} <span style="color:${trendColor};">${trendIcon}</span></span><span style="color:${dc};">${dim.avg_score}</span></div>`;
            html += `<div style="height:5px;background:#2d3748;border-radius:3px;"><div style="width:${dim.avg_score}%;height:100%;background:${dc};border-radius:3px;"></div></div></div>`;
        });

        // Attorney performance
        html += '<div style="font-size:0.8rem;font-weight:700;color:#b794f4;margin:12px 0 8px;">ATTORNEY PERFORMANCE (Top: ${d.top_attorney})</div>';
        (d.attorney_performance || []).forEach(a => {
            const ac = a.avg_quality >= 75 ? '#68d391' : (a.avg_quality >= 55 ? '#f6ad55' : '#fc8181');
            html += `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;font-size:0.78rem;">`;
            html += `<span style="color:#e2e8f0;">${a.attorney}</span>`;
            html += `<div style="display:flex;gap:10px;"><span style="color:${ac};">${a.avg_quality} qual</span><span style="color:#718096;">${a.depositions} deps</span><span style="color:#a0aec0;">${a.objections_sustained_pct}% sustained</span></div>`;
            html += '</div>';
        });

        // Common deficiencies
        html += '<div style="font-size:0.8rem;font-weight:700;color:#fc8181;margin:12px 0 8px;">COMMON DEFICIENCIES</div>';
        (d.common_deficiencies || []).forEach(def => {
            const sevColor = def.severity === 'Critical' ? '#fc8181' : (def.severity === 'High' ? '#f6ad55' : '#a0aec0');
            html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.78rem;">`;
            html += `<span style="color:#e2e8f0;">${def.deficiency}</span>`;
            html += `<div style="display:flex;gap:8px;"><span style="color:#718096;">${def.frequency}x</span><span style="font-size:0.72rem;padding:2px 7px;border-radius:4px;background:rgba(252,129,129,0.08);color:${sevColor};font-weight:700;">${def.severity}</span></div>`;
            html += '</div>';
        });

        // Recommendations
        if (d.quality_improvement_recommendations?.length) {
            html += '<div style="font-size:0.8rem;font-weight:700;color:#68d391;margin:12px 0 8px;">RECOMMENDATIONS</div>';
            d.quality_improvement_recommendations.forEach(rec => { html += `<div style="font-size:0.78rem;color:#a0aec0;margin-bottom:5px;padding:6px;background:rgba(104,211,145,0.06);border-radius:6px;">✅ ${rec}</div>`; });
        }

        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Error: ${e.message}</p>`; }
}

document.getElementById('settlement-analytics-refresh')?.addEventListener('click', loadSettlementAnalyticsPanel);
document.getElementById('deposition-quality-refresh')?.addEventListener('click', loadDepositionQualityPanel);
setTimeout(loadSettlementAnalyticsPanel, 34000);
setTimeout(loadDepositionQualityPanel, 36000);

async function loadAppealTrendsPanel() {
    const el = document.getElementById('appeal-trends-content');
    if (!el) return;
    try {
        const res = await fetch('/api/admin/appeal-trends', {headers: {'Authorization': 'Bearer ' + getAdminToken()}});
        if (!res.ok) throw new Error('Auth required');
        const d = await res.json();
        let html = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px;">`;
        html += `<div class="stat-mini"><span style="color:#fc8181;font-size:1.2rem;font-weight:800;">${d.overall_appeal_rate_pct}%</span><br><span>Appeal Rate</span></div>`;
        html += `<div class="stat-mini"><span style="color:#f6ad55;font-size:1.2rem;font-weight:800;">${d.overall_reversal_rate_pct}%</span><br><span>Reversal Rate</span></div>`;
        html += `<div class="stat-mini"><span style="color:#63b3ed;font-size:1.2rem;font-weight:800;">${d.total_cases_appealed}</span><br><span>Total Appealed</span></div>`;
        html += `<div class="stat-mini"><span style="color:#b794f4;font-size:1.2rem;font-weight:800;">${d.total_reversals}</span><br><span>Reversals</span></div>`;
        html += '</div>';

        if (d.system_alert) {
            html += `<div style="background:rgba(252,129,129,0.1);border:1px solid rgba(252,129,129,0.3);border-radius:8px;padding:8px;margin-bottom:12px;font-size:0.78rem;color:#fc8181;">⚠️ ${d.system_alert}</div>`;
        }

        html += `<div style="font-size:0.8rem;font-weight:700;color:#63b3ed;margin-bottom:8px;">WEEKLY APPEAL TREND (${d.appeal_trend})</div>`;
        html += `<div style="display:flex;gap:3px;align-items:flex-end;height:60px;margin-bottom:14px;">`;
        const maxRate = Math.max(...(d.weekly_trend||[]).map(w => w.appeal_rate_pct));
        (d.weekly_trend||[]).forEach(w => {
            const h = Math.max(8, Math.round(w.appeal_rate_pct / maxRate * 55));
            const c = w.appeal_rate_pct > 30 ? '#fc8181' : (w.appeal_rate_pct > 20 ? '#f6ad55' : '#68d391');
            html += `<div title="${w.week}: ${w.appeal_rate_pct}% appeals, ${w.reversal_rate_pct}% reversals" style="flex:1;height:${h}px;background:${c};border-radius:2px 2px 0 0;min-width:6px;"></div>`;
        });
        html += '</div>';

        html += `<div style="font-size:0.8rem;font-weight:700;color:#b794f4;margin-bottom:8px;">APPEAL GROUNDS (Most Common: ${d.most_common_ground})</div>`;
        (d.by_appeal_ground||[]).forEach(g => {
            const gc = g.success_rate_pct > 40 ? '#fc8181' : (g.success_rate_pct > 25 ? '#f6ad55' : '#68d391');
            html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.78rem;">`;
            html += `<span style="color:#e2e8f0;">${g.ground}</span>`;
            html += `<div style="display:flex;gap:10px;"><span style="color:#a0aec0;">${g.frequency}x</span><span style="color:${gc};">${g.success_rate_pct}% reversal</span><span style="color:#718096;">${g.avg_duration_months}mo</span></div></div>`;
        });

        html += `<div style="font-size:0.8rem;font-weight:700;color:#f6ad55;margin:12px 0 8px;">BY CASE TYPE</div>`;
        (d.by_case_type||[]).forEach(ct => {
            const ac = ct.appeal_rate_pct > 30 ? '#fc8181' : '#a0aec0';
            html += `<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04);">`;
            html += `<span style="color:#e2e8f0;">${ct.case_type}</span>`;
            html += `<span style="color:${ac};">Appeal: ${ct.appeal_rate_pct}% · Reversal: ${ct.reversal_rate_pct}% · $${ct.avg_appellate_cost_k}k</span></div>`;
        });

        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Error: ${e.message}</p>`; }
}

async function loadComplexityOverviewPanel() {
    const el = document.getElementById('complexity-overview-content');
    if (!el) return;
    try {
        const res = await fetch('/api/admin/complexity-overview', {headers: {'Authorization': 'Bearer ' + getAdminToken()}});
        if (!res.ok) throw new Error('Auth required');
        const d = await res.json();
        let html = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px;">`;
        html += `<div class="stat-mini"><span style="color:#63b3ed;font-size:1.2rem;font-weight:800;">${d.total_active_cases}</span><br><span>Total Cases</span></div>`;
        html += `<div class="stat-mini"><span style="color:#f6ad55;font-size:1.2rem;font-weight:800;">${d.portfolio_avg_complexity_score}</span><br><span>Avg Complexity</span></div>`;
        html += `<div class="stat-mini"><span style="color:#9f7aea;font-size:1.2rem;font-weight:800;">${d.mega_complex_percentage}%</span><br><span>Mega-Complex</span></div>`;
        html += `<div class="stat-mini"><span style="color:#fc8181;font-size:1.2rem;font-weight:800;">${d.trend_direction}</span><br><span>Trend</span></div>`;
        html += '</div>';

        html += `<div style="font-size:0.8rem;font-weight:700;color:#63b3ed;margin-bottom:8px;">CASE DISTRIBUTION BY COMPLEXITY</div>`;
        html += `<div style="display:flex;gap:6px;margin-bottom:14px;">`;
        const totalCases = (d.complexity_distribution||[]).reduce((s,t) => s+t.case_count, 0);
        (d.complexity_distribution||[]).forEach(tier => {
            const pct = Math.round(tier.case_count / totalCases * 100);
            html += `<div style="flex:${pct};background:${tier.color};border-radius:6px;padding:8px 6px;text-align:center;min-width:40px;">`;
            html += `<div style="font-size:0.7rem;font-weight:700;color:#fff;">${tier.tier}</div>`;
            html += `<div style="font-size:1rem;font-weight:800;color:#fff;">${tier.case_count}</div>`;
            html += `<div style="font-size:0.65rem;color:rgba(255,255,255,0.8);">${pct}%</div></div>`;
        });
        html += '</div>';

        html += `<div style="font-size:0.8rem;font-weight:700;color:#b794f4;margin-bottom:8px;">COMPLEXITY TREND (${d.trend_direction})</div>`;
        html += `<div style="display:flex;gap:3px;align-items:flex-end;height:50px;margin-bottom:14px;">`;
        const maxScore = Math.max(...(d.complexity_trend||[]).map(w => w.avg_complexity_score));
        (d.complexity_trend||[]).forEach(w => {
            const h = Math.max(6, Math.round(w.avg_complexity_score / maxScore * 45));
            const c = w.avg_complexity_score > 60 ? '#fc8181' : (w.avg_complexity_score > 40 ? '#f6ad55' : '#68d391');
            html += `<div title="${w.week}: score ${w.avg_complexity_score}, ${w.new_cases} new cases" style="flex:1;height:${h}px;background:${c};border-radius:2px 2px 0 0;min-width:6px;"></div>`;
        });
        html += '</div>';

        html += `<div style="font-size:0.8rem;font-weight:700;color:#f6ad55;margin-bottom:8px;">RESOURCE PRESSURE</div>`;
        (d.resource_pressure||[]).forEach(rp => {
            const rc = rp.utilization_pct > 85 ? '#fc8181' : (rp.utilization_pct > 70 ? '#f6ad55' : '#68d391');
            html += `<div style="margin-bottom:7px;"><div style="display:flex;justify-content:space-between;font-size:0.76rem;margin-bottom:3px;">`;
            html += `<span style="color:#e2e8f0;">${rp.resource}</span><span style="color:${rc};">${rp.utilization_pct}% · Shortage: ${rp.shortage_risk}</span></div>`;
            html += `<div style="height:4px;background:#2d3748;border-radius:3px;"><div style="width:${rp.utilization_pct}%;height:100%;background:${rc};border-radius:3px;"></div></div></div>`;
        });

        html += `<div style="margin-top:10px;font-size:0.78rem;color:#718096;padding:6px;background:rgba(255,255,255,0.03);border-radius:6px;">💡 ${d.system_recommendation}</div>`;
        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Error: ${e.message}</p>`; }
}

document.getElementById('appeal-trends-refresh')?.addEventListener('click', loadAppealTrendsPanel);
document.getElementById('complexity-overview-refresh')?.addEventListener('click', loadComplexityOverviewPanel);
setTimeout(loadAppealTrendsPanel, 38000);
setTimeout(loadComplexityOverviewPanel, 40000);

async function loadRecantationMonitorPanel() {
    const el = document.getElementById('recantation-monitor-content');
    if (!el) return;
    el.innerHTML = '<p>Loading...</p>';
    try {
        const resp = await fetch('/api/admin/recantation-monitor', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('wr_token') || '') } });
        const d = await resp.json();
        let html = '';
        html += `<div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;">`;
        html += `<div style="flex:1;min-width:80px;background:rgba(252,129,129,0.08);border-radius:8px;padding:8px;text-align:center;"><div style="font-size:1.4rem;font-weight:800;color:#fc8181;">${d.currently_at_risk}</div><div style="font-size:0.68rem;color:#a0aec0;">At Risk</div></div>`;
        html += `<div style="flex:1;min-width:80px;background:rgba(252,129,129,0.12);border-radius:8px;padding:8px;text-align:center;"><div style="font-size:1.4rem;font-weight:800;color:#fc8181;">${d.critical_cases}</div><div style="font-size:0.68rem;color:#a0aec0;">Critical</div></div>`;
        html += `<div style="flex:1;min-width:80px;background:rgba(255,255,255,0.04);border-radius:8px;padding:8px;text-align:center;"><div style="font-size:1.4rem;font-weight:800;color:#e2e8f0;">${d.overall_recantation_rate_pct}%</div><div style="font-size:0.68rem;color:#a0aec0;">Recant Rate</div></div>`;
        html += `<div style="flex:1;min-width:80px;background:rgba(255,255,255,0.04);border-radius:8px;padding:8px;text-align:center;"><div style="font-size:1.4rem;font-weight:800;color:#e2e8f0;">${d.total_witnesses_monitored}</div><div style="font-size:0.68rem;color:#a0aec0;">Monitored</div></div>`;
        html += '</div>';
        html += `<div style="font-size:0.8rem;font-weight:700;color:#fc8181;margin-bottom:8px;">BY CASE TYPE</div>`;
        (d.by_case_type || []).forEach(ct => {
            const rc = ct.recantation_rate_pct > 10 ? '#fc8181' : ct.recantation_rate_pct > 6 ? '#f6ad55' : '#68d391';
            html += `<div style="margin-bottom:5px;"><div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:2px;">`;
            html += `<span style="color:#e2e8f0;">${ct.case_type}</span><span style="color:${rc};">${ct.recantation_rate_pct}% recant · ${ct.at_risk_pct}% at-risk</span></div>`;
            html += `<div style="height:3px;background:#2d3748;border-radius:2px;"><div style="width:${Math.min(ct.recantation_rate_pct * 6, 100)}%;height:100%;background:${rc};border-radius:2px;"></div></div></div>`;
        });
        html += `<div style="font-size:0.8rem;font-weight:700;color:#68d391;margin:10px 0 6px;">INTERVENTION EFFECTIVENESS</div>`;
        (d.intervention_effectiveness || []).slice(0, 4).forEach(iv => {
            const sc = iv.success_rate_pct > 70 ? '#68d391' : iv.success_rate_pct > 55 ? '#f6ad55' : '#a0aec0';
            html += `<div style="display:flex;justify-content:space-between;font-size:0.73rem;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.05);">`;
            html += `<span style="color:#e2e8f0;">${iv.intervention}</span><span style="color:${sc};">${iv.success_rate_pct}% success</span></div>`;
        });
        html += `<div style="margin-top:10px;font-size:0.75rem;color:#718096;padding:6px;background:rgba(255,255,255,0.03);border-radius:6px;">⚠️ Highest Risk: ${d.highest_risk_case_type} · Best Intervention: ${d.most_effective_intervention}</div>`;
        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Error: ${e.message}</p>`; }
}

async function loadCrossExamAnalyticsPanel() {
    const el = document.getElementById('cross-exam-analytics-content');
    if (!el) return;
    el.innerHTML = '<p>Loading...</p>';
    try {
        const resp = await fetch('/api/admin/cross-exam-analytics', { headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('wr_token') || '') } });
        const d = await resp.json();
        let html = '';
        html += `<div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;">`;
        html += `<div style="flex:1;min-width:80px;background:rgba(99,179,237,0.08);border-radius:8px;padding:8px;text-align:center;"><div style="font-size:1.4rem;font-weight:800;color:#63b3ed;">${d.avg_effectiveness_score}</div><div style="font-size:0.68rem;color:#a0aec0;">Avg Effectiveness</div></div>`;
        html += `<div style="flex:1;min-width:80px;background:rgba(255,255,255,0.04);border-radius:8px;padding:8px;text-align:center;"><div style="font-size:1.4rem;font-weight:800;color:#e2e8f0;">${d.avg_cross_exam_duration_minutes}</div><div style="font-size:0.68rem;color:#a0aec0;">Avg Minutes</div></div>`;
        html += `<div style="flex:1;min-width:80px;background:rgba(104,211,145,0.08);border-radius:8px;padding:8px;text-align:center;"><div style="font-size:1.4rem;font-weight:800;color:#68d391;">${d.successful_impeachment_rate_pct}%</div><div style="font-size:0.68rem;color:#a0aec0;">Impeachment Rate</div></div>`;
        html += `<div style="flex:1;min-width:80px;background:rgba(255,255,255,0.04);border-radius:8px;padding:8px;text-align:center;"><div style="font-size:1.4rem;font-weight:800;color:#e2e8f0;">${d.total_cross_examinations_analyzed}</div><div style="font-size:0.68rem;color:#a0aec0;">Analyzed</div></div>`;
        html += '</div>';
        html += `<div style="font-size:0.8rem;font-weight:700;color:#63b3ed;margin-bottom:8px;">PERFORMANCE BY SECTION</div>`;
        (d.by_section || []).forEach(s => {
            const sc = s.avg_effectiveness > 75 ? '#68d391' : s.avg_effectiveness > 65 ? '#f6ad55' : '#fc8181';
            html += `<div style="margin-bottom:5px;"><div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:2px;">`;
            html += `<span style="color:#e2e8f0;">${s.section}</span><span style="color:${sc};">${s.avg_effectiveness}% · ${s.avg_questions} Q's avg</span></div>`;
            html += `<div style="height:3px;background:#2d3748;border-radius:2px;"><div style="width:${s.avg_effectiveness}%;height:100%;background:${sc};border-radius:2px;"></div></div></div>`;
        });
        html += `<div style="margin-top:10px;font-size:0.75rem;color:#718096;padding:6px;background:rgba(255,255,255,0.03);border-radius:6px;">💡 ${d.system_recommendation}</div>`;
        el.innerHTML = html;
    } catch(e) { el.innerHTML = `<p class="error-msg">Error: ${e.message}</p>`; }
}

document.getElementById('recantation-monitor-refresh')?.addEventListener('click', loadRecantationMonitorPanel);
document.getElementById('cross-exam-analytics-refresh')?.addEventListener('click', loadCrossExamAnalyticsPanel);
setTimeout(loadRecantationMonitorPanel, 42000);
setTimeout(loadCrossExamAnalyticsPanel, 44000);

// ── Attorney Performance Panel ──
async function loadAttorneyPerformancePanel() {
    const el = document.getElementById('attorney-performance-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/attorney-performance', {headers:{'Authorization': 'Bearer ' + getAdminToken()}});
        if (!r.ok) throw new Error('Failed');
        const d = await r.json();
        let h = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">';
        h += `<div style="text-align:center;padding:10px;background:rgba(96,165,250,0.1);border-radius:8px;border:1px solid rgba(96,165,250,0.2);"><div style="font-size:1.6rem;font-weight:700;color:#60a5fa;">${d.total_attorneys_tracked}</div><div style="font-size:0.75rem;color:#a0aec0;">Attorneys</div></div>`;
        h += `<div style="text-align:center;padding:10px;background:rgba(74,222,128,0.1);border-radius:8px;border:1px solid rgba(74,222,128,0.2);"><div style="font-size:1.6rem;font-weight:700;color:#4ade80;">${d.firm_avg_win_rate_pct}%</div><div style="font-size:0.75rem;color:#a0aec0;">Avg Win Rate</div></div>`;
        h += `<div style="text-align:center;padding:10px;background:rgba(167,139,250,0.1);border-radius:8px;border:1px solid rgba(167,139,250,0.2);"><div style="font-size:1.6rem;font-weight:700;color:#a78bfa;">${d.firm_avg_depo_quality}</div><div style="font-size:0.75rem;color:#a0aec0;">Avg Depo Quality</div></div>`;
        h += '</div>';
        h += `<div style="font-size:0.8rem;color:#4ade80;margin-bottom:4px;">🏆 Top: ${d.top_performer.name} (${d.top_performer.win_rate_pct}% win rate)</div>`;
        h += `<div style="font-size:0.8rem;color:#fbbf24;margin-bottom:8px;">📉 Support: ${d.needs_support.name} (${d.needs_support.win_rate_pct}% win rate)</div>`;
        h += '<table style="width:100%;font-size:0.72rem;border-collapse:collapse;">';
        h += '<tr style="color:#a0aec0;border-bottom:1px solid rgba(255,255,255,0.1);"><th style="text-align:left;padding:4px;">Attorney</th><th>Cases</th><th>Win %</th><th>Quality</th><th>Trend</th></tr>';
        d.attorneys.sort((a,b) => b.win_rate_pct - a.win_rate_pct).forEach(a => {
            const tc = a.performance_trend === 'improving' ? '#4ade80' : a.performance_trend === 'declining' ? '#f87171' : '#fbbf24';
            const ti = a.performance_trend === 'improving' ? '↑' : a.performance_trend === 'declining' ? '↓' : '→';
            h += `<tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:4px;color:#e2e8f0;">${a.attorney_name}</td><td style="text-align:center;">${a.active_cases}</td><td style="text-align:center;color:${a.win_rate_pct > 70 ? '#4ade80' : '#fbbf24'};">${a.win_rate_pct}%</td><td style="text-align:center;">${a.avg_deposition_quality}</td><td style="text-align:center;color:${tc};">${ti}</td></tr>`;
        });
        h += '</table>';
        h += `<div style="font-size:0.72rem;color:#a0aec0;margin-top:8px;">💡 ${d.system_recommendation}</div>`;
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load attorney performance</p>'; }
}
loadAttorneyPerformancePanel();
document.getElementById('attorney-performance-refresh')?.addEventListener('click', loadAttorneyPerformancePanel);
setTimeout(loadAttorneyPerformancePanel, 46000);

// ── Witness Pool Analytics Panel ──
async function loadWitnessPoolAnalyticsPanel() {
    const el = document.getElementById('witness-pool-analytics-content');
    if (!el) return;
    try {
        const r = await fetch('/api/admin/witness-pool-analytics', {headers:{'Authorization': 'Bearer ' + getAdminToken()}});
        if (!r.ok) throw new Error('Failed');
        const d = await r.json();
        let h = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">';
        h += `<div style="text-align:center;padding:10px;background:rgba(96,165,250,0.1);border-radius:8px;border:1px solid rgba(96,165,250,0.2);"><div style="font-size:1.6rem;font-weight:700;color:#60a5fa;">${d.total_witnesses_in_pool}</div><div style="font-size:0.75rem;color:#a0aec0;">Total Witnesses</div></div>`;
        const qc = d.pool_quality_rating === 'strong' ? '#4ade80' : d.pool_quality_rating === 'adequate' ? '#fbbf24' : '#f87171';
        h += `<div style="text-align:center;padding:10px;background:rgba(74,222,128,0.1);border-radius:8px;border:1px solid rgba(74,222,128,0.2);"><div style="font-size:1.6rem;font-weight:700;color:${qc};">${d.pool_quality_score}</div><div style="font-size:0.75rem;color:#a0aec0;">Pool Quality</div></div>`;
        h += `<div style="text-align:center;padding:10px;background:rgba(248,113,113,0.1);border-radius:8px;border:1px solid rgba(248,113,113,0.2);"><div style="font-size:1.6rem;font-weight:700;color:#f87171;">${d.witnesses_at_risk}</div><div style="font-size:0.75rem;color:#a0aec0;">At Risk</div></div>`;
        h += '</div>';
        h += '<div style="font-size:0.78rem;color:#fbbf24;margin-bottom:6px;">📊 Reliability Distribution:</div>';
        d.reliability_distribution.forEach(r => {
            const barW = Math.max(5, r.pct);
            const bc = r.tier.includes('Excellent') ? '#4ade80' : r.tier.includes('Good') ? '#60a5fa' : r.tier.includes('Moderate') ? '#fbbf24' : r.tier.includes('Marginal') ? '#fb923c' : '#f87171';
            h += `<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;font-size:0.7rem;">`;
            h += `<span style="width:110px;color:#a0aec0;">${r.tier.split('(')[0].trim()}</span>`;
            h += `<div style="flex:1;background:rgba(255,255,255,0.05);border-radius:4px;height:14px;"><div style="width:${barW}%;background:${bc};height:100%;border-radius:4px;"></div></div>`;
            h += `<span style="width:30px;color:#e2e8f0;">${r.count}</span>`;
            h += '</div>';
        });
        h += '<div style="font-size:0.78rem;color:#a78bfa;margin-top:8px;margin-bottom:4px;">🏷️ By Type:</div>';
        d.witness_types.forEach(t => {
            h += `<div style="font-size:0.7rem;color:#e2e8f0;margin-left:8px;">${t.type}: <strong>${t.count}</strong> witnesses (avg reliability: ${t.avg_reliability})</div>`;
        });
        h += `<div style="font-size:0.72rem;color:#4ade80;margin-top:6px;">✅ Most reliable: ${d.most_reliable_type} | ⚠️ Least: ${d.least_reliable_type}</div>`;
        h += `<div style="font-size:0.72rem;color:#a0aec0;margin-top:4px;">💡 ${d.system_recommendation}</div>`;
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load witness pool analytics</p>'; }
}
loadWitnessPoolAnalyticsPanel();
document.getElementById('witness-pool-analytics-refresh')?.addEventListener('click', loadWitnessPoolAnalyticsPanel);
setTimeout(loadWitnessPoolAnalyticsPanel, 48000);

// ── Jury Analytics Panel ──
async function loadJuryAnalyticsPanel() {
    const el = document.getElementById('jury-analytics-content');
    if (!el) return;
    try {
        const token = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || '';
        const r = await fetch('/api/admin/jury-analytics', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!r.ok) throw new Error('API error');
        const d = await r.json();
        let h = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">';
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:#60a5fa;">${d.total_cases_analyzed}</div><div style="font-size:0.75rem;color:#a0aec0;">Cases Analyzed</div></div>`;
        const favColor = d.avg_jury_favorability_score > 65 ? '#4ade80' : d.avg_jury_favorability_score > 50 ? '#fbbf24' : '#f87171';
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:${favColor};">${d.avg_jury_favorability_score}%</div><div style="font-size:0.75rem;color:#a0aec0;">Avg Favorability</div></div>`;
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:#a78bfa;">${d.overall_strike_accuracy_pct}%</div><div style="font-size:0.75rem;color:#a0aec0;">Strike Accuracy</div></div>`;
        h += '</div>';
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin-bottom:6px;">Verdict by Composition:</div>';
        d.verdict_by_composition.forEach(v => {
            const pctColor = v.plaintiff_win_pct > 60 ? '#4ade80' : v.plaintiff_win_pct > 50 ? '#fbbf24' : '#f87171';
            h += `<div style="display:flex;justify-content:space-between;padding:4px 8px;background:rgba(0,0,0,0.1);border-radius:4px;margin-bottom:3px;font-size:0.75rem;">`;
            h += `<span style="color:#e2e8f0;">${v.composition_type}</span>`;
            h += `<span><span style="color:${pctColor};">${v.plaintiff_win_pct}% win</span> | <span style="color:#fbbf24;">$${v.avg_damages_k}K avg</span> | <span style="color:#a0aec0;">${v.cases} cases</span></span>`;
            h += '</div>';
        });
        h += `<div style="font-size:0.72rem;color:#a0aec0;margin-top:8px;">🏆 Best: ${d.most_favorable_composition} | 💡 ${d.system_recommendation}</div>`;
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load jury analytics</p>'; }
}
loadJuryAnalyticsPanel();
document.getElementById('jury-analytics-refresh')?.addEventListener('click', loadJuryAnalyticsPanel);
setTimeout(loadJuryAnalyticsPanel, 50000);

// ── Evidence Completeness Panel ──
async function loadEvidenceCompletenessPanel() {
    const el = document.getElementById('evidence-completeness-content');
    if (!el) return;
    try {
        const token = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || '';
        const r = await fetch('/api/admin/evidence-completeness', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!r.ok) throw new Error('API error');
        const d = await r.json();
        let h = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">';
        const compColor = d.completeness_rating === 'strong' ? '#4ade80' : d.completeness_rating === 'adequate' ? '#fbbf24' : '#f87171';
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:${compColor};">${d.portfolio_completeness_score}%</div><div style="font-size:0.75rem;color:#a0aec0;">Completeness</div></div>`;
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:#f87171;">${d.critical_cases_needing_attention}</div><div style="font-size:0.75rem;color:#a0aec0;">Critical Cases</div></div>`;
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:#fbbf24;">${d.total_open_gaps}</div><div style="font-size:0.75rem;color:#a0aec0;">Open Gaps</div></div>`;
        h += '</div>';
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin-bottom:6px;">Gaps by Evidence Type:</div>';
        d.gap_by_evidence_type.forEach(g => {
            const gapColor = g.avg_gap_pct > 25 ? '#f87171' : g.avg_gap_pct > 15 ? '#fbbf24' : '#4ade80';
            h += `<div style="display:flex;justify-content:space-between;padding:4px 8px;background:rgba(0,0,0,0.1);border-radius:4px;margin-bottom:3px;font-size:0.75rem;">`;
            h += `<span style="color:#e2e8f0;">${g.type}</span>`;
            h += `<span><span style="color:${gapColor};">${g.avg_gap_pct}% gap</span> | <span style="color:#a0aec0;">${g.cases_affected} cases</span></span>`;
            h += '</div>';
        });
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin:8px 0 4px;">Distribution:</div>';
        d.completeness_distribution.forEach(tier => {
            const tColor = tier.tier.includes('Complete') ? '#4ade80' : tier.tier.includes('Strong') ? '#60a5fa' : tier.tier.includes('Adequate') ? '#fbbf24' : tier.tier.includes('Gaps') ? '#fb923c' : '#f87171';
            h += `<div style="font-size:0.72rem;color:#a0aec0;padding:2px 8px;"><span style="color:${tColor};">■</span> ${tier.tier}: ${tier.count} (${tier.pct}%)</div>`;
        });
        h += `<div style="font-size:0.72rem;color:#a0aec0;margin-top:8px;">📊 Most gaps: ${d.most_common_gap_type} | Avg fix cost: $${d.avg_remediation_cost_per_gap_k}K | 💡 ${d.system_recommendation}</div>`;
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load evidence completeness</p>'; }
}
loadEvidenceCompletenessPanel();
document.getElementById('evidence-completeness-refresh')?.addEventListener('click', loadEvidenceCompletenessPanel);
setTimeout(loadEvidenceCompletenessPanel, 52000);

// ── Coaching Detection Analytics Panel ──
async function loadCoachingAnalyticsPanel() {
    const el = document.getElementById('coaching-analytics-content');
    if (!el) return;
    try {
        const token = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || '';
        const r = await fetch('/api/admin/coaching-analytics', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!r.ok) throw new Error('API error');
        const d = await r.json();
        let h = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">';
        const rateColor = d.overall_coaching_rate_pct > 30 ? '#f87171' : d.overall_coaching_rate_pct > 15 ? '#fbbf24' : '#4ade80';
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:#60a5fa;">${d.total_depositions_analyzed}</div><div style="font-size:0.75rem;color:#a0aec0;">Analyzed</div></div>`;
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:${rateColor};">${d.overall_coaching_rate_pct}%</div><div style="font-size:0.75rem;color:#a0aec0;">Coaching Rate</div></div>`;
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:#fbbf24;">${d.motions_filed_total}</div><div style="font-size:0.75rem;color:#a0aec0;">Motions Filed</div></div>`;
        h += '</div>';
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin-bottom:6px;">By Indicator:</div>';
        d.by_indicator.forEach(ind => {
            const indColor = ind.detection_rate_pct > 40 ? '#f87171' : ind.detection_rate_pct > 20 ? '#fbbf24' : '#4ade80';
            h += `<div style="display:flex;justify-content:space-between;padding:4px 8px;background:rgba(0,0,0,0.1);border-radius:4px;margin-bottom:3px;font-size:0.75rem;">`;
            h += `<span style="color:#e2e8f0;">${ind.indicator}</span>`;
            h += `<span><span style="color:${indColor};">${ind.detection_rate_pct}%</span> | <span style="color:#a0aec0;">${ind.cases_flagged} flagged</span></span>`;
            h += '</div>';
        });
        h += `<div style="font-size:0.72rem;color:#a0aec0;margin-top:8px;">📊 Most common: ${d.most_common_indicator} | Avg score: ${d.avg_coaching_score} | 💡 ${d.system_recommendation.substring(0,80)}</div>`;
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load coaching analytics</p>'; }
}
loadCoachingAnalyticsPanel();
document.getElementById('coaching-analytics-refresh')?.addEventListener('click', loadCoachingAnalyticsPanel);
setTimeout(loadCoachingAnalyticsPanel, 54000);

// ── Settlement Accuracy Tracker Panel ──
async function loadSettlementAccuracyPanel() {
    const el = document.getElementById('settlement-accuracy-content');
    if (!el) return;
    try {
        const token = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || '';
        const r = await fetch('/api/admin/settlement-accuracy', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!r.ok) throw new Error('API error');
        const d = await r.json();
        let h = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">';
        const accColor = d.overall_accuracy_pct > 75 ? '#4ade80' : d.overall_accuracy_pct > 60 ? '#fbbf24' : '#f87171';
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:${accColor};">${d.overall_accuracy_pct}%</div><div style="font-size:0.75rem;color:#a0aec0;">Accuracy</div></div>`;
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:#60a5fa;">${d.total_predictions_made}</div><div style="font-size:0.75rem;color:#a0aec0;">Predictions</div></div>`;
        h += `<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.5rem;font-weight:700;color:#4ade80;">$${d.estimated_client_savings_k}K</div><div style="font-size:0.75rem;color:#a0aec0;">Client Savings</div></div>`;
        h += '</div>';
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin-bottom:6px;">By Case Type:</div>';
        d.by_case_type.forEach(ct => {
            const ctColor = ct.accuracy_pct > 75 ? '#4ade80' : ct.accuracy_pct > 60 ? '#fbbf24' : '#f87171';
            h += `<div style="display:flex;justify-content:space-between;padding:4px 8px;background:rgba(0,0,0,0.1);border-radius:4px;margin-bottom:3px;font-size:0.75rem;">`;
            h += `<span style="color:#e2e8f0;">${ct.type}</span>`;
            h += `<span><span style="color:${ctColor};">${ct.accuracy_pct}%</span> | <span style="color:#a0aec0;">±$${ct.avg_deviation_k}K</span> | <span style="color:#60a5fa;">${ct.predictions}</span></span>`;
            h += '</div>';
        });
        h += `<div style="font-size:0.72rem;color:#a0aec0;margin-top:8px;">📊 Best: ${d.best_performing_category} | Trend: ${d.improvement_trend} | Settled in range: ${d.cases_settled_within_range} | 💡 ${d.system_recommendation.substring(0,80)}</div>`;
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load settlement accuracy</p>'; }
}
loadSettlementAccuracyPanel();
document.getElementById('settlement-accuracy-refresh')?.addEventListener('click', loadSettlementAccuracyPanel);
setTimeout(loadSettlementAccuracyPanel, 56000);

// ── Testimony Volume Analytics Panel ──
async function loadTestimonyVolumePanel() {
    const el = document.getElementById('testimony-volume-content');
    if (!el) return;
    try {
        const token = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || '';
        const r = await fetch('/api/admin/testimony-volume', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!r.ok) throw new Error('API error');
        const d = await r.json();
        let h = '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px;">';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#60a5fa;">' + d.total_testimonies_processed + '</div><div style="font-size:0.7rem;color:#a0aec0;">Testimonies (30d)</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#4ade80;">' + d.total_analyses_run + '</div><div style="font-size:0.7rem;color:#a0aec0;">Analyses Run</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#fbbf24;">' + d.avg_daily_testimonies + '</div><div style="font-size:0.7rem;color:#a0aec0;">Avg/Day</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#c084fc;">' + d.avg_analyses_per_testimony + '</div><div style="font-size:0.7rem;color:#a0aec0;">Analyses/Testimony</div></div>';
        h += '</div>';
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin-bottom:6px;">Top Features by Usage:</div>';
        d.by_feature.forEach(function(f) {
            var barW = Math.min(100, f.calls / 3);
            h += '<div style="display:flex;align-items:center;gap:6px;padding:3px 8px;font-size:0.72rem;margin-bottom:2px;">';
            h += '<span style="min-width:130px;color:#e2e8f0;">' + f.feature + '</span>';
            h += '<div style="flex:1;height:5px;background:#1e293b;border-radius:3px;overflow:hidden;"><div style="height:100%;width:' + barW + '%;background:#60a5fa;border-radius:3px;"></div></div>';
            h += '<span style="color:#60a5fa;min-width:35px;text-align:right;">' + f.calls + '</span>';
            h += '<span style="color:#64748b;min-width:40px;text-align:right;">' + f.avg_time_sec + 's</span></div>';
        });
        h += '<div style="display:flex;gap:12px;margin-top:8px;font-size:0.72rem;color:#a0aec0;">';
        h += '<span>📈 Trend: ' + d.growth_trend + '</span>';
        h += '<span>⏰ Busiest hour: ' + d.busiest_hour + ':00</span>';
        h += '<span>📅 Busiest day: ' + d.busiest_day + '</span>';
        h += '<span>📝 Avg ' + d.avg_words_per_testimony + ' words/testimony</span></div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load testimony volume</p>'; }
}
loadTestimonyVolumePanel();
document.getElementById('testimony-volume-refresh')?.addEventListener('click', loadTestimonyVolumePanel);
setTimeout(loadTestimonyVolumePanel, 58000);

// ── Witness Credibility Trends Panel ──
async function loadCredibilityTrendsPanel() {
    const el = document.getElementById('credibility-trends-content');
    if (!el) return;
    try {
        const token = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || '';
        const r = await fetch('/api/admin/witness-credibility-dashboard', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!r.ok) throw new Error('API error');
        const d = await r.json();
        let h = '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px;">';
        const trendColor = d.trend_direction === 'improving' ? '#4ade80' : '#f87171';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#60a5fa;">' + d.total_witnesses_assessed + '</div><div style="font-size:0.7rem;color:#a0aec0;">Witnesses Assessed</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#4ade80;">' + d.overall_avg_credibility + '</div><div style="font-size:0.7rem;color:#a0aec0;">Avg Credibility</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#f87171;">' + d.high_risk_percentage + '%</div><div style="font-size:0.7rem;color:#a0aec0;">High Risk Rate</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:' + trendColor + ';">' + (d.trend_direction === 'improving' ? '📈' : '📉') + ' ' + d.trend_direction + '</div><div style="font-size:0.7rem;color:#a0aec0;">12-Week Trend</div></div>';
        h += '</div>';
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin-bottom:6px;">By Case Type:</div>';
        d.by_case_type.forEach(function(ct) {
            var ctColor = ct.avg_credibility >= 75 ? '#4ade80' : ct.avg_credibility >= 60 ? '#60a5fa' : '#fbbf24';
            var tColor = ct.trend === 'improving' ? '#4ade80' : ct.trend === 'declining' ? '#f87171' : '#94a3b8';
            var barW = ct.avg_credibility;
            h += '<div style="display:flex;align-items:center;gap:6px;padding:3px 0;font-size:0.72rem;margin-bottom:2px;">';
            h += '<span style="min-width:130px;color:#e2e8f0;">' + ct.case_type + '</span>';
            h += '<div style="flex:1;height:5px;background:#1e293b;border-radius:3px;overflow:hidden;"><div style="height:100%;width:' + barW + '%;background:' + ctColor + ';border-radius:3px;"></div></div>';
            h += '<span style="color:' + ctColor + ';min-width:35px;text-align:right;">' + ct.avg_credibility + '</span>';
            h += '<span style="color:' + tColor + ';min-width:55px;text-align:right;">' + ct.trend + '</span></div>';
        });
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin:8px 0 4px;">Risk Distribution:</div>';
        h += '<div style="display:flex;gap:6px;flex-wrap:wrap;">';
        var riskColors = { very_high_risk: '#ef4444', high_risk: '#f97316', moderate_risk: '#fbbf24', low_risk: '#4ade80', minimal_risk: '#60a5fa' };
        Object.entries(d.risk_distribution).forEach(function([k, v]) {
            var rc = riskColors[k] || '#94a3b8';
            h += '<div style="text-align:center;padding:5px 10px;background:' + rc + '18;border-radius:6px;border:1px solid ' + rc + '44;">';
            h += '<div style="font-size:1rem;font-weight:700;color:' + rc + '">' + v + '</div>';
            h += '<div style="font-size:0.6rem;color:#a0aec0;">' + k.replace(/_/g, ' ') + '</div></div>';
        });
        h += '</div>';
        h += '<div style="font-size:0.72rem;color:#fbbf24;margin-top:8px;">⚠️ ' + d.alert + '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load credibility trends</p>'; }
}
loadCredibilityTrendsPanel();
document.getElementById('credibility-trends-refresh')?.addEventListener('click', loadCredibilityTrendsPanel);
setTimeout(loadCredibilityTrendsPanel, 62000);

// ── Deposition Risk Monitor Panel ──
async function loadDepositionRiskMonitorPanel() {
    const el = document.getElementById('deposition-risk-monitor-content');
    if (!el) return;
    try {
        const token = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || localStorage.getItem('wr_admin_token') || '';
        const r = await fetch('/api/admin/deposition-risk-monitor', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!r.ok) throw new Error('API error');
        const d = await r.json();
        let h = '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px;">';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#60a5fa;">' + d.total_active_depositions + '</div><div style="font-size:0.7rem;color:#a0aec0;">Active Depositions</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#ef4444;">' + d.critical_risk_count + '</div><div style="font-size:0.7rem;color:#a0aec0;">Critical Risk</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#f97316;">' + d.high_risk_count + '</div><div style="font-size:0.7rem;color:#a0aec0;">High Risk</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;"><div style="font-size:1.4rem;font-weight:700;color:#fbbf24;">' + d.avg_risk_score + '</div><div style="font-size:0.7rem;color:#a0aec0;">Avg Risk Score</div></div>';
        h += '</div>';
        if (d.system_alert) {
            h += '<div style="padding:6px 10px;background:rgba(239,68,68,0.12);border-left:3px solid #ef4444;border-radius:4px;font-size:0.72rem;color:#f87171;margin-bottom:10px;">🚨 ' + d.system_alert + '</div>';
        }
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin-bottom:6px;">Top At-Risk Depositions:</div>';
        d.top_at_risk_depositions.forEach(function(dep) {
            var dc = dep.risk_level === 'critical' ? '#ef4444' : dep.risk_level === 'high' ? '#f97316' : dep.risk_level === 'moderate' ? '#fbbf24' : '#4ade80';
            h += '<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:rgba(0,0,0,0.15);border-radius:5px;margin-bottom:4px;">';
            h += '<div><div style="font-size:0.75rem;font-weight:600;color:#e2e8f0;">' + dep.case_name + '</div>';
            h += '<div style="font-size:0.65rem;color:#64748b;">' + dep.scheduled_date + ' · ' + dep.attorney_assigned + ' · Risk: ' + dep.primary_risk + '</div></div>';
            h += '<div style="text-align:right;"><div style="font-size:0.85rem;font-weight:700;color:' + dc + '">' + dep.risk_score + '</div>';
            h += '<div style="font-size:0.6rem;color:' + dc + ';text-transform:uppercase;">' + dep.risk_level + '</div>';
            h += '<div style="font-size:0.6rem;color:#64748b;">' + dep.prep_hours_remaining + 'h prep left</div></div></div>';
        });
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin:8px 0 4px;">Risk Categories:</div>';
        Object.entries(d.risk_categories_summary).forEach(function([cat, info]) {
            var tColor = info.trend === 'worsening' ? '#f87171' : info.trend === 'improving' ? '#4ade80' : '#94a3b8';
            var barW = info.avg_risk;
            h += '<div style="display:flex;align-items:center;gap:6px;font-size:0.7rem;margin-bottom:3px;">';
            h += '<span style="min-width:120px;color:#e2e8f0;">' + cat + '</span>';
            h += '<div style="flex:1;height:4px;background:#1e293b;border-radius:2px;"><div style="height:100%;width:' + barW + '%;background:#60a5fa;border-radius:2px;"></div></div>';
            h += '<span style="color:#60a5fa;min-width:30px;text-align:right;">' + info.avg_risk + '</span>';
            h += '<span style="color:' + tColor + ';min-width:55px;text-align:right;">' + info.trend + '</span></div>';
        });
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load deposition risk monitor</p>'; }
}
loadDepositionRiskMonitorPanel();
document.getElementById('deposition-risk-monitor-refresh')?.addEventListener('click', loadDepositionRiskMonitorPanel);
setTimeout(loadDepositionRiskMonitorPanel, 64000);

// ─── Feature Usage Analytics Panel ───────────────────────────────────────────
async function loadFeatureUsagePanel() {
    var el = document.getElementById('feature-usage-content');
    if (!el) return;
    var tk = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || '';
    try {
        var r = await fetch('/api/admin/feature-usage-analytics', { headers: { 'Authorization': 'Bearer ' + tk } });
        var d = await r.json();
        var h = '';
        h += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px;">';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;border-top:3px solid #a78bfa;"><div style="font-size:1.3rem;font-weight:700;color:#a78bfa;">' + (d.total_feature_uses || 0).toLocaleString() + '</div><div style="font-size:0.6rem;color:#a0aec0;">Total Uses (30d)</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;border-top:3px solid #60a5fa;"><div style="font-size:1.3rem;font-weight:700;color:#60a5fa;">' + (d.total_unique_users || 0) + '</div><div style="font-size:0.6rem;color:#a0aec0;">Unique Users</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;border-top:3px solid #4ade80;"><div style="font-size:1.3rem;font-weight:700;color:#4ade80;">' + (d.avg_features_per_session || 0) + '</div><div style="font-size:0.6rem;color:#a0aec0;">Avg Features/Session</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;border-top:3px solid #fbbf24;"><div style="font-size:1.3rem;font-weight:700;color:#fbbf24;">' + (d.engagement_metrics?.return_rate_7d || 0) + '%</div><div style="font-size:0.6rem;color:#a0aec0;">7d Return Rate</div></div>';
        h += '</div>';
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin-bottom:6px;">🏆 Top Features by Usage</div>';
        (d.feature_usage || []).slice(0, 10).forEach(function(f) {
            var maxUses = (d.feature_usage[0] || {}).total_uses_30d || 1;
            var barW = Math.round(f.total_uses_30d / maxUses * 100);
            var tColor = f.trend === 'rising' ? '#4ade80' : f.trend === 'declining' ? '#f87171' : f.trend === 'new' ? '#a78bfa' : '#94a3b8';
            h += '<div style="margin-bottom:4px;">';
            h += '<div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:1px;">';
            h += '<span style="color:#e2e8f0;">' + f.feature + '</span>';
            h += '<span><span style="color:#60a5fa;font-weight:600;">' + f.total_uses_30d + '</span> <span style="color:' + tColor + ';">(' + f.trend + ')</span> ⭐' + f.satisfaction_score + '</span></div>';
            h += '<div style="height:4px;background:#1e293b;border-radius:2px;"><div style="height:100%;width:' + barW + '%;background:#60a5fa;border-radius:2px;"></div></div></div>';
        });
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin:10px 0 6px;">📈 Category Breakdown</div>';
        Object.entries(d.category_breakdown || {}).forEach(function([cat, info]) {
            h += '<div style="display:flex;justify-content:space-between;font-size:0.7rem;padding:2px 0;">';
            h += '<span style="color:#e2e8f0;">' + cat + '</span>';
            h += '<span style="color:#a78bfa;font-weight:600;">' + info.uses + ' (' + info.pct + '%)</span></div>';
        });
        if (d.adoption_alerts) {
            h += '<div style="margin-top:8px;font-size:0.72rem;color:#fbbf24;">';
            d.adoption_alerts.forEach(function(a) { h += '<div>⚠️ ' + a + '</div>'; });
            h += '</div>';
        }
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load feature usage analytics</p>'; }
}
loadFeatureUsagePanel();
document.getElementById('feature-usage-refresh')?.addEventListener('click', loadFeatureUsagePanel);
setTimeout(loadFeatureUsagePanel, 65000);

// ─── System Performance Dashboard Panel ──────────────────────────────────────
async function loadSystemPerformancePanel() {
    var el = document.getElementById('system-performance-content');
    if (!el) return;
    var tk = sessionStorage.getItem('admin_token') || localStorage.getItem('admin_token') || '';
    try {
        var r = await fetch('/api/admin/system-performance', { headers: { 'Authorization': 'Bearer ' + tk } });
        var d = await r.json();
        var statusColor = d.system_status === 'healthy' ? '#4ade80' : d.system_status === 'degraded' ? '#fbbf24' : '#f87171';
        var h = '';
        h += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px;">';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;border-top:3px solid ' + statusColor + ';"><div style="font-size:1.1rem;font-weight:700;color:' + statusColor + ';text-transform:uppercase;">' + (d.system_status || 'unknown') + '</div><div style="font-size:0.6rem;color:#a0aec0;">System Status</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;border-top:3px solid #60a5fa;"><div style="font-size:1.3rem;font-weight:700;color:#60a5fa;">' + (d.uptime_pct || 0) + '%</div><div style="font-size:0.6rem;color:#a0aec0;">Uptime (' + (d.uptime_days || 0) + 'd)</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;border-top:3px solid #a78bfa;"><div style="font-size:1.3rem;font-weight:700;color:#a78bfa;">' + (d.total_requests_24h || 0) + '</div><div style="font-size:0.6rem;color:#a0aec0;">Requests (24h)</div></div>';
        h += '<div style="text-align:center;padding:10px;background:rgba(0,0,0,0.2);border-radius:8px;border-top:3px solid #fbbf24;"><div style="font-size:1.3rem;font-weight:700;color:#fbbf24;">' + (d.avg_response_time_ms || 0) + 'ms</div><div style="font-size:0.6rem;color:#a0aec0;">Avg Response</div></div>';
        h += '</div>';
        h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">';
        h += '<div style="padding:8px;background:rgba(0,0,0,0.15);border-radius:6px;">';
        h += '<div style="font-size:0.75rem;font-weight:600;color:#e2e8f0;margin-bottom:4px;">💾 System Resources</div>';
        h += '<div style="font-size:0.68rem;color:#60a5fa;">Memory: ' + (d.current_memory_mb || 0) + ' MB</div>';
        h += '<div style="font-size:0.68rem;color:#a78bfa;">CPU: ' + (d.current_cpu_pct || 0) + '%</div>';
        h += '<div style="font-size:0.68rem;color:#f87171;">Errors (24h): ' + (d.total_errors_24h || 0) + ' (' + (d.overall_error_rate_pct || 0) + '%)</div></div>';
        h += '<div style="padding:8px;background:rgba(0,0,0,0.15);border-radius:6px;">';
        h += '<div style="font-size:0.75rem;font-weight:600;color:#e2e8f0;margin-bottom:4px;">🤖 Gemini API</div>';
        var gs = d.gemini_api_stats || {};
        h += '<div style="font-size:0.68rem;color:#60a5fa;">Calls (24h): ' + (gs.total_calls_24h || 0) + '</div>';
        h += '<div style="font-size:0.68rem;color:#a78bfa;">Avg Latency: ' + (gs.avg_latency_ms || 0) + 'ms</div>';
        h += '<div style="font-size:0.68rem;color:#fbbf24;">Cache Hit: ' + (gs.cache_hit_rate_pct || 0) + '% · Cost: ' + (gs.estimated_cost_24h || '$0') + '</div></div>';
        h += '</div>';
        h += '<div style="font-size:0.8rem;font-weight:600;color:#e2e8f0;margin-bottom:6px;">⚡ Slowest Endpoints (p95)</div>';
        (d.api_endpoint_performance || []).slice(0, 6).forEach(function(ep) {
            var epColor = ep.status === 'healthy' ? '#4ade80' : ep.status === 'degraded' ? '#fbbf24' : '#f87171';
            h += '<div style="display:flex;justify-content:space-between;align-items:center;font-size:0.68rem;padding:2px 0;">';
            h += '<span style="color:#e2e8f0;flex:1;">' + ep.endpoint + '</span>';
            h += '<span style="color:#94a3b8;min-width:40px;text-align:right;">' + ep.requests_24h + 'req</span>';
            h += '<span style="color:' + epColor + ';min-width:65px;text-align:right;font-weight:600;">' + ep.p95_ms + 'ms</span>';
            h += '<span style="color:' + (ep.error_rate_pct > 1 ? '#f87171' : '#4ade80') + ';min-width:40px;text-align:right;">' + ep.error_rate_pct + '%</span></div>';
        });
        if (d.alerts && d.alerts.length > 0) {
            h += '<div style="margin-top:8px;">';
            d.alerts.forEach(function(a) { h += '<div style="font-size:0.7rem;color:#f87171;padding:2px 0;">🚨 ' + a + '</div>'; });
            h += '</div>';
        }
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load system performance</p>'; }
}
loadSystemPerformancePanel();
document.getElementById('system-performance-refresh')?.addEventListener('click', loadSystemPerformancePanel);
setTimeout(loadSystemPerformancePanel, 66000);

// ── Admin Case Outcome Tracker ───────────────────────────────────
async function loadCaseOutcomeTrackerPanel() {
    var el = document.getElementById('case-outcome-tracker-content');
    if (!el) return;
    try {
        var tk = localStorage.getItem('adminToken') || 'admin';
        var r = await fetch('/api/admin/case-outcome-tracker', { headers: { 'Authorization': 'Bearer ' + tk } });
        var d = await r.json();
        var gc = d.accuracy_grade === 'A' ? '#4ade80' : d.accuracy_grade === 'B' ? '#60a5fa' : '#fbbf24';
        var h = '<div style="display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;">';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;border-top:3px solid ' + gc + ';">';
        h += '<div style="font-size:1.5rem;font-weight:700;color:' + gc + '">' + d.overall_prediction_accuracy + '%</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Accuracy (' + d.accuracy_grade + ')</div></div>';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;">';
        h += '<div style="font-size:1.5rem;font-weight:700;color:#60a5fa">' + d.total_cases + '</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Total Cases</div></div>';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;">';
        h += '<div style="font-size:1.5rem;font-weight:700;color:#a78bfa">' + d.resolved_cases + '</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Resolved</div></div></div>';
        h += '<h4 style="color:#fbbf24;font-size:0.75rem;margin:8px 0 4px;">📊 Outcome Breakdown</h4>';
        h += '<table style="width:100%;font-size:0.65rem;border-collapse:collapse;">';
        h += '<tr style="border-bottom:1px solid #334155;"><th style="text-align:left;color:#94a3b8;padding:3px 4px;">Outcome</th><th style="color:#94a3b8;">Count</th><th style="color:#94a3b8;">Correct</th><th style="color:#94a3b8;">Accuracy</th></tr>';
        d.outcome_breakdown.forEach(function(o) {
            var oc = o.accuracy_pct >= 75 ? '#4ade80' : o.accuracy_pct >= 60 ? '#fbbf24' : '#f87171';
            h += '<tr style="border-bottom:1px solid #1e293b;"><td style="color:#e2e8f0;padding:3px 4px;">' + o.outcome_type + '</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + o.count + '</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + o.predicted_correctly + '</td>';
            h += '<td style="text-align:center;color:' + oc + ';font-weight:600;">' + o.accuracy_pct + '%</td></tr>';
        });
        h += '</table>';
        h += '<h4 style="color:#60a5fa;font-size:0.75rem;margin:8px 0 4px;">📈 Monthly Trend (last 6)</h4>';
        d.monthly_accuracy_trend.slice(-6).forEach(function(m) {
            var mc = m.accuracy_pct >= 75 ? '#4ade80' : m.accuracy_pct >= 60 ? '#fbbf24' : '#f87171';
            h += '<div style="display:flex;justify-content:space-between;font-size:0.62rem;padding:1px 0;">';
            h += '<span style="color:#94a3b8;">' + m.month + ' (' + m.cases_resolved + ' cases)</span>';
            h += '<span style="color:' + mc + ';font-weight:600;">' + m.accuracy_pct + '%</span></div>';
        });
        h += '<h4 style="color:#a78bfa;font-size:0.75rem;margin:8px 0 4px;">⚙️ Model Calibration</h4>';
        h += '<div style="font-size:0.62rem;color:#94a3b8;">Well-calibrated: <b style="color:#4ade80">' + d.model_calibration.well_calibrated_pct + '%</b> | Overconfident: <b style="color:#fbbf24">' + d.model_calibration.overconfident_predictions_pct + '%</b> | Underconfident: <b style="color:#60a5fa">' + d.model_calibration.underconfident_predictions_pct + '%</b></div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load case outcome tracker</p>'; }
}
loadCaseOutcomeTrackerPanel();
document.getElementById('case-outcome-tracker-refresh')?.addEventListener('click', loadCaseOutcomeTrackerPanel);
setTimeout(loadCaseOutcomeTrackerPanel, 67000);

// ── Admin Gemini Cost Dashboard ──────────────────────────────────
async function loadGeminiCostDashboardPanel() {
    var el = document.getElementById('gemini-cost-dashboard-content');
    if (!el) return;
    try {
        var tk = localStorage.getItem('adminToken') || 'admin';
        var r = await fetch('/api/admin/gemini-cost-dashboard', { headers: { 'Authorization': 'Bearer ' + tk } });
        var d = await r.json();
        var bc = d.budget_used_pct >= 90 ? '#f87171' : d.budget_used_pct >= 70 ? '#fbbf24' : '#4ade80';
        var h = '<div style="display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;">';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;border-top:3px solid #4ade80;">';
        h += '<div style="font-size:1.4rem;font-weight:700;color:#4ade80">$' + d.total_cost_today_usd + '</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Today\'s Cost</div></div>';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;border-top:3px solid #60a5fa;">';
        h += '<div style="font-size:1.4rem;font-weight:700;color:#60a5fa">$' + d.monthly_cost_usd + '</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Monthly</div></div>';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;border-top:3px solid ' + bc + ';">';
        h += '<div style="font-size:1.4rem;font-weight:700;color:' + bc + '">' + d.budget_used_pct + '%</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Budget Used</div></div></div>';
        h += '<h4 style="color:#a78bfa;font-size:0.75rem;margin:8px 0 4px;">🤖 Model Usage</h4>';
        h += '<table style="width:100%;font-size:0.62rem;border-collapse:collapse;">';
        h += '<tr style="border-bottom:1px solid #334155;"><th style="text-align:left;color:#94a3b8;padding:2px 4px;">Model</th><th style="color:#94a3b8;">Reqs</th><th style="color:#94a3b8;">Tokens</th><th style="color:#94a3b8;">Cost</th></tr>';
        d.model_usage.forEach(function(m) {
            h += '<tr style="border-bottom:1px solid #1e293b;"><td style="color:#e2e8f0;padding:2px 4px;">' + m.model + '</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + m.requests_today.toLocaleString() + '</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + (m.total_tokens / 1000000).toFixed(1) + 'M</td>';
            h += '<td style="text-align:center;color:#4ade80;font-weight:600;">$' + m.estimated_cost_usd + '</td></tr>';
        });
        h += '</table>';
        h += '<h4 style="color:#fbbf24;font-size:0.75rem;margin:8px 0 4px;">🏷️ Top Features by Cost</h4>';
        d.feature_cost_breakdown.slice(0, 6).forEach(function(f) {
            h += '<div style="display:flex;justify-content:space-between;font-size:0.62rem;padding:1px 0;">';
            h += '<span style="color:#e2e8f0;">' + f.feature + ' (' + f.requests_today + ' reqs)</span>';
            h += '<span style="color:#4ade80;font-weight:600;">$' + f.cost_usd + '</span></div>';
        });
        if (d.cost_optimization_suggestions.length > 0) {
            h += '<h4 style="color:#f87171;font-size:0.75rem;margin:8px 0 4px;">💡 Optimization Tips</h4>';
            d.cost_optimization_suggestions.forEach(function(s) {
                h += '<div style="font-size:0.6rem;color:#fbbf24;padding:1px 0;">• ' + s + '</div>';
            });
        }
        h += '<div style="font-size:0.6rem;color:#94a3b8;margin-top:4px;">Projected monthly: $' + d.projected_monthly_usd + ' / $' + d.budget_limit_usd + ' budget</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load Gemini cost dashboard</p>'; }
}
loadGeminiCostDashboardPanel();
document.getElementById('gemini-cost-dashboard-refresh')?.addEventListener('click', loadGeminiCostDashboardPanel);
setTimeout(loadGeminiCostDashboardPanel, 68000);

// ── Witness Demographics Dashboard ──────────────────────────────
async function loadWitnessDemographicsPanel() {
    var el = document.getElementById('witness-demographics-content');
    if (!el) return;
    try {
        var tk = localStorage.getItem('adminToken') || 'admin';
        var r = await fetch('/api/admin/witness-demographics', { headers: { 'Authorization': 'Bearer ' + tk } });
        var d = await r.json();
        var h = '<div style="display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;">';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;border-top:3px solid #a78bfa;">';
        h += '<div style="font-size:1.4rem;font-weight:700;color:#a78bfa">' + d.total_witnesses + '</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Total Witnesses</div></div>';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;border-top:3px solid #60a5fa;">';
        h += '<div style="font-size:1.4rem;font-weight:700;color:#60a5fa">' + d.avg_witnesses_per_case + '</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Avg/Case</div></div>';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;border-top:3px solid #4ade80;">';
        h += '<div style="font-size:1.4rem;font-weight:700;color:#4ade80">' + d.avg_testimony_duration_hours + 'h</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Avg Duration</div></div></div>';
        h += '<h4 style="color:#a78bfa;font-size:0.75rem;margin:8px 0 4px;">👥 Witness Types</h4>';
        h += '<table style="width:100%;font-size:0.62rem;border-collapse:collapse;">';
        h += '<tr style="border-bottom:1px solid #334155;"><th style="text-align:left;color:#94a3b8;padding:2px 4px;">Type</th><th style="color:#94a3b8;">Count</th><th style="color:#94a3b8;">Cooperative %</th></tr>';
        d.witness_types.forEach(function(wt) {
            var cc = wt.pct_cooperative >= 80 ? '#4ade80' : wt.pct_cooperative >= 65 ? '#fbbf24' : '#f87171';
            h += '<tr style="border-bottom:1px solid #1e293b;"><td style="color:#e2e8f0;padding:2px 4px;">' + wt.type + '</td>';
            h += '<td style="text-align:center;color:#60a5fa;font-weight:600;">' + wt.count + '</td>';
            h += '<td style="text-align:center;color:' + cc + ';">' + wt.pct_cooperative + '%</td></tr>';
        });
        h += '</table>';
        h += '<h4 style="color:#60a5fa;font-size:0.75rem;margin:8px 0 4px;">⚖️ Role Distribution</h4>';
        d.role_distribution.forEach(function(rd) {
            h += '<div style="display:flex;justify-content:space-between;font-size:0.62rem;padding:2px 0;">';
            h += '<span style="color:#e2e8f0;">' + rd.role + ' (' + rd.count + ')</span>';
            h += '<span style="color:#60a5fa;">Avg cred: ' + rd.avg_credibility + '</span></div>';
        });
        h += '<h4 style="color:#fbbf24;font-size:0.75rem;margin:8px 0 4px;">📈 Monthly Trend</h4>';
        d.monthly_trend.slice(-3).forEach(function(mt) {
            h += '<div style="display:flex;justify-content:space-between;font-size:0.62rem;padding:1px 0;">';
            h += '<span style="color:#94a3b8;">' + mt.month + '</span>';
            h += '<span style="color:#e2e8f0;">' + mt.new_witnesses + ' new | ' + mt.depositions_taken + ' depos | ' + mt.avg_testimony_hours + 'h avg</span></div>';
        });
        h += '<div style="font-size:0.6rem;color:#94a3b8;margin-top:4px;">Repeat witnesses: ' + d.repeat_witness_pct + '% | Credibility: High ' + d.credibility_distribution.high_credibility + '%, Mod ' + d.credibility_distribution.moderate_credibility + '%, Low ' + d.credibility_distribution.low_credibility + '%</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load witness demographics</p>'; }
}
loadWitnessDemographicsPanel();
document.getElementById('witness-demographics-refresh')?.addEventListener('click', loadWitnessDemographicsPanel);
setTimeout(loadWitnessDemographicsPanel, 72000);

// ── Analysis Quality Scorecard ──────────────────────────────────
async function loadAnalysisQualityScorecardPanel() {
    var el = document.getElementById('analysis-quality-scorecard-content');
    if (!el) return;
    try {
        var tk = localStorage.getItem('adminToken') || 'admin';
        var r = await fetch('/api/admin/analysis-quality-scorecard', { headers: { 'Authorization': 'Bearer ' + tk } });
        var d = await r.json();
        var gc = d.overall_quality_grade === 'A' ? '#4ade80' : d.overall_quality_grade === 'B' ? '#60a5fa' : d.overall_quality_grade === 'C' ? '#fbbf24' : '#f87171';
        var h = '<div style="display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;">';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;border-top:3px solid ' + gc + ';">';
        h += '<div style="font-size:1.4rem;font-weight:700;color:' + gc + '">' + d.overall_quality_grade + ' (' + d.overall_quality_score + ')</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Quality Grade</div></div>';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;border-top:3px solid #4ade80;">';
        h += '<div style="font-size:1.4rem;font-weight:700;color:#4ade80">' + d.user_satisfaction_avg + '%</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Satisfaction</div></div>';
        h += '<div style="text-align:center;padding:8px 14px;background:rgba(0,0,0,0.3);border-radius:8px;flex:1;min-width:80px;border-top:3px solid #60a5fa;">';
        h += '<div style="font-size:1.4rem;font-weight:700;color:#60a5fa">' + d.total_analyses_today + '</div>';
        h += '<div style="font-size:0.6rem;color:#94a3b8;">Today</div></div></div>';
        h += '<h4 style="color:#a78bfa;font-size:0.75rem;margin:8px 0 4px;">📊 Analysis Quality by Type</h4>';
        h += '<table style="width:100%;font-size:0.58rem;border-collapse:collapse;">';
        h += '<tr style="border-bottom:1px solid #334155;"><th style="text-align:left;color:#94a3b8;padding:2px 3px;">Analysis</th><th style="color:#94a3b8;">Acc</th><th style="color:#94a3b8;">Conf</th><th style="color:#94a3b8;">Sat</th><th style="color:#94a3b8;">Trend</th></tr>';
        d.analysis_quality_metrics.forEach(function(q) {
            var ac = q.accuracy_score >= 85 ? '#4ade80' : q.accuracy_score >= 75 ? '#fbbf24' : '#f87171';
            var tc = q.improvement_trend === 'Improving' ? '#4ade80' : q.improvement_trend === 'Stable' ? '#60a5fa' : '#f87171';
            h += '<tr style="border-bottom:1px solid #1e293b;">';
            h += '<td style="color:#e2e8f0;padding:2px 3px;">' + q.analysis_type + '</td>';
            h += '<td style="text-align:center;color:' + ac + ';font-weight:600;">' + q.accuracy_score + '</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + q.avg_confidence + '</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + q.user_satisfaction_pct + '%</td>';
            h += '<td style="text-align:center;color:' + tc + ';">' + (q.improvement_trend === 'Improving' ? '↑' : q.improvement_trend === 'Stable' ? '→' : '↓') + '</td></tr>';
        });
        h += '</table>';
        h += '<h4 style="color:#fbbf24;font-size:0.75rem;margin:8px 0 4px;">📈 Weekly Trend</h4>';
        d.weekly_trend.slice(-4).forEach(function(wt) {
            h += '<div style="display:flex;justify-content:space-between;font-size:0.6rem;padding:1px 0;">';
            h += '<span style="color:#94a3b8;">' + wt.week + '</span>';
            h += '<span style="color:#e2e8f0;">Acc: ' + wt.avg_accuracy + ' | Count: ' + wt.analyses_count + ' | Rating: ⭐' + wt.user_rating + '</span></div>';
        });
        h += '<h4 style="color:#f87171;font-size:0.75rem;margin:8px 0 4px;">💡 Recommendations</h4>';
        d.recommendations.forEach(function(rec) {
            h += '<div style="font-size:0.6rem;color:#fbbf24;padding:1px 0;">• ' + rec + '</div>';
        });
        h += '<div style="font-size:0.6rem;color:#94a3b8;margin-top:4px;">🏆 Best: ' + d.top_performing + ' | ⚠️ Needs work: ' + d.needs_improvement + '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load analysis quality scorecard</p>'; }
}
loadAnalysisQualityScorecardPanel();
document.getElementById('analysis-quality-scorecard-refresh')?.addEventListener('click', loadAnalysisQualityScorecardPanel);
setTimeout(loadAnalysisQualityScorecardPanel, 75000);

// ── Prompt Performance Panel ────────────────────────────────────
async function loadPromptPerformancePanel() {
    var el = document.getElementById('prompt-performance-content');
    if (!el) return;
    try {
        var r = await fetch('/api/admin/prompt-performance', { headers: authHeaders() });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var d = await r.json();
        var h = '<div style="font-size:0.75rem;">';
        h += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px;">';
        h += '<span style="color:#60a5fa;">Templates: <b>' + d.total_prompt_templates + '</b></span>';
        h += '<span style="color:#34d399;">Tokens Today: <b>' + d.total_tokens_today.toLocaleString() + '</b></span>';
        h += '<span style="color:#fbbf24;">Cost: <b>$' + d.total_cost_today_usd + '</b></span>';
        h += '<span style="color:#a78bfa;">Avg Quality: <b>' + d.avg_quality_score + '</b></span></div>';
        h += '<table style="width:100%;font-size:0.6rem;border-collapse:collapse;">';
        h += '<tr style="color:#94a3b8;"><th style="text-align:left;padding:1px 3px;">Template</th><th>Quality</th><th>Tokens</th><th>$/call</th><th>Halluc%</th><th>Calls</th></tr>';
        d.prompt_metrics.forEach(function(p) {
            var qc = p.quality_score >= 85 ? '#34d399' : p.quality_score >= 75 ? '#fbbf24' : '#f87171';
            var hc = p.hallucination_rate_pct <= 3 ? '#34d399' : p.hallucination_rate_pct <= 6 ? '#fbbf24' : '#f87171';
            h += '<tr><td style="color:#e2e8f0;padding:1px 3px;">' + p.template_name + '</td>';
            h += '<td style="text-align:center;color:' + qc + ';">' + p.quality_score + '</td>';
            h += '<td style="text-align:center;color:#60a5fa;">' + p.avg_total_tokens + '</td>';
            h += '<td style="text-align:center;color:#fbbf24;">$' + p.cost_per_call_usd + '</td>';
            h += '<td style="text-align:center;color:' + hc + ';">' + p.hallucination_rate_pct + '%</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + p.invocations_today + '</td></tr>';
        });
        h += '</table>';
        h += '<h4 style="color:#fbbf24;font-size:0.72rem;margin:6px 0 3px;">📈 Daily Trend</h4>';
        d.daily_trend.slice(-4).forEach(function(dt) {
            h += '<div style="display:flex;justify-content:space-between;font-size:0.58rem;padding:1px 0;">';
            h += '<span style="color:#94a3b8;">' + dt.day + '</span>';
            h += '<span style="color:#e2e8f0;">Tokens: ' + dt.total_tokens.toLocaleString() + ' | Quality: ' + dt.avg_quality + ' | Cost: $' + dt.cost_usd + '</span></div>';
        });
        h += '<div style="font-size:0.58rem;color:#94a3b8;margin-top:4px;">🏆 Best: ' + d.top_performing_prompt + ' | 💸 Most expensive: ' + d.most_expensive_prompt + '</div>';
        h += '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load prompt performance</p>'; }
}
loadPromptPerformancePanel();
document.getElementById('prompt-performance-refresh')?.addEventListener('click', loadPromptPerformancePanel);
setTimeout(loadPromptPerformancePanel, 80000);

// ── Case Complexity Distribution Panel ──────────────────────────
async function loadCaseComplexityDistPanel() {
    var el = document.getElementById('case-complexity-distribution-content');
    if (!el) return;
    try {
        var r = await fetch('/api/admin/case-complexity-distribution', { headers: authHeaders() });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var d = await r.json();
        var h = '<div style="font-size:0.75rem;">';
        h += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px;">';
        h += '<span style="color:#60a5fa;">Total Cases: <b>' + d.total_active_cases + '</b></span>';
        h += '<span style="color:#fbbf24;">Most Common: <b>' + d.most_common_complexity + '</b></span></div>';
        h += '<table style="width:100%;font-size:0.6rem;border-collapse:collapse;">';
        h += '<tr style="color:#94a3b8;"><th style="text-align:left;padding:1px 3px;">Level</th><th>Cases</th><th>Witnesses</th><th>Pages</th><th>Time(min)</th><th>Cost</th></tr>';
        Object.keys(d.complexity_distribution).forEach(function(level) {
            var cd = d.complexity_distribution[level];
            var lc = level === 'Simple' ? '#34d399' : level === 'Moderate' ? '#60a5fa' : level === 'Complex' ? '#fbbf24' : level === 'Highly Complex' ? '#f87171' : '#a78bfa';
            h += '<tr><td style="color:' + lc + ';padding:1px 3px;font-weight:700;">' + level + '</td>';
            h += '<td style="text-align:center;color:#e2e8f0;">' + cd.case_count + '</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + cd.avg_witnesses + '</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + cd.avg_pages_testimony + '</td>';
            h += '<td style="text-align:center;color:#60a5fa;">' + cd.avg_processing_time_min + '</td>';
            h += '<td style="text-align:center;color:#fbbf24;">$' + cd.avg_cost_usd + '</td></tr>';
        });
        h += '</table>';
        h += '<h4 style="color:#f87171;font-size:0.72rem;margin:6px 0 3px;">⚠️ Bottlenecks</h4>';
        d.processing_bottlenecks.forEach(function(b) {
            h += '<div style="font-size:0.58rem;color:#fbbf24;padding:1px 0;">• ' + b + '</div>';
        });
        h += '<h4 style="color:#34d399;font-size:0.72rem;margin:6px 0 3px;">📈 Monthly Trend</h4>';
        d.monthly_trend.slice(-3).forEach(function(m) {
            h += '<div style="display:flex;justify-content:space-between;font-size:0.58rem;padding:1px 0;">';
            h += '<span style="color:#94a3b8;">' + m.month + '</span>';
            h += '<span style="color:#e2e8f0;">Cases: ' + m.total_cases + ' | Complexity: ' + m.avg_complexity_score + ' | Complex%: ' + m.complex_case_pct + '%</span></div>';
        });
        h += '<h4 style="color:#60a5fa;font-size:0.72rem;margin:6px 0 3px;">💡 Scaling</h4>';
        d.scaling_recommendations.forEach(function(s) {
            h += '<div style="font-size:0.58rem;color:#94a3b8;padding:1px 0;">• ' + s + '</div>';
        });
        h += '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load case complexity distribution</p>'; }
}
loadCaseComplexityDistPanel();
document.getElementById('case-complexity-distribution-refresh')?.addEventListener('click', loadCaseComplexityDistPanel);
setTimeout(loadCaseComplexityDistPanel, 85000);

// ── Feature Adoption Dashboard Panel ────────────────────────────
async function loadFeatureAdoptionPanel() {
    var el = document.getElementById('feature-adoption-content');
    if (!el) return;
    try {
        var r = await fetch('/api/admin/feature-adoption', { headers: authHeaders() });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var d = await r.json();
        var h = '<div style="font-size:0.75rem;">';
        h += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px;">';
        h += '<span style="color:#60a5fa;">Features: <b>' + d.total_features_tracked + '</b></span>';
        h += '<span style="color:#34d399;">Uses Today: <b>' + d.total_uses_today.toLocaleString() + '</b></span>';
        h += '<span style="color:#fbbf24;">Most Popular: <b>' + d.most_popular_feature + '</b></span></div>';
        h += '<h4 style="color:#a78bfa;font-size:0.72rem;margin:4px 0 3px;">📊 Adoption by Category</h4>';
        Object.keys(d.adoption_by_category).forEach(function(cat) {
            var val = d.adoption_by_category[cat];
            var cc = val >= 70 ? '#34d399' : val >= 40 ? '#fbbf24' : '#f87171';
            h += '<div style="font-size:0.6rem;padding:1px 0;"><span style="color:#94a3b8;">' + cat + ':</span> <span style="color:' + cc + ';font-weight:700;">' + val + '%</span></div>';
        });
        h += '<table style="width:100%;font-size:0.6rem;border-collapse:collapse;margin-top:4px;">';
        h += '<tr style="color:#94a3b8;"><th style="text-align:left;padding:1px 3px;">Feature</th><th>Today</th><th>Week</th><th>Rating</th><th>Repeat%</th><th>Trend</th></tr>';
        d.feature_metrics.slice(0, 10).forEach(function(f) {
            var tc = f.trend.includes('Growing') ? '#34d399' : f.trend.includes('Stable') ? '#fbbf24' : '#f87171';
            h += '<tr><td style="color:#e2e8f0;padding:1px 3px;">' + f.feature + '</td>';
            h += '<td style="text-align:center;color:#60a5fa;">' + f.uses_today + '</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + f.uses_this_week + '</td>';
            h += '<td style="text-align:center;color:#fbbf24;">★' + f.satisfaction_rating + '</td>';
            h += '<td style="text-align:center;color:#a78bfa;">' + f.repeat_usage_pct + '%</td>';
            h += '<td style="text-align:center;color:' + tc + ';">' + f.trend + '</td></tr>';
        });
        h += '</table>';
        h += '<h4 style="color:#34d399;font-size:0.72rem;margin:6px 0 3px;">💡 Insights</h4>';
        d.insights.forEach(function(i) { h += '<div style="font-size:0.58rem;color:#e2e8f0;padding:1px 0;">• ' + i + '</div>'; });
        h += '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load feature adoption</p>'; }
}
loadFeatureAdoptionPanel();
document.getElementById('feature-adoption-refresh')?.addEventListener('click', loadFeatureAdoptionPanel);
setTimeout(loadFeatureAdoptionPanel, 90000);

// ── Error Rate Monitor Panel ────────────────────────────────────
async function loadErrorRateMonitorPanel() {
    var el = document.getElementById('error-rate-monitor-content');
    if (!el) return;
    try {
        var r = await fetch('/api/admin/error-rate-monitor', { headers: authHeaders() });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var d = await r.json();
        var sc = d.system_status === 'Healthy' ? '#34d399' : d.system_status === 'Degraded' ? '#fbbf24' : '#f87171';
        var h = '<div style="font-size:0.75rem;">';
        h += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px;">';
        h += '<span style="color:' + sc + ';">Status: <b>' + d.system_status + '</b></span>';
        h += '<span style="color:#60a5fa;">Requests: <b>' + d.total_requests_today.toLocaleString() + '</b></span>';
        h += '<span style="color:#f87171;">Errors: <b>' + d.total_errors_today + '</b> (' + d.overall_error_rate_pct + '%)</span>';
        h += '<span style="color:#34d399;">Uptime: <b>' + d.uptime_pct + '%</b></span></div>';
        h += '<h4 style="color:#fbbf24;font-size:0.72rem;margin:4px 0 3px;">⚠️ Error Type Breakdown</h4>';
        Object.keys(d.error_type_breakdown).forEach(function(et) {
            var count = d.error_type_breakdown[et];
            if (count > 0) {
                var ec = count > 15 ? '#f87171' : count > 5 ? '#fbbf24' : '#94a3b8';
                h += '<div style="font-size:0.6rem;padding:1px 0;"><span style="color:' + ec + ';">' + et + ': <b>' + count + '</b></span></div>';
            }
        });
        h += '<table style="width:100%;font-size:0.6rem;border-collapse:collapse;margin-top:4px;">';
        h += '<tr style="color:#94a3b8;"><th style="text-align:left;padding:1px 3px;">Endpoint</th><th>Reqs</th><th>Errs</th><th>Rate%</th><th>Avg ms</th><th>Status</th></tr>';
        d.endpoint_errors.slice(0, 8).forEach(function(ep) {
            var epc = ep.status === 'Healthy' ? '#34d399' : ep.status === 'Warning' ? '#fbbf24' : '#f87171';
            var short = ep.endpoint.replace('/api/sessions/*/', '').replace('/api/admin/', 'admin/');
            h += '<tr><td style="color:#e2e8f0;padding:1px 3px;">' + short + '</td>';
            h += '<td style="text-align:center;color:#60a5fa;">' + ep.total_requests_today + '</td>';
            h += '<td style="text-align:center;color:#f87171;">' + ep.errors_today + '</td>';
            h += '<td style="text-align:center;color:' + epc + ';">' + ep.error_rate_pct + '%</td>';
            h += '<td style="text-align:center;color:#94a3b8;">' + ep.avg_response_time_ms + '</td>';
            h += '<td style="text-align:center;color:' + epc + ';">' + ep.status + '</td></tr>';
        });
        h += '</table>';
        h += '<h4 style="color:#60a5fa;font-size:0.72rem;margin:6px 0 3px;">📊 Reliability</h4>';
        h += '<div style="font-size:0.58rem;color:#94a3b8;">MTBF: ' + d.reliability_metrics.mean_time_between_failures_hours + 'h | MTTR: ' + d.reliability_metrics.mean_time_to_recovery_min + 'min | Error Budget: ' + d.reliability_metrics.error_budget_remaining_pct + '%</div>';
        h += '<h4 style="color:#34d399;font-size:0.72rem;margin:6px 0 3px;">💡 Recommendations</h4>';
        d.recommendations.forEach(function(rec) { h += '<div style="font-size:0.58rem;color:#e2e8f0;padding:1px 0;">• ' + rec + '</div>'; });
        h += '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load error rate monitor</p>'; }
}
loadErrorRateMonitorPanel();
document.getElementById('error-rate-monitor-refresh')?.addEventListener('click', loadErrorRateMonitorPanel);
setTimeout(loadErrorRateMonitorPanel, 95000);

// ── User Engagement Heatmap ───────────────────────────────────
async function loadUserEngagementHeatmapPanel() {
    var el = document.getElementById('user-engagement-heatmap-content');
    if (!el) return;
    try {
        var r = await fetch('/api/admin/user-engagement-heatmap', {headers:{'Authorization':'Bearer '+localStorage.getItem('admin_token')}});
        var d = await r.json(); if (!r.ok) throw new Error(d.detail||'Failed');
        var h = '<div style="padding:4px;">';
        h += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:8px;">';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#60a5fa;font-size:0.95rem;font-weight:700;">' + d.total_weekly_sessions + '</div><div style="color:#94a3b8;font-size:0.55rem;">Weekly Sessions</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#f59e0b;font-size:0.85rem;font-weight:700;">' + d.peak_hour + '</div><div style="color:#94a3b8;font-size:0.55rem;">Peak Hour</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#34d399;font-size:0.85rem;font-weight:700;">' + d.peak_day + '</div><div style="color:#94a3b8;font-size:0.55rem;">Peak Day</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#a78bfa;font-size:0.85rem;font-weight:700;">' + d.avg_sessions_per_day + '</div><div style="color:#94a3b8;font-size:0.55rem;">Avg/Day</div></div></div>';
        // Mini heatmap table
        h += '<h4 style="color:#60a5fa;font-size:0.68rem;margin:6px 0 3px;">📅 Activity Heatmap (sessions by hour)</h4>';
        h += '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:0.45rem;">';
        h += '<tr><td style="color:#94a3b8;padding:1px;"></td>';
        for (var hr = 6; hr <= 22; hr += 2) h += '<td style="color:#94a3b8;text-align:center;padding:1px;">' + hr + '</td>';
        h += '</tr>';
        var days = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
        days.forEach(function(day) {
            h += '<tr><td style="color:#94a3b8;padding:1px;white-space:nowrap;">' + day.substr(0,3) + '</td>';
            for (var hr = 6; hr <= 22; hr += 2) {
                var val = (d.heatmap[day] || {})[String(hr)] || 0;
                var intensity = Math.min(255, Math.round(val * 5));
                var bg = 'rgba(96,165,250,' + (intensity/255).toFixed(2) + ')';
                h += '<td style="text-align:center;padding:1px 2px;background:' + bg + ';color:#fff;border-radius:2px;">' + val + '</td>';
            }
            h += '</tr>';
        });
        h += '</table></div>';
        h += '<h4 style="color:#34d399;font-size:0.68rem;margin:6px 0 3px;">⏱️ Feature Usage by Time</h4>';
        d.feature_usage_by_time.forEach(function(f) {
            h += '<div style="font-size:0.55rem;color:#e2e8f0;padding:1px 0;">• ' + f.feature + ': peak ' + f.peak_usage_hour + ', avg ' + f.avg_session_minutes + ' min</div>';
        });
        h += '<h4 style="color:#f59e0b;font-size:0.68rem;margin:6px 0 3px;">📋 Capacity Recommendations</h4>';
        d.capacity_recommendations.forEach(function(r) { h += '<div style="font-size:0.55rem;color:#e2e8f0;padding:1px 0;">• ' + r + '</div>'; });
        h += '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load engagement heatmap</p>'; }
}
loadUserEngagementHeatmapPanel();
document.getElementById('user-engagement-heatmap-refresh')?.addEventListener('click', loadUserEngagementHeatmapPanel);
setTimeout(loadUserEngagementHeatmapPanel, 100000);

// ── Case Resolution Metrics ───────────────────────────────────
async function loadCaseResolutionMetricsPanel() {
    var el = document.getElementById('case-resolution-metrics-content');
    if (!el) return;
    try {
        var r = await fetch('/api/admin/case-resolution-metrics', {headers:{'Authorization':'Bearer '+localStorage.getItem('admin_token')}});
        var d = await r.json(); if (!r.ok) throw new Error(d.detail||'Failed');
        var h = '<div style="padding:4px;">';
        h += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:8px;">';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#60a5fa;font-size:0.95rem;font-weight:700;">' + d.total_cases_tracked + '</div><div style="color:#94a3b8;font-size:0.55rem;">Total Cases</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#34d399;font-size:0.85rem;font-weight:700;">' + d.outcomes.settled.percentage + '%</div><div style="color:#94a3b8;font-size:0.55rem;">Settled</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#f59e0b;font-size:0.85rem;font-weight:700;">' + d.outcomes.tried_to_verdict.percentage + '%</div><div style="color:#94a3b8;font-size:0.55rem;">Tried</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#a78bfa;font-size:0.85rem;font-weight:700;">' + d.outcomes.ongoing.count + '</div><div style="color:#94a3b8;font-size:0.55rem;">Ongoing</div></div></div>';
        h += '<h4 style="color:#60a5fa;font-size:0.68rem;margin:6px 0 3px;">⏳ Resolution Times</h4>';
        h += '<div style="font-size:0.55rem;color:#94a3b8;">Settlement: ' + d.resolution_times.average_days_to_settlement + ' days | Trial: ' + d.resolution_times.average_days_to_trial + ' days | Dismissal: ' + d.resolution_times.average_days_to_dismissal + ' days</div>';
        h += '<h4 style="color:#34d399;font-size:0.68rem;margin:6px 0 3px;">🚀 Platform Impact</h4>';
        h += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:3px;">';
        h += '<div style="font-size:0.52rem;color:#e2e8f0;text-align:center;background:#1e293b;padding:3px;border-radius:3px;"><div style="color:#34d399;font-weight:700;">' + d.platform_impact.avg_analysis_time_saved_hours + 'h</div>Time Saved</div>';
        h += '<div style="font-size:0.52rem;color:#e2e8f0;text-align:center;background:#1e293b;padding:3px;border-radius:3px;"><div style="color:#60a5fa;font-weight:700;">' + d.platform_impact.contradiction_detection_accuracy_pct + '%</div>Accuracy</div>';
        h += '<div style="font-size:0.52rem;color:#e2e8f0;text-align:center;background:#1e293b;padding:3px;border-radius:3px;"><div style="color:#f59e0b;font-weight:700;">$' + d.platform_impact.estimated_cost_savings_per_case.toLocaleString() + '</div>Savings/Case</div></div>';
        h += '<h4 style="color:#a78bfa;font-size:0.68rem;margin:6px 0 3px;">📈 Monthly Trends</h4>';
        h += '<table style="width:100%;border-collapse:collapse;font-size:0.5rem;">';
        h += '<tr><th style="color:#94a3b8;text-align:left;padding:1px 3px;">Month</th><th style="color:#94a3b8;text-align:center;">Resolved</th><th style="color:#94a3b8;text-align:center;">Avg Days</th><th style="color:#94a3b8;text-align:center;">Settlement%</th></tr>';
        d.monthly_trends.forEach(function(m) {
            h += '<tr><td style="color:#e2e8f0;padding:1px 3px;">' + m.month + '</td>';
            h += '<td style="text-align:center;color:#60a5fa;">' + m.cases_resolved + '</td>';
            h += '<td style="text-align:center;color:#f59e0b;">' + m.avg_resolution_days + '</td>';
            h += '<td style="text-align:center;color:#34d399;">' + m.settlement_rate_pct + '%</td></tr>';
        });
        h += '</table>';
        h += '<h4 style="color:#f59e0b;font-size:0.68rem;margin:6px 0 3px;">💡 Insights</h4>';
        d.insights.forEach(function(i) { h += '<div style="font-size:0.55rem;color:#e2e8f0;padding:1px 0;">• ' + i + '</div>'; });
        h += '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load case resolution metrics</p>'; }
}
loadCaseResolutionMetricsPanel();
document.getElementById('case-resolution-metrics-refresh')?.addEventListener('click', loadCaseResolutionMetricsPanel);
setTimeout(loadCaseResolutionMetricsPanel, 105000);

// ── AI Model Performance Panel ────────────────────────────────
async function loadAiModelPerformancePanel() {
    var el = document.getElementById('ai-model-performance-content');
    if (!el) return;
    try {
        var r = await fetch('/api/admin/ai-model-performance');
        var d = await r.json(); if (!r.ok) throw new Error('Failed');
        var h = '<div style="border:1px solid #334155;border-radius:6px;padding:8px;background:#0f172a;">';
        h += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:8px;">';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#60a5fa;font-size:0.95rem;font-weight:700;">' + d.model_stats.total_api_calls_24h.toLocaleString() + '</div><div style="color:#94a3b8;font-size:0.55rem;">API Calls (24h)</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#34d399;font-size:0.95rem;font-weight:700;">' + d.model_stats.avg_response_time_sec + 's</div><div style="color:#94a3b8;font-size:0.55rem;">Avg Latency</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#f59e0b;font-size:0.95rem;font-weight:700;">$' + d.model_stats.estimated_cost_24h_usd + '</div><div style="color:#94a3b8;font-size:0.55rem;">Cost (24h)</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#34d399;font-size:0.95rem;font-weight:700;">' + d.model_stats.uptime_pct + '%</div><div style="color:#94a3b8;font-size:0.55rem;">Uptime</div></div></div>';
        h += '<h4 style="color:#60a5fa;font-size:0.68rem;margin:6px 0 3px;">📊 Feature Performance</h4>';
        h += '<table style="width:100%;border-collapse:collapse;font-size:0.5rem;">';
        h += '<tr><th style="color:#94a3b8;text-align:left;padding:1px 3px;">Feature</th><th style="color:#94a3b8;text-align:center;">Calls</th><th style="color:#94a3b8;text-align:center;">Latency</th><th style="color:#94a3b8;text-align:center;">Quality</th><th style="color:#94a3b8;text-align:center;">Cache%</th></tr>';
        d.feature_metrics.slice(0, 8).forEach(function(f) {
            var qc = f.avg_quality_score > 4.5 ? '#34d399' : f.avg_quality_score > 4.0 ? '#60a5fa' : '#f59e0b';
            h += '<tr><td style="color:#e2e8f0;padding:1px 3px;">' + f.feature + '</td>';
            h += '<td style="text-align:center;color:#60a5fa;">' + f.total_calls_24h + '</td>';
            h += '<td style="text-align:center;color:#f59e0b;">' + f.avg_response_time_sec + 's</td>';
            h += '<td style="text-align:center;color:' + qc + ';">' + f.avg_quality_score + '</td>';
            h += '<td style="text-align:center;color:#a78bfa;">' + f.cache_hit_rate_pct + '%</td></tr>';
        });
        h += '</table>';
        if (d.performance_alerts.length > 0) {
            h += '<h4 style="color:#f87171;font-size:0.68rem;margin:6px 0 3px;">⚠️ Alerts</h4>';
            d.performance_alerts.forEach(function(a) { h += '<div style="font-size:0.52rem;color:#f87171;padding:1px 0;">• ' + a + '</div>'; });
        }
        h += '<h4 style="color:#34d399;font-size:0.68rem;margin:6px 0 3px;">💡 Optimizations</h4>';
        d.optimization_suggestions.forEach(function(s) { h += '<div style="font-size:0.52rem;color:#e2e8f0;padding:1px 0;">• ' + s + '</div>'; });
        h += '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load AI model performance</p>'; }
}
loadAiModelPerformancePanel();
document.getElementById('ai-model-performance-refresh')?.addEventListener('click', loadAiModelPerformancePanel);
setTimeout(loadAiModelPerformancePanel, 110000);

// ── Data Storage Analytics Panel ──────────────────────────────
async function loadDataStorageAnalyticsPanel() {
    var el = document.getElementById('data-storage-analytics-content');
    if (!el) return;
    try {
        var r = await fetch('/api/admin/data-storage-analytics');
        var d = await r.json(); if (!r.ok) throw new Error('Failed');
        var h = '<div style="border:1px solid #334155;border-radius:6px;padding:8px;background:#0f172a;">';
        h += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:8px;">';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#60a5fa;font-size:0.95rem;font-weight:700;">' + d.total_sessions.toLocaleString() + '</div><div style="color:#94a3b8;font-size:0.55rem;">Sessions</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#34d399;font-size:0.95rem;font-weight:700;">' + d.total_testimonies.toLocaleString() + '</div><div style="color:#94a3b8;font-size:0.55rem;">Testimonies</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#f59e0b;font-size:0.95rem;font-weight:700;">' + d.total_storage_gb + ' GB</div><div style="color:#94a3b8;font-size:0.55rem;">Total Storage</div></div>';
        var uc = d.storage_health.capacity_used_pct > 80 ? '#f87171' : d.storage_health.capacity_used_pct > 60 ? '#f59e0b' : '#34d399';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:' + uc + ';font-size:0.95rem;font-weight:700;">' + d.storage_health.capacity_used_pct + '%</div><div style="color:#94a3b8;font-size:0.55rem;">Used</div></div></div>';
        h += '<h4 style="color:#60a5fa;font-size:0.68rem;margin:6px 0 3px;">📁 Storage Breakdown</h4>';
        h += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:3px;">';
        var cats = [
            {l:'Text',v:d.storage_breakdown.testimony_text_gb,c:'#60a5fa'},
            {l:'Audio',v:d.storage_breakdown.audio_files_gb,c:'#34d399'},
            {l:'Video',v:d.storage_breakdown.video_files_gb,c:'#a78bfa'},
            {l:'Cache',v:d.storage_breakdown.analysis_cache_gb,c:'#f59e0b'},
            {l:'Reports',v:d.storage_breakdown.reports_exports_gb,c:'#f87171'},
            {l:'Database',v:d.storage_breakdown.database_gb,c:'#94a3b8'},
        ];
        cats.forEach(function(c) {
            h += '<div style="font-size:0.52rem;color:#e2e8f0;text-align:center;background:#1e293b;padding:3px;border-radius:3px;"><div style="color:' + c.c + ';font-weight:700;">' + c.v + ' GB</div>' + c.l + '</div>';
        });
        h += '</div>';
        h += '<h4 style="color:#34d399;font-size:0.68rem;margin:6px 0 3px;">🏆 Top Storage Consumers</h4>';
        d.top_storage_consumers.forEach(function(tc) {
            h += '<div style="font-size:0.52rem;color:#e2e8f0;padding:1px 0;">' + tc.case_name + ' - <span style="color:#f59e0b;">' + tc.storage_mb + ' MB</span> (' + tc.testimony_count + ' testimonies)</div>';
        });
        h += '<div style="font-size:0.52rem;color:#94a3b8;margin-top:4px;">Est. ' + d.storage_health.estimated_days_until_full + ' days until full | Cleanup: ' + d.storage_health.cleanup_candidates_gb + ' GB available</div>';
        h += '<h4 style="color:#f59e0b;font-size:0.68rem;margin:6px 0 3px;">💡 Recommendations</h4>';
        d.recommendations.forEach(function(r) { h += '<div style="font-size:0.52rem;color:#e2e8f0;padding:1px 0;">• ' + r + '</div>'; });
        h += '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load storage analytics</p>'; }
}
loadDataStorageAnalyticsPanel();
document.getElementById('data-storage-analytics-refresh')?.addEventListener('click', loadDataStorageAnalyticsPanel);
setTimeout(loadDataStorageAnalyticsPanel, 115000);

// ── Client Satisfaction Tracker Panel ──────────────────────────
async function loadClientSatisfactionTrackerPanel() {
    var el = document.getElementById('client-satisfaction-tracker-content');
    if (!el) return;
    try {
        var r = await fetch('/api/admin/client-satisfaction-tracker', {headers:{'Authorization':'Bearer admin'}});
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var d = await r.json();
        var h = '<div style="font-size:0.7rem;">';
        h += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:8px;">';
        var nc = d.nps_score >= 70 ? '#34d399' : d.nps_score >= 50 ? '#f59e0b' : '#f87171';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:' + nc + ';font-size:0.95rem;font-weight:700;">' + d.nps_score + '</div><div style="color:#94a3b8;font-size:0.55rem;">NPS Score</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#60a5fa;font-size:0.95rem;font-weight:700;">' + d.overall_satisfaction + '/5</div><div style="color:#94a3b8;font-size:0.55rem;">Satisfaction</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#a78bfa;font-size:0.95rem;font-weight:700;">' + d.total_responses + '</div><div style="color:#94a3b8;font-size:0.55rem;">Responses</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#34d399;font-size:0.95rem;font-weight:700;">' + d.retention_metrics.monthly_active_rate_pct + '%</div><div style="color:#94a3b8;font-size:0.55rem;">Active Rate</div></div></div>';
        h += '<h4 style="color:#60a5fa;font-size:0.68rem;margin:6px 0 3px;">⭐ Feature Satisfaction</h4>';
        d.satisfaction_by_feature.forEach(function(f) {
            var sc = f.satisfaction_score >= 4.5 ? '#34d399' : f.satisfaction_score >= 3.5 ? '#f59e0b' : '#f87171';
            var tc = f.trend === 'improving' ? '#34d399' : f.trend === 'stable' ? '#60a5fa' : '#f87171';
            var barW = Math.min(f.satisfaction_score / 5 * 100, 100);
            h += '<div style="font-size:0.52rem;padding:2px 0;">';
            h += '<div style="display:flex;justify-content:space-between;"><span style="color:#e2e8f0;">' + f.feature + '</span><span style="color:' + sc + ';">' + f.satisfaction_score + '/5 <span style="color:' + tc + ';font-size:0.42rem;">(' + f.trend + ')</span></span></div>';
            h += '<div style="background:#0f172a;border-radius:2px;height:3px;"><div style="background:' + sc + ';height:3px;border-radius:2px;width:' + barW + '%;"></div></div></div>';
        });
        h += '<h4 style="color:#f59e0b;font-size:0.68rem;margin:6px 0 3px;">📝 Recent Feedback</h4>';
        d.recent_feedback.forEach(function(fb) {
            var stars = '⭐'.repeat(fb.rating);
            h += '<div style="font-size:0.5rem;background:#1e293b;padding:3px;border-radius:3px;margin:2px 0;">';
            h += '<div style="color:#f59e0b;">' + stars + ' <span style="color:#94a3b8;font-size:0.42rem;">' + fb.date + ' | ' + fb.feature_mentioned + '</span></div>';
            h += '<div style="color:#e2e8f0;font-style:italic;">"' + fb.comment + '"</div></div>';
        });
        h += '<h4 style="color:#a78bfa;font-size:0.68rem;margin:6px 0 3px;">🎯 Top Feature Requests</h4>';
        d.top_requests.forEach(function(req) { h += '<div style="font-size:0.52rem;color:#e2e8f0;padding:1px 0;">• ' + req + '</div>'; });
        h += '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load satisfaction tracker</p>'; }
}
loadClientSatisfactionTrackerPanel();
document.getElementById('client-satisfaction-tracker-refresh')?.addEventListener('click', loadClientSatisfactionTrackerPanel);
setTimeout(loadClientSatisfactionTrackerPanel, 120000);

// ── Compliance Monitor Panel ───────────────────────────────────
async function loadComplianceMonitorPanel() {
    var el = document.getElementById('compliance-monitor-content');
    if (!el) return;
    try {
        var r = await fetch('/api/admin/compliance-monitor', {headers:{'Authorization':'Bearer admin'}});
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var d = await r.json();
        var h = '<div style="font-size:0.7rem;">';
        h += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:8px;">';
        var oc = d.overall_compliance_score >= 85 ? '#34d399' : d.overall_compliance_score >= 70 ? '#f59e0b' : '#f87171';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:' + oc + ';font-size:0.95rem;font-weight:700;">' + d.overall_compliance_score + '</div><div style="color:#94a3b8;font-size:0.55rem;">Score</div></div>';
        var stc = d.compliance_status === 'Compliant' ? '#34d399' : d.compliance_status === 'Needs Attention' ? '#f59e0b' : '#f87171';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:' + stc + ';font-size:0.7rem;font-weight:700;">' + d.compliance_status + '</div><div style="color:#94a3b8;font-size:0.55rem;">Status</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#f87171;font-size:0.95rem;font-weight:700;">' + d.non_compliant_count + '</div><div style="color:#94a3b8;font-size:0.55rem;">Issues</div></div>';
        h += '<div style="background:#1e293b;padding:4px;border-radius:4px;text-align:center;"><div style="color:#f59e0b;font-size:0.95rem;font-weight:700;">' + d.warning_count + '</div><div style="color:#94a3b8;font-size:0.55rem;">Warnings</div></div></div>';
        h += '<h4 style="color:#60a5fa;font-size:0.68rem;margin:6px 0 3px;">🛡️ Compliance Areas</h4>';
        d.compliance_areas.forEach(function(a) {
            var ac = a.status === 'Compliant' ? '#34d399' : a.status === 'Warning' ? '#f59e0b' : '#f87171';
            var barW = Math.min(a.score, 100);
            h += '<div style="font-size:0.52rem;padding:2px 0;">';
            h += '<div style="display:flex;justify-content:space-between;"><span style="color:#e2e8f0;">' + a.area + ' <span style="color:#94a3b8;font-size:0.42rem;">(' + a.standard + ')</span></span><span style="color:' + ac + ';">' + a.status + ' (' + a.score + ')</span></div>';
            h += '<div style="background:#0f172a;border-radius:2px;height:3px;"><div style="background:' + ac + ';height:3px;border-radius:2px;width:' + barW + '%;"></div></div></div>';
        });
        h += '<h4 style="color:#f59e0b;font-size:0.68rem;margin:6px 0 3px;">🔐 PII Protection</h4>';
        var pm = d.data_privacy_metrics;
        var mc = pm.masking_rate_pct >= 95 ? '#34d399' : pm.masking_rate_pct >= 85 ? '#f59e0b' : '#f87171';
        h += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:3px;">';
        h += '<div style="background:#1e293b;padding:3px;border-radius:3px;text-align:center;"><div style="color:#60a5fa;font-weight:700;font-size:0.65rem;">' + pm.pii_instances_detected + '</div><div style="font-size:0.42rem;color:#94a3b8;">Detected</div></div>';
        h += '<div style="background:#1e293b;padding:3px;border-radius:3px;text-align:center;"><div style="color:' + mc + ';font-weight:700;font-size:0.65rem;">' + pm.masking_rate_pct + '%</div><div style="font-size:0.42rem;color:#94a3b8;">Masked</div></div>';
        h += '<div style="background:#1e293b;padding:3px;border-radius:3px;text-align:center;"><div style="color:#a78bfa;font-weight:700;font-size:0.65rem;">' + pm.data_subject_requests + '</div><div style="font-size:0.42rem;color:#94a3b8;">DSR Requests</div></div></div>';
        h += '<h4 style="color:#a78bfa;font-size:0.68rem;margin:6px 0 3px;">📅 Upcoming Audits</h4>';
        d.upcoming_audits.forEach(function(ua) {
            h += '<div style="font-size:0.52rem;color:#e2e8f0;padding:1px 0;">📋 ' + ua.audit + ' — <span style="color:#f59e0b;">' + ua.date + '</span></div>';
        });
        h += '<h4 style="color:#34d399;font-size:0.68rem;margin:6px 0 3px;">💡 Recommendations</h4>';
        d.recommendations.forEach(function(rec) { h += '<div style="font-size:0.52rem;color:#e2e8f0;padding:1px 0;">• ' + rec + '</div>'; });
        h += '</div>';
        el.innerHTML = h;
    } catch(e) { el.innerHTML = '<p style="color:#f87171;">Failed to load compliance monitor</p>'; }
}
loadComplianceMonitorPanel();
document.getElementById('compliance-monitor-refresh')?.addEventListener('click', loadComplianceMonitorPanel);
setTimeout(loadComplianceMonitorPanel, 125000);

// ============================================================
// Feature Adoption Funnel
// ============================================================
async function loadFeatureAdoptionFunnel() {
    try {
        var r = await fetch('/api/admin/feature-adoption-funnel', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('admin_token') } });
        var d = await r.json();
        var el = document.getElementById('feature-adoption-funnel-content');
        if (!el) return;
        var html = '<div style="font-size:0.55rem;">';
        html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-bottom:6px;">';
        html += '<div style="background:#2d3748;padding:6px;border-radius:4px;text-align:center;"><div style="color:#b794f4;font-size:0.7rem;font-weight:bold;">' + d.total_users + '</div><div style="color:#a0aec0;font-size:0.42rem;">Total Users</div></div>';
        html += '<div style="background:#2d3748;padding:6px;border-radius:4px;text-align:center;"><div style="color:#68d391;font-size:0.7rem;font-weight:bold;">' + d.overall_conversion_rate_pct + '%</div><div style="color:#a0aec0;font-size:0.42rem;">Full Conversion</div></div>';
        html += '<div style="background:#2d3748;padding:6px;border-radius:4px;text-align:center;"><div style="color:#fc8181;font-size:0.7rem;font-weight:bold;">' + d.biggest_drop_off_pct + '%</div><div style="color:#a0aec0;font-size:0.42rem;">Biggest Drop</div></div>';
        html += '</div>';
        html += '<div style="color:#e2e8f0;font-weight:bold;margin-bottom:3px;">Funnel Stages:</div>';
        d.funnel_stages.forEach(function(s) {
            var barW = Math.max(s.pct, 5);
            html += '<div style="margin:2px 0;display:flex;align-items:center;gap:4px;">';
            html += '<div style="width:120px;font-size:0.42rem;color:#a0aec0;text-align:right;">' + s.stage + '</div>';
            html += '<div style="flex:1;background:#4a5568;border-radius:2px;height:14px;position:relative;">';
            html += '<div style="width:' + barW + '%;background:linear-gradient(90deg,#b794f4,#805ad5);height:100%;border-radius:2px;"></div>';
            html += '<span style="position:absolute;right:4px;top:1px;font-size:0.4rem;color:#fff;">' + s.users + ' (' + s.pct + '%)</span>';
            html += '</div></div>';
        });
        html += '<div style="margin-top:6px;color:#e2e8f0;font-weight:bold;">Feature Adoption:</div>';
        Object.keys(d.feature_adoption).slice(0, 5).forEach(function(f) {
            var fa = d.feature_adoption[f];
            html += '<div style="font-size:0.42rem;color:#cbd5e0;padding:1px 0;">' + f + ': <span style="color:#b794f4;">' + fa.adoption_rate_pct + '%</span> (' + fa.users + ' users, ' + fa.avg_uses_per_user + ' uses/user)</div>';
        });
        html += '</div>';
        el.innerHTML = html;
    } catch(e) { console.error('Feature adoption funnel error:', e); }
}
function refreshFeatureAdoptionFunnel() { loadFeatureAdoptionFunnel(); }
document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('feature-adoption-funnel-refresh');
    if (btn) btn.addEventListener('click', refreshFeatureAdoptionFunnel);
    loadFeatureAdoptionFunnel();
});

// ============================================================
// Infrastructure Monitor
// ============================================================
async function loadInfrastructureMonitor() {
    try {
        var r = await fetch('/api/admin/infrastructure-monitor', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('admin_token') } });
        var d = await r.json();
        var el = document.getElementById('infrastructure-monitor-content');
        if (!el) return;
        var healthColor = d.overall_health === 'Healthy' ? '#68d391' : '#fc8181';
        var html = '<div style="font-size:0.55rem;">';
        html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:6px;">';
        html += '<div style="background:#2d3748;padding:6px;border-radius:4px;text-align:center;"><div style="color:' + healthColor + ';font-size:0.65rem;font-weight:bold;">' + d.overall_health + '</div><div style="color:#a0aec0;font-size:0.42rem;">Status</div></div>';
        html += '<div style="background:#2d3748;padding:6px;border-radius:4px;text-align:center;"><div style="color:#63b3ed;font-size:0.65rem;font-weight:bold;">' + d.system_metrics.cpu_usage_pct + '%</div><div style="color:#a0aec0;font-size:0.42rem;">CPU</div></div>';
        html += '<div style="background:#2d3748;padding:6px;border-radius:4px;text-align:center;"><div style="color:#b794f4;font-size:0.65rem;font-weight:bold;">' + d.system_metrics.memory_usage_pct + '%</div><div style="color:#a0aec0;font-size:0.42rem;">Memory</div></div>';
        html += '<div style="background:#2d3748;padding:6px;border-radius:4px;text-align:center;"><div style="color:#f6ad55;font-size:0.65rem;font-weight:bold;">' + d.system_metrics.disk_usage_pct + '%</div><div style="color:#a0aec0;font-size:0.42rem;">Disk</div></div>';
        html += '</div>';
        html += '<div style="color:#e2e8f0;font-weight:bold;margin-bottom:3px;">Services:</div>';
        d.services.forEach(function(s) {
            var sColor = s.status === 'Healthy' ? '#68d391' : '#fc8181';
            html += '<div style="font-size:0.42rem;color:#cbd5e0;padding:1px 0;display:flex;justify-content:space-between;">';
            html += '<span>' + s.service + '</span>';
            html += '<span style="color:' + sColor + ';">' + s.status + ' (' + s.uptime_pct + '%, ' + s.response_time_ms + 'ms)</span>';
            html += '</div>';
        });
        html += '<div style="margin-top:4px;color:#e2e8f0;font-weight:bold;">Performance:</div>';
        html += '<div style="font-size:0.42rem;color:#a0aec0;">Avg Response: ' + d.performance_summary.avg_response_time_ms + 'ms | Requests Today: ' + d.performance_summary.total_requests_today + ' | Error Rate: ' + d.performance_summary.overall_error_rate_pct + '%</div>';
        if (d.recent_incidents.length) {
            html += '<div style="margin-top:4px;color:#e2e8f0;font-weight:bold;">Recent Incidents:</div>';
            d.recent_incidents.forEach(function(inc) {
                var iColor = inc.severity === 'Warning' ? '#ecc94b' : '#63b3ed';
                html += '<div style="font-size:0.42rem;color:#cbd5e0;padding:1px 0;"><span style="color:' + iColor + ';">[' + inc.severity + ']</span> ' + inc.description + ' <span style="color:#a0aec0;">(' + inc.time + ')</span></div>';
            });
        }
        html += '</div>';
        el.innerHTML = html;
    } catch(e) { console.error('Infrastructure monitor error:', e); }
}
function refreshInfrastructureMonitor() { loadInfrastructureMonitor(); }
document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('infrastructure-monitor-refresh');
    if (btn) btn.addEventListener('click', refreshInfrastructureMonitor);
    loadInfrastructureMonitor();
});

// ============================================================
// Admin: API Usage Monitor
// ============================================================
function loadApiUsageMonitor() {
    var el = document.getElementById('api-usage-monitor-content');
    if (!el) return;
    el.innerHTML = '<p>Loading API usage data...</p>';
    fetch('/api/admin/api-usage-monitor', {headers:{'Authorization':'Bearer ' + (localStorage.getItem('adminToken') || '')}})
    .then(function(r){return r.json();})
    .then(function(d){
        var html = '<div class="admin-stats-grid">';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.total_requests_24h.toLocaleString() + '</div><div class="stat-label">Requests (24h)</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.overall_error_rate_pct + '%</div><div class="stat-label">Error Rate</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.average_response_ms + 'ms</div><div class="stat-label">Avg Response</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:' + (d.endpoints_critical > 0 ? '#f56565' : '#68d391') + ';">' + d.endpoints_healthy + '/' + (d.endpoints_healthy + d.endpoints_warning + d.endpoints_critical) + '</div><div class="stat-label">Healthy</div></div>';
        html += '</div>';
        html += '<h4>📊 Top Endpoints</h4><table class="admin-table"><thead><tr><th>Endpoint</th><th>Requests</th><th>Errors</th><th>Avg(ms)</th><th>Status</th></tr></thead><tbody>';
        d.endpoint_stats.slice(0, 8).forEach(function(e){
            var statusColor = e.status === 'Healthy' ? '#68d391' : e.status === 'Warning' ? '#ecc94b' : '#f56565';
            html += '<tr><td style="font-size:0.75rem;">' + e.endpoint + '</td><td>' + e.requests_24h + '</td><td>' + e.errors_24h + '</td><td>' + e.avg_response_ms + '</td><td style="color:' + statusColor + ';">' + e.status + '</td></tr>';
        });
        html += '</tbody></table>';
        if (d.top_errors && d.top_errors.length) {
            html += '<h4>⚠️ Top Errors</h4><ul class="admin-list">';
            d.top_errors.forEach(function(e){ html += '<li><strong>' + e.code + '</strong>: ' + e.message + ' (' + e.count + 'x)</li>'; });
            html += '</ul>';
        }
        if (d.alerts && d.alerts.length) {
            html += '<h4>🔔 Alerts</h4><ul class="admin-list">';
            d.alerts.forEach(function(a){ html += '<li>' + a + '</li>'; });
            html += '</ul>';
        }
        el.innerHTML = html;
    }).catch(function(e){el.innerHTML='<p class="error">Failed to load API usage: '+e.message+'</p>';});
}
function refreshApiUsageMonitor() { loadApiUsageMonitor(); }
document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('api-usage-monitor-refresh');
    if (btn) btn.addEventListener('click', refreshApiUsageMonitor);
    loadApiUsageMonitor();
});

// ============================================================
// Admin: Session Analytics Dashboard
// ============================================================
function loadSessionAnalyticsDashboard() {
    var el = document.getElementById('session-analytics-dashboard-content');
    if (!el) return;
    el.innerHTML = '<p>Loading session analytics...</p>';
    fetch('/api/admin/session-analytics-dashboard', {headers:{'Authorization':'Bearer ' + (localStorage.getItem('adminToken') || '')}})
    .then(function(r){return r.json();})
    .then(function(d){
        var html = '<div class="admin-stats-grid">';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.total_sessions_all_time.toLocaleString() + '</div><div class="stat-label">Total Sessions</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#68d391;">' + d.active_sessions_now + '</div><div class="stat-label">Active Now</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.average_session_duration_min + ' min</div><div class="stat-label">Avg Duration</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.bounce_rate_pct + '%</div><div class="stat-label">Bounce Rate</div></div>';
        html += '</div>';
        html += '<h4>🏷️ User Segments</h4><table class="admin-table"><thead><tr><th>Segment</th><th>Count</th><th>Avg Duration</th></tr></thead><tbody>';
        d.user_segments.forEach(function(s){
            html += '<tr><td>' + s.segment + '</td><td>' + s.count + '</td><td>' + s.avg_session_length_min + ' min</td></tr>';
        });
        html += '</tbody></table>';
        html += '<h4>🔥 Feature Usage</h4><table class="admin-table"><thead><tr><th>Feature</th><th>Sessions</th><th>Avg Time</th></tr></thead><tbody>';
        d.feature_usage_stats.forEach(function(f){
            html += '<tr><td>' + f.feature + '</td><td>' + f.sessions_used + '</td><td>' + f.avg_time_sec + 's</td></tr>';
        });
        html += '</tbody></table>';
        var em = d.engagement_metrics;
        html += '<h4>📈 Engagement</h4><ul class="admin-list">';
        html += '<li>Avg features/session: <strong>' + em.avg_features_per_session + '</strong></li>';
        html += '<li>7-day return rate: <strong>' + em.return_rate_7day_pct + '%</strong></li>';
        html += '<li>30-day return rate: <strong>' + em.return_rate_30day_pct + '%</strong></li>';
        html += '<li>Common first action: <strong>' + em.most_common_first_action + '</strong></li>';
        html += '</ul>';
        if (d.insights && d.insights.length) {
            html += '<h4>💡 Insights</h4><ul class="admin-list">';
            d.insights.forEach(function(i){ html += '<li>' + i + '</li>'; });
            html += '</ul>';
        }
        el.innerHTML = html;
    }).catch(function(e){el.innerHTML='<p class="error">Failed to load session analytics: '+e.message+'</p>';});
}
function refreshSessionAnalyticsDashboard() { loadSessionAnalyticsDashboard(); }
document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('session-analytics-dashboard-refresh');
    if (btn) btn.addEventListener('click', refreshSessionAnalyticsDashboard);
    loadSessionAnalyticsDashboard();
});

// ============================================================
// Admin: User Retention Analyzer
// ============================================================
function loadUserRetentionAnalyzer() {
    var el = document.getElementById('user-retention-analyzer-content');
    if (!el) return;
    el.innerHTML = '<p>Loading retention data...</p>';
    fetch('/api/admin/user-retention-analyzer', {headers:{'Authorization':'Bearer ' + (localStorage.getItem('adminToken') || '')}})
    .then(function(r){return r.json();})
    .then(function(d){
        var html = '<div class="admin-stats-grid">';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#68d391;">' + d.overall_retention_30day_pct + '%</div><div class="stat-label">30-Day Retention</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.overall_retention_90day_pct + '%</div><div class="stat-label">90-Day Retention</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#90cdf4;">' + d.total_active_users + '</div><div class="stat-label">Active Users</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#fc8181;">' + d.users_at_risk + '</div><div class="stat-label">At Risk</div></div>';
        html += '</div>';
        html += '<h4>📉 Cohort Retention</h4><table class="admin-table"><thead><tr><th>Cohort</th><th>Users</th><th>Active</th><th>W1</th><th>W4</th><th>W6</th></tr></thead><tbody>';
        d.cohort_analysis.forEach(function(c){
            html += '<tr><td>' + c.cohort_month + '</td><td>' + c.initial_users + '</td><td>' + c.current_active + '</td>';
            html += '<td>' + (c.weekly_retention_pct[1] || '-') + '%</td>';
            html += '<td>' + (c.weekly_retention_pct[4] || '-') + '%</td>';
            html += '<td>' + (c.weekly_retention_pct[6] || '-') + '%</td></tr>';
        });
        html += '</tbody></table>';
        html += '<h4>⚠️ Churn Risk Users (Top 5)</h4><table class="admin-table"><thead><tr><th>User</th><th>Risk</th><th>Last Active</th><th>Factors</th></tr></thead><tbody>';
        d.churn_risk_users.slice(0, 5).forEach(function(u){
            var riskColor = u.risk_level === 'Critical' ? '#fc8181' : '#fbd38d';
            html += '<tr><td>' + u.user_id + '</td><td style="color:' + riskColor + ';">' + u.churn_risk_score + '</td>';
            html += '<td>' + u.last_active_days_ago + 'd ago</td><td>' + u.contributing_factors[0] + '</td></tr>';
        });
        html += '</tbody></table>';
        if (d.engagement_drivers && d.engagement_drivers.length) {
            html += '<h4>💡 Engagement Drivers</h4><ul class="admin-list">';
            d.engagement_drivers.forEach(function(e){ html += '<li>' + e + '</li>'; });
            html += '</ul>';
        }
        el.innerHTML = html;
    }).catch(function(e){el.innerHTML='<p class="error">Failed to load retention data: '+e.message+'</p>';});
}
function refreshUserRetentionAnalyzer() { loadUserRetentionAnalyzer(); }
document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('user-retention-analyzer-refresh');
    if (btn) btn.addEventListener('click', refreshUserRetentionAnalyzer);
    loadUserRetentionAnalyzer();
});

// ============================================================
// Admin: Document Processing Queue
// ============================================================
function loadDocumentProcessingQueue() {
    var el = document.getElementById('document-processing-queue-content');
    if (!el) return;
    el.innerHTML = '<p>Loading processing queue...</p>';
    fetch('/api/admin/document-processing-queue', {headers:{'Authorization':'Bearer ' + (localStorage.getItem('adminToken') || '')}})
    .then(function(r){return r.json();})
    .then(function(d){
        var html = '<div class="admin-stats-grid">';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#fbd38d;">' + d.queue_depth + '</div><div class="stat-label">In Queue</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#90cdf4;">' + d.currently_processing + '</div><div class="stat-label">Processing</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#68d391;">' + d.completed_today + '</div><div class="stat-label">Completed</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#fc8181;">' + d.failed_today + '</div><div class="stat-label">Failed</div></div>';
        html += '</div>';
        html += '<div class="admin-stats-grid" style="margin-top:8px;">';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.success_rate_pct + '%</div><div class="stat-label">Success Rate</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.average_processing_time_min + ' min</div><div class="stat-label">Avg Time</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.throughput_docs_per_hour + '/hr</div><div class="stat-label">Throughput</div></div>';
        html += '</div>';
        html += '<h4>📋 Queue Items</h4><table class="admin-table"><thead><tr><th>File</th><th>Type</th><th>Size</th><th>Status</th><th>Progress</th></tr></thead><tbody>';
        d.queue_items.forEach(function(q){
            var statusColor = q.status === 'Completed' ? '#68d391' : q.status === 'Processing' ? '#90cdf4' : q.status === 'Failed' ? '#fc8181' : '#fbd38d';
            html += '<tr><td title="' + q.filename + '">' + q.doc_id + '</td><td>' + q.file_type + '</td><td>' + q.size_mb + ' MB</td>';
            html += '<td style="color:' + statusColor + ';">' + q.status + '</td>';
            html += '<td>' + (q.status === 'Processing' ? q.progress_pct + '%' : q.status === 'Completed' ? '✅' : q.status === 'Failed' ? '❌' : '⏳') + '</td></tr>';
        });
        html += '</tbody></table>';
        html += '<h4>🖥️ System Resources</h4><ul class="admin-list">';
        var sr = d.system_resources;
        html += '<li>CPU: <strong>' + sr.cpu_usage_pct + '%</strong></li>';
        html += '<li>Memory: <strong>' + sr.memory_usage_pct + '%</strong></li>';
        html += '<li>Disk: <strong>' + sr.disk_usage_pct + '%</strong></li>';
        html += '<li>Workers: <strong>' + sr.worker_threads_active + '/' + sr.worker_threads_total + '</strong></li>';
        html += '</ul>';
        if (d.alerts && d.alerts.length) {
            html += '<h4>🔔 Alerts</h4><ul class="admin-list">';
            d.alerts.forEach(function(a){ html += '<li>' + a + '</li>'; });
            html += '</ul>';
        }
        el.innerHTML = html;
    }).catch(function(e){el.innerHTML='<p class="error">Failed to load processing queue: '+e.message+'</p>';});
}
function refreshDocumentProcessingQueue() { loadDocumentProcessingQueue(); }
document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('document-processing-queue-refresh');
    if (btn) btn.addEventListener('click', refreshDocumentProcessingQueue);
    loadDocumentProcessingQueue();
});

// ============================================================
// Admin: Error Log Viewer
// ============================================================
function loadErrorLogViewer() {
    var el = document.getElementById('error-log-viewer-content');
    if (!el) return;
    el.innerHTML = '<p>Loading error logs...</p>';
    fetch('/api/admin/error-log-viewer', {headers:{'Authorization':'Bearer ' + (localStorage.getItem('adminToken') || '')}})
    .then(function(r){return r.json();})
    .then(function(d){
        var html = '<div class="admin-stats-grid">';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#fc8181;">' + d.critical_count + '</div><div class="stat-label">Critical</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#fbd38d;">' + d.error_count + '</div><div class="stat-label">Errors</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#90cdf4;">' + d.warning_count + '</div><div class="stat-label">Warnings</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#68d391;">' + d.info_count + '</div><div class="stat-label">Info</div></div>';
        html += '</div>';
        html += '<div class="admin-stats-grid" style="margin-top:8px;">';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.total_errors_24h + '</div><div class="stat-label">Total (24h)</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.error_rate_per_hour + '/hr</div><div class="stat-label">Error Rate</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.mean_time_to_resolution_min + ' min</div><div class="stat-label">Avg Resolution</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.auto_recovered_pct + '%</div><div class="stat-label">Auto-Recovered</div></div>';
        html += '</div>';
        html += '<h4>🔝 Top Error Types</h4><table class="admin-table"><thead><tr><th>Error Type</th><th>Count</th></tr></thead><tbody>';
        d.top_error_types.forEach(function(t){ html += '<tr><td>' + t.error_type + '</td><td>' + t.count + '</td></tr>'; });
        html += '</tbody></table>';
        html += '<h4>🏷️ Errors by Service</h4><table class="admin-table"><thead><tr><th>Service</th><th>Count</th></tr></thead><tbody>';
        d.errors_by_service.forEach(function(s){ html += '<tr><td>' + s.service + '</td><td>' + s.count + '</td></tr>'; });
        html += '</tbody></table>';
        html += '<h4>📋 Recent Errors</h4><table class="admin-table"><thead><tr><th>ID</th><th>Severity</th><th>Type</th><th>Service</th><th>Status</th></tr></thead><tbody>';
        d.error_logs.slice(0,15).forEach(function(l){
            var sc = l.severity === 'CRITICAL' ? '#fc8181' : l.severity === 'ERROR' ? '#fbd38d' : l.severity === 'WARN' ? '#90cdf4' : '#68d391';
            html += '<tr><td>' + l.log_id + '</td><td style="color:' + sc + ';">' + l.severity + '</td><td>' + l.error_type + '</td><td>' + l.service + '</td><td>' + l.resolution_status + '</td></tr>';
        });
        html += '</tbody></table>';
        if (d.alerts && d.alerts.length) {
            html += '<h4>🔔 Alerts</h4><ul class="admin-list">';
            d.alerts.forEach(function(a){ html += '<li>' + a + '</li>'; });
            html += '</ul>';
        }
        el.innerHTML = html;
    }).catch(function(e){el.innerHTML='<p class="error">Failed to load error logs: '+e.message+'</p>';});
}
function refreshErrorLogViewer() { loadErrorLogViewer(); }
document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('error-log-viewer-refresh');
    if (btn) btn.addEventListener('click', refreshErrorLogViewer);
    loadErrorLogViewer();
});

// ============================================================
// Admin: Content Moderation Dashboard
// ============================================================
function loadContentModerationDashboard() {
    var el = document.getElementById('content-moderation-dashboard-content');
    if (!el) return;
    el.innerHTML = '<p>Loading moderation data...</p>';
    fetch('/api/admin/content-moderation-dashboard', {headers:{'Authorization':'Bearer ' + (localStorage.getItem('adminToken') || '')}})
    .then(function(r){return r.json();})
    .then(function(d){
        var html = '<div class="admin-stats-grid">';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#fbd38d;">' + d.total_flagged_items + '</div><div class="stat-label">Flagged Items</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#fc8181;">' + d.pending_review + '</div><div class="stat-label">Pending Review</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#fc8181;">' + d.high_severity_count + '</div><div class="stat-label">High Severity</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#68d391;">' + d.items_reviewed_today + '</div><div class="stat-label">Reviewed Today</div></div>';
        html += '</div>';
        html += '<h4>🏷️ Flag Reasons</h4><table class="admin-table"><thead><tr><th>Reason</th><th>Count</th></tr></thead><tbody>';
        d.flag_reason_breakdown.forEach(function(r){ html += '<tr><td>' + r.reason + '</td><td>' + r.count + '</td></tr>'; });
        html += '</tbody></table>';
        html += '<h4>📋 Flagged Items</h4><table class="admin-table"><thead><tr><th>ID</th><th>Type</th><th>Reason</th><th>Severity</th><th>Status</th></tr></thead><tbody>';
        d.flagged_items.slice(0,12).forEach(function(f){
            var sc = f.severity === 'HIGH' ? '#fc8181' : f.severity === 'MEDIUM' ? '#fbd38d' : '#68d391';
            html += '<tr><td>' + f.item_id + '</td><td>' + f.content_type + '</td><td>' + f.flag_reason + '</td>';
            html += '<td style="color:' + sc + ';">' + f.severity + '</td><td>' + f.moderation_status + '</td></tr>';
        });
        html += '</tbody></table>';
        html += '<h4>📜 Moderation Policies</h4><table class="admin-table"><thead><tr><th>Policy</th><th>Status</th><th>Sensitivity</th></tr></thead><tbody>';
        d.moderation_policies.forEach(function(p){ html += '<tr><td>' + p.policy + '</td><td style="color:#68d391;">' + p.status + '</td><td>' + p.sensitivity + '</td></tr>'; });
        html += '</tbody></table>';
        html += '<h4>📊 Compliance Metrics</h4><ul class="admin-list">';
        var cm = d.compliance_metrics;
        html += '<li>SLA Met: <strong>' + cm.review_sla_met_pct + '%</strong></li>';
        html += '<li>False Positive Rate: <strong>' + cm.false_positive_rate_pct + '%</strong></li>';
        html += '<li>Auto-Flag Accuracy: <strong>' + cm.auto_flag_accuracy_pct + '%</strong></li>';
        html += '<li>Escalations This Week: <strong>' + cm.escalations_this_week + '</strong></li>';
        html += '</ul>';
        if (d.recommendations && d.recommendations.length) {
            html += '<h4>�� Recommendations</h4><ul class="admin-list">';
            d.recommendations.forEach(function(r){ html += '<li>' + r + '</li>'; });
            html += '</ul>';
        }
        el.innerHTML = html;
    }).catch(function(e){el.innerHTML='<p class="error">Failed to load moderation data: '+e.message+'</p>';});
}
function refreshContentModerationDashboard() { loadContentModerationDashboard(); }
document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('content-moderation-dashboard-refresh');
    if (btn) btn.addEventListener('click', refreshContentModerationDashboard);
    loadContentModerationDashboard();
});

// ============================================================
// Admin: Gemini Model Analytics
// ============================================================
function loadGeminiModelAnalytics() {
    var el = document.getElementById('gemini-model-analytics-content');
    if (!el) return;
    el.innerHTML = '<p>Loading Gemini analytics...</p>';
    fetch('/api/admin/gemini-model-analytics', {headers:{'Authorization':'Bearer ' + (localStorage.getItem('adminToken') || '')}})
    .then(function(r){return r.json();})
    .then(function(d){
        var html = '<div class="admin-stats-grid">';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.total_requests_24h + '</div><div class="stat-label">Requests (24h)</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#68d391;">' + d.total_estimated_cost_formatted + '</div><div class="stat-label">Est. Cost (24h)</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.average_quality_score + '/10</div><div class="stat-label">Avg Quality</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + (d.total_tokens_input / 1000).toFixed(0) + 'K</div><div class="stat-label">Tokens In</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + (d.total_tokens_output / 1000).toFixed(0) + 'K</div><div class="stat-label">Tokens Out</div></div>';
        html += '</div>';
        html += '<h4>🤖 Model Performance</h4><table class="admin-table"><thead><tr><th>Model</th><th>Requests</th><th>Avg Latency</th><th>P95 Latency</th><th>Quality</th><th>Error Rate</th><th>Cost</th></tr></thead><tbody>';
        d.model_stats.forEach(function(m){
            html += '<tr><td><strong>' + m.model_name + '</strong></td><td>' + m.requests_24h + '</td>';
            html += '<td>' + m.avg_latency_seconds + 's</td><td>' + m.p95_latency_seconds + 's</td>';
            html += '<td style="color:#68d391;">' + m.quality_score + '</td>';
            html += '<td style="color:' + (m.error_rate_pct > 2 ? '#fc8181' : '#68d391') + ';">' + m.error_rate_pct + '%</td>';
            html += '<td>$' + m.estimated_cost_24h + '</td></tr>';
        });
        html += '</tbody></table>';
        html += '<h4>📊 Feature AI Usage</h4><table class="admin-table"><thead><tr><th>Feature</th><th>Requests</th><th>Avg Tokens</th><th>Quality</th><th>Latency</th></tr></thead><tbody>';
        d.feature_usage.slice(0,8).forEach(function(f){
            html += '<tr><td>' + f.feature + '</td><td>' + f.requests_24h + '</td><td>' + f.avg_tokens_per_request + '</td>';
            html += '<td style="color:#68d391;">' + f.avg_quality_score + '</td><td>' + f.avg_latency_seconds + 's</td></tr>';
        });
        html += '</tbody></table>';
        html += '<h4>💡 Cost Optimization</h4><ul class="admin-list">';
        d.cost_optimization_tips.forEach(function(t){ html += '<li>' + t + '</li>'; });
        html += '</ul>';
        if (d.alerts && d.alerts.length) {
            html += '<h4>🔔 Alerts</h4><ul class="admin-list">';
            d.alerts.forEach(function(a){ html += '<li>' + a + '</li>'; });
            html += '</ul>';
        }
        el.innerHTML = html;
    }).catch(function(e){el.innerHTML='<p class="error">Failed to load Gemini analytics: '+e.message+'</p>';});
}
function refreshGeminiModelAnalytics() { loadGeminiModelAnalytics(); }
document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('gemini-model-analytics-refresh');
    if (btn) btn.addEventListener('click', refreshGeminiModelAnalytics);
    loadGeminiModelAnalytics();
});

// ============================================================
// Admin: User Activity Timeline
// ============================================================
function loadUserActivityTimeline() {
    var el = document.getElementById('user-activity-timeline-content');
    if (!el) return;
    el.innerHTML = '<p>Loading user activity...</p>';
    fetch('/api/admin/user-activity-timeline', {headers:{'Authorization':'Bearer ' + (localStorage.getItem('adminToken') || '')}})
    .then(function(r){return r.json();})
    .then(function(d){
        var html = '<div class="admin-stats-grid">';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.total_activities + '</div><div class="stat-label">Activities (12h)</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value" style="color:#68d391;">' + d.active_users_last_hour + '</div><div class="stat-label">Active Now</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.total_unique_users_12h + '</div><div class="stat-label">Unique Users</div></div>';
        html += '<div class="admin-stat-card"><div class="stat-value">' + d.engagement_metrics.avg_actions_per_session + '</div><div class="stat-label">Avg Actions/Session</div></div>';
        html += '</div>';
        html += '<h4>👥 Most Active Users</h4><table class="admin-table"><thead><tr><th>Username</th><th>Actions</th></tr></thead><tbody>';
        d.most_active_users.forEach(function(u){ html += '<tr><td>' + u.username + '</td><td>' + u.actions + '</td></tr>'; });
        html += '</tbody></table>';
        html += '<h4>🔥 Top Actions</h4><table class="admin-table"><thead><tr><th>Action</th><th>Count</th></tr></thead><tbody>';
        d.top_actions.forEach(function(a){ html += '<tr><td>' + a.action + '</td><td>' + a.count + '</td></tr>'; });
        html += '</tbody></table>';
        html += '<h4>📱 Device Breakdown</h4><table class="admin-table"><thead><tr><th>Device</th><th>Count</th></tr></thead><tbody>';
        d.device_breakdown.forEach(function(db){ html += '<tr><td>' + db.device + '</td><td>' + db.count + '</td></tr>'; });
        html += '</tbody></table>';
        html += '<h4>📋 Recent Activity Feed</h4><table class="admin-table"><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th><th>Device</th></tr></thead><tbody>';
        d.activities.slice(0,20).forEach(function(a){
            var timeStr = a.minutes_ago < 60 ? a.minutes_ago + 'm ago' : Math.floor(a.minutes_ago/60) + 'h ago';
            html += '<tr><td>' + timeStr + '</td><td>' + a.username + '</td>';
            html += '<td>' + a.icon + ' ' + a.description + '</td><td>' + a.detail + '</td><td>' + a.device + '</td></tr>';
        });
        html += '</tbody></table>';
        html += '<h4>📊 Engagement Metrics</h4><ul class="admin-list">';
        var em = d.engagement_metrics;
        html += '<li>Avg Session Duration: <strong>' + em.avg_session_duration_min + ' min</strong></li>';
        html += '<li>Bounce Rate: <strong>' + em.bounce_rate_pct + '%</strong></li>';
        html += '<li>Feature Discovery: <strong>' + em.feature_discovery_rate_pct + '%</strong></li>';
        html += '</ul>';
        if (d.alerts && d.alerts.length) {
            html += '<h4>🔔 Alerts</h4><ul class="admin-list">';
            d.alerts.forEach(function(a){ html += '<li>' + a + '</li>'; });
            html += '</ul>';
        }
        el.innerHTML = html;
    }).catch(function(e){el.innerHTML='<p class="error">Failed to load activity timeline: '+e.message+'</p>';});
}
function refreshUserActivityTimeline() { loadUserActivityTimeline(); }
document.addEventListener('DOMContentLoaded', function() {
    var btn = document.getElementById('user-activity-timeline-refresh');
    if (btn) btn.addEventListener('click', refreshUserActivityTimeline);
    loadUserActivityTimeline();
});
