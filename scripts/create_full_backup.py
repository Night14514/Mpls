"""
Create full backup of the project before security enhancements.
"""

import shutil
import datetime
import sys
from pathlib import Path

def create_backup():
    """Create a complete backup of the project."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"mp_backup_{timestamp}"
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    
    backup_path = backup_dir / backup_name
    
    print(f"Creating backup: {backup_path}")
    
    # Exclude patterns
    def exclude_filter(src, names):
        excluded = []
        for name in names:
            if '__pycache__' in name:
                excluded.append(name)
            elif name.endswith('.pyc'):
                excluded.append(name)
            elif 'backup' in name.lower():
                excluded.append(name)
            elif name.endswith('.so') or name.endswith('.pyd'):
                excluded.append(name)
            elif name == 'build_output':
                excluded.append(name)
        return excluded
    
    try:
        shutil.copytree(".", backup_path, ignore=exclude_filter)
        print(f"✅ Backup created successfully: {backup_path}")
        return str(backup_path)
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    create_backup()