import sys
sys.path.insert(0, '.')

print("Testing all imports...")
modules = ['config', 'models', 'database', 'keyboards', 'handlers.profile', 'handlers.start', 'handlers.admin', 'handlers.catalog']

for module in modules:
    try:
        __import__(module)
        print(f"OK: {module}")
    except Exception as e:
        print(f"ERROR: {module} - {e}")

print("Done")