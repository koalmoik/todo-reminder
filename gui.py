"""GTK 4/libadwaita window for viewing and editing Microsoft To Do tasks."""
import colorsys
import math
import threading
from datetime import date, datetime, timedelta

import cairo
import gi
import requests

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

import todo  # noqa: E402
from i18n import WEEKDAYS, _  # noqa: E402

APP_ID = "io.github.peter.TodoReminder"
ALL = "__all__"
OFFLINE = _("No internet connection")
RANK = {"overdue": 0, "today": 1, "soon": 2, "later": 3, "none": 4}

CSS = "".join(
    [".task-bar { min-width: 5px; border-radius: 3px; margin: 8px 0; }",
     ".dot { min-width: 10px; min-height: 10px; border-radius: 5px; }",
     ".swatch { min-width: 26px; min-height: 26px; padding: 0; border-radius: 13px; }",
     ".swatch:hover { filter: brightness(1.15); }",
     ".star { color: #f6d32d; font-size: 1.2em; }"]
    + [f".st-{k} {{ background: {v}; }}" for k, v in todo.STATUS_COLORS.items()]
    + [".swatch-preview { min-width: 34px; min-height: 34px; border-radius: 17px; }"])

_color_css = Gtk.CssProvider()
_color_classes = {}


def color_class(value):
    """CSS class with the given list color as background (created on first use)."""
    hexval = todo.color_hex(value)
    cls = "lc-" + hexval[1:]
    if cls not in _color_classes:
        _color_classes[cls] = hexval
        _color_css.load_from_string("".join(f".{c} {{ background: {h}; }}"
                                            for c, h in _color_classes.items()))
    return cls


def esc(text):
    return GLib.markup_escape_text(text or "")


def dot(css):
    return Gtk.Box(css_classes=["dot", css], valign=Gtk.Align.CENTER)


def hex_to_rgb(hexval):
    return tuple(int(hexval[i:i + 2], 16) / 255 for i in (1, 3, 5))


def rgb_to_hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(*(round(x * 255) for x in (r, g, b)))


def rounded_rect(cr, w, h, r):
    cr.new_sub_path()
    cr.arc(w - r, r, r, -math.pi / 2, 0)
    cr.arc(w - r, h - r, r, 0, math.pi / 2)
    cr.arc(r, h - r, r, math.pi / 2, math.pi)
    cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class ColorMixer(Gtk.Box):
    """Saturation/value plane plus a hue strip; calls on_change('#rrggbb') while dragging."""

    def __init__(self, hexval, on_change):
        super().__init__(spacing=10)
        self.on_change = on_change
        self.h = self.s = self.v = 0.0
        self.set_hex(hexval)
        self.plane = Gtk.DrawingArea(hexpand=True, content_height=130, cursor=Gdk.Cursor.new_from_name("crosshair"))
        self.plane.set_draw_func(self.draw_plane)
        self.strip = Gtk.DrawingArea(content_width=18, content_height=130)
        self.strip.set_draw_func(self.draw_strip)
        self.append(self.plane)
        self.append(self.strip)
        for area, handler in ((self.plane, self.pick_plane), (self.strip, self.pick_strip)):
            drag = Gtk.GestureDrag(propagation_phase=Gtk.PropagationPhase.CAPTURE)
            drag.connect("drag-begin", lambda g, x, y, a=area, f=handler: self._start(g, a, f, x, y))
            drag.connect("drag-update", lambda g, dx, dy, a=area, f=handler: self._move(g, a, f, dx, dy))
            area.add_controller(drag)

    def set_hex(self, hexval):
        h, s, v = colorsys.rgb_to_hsv(*hex_to_rgb(hexval))
        if s > 0 and v > 0:  # grey/black carries no hue: keep the current one
            self.h = h
        if v > 0:
            self.s = s
        self.v = v
        if hasattr(self, "plane"):
            self.plane.queue_draw()
            self.strip.queue_draw()

    def hex(self):
        return rgb_to_hex(*colorsys.hsv_to_rgb(self.h, self.s, self.v))

    def _start(self, gesture, area, handler, x, y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)  # don't let the window move instead
        gesture.origin = (x, y)
        handler(area, x, y)

    def _move(self, gesture, area, handler, dx, dy):
        handler(area, gesture.origin[0] + dx, gesture.origin[1] + dy)

    def pick_plane(self, area, x, y):
        self.s = min(max(x / max(area.get_width(), 1), 0), 1)
        self.v = 1 - min(max(y / max(area.get_height(), 1), 0), 1)
        self.plane.queue_draw()
        self.on_change(self.hex())

    def pick_strip(self, area, x, y):
        self.h = min(max(y / max(area.get_height(), 1), 0), 0.9999)
        self.plane.queue_draw()
        self.strip.queue_draw()
        self.on_change(self.hex())

    def draw_plane(self, _area, cr, w, h):
        rounded_rect(cr, w, h, 8)
        cr.clip()
        cr.set_source_rgb(*colorsys.hsv_to_rgb(self.h, 1, 1))
        cr.paint()
        white = cairo.LinearGradient(0, 0, w, 0)
        white.add_color_stop_rgba(0, 1, 1, 1, 1)
        white.add_color_stop_rgba(1, 1, 1, 1, 0)
        cr.set_source(white)
        cr.paint()
        black = cairo.LinearGradient(0, 0, 0, h)
        black.add_color_stop_rgba(0, 0, 0, 0, 0)
        black.add_color_stop_rgba(1, 0, 0, 0, 1)
        cr.set_source(black)
        cr.paint()
        cr.reset_clip()
        self._marker(cr, min(max(self.s * w, 7), w - 7), min(max((1 - self.v) * h, 7), h - 7))

    def draw_strip(self, _area, cr, w, h):
        rounded_rect(cr, w, h, w / 2)
        grad = cairo.LinearGradient(0, 0, 0, h)
        for i in range(7):
            grad.add_color_stop_rgb(i / 6, *colorsys.hsv_to_rgb(i / 6 % 1, 1, 1))
        cr.set_source(grad)
        cr.fill()
        self._marker(cr, w / 2, min(max(self.h * h, w / 2), h - w / 2))

    @staticmethod
    def _marker(cr, x, y):
        cr.arc(x, y, 7, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.set_line_width(4)
        cr.stroke_preserve()
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(2)
        cr.stroke()


def ask_name(parent, heading, initial, confirm, callback):
    """Small dialog with a text field; calls callback(name) on confirm."""
    entry = Gtk.Entry(text=initial, activates_default=True)
    dialog = Adw.AlertDialog(heading=heading, extra_child=entry,
                             default_response="ok", close_response="cancel")
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("ok", confirm)
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

    def done(_d, response):
        name = entry.get_text().strip()
        if response == "ok" and name:
            callback(name)

    dialog.connect("response", done)
    dialog.present(parent)
    entry.grab_focus()


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="To Do", default_width=860, default_height=620)
        self.data = todo.load_json(todo.CACHE_FILE, {"lists": [], "tasks": []})
        self.current = ALL
        self._rendering = False

        for name, handler in (("rename-list", self.on_rename_list), ("color-list", self.on_color_list),
                              ("delete-list", self.on_delete_list)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        header = Adw.HeaderBar()
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("New task"))
        add.connect("clicked", lambda *_: self.edit(None))
        header.pack_start(add)
        menu = Gio.Menu()
        menu.append(_("Rename list…"), "win.rename-list")
        menu.append(_("Change color…"), "win.color-list")
        menu.append(_("Delete list…"), "win.delete-list")
        header.pack_end(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu,
                                       tooltip_text=_("List")))
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Sync"))
        refresh.connect("clicked", lambda *_: self.sync())
        header.pack_end(refresh)
        self.spinner = Adw.Spinner(visible=False)
        header.pack_end(self.spinner)

        self.sidebar = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.sidebar.connect("row-selected", self.on_list_selected)
        new_list = Gtk.Button(css_classes=["flat"], margin_start=6, margin_end=6, margin_bottom=6,
                              child=Adw.ButtonContent(icon_name="list-add-symbolic", label=_("New list")))
        new_list.connect("clicked", self.on_new_list)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=200)
        side.append(Gtk.ScrolledWindow(child=self.sidebar, vexpand=True))
        side.append(new_list)

        self.tasks = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE,
                                 valign=Gtk.Align.START)
        clamp = Adw.Clamp(child=self.tasks, maximum_size=760, margin_top=18, margin_bottom=18,
                          margin_start=12, margin_end=12)
        self.empty = Adw.StatusPage(icon_name="checkbox-checked-symbolic", title=_("All done 🎉"))
        self.stack = Gtk.Stack()
        self.stack.add_named(Gtk.ScrolledWindow(child=clamp, vexpand=True), "tasks")
        self.stack.add_named(self.empty, "empty")

        paned = Gtk.Paned(start_child=side, end_child=self.stack, position=230,
                          shrink_start_child=False, resize_start_child=False)
        self.toasts = Adw.ToastOverlay(child=paned)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        self.set_content(view)

        self._offline = False   # last fetch failed for lack of a connection
        self._retry_id = 0
        Gio.NetworkMonitor.get_default().connect("network-changed", self.on_network_changed)

        self.render()
        self.sync()

    def toast(self, text, timeout=3):
        self.toasts.add_toast(Adw.Toast(title=esc(text), timeout=timeout))

    # ---------- Background work ----------

    def run_bg(self, fn, done=None):
        self.spinner.set_visible(True)

        def work():
            try:
                res, err = fn(), None
            except todo.AuthError as e:
                res, err = None, str(e)
            except requests.ConnectionError:  # no network, DNS failing, server unreachable
                res, err = None, OFFLINE
            except Exception as e:  # show network/API errors as a toast
                res, err = None, _("Error: {error}").format(error=e)
            GLib.idle_add(self._bg_done, res, err, done)

        threading.Thread(target=work, daemon=True).start()

    def _bg_done(self, res, err, done):
        self.spinner.set_visible(False)
        if err == OFFLINE:
            if not self._offline:   # show the message once, not on every retry
                self.toast(err, 8)
            self._offline = True
            self.schedule_retry(30)
        elif err:
            self.toast(err, 8)
        else:
            self._offline = False
            if done:
                done(res)
        return False

    # ---------- Reload automatically once the network is back ----------

    def on_network_changed(self, monitor, available):
        if available and self._offline:
            self.schedule_retry(3)   # give DNS a moment to come up

    def schedule_retry(self, seconds):
        if self._retry_id:
            GLib.source_remove(self._retry_id)

        def retry():
            self._retry_id = 0
            if self._offline:
                self.sync()
            return False

        self._retry_id = GLib.timeout_add_seconds(seconds, retry)

    def sync(self):
        self.run_bg(todo.fetch, self.set_data)

    def change(self, action, message=None):
        """Run an API change, then reload."""
        def fn():
            action()
            return todo.fetch()

        def done(data):
            self.set_data(data)
            if message:
                self.toast(message)

        self.run_bg(fn, done)

    def set_data(self, data):
        self.data = data
        if self.current != ALL and not self.current_list():
            self.current = ALL
        self.render()

    def current_list(self):
        return next((l for l in self.data["lists"] if l["id"] == self.current), None)

    # ---------- Rendering ----------

    def visible_tasks(self):
        tasks = [t for t in self.data["tasks"] if self.current in (ALL, t["list_id"])]
        return sorted(tasks, key=lambda t: (RANK[todo.due_status(t["due"])], t["due"] or "",
                                            t["importance"] != "high", t["title"].lower()))

    def render(self):
        self._rendering = True
        self.sidebar.remove_all()
        counts = {}
        for t in self.data["tasks"]:
            counts[t["list_id"]] = counts.get(t["list_id"], 0) + 1
        entries = [(ALL, _("All open"), "st-today", len(self.data["tasks"]))]
        entries += [(l["id"], l["name"] + (" 👥" if l.get("shared") else ""),
                     color_class(l["color"]), counts.get(l["id"], 0)) for l in self.data["lists"]]
        for list_id, name, css, count in entries:
            box = Gtk.Box(spacing=10, margin_top=4, margin_bottom=4)
            box.append(dot(css))
            box.append(Gtk.Label(label=name, xalign=0, hexpand=True, ellipsize=3))
            box.append(Gtk.Label(label=str(count) if count else "", css_classes=["dim-label"]))
            row = Gtk.ListBoxRow(child=box)
            row.list_id = list_id
            self.sidebar.append(row)
            if list_id == self.current:
                self.sidebar.select_row(row)
        self._rendering = False

        lst = self.current_list()
        editable = bool(lst and not lst.get("default"))
        self.lookup_action("rename-list").set_enabled(editable)
        self.lookup_action("delete-list").set_enabled(editable)
        self.lookup_action("color-list").set_enabled(lst is not None)

        self.tasks.remove_all()
        tasks = self.visible_tasks()
        for t in tasks:
            self.tasks.append(self.task_row(t))
        self.stack.set_visible_child_name("tasks" if tasks else "empty")

    def task_row(self, t):
        status = todo.due_status(t["due"])
        parts = []
        if t["due"]:
            parts.append(f'<span foreground="{todo.STATUS_COLORS[status]}" weight="bold">'
                         f'{esc(todo.due_label(t["due"]))}</span>')
        if t["reminder"]:
            rem = datetime.fromisoformat(t["reminder"])
            parts.append(f"🔔 {todo.date_label(rem.date())} {rem:%H:%M}")
        if t.get("recurrence"):
            parts.append(f"🔁 {todo.recurrence_label(t['recurrence'])}")
        if self.current == ALL:
            parts.append(esc(t["list"]))
        row = Adw.ActionRow(title=esc(t["title"]), subtitle=" · ".join(parts), activatable=True)

        check = Gtk.CheckButton(valign=Gtk.Align.CENTER, tooltip_text=_("Done"))
        check.connect("toggled", self.on_done, t)
        row.add_prefix(Gtk.Box(css_classes=["task-bar", f"st-{status}"]))
        row.add_prefix(check)
        if t["importance"] == "high":
            row.add_suffix(Gtk.Label(label="★", css_classes=["star"]))
        if self.current == ALL:
            color = next((l["color"] for l in self.data["lists"] if l["id"] == t["list_id"]), 0)
            row.add_suffix(dot(color_class(color)))
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic", css_classes=["dim-label"]))
        row.connect("activated", lambda *_: self.edit(t))
        return row

    def on_list_selected(self, _box, row):
        if row and not self._rendering:
            self.current = row.list_id
            self.render()

    def on_done(self, check, t):
        if not check.get_active():
            return
        self.data["tasks"] = [x for x in self.data["tasks"] if x["id"] != t["id"]]
        self.render()
        self.change(lambda: todo.complete_task(t["list_id"], t["id"]), _("“{title}” done ✓").format(title=t["title"]))

    # ---------- Lists ----------

    def on_new_list(self, *_args):
        ask_name(self, _("New list"), "", _("Create"),
                 lambda name: self.change(lambda: todo.create_list(name),
                                          _("List “{name}” created").format(name=name)))

    def on_rename_list(self, *_args):
        lst = self.current_list()
        ask_name(self, _("Rename list"), lst["name"], _("Rename"),
                 lambda name: self.change(lambda: todo.rename_list(lst["id"], name), _("Renamed ✓")))

    def on_color_list(self, *_args):
        lst = self.current_list()
        current = todo.color_hex(lst["color"])
        dialog = Adw.AlertDialog(heading=_("Color for “{name}”").format(name=lst["name"]),
                                 body=_("Pick a preset or mix your own color."),
                                 default_response="ok", close_response="cancel")
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("ok", _("Apply"))
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        presets = Gtk.Grid(halign=Gtk.Align.CENTER, column_spacing=8)
        preview = Gtk.Box(css_classes=["swatch-preview", color_class(current)],
                          valign=Gtk.Align.CENTER)
        entry = Gtk.Entry(text=current, max_length=7, width_chars=9, activates_default=True,
                          valign=Gtk.Align.CENTER, tooltip_text=_("Hex code, e.g. #3584e4"))
        state = {"color": current, "syncing": False}

        def show(hexval, source=None):
            state["color"] = hexval
            dialog.set_response_enabled("ok", hexval is not None)
            if hexval is None:
                entry.add_css_class("error")
                return
            entry.remove_css_class("error")
            for c in list(preview.get_css_classes()):
                if c.startswith("lc-"):
                    preview.remove_css_class(c)
            preview.add_css_class(color_class(hexval))
            state["syncing"] = True
            if source is not entry and entry.get_text().lower() != hexval:
                entry.set_text(hexval)
            if source is not mixer:
                mixer.set_hex(hexval)
            state["syncing"] = False

        mixer = ColorMixer(current, lambda h: show(h, mixer))
        mixer.set_margin_top(12)
        entry.connect("changed", lambda e: state["syncing"] or show(todo.normalize_hex(e.get_text()), entry))

        for i, hexval in enumerate(todo.LIST_COLORS):
            btn = Gtk.Button(css_classes=["swatch", color_class(hexval)], tooltip_text=hexval,
                             valign=Gtk.Align.CENTER)
            btn.connect("clicked", lambda _b, h=hexval: show(h))
            presets.attach(btn, i, 0, 1, 1)

        custom = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER, margin_top=12)
        custom.append(preview)
        custom.append(entry)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(presets)
        box.append(mixer)
        box.append(custom)
        dialog.set_extra_child(box)
        dialog.connect("response", lambda _d, r: r == "ok" and state["color"]
                       and self.set_list_color(lst, state["color"]))
        dialog.present(self)

    def set_list_color(self, lst, color):
        todo.set_list_color(lst["id"], color)
        for l in self.data["lists"]:
            if l["id"] == lst["id"]:
                l["color"] = todo.color_hex(color)
        self.render()

    def on_delete_list(self, *_args):
        lst = self.current_list()
        count = sum(t["list_id"] == lst["id"] for t in self.data["tasks"])
        dialog = Adw.AlertDialog(
            heading=_("Delete “{name}”?").format(name=lst["name"]),
            body=_("The list and its {count} open tasks will be deleted everywhere, "
                   "including on your phone.").format(count=count),
            close_response="cancel")
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda _d, r: r == "delete" and self.change(
            lambda: todo.delete_list(lst["id"]), _("List “{name}” deleted").format(name=lst["name"])))
        dialog.present(self)

    # ---------- Editing ----------

    def edit(self, t):
        if not self.data["lists"]:
            self.toast(_("No lists loaded yet – sync first."))
            return
        EditDialog(self, t).present(self)


class DatePicker(Gtk.MenuButton):
    """Button showing a date; popover with quick picks and a calendar."""

    def __init__(self, value=None, allow_none=True):
        super().__init__(valign=Gtk.Align.CENTER, always_show_arrow=True)
        self.value = value
        self.allow_none = allow_none
        self._syncing = False

        quick = Gtk.Box(spacing=6, homogeneous=True)
        for label, days in ((_("Today"), 0), (_("Tomorrow"), 1), (_("Next week"), 7)):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", lambda _b, d=days: self.set_value(date.today() + timedelta(days=d)))
            quick.append(btn)
        self.cal = Gtk.Calendar()
        self.cal.connect("day-selected", self._picked)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(quick)
        box.append(self.cal)
        if allow_none:
            clear = Gtk.Button(label=_("No date"), css_classes=["flat"])
            clear.connect("clicked", lambda *_: self.set_value(None))
            box.append(clear)
        popover = Gtk.Popover(child=box)
        popover.connect("show", self._sync_calendar)
        self.set_popover(popover)
        self._update()

    def _sync_calendar(self, *_args):
        d = self.value or date.today()
        self._syncing = True
        self.cal.select_day(GLib.DateTime.new_local(d.year, d.month, d.day, 0, 0, 0))
        self._syncing = False

    def _picked(self, cal):
        if not self._syncing:
            d = cal.get_date()
            self.set_value(date(d.get_year(), d.get_month(), d.get_day_of_month()))

    def set_value(self, value):
        self.value = value
        self._update()
        self.get_popover().popdown()

    def _update(self):
        self.set_label(todo.date_label(self.value) if self.value else _("No date"))


def spin(upper, step):
    s = Gtk.SpinButton.new_with_range(0, upper, step)
    s.set_numeric(True)
    s.set_wrap(True)
    s.set_width_chars(2)
    s.set_valign(Gtk.Align.CENTER)
    s.set_orientation(Gtk.Orientation.VERTICAL)

    def two_digits(sb):
        sb.set_text(f"{int(sb.get_value()):02d}")
        return True

    s.connect("output", two_digits)
    return s


class EditDialog(Adw.Dialog):
    def __init__(self, win, t):
        super().__init__(title=_("Edit task") if t else _("New task"), content_width=480)
        self.win, self.t = win, t
        lists = win.data["lists"]

        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_: self.close())
        save = Gtk.Button(label=_("Save"), css_classes=["suggested-action"])
        save.connect("clicked", self.on_save)
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(save)

        self.title = Adw.EntryRow(title=_("Title"), text=t["title"] if t else "")
        self.title.connect("entry-activated", self.on_save)
        self.list_ids = [l["id"] for l in lists]
        self.list_row = Adw.ComboRow(title=_("List"), sensitive=t is None,
                                     model=Gtk.StringList.new([l["name"] for l in lists]))
        default = t["list_id"] if t else win.current
        if default in self.list_ids:
            self.list_row.set_selected(self.list_ids.index(default))

        # Due date
        self.due = DatePicker(date.fromisoformat(t["due"]) if t and t["due"] else None)
        due_row = Adw.ActionRow(title=_("Due"))
        due_row.add_suffix(self.due)

        # Reminder: switch + date + time
        rem = datetime.fromisoformat(t["reminder"]) if t and t["reminder"] else None
        self.rem = Adw.ExpanderRow(title=_("Reminder 🔔"), show_enable_switch=True,
                                   enable_expansion=rem is not None, expanded=rem is not None)
        self.rem.connect("notify::enable-expansion", self.on_reminder_toggled)
        self.rem_date = DatePicker(rem.date() if rem else None, allow_none=False)
        date_row = Adw.ActionRow(title=_("Day"))
        date_row.add_suffix(self.rem_date)
        self.hour, self.minute = spin(23, 1), spin(59, 5)
        if rem:
            self.hour.set_value(rem.hour)
            self.minute.set_value(rem.minute)
        time_box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        time_box.append(self.hour)
        time_box.append(Gtk.Label(label=":", css_classes=["title-3"]))
        time_box.append(self.minute)
        time_row = Adw.ActionRow(title=_("Time"))
        time_row.add_suffix(time_box)
        self.rem.add_row(date_row)
        self.rem.add_row(time_row)

        # Recurrence: kind, interval ("every 2 weeks"), weekdays
        rec = t.get("recurrence") if t else None
        self.repeat = Adw.ComboRow(title=_("Repeat 🔁"), model=Gtk.StringList.new(todo.REPEAT_LABELS))
        self.repeat.set_selected(todo.REPEAT_KINDS.index(rec["kind"]) if rec else 0)
        self.interval = Gtk.SpinButton.new_with_range(1, 99, 1)
        self.interval.set_numeric(True)
        self.interval.set_valign(Gtk.Align.CENTER)
        self.interval.set_value(rec["interval"] if rec else 1)
        self.unit = Gtk.Label(width_chars=7, xalign=0)
        interval_box = Gtk.Box(spacing=8)
        interval_box.append(self.interval)
        interval_box.append(self.unit)
        self.interval_row = Adw.ActionRow(title=_("Every"))
        self.interval_row.add_suffix(interval_box)
        self.day_buttons = [Gtk.ToggleButton(label=name, active=bool(rec and i in rec["days"]))
                            for i, name in enumerate(WEEKDAYS)]
        days_box = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        for btn in self.day_buttons:
            days_box.append(btn)
        self.days_row = Adw.ActionRow(title=_("On"))
        self.days_row.add_suffix(days_box)
        self.repeat.connect("notify::selected", self.on_repeat_changed)
        self.interval.connect("value-changed", self.on_repeat_changed)
        self._initial = (self.repeat_state(), self.due.value)
        self.on_repeat_changed()

        self.important = Adw.SwitchRow(title=_("Important ⭐"), active=bool(t and t["importance"] == "high"))

        group = Adw.PreferencesGroup()
        for row in (self.title, self.list_row, due_row, self.repeat, self.interval_row,
                    self.days_row, self.rem, self.important):
            group.add(row)

        self.notes = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                                  left_margin=8, right_margin=8, css_classes=["card"])
        self.notes.get_buffer().set_text(t["notes"] if t else "")
        notes_group = Adw.PreferencesGroup(title=_("Notes"))
        notes_group.add(Gtk.ScrolledWindow(child=self.notes, min_content_height=90))

        page = Adw.PreferencesPage()
        page.add(group)
        page.add(notes_group)
        if t:
            delete = Gtk.Button(label=_("Delete task"), css_classes=["destructive-action", "pill"],
                                halign=Gtk.Align.CENTER)
            delete.connect("clicked", self.on_delete)
            del_group = Adw.PreferencesGroup()
            del_group.add(delete)
            page.add(del_group)

        self.banner = Adw.Banner()
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(header)
        view.add_top_bar(self.banner)
        self.set_child(view)
        self.set_focus(self.title)

    def repeat_state(self):
        kind = todo.REPEAT_KINDS[self.repeat.get_selected()]
        days = tuple(i for i, b in enumerate(self.day_buttons) if b.get_active())
        return kind, self.interval.get_value_as_int(), days

    def on_repeat_changed(self, *_args):
        kind = todo.REPEAT_KINDS[self.repeat.get_selected()]
        self.interval_row.set_visible(kind in todo.REPEAT_UNITS)
        self.days_row.set_visible(kind == "weekly")
        if kind in todo.REPEAT_UNITS:
            one, many = todo.REPEAT_UNITS[kind]
            self.unit.set_label(one if self.interval.get_value_as_int() == 1 else many)
        if kind == "weekly" and not any(b.get_active() for b in self.day_buttons):
            self.day_buttons[(self.due.value or date.today()).weekday()].set_active(True)

    def on_reminder_toggled(self, row, _pspec):
        """When switched on, use sensible defaults: the due date (or today) and the next full hour."""
        if not row.get_enable_expansion() or self.rem_date.value:
            return
        day = self.due.value or date.today()
        hour = 9 if day > date.today() else min(datetime.now().hour + 1, 23)
        self.rem_date.set_value(day)
        self.hour.set_value(hour)
        self.minute.set_value(0)

    def reminder(self):
        if not self.rem.get_enable_expansion():
            return None
        d = self.rem_date.value
        return datetime(d.year, d.month, d.day,
                        self.hour.get_value_as_int(), self.minute.get_value_as_int()).astimezone()

    def on_save(self, *_args):
        title = self.title.get_text().strip()
        if not title:
            self.banner.set_title(_("Please enter a title."))
            self.banner.set_revealed(True)
            return
        due, rem = self.due.value, self.reminder()
        kind, interval, days = self.repeat_state()
        if kind != "none" and not due:
            due = date.today()  # Microsoft requires a due date for recurring tasks

        buf = self.notes.get_buffer()
        notes = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        fields = {"title": title, "importance": "high" if self.important.get_active() else "normal",
                  "dueDateTime": todo.due_to_graph(due) if due else None,
                  "isReminderOn": rem is not None}
        if rem:
            fields["reminderDateTime"] = todo.dt_to_graph(rem)
        if ((kind, interval, days), due) != self._initial:
            fields["recurrence"] = todo.recurrence_to_graph(kind, interval, days, due)
        t = self.t
        if not t or notes != t["notes"]:
            fields["body"] = {"content": notes, "contentType": "text"}

        if t:
            action = lambda: todo.update_task(t["list_id"], t["id"], fields)  # noqa: E731
        else:
            list_id = self.list_ids[self.list_row.get_selected()]
            action = lambda: todo.create_task(list_id, fields)  # noqa: E731
        self.win.change(action, _("Saved ✓"))
        self.close()

    def on_delete(self, *_args):
        t = self.t
        self.win.change(lambda: todo.delete_task(t["list_id"], t["id"]), _("“{title}” deleted").format(title=t["title"]))
        self.close()


def main(startup=False, new=False):
    if startup and not todo.load_json(todo.CACHE_FILE, {}).get("tasks", True):
        return  # at login, show nothing if there are no open tasks

    app = Adw.Application(application_id=APP_ID)

    def window():
        return app.get_active_window() or Window(app)

    def on_startup(app):
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), _color_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        new_action = Gio.SimpleAction.new("new-task", None)
        new_action.connect("activate", lambda *_: (window().present(), window().edit(None)))
        app.add_action(new_action)

    app.connect("startup", on_startup)
    app.connect("activate", lambda app: window().present())

    # If the window is already running, talk to that instance (brings it to the front).
    app.register(None)
    if app.get_is_remote():
        app.activate_action("new-task", None) if new else app.activate()
        return
    if new:
        app.activate_action("new-task", None)
    app.run([])
