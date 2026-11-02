#!/bin/bash
# Sets up the timer, autostart, app launcher and GNOME extension.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
EXT=todo-counter@peter
PY=/usr/bin/python3

mkdir -p ~/.config/systemd/user ~/.config/autostart ~/.local/share/applications \
         ~/.local/share/gnome-shell/extensions

# Sync + reminders every 2 minutes
cat > ~/.config/systemd/user/todo-reminder.service <<EOF
[Unit]
Description=Sync Microsoft To Do and send reminders

[Service]
Type=oneshot
ExecStart=$PY $DIR/todo.py sync
EOF

cat > ~/.config/systemd/user/todo-reminder.timer <<EOF
[Unit]
Description=Sync Microsoft To Do every 2 minutes

[Timer]
OnActiveSec=20s
OnUnitActiveSec=2min

[Install]
WantedBy=timers.target
EOF

# Window at login
cat > ~/.config/autostart/todo-reminder.desktop <<EOF
[Desktop Entry]
Type=Application
Name=To Do at login
Name[de]=To Do beim Anmelden
Exec=$PY $DIR/todo.py app --startup
X-GNOME-Autostart-Delay=5
EOF

# Launcher in the app menu
cat > ~/.local/share/applications/io.github.peter.TodoReminder.desktop <<EOF
[Desktop Entry]
Type=Application
Name=To Do
Comment=Microsoft To Do tasks
Comment[de]=Microsoft-To-Do-Aufgaben
Exec=$PY $DIR/todo.py app
Icon=io.github.peter.TodoReminder
Categories=Office;
EOF

mkdir -p ~/.local/share/icons/hicolor/scalable/apps
cp "$DIR/icon.svg" ~/.local/share/icons/hicolor/scalable/apps/io.github.peter.TodoReminder.svg
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor >/dev/null 2>&1 || true

ln -sfn "$DIR/extension" ~/.local/share/gnome-shell/extensions/$EXT

systemctl --user daemon-reload
systemctl --user enable --now todo-reminder.timer
gnome-extensions enable $EXT 2>/dev/null \
  || echo "Extension: log out and back in once, then run: gnome-extensions enable $EXT"
echo "Done."
