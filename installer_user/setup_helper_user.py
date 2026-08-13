"""
setup_helper_user.py — writes .env file for user-level install.
No admin rights needed. Stores all config in a .env file next to the exe.
The app reads from this .env file instead of the registry.
"""
import argparse
import os
import sys
from pathlib import Path

KEYRING_SERVICE = "FinanceSuite"

try:
    import keyring
except ImportError:
    print("ERROR: keyring package not found. Run: pip install keyring")
    sys.exit(1)

def write_env(app_dir: str, values: dict):
   """
   Writes a .env file next to the executable.
   Location: {app_dir}/.env
   """
   env_path = os.path.join(app_dir, ".env")
   with open(env_path, "w", encoding="utf-8") as f:
       for key, value in values.items():
           # Escape quotes and newlines in values
           escaped = value.replace('"', '\\"').replace('\n', '\\n')
           f.write(f'{key}="{escaped}"\n')
   print(f"  [File] .env written to {env_path}")

def write_secrets(secrets: dict):
    """Write sensitive values to Windows Credential Manager via keyring."""
    for key, value in secrets.items():
        keyring.set_password(KEYRING_SERVICE, key, value)
        print(f"  [Credential Manager] {key} stored")

# Same secret keys written by setup_helper_user.py
SECRET_KEYS = [
    "CLIENT_ID",
    "TENANT_ID",
    "GH_PAT",
    "SP_BASE_URL",
    "config_loc",
    "PASSWORD_PREFIX",
]

# Current + legacy keyring service names to clean up
KEYRING_SERVICES = ["FinanceSuite", "PayrollAutomation"]

def delete_secrets():
    """Removes stored secrets from Windows Credential Manager, current and legacy service names."""
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

   delete_secrets()
   
   parser = argparse.ArgumentParser()

   # Secrets (go to Credential Manager)
   parser.add_argument("--client-id",           required=True)
   parser.add_argument("--tenant-id",           required=True)
   parser.add_argument("--sp-base-url",         required=True)
   parser.add_argument("--gh-pat",              required=False, default="")
   parser.add_argument("--config-loc",          required=True)
   parser.add_argument("--password-prefix",     required=False, default="INTOGREAT")

   # Secrets (go to .env)
   parser.add_argument("--loc",                 required=True)
   parser.add_argument("--installation",        required=True)
   parser.add_argument("--app-name",            required=True)
   parser.add_argument("--envt",                required=True)
   parser.add_argument("--version",             required=False, default="0.0.0")
   parser.add_argument("--support-email",       required=False, default="")
   parser.add_argument("--app-dir",             required=True, help="Directory where the .exe lives")
   args = parser.parse_args()

   print("\nFinance Suite — Writing configuration file...\n")

   write_env(args.app_dir, {
       "loc":                    args.loc,
       "installation_loc":       str(args.app_dir).replace("\\", "/"),
       "app":                    args.app_name,
       "ENVT":                   args.envt,
       "VERSION":                args.version,
       "support_email":          args.support_email
       
   })

   write_secrets({
      "CLIENT_ID":               args.client_id,
      "TENANT_ID":               args.tenant_id,
      "GH_PAT":                  args.gh_pat,
      "SP_BASE_URL":             args.sp_base_url,
      "config_loc":              args.config_loc,
      "PASSWORD_PREFIX":         args.password_prefix
   })
   
   print("Setup complete.\n")

if __name__ == "__main__":
   main()