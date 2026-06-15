#!/usr/bin/env python3
"""
Quick deployment script for production builds.
Automates the build and deployment process.
"""

import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class QuickDeploy:
    """Quick deployment automation for production builds."""

    def __init__(self, production_dir: str = "/opt/telegram-bot"):
        self.production_dir = Path(production_dir)
        self.build_dir = Path("build_output")

    def run_command(self, cmd: list, description: str = "") -> bool:
        """Run a shell command and return success status."""
        if description:
            print(f"🔧 {description}...")

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                print(result.stdout)
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Command failed: {e}")
            if e.stderr:
                print(e.stderr)
            return False

    def check_dependencies(self) -> bool:
        """Check if required dependencies are installed."""
        print("🔍 Checking dependencies...")

        required = ["python3", "pip"]
        missing = []

        for cmd in required:
            if not shutil.which(cmd):
                missing.append(cmd)

        if missing:
            print(f"❌ Missing dependencies: {missing}")
            print("   Please install missing dependencies")
            return False

        print("✅ All dependencies available")
        return True

    def install_python_dependencies(self) -> bool:
        """Install Python dependencies."""
        print("📦 Installing Python dependencies...")

        if not (Path("requirements.txt").exists()):
            print("❌ requirements.txt not found")
            return False

        return self.run_command(
            ["pip", "install", "-r", "requirements.txt"],
            "Installing packages"
        )

    def check_configuration(self) -> bool:
        """Check if .env configuration exists."""
        print("🔍 Checking configuration...")

        if not Path(".env").exists():
            print("❌ .env file not found")
            print("   Please create .env from .env.example")
            return False

        print("✅ Configuration file exists")
        return True

    def build_production(self, keep_sources: bool = False) -> bool:
        """Build production version with compiled modules."""
        print("🏗️ Building production version...")

        cmd = ["python", "build_production.py"]
        if keep_sources:
            cmd.append("--keep-sources")

        return self.run_command(cmd, "Building with Cython")

    def verify_build(self) -> bool:
        """Verify that build was successful."""
        print("✅ Verifying build...")

        if not self.build_dir.exists():
            print("❌ Build directory not found")
            return False

        # Check for critical files
        critical_files = [
            "main.py",
            "config.py",
            "integrity.json"
        ]

        missing = []
        for file in critical_files:
            if not (self.build_dir / file).exists():
                missing.append(file)

        if missing:
            print(f"❌ Missing critical files: {missing}")
            return False

        print("✅ Build verification passed")
        return True

    def backup_current_deployment(self) -> bool:
        """Backup current deployment before updating."""
        print("💾 Backing up current deployment...")

        if not self.production_dir.exists():
            print("   No existing deployment to backup")
            return True

        backup_dir = self.production_dir.parent / f"{self.production_dir.name}_backup"

        try:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.copytree(self.production_dir, backup_dir)
            print(f"✅ Backup created: {backup_dir}")
            return True
        except Exception as e:
            print(f"❌ Backup failed: {e}")
            return False

    def deploy_to_production(self) -> bool:
        """Deploy build to production directory."""
        print("🚀 Deploying to production...")

        try:
            # Create production directory if needed
            self.production_dir.mkdir(parents=True, exist_ok=True)

            # Copy build output
            for item in self.build_dir.iterdir():
                dest = self.production_dir / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()

                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            print(f"✅ Deployed to: {self.production_dir}")
            return True

        except Exception as e:
            print(f"❌ Deployment failed: {e}")
            return False

    def set_permissions(self) -> bool:
        """Set correct permissions for production directory."""
        print("🔐 Setting permissions...")

        try:
            # Set ownership (if running as root)
            if os.geteuid() == 0:
                import pwd
                import grp

                try:
                    user = pwd.getpwnam("botuser")
                    group = grp.getgrnam("botuser")

                    for root, dirs, files in os.walk(self.production_dir):
                        for d in dirs:
                            os.chown(os.path.join(root, d), user.pw_uid, group.gr_gid)
                        for f in files:
                            os.chown(os.path.join(root, f), user.pw_uid, group.gr_gid)

                    print("✅ Ownership set to botuser:botuser")
                except KeyError:
                    print("⚠️  botuser not found, skipping ownership change")

            # Set .env permissions
            env_file = self.production_dir / ".env"
            if env_file.exists():
                os.chmod(env_file, 0o600)
                print("✅ .env permissions set to 600")

            return True

        except Exception as e:
            print(f"⚠️  Permission setting failed: {e}")
            return True  # Not critical

    def restart_service(self) -> bool:
        """Restart systemd service."""
        print("🔄 Restarting service...")

        if not shutil.which("systemctl"):
            print("⚠️  systemctl not found, skipping service restart")
            return True

        return self.run_command(
            ["systemctl", "restart", "telegram-bot"],
            "Restarting service"
        )

    def check_service_status(self) -> bool:
        """Check service status after deployment."""
        print("📊 Checking service status...")

        if not shutil.which("systemctl"):
            print("⚠️  systemctl not found, skipping status check")
            return True

        return self.run_command(
            ["systemctl", "status", "telegram-bot"],
            "Checking status"
        )

    def deploy(self, keep_sources: bool = False, backup: bool = True) -> bool:
        """Run complete deployment process."""
        print("🚀 Starting quick deployment...\n")

        steps = [
            ("Check dependencies", self.check_dependencies),
            ("Install Python dependencies", self.install_python_dependencies),
            ("Check configuration", self.check_configuration),
            ("Build production", lambda: self.build_production(keep_sources)),
            ("Verify build", self.verify_build),
        ]

        if backup:
            steps.append(("Backup current deployment", self.backup_current_deployment))

        steps.extend([
            ("Deploy to production", self.deploy_to_production),
            ("Set permissions", self.set_permissions),
            ("Restart service", self.restart_service),
            ("Check service status", self.check_service_status),
        ])

        for step_name, step_func in steps:
            print(f"\n{'='*60}")
            if not step_func():
                print(f"\n❌ Deployment failed at: {step_name}")
                return False
            print(f"✅ {step_name} completed")

        print("\n" + "="*60)
        print("🎉 Deployment completed successfully!")
        print(f"📦 Production directory: {self.production_dir}")
        print("🔍 Check logs: journalctl -u telegram-bot -f")
        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Quick deployment for Telegram bot")
    parser.add_argument(
        "--production-dir",
        default="/opt/telegram-bot",
        help="Production directory (default: /opt/telegram-bot)"
    )
    parser.add_argument(
        "--keep-sources",
        action="store_true",
        help="Keep Python source files (development)"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup of current deployment"
    )

    args = parser.parse_args()

    deployer = QuickDeploy(args.production_dir)

    if not deployer.deploy(
        keep_sources=args.keep_sources,
        backup=not args.no_backup
    ):
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
