/**
 * Scene Element Library - Draggable Element Palette for Scene Editing
 * WitnessReplay - Professional Law Enforcement Tool
 */

class SceneElementLibrary {
    constructor() {
        this.elements = null;
        this.categories = [];
        this.activeCategory = null;
        this.selectedElement = null;
        this.placedElements = [];
        this.elementIdCounter = 0;
        this.isInitialized = false;
    }

    /**
     * Initialize the scene element library
     */
    async init() {
        if (this.isInitialized) return;
        
        try {
            await this.loadElements();
            this.renderPalette();
            this.setupEventListeners();
            this.isInitialized = true;
            console.log('[SceneElements] Library initialized with', this.categories.length, 'categories');
        } catch (error) {
            console.error('[SceneElements] Failed to initialize:', error);
        }
    }

    /**
     * Load scene elements from the API
     */
    async loadElements() {
        try {
            const response = await fetch('/api/scene-elements');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const data = await response.json();
            this.categories = data.categories || [];
            this.elements = data;
            
            // Set first category as active
            if (this.categories.length > 0) {
                this.activeCategory = this.categories[0].id;
            }
        } catch (error) {
            console.error('[SceneElements] Failed to load elements:', error);
            // Fallback to empty state
            this.categories = [];
        }
    }

    /**
     * Render the element palette UI
     */
    renderPalette() {
        const container = document.getElementById('scene-element-palette');
        if (!container) {
            console.warn('[SceneElements] Palette container not found');
            return;
        }

        // Clear existing content
        container.innerHTML = '';

        // Create category tabs
        const tabsContainer = document.createElement('div');
        tabsContainer.className = 'element-palette-tabs';
        
        this.categories.forEach(category => {
            const tab = document.createElement('button');
            tab.className = `palette-tab ${category.id === this.activeCategory ? 'active' : ''}`;
            tab.dataset.category = category.id;
            tab.innerHTML = `<span class="tab-icon">${category.icon}</span><span class="tab-name">${category.name}</span>`;
            tab.title = category.name;
            tab.addEventListener('click', () => this.selectCategory(category.id));
            tabsContainer.appendChild(tab);
        });
        
        container.appendChild(tabsContainer);

        // Create elements grid
        const elementsContainer = document.createElement('div');
        elementsContainer.className = 'element-palette-grid';
        elementsContainer.id = 'element-palette-grid';
        container.appendChild(elementsContainer);

        // Render elements for active category
        this.renderCategoryElements();
    }

    /**
     * Render elements for the active category
     */
    renderCategoryElements() {
        const grid = document.getElementById('element-palette-grid');
        if (!grid) return;

        grid.innerHTML = '';

        const category = this.categories.find(c => c.id === this.activeCategory);
        if (!category) return;

        category.elements.forEach(element => {
            const item = document.createElement('div');
            item.className = 'palette-element';
            item.dataset.elementId = element.id;
            item.draggable = true;
            item.innerHTML = `
                <span class="element-icon">${element.icon}</span>
                <span class="element-name">${element.name}</span>
            `;
            item.title = element.description || element.name;
            
            // Drag events
            item.addEventListener('dragstart', (e) => this.handleDragStart(e, element));
            item.addEventListener('dragend', (e) => this.handleDragEnd(e));
            
            // Click to select for placement
            item.addEventListener('click', () => this.selectElement(element));
            
            grid.appendChild(item);
        });
    }

    /**
     * Select a category
     */
    selectCategory(categoryId) {
        this.activeCategory = categoryId;
        
        // Update tab styling
        document.querySelectorAll('.palette-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.category === categoryId);
        });
        
        this.renderCategoryElements();
    }

    /**
     * Select an element for placement
     */
    selectElement(element) {
        this.selectedElement = element;
        
        // Update selection styling
        document.querySelectorAll('.palette-element').forEach(el => {
            el.classList.toggle('selected', el.dataset.elementId === element.id);
        });
        
        // Show placement hint
        this.showPlacementHint();
    }

    /**
     * Show hint for placing selected element
     */
    showPlacementHint() {
        const canvas = document.getElementById('scene-editor-canvas');
        if (canvas && this.selectedElement) {
            canvas.style.cursor = 'crosshair';
            canvas.title = `Click to place: ${this.selectedElement.name}`;
        }
    }

    /**
     * Clear selection
     */
    clearSelection() {
        this.selectedElement = null;
        document.querySelectorAll('.palette-element').forEach(el => {
            el.classList.remove('selected');
        });
        
        const canvas = document.getElementById('scene-editor-canvas');
        if (canvas) {
            canvas.style.cursor = 'default';
            canvas.title = '';
        }
    }

    /**
     * Handle drag start
     */
    handleDragStart(event, element) {
        event.dataTransfer.setData('application/json', JSON.stringify(element));
        event.dataTransfer.effectAllowed = 'copy';
        event.target.classList.add('dragging');
        
        // Create drag image
        const dragImage = document.createElement('div');
        dragImage.className = 'drag-preview';
        dragImage.textContent = element.icon;
        dragImage.style.fontSize = '32px';
        dragImage.style.position = 'absolute';
        dragImage.style.top = '-1000px';
        document.body.appendChild(dragImage);
        event.dataTransfer.setDragImage(dragImage, 16, 16);
        
        setTimeout(() => document.body.removeChild(dragImage), 0);
    }

    /**
     * Handle drag end
     */
    handleDragEnd(event) {
        event.target.classList.remove('dragging');
    }

    /**
     * Setup event listeners for the scene canvas
     */
    setupEventListeners() {
        const canvas = document.getElementById('scene-editor-canvas');
        if (!canvas) return;

        // Drag over - allow drop
        canvas.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
            canvas.classList.add('drop-target');
        });

        // Drag leave
        canvas.addEventListener('dragleave', () => {
            canvas.classList.remove('drop-target');
        });

        // Drop
        canvas.addEventListener('drop', (e) => {
            e.preventDefault();
            canvas.classList.remove('drop-target');
            
            try {
                const elementData = JSON.parse(e.dataTransfer.getData('application/json'));
                const rect = canvas.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                
                this.placeElement(elementData, x, y);
            } catch (error) {
                console.error('[SceneElements] Drop error:', error);
            }
        });

        // Click to place selected element
        canvas.addEventListener('click', (e) => {
            if (this.selectedElement) {
                const rect = canvas.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                
                this.placeElement(this.selectedElement, x, y);
                this.clearSelection();
            }
        });
    }

    /**
     * Place an element on the canvas
     */
    placeElement(elementData, x, y) {
        const canvas = document.getElementById('scene-editor-canvas');
        if (!canvas) return null;

        const placedElement = {
            ...elementData,
            instanceId: `${elementData.id}_${++this.elementIdCounter}`,
            x: x - (elementData.defaultWidth || 40) / 2,
            y: y - (elementData.defaultHeight || 40) / 2,
            width: elementData.defaultWidth || 40,
            height: elementData.defaultHeight || 40,
            rotation: 0,
            zIndex: this.placedElements.length
        };

        this.placedElements.push(placedElement);
        this.renderPlacedElement(placedElement);
        
        // Dispatch custom event for external handlers
        canvas.dispatchEvent(new CustomEvent('elementPlaced', {
            detail: placedElement
        }));

        console.log('[SceneElements] Placed element:', placedElement.name, 'at', x, y);
        return placedElement;
    }

    /**
     * Render a placed element on the canvas
     */
    renderPlacedElement(element) {
        const canvas = document.getElementById('scene-editor-canvas');
        if (!canvas) return;

        const el = document.createElement('div');
        el.className = 'placed-element';
        el.id = element.instanceId;
        el.dataset.elementId = element.id;
        el.style.cssText = `
            position: absolute;
            left: ${element.x}px;
            top: ${element.y}px;
            width: ${element.width}px;
            height: ${element.height}px;
            transform: rotate(${element.rotation}deg);
            z-index: ${element.zIndex};
            cursor: move;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: ${Math.min(element.width, element.height) * 0.7}px;
            user-select: none;
        `;
        el.innerHTML = `<span class="element-content">${element.icon}</span>`;
        el.title = element.name;

        // Make draggable within canvas
        this.makeDraggable(el, element);
        
        // Context menu for actions
        el.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            this.showElementContextMenu(e, element);
        });

        canvas.appendChild(el);
    }

    /**
     * Make a placed element draggable within the canvas
     */
    makeDraggable(el, element) {
        let isDragging = false;
        let startX, startY, initialX, initialY;

        el.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return; // Left click only
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            initialX = element.x;
            initialY = element.y;
            el.classList.add('dragging');
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            
            element.x = initialX + dx;
            element.y = initialY + dy;
            
            el.style.left = `${element.x}px`;
            el.style.top = `${element.y}px`;
        });

        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                el.classList.remove('dragging');
            }
        });
    }

    /**
     * Show context menu for a placed element
     */
    showElementContextMenu(event, element) {
        // Remove existing menu
        const existingMenu = document.querySelector('.element-context-menu');
        if (existingMenu) existingMenu.remove();

        const menu = document.createElement('div');
        menu.className = 'element-context-menu';
        menu.style.cssText = `
            position: fixed;
            left: ${event.clientX}px;
            top: ${event.clientY}px;
            z-index: 10000;
        `;
        
        const actions = [
            { label: '🔄 Rotate 45°', action: () => this.rotateElement(element, 45) },
            { label: '📏 Resize', action: () => this.showResizeDialog(element) },
            { label: '📋 Duplicate', action: () => this.duplicateElement(element) },
            { label: '🗑️ Delete', action: () => this.removeElement(element) }
        ];

        if (element.rotatable === false) {
            actions.shift(); // Remove rotate option
        }

        actions.forEach(({ label, action }) => {
            const item = document.createElement('button');
            item.className = 'context-menu-item';
            item.textContent = label;
            item.addEventListener('click', () => {
                action();
                menu.remove();
            });
            menu.appendChild(item);
        });

        document.body.appendChild(menu);

        // Close menu on click outside
        const closeMenu = (e) => {
            if (!menu.contains(e.target)) {
                menu.remove();
                document.removeEventListener('click', closeMenu);
            }
        };
        setTimeout(() => document.addEventListener('click', closeMenu), 0);
    }

    /**
     * Rotate an element
     */
    rotateElement(element, degrees) {
        element.rotation = (element.rotation + degrees) % 360;
        const el = document.getElementById(element.instanceId);
        if (el) {
            el.style.transform = `rotate(${element.rotation}deg)`;
        }
    }

    /**
     * Duplicate an element
     */
    duplicateElement(element) {
        this.placeElement(element, element.x + 20, element.y + 20);
    }

    /**
     * Remove an element from the canvas
     */
    removeElement(element) {
        const el = document.getElementById(element.instanceId);
        if (el) el.remove();
        
        const idx = this.placedElements.findIndex(e => e.instanceId === element.instanceId);
        if (idx > -1) {
            this.placedElements.splice(idx, 1);
        }

        const canvas = document.getElementById('scene-editor-canvas');
        if (canvas) {
            canvas.dispatchEvent(new CustomEvent('elementRemoved', {
                detail: element
            }));
        }
    }

    /**
     * Show resize dialog for an element
     */
    showResizeDialog(element) {
        const newWidth = prompt('Enter new width:', element.width);
        const newHeight = prompt('Enter new height:', element.height);
        
        if (newWidth && newHeight) {
            element.width = parseInt(newWidth, 10) || element.width;
            element.height = parseInt(newHeight, 10) || element.height;
            
            const el = document.getElementById(element.instanceId);
            if (el) {
                el.style.width = `${element.width}px`;
                el.style.height = `${element.height}px`;
                el.style.fontSize = `${Math.min(element.width, element.height) * 0.7}px`;
            }
        }
    }

    /**
     * Get all placed elements (for export/save)
     */
    getPlacedElements() {
        return this.placedElements.map(e => ({
            id: e.id,
            instanceId: e.instanceId,
            name: e.name,
            icon: e.icon,
            category: e.category,
            x: e.x,
            y: e.y,
            width: e.width,
            height: e.height,
            rotation: e.rotation
        }));
    }

    /**
     * Load placed elements (from saved data)
     */
    loadPlacedElements(elements) {
        // Clear existing
        this.clearCanvas();
        
        // Place each element
        elements.forEach(el => {
            const fullElement = this.findElement(el.id);
            if (fullElement) {
                const placed = { ...fullElement, ...el };
                this.placedElements.push(placed);
                this.renderPlacedElement(placed);
            }
        });
    }

    /**
     * Find an element by ID in the library
     */
    findElement(elementId) {
        for (const category of this.categories) {
            const element = category.elements.find(e => e.id === elementId);
            if (element) return element;
        }
        return null;
    }

    /**
     * Clear all placed elements from canvas
     */
    clearCanvas() {
        const canvas = document.getElementById('scene-editor-canvas');
        if (canvas) {
            canvas.querySelectorAll('.placed-element').forEach(el => el.remove());
        }
        this.placedElements = [];
        this.elementIdCounter = 0;
    }

    /**
     * Toggle palette visibility
     */
    togglePalette() {
        const palette = document.getElementById('scene-element-palette');
        if (palette) {
            palette.classList.toggle('collapsed');
        }
    }
}

// Create global instance
window.sceneElementLibrary = new SceneElementLibrary();

// Export for module use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SceneElementLibrary;
}
