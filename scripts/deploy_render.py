"""Playwright で Render ダッシュボードを操作してデプロイする。

使い方:
  python3 scripts/deploy_render.py

ブラウザが開くので、まず Render にログインしてください。
ログイン完了後、自動でサービス作成を行います。
"""
import sys
import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


REPO_NAME = "itashiki124/line-warikan-bot"
SERVICE_NAME = "line-warikan-bot"
BUILD_CMD = "pip install -r requirements.txt"
START_CMD = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"


def wait_for_login(page):
    """ユーザーがログインするまで待機"""
    print("🔑 Render にログインしてください...")
    print("   (ログイン済みの場合は自動的に進みます)")
    # ダッシュボードに到達するまで待つ
    while True:
        url = page.url
        if "dashboard.render.com" in url and "/login" not in url and "/register" not in url:
            print("✅ ログイン確認!")
            return
        time.sleep(2)


def create_web_service(page):
    """New Web Service を作成"""
    print("\n📦 新しい Web Service を作成中...")

    # New + ボタンをクリック
    page.goto("https://dashboard.render.com/select-repo?type=web")
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # GitHub リポジトリを検索・接続
    print("🔍 リポジトリを検索中...")

    # リポジトリ検索フィールドを探す
    search_input = page.locator('input[placeholder*="Search"], input[placeholder*="search"], input[type="search"]').first
    if search_input.is_visible():
        search_input.fill("line-warikan-bot")
        time.sleep(2)

    # リポジトリの Connect ボタンをクリック
    # リポジトリ名を含む行の Connect ボタンを探す
    connect_clicked = False
    for attempt in range(3):
        try:
            # "Connect" ボタンを探す
            connect_buttons = page.locator('button:has-text("Connect"), a:has-text("Connect")')
            count = connect_buttons.count()
            for i in range(count):
                btn = connect_buttons.nth(i)
                # line-warikan-bot に関連する Connect ボタンを探す
                parent_text = btn.locator("xpath=ancestor::*[contains(., 'line-warikan-bot')]").first
                if parent_text.is_visible():
                    btn.click()
                    connect_clicked = True
                    break
            if connect_clicked:
                break

            # それでもだめなら、line-warikan-bot を含む行を探して近くの Connect をクリック
            repo_row = page.locator(f'text=line-warikan-bot').first
            if repo_row.is_visible():
                # 同じコンテナ内の Connect ボタンを探す
                container = repo_row.locator("xpath=ancestor::div[.//button or .//a]").first
                connect_btn = container.locator('button:has-text("Connect"), a:has-text("Connect")').first
                if connect_btn.is_visible():
                    connect_btn.click()
                    connect_clicked = True
                    break
        except Exception:
            pass
        time.sleep(2)

    if not connect_clicked:
        # 最後の手段: 最初のConnectボタンを押す
        try:
            page.locator('button:has-text("Connect")').first.click()
            connect_clicked = True
        except Exception:
            print("❌ リポジトリの Connect ボタンが見つかりませんでした。")
            print("   手動で line-warikan-bot リポジトリを選択してください。")
            input("   選択したら Enter を押してください...")

    time.sleep(3)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    print("⚙️ サービス設定を入力中...")

    # サービス名を設定
    try:
        name_input = page.locator('input[name="name"], input[id="name"]').first
        if name_input.is_visible():
            name_input.clear()
            name_input.fill(SERVICE_NAME)
    except Exception:
        pass

    # Region を選択 (Singapore が近い)
    try:
        region_select = page.locator('text=Region').first
        if region_select.is_visible():
            region_select.click()
            time.sleep(1)
            singapore = page.locator('text=Singapore').first
            if singapore.is_visible():
                singapore.click()
    except Exception:
        pass

    # Build Command
    try:
        build_input = page.locator('input[name*="build"], label:has-text("Build Command") + * input, label:has-text("Build Command") ~ input').first
        if build_input.is_visible():
            build_input.clear()
            build_input.fill(BUILD_CMD)
    except Exception:
        pass

    # Start Command
    try:
        start_input = page.locator('input[name*="start"], label:has-text("Start Command") + * input, label:has-text("Start Command") ~ input').first
        if start_input.is_visible():
            start_input.clear()
            start_input.fill(START_CMD)
    except Exception:
        pass

    # Instance Type: Free を選択
    try:
        free_option = page.locator('text=Free').first
        if free_option.is_visible():
            free_option.click()
    except Exception:
        pass

    time.sleep(1)
    print("📝 設定内容を確認してください。")
    print(f"   Name: {SERVICE_NAME}")
    print(f"   Build: {BUILD_CMD}")
    print(f"   Start: {START_CMD}")
    print("")
    print("⚠️  環境変数 (LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN) は")
    print("   サービス作成後にダッシュボードの Environment タブで設定してください。")
    print("")

    # Create Web Service ボタンをクリック
    input("設定を確認したら Enter を押してデプロイを開始します...")

    try:
        deploy_btn = page.locator('button:has-text("Create Web Service"), button:has-text("Deploy")').first
        deploy_btn.click()
        print("🚀 デプロイを開始しました!")
    except Exception:
        print("⚠️ Create ボタンを自動クリックできませんでした。手動でクリックしてください。")

    # デプロイ完了を待つ
    print("\n⏳ デプロイ中... (数分かかることがあります)")
    time.sleep(5)

    # URLを取得
    try:
        page.wait_for_load_state("networkidle")
        current_url = page.url
        print(f"\n📋 ダッシュボード: {current_url}")

        # .onrender.com のURLを探す
        onrender_link = page.locator('a[href*=".onrender.com"]').first
        if onrender_link.is_visible():
            service_url = onrender_link.get_attribute("href")
            print(f"🌐 サービスURL: {service_url}")
            print(f"📌 Webhook URL: {service_url}/webhook")
            print("\n   ↑ この Webhook URL を LINE Developers の Webhook URL に設定してください")
    except Exception:
        pass

    print("\n✅ 完了! ブラウザは開いたままにしています。")
    print("   環境変数の設定を忘れずに行ってください。")
    input("   全て完了したら Enter を押して終了...")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Render ダッシュボードを開く
        page.goto("https://dashboard.render.com")
        page.wait_for_load_state("networkidle")

        # ログイン待ち
        wait_for_login(page)

        # サービス作成
        create_web_service(page)

        browser.close()


if __name__ == "__main__":
    main()
