"""
uninstall_helper_user.py — removes .env on uninstall.
User-level uninstall. No admin needed. Just removes the .env file.
"""

import shutil
import sys
import os

def main():
    print("\nUninstalling Payroll Automation...\n")

    # Inno Setup passes {app}
    if len(sys.argv) > 1:
        app_dir = sys.argv[1]
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))

    # Safety check (VERY important)
    if not app_dir or app_dir in ["C:\\", "C:\\Windows", "C:\\Users"]:
        print("[Blocked] Unsafe directory detected!")
        return

    if os.path.exists(app_dir):
        try:
            shutil.rmtree(app_dir)
            print(f"[Deleted] {app_dir}")
        except Exception as e:
            print(f"[Error] Could not delete {app_dir} — {e}")
    else:
        print(f"[Info] Not found: {app_dir}")

    print("\nDone.\n")


if __name__ == "__main__":
    main()