# 読書リスト × 図書館蔵書 × 通販検索リンク（MVP）

自分の読書リストの本について、①中野区立中央図書館の蔵書状況（カーリルAPI）と②Amazon / メルカリの検索リンクを一覧表示するStreamlitアプリのMVPです。現状はすべてモックデータ・モックAPIで動作します。

## ファイル構成

- `app.py` — Streamlitアプリ本体（UI、画面切り替え）
- `mock_data.py` — 読書リストの初期データと図書館システムのモックデータ
- `calil_client.py` — カーリルAPI連携（現在はモック関数。`CALIL_APPKEY`環境変数を設定すると実APIに切り替わる）
- `book_search.py` — OpenLibrary + NDLサーチを組み合わせた本の検索（読書リストの5冊以外も検索可能）
- `links.py` — Amazon / メルカリ / 中野区立図書館の検索URL生成
- `.streamlit/config.toml` — 配色テーマ（水色ベース）
- `requirements.txt` — 依存パッケージ

## 実行方法

```bash
pip install -r requirements.txt
streamlit run app.py
```

ブラウザで `http://localhost:8501` が開きます。3つの画面を上部のボタンで切り替えます。

- **🔍 本を検索**（ホーム画面） — キーワードで本を検索し、見つかった本を「📚 読書リストに追加」ボタンで読書リストに追加できます。
- **📖 読書リスト** — 追加した本の一覧。中野区立中央図書館の蔵書状況・Amazon/メルカリの検索リンクを表示します。
- **🕘 検索履歴** — これまでの検索キーワードの履歴。「🔁 再検索」でワンクリックで検索画面に戻れます。

読書リストと検索履歴はブラウザのセッション内でのみ保持されます（サーバーを再起動するとリセットされます）。永続化したい場合は「次のステップ」を参照してください。

## 本の検索について（book_search.py）

- OpenLibrary（海外の翻訳ベストセラーなどに強い）と国立国会図書館サーチ（日本国内出版物の網羅性が高い）の2つを両方検索し、ISBN13で重複排除しながら結果を合成しています。どちらか一方だけでは取りこぼしがある（例: 「嫌われる勇気」はOpenLibrary単体だと日本語版ISBNが登録されておらず0件になる）ため、この構成にしています。
- カーリルAPIでの蔵書照会にはISBN13が必須のため、日本語版のISBN13（`9784`から始まるもの）を持つ本だけを結果に含めています。
- 検索先が両方とも通信エラーになった場合のみ「本の検索に失敗しました」と表示します。片方だけ失敗した場合はもう片方の結果をそのまま表示します。

## モックデータの中身

- `mock_data.py` に5冊のダミー読書リストを用意しています。ここを自分の実際のリストに差し替えてください。
- `calil_client.py` のモックは、書籍のISBNと図書館IDから決定論的な擬似乱数で「貸出可 / 貸出中 / 蔵書なし」を生成します（同じ本・同じ図書館なら毎回同じ結果になります）。

## 次のステップ（実装を進める場合）

1. **カーリルAPIキーの取得**
   https://calil.jp/api/dashboard/ からAPIキーを申請し、環境変数 `CALIL_APPKEY` にセットすると `calil_client.py` の `fetch_availability_real()` が自動的に使われます。
   ```bash
   export CALIL_APPKEY="あなたのAPIキー"
   ```
2. **図書館のsystemidを確認する**
   `mock_data.py` の `MOCK_LIBRARY_SYSTEMS` は中野区立図書館（systemid: `Tokyo_Nakano`）に設定済みです。他の自治体を追加・変更したい場合は https://calil.jp/library/ で自治体名を検索してsystemidを調べてください。
3. **読書リストの取得元を実データに接続**
   Notion API、Googleスプレッドシート、読書メーターのエクスポートCSVなど、実際に使っているサービスに合わせて `mock_data.py` の代わりにデータ取得処理を実装します。
4. **カーリルAPIの非同期仕様に注意**
   カーリルAPIは「まずリクエスト→session発行→数秒後に同じsessionでポーリング」という非同期方式です。`fetch_availability_real()` に簡易的なポーリング実装を入れていますが、複数冊を同時にチェックする場合はISBNをまとめて1回のリクエストで送る（`isbn=` にカンマ区切りで複数指定できる）方が高速です。
5. **Amazon / メルカリの正式なAPI化（任意）**
   現状は検索リンク（URL）を生成するだけです。実際の在庫・価格を取得したい場合は、Amazon PA-APIやメルカリの提供APIの利用申請が必要になります（利用規約・審査あり）。
6. **読書リスト・検索履歴の永続化**
   現状は `st.session_state` にのみ保持しており、サーバー再起動やブラウザを変えるとリセットされます。永続化したい場合は、SQLiteやNotion APIなどに保存する処理を `add_to_reading_list()` 周りに追加してください。

## 補足: FastAPIで作りたい場合

今回はUIがそのまま画面になるStreamlit版をMVPとして作成しました。バックエンドAPIとフロントエンドを分離したい場合は、`calil_client.py` / `links.py` / `mock_data.py` はそのまま流用でき、`app.py` の代わりにFastAPIで以下のようなエンドポイントを作る形になります。

```python
from fastapi import FastAPI
from mock_data import READING_LIST
from calil_client import fetch_availability
from links import amazon_search_url, mercari_search_url

app = FastAPI()

@app.get("/books")
def list_books():
    return [
        {
            "title": b.title,
            "author": b.author,
            "isbn13": b.isbn13,
            "libraries": [a.__dict__ for a in fetch_availability(b.isbn13)],
            "amazon_url": amazon_search_url(b.title, b.author),
            "mercari_url": mercari_search_url(b.title),
        }
        for b in READING_LIST
    ]
```

フロント側（React等）やJinja2テンプレートから `/books` を呼び出す形にすれば、同じロジックを再利用できます。
