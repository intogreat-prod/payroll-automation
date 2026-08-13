"""
uninstall_helper_user.py — removes .env on uninstall.
User-level uninstall. No admin needed. Removes the .env file and
clears any secrets written to Windows Credential Manager, including
stale entries left over from the old PayrollAutomation service name.
"""

import shutil
import sys
import os

try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

# Current + legacy keyring service names to clean up
KEYRING_SERVICES = ["FinanceSuite", "PayrollAutomation"]

# Same secret keys written by setup_helper_user.py
SECRET_KEYS = [
    "CLIENT_ID",
    "TENANT_ID",
    "GH_PAT",
    "SP_BASE_URL",
    "config_loc",
    "PASSWORD_PREFIX",
]

def delete_secrets():
    """Removes stored secrets from Windows Credential Manager, current and legacy service names."""
    if not _KEYRING_AVAILABLE:
        print("[Skip] keyring package not available — nothing to clear.")
        return

    for service in KEYRING_SERVICES:
        for key in SECRET_KEYS:
            try:
                keyring.delete_password(service, key)
                print(f"  [Credential Manager] Removed {service}/{key}")
            except keyring.errors.PasswordDeleteError:
                # Not found — nothing to do
                pass
            except Exception as e:
                print(f"  [Warn] Could not remove {service}/{key} — {e}")

def main():
    print("\nUninstalling Finance Suite...\n")

    delete_secrets()

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