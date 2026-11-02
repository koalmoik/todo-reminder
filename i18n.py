"""Minimal translation layer: English source strings with German translations.

The UI language is taken from "language" ("en" or "de") in
~/.config/todo-reminder/config.json, otherwise from the system locale
(LANGUAGE, LC_ALL, LC_MESSAGES, LANG). Anything that is not German falls back to English.
"""
import json
import os
from datetime import date
from pathlib import Path

CONFIG_FILE = Path.home() / ".config/todo-reminder/config.json"
SUPPORTED = ("en", "de")


def detect_language():
    try:
        lang = json.loads(CONFIG_FILE.read_text()).get("language")
    except (OSError, ValueError, AttributeError):
        lang = None
    if lang in SUPPORTED:
        return lang
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "de" if value.split(":")[0].lower().startswith("de") else "en"
    return "en"


LANG = detect_language()

DE = {
    # todo.py
    "Keyring not available: {error}": "Schlüsselbund nicht erreichbar: {error}",
    "No client ID – please run 'todo.py login <client-id>'.":
        "Keine Client-ID – bitte 'todo.py login <client-id>' ausführen.",
    "Not signed in – please run 'todo.py login <client-id>'.":
        "Nicht angemeldet – bitte 'todo.py login <client-id>' ausführen.",
    "Sign-in expired – please sign in again ({error}).":
        "Anmeldung abgelaufen – bitte neu anmelden ({error}).",
    "Error: {error}": "Fehler: {error}",
    "Signed in.": "Angemeldet.",
    "Sign-in failed: {error}": "Anmeldung fehlgeschlagen: {error}",
    "Connection to Microsoft failed: {error}": "Verbindung zu Microsoft fehlgeschlagen: {error}",
    "Today": "Heute",
    "Tomorrow": "Morgen",
    "Overdue": "Überfällig",
    "Never": "Nie",
    "Daily": "Täglich",
    "Weekdays (Mon–Fri)": "Wochentags (Mo–Fr)",
    "Weekly": "Wöchentlich",
    "Monthly": "Monatlich",
    "Yearly": "Jährlich",
    "day": "Tag", "days": "Tage",
    "week": "Woche", "weeks": "Wochen",
    "month": "Monat", "months": "Monate",
    "year": "Jahr", "years": "Jahre",
    "Mon–Fri": "Mo–Fr",
    "daily": "täglich",
    "weekly": "wöchentlich",
    "monthly": "monatlich",
    "yearly": "jährlich",
    "every {n} {unit}": "alle {n} {unit}",
    # gui.py
    "No internet connection": "Keine Internetverbindung",
    "Cancel": "Abbrechen",
    "New task": "Neue Aufgabe",
    "Rename list…": "Liste umbenennen…",
    "Delete list…": "Liste löschen…",
    "List": "Liste",
    "Sync": "Synchronisieren",
    "New list": "Neue Liste",
    "All done 🎉": "Alles erledigt 🎉",
    "All open": "Alle offenen",
    "Done": "Erledigt",
    "“{title}” done ✓": "„{title}“ erledigt ✓",
    "Create": "Anlegen",
    "List “{name}” created": "Liste „{name}“ angelegt",
    "Rename list": "Liste umbenennen",
    "Rename": "Umbenennen",
    "Renamed ✓": "Umbenannt ✓",
    "Delete “{name}”?": "„{name}“ löschen?",
    "The list and its {count} open tasks will be deleted everywhere, including on your phone.":
        "Die Liste und ihre {count} offenen Aufgaben werden überall gelöscht, auch auf dem Handy.",
    "Delete": "Löschen",
    "List “{name}” deleted": "Liste „{name}“ gelöscht",
    "No lists loaded yet – sync first.": "Noch keine Listen geladen – erst synchronisieren.",
    "Next week": "Nächste Woche",
    "No date": "Kein Datum",
    "Edit task": "Aufgabe bearbeiten",
    "Save": "Speichern",
    "Title": "Titel",
    "Due": "Fällig",
    "Reminder 🔔": "Erinnerung 🔔",
    "Day": "Tag",
    "Time": "Uhrzeit",
    "Repeat 🔁": "Wiederholen 🔁",
    "Every": "Alle",
    "On": "An",
    "Important ⭐": "Wichtig ⭐",
    "Notes": "Notizen",
    "Delete task": "Aufgabe löschen",
    "Please enter a title.": "Bitte einen Titel eingeben.",
    "Saved ✓": "Gespeichert ✓",
    "“{title}” deleted": "„{title}“ gelöscht",
}


def _(text):
    """Translate an English UI string into the current language."""
    return DE.get(text, text) if LANG == "de" else text


WEEKDAYS = {"en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]}[LANG]
MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_day(d: date, year=True):
    """'Fri 31 Oct 2026' or 'Fr 31.10.2026' (without year: 'Fri 31 Oct' / 'Fr 31.10.')."""
    if LANG == "de":
        return f"{WEEKDAYS[d.weekday()]} {d:%d.%m.}" + (f"{d:%Y}" if year else "")
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS_SHORT[d.month - 1]}" + (f" {d:%Y}" if year else "")
