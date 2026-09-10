# -*- coding: utf-8 -*-
"""
Amazon / メルカリ / 中野区立図書館の検索リンク生成モジュール

MVPでは各サービスの公式APIは使わず、検索クエリURLを組み立てるだけにする。
（Amazon PA-APIやメルカリのAPIは審査・利用条件があるため、後で必要になれば差し替える）
"""

from urllib.parse import quote_plus

# 中野区立図書館の蔵書検索（簡単検索）ページ。
# このサイトは検索も書誌詳細もセッション付きのPOST送信で動いており、
# 「このURLを開けば自動でこの本の検索結果が表示される」というGETリンクを
# 組み立てることができなかったため、キーワード入力欄があるトップページに留めている。
# （usermenu.do の予約ページから辿るより1クリック少なくなる）
NAKANO_LIBRARY_SEARCH_URL = "https://www.kn.licsre-saas.jp/tokyo-nakano/webopac/index.do?target=adult"


def amazon_search_url(title: str, author: str | None = None) -> str:
    query = title if not author else f"{title} {author}"
    return f"https://www.amazon.co.jp/s?k={quote_plus(query)}&i=stripbooks"


def mercari_search_url(title: str) -> str:
    # メルカリはタイトルのみで検索した方がヒットしやすいことが多い
    return f"https://jp.mercari.com/search?keyword={quote_plus(title)}"


def nakano_library_search_url() -> str:
    return NAKANO_LIBRARY_SEARCH_URL
