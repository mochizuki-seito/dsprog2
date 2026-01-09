import flet as ft
import requests
import sqlite3
import datetime
import json # For initial parsing of area.json

# データベースファイル名
DATABASE_NAME = "weather_forecasts.db"

# --- DB Helper Functions ---

def init_db():
    """データベースの初期化とテーブル作成を行う"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # areas テーブルの作成
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS areas (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_office_code TEXT NULL,
            type TEXT NOT NULL
        )
    """)

    # forecasts テーブルの作成
    # area_code, report_datetime, forecast_date の組み合わせでユニークな予報を想定
    # fetched_at は、その予報データがいつDBに保存されたかを示す
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            area_code TEXT NOT NULL,
            report_datetime TEXT NOT NULL,
            forecast_date TEXT NOT NULL,
            weather_code TEXT,
            weather_text TEXT,
            min_temperature INTEGER,
            max_temperature INTEGER,
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (area_code) REFERENCES areas(code),
            UNIQUE (area_code, report_datetime, forecast_date) ON CONFLICT REPLACE
        )
    """)
    conn.commit()
    conn.close()

def populate_areas_db(all_areas_data):
    """JMA APIから取得した地域情報をareasテーブルに投入する"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Center (管区気象台)
    for c_code, c_info in all_areas_data["centers"].items():
        cursor.execute("INSERT OR IGNORE INTO areas (code, name, parent_office_code, type) VALUES (?, ?, ?, ?)",
                       (c_code, c_info["name"], None, 'center'))

    # Office (予報区/都道府県庁所在地など)
    for o_code, o_info in all_areas_data["offices"].items():
        parent_center_code = None
        # 所属する管区気象台を探す
        for c_code_check, c_info_check in all_areas_data["centers"].items():
            if o_code in c_info_check.get("children", []):
                parent_center_code = c_code_check
                break
        cursor.execute("INSERT OR IGNORE INTO areas (code, name, parent_office_code, type) VALUES (?, ?, ?, ?)",
                       (o_code, o_info["name"], parent_center_code, 'office'))

    # Class10s (詳細地域)
    for c10_code, c10_info in all_areas_data["class10s"].items():
        parent_office_code = None
        # 所属する予報区を探す
        for o_code_check, o_info_check in all_areas_data["offices"].items():
            if c10_code in o_info_check.get("children", []):
                parent_office_code = o_code_check
                break
        cursor.execute("INSERT OR IGNORE INTO areas (code, name, parent_office_code, type) VALUES (?, ?, ?, ?)",
                       (c10_code, c10_info["name"], parent_office_code, 'class10s'))
    conn.commit()
    conn.close()

def insert_forecast_into_db(area_code, report_datetime, forecast_date, weather_code, weather_text, min_temp, max_temp):
    """天気予報データをforecastsテーブルに挿入または更新する"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    fetched_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # UNIQUE制約 (area_code, report_datetime, forecast_date) ON CONFLICT REPLACE により、
    # 同じ予報が存在する場合は置き換えられる (UPDATEの挙動と同様)
    cursor.execute("""
        INSERT INTO forecasts (area_code, report_datetime, forecast_date, weather_code, weather_text, min_temperature, max_temperature, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (area_code, report_datetime, forecast_date, weather_code, weather_text, min_temp, max_temp, fetched_at))
    conn.commit()
    conn.close()

def get_forecasts_from_db(area_code, target_forecast_date=None):
    """
    DBから天気予報データを取得する
    target_forecast_dateがNoneの場合、最新の発表日時の全ての予報日付を取得
    指定された場合、その日付の最も新しい発表日時の予報を取得
    """
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    if target_forecast_date:
        # 特定の予報日付が指定された場合、その日付の最も新しい発表日時の予報を取得
        query = """
            SELECT
                forecast_date, weather_code, weather_text, min_temperature, max_temperature
            FROM
                forecasts
            WHERE
                area_code = ? AND forecast_date = ?
            ORDER BY
                report_datetime DESC
            LIMIT 1
        """
        params = [area_code, target_forecast_date]
    else:
        # 特定の予報日付が指定されない場合、最新の発表日時の全ての予報日付を取得
        # 同じreport_datetimeのレコードが複数ある場合、それらを全て取得
        query = """
            SELECT
                forecast_date, weather_code, weather_text, min_temperature, max_temperature
            FROM
                forecasts
            WHERE
                area_code = ? AND report_datetime = (
                    SELECT MAX(report_datetime) FROM forecasts WHERE area_code = ?
                )
            ORDER BY
                forecast_date ASC
        """
        params = [area_code, area_code]
    
    cursor.execute(query, params)
    data = cursor.fetchall()
    conn.close()
    return data

def get_area_children_from_db(selected_office_code):
    """指定されたoffice_codeの子のエリア（class10s）をDBから取得する"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # まず、selected_office_codeに属するclass10sタイプの子を探す
    cursor.execute("""
        SELECT code, name FROM areas
        WHERE parent_office_code = ? AND type = 'class10s'
        ORDER BY code
    """, (selected_office_code,))
    children = cursor.fetchall()

    if not children:
        # class10sの子が見つからない場合、そのoffice_code自体を詳細地域として扱う
        cursor.execute("SELECT code, name FROM areas WHERE code = ? AND type = 'office'", (selected_office_code,))
        children = cursor.fetchall()
    
    conn.close()
    return children


def get_sidebar_data_from_db():
    """サイドバー表示用の地域階層データをDBから取得する"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    sidebar_data = []

    # Centers (管区気象台) を取得
    cursor.execute("SELECT code, name FROM areas WHERE type = 'center' ORDER BY code")
    centers = cursor.fetchall()

    for c_code, c_name in centers:
        sub_tiles_data = []
        # このCenterに属するOffices (予報区) を取得
        cursor.execute("""
            SELECT code, name FROM areas
            WHERE parent_office_code = ? AND type = 'office'
            ORDER BY code
        """, (c_code,))
        offices = cursor.fetchall()
        
        # もし子Officesが見つからない場合、そのCenter自体がOfficeとして機能している可能性を考慮し、
        # Centerに直接紐づくOfficeを再度検索するか、別のロジックで対応が必要になるかもしれません。
        # 現在のJMAデータ構造では、Centerの下にOfficeが直接紐づいています。
        
        for o_code, o_name in offices:
            sub_tiles_data.append({'code': o_code, 'name': o_name})
        
        sidebar_data.append({'center_code': c_code, 'center_name': c_name, 'offices': sub_tiles_data})
    
    conn.close()
    return sidebar_data


def main(page: ft.Page):
    page.title = "天気予報 - 気象庁高度解析版"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.spacing = 0
    page.window_width = 1200
    page.window_height = 850

    COLOR_HEADER = "#1B7292"
    COLOR_SIDEBAR = "#455A64"
    COLOR_BG = "#CFD8DC"

    # --- DB初期化とエリア情報の投入 ---
    init_db()
    
    # areasテーブルが空の場合のみ、APIから地域情報を取得して投入
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM areas")
    if cursor.fetchone()[0] == 0:
        # SnackBarの定義に duration プロパティを追加
        page.snack_bar = ft.SnackBar(
            ft.Text("地域情報を初期データベースにインポートしています...", color=ft.colors.WHITE),
            open=True,
            duration=2000 # ここで表示時間を設定 (ミリ秒単位)
        )
        page.update() # SnackBarを一度表示

        try:
            all_areas_api = requests.get("https://www.jma.go.jp/bosai/common/const/area.json").json()
            populate_areas_db(all_areas_api)
            page.snack_bar.content = ft.Text("地域情報のインポートが完了しました。", color=ft.colors.WHITE)
            page.snack_bar.bgcolor = ft.colors.GREEN_700
            page.snack_bar.open = True # 成功メッセージを表示するために再度open=Trueを設定
        except Exception as e:
            page.snack_bar.content = ft.Text(f"地域情報のインポートに失敗しました: {e}", color=ft.colors.WHITE)
            page.snack_bar.bgcolor = ft.colors.RED_700
            page.snack_bar.open = True # 失敗メッセージを表示するために再度open=Trueを設定
        finally:
            page.update() # SnackBarの内容と表示状態を更新
    conn.close()

    def get_weather_info(code):
        """天気コードに基づいてアイコンと色を返す"""
        c = str(code)
        if c.startswith("1"): return ft.Icons.WB_SUNNY, "orange" # 晴れ
        if c.startswith("2"): return ft.Icons.CLOUD, "grey"     # 曇り
        if c.startswith("3"): return ft.Icons.UMBRELLA, "blue"  # 雨
        if c.startswith("4"): return ft.Icons.AC_UNIT, "lightBlue" # 雪
        return ft.Icons.QUESTION_MARK, "black"

    weather_grid = ft.GridView(expand=True, max_extent=250, child_aspect_ratio=0.7, spacing=15)
    
    city_dropdown = ft.Dropdown(
        label="詳細地域（エリア）を選択",
        width=400, bgcolor="white",
        on_change=lambda e: update_weather_display(e.control.value) # e.control.value で選択されたキーを取得
    )

    page.appbar = ft.AppBar(
        leading=ft.Icon(ft.Icons.WB_SUNNY_OUTLINED, color="white"),
        title=ft.Text("天気予報 - 気象庁高度解析版 (DB連携)", size=24, weight="bold", color="white"),
        bgcolor=COLOR_HEADER,
    )

    # --- 日付選択機能 (オプション) ---
    def on_date_change(e):
        """日付ピッカーで日付が変更された際の処理"""
        if date_picker.value:
            selected_date_str = date_picker.value.strftime("%Y-%m-%d")
            update_weather_display(city_dropdown.value, selected_forecast_date=selected_date_str)
        else:
            # 日付がクリアされた場合、最新の予報を表示
            update_weather_display(city_dropdown.value)

    date_picker = ft.DatePicker(
        on_change=on_date_change,
        # on_cancel=lambda e: print("Date picker canceled!"), # << この行を削除しました。
        first_date=datetime.datetime.now() - datetime.timedelta(days=30), # 過去30日まで選択可能
        last_date=datetime.datetime.now() + datetime.timedelta(days=7),   # 未来7日まで選択可能
    )
    page.overlay.append(date_picker) # DatePickerはoverlayに追加する必要がある

    def open_date_picker(e):
        date_picker.open = True
        page.update()

    date_button = ft.ElevatedButton(
        "日付選択",
        icon=ft.Icons.CALENDAR_MONTH,
        on_click=open_date_picker,
        bgcolor="white", color=COLOR_HEADER
    )

    # --- 2. データの取得、DB保存、表示ロジック ---
    def update_weather_display(selected_area_code, selected_forecast_date=None):
        """
        選択された地域の天気予報を取得し、DBに保存後、表示を更新する。
        selected_forecast_dateが指定された場合、その日付の予報を表示する。
        """
        if not selected_area_code:
            weather_grid.controls.clear()
            weather_grid.controls.append(ft.Text("地域を選択してください。", color="gray", size=16))
            page.update()
            return
        
        weather_grid.controls.clear()
        weather_grid.controls.append(ft.Container(content=ft.ProgressRing(), alignment=ft.alignment.center, expand=True))
        page.update()
        
        try:
            # --- APIから最新データを取得しDBに保存 ---
            # APIを呼び出すための親OfficeコードをDBから取得
            conn = sqlite3.connect(DATABASE_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT parent_office_code, type FROM areas WHERE code = ?", (selected_area_code,))
            area_info = cursor.fetchone()
            conn.close()

            api_target_office_code = selected_area_code # デフォルトは自分自身のコード
            if area_info and area_info[1] == 'class10s' and area_info[0]:
                api_target_office_code = area_info[0] # class10sの場合、その親オフィスコードを使用
            elif area_info and area_info[1] == 'office': # officeが直接選択された場合
                api_target_office_code = selected_area_code
            elif area_info and area_info[1] == 'center':
                # Centerの場合、JMAのAPIはCenterコードではなく、その管轄の主要officeコードで呼び出す必要があることが多い
                # 例: 東京管区気象台(210000)の子の東京(130000)を使用するなど
                # ここでは簡単な例として、もしCenterが直接選択されたら、そのCenterの最初のOfficeの子を使うと仮定
                cursor = sqlite3.connect(DATABASE_NAME).cursor()
                cursor.execute("SELECT code FROM areas WHERE parent_office_code = ? AND type = 'office' ORDER BY code LIMIT 1", (selected_area_code,))
                first_office = cursor.fetchone()
                if first_office:
                    api_target_office_code = first_office[0]
                else: # Fallback if no office children for center
                    api_target_office_code = selected_area_code

            # JMA APIから予報データを取得
            res = requests.get(f"https://www.jma.go.jp/bosai/forecast/data/forecast/{api_target_office_code}.json").json()
            forecast_data = res[0] # [0]は短期予報
            report_datetime = forecast_data["reportDatetime"] # 予報発表日時

            # APIから取得したデータを解析し、DBに保存
            target_weather_series = None
            for series in forecast_data["timeSeries"]:
                if "weathers" in series["areas"][0]:
                    target_weather_series = series
                    break
            
            target_temp_series = None
            for series in forecast_data["timeSeries"]:
                if "temps" in series["areas"][0]:
                    target_temp_series = series
                    break

            if target_weather_series and target_temp_series:
                time_defines = target_weather_series["timeDefines"]
                
                # 選択されたエリアの天気と気温データを抽出 (見つからない場合は、予報区の代表値を使用)
                target_weather_area = next((a for a in target_weather_series["areas"] if a["area"]["code"] == selected_area_code), 
                                           target_weather_series["areas"][0] if target_weather_series["areas"] else None)
                target_temp_area = next((a for a in target_temp_series["areas"] if a["area"]["code"] == selected_area_code), 
                                        target_temp_series["areas"][0] if target_temp_series["areas"] else None)

                if target_weather_area and target_temp_area:
                    codes = target_weather_area["weatherCodes"]
                    weathers = target_weather_area["weathers"]
                    temps = target_temp_area["temps"]
                    
                    for i in range(len(codes)):
                        forecast_date_iso = time_defines[i]
                        # '2023-10-27T09:00:00+09:00' -> 'YYYY-MM-DD'
                        forecast_date_str = datetime.datetime.fromisoformat(forecast_date_iso).strftime("%Y-%m-%d")
                        
                        # 気温データは [最低気温, 最高気温, ...] の配列。
                        # 予報日によってデータがない場合もあるので、安全にアクセス
                        # temps配列の長さは `len(codes) * 2` とは限らない場合があるので注意
                        t_min = temps[i*2] if (i*2) < len(temps) else None
                        t_max = temps[i*2+1] if (i*2+1) < len(temps) else None
                        
                        insert_forecast_into_db(selected_area_code, report_datetime, forecast_date_str, 
                                                codes[i], weathers[i].replace("　", " "), t_min, t_max)
            
            # --- DBからデータを読み込んで表示 ---
            forecast_items = get_forecasts_from_db(selected_area_code, selected_forecast_date)

            weather_grid.controls.clear()
            if not forecast_items:
                weather_grid.controls.append(ft.Text("この地域の予報データが見つかりませんでした。", color="gray"))
            else:
                for item in forecast_items:
                    # DBから取得したタプルをアンパック
                    forecast_date_str, weather_code, weather_text, min_temp, max_temp = item
                    icon, color = get_weather_info(weather_code)
                    
                    min_temp_str = f"{min_temp}°" if min_temp is not None else "--"
                    max_temp_str = f"{max_temp}°" if max_temp is not None else "--"
                    
                    weather_grid.controls.append(
                        ft.Card(
                            elevation=4,
                            content=ft.Container(
                                padding=20, border_radius=10, bgcolor="white",
                                content=ft.Column([
                                    ft.Text(forecast_date_str, weight="bold", size=16),
                                    ft.Icon(icon, color=color, size=60),
                                    ft.Text(weather_text, size=12, text_align="center", height=45),
                                    ft.Row([
                                        ft.Text(min_temp_str, color="blue", size=18, weight="bold"),
                                        ft.Text("/", size=18),
                                        ft.Text(max_temp_str, color="red", size=18, weight="bold"),
                                    ], alignment=ft.MainAxisAlignment.CENTER)
                                ], horizontal_alignment="center", alignment="center")
                            )
                        )
                    )
        except requests.exceptions.RequestException as req_ex:
            weather_grid.controls.clear()
            weather_grid.controls.append(ft.Column([
                ft.Text("ネットワークエラーが発生しました。", color="red"),
                ft.Text(f"詳細: {req_ex}", color="red", size=12)
            ]))
        except json.JSONDecodeError as json_ex:
            weather_grid.controls.clear()
            weather_grid.controls.append(ft.Column([
                ft.Text("APIからのデータ解析に失敗しました。", color="red"),
                ft.Text(f"詳細: {json_ex}", color="red", size=12)
            ]))
        except Exception as ex:
            weather_grid.controls.clear()
            weather_grid.controls.append(ft.Column([
                ft.Text("データ処理中に予期せぬエラーが発生しました。", color="red"),
                ft.Text(f"詳細: {ex}", color="red", size=12)
            ]))
        page.update()

    # --- 3. 都道府県選択時の処理 ---
    def on_office_select(office_code):
        """サイドバーでOfficeが選択された際の処理"""
        city_dropdown.options = []
        # DBから指定されたOfficeコードの子のエリア（class10s）を取得
        children_data = get_area_children_from_db(office_code)

        for code, name in children_data:
            city_dropdown.options.append(ft.dropdown.Option(key=code, text=name))
        
        if city_dropdown.options:
            city_dropdown.value = city_dropdown.options[0].key # 最初の子をデフォルトで選択
        else:
            city_dropdown.value = None # オプションがなければクリア

        page.update()
        if city_dropdown.value:
            update_weather_display(city_dropdown.value)

    # --- 4. サイドバー構築 ---
    sidebar_items = []
    sidebar_data = get_sidebar_data_from_db() # DBからサイドバー用の階層データを取得

    for center_info in sidebar_data:
        sub_tiles = []
        for office_info in center_info["offices"]:
            sub_tiles.append(
                ft.ListTile(
                    title=ft.Text(office_info['name'], color="white", size=14),
                    on_click=lambda e, code=office_info['code']: on_office_select(code)
                )
            )
        sidebar_items.append(
            ft.ExpansionTile(
                title=ft.Text(center_info["center_name"], color="white", size=15, weight="bold"),
                controls=sub_tiles, collapsed_icon_color="white", icon_color="white",
            )
        )

    # --- レイアウト構築 ---
    page.add(
        ft.Row([
            ft.Container(width=260, bgcolor=COLOR_SIDEBAR, content=ft.Column([
                ft.Container(padding=15, content=ft.Text("地域一覧", color="white", size=16, weight="bold")),
                ft.Column(sidebar_items, scroll="adaptive", expand=True)
            ], spacing=0)),
            ft.Container(expand=True, bgcolor=COLOR_BG, padding=30, content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.SEARCH, color="blueGrey"), city_dropdown, date_button],
                       alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Divider(height=20, color="transparent"),
                weather_grid
            ]))
        ], expand=True, spacing=0)
    )
    # 初期表示: 東京 (130000) の予報をロード
    on_office_select("130000")

# Fletアプリケーションの実行
ft.app(target=main)