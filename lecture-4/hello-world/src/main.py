import flet as ft


def main(page: ft.Page):

    # カウンター表示用のテキスト
    counter = ft.Text("0", size=50, data=0)

    #
    hore = ft.Text("hello",size=50, data=0)

    # ボタンはが押下された時に呼び出される関数
    def increment_click(e):
        counter.data += 1
        counter.value = str(counter.data)
        counter.update()

    
    def decrement_click(e):
        counter.data -= 1
        counter.value = str(counter.data)
        counter.update()

    # カウンターを増やすボタン
    page.floating_action_button = ft.FloatingActionButton(icon=ft.Icons.ADD, on_click=increment_click)


    # SafeAreaで囲んで、中央にカウンターを配置
    page.add(
        ft.SafeArea(
            ft.Container(
                content=ft.Column(controls=[counter, hore]),  # 'countent' を 'content' に修正
                alignment=ft.alignment.center,
            ),
            expand=True,
        ),
        ft.FloatingActionButton(icon=ft.Icons.REMOVE, on_click=decrement_click)
    )


ft.app(main)