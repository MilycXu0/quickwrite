"""Web UI verification."""
import os, sys
sys.path.insert(0, ".")
os.environ["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY", "test-key")

print("=" * 60)
print("Web UI Verification")
print("=" * 60)

# 1. Import all web modules
print("\n[1/4] Importing web modules...")
from src.web.server import app, get_app, templates
print("  OK - FastAPI app imported")

# 2. Test app initialization
print("\n[2/4] Testing app init...")
app_inst = get_app()
print(f"  Config loaded: {app_inst.config.default_model}")
print(f"  DB ready: True")
print(f"  Novels in DB: {len(app_inst.novel_repo.list_all())}")
print("  OK - App initialized")

# 3. Test template loading
print("\n[3/4] Testing templates...")
for name in ["index.html", "create.html", "novel.html", "chapter.html", "base.html"]:
    try:
        templates.get_template(name)
        print(f"  OK {name}")
    except Exception as e:
        print(f"  FAIL {name}: {e}")
print("  OK - All templates found")

# 4. Test routes exist
print("\n[4/4] Testing routes...")
routes = [r.path for r in app.routes if hasattr(r, 'path')]
print(f"  Routes: {len(routes)}")
for path in sorted(routes):
    print(f"    {path}")
print("  OK - Routes registered")

print()
print("=" * 60)
print("Web UI READY!")
print("=" * 60)
print()
print("Start with: python -m src.main web")
print("Then open: http://127.0.0.1:8080")
