#!/usr/bin/env python
print("Starting test")
import sys
sys.path.insert(0, '.')

print("Importing config...")
try:
    from config import get_settings
    print("Config OK")
except Exception as e:
    print(f"Config ERROR: {e}")

print("Done")