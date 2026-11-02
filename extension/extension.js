import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const CACHE_DIR = GLib.build_filenamev([GLib.get_user_cache_dir(), 'todo-reminder']);
const CACHE_FILE = GLib.build_filenamev([CACHE_DIR, 'tasks.json']);
const SCRIPT = GLib.build_filenamev([GLib.get_home_dir(), 'Programs', 'todo-reminder', 'todo.py']);
const MAX_ITEMS = 15;
const TICKER_ITEMS = 5;
const TICKER_SECONDS = 30;

const COLORS = {overdue: '#e01b24', today: '#ff7800', soon: '#e5a50a', later: '#62a0ea', none: '#9a9996'};
const RANK = {overdue: 0, today: 1, soon: 2, later: 3, none: 4};

function isoDay(offset = 0) {
    const d = new Date();
    d.setDate(d.getDate() + offset);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function statusOf(due) {
    if (!due)
        return 'none';
    const today = isoDay();
    if (due < today)
        return 'overdue';
    if (due === today)
        return 'today';
    return due <= isoDay(2) ? 'soon' : 'later';
}

const WEEKDAYS = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
const MONTHS = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August',
    'September', 'Oktober', 'November', 'Dezember'];

// Immer gleiches Format: "Fr 06.11."
function dueText(t) {
    if (!t.due)
        return '';
    const [y, m, d] = t.due.split('-').map(Number);
    const pad = n => String(n).padStart(2, '0');
    return `${WEEKDAYS[new Date(y, m - 1, d).getDay()]} ${pad(d)}.${pad(m)}.`;
}

function tickerMarkup(t) {
    const when = {overdue: 'überfällig', today: 'heute'}[t.status] ??
        (t.due === isoDay(1) ? 'morgen' : dueText(t));
    return `${GLib.markup_escape_text(t.title, -1)}  <span foreground="${COLORS[t.status]}" ` +
        `weight="bold">· ${when}</span>`;
}

// Überschrift, unter der eine Aufgabe im Menü steht
function sectionOf(t) {
    if (t.status === 'overdue')
        return 'Überfällig';
    if (t.status === 'today')
        return 'Heute';
    if (!t.due)
        return 'Ohne Datum';
    if (t.due === isoDay(1))
        return 'Morgen';
    if (t.due <= isoDay(7))
        return 'Nächste 7 Tage';
    const [y, m] = t.due.split('-').map(Number);
    return MONTHS[m - 1] + (y !== new Date().getFullYear() ? ` ${y}` : '');
}

// Spalte mit fester Breite, damit Sterne und Daten untereinander stehen
function column(child, width) {
    return new St.Bin({child, style: `width: ${width};`, y_align: Clutter.ActorAlign.CENTER});
}

function run(args) {
    try {
        // Über einen Launch-Context starten, damit GNOME das Fenster nach vorne holen darf
        const info = Gio.AppInfo.create_from_commandline(
            ['/usr/bin/python3', SCRIPT, ...args].map(a => GLib.shell_quote(a)).join(' '),
            'To Do', Gio.AppInfoCreateFlags.SUPPORTS_STARTUP_NOTIFICATION);
        info.launch([], global.create_app_launch_context(0, -1));
    } catch (e) {
        logError(e, 'todo-counter');
    }
}

const TodoIndicator = GObject.registerClass(
class TodoIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.5, 'To Do');
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        box.add_child(new St.Icon({icon_name: 'checkbox-checked-symbolic', style_class: 'system-status-icon'}));
        this._label = new St.Label({text: '…', y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._label);
        this._ticker = new St.Label({
            y_align: Clutter.ActorAlign.CENTER, visible: false,
            style: 'max-width: 24em; margin-left: 10px; padding-left: 10px; ' +
                   'border-left: 1px solid rgba(255,255,255,0.25);',
        });
        box.add_child(this._ticker);
        this.add_child(box);
        this._upcoming = [];
        this._tickerIndex = 0;
        this._tickerTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, TICKER_SECONDS, () => {
            this._nextTicker();
            return GLib.SOURCE_CONTINUE;
        });

        GLib.mkdir_with_parents(CACHE_DIR, 0o700);
        this._monitor = Gio.File.new_for_path(CACHE_DIR)
            .monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, null);
        this._monitor.connect('changed', (_m, file, other) => {
            if ([file, other].some(f => f?.get_basename() === 'tasks.json'))
                this._reload();
        });
        // Alle 5 Minuten neu einfärben (z.B. wenn um Mitternacht "morgen" zu "heute" wird)
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 300, () => {
            this._reload();
            return GLib.SOURCE_CONTINUE;
        });
        this._reload();
    }

    _reload() {
        let tasks;
        try {
            const [, bytes] = GLib.file_get_contents(CACHE_FILE);
            tasks = JSON.parse(new TextDecoder().decode(bytes)).tasks;
        } catch {
            this._label.text = ' ?';
            this._buildMenu(null);
            return;
        }
        tasks = tasks.map(t => ({...t, status: statusOf(t.due)}));
        tasks.sort((a, b) => RANK[a.status] - RANK[b.status] ||
            (a.due ?? '').localeCompare(b.due ?? '') ||
            (b.importance === 'high') - (a.importance === 'high') ||
            a.title.localeCompare(b.title));

        const overdue = tasks.filter(t => t.status === 'overdue').length;
        const today = tasks.filter(t => t.status === 'today').length;
        this._label.text = ` ${tasks.length}`;
        const color = overdue ? COLORS.overdue : today ? COLORS.today : null;
        this._label.set_style(color ? `color: ${color}; font-weight: bold;` : null);
        this._upcoming = tasks.filter(t => t.due && t.due <= isoDay(7)).slice(0, TICKER_ITEMS);
        this._tickerIndex = 0;
        this._showTicker();
        this._buildMenu(tasks);
    }

    _showTicker() {
        const t = this._upcoming[this._tickerIndex % Math.max(this._upcoming.length, 1)];
        this._ticker.visible = !!t;
        if (t)
            this._ticker.clutter_text.set_markup(tickerMarkup(t));
    }

    _nextTicker() {
        if (this._upcoming.length < 2)
            return;
        this._ticker.ease({
            opacity: 0, duration: 300, mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => {
                this._tickerIndex++;
                this._showTicker();
                this._ticker.ease({opacity: 255, duration: 300, mode: Clutter.AnimationMode.EASE_IN_QUAD});
            },
        });
    }

    _buildMenu(tasks) {
        this.menu.removeAll();
        if (!tasks) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem('Noch keine Daten – bitte anmelden', {reactive: false}));
        } else if (!tasks.length) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem('Alles erledigt 🎉', {reactive: false}));
        }
        let section = null;
        for (const t of (tasks ?? []).slice(0, MAX_ITEMS)) {
            if (sectionOf(t) !== section) {
                section = sectionOf(t);
                this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem(section));
            }
            const item = new PopupMenu.PopupBaseMenuItem();
            const color = COLORS[t.status];
            item.add_child(new St.Label({text: '●', style: `color: ${color};`, y_align: Clutter.ActorAlign.CENTER}));
            item.add_child(column(t.importance === 'high'
                ? new St.Label({text: '★', style: 'color: #f6d32d;'})
                : new St.Widget(), '1.4em'));
            item.add_child(new St.Label({
                text: t.title + (t.recurrence ? '  🔁' : ''),
                style: 'max-width: 22em;', x_expand: true, y_align: Clutter.ActorAlign.CENTER,
            }));
            item.add_child(column(new St.Label({
                text: dueText(t), x_align: Clutter.ActorAlign.END, x_expand: true,
                style: `color: ${color}; font-weight: bold; font-feature-settings: "tnum";`,
            }), '5.5em'));
            item.connect('activate', () => run(['app']));
            this.menu.addMenuItem(item);
        }
        if (tasks && tasks.length > MAX_ITEMS) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                `… und ${tasks.length - MAX_ITEMS} weitere`, {reactive: false}));
        }
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addAction('Neue Aufgabe…', () => run(['app', '--new']), 'list-add-symbolic');
        this.menu.addAction('Alle Aufgaben öffnen', () => run(['app']), 'view-list-symbolic');
        this.menu.addAction('Jetzt synchronisieren', () => run(['sync']), 'view-refresh-symbolic');
    }

    destroy() {
        for (const id of [this._timer, this._tickerTimer]) {
            if (id)
                GLib.source_remove(id);
        }
        this._timer = this._tickerTimer = 0;
        this._monitor?.cancel();
        super.destroy();
    }
});

export default class TodoCounterExtension extends Extension {
    enable() {
        this._indicator = new TodoIndicator();
        // Links in der Leiste, nach dem Digest – das Laufband ändert seine Breite, daher ganz außen
        Main.panel.addToStatusArea(this.uuid, this._indicator, 2, 'left');
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
