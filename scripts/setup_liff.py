#!/usr/bin/env python3
"""
Playwright を使って LINE Developers Console で LIFF アプリを自動セットアップする。

使い方:
    python scripts/setup_liff.py https://your-domain.com

手動操作が必要な箇所:
    1. LINE アカウントでログイン
    2. プロバイダー / チャネル の選択
    (残りは自動で入力されます)
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, TimeoutError as PwTimeout

CONSOLE_URL = "https://developers.line.biz/console/"
DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"


# ── ユーティリティ ───────────────────────────────────

def _print_step(n: int, msg: str) -> None:
    print(f"\n{'='*50}")
    print(f"  Step {n}: {msg}")
    print(f"{'='*50}\n")


def _wait_for_console(page: Page) -> None:
    """ログイン完了してコンソールトップに到着するまで待つ"""
    print("⏳ LINE Developers Console のログイン待ち...")
    print("   ブラウザでログインしてください。ログイン完了まで待機します。\n")
    while True:
        if "/console/" in page.url and "login" not in page.url.lower():
            # コンソールページに到着
            break
        time.sleep(1)
    print("✅ ログイン完了！\n")


def _update_env(liff_id: str) -> None:
    """LIFF_ID を .env ファイルに書き込む（既存なら上書き）"""
    env_path = DOTENV_PATH
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        if re.search(r"^LIFF_ID=", content, re.MULTILINE):
            content = re.sub(r"^LIFF_ID=.*$", f"LIFF_ID={liff_id}", content, flags=re.MULTILINE)
        else:
            content = content.rstrip("\n") + f"\nLIFF_ID={liff_id}\n"
        env_path.write_text(content, encoding="utf-8")
    else:
        env_path.write_text(f"LIFF_ID={liff_id}\n", encoding="utf-8")
    print(f"📝 .env に LIFF_ID={liff_id} を書き込みました")


# ── メイン処理 ────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="LIFF アプリを LINE Developers Console で自動セットアップ")
    parser.add_argument("endpoint_url", help="LIFF エンドポイント URL (例: https://your-app.fly.dev)")
    parser.add_argument("--size", choices=["full", "tall", "compact"], default="full",
                        help="LIFF 画面サイズ (default: full)")
    args = parser.parse_args()

    endpoint_url = args.endpoint_url.rstrip("/")
    if not endpoint_url.startswith("https://"):
        print("❌ エンドポイント URL は https:// で始まる必要があります")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="ja-JP")
        page = context.new_page()

        # ── Step 1: ログイン ──
        _print_step(1, "LINE Developers Console にログイン")
        page.goto(CONSOLE_URL)
        page.wait_for_load_state("networkidle")

        # すでにログイン済みならスキップ
        if "login" in page.url.lower() or "/console/" not in page.url:
            _wait_for_console(page)
        else:
            print("✅ すでにログイン済みです\n")

        # ── Step 2: チャネル選択 ──
        _print_step(2, "チャネルを選択")
        print("📋 ブラウザで以下の操作をしてください:")
        print("   1. プロバイダーを選択")
        print("   2. Messaging API チャネル を選択")
        print("   3. チャネルの詳細画面が表示されたら、ここに戻って Enter を押してください\n")
        input("   👉 チャネル詳細画面を開いたら Enter キーを押してください... ")

        # チャネルページにいることを確認
        channel_url = page.url
        print(f"   現在のURL: {channel_url}\n")

        # ── Step 3: LIFF タブに移動 ──
        _print_step(3, "LIFF タブへ移動して LIFF アプリを追加")

        # LIFF タブをクリック
        try:
            liff_tab = page.locator("text=LIFF").first
            liff_tab.click()
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            print("✅ LIFF タブを開きました\n")
        except PwTimeout:
            print("⚠️  LIFF タブが見つかりません。手動で LIFF タブをクリックしてください。")
            input("   👉 LIFF タブを開いたら Enter キーを押してください... ")

        # 「追加」ボタンをクリック
        try:
            add_btn = page.locator("button:has-text('追加'), button:has-text('Add')").first
            add_btn.click()
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            print("✅ 「追加」ボタンをクリックしました\n")
        except PwTimeout:
            print("⚠️  「追加」ボタンが見つかりません。手動でクリックしてください。")
            input("   👉 LIFF追加フォームが開いたら Enter キーを押してください... ")

        # ── Step 4: フォーム入力 ──
        _print_step(4, "LIFF フォームを自動入力")

        # サイズ選択
        size_label_map = {"full": "Full", "tall": "Tall", "compact": "Compact"}
        size_label = size_label_map[args.size]
        try:
            size_option = page.locator(f"text={size_label}").first
            size_option.click()
            time.sleep(0.5)
            print(f"   📐 サイズ: {size_label}")
        except PwTimeout:
            print(f"   ⚠️  サイズ「{size_label}」の自動選択に失敗。手動で選択してください。")

        # エンドポイント URL 入力
        try:
            # URL入力欄を探す (placeholder や label で特定)
            url_input = page.locator(
                'input[placeholder*="https://"], '
                'input[name*="url"], '
                'input[name*="endpoint"]'
            ).first
            url_input.fill(endpoint_url)
            time.sleep(0.5)
            print(f"   🔗 エンドポイント URL: {endpoint_url}")
        except PwTimeout:
            print(f"   ⚠️  URL入力欄の自動入力に失敗。手動で入力してください: {endpoint_url}")

        # Scope (openid にチェック)
        try:
            openid_checkbox = page.locator("text=openid").first
            openid_checkbox.click()
            time.sleep(0.3)
            print("   🔑 Scope: openid ✓")
        except (PwTimeout, Exception):
            print("   ℹ️  openid scope は手動で設定してください")

        print(f"\n📋 入力内容を確認してください:")
        print(f"   サイズ: {size_label}")
        print(f"   URL:    {endpoint_url}")
        print(f"   Scope:  openid")
        print()

        # ── Step 5: 作成を確定 ──
        _print_step(5, "LIFF アプリを作成")
        input("   👉 内容を確認したら Enter を押してください（「追加」ボタンをクリックします）... ")

        try:
            # フォーム下部の追加/作成ボタン
            submit_btn = page.locator(
                "button:has-text('追加'), "
                "button:has-text('Add'), "
                "button[type='submit']"
            ).last
            submit_btn.click()
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            print("✅ 作成リクエストを送信しました\n")
        except PwTimeout:
            print("⚠️  自動クリックに失敗。手動で「追加」ボタンをクリックしてください。")
            input("   👉 LIFF アプリが作成されたら Enter を押してください... ")

        # ── Step 6: LIFF ID を取得 ──
        _print_step(6, "LIFF ID を取得")
        time.sleep(2)

        liff_id = None

        # ページ内から LIFF ID を探す
        # LIFF ID は通常 "xxxx-yyyy" 形式 (数字とハイフン)
        try:
            page_text = page.inner_text("body")
            # LIFF ID パターン: 数字-英数字 (例: 1234567890-abcdefgh)
            matches = re.findall(r"\b(\d{7,10}-[a-zA-Z0-9]{6,10})\b", page_text)
            if matches:
                liff_id = matches[0]
                print(f"🎉 LIFF ID を検出: {liff_id}")
        except Exception:
            pass

        if not liff_id:
            print("⚠️  LIFF ID を自動検出できませんでした。")
            print("   ブラウザに表示されている LIFF ID をコピーしてください。")
            liff_id = input("   👉 LIFF ID を入力: ").strip()

        if not liff_id:
            print("❌ LIFF ID が空です。手動で .env に設定してください。")
            browser.close()
            sys.exit(1)

        # ── Step 7: .env に書き込み ──
        _print_step(7, ".env に LIFF_ID を保存")
        _update_env(liff_id)

        print()
        print("🎉 セットアップ完了！")
        print(f"   LIFF ID: {liff_id}")
        print(f"   LIFF URL: https://liff.line.me/{liff_id}")
        print()
        print("📌 次のステップ:")
        print("   1. ボットを再デプロイしてください")
        print("   2. LINE トーク画面で「ヘルプ」と送信して動作確認")
        print()

        input("Enter を押すとブラウザを閉じます... ")
        browser.close()


if __name__ == "__main__":
    main()
