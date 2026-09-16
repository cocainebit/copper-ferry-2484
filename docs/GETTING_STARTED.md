# Getting started with your desktop

This guide describes the current local preview of our cloud desktop platform. Hosted signup and payments are not enabled yet.

## Open your computer

1. Open http://localhost:3000/app.
2. Select **My computer**, or create a computer.
3. Wait for **Connected** above the live desktop. If it is stopped, click **Start**.
4. Click **Take control** to use the mouse and keyboard. Click inside the desktop to focus it. Use the fullscreen button for more space.
5. Click **Return to agent** when you are finished controlling it.

The screen is a continuous live stream. Closing this tab does not stop the computer or a running task. An idle computer automatically stops after 15 minutes. Start it again to continue.

## Connect the agent

In **Settings**, add your Anthropic API key. Provider usage is billed by Anthropic. Do not paste API keys into task messages or public documents.

Open your computer and describe a task in the chat. The agent uses the visible browser, terminal and computer controls. When it asks for approval, review the action and approve or decline. During takeover, the agent pauses at its next tool boundary. These approval checks depend on model behavior and are not a guarantee against every unintended action.

## Files and terminal

The **Files** tab browses Home. Click folders to open them and files to download them; downloads are limited to 20 MB per file. Take control before using **Terminal**. Terminal commands run with administrator privileges inside this computer, so use care with system changes.

## Stop safely

Use the power button in the dashboard. The platform saves the system snapshot before stopping; this can take a little time. A normal restart preserves files, browser profiles, installed applications and system settings. Applications reopen as new processes; unsaved document edits and running processes are not restored. Save your work first.

## If something is unavailable

- **Desktop service unavailable:** the worker is offline. For local setup, run `sh scripts/dev.sh` after Docker/OpenSandbox is running.
- **Connection lost:** use Reconnect and verify the API, worker and OpenSandbox are running.
- **Agent will not start:** add a valid provider key, start the desktop, return control to the agent and check available credits.
- **Stop reports an error:** the platform may be retaining the desktop because it could not save the system snapshot. Do not delete it to resolve this; check worker logs.

For installation and service commands, see the repository README.
