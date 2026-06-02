"""
setup_helper.py — one-time machine configuration for Payroll Automation.

This script is compiled to setup_helper.exe by PyInstaller and called
silently by the Inno Setup installer during installation. It writes all
config values to the Windows Registry and Credential Manager so the
main app never needs a .env file.

Inno Setup calls it as:
    setup_helper.exe --client-id {CLIENT_ID} --tenant-id {TENANT_ID} ...

All values are passed as CLI arguments by the installer so this script
contains no hardcoded secrets — the installer wizard collects them or
they are baked into the Inno Setup script by the dev before release.
"""

import argparse
import sys
import ctypes, sys

try:
    import winreg
except ImportError:
    print("ERROR: This script must run on Windows.")
    sys.exit(1)

try:
    import keyring
except ImportError:
    print("ERROR: keyring package not found. Run: pip install keyring")
    sys.exit(1)

# ── Constants ────────────────────────────────────────────────────────────────
REG_PATH        = r"SOFTWARE\Intogreat\PayrollAutomation"
KEYRING_SERVICE = "PayrollAutomation"


def write_registry(values: dict):
    """Write non-sensitive config values to HKLM registry."""
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE, REG_PATH, 0, winreg.KEY_SET_VALUE
    ) as reg:
        for key, value in values.items():
            winreg.SetValueEx(reg, key, 0, winreg.REG_SZ, value)
            print(f"  [Registry] {key} = {value}")


def write_secrets(secrets: dict):
    """Write sensitive values to Windows Credential Manager via keyring."""
    for key, value in secrets.items():
        keyring.set_password(KEYRING_SERVICE, key, value)
        print(f"  [Credential Manager] {key} stored")


def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("ERROR: Not running as admin")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Payroll Automation — Machine Setup")

    # Secrets (go to Credential Manager)
    parser.add_argument("--client-id",   required=True,  help="Azure AD app client ID")
    parser.add_argument("--tenant-id",   required=True,  help="Azure AD tenant ID")

    # Config (go to Registry)
    parser.add_argument("--sp-base-url", required=True,  help="SharePoint Graph base URL")
    parser.add_argument("--config-loc",  required=True,  help="Config JSON path in SharePoint drive")
    parser.add_argument("--loc",         required=True,  help="App data folder name (e.g. PayrollProd)")
    parser.add_argument("--app-name",    required=True,  help="Human-readable app name")
    parser.add_argument("--envt",        required=True,  help="Environment label (PROD / DEV)")
    parser.add_argument("--version",     required=False, default="1.0.0", help="App version string")
    parser.add_argument("--support-email", required=False, default="", help="Support email shown on login screen")

    args = parser.parse_args()

    print("\nPayroll Automation — Writing machine configuration...\n")

    write_secrets({
        "CLIENT_ID": args.client_id,
        "TENANT_ID": args.tenant_id,
    })

    write_registry({
        "SP_BASE_URL":    args.sp_base_url,
        "config_loc":     args.config_loc,
        "loc":            args.loc,
        "app":            args.app_name,
        "ENVT":           args.envt,
        "VERSION":        args.version,
        "support_email":  args.support_email,
    })

    print("\nSetup complete. You can now launch Payroll Automation.\n")


if __name__ == "__main__":
    main()
