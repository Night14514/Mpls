#!/usr/bin/env python3
"""
Automatic backup script before security implementation.
Creates timestamped backup of the entire project.
"""

import os
import sys
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

def create_backup():
    """Create timestamped backup of the project."""
    project_root = Path(__file__).parent.parent
    backup_dir = project_root.parent / f"mp_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"📦 Creating backup of project...")
    print(f"   Source: {project_root}")
    print(f"   Target: {backup_dir}")

    try:
        # Create backup directory
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Copy entire project (excluding common build artifacts)
        exclude_dirs = {'.git', '__pycache__', '*.pyc', '*.pyo', 'venv', 'env', '.venv',
                       'build', 'dist', '*.egg-info', '.tox', 'temp', 'tmp', 'build_output'}

        for item in project_root.iterdir():
            if any(item.name == excl.strip('*') for excl in exclude_dirs):
                print(f"   ⏭️  Skipping: {item.name}")
                continue
            if any(item.match(excl) for excl in exclude_dirs):
                continue

            dest = backup_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
                print(f"   📁 Copied: {item.name}/")
            else:
                shutil.copy2(item, dest)
                print(f"   📄 Copied: {item.name}")

        # Create backup manifest
        manifest_file = backup_dir / "backup_manifest.txt"
        with open(manifest_file, 'w') as f:
            f.write(f"Backup created: {datetime.now().isoformat()}\n")
            f.write(f"Project root: {project_root}\n")
            f.write(f"Backup location: {backup_dir}\n\n")
            f.write("Backup contents:\n")
            for item in sorted(backup_dir.rglob('*')):
                if item.is_file():
                    f.write(f"  {item.relative_to(backup_dir)}\n")

        print(f"\n✅ Backup completed successfully!")
        print(f"   Location: {backup_dir}")
        print(f"   Manifest: {manifest_file}")

        # Try to create git tag if in git repository
        if (project_root / '.git').exists():
            try:
                tag_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                subprocess.run(['git', 'tag', tag_name], cwd=project_root, check=True)
                print(f"   Git tag: {tag_name}")
            except subprocess.CalledProcessError as e:
                print(f"   ⚠️  Could not create git tag: {e}")

        return True

    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return False

if __name__ == "__main__":
    if create_backup():
        sys.exit(0)
    else:
        sys.exit(1)
