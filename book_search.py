# -*- coding: utf-8 -*-
"""
書籍検索モジュール

自分の読書リスト（mock_data.READING_LIST）に入っていない本も検索できるように、
2つの無料・APIキー不要の検索先を組み合わせてキーワード検索する。

1. OpenLibrary (https://openlibrary.org/search.json)
   海外の翻訳ベストセラーなどにも強く、ヒットすれば1件だけ正確に返ることが多い。
   ただし「嫌われる勇気」のような日本発の本は、作品(work)に紐づくISBN一覧に
   日本語版ISBNが含まれていないことがあり、その場合は0件になってしまう。
2. NDLサーチ SRU API (https://ndlsearch.ndl.go.jp/api/sru)
   国立国会図書館の書誌データベース（dpid=iss-ndl-opac、雑誌記事等を除いた図書のみ）。
   日本国内で出版された本の網羅性はOpenLibraryより高いが、関連度順の並び替えが
   弱く、短い単語（「三体」「火花」など）ではノイズが混ざりやすい。また "title"
   フィールドだけでは「カフネ」のような最近の本を取りこぼすことがあるため、
   内容紹介文を検索する "description" フィールドにも問い合わせて補完している
   （新しいJSON API [ndlsearch.ndl.go.jp/api/bib/search] の方が精度は高いが、
   ブラウザセッション必須でサーバーサイドから直接は呼べないため未採用）。

そのため両方に問い合わせて結果をISBN13で重複排除しながら合成する
（OpenLibraryの結果を先に、NDLの結果を後に）。片方が失敗してももう片方の
結果は返す。両方とも失敗した場合のみ BookSearchError を送出する。

カーリルAPIでの蔵書照会にはISBN13が必須のため、ISBN13が取れない本は結果から除外する。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests

from mock_data import Book

OPENLIBRARY_SEARCH_API = "https://openlibrary.org/search.json"
NDL_SRU_API = "https://ndlsearch.ndl.go.jp/api/sru"

_JP_ISBN13_RE = re.compile(r"9784\d{9}")
_NORMALIZE_RE = re.compile(r"[\s・:：、,，.．\-－()（）\"'\[\]「」『』]")
_QUERY_SPLIT_RE = re.compile(r"[の、・]")


def _normalize(text: str) -> str:
    """比較用に空白・中点・括弧などの表記ゆれを取り除いて正規化する。"""
    return _NORMALIZE_RE.sub("", text).lower()


def _query_tokens(query: str) -> list[str]:
    """「福井至の認知行動療法ノート」のような複合クエリを意味の単位に分割する。

    最初の区切りだけで2分割する（maxsplit=1）。「死ぬことが決まっているのなら」の
    ように書名そのものに「の」が含まれる場合、全部の「の」で割ってしまうと
    書名が壊れてしまうため。
    """
    tokens = [t.strip() for t in _QUERY_SPLIT_RE.split(query, maxsplit=1) if len(t.strip()) >= 2]
    return tokens or [query]


def _matches_query(query: str, book: Book) -> bool:
    """タイトル＋著者名のどこかにクエリの各断片が含まれているかを見る。"""
    haystack = _normalize(book.title) + _normalize(book.author)
    return all(_normalize(token) in haystack for token in _query_tokens(query))

_SRW_NS = {"srw": "http://www.loc.gov/zing/srw/"}
_DC_NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}
_RDF_DATATYPE_ATTR = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}datatype"
_AUTHOR_SUFFIX_RE = re.compile(r"\s*(著|編著|編|訳|画|作|文)\s*$")
_AUTHOR_BRACKET_RE = re.compile(r"[\[［](著|編|訳|画|作|文)[\]］]")


class BookSearchError(Exception):
    """検索APIへの通信に失敗した場合に送出する（両方の検索先が失敗した場合のみ）。"""


def _pick_jp_isbn13(isbns: list[str]) -> str | None:
    return next((i for i in isbns if _JP_ISBN13_RE.fullmatch(i)), None)


def _clean_author(text: str | None) -> str:
    if not text:
        return "著者不明"
    text = _AUTHOR_BRACKET_RE.sub("", text)
    text = _AUTHOR_SUFFIX_RE.sub("", text)
    return text.strip().rstrip(",、").strip() or "著者不明"


def _search_openlibrary(query: str, max_results: int) -> list[Book]:
    """OpenLibraryで検索する。`q`は3文字未満だと422になるので`title`にフォールバックする。"""

    def _request(param_name: str) -> dict | None:
        params = {
            param_name: query,
            "limit": max_results,
            "fields": "title,author_name,isbn",
        }
        response = requests.get(OPENLIBRARY_SEARCH_API, params=params, timeout=10)
        if response.status_code == 422:
            return None
        response.raise_for_status()
        return response.json()

    data = _request("q")
    if data is None:
        data = _request("title")
    if data is None:
        return []

    results: list[Book] = []
    for doc in data.get("docs", []):
        title = doc.get("title")
        if not title:
            continue
        isbn13 = _pick_jp_isbn13(doc.get("isbn", []) or [])
        if not isbn13:
            continue  # 日本語版ISBNが見つからない本はカーリル照会ができないため除外
        authors = ", ".join(doc.get("author_name", []) or []) or "著者不明"
        results.append(Book(title=title, author=authors, isbn13=isbn13))
    return results


def _ndl_sru_request(cql: str, max_results: int) -> ET.Element:
    params = {
        "operation": "searchRetrieve",
        "version": "1.2",
        "query": cql,
        "recordSchema": "dcndl",
        "maximumRecords": max_results,
    }
    response = requests.get(NDL_SRU_API, params=params, timeout=15)
    response.raise_for_status()
    return ET.fromstring(response.content)


def _parse_ndl_records(root: ET.Element) -> list[Book]:
    results: list[Book] = []
    for record_data in root.findall(".//srw:recordData", _SRW_NS):
        if not record_data.text:
            continue
        try:
            inner = ET.fromstring(record_data.text)
        except ET.ParseError:
            continue

        title_el = inner.find(".//dcterms:title", _DC_NS)
        title = title_el.text.strip() if title_el is not None and title_el.text else None
        if not title:
            continue

        isbn13 = None
        for ident in inner.findall(".//dcterms:identifier", _DC_NS):
            datatype = ident.get(_RDF_DATATYPE_ATTR, "")
            if datatype.endswith("/ISBN") and ident.text:
                candidate = ident.text.replace("-", "").strip()
                if _JP_ISBN13_RE.fullmatch(candidate):
                    isbn13 = candidate
                    break
        if not isbn13:
            continue  # ISBN13が取れない（雑誌・古い資料など）は除外

        creator_el = inner.find(".//dc:creator", _DC_NS)
        author = _clean_author(creator_el.text if creator_el is not None else None)
        results.append(Book(title=title, author=author, isbn13=isbn13))
    return results


def _search_ndl(query: str, max_results: int) -> list[Book]:
    """NDLサーチ（国立国会図書館の図書データベースのみ）で検索する。

    "title"（タイトル）フィールドだけだと、短いタイトル（「カフネ」など）を
    正しく拾えないことがある一方、"description"（内容紹介・要約）フィールドは
    本文中にタイトルが登場することが多く、より確実に見つかることがあるため、
    両方のフィールドに問い合わせて合成する。
    さらに「福井至の認知行動療法ノート」のような「著者名の書名」という自然な
    検索フレーズは、1つの文字列としてタイトル/内容紹介を検索してもまず
    ヒットしないため、「の」「、」「・」で区切って複数の断片がある場合は
    最後の断片をタイトル、それより前を著者とみなした title+creator の
    組み合わせ検索も試す。
    """
    safe_query = query.replace('"', "")

    cql_queries = [
        f'title="{safe_query}" AND dpid=iss-ndl-opac',
        f'description="{safe_query}" AND dpid=iss-ndl-opac',
    ]
    tokens = _query_tokens(query)
    if len(tokens) >= 2:
        title_guess = tokens[-1].replace('"', "")
        creator_guess = "".join(tokens[:-1]).replace('"', "")
        cql_queries.append(
            f'title="{title_guess}" AND creator="{creator_guess}" AND dpid=iss-ndl-opac'
        )

    results_by_isbn: dict[str, Book] = {}
    any_success = False
    last_error: requests.RequestException | None = None
    for cql in cql_queries:
        try:
            root = _ndl_sru_request(cql, max_results)
            any_success = True
        except requests.RequestException as exc:
            last_error = exc
            continue
        for book in _parse_ndl_records(root):
            # NDLの検索は関連度順の絞り込みが弱く、検索語をまったく含まない
            # 無関係な本がヒットすることがあるため、念のためタイトルまたは
            # 著者名にクエリの各断片が含まれるものだけを残す。「ハリーポッター」と
            # 「ハリー・ポッター」のような中点や空白などの表記ゆれは無視して比較する。
            if not _matches_query(query, book):
                continue
            results_by_isbn.setdefault(book.isbn13, book)

    if not any_success and last_error is not None:
        # すべての問い合わせが失敗した場合のみ、NDLが使えなかったこととして
        # 呼び出し元（search_books）に伝える。
        raise last_error

    return list(results_by_isbn.values())[:max_results]


def search_books(query: str, max_results: int = 10) -> list[Book]:
    """OpenLibraryとNDLサーチを両方検索し、ISBN13で重複排除して合成した結果を返す。"""
    query = query.strip()
    if not query:
        return []

    openlibrary_results: list[Book] = []
    openlibrary_error: Exception | None = None
    try:
        openlibrary_results = _search_openlibrary(query, max_results)
    except requests.RequestException as exc:
        openlibrary_error = exc

    ndl_results: list[Book] = []
    ndl_error: Exception | None = None
    try:
        ndl_results = _search_ndl(query, max_results)
    except (requests.RequestException, ET.ParseError) as exc:
        ndl_error = exc

    if openlibrary_error is not None and ndl_error is not None:
        raise BookSearchError(f"{openlibrary_error} / {ndl_error}")

    merged: list[Book] = []
    seen_isbns: set[str] = set()
    for book in [*openlibrary_results, *ndl_results]:
        if book.isbn13 in seen_isbns:
            continue
        seen_isbns.add(book.isbn13)
        merged.append(book)
        if len(merged) >= max_results:
            break

    return merged
