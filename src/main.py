# main.py – Flet UI for Shelly Pro 3EM Energy Monitoring.

import math
import sqlite3
from datetime import datetime,timedelta
from pathlib import Path
import flet as ft
import flet_charts as fch
from config import AppConfig
import shelly_db as db
import data as d
from translator import TranslationSystem

ts = TranslationSystem("de_DE")
_ = ts.tr
# uncomment this for a translation in another language
#print(ts.list_locales())
#ts.run_tr_extractor_ui()
#exit()
#Chart colours matching the original hex values
COLOR_CONSUMPTION = ft.Colors.BLUE_300    # #64B5F6 light blue
COLOR_FEEDIN      = ft.Colors.GREEN_300   # #81C784 light green
COLOR_CURRENT     = ft.Colors.ORANGE_400  # #FF9800 orange
COLOR_ALT         = ft.Colors.BLUE_400    # #42A5F5 blue


def show_snackbar(page, text, bgcolor=None, duration=5000):
    """Display a snackbar, removing any previously shown snackbars first."""
    page.overlay[:] = [c for c in page.overlay if not isinstance(c, ft.SnackBar)]
    snack = ft.SnackBar(ft.Text(text), open=True, bgcolor=bgcolor, duration=duration)
    page.overlay.append(snack)
    page.update()


async def main(page: ft.Page):
    """Main entry point: builds and runs the Flet UI."""
    page.title = "Shelly Pro 3EM – Energy Monitor"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 10
    page.safe_area = True
    print('Starte...')
    # Create config once – path via FLET_APP_STORAGE_DATA or fallback
    config = AppConfig()
    print('Config gelesen')
    # Set locale from config if available
    saved_locale = config.get("main", "locale", None)
    if saved_locale:
        ts.set_locale(saved_locale)
    print("Locale gesetzt")
    # ── Read settings ─────────────────────────────────────────────────────────
    # Active MAC – set after discover/connect
    current_mac = [config.get("main", "last_mac", None)]
    print(f"Get Mac {current_mac}")
    def load_settings():
        """Load all user settings for the currently active MAC."""
        mac = current_mac[0]
        sec = mac if mac else "main"
        return {
            "shelly_ip":      config.get(sec, "shelly_ip",      db.DEFAULT_SHELLY_IP),
            "price_per_kwh":  float(config.get(sec, "price_per_kwh",  str(d.DEFAULT_PRICE_PER_KWH))),
            "feedin_price":   float(config.get(sec, "feedin_price",   str(d.DEFAULT_FEEDIN_PRICE_PER_KWH))),
            "base_per_month": float(config.get(sec, "base_per_month", str(d.DEFAULT_BASE_PRICE_PER_MONTH))),
            "alt_price":      float(config.get(sec, "alt_price",      str(d.DEFAULT_ALT_PRICE_PER_KWH))),
            "alt_base":       float(config.get(sec, "alt_base",       str(d.DEFAULT_ALT_BASE_PER_MONTH))),
            "currency":       config.get(sec, "currency",             d.DEFAULT_CURRENCY),
            "date_from":      config.get(sec, "date_from",            (datetime.now() - timedelta(days=730)).strftime("%d.%m.%Y")),
            "date_to":        config.get(sec, "date_to",              datetime.now().strftime("%d.%m.%Y")),
        }

    def save_setting(key, value):
        """Persist a single setting value for the currently active MAC."""
        mac = current_mac[0]
        sec = mac if mac else "main"
        config.set(sec, key, value)

    # ── Platform-aware DB path ────────────────────────────────────────────────
    def get_db_path():
        """Return the platform-appropriate path for the SQLite database."""
        platform = page.platform.value   # 'android', 'linux', 'windows', ...
        if platform in ("android", "android_tv"):
            base = Path("/sdcard/Documents")
        else:
            home = Path.home()
            for name in ("Dokumente", "Documents"):   # Linux locale fallback
                if (home / name).exists():
                    base = home / name
                    break
            else:
                base = home / "Documents"
        db_dir = base / "shelly"
        db_dir.mkdir(parents=True, exist_ok=True)
        return db_dir / "energy.db"
    print("Lades setting ")
    settings = load_settings()
    db_path  = get_db_path()
    print("done")
    print("Init db")
    db.init_db(db_path)
    print("done")
    # ── State ─────────────────────────────────────────────────────────────────
    monthly_data = []
    yearly_data  = []
    cost_monthly = []
    cost_yearly  = []

    # ── Chart containers for all four tabs ────────────────────────────────────
    chart_monthly_kwh   = ft.Column([], expand=True)
    chart_yearly_kwh    = ft.Column([],  expand=True)
    chart_monthly_costs = ft.Column([],  expand=True)
    chart_yearly_costs  = ft.Column([],expand=True)

    def round_dynamic(value):
        """Round up to the next 10 % of the value's order of magnitude.

        Examples: 285.7 → 290, 1.2 → 1.3, 0.07 → 0.07
        """
        if value <= 0:
            return 1
        exponent = math.floor(math.log10(value))
        base     = 10 ** exponent
        step     = base * 0.1
        return math.ceil(value / step) * step

    def date_format(date_str):
        """Convert YYYY-MM to MM.YY; pass YYYY through unchanged."""
        parts = date_str.split("-")
        if len(parts) == 2:
            return f"{parts[1]}.{parts[0][2:]}"
        return date_str

    def make_kwh_chart(labels, values_cons, values_feedin, costs):
        """Build and return a (column, resize_callback) tuple for the kWh bar chart."""
        n = len(labels)
        chart_limit_up = round_dynamic(max(values_cons, default=1) or 1)
        chart_limit_down = round_dynamic(max(values_feedin, default=1) or 1)

        container_top = ft.Container(expand=3, padding=ft.Padding.only(top=10))
        container_bottom = ft.Container(expand=1, margin=ft.Margin.only(top=-10))

        def legend_item(color, text):
            return ft.Row([
                ft.Container(width=12, height=12, bgcolor=color, border_radius=3),
                ft.Text(text, size=11, weight=ft.FontWeight.BOLD),
            ], spacing=5)

        legend = ft.Row([
            legend_item(COLOR_CONSUMPTION, _("Verbrauch (kWh)")),
            legend_item(COLOR_FEEDIN, _("Einspeisung (kWh)")),
            legend_item(ft.Colors.GREY_400, _("Grundpreis (€)")),
        ],
            alignment=ft.MainAxisAlignment.CENTER,
        )
        info_text = ft.Text("", size=10, color=ft.Colors.GREY_400, italic=True)
        info_row  = ft.Container(content=info_text, padding=ft.Padding.symmetric(horizontal=10, vertical=2))


        def build_charts(_e=None):
            bar_width = (page.width - 70) / n * 0.9
            segment_w = (page.width - 70) / max(n, 1)

            is_narrow = segment_w < 50
            rot_val = -1.5708 if is_narrow else 0

            groups_up = []
            groups_down = []
            for i in range(n):
                cons = round(values_cons[i], 2)
                feedin = round(values_feedin[i], 2)
                c = costs[i] if costs and i < len(costs) else {}
                cur_var = c.get("cur_variable", 0.0)
                cur_base = c.get("cur_base", 0.0)
                f_comp = round(feedin * settings["feedin_price"], 2)

                groups_up.append(fch.BarChartGroup(x=i, rods=[
                    fch.BarChartRod(
                        from_y=0, to_y=cons,
                        width=bar_width, color=COLOR_CONSUMPTION,
                        border_radius=1,
                        tooltip=f"{cons:.1f} kWh | {cur_var:.2f} {settings['currency']}",
                    )
                ]))
                groups_down.append(fch.BarChartGroup(x=i, rods=[
                    fch.BarChartRod(
                        from_y=0, to_y=-feedin,
                        width=bar_width, color=COLOR_FEEDIN,
                        border_radius=1,
                        tooltip=f"{feedin:.1f} kWh | {f_comp:.2f} {settings['currency']}",
                    )
                ]))

            bar_data_up = [(round(values_cons[i],2), costs[i].get("cur_variable",0.0) if costs and i<len(costs) else 0.0) for i in range(n)]
            bar_data_down = [(round(values_feedin[i],2), round(values_feedin[i]*settings["feedin_price"],2)) for i in range(n)]

            def on_kwh_event(e: fch.BarChartEvent):
                if e.type in ("TapUpEvent", "PointerDownEvent", "FlTapUpEvent") and e.group_index is not None and e.group_index >= 0:
                    i = e.group_index
                    lbl = labels[i]
                    if e.rod_index == 0 and i < len(bar_data_up):
                        v, cv = bar_data_up[i]
                        info_text.value = f"{lbl}  Verbrauch: {v:.1f} kWh | Kosten: {cv:.2f} {settings['currency']}"
                    page.update()

            def on_kwh_event_down(e: fch.BarChartEvent):
                if e.type in ("TapUpEvent", "PointerDownEvent", "FlTapUpEvent") and e.group_index is not None and e.group_index >= 0:
                    i = e.group_index
                    lbl = labels[i]
                    if e.rod_index == 0 and i < len(bar_data_down):
                        v, fc = bar_data_down[i]
                        info_text.value = f"{lbl}  Einspeisung: {v:.1f} kWh | Vergütung: {fc:.2f} {settings['currency']}"
                    page.update()

            chart_up = fch.BarChart(
                groups=groups_up, interactive=True, border=None, max_y=chart_limit_up,
                on_event=on_kwh_event,
                left_axis=fch.ChartAxis(label_size=50),
                top_axis=fch.ChartAxis(
                    labels=[fch.ChartAxisLabel(value=i, label=ft.Container(
                        content=ft.Text(f"{values_cons[i]:.1f}", size=9, rotate=rot_val),
                        padding=ft.Padding.only(bottom=15) if is_narrow else 0)) for i in range(n)],
                    label_size=35 if is_narrow else 20,
                ),
                bottom_axis=fch.ChartAxis(
                    labels=[fch.ChartAxisLabel(value=i,
                                              label=ft.Container(content=ft.Text(labels[i], size=9, rotate=rot_val),
                                                                 padding=ft.Padding.only(top=15) if is_narrow else 0))
                            for i in range(n)],
                    label_size=45 if is_narrow else 25,
                ),
            )

            chart_down = fch.BarChart(
                groups=groups_down, interactive=True, border=None, min_y=-chart_limit_down, max_y=0,
                on_event=on_kwh_event_down,
                left_axis=fch.ChartAxis(label_size=50),
                top_axis=fch.ChartAxis(
                    labels=[fch.ChartAxisLabel(value=i, label=ft.Container(
                        content=ft.Text(f"{(costs[i].get('cur_base', 0.0) if costs and i < len(costs) else 0.0):.2f}",
                                        size=8, color=ft.Colors.GREY_600, rotate=rot_val),
                        padding=ft.Padding.only(bottom=15) if is_narrow else 0)) for i in range(n)],
                    label_size=35 if is_narrow else 20,
                ),
                bottom_axis=fch.ChartAxis(
                    labels=[fch.ChartAxisLabel(value=i, label=ft.Container(
                        content=ft.Text(f"{values_feedin[i]:.1f}", size=9, color=COLOR_FEEDIN, rotate=rot_val),
                        padding=ft.Padding.only(top=15) if is_narrow else 0)) for i in range(n)],
                    label_size=35 if is_narrow else 25,
                ),
            )

            container_top.content = chart_up
            container_bottom.content = chart_down
            page.update()

        total_kwh = sum(values_cons)
        total_energy_cost = sum(c.get("cur_variable", 0.0) for c in costs) if costs else total_kwh * settings[
            "price_per_kwh"]
        total_base = sum(c.get("cur_base", 0.0) for c in costs) if costs else 0.0
        total_feedin = sum(values_feedin)
        total_compensation = round(total_feedin * settings["feedin_price"], 2)

        summary_row = ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Text(f"{_("Verbrauch:")} {total_kwh:.1f} kWh",                              size=11, color=ft.Colors.BLUE_700,  weight="bold"),
                    ft.Text(f"{_("Energie:")} {total_energy_cost:.2f} {settings['currency']}",      size=10),
                    ft.Text(f"{_("Grundpreis:")} {total_base:.2f} {settings['currency']}",          size=10, color=ft.Colors.GREY_400),
                ], spacing=1),
                ft.Column([
                    ft.Text(f"{_("Einspeisung:")} {total_feedin:.1f} kWh",                          size=11, color=ft.Colors.GREEN_700, weight="bold"),
                    ft.Text(f"{_("Vergütung:")} {total_compensation:.2f} {settings['currency']}",  size=10),
                ], spacing=1),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=10, bgcolor=ft.Colors.GREY_900, border_radius=10
        )

        build_charts()
        return ft.Column([legend, summary_row, info_row, container_top, container_bottom], expand=True), build_charts

    def make_costs_chart(labels, costs_data):
        """Build and return a (column, resize_callback) tuple for the costs bar chart."""
        n, s = len(labels), settings
        chart_limit = round_dynamic(max((c["cur_total"] for c in costs_data), default=1) or 1)

        COLOR_CUR_BASE, COLOR_CUR_ENERGY = ft.Colors.ORANGE_200, ft.Colors.ORANGE_400
        COLOR_ALT_BASE, COLOR_ALT_ENERGY = ft.Colors.BLUE_200, ft.Colors.BLUE_400

        # Totals for summary
        total_cur      = sum(c["cur_total"] for c in costs_data)
        total_alt      = sum(c["alt_total"] for c in costs_data)
        total_cur_base = sum(c.get("cur_base", 0.0) for c in costs_data)
        total_alt_base = sum(c.get("alt_base", 0.0) for c in costs_data)
        total_cur_energy = total_cur - total_cur_base
        total_alt_energy = total_alt - total_alt_base
        diff             = total_cur - total_alt

        def legend_item(color, text):
            return ft.Row([
                ft.Container(width=10, height=10, bgcolor=color, border_radius=2),
                ft.Text(text, size=10, weight="bold"),
            ], spacing=5)

        summary_row = ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Text(f"{_("Aktuell:")} {total_cur:.2f} {s['currency']}",           size=11, color=COLOR_CURRENT,    weight="bold"),
                    ft.Text(f"{_("  Energie:")} {total_cur_energy:.2f} {s['currency']}",   size=10, color=COLOR_CUR_ENERGY),
                    ft.Text(f"{_("  Grundpr.:")} {total_cur_base:.2f} {s['currency']}",    size=10, color=COLOR_CUR_BASE),
                    ft.Text(f"{_("Alt:")} {total_alt:.2f} {s['currency']}",               size=11, color=COLOR_ALT,        weight="bold"),
                    ft.Text(f"{_("  Energie:")} {total_alt_energy:.2f} {s['currency']}",   size=10, color=COLOR_ALT_ENERGY),
                    ft.Text(f"{_("  Grundpr.:")} {total_alt_base:.2f} {s['currency']}",    size=10, color=COLOR_ALT_BASE),
                    ft.Text(f"{_("Differenz:")} {diff:+.2f} {s['currency']}",             size=11,
                            color=ft.Colors.RED_400 if diff > 0 else ft.Colors.GREEN_400, weight="bold"),
                ], spacing=1),
                ft.Column([
                    legend_item(COLOR_CUR_ENERGY, _("Energie akt.")),
                    legend_item(COLOR_CUR_BASE,   _("Grundpr. akt.")),
                    legend_item(COLOR_ALT_ENERGY, _("Energie alt.")),
                    legend_item(COLOR_ALT_BASE,   _("Grundpr. alt.")),
                ], spacing=2),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.Padding.all(10),
            bgcolor=ft.Colors.GREY_900,
            border_radius=10,
        )

        info_text = ft.Text("", size=10, color=ft.Colors.GREY_400, italic=True)

        # Exactly like demo: named outer container, chart directly in inner Container(expand=True)
        y_axis_w        = 40
        rod_count       = n * 2
        chart_container = ft.Container(expand=True)

        def build_chart(_e=None):
            bar_width = (page.width - y_axis_w - 20) / rod_count * 0.9
            groups      = []
            top_labels  = []
            bot_labels  = []

            for i, c in enumerate(costs_data):
                cur_b, cur_t = c.get("cur_base", 0), c["cur_total"]
                alt_b, alt_t = c.get("alt_base", 0), c["alt_total"]

                groups.append(fch.BarChartGroup(
                    x=i,
                    rods=[
                        fch.BarChartRod(
                            from_y=0, to_y=cur_t,
                            width=bar_width,
                            color=COLOR_CUR_ENERGY,
                            border_radius=0,
                            stack_items=[
                                fch.BarChartRodStackItem(0, cur_b, COLOR_CUR_BASE),
                                fch.BarChartRodStackItem(cur_b, cur_t, COLOR_CUR_ENERGY),
                            ],
                        ),
                        fch.BarChartRod(
                            from_y=0, to_y=alt_t,
                            width=bar_width,
                            color=COLOR_ALT_ENERGY,
                            border_radius=0,
                            stack_items=[
                                fch.BarChartRodStackItem(0, alt_b, COLOR_ALT_BASE),
                                fch.BarChartRodStackItem(alt_b, alt_t, COLOR_ALT_ENERGY),
                            ],
                        ),
                    ],
                ))
                top_labels.append(fch.ChartAxisLabel(
                    value=i,
                    label=ft.Text(f"{cur_t:.0f} / {alt_t:.0f}", size=9, color=ft.Colors.GREY_300),
                ))
                bot_labels.append(fch.ChartAxisLabel(
                    value=i,
                    label=ft.Text(labels[i], size=11),
                ))

            # Manual Y-axis
            step   = round_dynamic(chart_limit / 5)
            ticks  = [int(step * i) for i in range(6) if step * i <= chart_limit + step]
            y_axis = ft.Column(
                [ft.Text(str(t), size=11) for t in reversed(ticks)],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                width=y_axis_w,
            )

            chart = fch.BarChart(
                groups=groups,
                max_y=chart_limit,
                min_y=0,
                interactive=False,
                border=None,
                left_axis=None,
                top_axis=fch.ChartAxis(labels=top_labels, label_size=20),
                bottom_axis=fch.ChartAxis(labels=bot_labels, label_size=25),
            )

            chart_container.content = ft.Row([
                y_axis,
                ft.Container(chart, expand=True),
            ])
            page.update()

        build_chart()
        return ft.Column([summary_row, info_text, chart_container], expand=True), build_chart

    # ── Chart resize callbacks ────────────────────────────────────────────────

    monthly_kwh_resizer   = [None]
    yearly_kwh_resizer    = [None]
    monthly_costs_resizer = [None]
    yearly_costs_resizer  = [None]

    def refresh_monthly_kwh():
        """Rebuild the monthly kWh chart from current data."""
        if not monthly_data:
            chart_monthly_kwh.controls = [ft.Text(_("Keine Daten vorhanden, bitte synchronisieren."))]
            monthly_kwh_resizer[0] = None
            return
        chart, build_charts        = make_kwh_chart(
            [date_format(m["month"]) for m in monthly_data],
            [m["consumption_kwh"] for m in monthly_data],
            [m["feedin_kwh"]      for m in monthly_data],
            cost_monthly,
        )
        chart_monthly_kwh.controls  = [chart]
        monthly_kwh_resizer[0]      = build_charts

    def refresh_yearly_kwh():
        """Rebuild the yearly kWh chart from current data."""
        if not yearly_data:
            chart_yearly_kwh.controls = [ft.Text(_("Keine Daten vorhanden, bitte synchronisieren."))]
            yearly_kwh_resizer[0] = None
            return
        chart, build_charts       = make_kwh_chart(
            [y["year"]            for y in yearly_data],
            [y["consumption_kwh"] for y in yearly_data],
            [y["feedin_kwh"]      for y in yearly_data],
            cost_yearly,
        )
        chart_yearly_kwh.controls  = [chart]
        yearly_kwh_resizer[0]      = build_charts

    def refresh_monthly_costs():
        """Rebuild the monthly costs chart from current data."""
        if not cost_monthly:
            chart_monthly_costs.controls = [ft.Text(_("Keine Daten vorhanden, bitte synchronisieren."))]
            monthly_costs_resizer[0] = None
            return
        chart, build_chart           = make_costs_chart(
            [date_format(c["month"]) for c in cost_monthly],
            cost_monthly,
        )
        chart_monthly_costs.controls = [chart]
        monthly_costs_resizer[0]     = build_chart

    def refresh_yearly_costs():
        """Rebuild the yearly costs chart from current data."""
        if not cost_yearly:
            chart_yearly_costs.controls = [ft.Text(_("Keine Daten vorhanden, bitte synchronisieren."))]
            yearly_costs_resizer[0] = None
            return
        chart, build_chart          = make_costs_chart(
            [date_format(c["year"]) for c in cost_yearly],
            cost_yearly,
        )
        chart_yearly_costs.controls = [chart]
        yearly_costs_resizer[0]     = build_chart

    def refresh_all_charts():
        """Rebuild all four charts."""
        refresh_monthly_kwh()
        refresh_yearly_kwh()
        refresh_monthly_costs()
        refresh_yearly_costs()

    # ── Load data ─────────────────────────────────────────────────────────────

    def load_data():
        """Load and aggregate energy records from the DB for the active MAC."""
        nonlocal monthly_data, yearly_data, cost_monthly, cost_yearly
        mac = current_mac[0]
        if not mac:
            return
        records = d.load_reference_days(db_path, mac)

        # Filter by date range from settings
        try:
            date_from = datetime.strptime(settings["date_from"], "%d.%m.%Y").strftime("%Y-%m-%d")
            date_to   = datetime.strptime(settings["date_to"],   "%d.%m.%Y").strftime("%Y-%m-%d")
            records   = [r for r in records if date_from <= r["date"] <= date_to]
        except Exception:
            pass  # if dates are invalid, show all records

        monthly_data = d.calculate_monthly(records, settings["price_per_kwh"])
        yearly_data  = d.calculate_yearly(monthly_data, settings["price_per_kwh"])
        cost_monthly = d.cost_summary_monthly(
            monthly_data,
            price_per_kwh        = settings["price_per_kwh"],
            base_price_per_month = settings["base_per_month"],
            alt_price_per_kwh    = settings["alt_price"],
            alt_base_per_month   = settings["alt_base"],
        )
        cost_yearly = d.cost_summary_yearly(
            yearly_data,
            price_per_kwh        = settings["price_per_kwh"],
            base_price_per_month = settings["base_per_month"],
            alt_price_per_kwh    = settings["alt_price"],
            alt_base_per_month   = settings["alt_base"],
        )

    # ── Settings tab ──────────────────────────────────────────────────────────

    def make_field(label, key, current_value):
        """Create an input field that saves and reloads settings on focus loss."""
        field = ft.TextField(label=label, value=str(current_value), width=300)

        def on_blur(_e):
            save_setting(key, field.value)
            settings.update(load_settings())

        field.on_blur = on_blur
        return field

    # Shelly IP field kept separate so the search button can access it
    field_shelly_ip = ft.TextField(
        label=_("Shelly IP"),
        value=settings["shelly_ip"],
        width=300,
    )

    def on_blur_shelly_ip(_e):
        ip = field_shelly_ip.value.strip()
        if ip:
            on_discover_by_ip(ip)

    field_shelly_ip.on_blur = on_blur_shelly_ip

    lbl_shelly_status = ft.Text(_("Shelly – Bitte Ihren Rechner im gleichen Netzwerk / WLAN einloggen"))
    shelly_info_row   = ft.Container(visible=False)  # populated after discovery

    def make_shelly_info(found):
        """Build a device info card widget from a device info dict."""
        fw_full  = found.get("firmware", "")
        fw_ver   = fw_full.split("/")[-1] if "/" in fw_full else fw_full
        updated  = found.get("updated", "")
        date_str = updated[:10] if len(updated) >= 10 else updated
        time_str = (updated[11:] + _(" Uhr")) if len(updated) > 10 else ""

        def info_item(label, value, color):
            return ft.Column([
                ft.Text(label, size=10, color=ft.Colors.GREY_500),
                ft.Text(value, size=12, color=color, weight=ft.FontWeight.BOLD),
            ], spacing=1, expand=1)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    info_item("Typ",          found.get("typ",   ""), ft.Colors.BLUE_300),
                    info_item("Modell",       found.get("model", ""), ft.Colors.BLUE_300),
                ]),
                ft.Row([
                    info_item("MAC",          found.get("mac",   ""), ft.Colors.ORANGE_300),
                    info_item("Firmware",     fw_ver,                  ft.Colors.GREEN_300),
                ]),
                ft.Row([
                    info_item("Aktualisiert", date_str,                ft.Colors.GREY_400),
                    info_item("Uhrzeit",      time_str,                ft.Colors.GREY_400),
                ]),
            ], spacing=6),
            padding=ft.Padding.only(left=10, right=10, top=8, bottom=8),
            bgcolor=ft.Colors.GREY_900,
            border_radius=6,
        )

    def _apply_found(found):
        """Apply a successfully discovered Shelly device to the app state."""
        mac = found["mac"]
        current_mac[0] = mac
        config.set("main", "last_mac", mac)
        save_setting("shelly_ip", found["ip"])
        db.upsert_device(db_path, found)
        settings.update(load_settings())
        field_shelly_ip.value   = found["ip"]
        lbl_shelly_status.value = _("Shelly – verbunden")
        shelly_info_row.content = make_shelly_info(found)
        shelly_info_row.visible = True
        load_data()
        refresh_all_charts()
        show_snackbar(page, f"{_("Shelly gefunden:")} {found['ip']}")
        page.update()

    def on_discover_by_ip(ip):
        """Connect directly to a Shelly at a known IP address."""
        show_snackbar(page, f"{_("Verbinde mit")} {ip} ...")
        found = db.get_device_info(ip)
        if found:
            _apply_found(found)
        else:
            show_snackbar(page, _("Kein Shelly unter {} erreichbar.").format(ip))

    def on_discover(_e):
        """Scan the local network for a Shelly device."""
        btn_discover.disabled = True
        show_snackbar(page, _("Suche gestartet …"), bgcolor=ft.Colors.GREEN_700, duration=2000)
        page.update()
        show_snackbar(page, _("Suche läuft – bitte warten ..."))

        def log_discover(m):
            show_snackbar(page, str(m))

        found = db.discover_shelly(log_callback=log_discover)
        if found:
            _apply_found(found)
        else:
            show_snackbar(page, _("Kein Shelly gefunden. Bitte IP manuell eingeben."))
        btn_discover.disabled = False
        page.update()

    btn_discover = ft.Button(_("Shelly suchen"), on_click=on_discover)

    def on_locale_select(e):
        config.set("main", "locale", e.control.value)
        ts.set_locale(e.control.value)
        page.update()

    locale_dropdown = ft.Dropdown(
        label=_("Sprache"),
        width=300,
        value=config.get("main", "locale", "de_DE"),
        options=[ft.dropdown.Option(loc) for loc in ts.list_locales()],
        on_select=on_locale_select,
    )

    settings_content = ft.Column(
        [
            lbl_shelly_status,
            field_shelly_ip,
            btn_discover,
            shelly_info_row,
            ft.Divider(),
            ft.Text(_("Aktueller Tarif")),
            make_field(_("Bezugspreis pro kWh"),    "price_per_kwh",  settings["price_per_kwh"]),
            make_field(_("Einspeisevergütung/kWh"), "feedin_price",   settings["feedin_price"]),
            make_field(_("Grundpreis/Monat"),        "base_per_month", settings["base_per_month"]),
            ft.Divider(),
            ft.Text(_("Alternativer Tarif")),
            make_field(_("Alt. Bezugspreis/kWh"),   "alt_price", settings["alt_price"]),
            make_field(_("Alt. Grundpreis/Monat"),  "alt_base",  settings["alt_base"]),
            ft.Divider(),
            ft.Text(_("Anzeige")),
            make_field(_("Währung"), "currency", settings["currency"]),
            ft.Divider(),
            ft.Text(_("Sprache - braucht vielleicht Neustart.")),
            locale_dropdown,
        ],
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    # ── Sync button references (disable/enable across tabs) ───────────────────
    # Each tab gets its own instance since Flet controls can only appear once in the tree.
    sync_buttons = []   # all instances, so on_sync can lock them all at once

    def on_sync(_e):
        """Trigger a data sync from the Shelly device."""
        if not current_mac[0]:
            show_snackbar(page, _("Bitte zuerst einen Shelly eingeben oder suchen."), bgcolor=ft.Colors.ORANGE_700)
            page.update()
            return
        for btn in sync_buttons:
            btn.disabled = True
        show_snackbar(page, _("Synchronisierung gestartet …"), bgcolor=ft.Colors.GREEN_700, duration=2000)
        page.update()

        def log_sync(m):
            show_snackbar(page, str(m))

        msg = db.collect(
            db_path,
            mac          = current_mac[0],
            shelly_ip    = settings["shelly_ip"],
            log_callback = log_sync,
        )
        if msg and "WARNUNG" in msg:
            show_snackbar(page, msg)
        else:
            load_data()
            refresh_all_charts()
            show_snackbar(page, _("Synchronisierung abgeschlossen."))
        for btn in sync_buttons:
            btn.disabled = False
        page.update()


    def make_chart_tab(chart_col):
        """Wrap a chart column with a dedicated sync button at the top."""
        btn = ft.Button(_("Daten synchronisieren"), on_click=on_sync, icon=ft.Icons.SYNC)
        sync_buttons.append(btn)
        result = ft.Column(
            [
                btn,
                chart_col,
            ],
            expand=True,
        )
        return result

    def parse_german_date(text: str):
        text = text.strip()
        if text.lower() in ("heute", "today"):
            return datetime.now().strftime("%d.%m.%Y")
        # 1) Vollständige deutsche Formate
        for fmt in ("%d.%m.%Y", "%d.%m.%y", "%d-%m-%Y", "%d-%m-%y"):
            try:
                # .strftime wandelt das Objekt in den gewünschten String um
                return datetime.strptime(text, fmt).strftime("%d.%m.%Y")
            except:
                pass
        # 2) Monat + Jahr
        for fmt in ("%m.%Y", "%m-%Y", "%m/%Y", "%b %Y", "%B %Y"):
            try:
                return datetime.strptime(text, fmt).replace(day=1).strftime("%d.%m.%Y")
            except:
                pass
        return text

    def checkdate(e):
        """Validate, save and apply a date range field on blur."""
        ctrl = e.control
        dt = parse_german_date(ctrl.value)
        if dt:
            ctrl.value = str(dt)
            key = "date_from" if ctrl == daterange_from else "date_to"
            save_setting(key, ctrl.value)
            settings.update(load_settings())
            load_data()
            refresh_all_charts()
        else:
            ctrl.value = ""
        page.update()

    def on_reset_range(_e):
        """Reset date range to first available DB record up to today."""
        mac = current_mac[0]
        if not mac:
            return
        all_records = d.load_reference_days(db_path, mac)
        if all_records:
            first = datetime.strptime(all_records[0]["date"], "%Y-%m-%d").strftime("%d.%m.%Y")
        else:
            first = (datetime.now() - timedelta(days=730)).strftime("%d.%m.%Y")
        today = datetime.now().strftime("%d.%m.%Y")
        daterange_from.value = first
        daterange_to.value   = today
        save_setting("date_from", first)
        save_setting("date_to",   today)
        settings.update(load_settings())
        load_data()
        refresh_all_charts()
        page.update()

    # ── Import / Migration tab ────────────────────────────────────────────────


    import_status      = ft.Text("", color=ft.Colors.GREY_400)
    import_path_field  = ft.TextField(label=_("Pfad zur alten DB"), width=400, read_only=True)
    daterange_from = ft.TextField(label=_("Zeitraum begin: "), width=200, read_only=False, on_blur=checkdate)
    daterange_to   = ft.TextField(label=_("Zeitraum Ende:"),  width=200, read_only=False, on_blur=checkdate)
    daterange_from.value = settings["date_from"]
    daterange_to.value   = settings["date_to"]

    def get_default_db_dir():
        """Return the default database directory for the current platform."""
        platform = page.platform.value
        if platform in ("android", "android_tv"):
            return "/sdcard/Documents/shelly"
        home = Path.home()
        for name in ("Dokumente", "Documents"):
            if (home / name).exists():
                return str(home / name / "shelly")
        return str(home / "Documents" / "shelly")

    def build_mac_dropdown():
        """Build dropdown options from all known devices in the database."""
        devices = db.load_devices(db_path)
        options = [ft.dropdown.Option(dev["mac"], f"{dev['mac']} – {dev['typ']} {dev['model']}") for dev in devices]
        if not options:
            options = [ft.dropdown.Option("", "Keine Geräte bekannt")]
        return options

    mac_dropdown = ft.Dropdown(
        label="Ziel-MAC",
        width=400,
        options=build_mac_dropdown(),
        value=current_mac[0] or "",
    )

    async def on_pick_file(_e):
        """Open a file picker to select the old database file."""
        result = await ft.FilePicker().pick_files(
            dialog_title=_("Alte DB auswählen"),
            allowed_extensions=["db"],
            initial_directory=get_default_db_dir(),
        )
        files = result.files if hasattr(result, "files") else result
        if files:
            import_path_field.value = files[0].path
            page.update()

    def on_migrate(_e):
        """Migrate raw_hours and reference_days from an old database into the current one."""
        old_path = import_path_field.value.strip()
        mac      = mac_dropdown.value
        if not old_path:
            import_status.value = _("Bitte eine Datei auswählen.")
            import_status.color = ft.Colors.ORANGE_400
            page.update()
            return
        if not mac:
            import_status.value = _("Bitte eine MAC auswählen.")
            import_status.color = ft.Colors.ORANGE_400
            page.update()
            return
        try:
            old_con  = sqlite3.connect(old_path)
            # Migrate raw_hours
            raw_rows = old_con.execute(
                "SELECT ts, a_net_energy, b_net_energy, c_net_energy FROM raw_hours"
            ).fetchall()
            new_con = sqlite3.connect(db_path)
            new_con.executemany(
                "INSERT OR IGNORE INTO raw_hours VALUES (?,?,?,?,?)",
                [(mac, r[0], r[1], r[2], r[3]) for r in raw_rows]
            )
            # Migrate reference_days
            ref_rows = old_con.execute(
                "SELECT date, ts_start, ts_end, consumption_wh, feedin_wh FROM reference_days"
            ).fetchall()
            new_con.executemany(
                "INSERT OR IGNORE INTO reference_days VALUES (?,?,?,?,?,?)",
                [(mac, r[0], r[1], r[2], r[3], r[4]) for r in ref_rows]
            )
            new_con.commit()
            new_con.close()
            old_con.close()
            import_status.value = f"Migration abgeschlossen: {len(raw_rows)} Rohdaten, {len(ref_rows)} Stichtage."
            import_status.color = ft.Colors.GREEN_400
            load_data()
            refresh_all_charts()
        except Exception as ex:
            import_status.value = f"Fehler: {ex}"
            import_status.color = ft.Colors.RED_400
        page.update()

    import_content = ft.Column(
        [
            ft.Text(_("Migration alter Datenbank"), size=14, weight=ft.FontWeight.BOLD),
            ft.Text(_("Wähle die alte energy.db und die Ziel-MAC für die importierten Daten."), color=ft.Colors.GREY_400),
            ft.Divider(),
            mac_dropdown,
            ft.Row([import_path_field, ft.Button(_("Datei wählen"), on_click=on_pick_file)]),
            ft.Button(_("Migrieren"), on_click=on_migrate, icon=ft.Icons.UPLOAD),
            import_status,
            ft.Divider(),
            ft.Text(_("Anzeige-Zeitraum"), size=14, weight=ft.FontWeight.BOLD),
            ft.Row([daterange_from, daterange_to]),
            ft.Button(_("Zeitraum zurücksetzen"), on_click=on_reset_range, icon=ft.Icons.RESTART_ALT),
            ft.Divider(),
            ft.Text(_("Verwendete Pfade"), size=14, weight=ft.FontWeight.BOLD),
            ft.Text(f"{_("Datenbank:")}  {db_path}", size=11, color=ft.Colors.GREY_400, selectable=True),
            ft.Text(f"{_("Einstellungen:")}  {config.path}", size=11, color=ft.Colors.GREY_400, selectable=True),
        ],
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    # ── Tabs ──────────────────────────────────────────────────────────────────
    def on_resized(_e=None):
        """Trigger chart rebuilds on window resize."""
        if monthly_kwh_resizer[0]:
            monthly_kwh_resizer[0]()
        if yearly_kwh_resizer[0]:
            yearly_kwh_resizer[0]()
        if monthly_costs_resizer[0]:
            monthly_costs_resizer[0]()
        if yearly_costs_resizer[0]:
            yearly_costs_resizer[0]()
    print("Page setup")
    page.on_resize = on_resized

    page.add(
        ft.Tabs(
            length=6,
            selected_index=0,
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(
                        tabs=[
                            ft.Tab(label=_("Monat kWh")),
                            ft.Tab(label=_("Jahr kWh")),
                            ft.Tab(label=_("Monat Kosten")),
                            ft.Tab(label=_("Jahr Kosten")),
                            ft.Tab(label=_("Einstellungen")),
                            ft.Tab(label=_("Import & Data")),
                        ]
                    ),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            ft.Container(content=make_chart_tab(chart_monthly_kwh), padding=10),
                            ft.Container(content=make_chart_tab(chart_yearly_kwh), padding=10),
                            ft.Container(content=make_chart_tab(chart_monthly_costs), padding=10),
                            ft.Container(content=make_chart_tab(chart_yearly_costs), padding=10),
                            ft.Container(content=settings_content, padding=10),
                            ft.Container(content=import_content, padding=10),
                        ],
                    ),
                ],
            ),
        ),
    )

    # Display existing data immediately.
    # If the last known Shelly is in the DB, load and show its info.
    if current_mac[0]:
        devices = db.load_devices(db_path)
        known   = {dev["mac"]: dev for dev in devices}
        if current_mac[0] in known:
            dev = known[current_mac[0]]
            lbl_shelly_status.value = "Shelly – verbunden"
            shelly_info_row.content = make_shelly_info(dev)
            shelly_info_row.visible = True
    print("load data")
    load_data()
    print("done")
    refresh_all_charts()
    page.update()
    if not monthly_data:
        show_snackbar(page, _("Keine Daten vorhanden, bitte synchronisieren."))


ft.run(main)