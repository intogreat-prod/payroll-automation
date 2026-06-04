# Payroll Automation

A PyQt6 desktop app that validates, uploads, and processes payroll files through SharePoint and the Unmand RPA platform.

---

## What it does

- Authenticates users via Microsoft MSAL (silent → interactive → device code)
- Validates payroll Excel files against a remote header reference before upload
- Uploads validated CSVs to a dated SharePoint folder structure
- Triggers the Unmand robot to run payroll processing
- Runs a variance checker between a manual checker file and Unmand's output
- Manages users and deminimis settings via the Settings screen
- Archives old logs and validation files on each launch
- Uploads the session log to SharePoint on close (and on crash)

---

## Project structure

```
Payroll.py              # Entry point — boots Qt, creates Orchestrator
orchestrator.py         # App state, flow control, routes all UI events

features/
    payroll.py          # File picker, validation, and upload prep for payroll
    checker.py          # File picker and validation for the variance checker

services/
    msal_service.py     # Microsoft login (MSAL)
    sharepoint_service.py  # Graph API — file download/upload
    config_service.py   # Reads/writes the remote config JSON
    outlook_services.py # Sends email via Graph sendMail
    power_automate_service.py  # Triggers Power Automate HTTP flows
    unmand_service.py   # Starts and polls Unmand jobs

ui/
    main_window.py      # Root window, holds header/body/footer
    statuses.py         # All user-facing status message strings
    styles.py           # Qt stylesheets
    ui_factory.py       # Widget builders (button, label, input, card, etc.)
    components/
        header.py
        body.py         # Screen switcher — show_login(), show_payroll_feature(), etc.
        footer.py
        login_form.py

utils/
    logger.py           # App-wide logger (console + file)
    error_handler.py    # Global uncaught exception hook
    file_manager.py     # Archives old files, uploads session log
    file_utils.py       # Path helpers (app_data_path, resource_path, etc.)
    internet.py         # Quick connectivity check at startup
    email_template.py   # Welcome email HTML template
```

---

## Setup

**Requirements:** Python 3.11+, Windows (DPAPI token encryption)

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in the values (see [Environment variables](#environment-variables) below).

```bash
python Payroll.py
```

### PRE COMMIT GUIDE
Use pre-commit hooks to automatically check and code formatting and issues before creating a commit.
We use pre-commit library (https://pre-commit.com/) for this.
To set it up,
1. Install pre-commit
To install pre-commit, run the following:
```
pip install pre-commit
```
2. Install the git hook script.
Run the following to install the pre-commit Git hook.
```
pre-commit install
```
This will run pre-commit whenever you create a commit. It will check all the files in the commit to see if there are
issues. If there are issues, it will either automatically fix them or give information about the issues, so you can
fix it.
If you ever want to run pre-commit manually, just execute the following:
```
pre-commit run --all-files
```

---

## Environment variables

Create a `.env` file in the project root. All keys are required unless marked optional.

| Key           | Description                                                                                          |
| ------------- | ---------------------------------------------------------------------------------------------------- |
| `CLIENT_ID`   | Azure AD app registration client ID                                                                  |
| `TENANT_ID`   | Azure AD tenant ID                                                                                   |
| `GH_PAT`      | GitHub Repo token                                                                                    |
| `SP_BASE_URL` | Microsoft Graph SharePoint drive base URL, e.g. `https://graph.microsoft.com/v1.0/sites/<id>/drive/` |
| `config_loc`  | Path to the config JSON inside the drive, e.g. `root:/Config/payroll_config.json:/content`           |
| `loc`         | Leaf folder name under `~/Documents/Automations/` — separates prod/dev data on the same machine      |
| `app`         | Human-readable app name shown in error reports, e.g. `Payroll Automation`                            |
| `ENVT`        | Environment label shown in error reports, e.g. `PROD` or `DEV`                                       |

---

## Remote config (SharePoint JSON)

The app fetches a JSON config file from SharePoint on every login. It controls:

- `users` — list of allowed email addresses
- `payroll.folder` — base SharePoint folder for uploads
- `payroll.required_files` — file names the user must provide
- `payroll.headers_loc` — path to the Payroll Headers Excel
- `payroll.expected_id_names` — accepted Employee ID column variants
- `deminimis` — deminimis values editable from the Settings screen
- `unmand.webhook` / `unmand.token` — Unmand API details
- `teams.flow` / `teams.id` — Power Automate webhook for error reporting
- `entra.flow_url` / `entra.teams_group` — Power Automate flow for adding users
- `log_folder` — SharePoint folder where session logs are uploaded

---

## Building a standalone executable

```bash
pip install pyinstaller
pyinstaller Payroll.spec
```

The bundled `.exe` will be in `dist/`. Asset files (images, icons) are resolved via `resource_path()` which handles the `sys._MEIPASS` path automatically.

---

## Architecture notes

The app follows a strict three-layer separation:

- **Body** (`ui/components/body.py`) — renders screens, never calls services directly
- **Orchestrator** (`orchestrator.py`) — owns all state, routes events, calls services
- **Services / Features** — pure logic, no UI imports

All callbacks flow as:
```
Body.on_clicked → Orchestrator handler → Service → Orchestrator → body.show_*()
```

Logging is centralised — one `Logger` instance is created in `Orchestrator.__init__` and passed down. Nothing creates its own logger.

---

## Data location

All runtime data is written to:
```
~/Documents/Automations/<loc>/
    data/
        logs/         ← one log file per session
        archive/      ← old logs and validation files, sorted YYYY/MM/DD/
        validation/   ← checker variance Excel exports
        auth/msal/    ← encrypted MSAL token cache
```

---

## Building the installer (Inno Setup)

### Prerequisites

- [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed on your build machine
- PyInstaller: `pip install pyinstaller`

### Step 1 — Fill in your values

Open `installer/PayrollAutomation.iss` and update the `[Config]` section at the top:

```
#define ClientID     "YOUR-CLIENT-ID-HERE"
#define TenantID     "YOUR-TENANT-ID-HERE"
#define SPBaseURL    "https://graph.microsoft.com/v1.0/sites/YOUR-SITE-ID/drive/"
#define ConfigLoc    "root:/Config/payroll_config.json:/content"
```

These values are embedded into the installer and written to the target machine during install. They never appear in the installed files themselves.

### Step 2 — Build the executables

```bash
# Main app
pyinstaller Payroll.spec

# Setup helper (writes registry + Credential Manager on install)
pyinstaller installer/setup_helper.spec

# Uninstall helper (cleans up on uninstall)
pyinstaller installer/uninstall_helper.spec
```

All three `.exe` files land in `dist/`.

### Step 3 — Compile the installer

Open `installer/PayrollAutomation.iss` in Inno Setup Compiler and press **Build → Compile** (or `Ctrl+F9`).

Output: `installer/Output/PayrollAutomation_Setup.exe`

### What the installer does

1. Copies `PayrollAutomation.exe` to `Program Files\Intogreat Solutions\Payroll Automation\`
2. Runs `setup_helper.exe` silently, which:
   - Writes `CLIENT_ID` and `TENANT_ID` to **Windows Credential Manager** (DPAPI-encrypted)
   - Writes all other config values to **HKLM\SOFTWARE\Intogreat\PayrollAutomation**
3. Creates Start Menu shortcuts (and optionally a desktop shortcut)
4. Registers a proper uninstaller in **Add or Remove Programs**

### What uninstalling does

1. Runs `uninstall_helper.exe` which removes the registry key and Credential Manager entries
2. Removes the install directory
3. Removes the Start Menu group

### Config storage at a glance (Admin-required App)

| Value                                    | Where                      | Protected by         |
| ---------------------------------------- | -------------------------- | -------------------- |
| `CLIENT_ID`, `TENANT_ID`                 | Windows Credential Manager | DPAPI (per OS user)  |
| `SP_BASE_URL`, `config_loc`, `loc`, etc. | Windows Registry (HKLM)    | OS ACL (admin write) |

### Config storage at a glance (No Admin-required App)
| `.env` file                              | Dev machines only          | Encrypted                    |
