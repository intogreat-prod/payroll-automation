"""
uninstall_helper_user.py — removes .env on uninstall.
User-level uninstall. No admin needed. Just removes the .env file.
"""
import os
import sys

def main():
   print("\nPayroll Automation — Removing configuration file...\n")
   # Get the app directory from the argument passed by Inno Setup
   # Inno passes {app} as the first positional argument
   if len(sys.argv) > 1:
       app_dir = sys.argv[1]
   else:
       app_dir = os.path.dirname(os.path.abspath(__file__))
   env_path = os.path.join(app_dir, ".env")
   if os.path.exists(env_path):
       try:
           os.remove(env_path)
           print(f"  [File] {env_path} removed")
       except Exception as e:
           print(f"  [Error] Could not remove {env_path} — {e}")
   else:
       print(f"  [Info] {env_path} not found (already gone)")
   print("\nDone.\n")

if __name__ == "__main__":
   main()