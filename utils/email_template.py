"""
email_template.py
-----------------
HTML email templates used by the Finance Suite app.

Templates are plain Python string constants with {placeholder} slots
for runtime values.  They are rendered via str.format() at the call
site (see orchestrator._add_user).

Available templates
-------------------
WELCOME_EMAIL
    Sent to a newly added user.
    Slots: {user} — display name of the admin who added them.
"""

# ---------------------------------------------------------------------------
# WELCOME EMAIL
# Sent via Microsoft Graph (POST /me/sendMail) when an admin adds a new user.
# Slot  : {user}  — the display name of the admin who granted access.
# ---------------------------------------------------------------------------

WELCOME_EMAIL = """
    <html>
    <head>
        <meta charset='UTF-8'>
        <meta name='viewport' content='width=device-width, initial-scale=1.0'>
        <title>Finance Suite</title>
    </head>

    <body style='margin:0;padding:0;background-color:#1E1E1E;font-family:Arial,sans-serif;color:#333;'>

        <!-- HEADER LOGO -->
        <div style='margin-top:15px;'>
            <img src='https://4867849.fs1.hubspotusercontent-na1.net/hub/4867849/hubfs/Branding/RGB_Intogreat__White%201.png?t=1740109657770&width=860'
                style='width:100%;max-width:700px;border-radius:10px;margin:10px auto;display:block;'>
        </div>

        <!-- BODY CARD -->
        <div style='background-color:#ffffff;margin:30px auto;padding:30px;border-radius:8px;width:90%;max-width:900px;
                    box-shadow:0 2px 8px rgba(0,0,0,0.1);'>

            <p>Hi <b>Team,</b></p>

            <p>Welcome to <b>Finance Suite</b>!</p>

            <p style='margin-top:20px;'>
                <b>{user}</b> has added you as a user of the Finance Suite system.
                Let's get you set up.
            </p>

            <p style='margin-top:15px;'><b>Getting Started:</b></p>

            <p>
                1. Download the application from the official folder using this link: 
                <a href="{download_link}" target="_blank">Download Application</a>.<br>

                2. Follow the installation guide to properly set up the application: 
                <a href="{installation_guide}" target="_blank">View Installation Guide</a>.<br>

                3. If the application fails to open or you encounter any issues, please contact the Automation Team for assistance.<br>
            </p>

        </div>

        <p style='font-size:12px;color:#777;text-align:center;margin:20px 0;'>
            DO NOT REPLY — This is an automated email.
        </p>

    </body>
    </html>
"""
