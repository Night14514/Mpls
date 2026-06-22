"""
Автоматическое создание резервных копий SQLite базы данных.
Запускается по cron каждые 6 часов.
"""

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from logging import basicConfig, getLogger

logger = getLogger(__name__)


def backup_database(db_path: str, backup_dir: str, max_backups: int = 10) -> bool:
    """Создать резервную копию базы данных."""
    try:
        db_file = Path(db_path)
        if not db_file.exists():
            logger.error("Database file not found: %s", db_path)
            return False
        
        backup_path = Path(backup_dir)
        backup_path.mkdir(parents=True, exist_ok=True)
        
        # Create backup filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_path / f"database_{timestamp}.db"
        
        # Close any open connections (WAL mode checkpoint)
        try:
            conn = sqlite3.connect(str(db_file))
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception as e:
            logger.warning("WAL checkpoint failed: %s", e)
        
        # Copy database file
        shutil.copy2(str(db_file), str(backup_file))
        logger.info("Database backup created: %s", backup_file)
        
        # Remove old backups (keep only max_backups)
        backups = sorted(backup_path.glob("database_*.db"), reverse=True)
        for old_backup in backups[max_backups:]:
            old_backup.unlink()
            logger.info("Removed old backup: %s", old_backup)
        
        return True
    except Exception as e:
        logger.error("Backup failed: %s", e)
        return False


if __name__ == "__main__":
    basicConfig(level="INFO", format="%(asctime)s - %(levelname)s - %(message)s")
    
    # Get database path from config or use default
    db_path = os.environ.get("DATABASE_PATH", "data/database.db")
    backup_dir = os.environ.get("BACKUP_DIR", "data/backups")
    
    success = backup_database(db_path, backup_dir)
    if not success:
        exit(1)
