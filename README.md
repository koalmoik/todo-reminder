# todo-reminder

Microsoft To Do on the GNOME desktop:

- **Top-bar extension** showing the number of open tasks, a ticker with upcoming tasks and a
  menu grouped by due date (overdue, today, tomorrow, next 7 days, …).
- **GTK 4 / libadwaita window** to view, create, edit, complete and delete tasks and lists,
  including due dates, reminders, recurrence, importance and notes.
- **Reminders** as desktop notifications, checked every 2 minutes by a systemd user timer.
- **Offline-friendly:** shows "No internet connection" and reloads automatically once the
  network is back.

Tasks are synced through the Microsoft Graph API, so changes show up on your phone as well.

## Requirements

- GNOME Shell 50 (the extension's `metadata.json` lists the supported versions)
- `/usr/bin/python3` with `requests` and PyGObject (GTK 4, libadwaita, libsecret)
- A Microsoft account and your own app registration (see below)

## Setup

1. Clone the repo to `~/Programs/todo-reminder` (the extension expects `todo.py` there).
2. Register an app in the [Microsoft Entra admin center](https://entra.microsoft.com):
   supported account types incl. personal Microsoft accounts, **Allow public client flows** on,
   delegated permission `Tasks.ReadWrite`. Copy its *Application (client) ID*.
3. Sign in once (device code flow; the token is stored in the GNOME keyring):

   ```bash
   /usr/bin/python3 todo.py login <client-id>
   ```

4. Install the timer, autostart entry, app launcher and extension:

   ```bash
   ./install.sh
   ```

## Usage

```
todo.py login <client-id>      sign in to Microsoft once
todo.py sync                   fetch tasks, send reminders (used by the systemd timer)
todo.py list                   show open tasks in the terminal
todo.py app [--startup|--new]  open the window
```

## Language

The UI is available in English and German. By default it follows the system locale.
To override it, set `language` in `~/.config/todo-reminder/config.json`:

```json
{"client_id": "…", "language": "de"}
```

Restart the app (and log out and back in for the extension) after changing it.

## Files

| Path | Contents |
| --- | --- |
| `~/.config/todo-reminder/config.json` | client ID, optional language |
| GNOME keyring | access/refresh token |
| `~/.cache/todo-reminder/tasks.json` | cached tasks, read by the extension |
| `~/.cache/todo-reminder/notified.json` | reminders already shown |
