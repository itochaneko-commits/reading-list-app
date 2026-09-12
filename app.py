# -*- coding: utf-8 -*-
"""
読みたい本探し（MVP）

3つの画面を切り替えて使うStreamlitアプリ。
  1. 🔍 本を検索 — ホーム画面。本を探し、読書リストへ追加できる。
  2. 📖 読書リスト — 追加した本の一覧。近隣図書館の蔵書状況とAmazon/メルカリの検索リンクを表示。
  3. 🕘 検索履歴 — これまでの検索キーワードの履歴。ワンクリックで再検索できる。

起動方法:
    pip install -r requirements.txt
    streamlit run app.py
"""

from datetime import datetime

import streamlit as st

from book_search import BookSearchError, search_books
from calil_client import CALIL_APPKEY, fetch_availability
from links import amazon_search_url, mercari_search_url, nakano_library_search_url

NAKANO_LIBRARY_NAME = "中野区立中央図書館"

st.set_page_config(
    page_title="読みたい本探し",
    page_icon="📚",
    layout="wide",
    # スマホ幅で開くとサイドバーがメイン画面を覆ってしまうため、初期状態は閉じておく
    initial_sidebar_state="collapsed",
)

# --- ポップな水色ベースの見た目にするための追加CSS ---
# 配色そのものは .streamlit/config.toml のテーマ設定が主役。ここではボタンの形や
# バッジ・カード周りのアクセントだけ足す（Streamlit内部DOMへの依存を最小限にするため）。
st.markdown(
    """
    <style>
    .stButton > button, .stLinkButton > a, .stFormSubmitButton > button {
        border-radius: 999px !important;
        font-weight: 700 !important;
        border: none !important;
    }
    .stTextInput input {
        border-radius: 16px !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 20px !important;
    }
    .status-pill {
        display: inline-block;
        padding: 4px 14px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.9rem;
    }
    .nakano-header {
        background: linear-gradient(90deg, #00B4D8 0%, #48CAE4 60%, #90E0EF 100%);
        padding: 14px 20px;
        border-radius: 18px;
        color: white;
        margin-bottom: 14px;
    }
    .nakano-header h1 {
        color: white !important;
        margin: 0 0 4px 0 !important;
        font-size: 1.4rem !important;
        line-height: 1.3 !important;
    }
    .nakano-header p {
        margin: 0 !important;
        opacity: 0.95;
        font-size: 0.85rem;
    }
    /* さらに狭い画面ではもう一段小さく */
    @media (max-width: 480px) {
        .nakano-header h1 {
            font-size: 1.15rem !important;
        }
        .nakano-header p {
            font-size: 0.78rem;
        }
    }
    /* Amazon/メルカリを横並びにするための行。st.columnsはスマホ幅だと
       自動的に縦積みになってしまうため、素のHTMLリンクをflexで並べている。 */
    .shop-row {
        display: flex;
        gap: 8px;
        margin-top: 6px;
    }
    .shop-btn {
        flex: 1;
        text-align: center;
        padding: 8px 10px;
        border-radius: 999px;
        background: white;
        border: 1px solid #B6E4F5;
        color: #0B3B5A !important;
        font-weight: 700;
        font-size: 0.85rem;
        text-decoration: none !important;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .shop-btn:hover {
        background: #EAF9FF;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

STATUS_STYLE = {
    "貸出可": ("🟢 貸出可", "#DFF7E3", "#1B8A5A"),
    "貸出中": ("🟡 貸出中", "#FFF3D6", "#9A6B00"),
    "予約中": ("🔵 予約中", "#DDF4FF", "#0B72B9"),
    "蔵書なし": ("🔴 蔵書なし", "#FFE3E7", "#C0392B"),
}


def render_status_pill(status: str) -> str:
    for key, (label, bg, fg) in STATUS_STYLE.items():
        if status.startswith(key):
            # 実APIモードでは "貸出中（本館）" のように分館名が付くことがあるので保持する
            suffix = status[len(key):]
            return f'<span class="status-pill" style="background:{bg};color:{fg};">{label}{suffix}</span>'
    return status


# --- セッション状態の初期化 ---
if "reading_list" not in st.session_state:
    st.session_state.reading_list = []  # 検索結果から追加していく形にするため、初期状態は空
if "search_history" not in st.session_state:
    st.session_state.search_history = []  # [{"query", "count", "time"}]
if "page" not in st.session_state:
    st.session_state.page = "search"  # ホーム画面は検索
if "search_query_input" not in st.session_state:
    st.session_state.search_query_input = ""
if "cached_query" not in st.session_state:
    st.session_state.cached_query = None


def go_to(page_name: str, prefill_query: str | None = None) -> None:
    st.session_state.page = page_name
    if prefill_query is not None:
        st.session_state.search_query_input = prefill_query
        st.session_state.cached_query = None  # 再検索させる
    st.rerun()


def is_in_reading_list(isbn13: str) -> bool:
    return any(b.isbn13 == isbn13 for b in st.session_state.reading_list)


def add_to_reading_list(book) -> None:
    if not is_in_reading_list(book.isbn13):
        st.session_state.reading_list.append(book)
        st.toast(f"「{book.title}」を読書リストに追加しました", icon="📚")
    else:
        st.toast(f"「{book.title}」は既に読書リストにあります", icon="ℹ️")


def remove_from_reading_list(isbn13: str, title: str) -> None:
    st.session_state.reading_list = [b for b in st.session_state.reading_list if b.isbn13 != isbn13]
    st.toast(f"「{title}」を読書リストから削除しました", icon="🗑")


st.markdown(
    """
    <div class="nakano-header">
        <h1>📚 読みたい本探し</h1>
        <p>本を検索して読書リストに追加。中野区立中央図書館の貸出状況とAmazon/メルカリの検索リンクをまとめてチェック。</p>
    </div>
    """,
    unsafe_allow_html=True,
)

nav_labels = {
    "search": "🔍 本を検索",
    "reading_list": f"📖 読書リスト（{len(st.session_state.reading_list)}）",
    "history": f"🕘 検索履歴（{len(st.session_state.search_history)}）",
}
nav_cols = st.columns(3)
for col, (page_key, label) in zip(nav_cols, nav_labels.items()):
    with col:
        if st.button(
            label,
            use_container_width=True,
            type="primary" if st.session_state.page == page_key else "secondary",
        ):
            go_to(page_key)

if not CALIL_APPKEY:
    st.warning(
        "⚠️ 蔵書状況・予約待ち人数は**すべてダミー（モック）データ**です。実際の中野区立中央図書館の"
        "予約状況とは一致しません（人気の本は実際には数百人待ちのこともあります）。"
        "正確な状況は「予約ページへ」から公式サイトでご確認ください。実際のデータを使うには"
        "サイドバーの案内に沿って `CALIL_APPKEY` を設定してください。"
    )

st.divider()

with st.sidebar:
    st.header("設定")
    if CALIL_APPKEY:
        st.success("カーリルAPI: 実APIモード（CALIL_APPKEY 設定済み）")
    else:
        st.warning("カーリルAPI: モックモード\n\n"
                    "環境変数 CALIL_APPKEY を設定すると実際のカーリルAPIを呼び出します。")
    st.divider()
    st.caption(f"読書リスト件数: {len(st.session_state.reading_list)} 冊")
    st.caption(f"検索履歴件数: {len(st.session_state.search_history)} 件")


def render_book_card(book, availability, *, action: str | None) -> None:
    """action: "add"（読書リストに追加）/ "remove"（読書リストから削除）/ None（なし）

    スマホ幅では st.columns が縦積みになるため、左右2カラムのレイアウト
    （情報｜ボタン）は「情報が全部並んだ後にボタンが全部並ぶ」だけになり、
    しかも図書館ごとの見出し・名前・バッジが別々の行になって非常に縦長になっていた。
    図書館は1館しかないので、名前とバッジを1行にまとめている。
    Amazon/メルカリのボタンは st.columns だとスマホ幅で縦積みになってしまうため、
    素のHTML（.shop-row）をflexで横並びにして1行に収めている。
    """
    with st.container(border=True):
        st.markdown(f"**{book.title}**")
        st.caption(book.author)

        for lib in availability:
            st.markdown(
                f"📍 {lib.library_name}　{render_status_pill(lib.status)}",
                unsafe_allow_html=True,
            )
            # 待ち人数はステータス文字列（貸出可/貸出中）とは別に管理されているため、
            # ステータスに関わらず waiting_count があれば表示する
            # （例: 「貸出中」なのに5人予約待ち、ということが実際にある）。
            # 0人待ちも意味のある値なので、Noneとの比較で判定する
            # （if lib.waiting_count: だと 0 が偽として扱われ表示が消えてしまう）。
            meta_bits = []
            if lib.waiting_count is not None:
                meta_bits.append(f"🔵 現在{lib.waiting_count}人予約待ち")
            if lib.reserve_url:
                meta_bits.append(f"[予約ページへ]({nakano_library_search_url()})")
            if meta_bits:
                st.caption(" ・ ".join(meta_bits))

        if action == "add":
            already = is_in_reading_list(book.isbn13)
            if st.button(
                "✅ 追加済み" if already else "📚 読書リストに追加",
                key=f"add-{book.isbn13}",
                disabled=already,
                use_container_width=True,
            ):
                add_to_reading_list(book)
                st.rerun()
        elif action == "remove":
            if st.button(
                "🗑 読書リストから削除",
                key=f"remove-{book.isbn13}",
                use_container_width=True,
            ):
                remove_from_reading_list(book.isbn13, book.title)
                st.rerun()

        st.markdown(
            f"""
            <div class="shop-row">
                <a class="shop-btn" href="{amazon_search_url(book.title, book.author)}" target="_blank" rel="noopener">🛒 Amazon</a>
                <a class="shop-btn" href="{mercari_search_url(book.title)}" target="_blank" rel="noopener">📦 メルカリ</a>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_book_list(books, *, action: str | None) -> None:
    if not books:
        return
    availability_by_book = [(b, fetch_availability(b.isbn13)) for b in books]
    reserved_count = sum(
        1
        for _, availability in availability_by_book
        for lib in availability
        if lib.library_name == NAKANO_LIBRARY_NAME and lib.waiting_count
    )
    st.caption(f"🔵 {NAKANO_LIBRARY_NAME}で予約待ちがある本: {reserved_count} / {len(books)} 冊")
    for book, availability in availability_by_book:
        render_book_card(book, availability, action=action)


# ============================================================
# 画面: 🔍 本を検索（ホーム）
# ============================================================
if st.session_state.page == "search":
    st.subheader("🔍 本を検索")

    # text_inputを単体で使うとEnterキーが確実にサーバーへ送信されず、
    # 「新しいキーワードを打ったのに前の検索結果が残る」ように見えることがあったため、
    # st.formで囲んでEnterキー・ボタンどちらでも確実に送信されるようにしている。
    with st.form("search_form"):
        col_search, col_button = st.columns([4, 1])
        with col_search:
            search_query = st.text_input(
                "本を検索（タイトル・著者など）",
                placeholder="例: 独学大全 / 村上春樹",
                help="読書リストに入っていない本も検索できます。見つかった本は「読書リストに追加」で追加できます。",
                key="search_query_input",
                label_visibility="collapsed",
            )
        with col_button:
            st.form_submit_button("🔍 検索する", use_container_width=True)

    # 検索結果は st.empty() のプレースホルダーにまとめて描画する。
    # 実APIモードでは1冊ごとの蔵書状況取得に数秒かかることがあり、直接書いていくと
    # 「新しい検索結果を上から描画している途中で、まだ上書きされていない前回検索分の
    # カードが下の方に残って見える」状態になってしまうため、いったん何も表示しない
    # 状態にしてから新しい内容をまとめて差し替えることで、前の本が混ざって見えるのを防ぐ。
    results_area = st.empty()

    if search_query:
        is_new_query = st.session_state.cached_query != search_query
        if is_new_query:
            results_area.empty()
            try:
                with st.spinner("検索中..."):
                    results = search_books(search_query)
                error = False
            except BookSearchError:
                results = []
                error = True
            st.session_state.cached_query = search_query
            st.session_state.cached_results = results
            st.session_state.cached_error = error
            if not error:
                st.session_state.search_history.append(
                    {"query": search_query, "count": len(results), "time": datetime.now()}
                )
        else:
            results = st.session_state.cached_results
            error = st.session_state.cached_error

        with results_area.container():
            if error:
                st.error("本の検索に失敗しました。ネットワーク接続を確認して、もう一度お試しください。")
            else:
                st.markdown(f"### 「{search_query}」の検索結果: {len(results)} 件")
                if not results:
                    st.info("該当する本が見つかりませんでした。別のキーワードでお試しください。")
                if is_new_query:
                    with st.spinner("図書館の蔵書状況を取得中..."):
                        render_book_list(results, action="add")
                else:
                    render_book_list(results, action="add")
    else:
        results_area.empty()
        st.info("キーワードを入力して本を検索してください。見つかった本は読書リストに追加できます。")

# ============================================================
# 画面: 📖 読書リスト
# ============================================================
elif st.session_state.page == "reading_list":
    st.subheader(f"📖 読書リスト（{len(st.session_state.reading_list)} 冊）")
    if not st.session_state.reading_list:
        st.info("読書リストはまだ空です。「🔍 本を検索」から本を追加してみましょう。")
    else:
        render_book_list(st.session_state.reading_list, action="remove")

# ============================================================
# 画面: 🕘 検索履歴
# ============================================================
elif st.session_state.page == "history":
    st.subheader(f"🕘 検索履歴（{len(st.session_state.search_history)} 件）")
    if st.session_state.search_history:
        if st.button("🗑 履歴をすべて削除", use_container_width=True):
            st.session_state.search_history = []
            st.rerun()

    if not st.session_state.search_history:
        st.info("まだ検索履歴がありません。「🔍 本を検索」から本を探してみましょう。")
    else:
        history = st.session_state.search_history
        for display_i, entry in enumerate(reversed(history)):
            original_i = len(history) - 1 - display_i
            with st.container(border=True):
                st.markdown(f"**{entry['query']}**")
                st.caption(f"{entry['count']} 件 ・ {entry['time'].strftime('%Y-%m-%d %H:%M:%S')}")
                col_redo, col_delete = st.columns(2)
                with col_redo:
                    if st.button("🔁 再検索", key=f"redo-{original_i}", use_container_width=True):
                        go_to("search", prefill_query=entry["query"])
                with col_delete:
                    if st.button("🗑 削除", key=f"del-hist-{original_i}", use_container_width=True):
                        st.session_state.search_history.pop(original_i)
                        st.rerun()

st.divider()
if CALIL_APPKEY:
    st.caption(
        "※ 実際のカーリルAPI（https://calil.jp/doc/api_ref.html）から取得した蔵書状況を表示しています。"
    )
else:
    st.caption(
        "※ 現在は蔵書状況がモックデータです。実際のカーリルAPI（https://calil.jp/doc/api_ref.html）を"
        "使うには CALIL_APPKEY を取得し環境変数に設定してください。詳細は calil_client.py 内のコメントを参照。"
    )
