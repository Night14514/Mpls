import sys
sys.path.insert(0, '.')

try:
    import keyboards
    print("OK: keyboards")
except Exception as e:
    print(f"ERROR: keyboards - {e}")