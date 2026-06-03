"""
setup_helper_user.py — writes .env file for user-level install.
No admin rights needed. Stores all config in a .env file next to the exe.
The app reads from this .env file instead of the registry.
"""
import argparse
import os
import sys

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

def main():
   parser = argparse.ArgumentParser()
   parser.add_argument("--client-id",      required=True)
   parser.add_argument("--tenant-id",      required=True)
   parser.add_argument("--sp-base-url",    required=True)
   parser.add_argument("--config-loc",     required=True)
   parser.add_argument("--loc",            required=True)
   parser.add_argument("--app-name",       required=True)
   parser.add_argument("--envt",           required=True)
   parser.add_argument("--version",        required=False, default="1.0.0")
   parser.add_argument("--support-email",  required=False, default="")
   parser.add_argument("--gh-pat",         required=False, default="")
   parser.add_argument("--app-dir",        required=True, help="Directory where the .exe lives")
   args = parser.parse_args()

   print("\nPayroll Automation — Writing configuration file...\n")

   write_env(args.app_dir, {
       "CLIENT_ID":    args.client_id,
       "TENANT_ID":    args.tenant_id,
       "SP_BASE_URL":  args.sp_base_url,
       "config_loc":   args.config_loc,
       "loc":          args.loc,
       "app":          args.app_name,
       "ENVT":         args.envt,
       "VERSION":      args.version,
       "support_email": args.support_email,
       "GH_PAT":       args.gh_pat,
   })
   
   print("Setup complete.\n")

if __name__ == "__main__":
   main()