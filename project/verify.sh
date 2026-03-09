#!/bin/bash
# Verification script for WitnessReplay project

echo "🔍 WitnessReplay Project Verification"
echo "====================================="
echo ""

# Check directory structure
echo "📁 Checking directory structure..."
REQUIRED_DIRS=(
    "backend/app/api"
    "backend/app/agents"
    "backend/app/services"
    "backend/app/models"
    "frontend/js"
    "frontend/css"
    "deploy/terraform"
    "docs"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo "  ✅ $dir"
    else
        echo "  ❌ $dir MISSING"
    fi
done

echo ""
echo "📄 Checking critical files..."
REQUIRED_FILES=(
    "backend/app/main.py"
    "backend/app/config.py"
    "backend/app/api/routes.py"
    "backend/app/api/websocket.py"
    "backend/app/agents/scene_agent.py"
    "backend/app/services/firestore.py"
    "backend/app/services/storage.py"
    "backend/app/services/image_gen.py"
    "frontend/index.html"
    "frontend/js/app.js"
    "frontend/js/audio.js"
    "backend/requirements.txt"
    "backend/Dockerfile"
    "deploy/deploy.sh"
    "deploy/cloudbuild.yaml"
    "deploy/terraform/main.tf"
    "README.md"
    ".env.example"
    ".gitignore"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file"
    else
        echo "  ❌ $file MISSING"
    fi
done

echo ""
echo "🐍 Checking Python environment..."
if [ -d "backend/venv" ]; then
    echo "  ✅ Virtual environment exists"
    source backend/venv/bin/activate
    if python -c "from app.main import app" 2>/dev/null; then
        echo "  ✅ FastAPI app imports successfully"
    else
        echo "  ⚠️  FastAPI app has import issues (may need env vars)"
    fi
    deactivate
else
    echo "  ⚠️  Virtual environment not found (run setup first)"
fi

echo ""
echo "📊 Code Statistics..."
echo "  Backend Python: $(find backend/app -name '*.py' -exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}') lines"
echo "  Frontend JS: $(find frontend/js -name '*.js' -exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}') lines"
echo "  Total files: $(find . -type f -not -path '*/venv/*' -not -path '*/.git/*' | wc -l)"

echo ""
echo "🔒 Git Status..."
if [ -d ".git" ]; then
    echo "  ✅ Git repository initialized"
    echo "  Commits: $(git rev-list --count HEAD)"
    echo "  Current branch: $(git branch --show-current)"
else
    echo "  ❌ Git repository not initialized"
fi

echo ""
echo "✅ Verification Complete!"
echo ""
echo "Next steps:"
echo "1. Set up environment: cp .env.example backend/.env"
echo "2. Add your GOOGLE_API_KEY to backend/.env"
echo "3. Run: cd backend && source venv/bin/activate && uvicorn app.main:app --reload"
echo "4. Open: http://localhost:8080"
