/**
 * 3D Scene Viewer for WitnessReplay
 * Provides 3D visualization of scene elements using Three.js
 */

class Scene3DViewer {
    constructor() {
        this.container = null;
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.controls = null;
        this.meshes = new Map(); // instanceId -> mesh
        this.isActive = false;
        this.animationId = null;
        this.gridHelper = null;
        this.groundPlane = null;
    }

    /**
     * Initialize the 3D viewer
     */
    async init() {
        // Check if Three.js is loaded
        if (typeof THREE === 'undefined') {
            console.warn('[Scene3D] Three.js not loaded, loading dynamically...');
            await this.loadThreeJS();
        }
        console.debug('[Scene3D] Initialized');
    }

    /**
     * Load Three.js from CDN
     */
    loadThreeJS() {
        return new Promise((resolve, reject) => {
            // Load Three.js core
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
            script.onload = () => {
                // Load OrbitControls
                const controlsScript = document.createElement('script');
                controlsScript.src = 'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js';
                controlsScript.onload = resolve;
                controlsScript.onerror = reject;
                document.head.appendChild(controlsScript);
            };
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    /**
     * Create the 3D scene
     */
    createScene(container) {
        this.container = container;
        const width = container.clientWidth;
        const height = container.clientHeight;

        // Create scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x1a1a2e);

        // Create camera
        this.camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000);
        this.camera.position.set(0, 150, 200);
        this.camera.lookAt(0, 0, 0);

        // Create renderer
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.setSize(width, height);
        this.renderer.setPixelRatio(window.devicePixelRatio);
        this.renderer.shadowMap.enabled = true;
        container.appendChild(this.renderer.domElement);

        // Add OrbitControls
        if (THREE.OrbitControls) {
            this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
            this.controls.enableDamping = true;
            this.controls.dampingFactor = 0.05;
            this.controls.minDistance = 50;
            this.controls.maxDistance = 500;
            this.controls.maxPolarAngle = Math.PI / 2.1; // Prevent going below ground
        }

        // Create ground/floor
        this.createGround();

        // Add grid
        this.createGrid();

        // Add lighting
        this.createLighting();

        // Handle resize
        window.addEventListener('resize', () => this.handleResize());

        console.debug('[Scene3D] Scene created');
    }

    /**
     * Create ground plane
     */
    createGround() {
        // Ground plane
        const groundGeom = new THREE.PlaneGeometry(400, 300);
        const groundMat = new THREE.MeshStandardMaterial({
            color: 0x2d3436,
            roughness: 0.9,
            metalness: 0.1
        });
        this.groundPlane = new THREE.Mesh(groundGeom, groundMat);
        this.groundPlane.rotation.x = -Math.PI / 2;
        this.groundPlane.position.y = 0;
        this.groundPlane.receiveShadow = true;
        this.scene.add(this.groundPlane);

        // Road/pavement area (center stripe)
        const roadGeom = new THREE.PlaneGeometry(80, 300);
        const roadMat = new THREE.MeshStandardMaterial({
            color: 0x4a4a4a,
            roughness: 0.7
        });
        const road = new THREE.Mesh(roadGeom, roadMat);
        road.rotation.x = -Math.PI / 2;
        road.position.y = 0.1;
        this.scene.add(road);

        // Center line
        const lineGeom = new THREE.PlaneGeometry(2, 280);
        const lineMat = new THREE.MeshStandardMaterial({
            color: 0xf1c40f,
            roughness: 0.5
        });
        const centerLine = new THREE.Mesh(lineGeom, lineMat);
        centerLine.rotation.x = -Math.PI / 2;
        centerLine.position.y = 0.2;
        this.scene.add(centerLine);
    }

    /**
     * Create grid helper
     */
    createGrid() {
        this.gridHelper = new THREE.GridHelper(400, 20, 0x555555, 0x333333);
        this.gridHelper.position.y = 0.05;
        this.scene.add(this.gridHelper);
    }

    /**
     * Create lighting for the scene
     */
    createLighting() {
        // Ambient light
        const ambient = new THREE.AmbientLight(0xffffff, 0.4);
        this.scene.add(ambient);

        // Directional light (sun)
        const directional = new THREE.DirectionalLight(0xffffff, 0.8);
        directional.position.set(100, 200, 100);
        directional.castShadow = true;
        directional.shadow.mapSize.width = 1024;
        directional.shadow.mapSize.height = 1024;
        directional.shadow.camera.near = 0.5;
        directional.shadow.camera.far = 500;
        directional.shadow.camera.left = -200;
        directional.shadow.camera.right = 200;
        directional.shadow.camera.top = 200;
        directional.shadow.camera.bottom = -200;
        this.scene.add(directional);

        // Hemisphere light for ambient variation
        const hemi = new THREE.HemisphereLight(0x87ceeb, 0x2d3436, 0.3);
        this.scene.add(hemi);
    }

    /**
     * Get 3D color and shape for element category
     */
    getElementVisuals(element) {
        const category = element.category || element.id?.split('_')[0] || 'misc';
        
        const visualConfig = {
            // Vehicles
            vehicle: { color: 0x3498db, shape: 'car', scale: 1.5 },
            car: { color: 0x3498db, shape: 'car', scale: 1.5 },
            truck: { color: 0x2980b9, shape: 'box', scale: 2 },
            motorcycle: { color: 0xe74c3c, shape: 'cylinder', scale: 0.8 },
            bicycle: { color: 0x27ae60, shape: 'cylinder', scale: 0.6 },
            bus: { color: 0xf39c12, shape: 'box', scale: 2.5 },
            
            // People
            person: { color: 0xfdcb6e, shape: 'capsule', scale: 1 },
            people: { color: 0xfdcb6e, shape: 'capsule', scale: 1 },
            witness: { color: 0x74b9ff, shape: 'capsule', scale: 1 },
            suspect: { color: 0xe17055, shape: 'capsule', scale: 1 },
            victim: { color: 0xd63031, shape: 'capsule', scale: 1 },
            
            // Infrastructure
            building: { color: 0x636e72, shape: 'building', scale: 3 },
            tree: { color: 0x00b894, shape: 'tree', scale: 2 },
            sign: { color: 0xfdcb6e, shape: 'sign', scale: 1 },
            light: { color: 0xffeaa7, shape: 'pole', scale: 2 },
            pole: { color: 0x95a5a6, shape: 'pole', scale: 2 },
            
            // Evidence
            evidence: { color: 0xe84393, shape: 'marker', scale: 0.8 },
            marker: { color: 0xff7675, shape: 'cone', scale: 0.5 },
            debris: { color: 0x6c5ce7, shape: 'scatter', scale: 0.5 },
            
            // Default
            misc: { color: 0x95a5a6, shape: 'box', scale: 1 }
        };

        // Find matching config
        for (const [key, config] of Object.entries(visualConfig)) {
            if (category.toLowerCase().includes(key) || 
                (element.id && element.id.toLowerCase().includes(key)) ||
                (element.name && element.name.toLowerCase().includes(key))) {
                return config;
            }
        }
        return visualConfig.misc;
    }

    /**
     * Create 3D mesh for element
     */
    createMesh(element, visuals) {
        let geometry;
        const baseSize = 20 * visuals.scale;

        switch (visuals.shape) {
            case 'car':
                // Car-like shape (box with slanted front)
                geometry = new THREE.BoxGeometry(baseSize * 2, baseSize * 0.6, baseSize);
                break;
            case 'box':
                geometry = new THREE.BoxGeometry(baseSize, baseSize * 0.8, baseSize * 0.6);
                break;
            case 'capsule':
                // Person-like capsule
                geometry = new THREE.CylinderGeometry(baseSize * 0.3, baseSize * 0.3, baseSize * 1.5, 8);
                break;
            case 'cylinder':
                geometry = new THREE.CylinderGeometry(baseSize * 0.4, baseSize * 0.4, baseSize * 0.8, 16);
                break;
            case 'building':
                geometry = new THREE.BoxGeometry(baseSize * 1.5, baseSize * 2, baseSize * 1.5);
                break;
            case 'tree':
                // Use cone for tree
                geometry = new THREE.ConeGeometry(baseSize * 0.6, baseSize * 2, 8);
                break;
            case 'sign':
            case 'pole':
                geometry = new THREE.CylinderGeometry(baseSize * 0.1, baseSize * 0.1, baseSize * 2, 8);
                break;
            case 'cone':
            case 'marker':
                geometry = new THREE.ConeGeometry(baseSize * 0.3, baseSize * 0.6, 16);
                break;
            case 'scatter':
                geometry = new THREE.IcosahedronGeometry(baseSize * 0.3, 0);
                break;
            default:
                geometry = new THREE.BoxGeometry(baseSize, baseSize, baseSize);
        }

        const material = new THREE.MeshStandardMaterial({
            color: visuals.color,
            roughness: 0.7,
            metalness: 0.1
        });

        const mesh = new THREE.Mesh(geometry, material);
        mesh.castShadow = true;
        mesh.receiveShadow = true;

        return mesh;
    }

    /**
     * Add element to 3D scene
     */
    addElement(element) {
        if (!this.scene) return;

        const visuals = this.getElementVisuals(element);
        const mesh = this.createMesh(element, visuals);

        // Convert 2D position to 3D (center the canvas coords)
        const canvasWidth = 400;  // Approximate canvas width
        const canvasHeight = 350; // Approximate canvas height
        
        const x3d = (element.x - canvasWidth / 2) * 0.8;
        const z3d = (element.y - canvasHeight / 2) * 0.8;
        const y3d = mesh.geometry.parameters?.height ? mesh.geometry.parameters.height / 2 : 10;

        mesh.position.set(x3d, y3d, z3d);
        mesh.rotation.y = THREE.MathUtils.degToRad(element.rotation || 0);

        mesh.userData = { element: element };
        this.scene.add(mesh);
        this.meshes.set(element.instanceId, mesh);

        // Add label sprite
        this.addLabel(mesh, element);

        console.debug('[Scene3D] Added element:', element.name);
    }

    /**
     * Add text label above mesh
     */
    addLabel(mesh, element) {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        canvas.width = 256;
        canvas.height = 64;

        ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.font = '32px Arial';
        ctx.fillStyle = '#ffffff';
        ctx.textAlign = 'center';
        ctx.fillText(element.icon + ' ' + element.name, canvas.width / 2, 42);

        const texture = new THREE.CanvasTexture(canvas);
        const spriteMat = new THREE.SpriteMaterial({ map: texture });
        const sprite = new THREE.Sprite(spriteMat);
        sprite.scale.set(40, 10, 1);
        
        const meshHeight = mesh.geometry.parameters?.height || 20;
        sprite.position.y = meshHeight + 15;
        mesh.add(sprite);
    }

    /**
     * Update element position in 3D
     */
    updateElement(element) {
        const mesh = this.meshes.get(element.instanceId);
        if (!mesh) return;

        const canvasWidth = 400;
        const canvasHeight = 350;
        
        const x3d = (element.x - canvasWidth / 2) * 0.8;
        const z3d = (element.y - canvasHeight / 2) * 0.8;

        mesh.position.x = x3d;
        mesh.position.z = z3d;
        mesh.rotation.y = THREE.MathUtils.degToRad(element.rotation || 0);
    }

    /**
     * Remove element from 3D scene
     */
    removeElement(instanceId) {
        const mesh = this.meshes.get(instanceId);
        if (mesh) {
            this.scene.remove(mesh);
            mesh.geometry.dispose();
            mesh.material.dispose();
            this.meshes.delete(instanceId);
        }
    }

    /**
     * Sync all elements from 2D canvas to 3D
     */
    syncFromLibrary() {
        if (!window.sceneElementLibrary) return;
        
        // Clear existing
        this.meshes.forEach((mesh, id) => {
            this.scene.remove(mesh);
            mesh.geometry.dispose();
            mesh.material.dispose();
        });
        this.meshes.clear();

        // Add all placed elements
        const elements = window.sceneElementLibrary.getPlacedElements();
        elements.forEach(el => this.addElement(el));
        
        console.debug('[Scene3D] Synced', elements.length, 'elements from 2D');
    }

    /**
     * Start animation loop
     */
    animate() {
        if (!this.isActive) return;
        
        this.animationId = requestAnimationFrame(() => this.animate());
        
        if (this.controls) {
            this.controls.update();
        }
        
        this.renderer.render(this.scene, this.camera);
    }

    /**
     * Handle window resize
     */
    handleResize() {
        if (!this.container || !this.camera || !this.renderer) return;
        
        const width = this.container.clientWidth;
        const height = this.container.clientHeight;
        
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height);
    }

    /**
     * Activate 3D view
     */
    activate(container) {
        if (this.isActive) return;
        
        this.isActive = true;
        
        if (!this.scene) {
            this.createScene(container);
        } else {
            container.appendChild(this.renderer.domElement);
        }
        
        this.syncFromLibrary();
        this.animate();
        
        console.debug('[Scene3D] Activated');
    }

    /**
     * Deactivate 3D view
     */
    deactivate() {
        if (!this.isActive) return;
        
        this.isActive = false;
        
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        
        if (this.renderer && this.renderer.domElement.parentNode) {
            this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
        }
        
        console.debug('[Scene3D] Deactivated');
    }

    /**
     * Reset camera to default position
     */
    resetCamera() {
        if (!this.camera || !this.controls) return;
        
        this.camera.position.set(0, 150, 200);
        this.camera.lookAt(0, 0, 0);
        this.controls.reset();
    }

    /**
     * Toggle grid visibility
     */
    toggleGrid() {
        if (this.gridHelper) {
            this.gridHelper.visible = !this.gridHelper.visible;
        }
    }

    /**
     * Clean up resources
     */
    dispose() {
        this.deactivate();
        
        this.meshes.forEach((mesh) => {
            mesh.geometry.dispose();
            mesh.material.dispose();
        });
        this.meshes.clear();
        
        if (this.renderer) {
            this.renderer.dispose();
        }
        
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.controls = null;
    }
}

// Global instance
window.scene3DViewer = new Scene3DViewer();

// Initialize when DOM ready
document.addEventListener('DOMContentLoaded', () => {
    window.scene3DViewer.init();
});

// Export for module use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Scene3DViewer;
}
