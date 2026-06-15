import sys
sys.path.insert(0, '.')

try:
    import handlers.profile
    print("OK: handlers.profile")
except Exception as e:
    print(f"ERROR: handlers.profile - {e}")