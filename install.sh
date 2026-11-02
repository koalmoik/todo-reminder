#!/bin/bash
# Richtet Timer, Autostart, App-Starter und GNOME-Erweiterung ein.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
EXT=todo-counter@peter
PY=/usr/bin/python3

mkdir -p ~/.config/systemd/user ~/.config/autostart ~/.local/share/applications \
         ~/.local/share/gnome-shell/extensions

# Sync + Erinnerungen alle 2 Minuten
cat > ~/.config/systemd/user/todo-reminder.service <<EOF
[Unit]
Description=Microsoft To Do synchronisieren und Erinnerungen senden

[Service]
Type=oneshot
ExecStart=$PY $DIR/todo.py sync
EOF

cat > ~/.config/systemd/user/todo-reminder.timer <<EOF
[Unit]
Description=Microsoft To Do alle 2 Minuten synchronisieren

[Timer]
OnActiveSec=20s
OnUnitActiveSec=2min

[Install]
WantedBy=timers.target
EOF

# Fenster beim Anmelden
cat > ~/.config/autostart/todo-reminder.desktop <<EOF
[Desktop Entry]
Type=Application
Name=To Do beim Anmelden
Exec=$PY $DIR/todo.py app --startup
X-GNOME-Autostart-Delay=5
EOF

# Starter im App-Menü
cat > ~/.local/share/applications/io.github.peter.TodoReminder.desktop <<EOF
[Desktop Entry]
Type=Application
Name=To Do
Comment=Microsoft-To-Do-Aufgaben
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
  || echo "Erweiterung: einmal ab- und wieder anmelden, dann: gnome-extensions enable $EXT"
echo "Fertig."
