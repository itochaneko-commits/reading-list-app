# -*- coding: utf-8 -*-
"""
モックデータ定義

本来は自分の「読書リスト」を管理しているサービス（例：Notion, スプレッドシート,
読書メーターのエクスポートなど）から取得する想定だが、MVPでは固定のモックデータを使う。

各書籍は最低限 ISBN13 を持たせる。カーリルAPIはISBNをキーに蔵書照会するため。
"""

from dataclasses import dataclass


@dataclass
class Book:
    title: str
    author: str
    isbn13: str  # カーリルAPI / Amazon検索などで利用


# 自分の読書リスト（モック）
READING_LIST: list[Book] = [
    Book(
        title="独学大全",
        author="読書猿",
        isbn13="9784478108536",
    ),
    Book(
        title="人を動かす",
        author="デール・カーネギー",
        isbn13="9784422100513",
    ),
    Book(
        title="ファクトフルネス",
        author="ハンス・ロスリング",
        isbn13="9784822289607",
    ),
    Book(
        title="LIFE SHIFT（ライフ・シフト）",
        author="リンダ・グラットン",
        isbn13="9784492533872",
    ),
    Book(
        title="嫌われる勇気",
        author="岸見一郎, 古賀史健",
        isbn13="9784478025819",
    ),
]


# 蔵書照会の対象図書館（カーリルAPIでいう "systemid" に相当）
# 中野区立図書館の systemid は "Tokyo_Nakano"（全分館共通。中央図書館の分館別状況は
# calil_client.py 側で libkey から「中央」を含む分館名を探して表示する）
MOCK_LIBRARY_SYSTEMS = [
    {"systemid": "Tokyo_Nakano", "name": "中野区立中央図書館"},
]
