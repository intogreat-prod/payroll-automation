"""
uninstall_helper.py — cleans up machine configuration on uninstall.

Called by Inno Setup during uninstallation:
    uninstall_helper.exe

Removes the registry key and Credential Manager entries written by setup_helper.
"""

import ctypes, sys

try:
    import winreg
except ImportError:
    sys.exit(0)

try:
    import keyring
except ImportError:
    keyring = None

REG_PATH        = r"SOFTWARE\Intogreat\FinanceSuite"
REG_PARENT      = r"SOFTWARE\Intogreat"
KEYRING_SERVICE = "FinanceSuite"
SECRET_KEYS     = ["CLIENT_ID", "TENANT_ID"]


def main():
    print("\nFinance Suite — Removing machine configuration...\n")

    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("ERROR: Not running as admin")
        sys.exit(1)

    # Remove secrets from Credential Manager
    if keyring:
        for key in SECRET_KEYS:
            try:
                keyring.delete_password(KEYRING_SERVICE, key)
                print(f"  [Credential Manager] {key} removed")
            except Exception:
                pass  # Already gone — fine

    # Remove the app registry key
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, REG_PATH)
        print(f"  [Registry] {REG_PATH} removed")
    except FileNotFoundError:
        pass

    # Remove the parent Intogreat key if it's now empty
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_PARENT) as parent:
            num_subkeys, _, _ = winreg.QueryInfoKey(parent)
            if num_subkeys == 0:
                winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, REG_PARENT)
                print(f"  [Registry] {REG_PARENT} removed (was empty)")
    except (FileNotFoundError, OSError):
        pass

    print("\nUninstall cleanup complete.\n")


if __name__ == "__main__":
    main()
