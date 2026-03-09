/**
 * WitnessReplay - Location Module
 * Provides location autocomplete with GPS coordinates using browser Geolocation API
 * No external API dependencies - uses manual address entry with GPS coordinates
 */

class LocationManager {
    constructor() {
        this.currentPosition = null;
        this.locationInput = null;
        this.gpsButton = null;
        this.suggestionList = null;
        this.coordinatesDisplay = null;
        this.mapContainer = null;
        this.recentLocations = this.loadRecentLocations();
        this.isWatching = false;
        this.watchId = null;
        
        // Common location type suggestions for incident reporting
        this.locationTypes = [
            { type: 'intersection', icon: '🚦', template: 'Intersection of {street1} & {street2}' },
            { type: 'address', icon: '🏠', template: '{number} {street}, {city}' },
            { type: 'landmark', icon: '🏛️', template: 'Near {landmark}' },
            { type: 'business', icon: '🏪', template: '{name}, {address}' },
            { type: 'parking', icon: '🅿️', template: '{name} Parking Lot' },
            { type: 'highway', icon: '🛣️', template: '{highway} near {exit/mile}' }
        ];
    }

    /**
     * Initialize location components
     */
    init() {
        this.locationInput = document.getElementById('witness-location');
        this.gpsButton = document.getElementById('gps-location-btn');
        this.suggestionList = document.getElementById('location-suggestions');
        this.coordinatesDisplay = document.getElementById('location-coordinates');
        this.mapContainer = document.getElementById('location-map');
        
        if (!this.locationInput) {
            console.warn('Location input not found');
            return;
        }

        this.setupEventListeners();
        this.checkGeolocationSupport();
    }

    /**
     * Setup event listeners for location input
     */
    setupEventListeners() {
        // Input events for autocomplete
        if (this.locationInput) {
            this.locationInput.addEventListener('input', (e) => this.onInput(e));
            this.locationInput.addEventListener('focus', () => this.showSuggestions());
            this.locationInput.addEventListener('blur', () => {
                // Delay to allow click on suggestions
                setTimeout(() => this.hideSuggestions(), 200);
            });
            this.locationInput.addEventListener('keydown', (e) => this.onKeydown(e));
        }

        // GPS button
        if (this.gpsButton) {
            this.gpsButton.addEventListener('click', () => this.getCurrentLocation());
        }

        // Close suggestions when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.location-input-wrapper')) {
                this.hideSuggestions();
            }
        });
    }

    /**
     * Check if geolocation is supported
     */
    checkGeolocationSupport() {
        if (!navigator.geolocation) {
            if (this.gpsButton) {
                this.gpsButton.disabled = true;
                this.gpsButton.title = 'Geolocation not supported by your browser';
            }
            return false;
        }
        return true;
    }

    /**
     * Get current location using browser Geolocation API
     */
    async getCurrentLocation() {
        if (!this.checkGeolocationSupport()) {
            this.showToast('Geolocation is not supported by your browser', 'error');
            return;
        }

        // Geolocation requires a secure context (HTTPS) except on localhost
        if (!window.isSecureContext &&
            window.location.hostname !== 'localhost' &&
            window.location.hostname !== '127.0.0.1') {
            this.showToast('📍 GPS requires HTTPS. Please access this page over a secure connection.', 'error');
            return;
        }

        // Update button state
        if (this.gpsButton) {
            this.gpsButton.classList.add('loading');
            this.gpsButton.innerHTML = '<span class="spinner"></span>';
        }

        const options = {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 0
        };

        try {
            const position = await new Promise((resolve, reject) => {
                navigator.geolocation.getCurrentPosition(resolve, reject, options);
            });

            this.currentPosition = {
                latitude: position.coords.latitude,
                longitude: position.coords.longitude,
                accuracy: position.coords.accuracy,
                timestamp: new Date().toISOString()
            };

            this.displayCoordinates();
            this.updateMapDisplay();
            this.addToRecentLocations(this.formatCoordinates(), this.currentPosition);
            
            // Auto-fill with coordinate format
            if (this.locationInput && !this.locationInput.value.trim()) {
                this.locationInput.value = this.formatCoordinates();
            }

            this.showToast('📍 Location captured successfully', 'success');

        } catch (error) {
            this.handleGeolocationError(error);
        } finally {
            // Reset button state
            if (this.gpsButton) {
                this.gpsButton.classList.remove('loading');
                this.gpsButton.innerHTML = '📍';
            }
        }
    }

    /**
     * Handle geolocation errors
     */
    handleGeolocationError(error) {
        let message = 'Unable to get location';
        
        switch (error.code) {
            case error.PERMISSION_DENIED:
                message = '📍 Please enable location in your browser settings';
                break;
            case error.POSITION_UNAVAILABLE:
                message = '📍 Location unavailable';
                break;
            case error.TIMEOUT:
                message = '📍 Location request timed out';
                break;
        }

        console.error('Geolocation error:', error);
        this.showToast(message, 'error');
    }

    /**
     * Format coordinates for display
     */
    formatCoordinates() {
        if (!this.currentPosition) return '';
        const { latitude, longitude } = this.currentPosition;
        return `${latitude.toFixed(6)}, ${longitude.toFixed(6)}`;
    }

    /**
     * Display coordinates in UI
     */
    displayCoordinates() {
        if (!this.coordinatesDisplay || !this.currentPosition) return;
        
        const { latitude, longitude, accuracy } = this.currentPosition;
        this.coordinatesDisplay.innerHTML = `
            <div class="coordinates-info">
                <span class="coord-label">GPS:</span>
                <span class="coord-value">${latitude.toFixed(6)}, ${longitude.toFixed(6)}</span>
                <span class="coord-accuracy">(±${Math.round(accuracy)}m)</span>
                <button class="coord-copy-btn" onclick="locationManager.copyCoordinates()" title="Copy coordinates">📋</button>
            </div>
        `;
        this.coordinatesDisplay.classList.add('visible');
    }

    /**
     * Copy coordinates to clipboard
     */
    async copyCoordinates() {
        if (!this.currentPosition) return;
        
        const text = this.formatCoordinates();
        try {
            await navigator.clipboard.writeText(text);
            this.showToast('Coordinates copied to clipboard', 'success');
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    }

    /**
     * Update map display with current location
     */
    updateMapDisplay() {
        if (!this.mapContainer || !this.currentPosition) return;

        const { latitude, longitude } = this.currentPosition;
        
        // Display a simple map using OpenStreetMap static image (no API key required)
        const zoom = 15;
        const mapUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${longitude-0.01},${latitude-0.01},${longitude+0.01},${latitude+0.01}&layer=mapnik&marker=${latitude},${longitude}`;
        
        this.mapContainer.innerHTML = `
            <div class="map-header">
                <span>📍 Incident Location</span>
                <a href="https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=17/${latitude}/${longitude}" 
                   target="_blank" rel="noopener" class="map-link">Open in Maps ↗</a>
            </div>
            <iframe 
                class="location-map-frame"
                src="${mapUrl}"
                frameborder="0"
                scrolling="no"
                title="Location map">
            </iframe>
        `;
        this.mapContainer.classList.add('visible');
    }

    /**
     * Handle input for autocomplete suggestions
     */
    onInput(e) {
        const value = e.target.value.trim();
        
        if (value.length < 2) {
            this.hideSuggestions();
            return;
        }

        this.showSuggestions(value);
    }

    /**
     * Handle keyboard navigation in suggestions
     */
    onKeydown(e) {
        if (!this.suggestionList || !this.suggestionList.classList.contains('visible')) return;

        const items = this.suggestionList.querySelectorAll('.suggestion-item');
        const activeItem = this.suggestionList.querySelector('.suggestion-item.active');
        let activeIndex = Array.from(items).indexOf(activeItem);

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                activeIndex = Math.min(activeIndex + 1, items.length - 1);
                this.setActiveSuggestion(items, activeIndex);
                break;
            case 'ArrowUp':
                e.preventDefault();
                activeIndex = Math.max(activeIndex - 1, 0);
                this.setActiveSuggestion(items, activeIndex);
                break;
            case 'Enter':
                if (activeItem) {
                    e.preventDefault();
                    activeItem.click();
                }
                break;
            case 'Escape':
                this.hideSuggestions();
                break;
        }
    }

    /**
     * Set active suggestion for keyboard navigation
     */
    setActiveSuggestion(items, index) {
        items.forEach((item, i) => {
            item.classList.toggle('active', i === index);
        });
    }

    /**
     * Show suggestion list
     */
    showSuggestions(filter = '') {
        if (!this.suggestionList) return;

        const suggestions = this.getSuggestions(filter);
        
        if (suggestions.length === 0) {
            this.hideSuggestions();
            return;
        }

        this.suggestionList.innerHTML = suggestions.map((s, i) => `
            <div class="suggestion-item ${i === 0 ? 'active' : ''}" 
                 data-value="${this.escapeHtml(s.value)}"
                 data-coords='${s.coords ? JSON.stringify(s.coords) : ''}'
                 onclick="locationManager.selectSuggestion(this)">
                <span class="suggestion-icon">${s.icon}</span>
                <span class="suggestion-text">${s.label}</span>
                ${s.type ? `<span class="suggestion-type">${s.type}</span>` : ''}
            </div>
        `).join('');

        this.suggestionList.classList.add('visible');
    }

    /**
     * Hide suggestion list
     */
    hideSuggestions() {
        if (this.suggestionList) {
            this.suggestionList.classList.remove('visible');
        }
    }

    /**
     * Get suggestions based on input
     */
    getSuggestions(filter) {
        const suggestions = [];
        const lowerFilter = filter.toLowerCase();

        // Add recent locations
        this.recentLocations
            .filter(loc => loc.value.toLowerCase().includes(lowerFilter))
            .slice(0, 3)
            .forEach(loc => {
                suggestions.push({
                    icon: '🕐',
                    label: loc.value,
                    value: loc.value,
                    coords: loc.coords,
                    type: 'Recent'
                });
            });

        // Add location type templates
        if (filter.length >= 2) {
            this.locationTypes
                .filter(lt => lt.type.toLowerCase().includes(lowerFilter) || 
                             lt.template.toLowerCase().includes(lowerFilter))
                .forEach(lt => {
                    suggestions.push({
                        icon: lt.icon,
                        label: lt.template,
                        value: lt.template,
                        type: lt.type
                    });
                });
        }

        // Add common location hints
        if (suggestions.length < 5) {
            const hints = this.getCommonLocationHints(filter);
            suggestions.push(...hints);
        }

        return suggestions.slice(0, 6);
    }

    /**
     * Get common location hints for autocomplete
     */
    getCommonLocationHints(filter) {
        const hints = [
            { icon: '🏠', label: 'Street address (e.g., 123 Main St)', value: '', type: 'Format' },
            { icon: '🚦', label: 'Intersection (e.g., Main St & Oak Ave)', value: '', type: 'Format' },
            { icon: '🏛️', label: 'Near landmark (e.g., Near City Hall)', value: '', type: 'Format' }
        ];

        return hints.filter(h => 
            h.label.toLowerCase().includes(filter.toLowerCase()) ||
            filter.length < 3
        ).slice(0, 2);
    }

    /**
     * Select a suggestion
     */
    selectSuggestion(element) {
        const value = element.dataset.value;
        const coordsStr = element.dataset.coords;

        if (this.locationInput && value) {
            this.locationInput.value = value;
        }

        if (coordsStr) {
            try {
                this.currentPosition = JSON.parse(coordsStr);
                this.displayCoordinates();
                this.updateMapDisplay();
            } catch (e) {
                console.error('Invalid coords data:', e);
            }
        }

        this.hideSuggestions();
        this.locationInput?.focus();
    }

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Load recent locations from localStorage
     */
    loadRecentLocations() {
        try {
            const stored = localStorage.getItem('witnessreplay-recent-locations');
            return stored ? JSON.parse(stored) : [];
        } catch (e) {
            return [];
        }
    }

    /**
     * Save recent locations to localStorage
     */
    saveRecentLocations() {
        try {
            localStorage.setItem('witnessreplay-recent-locations', 
                JSON.stringify(this.recentLocations.slice(0, 10)));
        } catch (e) {
            console.error('Failed to save recent locations:', e);
        }
    }

    /**
     * Add a location to recent locations
     */
    addToRecentLocations(value, coords = null) {
        if (!value.trim()) return;

        // Remove existing entry with same value
        this.recentLocations = this.recentLocations.filter(loc => loc.value !== value);

        // Add to beginning
        this.recentLocations.unshift({
            value: value,
            coords: coords,
            timestamp: new Date().toISOString()
        });

        // Keep only last 10
        this.recentLocations = this.recentLocations.slice(0, 10);
        this.saveRecentLocations();
    }

    /**
     * Get location data for session
     */
    getLocationData() {
        const address = this.locationInput?.value?.trim() || '';
        
        return {
            address: address,
            coordinates: this.currentPosition ? {
                latitude: this.currentPosition.latitude,
                longitude: this.currentPosition.longitude,
                accuracy: this.currentPosition.accuracy
            } : null,
            timestamp: this.currentPosition?.timestamp || new Date().toISOString()
        };
    }

    /**
     * Save location to session metadata
     */
    async saveToSession(sessionId) {
        if (!sessionId) {
            console.warn('No session ID provided');
            return false;
        }

        const locationData = this.getLocationData();
        
        if (!locationData.address && !locationData.coordinates) {
            return false; // Nothing to save
        }

        try {
            const response = await fetch(`/api/sessions/${sessionId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    metadata: {
                        incident_location: locationData
                    }
                })
            });

            if (!response.ok) {
                throw new Error('Failed to update session');
            }

            // Add to recent locations
            if (locationData.address) {
                this.addToRecentLocations(locationData.address, locationData.coordinates);
            }

            return true;
        } catch (error) {
            console.error('Failed to save location to session:', error);
            return false;
        }
    }

    /**
     * Show toast notification (uses app's toast if available)
     */
    showToast(message, type = 'info') {
        if (window.app?.ui?.showToast) {
            window.app.ui.showToast(message, type);
        } else {
            console.log(`[${type}] ${message}`);
        }
    }

    /**
     * Clear current location
     */
    clearLocation() {
        this.currentPosition = null;
        if (this.coordinatesDisplay) {
            this.coordinatesDisplay.classList.remove('visible');
            this.coordinatesDisplay.innerHTML = '';
        }
        if (this.mapContainer) {
            this.mapContainer.classList.remove('visible');
            this.mapContainer.innerHTML = '';
        }
        if (this.locationInput) {
            this.locationInput.value = '';
        }
    }
}

// Create global instance
const locationManager = new LocationManager();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    locationManager.init();
});
