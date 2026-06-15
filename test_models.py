import sys
sys.path.insert(0, '.')

try:
    import models
    print("OK: models")
except Exception as e:
    print(f"ERROR: models - {e}")