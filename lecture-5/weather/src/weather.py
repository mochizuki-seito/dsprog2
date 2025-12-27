import flet as ft
import requests

def main(page: ft.Page):
    page.title = "天気報 - 気象庁高度解析版"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.spacing = 0
    page.window_width = 1200
    page.window_height = 850

    COLOR_HEADER = "#311B92"
    COLOR_SIDEBAR = "#455A64"
    COLOR_BG = "#CFD8DC"

    # --- 1. 地域定義の取得 ---
    all_areas = requests.get("https://www.jma.go.jp/bosai/common/const/area.json").json()

    def get_weather_info(code):
        c = str(code)
        if c.startswith("1"): return ft.Icons.WB_SUNNY, "orange"
        if c.startswith("2"): return ft.Icons.CLOUD, "grey"
        if c.startswith("3"): return ft.Icons.UMBRELLA, "blue"
        if c.startswith("4"): return ft.Icons.AC_UNIT, "lightBlue"
        return ft.Icons.QUESTION_MARK, "black"

    weather_grid = ft.GridView(expand=True, max_extent=250, child_aspect_ratio=0.7, spacing=15)
    
    city_dropdown = ft.Dropdown(
        label="詳細地域（エリア）を選択",
        width=400, bgcolor="white",
        on_change=lambda e: update_weather_display(e.data)
    )

    page.appbar = ft.AppBar(
        leading=ft.Icon(ft.Icons.WB_SUNNY_OUTLINED, color="white"),
        title=ft.Text("天気報", size=24, weight="bold", color="white"),
        bgcolor=COLOR_HEADER,
        actions=[ft.IconButton(ft.Icons.GRID_VIEW_ROUNDED, icon_color="white"), ft.IconButton(ft.Icons.MENU, icon_color="white")],
    )

    # --- 2. データの動的解析ロジック ---
    def update_weather_display(area_code):
        if not area_code: return
        weather_grid.controls.clear()
        weather_grid.controls.append(ft.Container(content=ft.ProgressRing(), alignment=ft.alignment.center, expand=True))
        page.update()
        
        try:
            # 親の都道府県コードを探す
            parent_office = ""
            for o_code, o_info in all_areas["offices"].items():
                if area_code in o_info.get("children", []) or area_code == o_code:
                    parent_office = o_code
                    break

            # APIから予報データを取得
            res = requests.get(f"https://www.jma.go.jp/bosai/forecast/data/forecast/{parent_office}.json").json()
            forecast_data = res[0] # [0]は短期予報

            # --- A. 天気文とコードの抽出 ---
            target_weather = None
            time_defines = []
            for series in forecast_data["timeSeries"]:
                if "weathers" in series["areas"][0]:
                    time_defines = series["timeDefines"]
                    # 選択したエリアのコードを探す。なければ最初のエリア。
                    target_weather = next((a for a in series["areas"] if a["area"]["code"] == area_code), series["areas"][0])
                    break

            # --- B. 気温データの抽出 ---
            # 気温は詳細地域(class10s)にはないことが多いため、見つからない場合は都道府県代表値(office)を表示
            target_temp = None
            for series in forecast_data["timeSeries"]:
                if "temps" in series["areas"][0]:
                    # 1. まず選択エリアを探す
                    target_temp = next((a for a in series["areas"] if a["area"]["code"] == area_code), None)
                    # 2. なければ最初のエリア（通常は県庁所在地）を代用
                    if not target_temp:
                        target_temp = series["areas"][0]
                    break

            weather_grid.controls.clear()
            if target_weather:
                codes = target_weather["weatherCodes"]
                weathers = target_weather["weathers"]
                temps = target_temp["temps"] if target_temp else []

                for i in range(len(codes)):
                    icon, color = get_weather_info(codes[i])
                    
                    # 気温配列の安全な取得
                    # 予報日によって [最高, 最低] の時と [最低, 最高] の時があるが、簡易的にマッピング
                    t_min = temps[i*2] if len(temps) > i*2 else "--"
                    t_max = temps[i*2+1] if len(temps) > i*2+1 else "--"

                    weather_grid.controls.append(
                        ft.Card(
                            elevation=4,
                            content=ft.Container(
                                padding=20, border_radius=10, bgcolor="white",
                                content=ft.Column([
                                    ft.Text(time_defines[i][:10], weight="bold", size=16),
                                    ft.Icon(icon, color=color, size=60),
                                    ft.Text(weathers[i].replace("　", " "), size=12, text_align="center", height=45),
                                    ft.Row([
                                        ft.Text(f"{t_min}°", color="blue", size=18, weight="bold"),
                                        ft.Text("/", size=18),
                                        ft.Text(f"{t_max}°", color="red", size=18, weight="bold"),
                                    ], alignment=ft.MainAxisAlignment.CENTER)
                                ], horizontal_alignment="center", alignment="center")
                            )
                        )
                    )
        except Exception as ex:
            weather_grid.controls.clear()
            weather_grid.controls.append(ft.Text(f"データ解析エラー: {ex}", color="red"))
        page.update()

    # --- 3. 都道府県選択時の処理 ---
    def on_office_select(office_code):
        city_dropdown.options = []
        children_codes = all_areas["offices"][office_code].get("children", [])
        if not children_codes: children_codes = [office_code]
        
        for code in children_codes:
            name = all_areas.get("class10s", {}).get(code, {}).get("name")
            if not name: name = all_areas["offices"].get(code, {}).get("name", "不明")
            city_dropdown.options.append(ft.dropdown.Option(key=code, text=name))
        
        city_dropdown.value = children_codes[0]
        page.update()
        update_weather_display(city_dropdown.value)

    # --- 4. サイドバー構築 ---
    sidebar_items = []
    for c_code, c_info in all_areas["centers"].items():
        sub_tiles = []
        for o_code in c_info["children"]:
            if o_code in all_areas["offices"]:
                sub_tiles.append(ft.ListTile(
                    title=ft.Text(all_areas["offices"][o_code]["name"], color="white", size=14),
                    on_click=lambda e, code=o_code: on_office_select(code)
                ))
        sidebar_items.append(ft.ExpansionTile(
            title=ft.Text(c_info["name"], color="white", size=15, weight="bold"),
            controls=sub_tiles, collapsed_icon_color="white", icon_color="white",
        ))

    page.add(
        ft.Row([
            ft.Container(width=260, bgcolor=COLOR_SIDEBAR, content=ft.Column([
                ft.Container(padding=15, content=ft.Text("地域一覧", color="white", size=16, weight="bold")),
                ft.Column(sidebar_items, scroll="adaptive", expand=True)
            ], spacing=0)),
            ft.Container(expand=True, bgcolor=COLOR_BG, padding=30, content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.SEARCH, color="blueGrey"), city_dropdown]),
                ft.Divider(height=20, color="transparent"),
                weather_grid
            ]))
        ], expand=True, spacing=0)
    )
    on_office_select("130000")

ft.app(target=main)