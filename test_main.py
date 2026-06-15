import sys
sys.path.insert(0, '.')

try:
    import main
    print("OK: main")
except Exception as e:
    print(f"ERROR: main - {e}")