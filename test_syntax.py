#!/usr/bin/env python
"""Test syntax of all files"""
import ast
import sys

files_to_check = [
    'handlers/profile.py',
    'handlers/payments.py', 
    'handlers/admin.py',
    'keyboards.py',
    'services/currency_service.py',
]

for file in files_to_check:
    try:
        with open(file, 'r', encoding='utf-8') as f:
            ast.parse(f.read())
        print(f"✅ {file} - OK")
    except SyntaxError as e:
        print(f"❌ {file} - ERROR at line {e.lineno}: {e.msg}")
        print(f"   {e.text}")
    except Exception as e:
        print(f"❌ {file} - ERROR: {e}")
