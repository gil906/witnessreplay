/**
 * Scene Template Manager - Pre-built scene templates for quick setup
 * WitnessReplay - Professional Law Enforcement Tool
 */

class SceneTemplateManager {
    constructor() {
        this.templates = [];
        this.isInitialized = false;
        this.selectedTemplate = null;
    }

    /**
     * Initialize the template manager
     */
    async init() {
        if (this.isInitialized) return;
        
        try {
            await this.loadTemplates();
            this.isInitialized = true;
            console.debug('[SceneTemplates] Manager initialized with', this.templates.length, 'templates');
        } catch (error) {
            console.error('[SceneTemplates] Failed to initialize:', error);
        }
    }

    /**
     * Load templates from the API
     */
    async loadTemplates() {
        try {
            const response = await fetch('/api/scene-templates');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const data = await response.json();
            this.templates = data.templates || [];
        } catch (error) {
            console.error('[SceneTemplates] Failed to load templates:', error);
            this.templates = [];
        }
    }

    /**
     * Show template selector modal
     */
    showTemplateSelector() {
        // Remove existing modal if any
        const existingModal = document.getElementById('template-selector-modal');
        if (existingModal) existingModal.remove();

        const modal = document.createElement('div');
        modal.id = 'template-selector-modal';
        modal.className = 'template-modal-overlay';
        modal.innerHTML = `
            <div class="template-modal">
                <div class="template-modal-header">
                    <h3>📐 Choose a Scene Template</h3>
                    <button class="template-modal-close" onclick="sceneTemplateManager.closeSelector()">&times;</button>
                </div>
                <div class="template-modal-body">
                    <p class="template-modal-hint">Select a template to quickly set up your scene, or start from scratch.</p>
                    <div class="template-grid">
                        <div class="template-card template-blank" onclick="sceneTemplateManager.selectTemplate(null)">
                            <span class="template-icon">📝</span>
                            <h4>Blank Canvas</h4>
                            <p>Start with an empty scene</p>
                        </div>
                        ${this.templates.map(t => `
                            <div class="template-card" onclick="sceneTemplateManager.selectTemplate('${t.id}')" data-template-id="${t.id}">
                                <span class="template-icon">${t.icon}</span>
                                <h4>${t.name}</h4>
                                <p>${t.description}</p>
                                <span class="template-category">${t.category}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="template-modal-footer">
                    <button class="btn btn-secondary" onclick="sceneTemplateManager.closeSelector()">Cancel</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Close on backdrop click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.closeSelector();
            }
        });

        // Close on Escape key
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                this.closeSelector();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    }

    /**
     * Close the template selector modal
     */
    closeSelector() {
        const modal = document.getElementById('template-selector-modal');
        if (modal) {
            modal.classList.add('closing');
            setTimeout(() => modal.remove(), 200);
        }
    }

    /**
     * Select and apply a template
     */
    async selectTemplate(templateId) {
        this.closeSelector();

        if (!templateId) {
            // Blank canvas selected
            this.clearAndPrepareCanvas();
            console.debug('[SceneTemplates] Starting with blank canvas');
            return;
        }

        try {
            // Fetch template details
            const response = await fetch(`/api/scene-templates/${templateId}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const template = await response.json();
            this.selectedTemplate = template;

            // Apply template to canvas
            this.applyTemplate(template);
            console.debug('[SceneTemplates] Applied template:', template.name);
        } catch (error) {
            console.error('[SceneTemplates] Failed to apply template:', error);
            alert('Failed to load template. Please try again.');
        }
    }

    /**
     * Apply a template to the scene canvas
     */
    applyTemplate(template) {
        // Clear existing elements
        if (window.sceneElementLibrary) {
            window.sceneElementLibrary.clearCanvas();
        }

        const canvas = document.getElementById('scene-editor-canvas');
        if (!canvas) {
            console.error('[SceneTemplates] Canvas not found');
            return;
        }

        // Remove placeholder
        const placeholder = canvas.querySelector('.placeholder');
        if (placeholder) {
            placeholder.style.display = 'none';
        }

        // Apply canvas size if specified
        if (template.canvasSize) {
            canvas.style.minHeight = `${template.canvasSize.height}px`;
        }

        // Place each element from the template
        template.elements.forEach(element => {
            const placedElement = {
                ...element,
                instanceId: element.instanceId || `${element.id}_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
                category: this.getElementCategory(element.id),
                zIndex: window.sceneElementLibrary ? window.sceneElementLibrary.placedElements.length : 0
            };

            if (window.sceneElementLibrary) {
                window.sceneElementLibrary.placedElements.push(placedElement);
                window.sceneElementLibrary.renderPlacedElement(placedElement);
                
                // Apply locked state if specified
                if (element.locked) {
                    const el = document.getElementById(placedElement.instanceId);
                    if (el) {
                        el.classList.add('locked-element');
                        el.title = `${element.name} (locked - right-click to unlock)`;
                    }
                }
            }
        });

        // Mark canvas as having elements
        canvas.classList.add('has-elements');

        // Dispatch event for other listeners
        canvas.dispatchEvent(new CustomEvent('templateApplied', {
            detail: { template: template }
        }));
    }

    /**
     * Clear canvas and prepare for new scene
     */
    clearAndPrepareCanvas() {
        if (window.sceneElementLibrary) {
            window.sceneElementLibrary.clearCanvas();
        }

        const canvas = document.getElementById('scene-editor-canvas');
        if (canvas) {
            // Show placeholder again
            const placeholder = canvas.querySelector('.placeholder');
            if (placeholder) {
                placeholder.style.display = 'flex';
            }
            canvas.classList.remove('has-elements');
        }
    }

    /**
     * Get the category of an element by its ID
     */
    getElementCategory(elementId) {
        const categoryMap = {
            'car': 'vehicles', 'truck': 'vehicles', 'motorcycle': 'vehicles', 'bicycle': 'vehicles',
            'suv': 'vehicles', 'van': 'vehicles', 'bus': 'vehicles', 'ambulance': 'vehicles',
            'police_car': 'vehicles', 'fire_truck': 'vehicles',
            'witness': 'people', 'suspect': 'people', 'victim': 'people', 'officer': 'people',
            'person': 'people', 'person_walking': 'people', 'person_running': 'people', 'group': 'people',
            'table': 'furniture', 'chair': 'furniture', 'bed': 'furniture', 'couch': 'furniture',
            'cabinet': 'furniture', 'door': 'furniture', 'window': 'furniture', 'counter': 'furniture',
            'tree': 'environment', 'building': 'environment', 'house': 'environment', 'road': 'environment',
            'sidewalk': 'environment', 'intersection': 'environment', 'parking_lot': 'environment',
            'traffic_light': 'environment', 'stop_sign': 'environment', 'streetlight': 'environment',
            'fence': 'environment', 'bush': 'environment'
        };
        return categoryMap[elementId] || 'environment';
    }

    /**
     * Get current template info (if any)
     */
    getCurrentTemplate() {
        return this.selectedTemplate;
    }

    /**
     * Check if scene has been modified from template
     */
    isModifiedFromTemplate() {
        if (!this.selectedTemplate || !window.sceneElementLibrary) {
            return false;
        }
        
        const currentElements = window.sceneElementLibrary.placedElements.length;
        const templateElements = this.selectedTemplate.elements.length;
        
        return currentElements !== templateElements;
    }
}

// Create global instance
window.sceneTemplateManager = new SceneTemplateManager();

// Auto-initialize when scene element library is ready
document.addEventListener('DOMContentLoaded', () => {
    // Initialize after a short delay to ensure scene library is ready
    setTimeout(() => {
        window.sceneTemplateManager.init();
    }, 500);
});

// Export for module use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SceneTemplateManager;
}
