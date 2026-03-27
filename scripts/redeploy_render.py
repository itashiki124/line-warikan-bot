"""既存の Render サービスにデプロイをトリガーする"""
import sys
import time
from playwright.sync_api import sync_playwright


SERVICE_URL = "https://dashboard.render.com/web/srv-d72ih5n5r7bs7386dl9g"


def main():
    with sync_playwright() as p:
        # ユーザーデータディレクトリを使って既存のセッションを保持
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # サービスページに直接アクセス
        print(f"🌐 サービスページにアクセス中...")
        page.goto(SERVICE_URL)
        page.wait_for_load_state("networkidle")
        time.sleep(3)

        # ログインが必要かチェック
        if "/login" in page.url or "Sign In" in page.content():
            print("🔑 Render にログインしてください...")
            print("   ブラウザでログインしたら自動的に進みます。")
            while "/login" in page.url or "/register" in page.url:
                time.sleep(2)
            # ログイン後にサービスページに再アクセス
            page.goto(SERVICE_URL)
            page.wait_for_load_state("networkidle")
            time.sleep(3)

        print("✅ サービスページにアクセスしました")

        # ページの情報を取得
        title = page.title()
        print(f"📄 ページタイトル: {title}")

        # 現在のページのテキストを取得して状態を確認
        body_text = page.inner_text("body")
        print(f"\n📝 ページ内容 (先頭500文字):")
        print(body_text[:500])
        print("...")

        # Manual Deploy ボタンを探す
        print("\n🔍 デプロイボタンを探しています...")

        # "Manual Deploy" または "Deploy" ボタンを探す
        deploy_triggered = False

        # 方法1: Manual Deploy ドロップダウン
        try:
            manual_deploy = page.locator('button:has-text("Manual Deploy")').first
            if manual_deploy.is_visible(timeout=3000):
                print("📦 Manual Deploy ボタン発見!")
                manual_deploy.click()
                time.sleep(1)

                # "Deploy latest commit" を選択
                deploy_latest = page.locator('text=Deploy latest commit').first
                if deploy_latest.is_visible(timeout=3000):
                    deploy_latest.click()
                    deploy_triggered = True
                    print("🚀 最新コミットのデプロイをトリガーしました!")

                # "Clear build cache & deploy" でも良い
                if not deploy_triggered:
                    clear_deploy = page.locator('text=Clear build cache').first
                    if clear_deploy.is_visible(timeout=2000):
                        clear_deploy.click()
                        deploy_triggered = True
                        print("🚀 キャッシュクリア&デプロイをトリガーしました!")
        except Exception as e:
            print(f"  Manual Deploy ボタンが見つかりません: {e}")

        # 方法2: Events タブの Deploy / Redeploy
        if not deploy_triggered:
            try:
                # ページ上の全ボタンを列挙
                buttons = page.locator("button")
                count = buttons.count()
                print(f"\n🔍 ページ上のボタン ({count}個):")
                for i in range(min(count, 20)):
                    btn = buttons.nth(i)
                    try:
                        text = btn.inner_text(timeout=1000)
                        if text.strip():
                            print(f"  - [{i}] {text.strip()[:50]}")
                    except Exception:
                        pass
            except Exception as e:
                print(f"  ボタン列挙エラー: {e}")

        # 方法3: ナビゲーション内のリンク
        if not deploy_triggered:
            try:
                links = page.locator("a")
                count = links.count()
                print(f"\n🔍 主要リンク:")
                for i in range(min(count, 30)):
                    link = links.nth(i)
                    try:
                        text = link.inner_text(timeout=1000)
                        href = link.get_attribute("href") or ""
                        if text.strip() and ("deploy" in text.lower() or "deploy" in href.lower()):
                            print(f"  - {text.strip()} -> {href}")
                    except Exception:
                        pass
            except Exception:
                pass

        if not deploy_triggered:
            print("\n⚠️ 自動デプロイのトリガーができませんでした。")
            print("   ブラウザからManual Deploy → Deploy latest commit を手動で押してください。")

        # デプロイの状況を確認
        print("\n⏳ デプロイの状況を確認中...")
        time.sleep(5)

        # ログ/Eventsタブを確認
        try:
            events_tab = page.locator('a:has-text("Events"), button:has-text("Events")').first
            if events_tab.is_visible(timeout=3000):
                events_tab.click()
                time.sleep(3)
                events_text = page.inner_text("body")
                # 最新のデプロイ情報を取得
                lines = events_text.split("\n")
                deploy_lines = [l for l in lines if any(kw in l.lower() for kw in ["deploy", "live", "build", "failed"])]
                if deploy_lines:
                    print("\n📋 最新デプロイ情報:")
                    for line in deploy_lines[:5]:
                        print(f"  {line.strip()}")
        except Exception:
            pass

        # サービスURLを探す
        try:
            url_element = page.locator('a[href*=".onrender.com"]').first
            if url_element.is_visible(timeout=3000):
                service_url = url_element.get_attribute("href")
                print(f"\n🌐 サービスURL: {service_url}")
                print(f"📌 Webhook URL: {service_url}/webhook")
        except Exception:
            pass

        print("\n✅ ブラウザは開いたままです。確認が終わったら Enter で閉じます。")
        input()
        browser.close()


if __name__ == "__main__":
    main()
