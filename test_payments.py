import sys
sys.path.insert(0, '.')

try:
    import handlers.payments
    print("OK: handlers.payments")
except Exception as e:
    print(f"ERROR: handlers.payments - {e}")