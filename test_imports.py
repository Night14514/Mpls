import sys
sys.path.insert(0, '.')

modules = ['config', 'models', 'database', 'keyboards', 'handlers.profile', 'handlers.payments']

for module in modules:
    try:
        __import__(module)
        print(f"OK: {module}")
    except Exception as e:
        print(f"ERROR: {module} - {e}")