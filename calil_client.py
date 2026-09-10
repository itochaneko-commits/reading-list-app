# -*- coding: utf-8 -*-
"""
カーリル図書館API連携モジュール

MVPの現段階ではAPIキーを使わず、決定論的な擬似乱数でモックの蔵書状況を返す。
CALIL_APPKEY 環境変数が設定されている場合は、実際のカーリルAPIを呼び出すモードに
自動で切り替わる（fetch_availability_real）。

--- 参考: カーリルAPIの実際の仕様（後で実装する際のメモ） ---
- エンドポイント: https://api.calil.jp/check
- パラメータ: appkey, isbn（カンマ区切り複数可）, systemid（カンマ区切り複数可）, format=json, callback=no
- カーリルAPIは非同期。1回目のリクエストで continue=1 かつ session が返ってきたら、
  数秒待って同じ session を付けて再度リクエストし、continue=0 になるまでポーリングする。
- レスポンス例:
    {
      "session": "...",
      "continue": 0,
      "books": {
        "9784478108536": {
          "Tokyo_Setagaya": {
            "status": "OK",
            "reserveurl": "https://...",
            "libkey": {"本館": "貸出可", "分館": "貸出中"}
          }
        }
      }
    }
- 図書館システムID（systemid）は https://calil.jp/library/ で自分の自治体を検索して取得する。
- APIキーは https://calil.jp/api/dashboard/ から申請する（無料）。
"""

from __future__ import annotations

import hashlib
import os
import random
import re
from dataclasses import dataclass

from mock_data import MOCK_LIBRARY_SYSTEMS

CALIL_APPKEY = os.environ.get("CALIL_APPKEY")  # 未設定ならモックモードで動作

# カーリルAPI自体のレスポンスには予約待ち人数は含まれていない（libkeyは
# "貸出可"/"貸出中" 等のステータス文字列のみ）。ただし reserveurl（図書館の書誌詳細
# ページへの実際のリンク）を開くと「予約数：5 貸出可能数：0 貸出件数：1」のように
# 待ち人数が載っていることが分かったため、そのページを取得して数値を抜き出す。
_WAITING_COUNT_RE = re.compile(r"予約数[：:][^\d]*(\d+)")


@dataclass
class LibraryAvailability:
    library_name: str
    status: str  # "貸出可" / "貸出中" / "予約中" / "蔵書なし" など
    reserve_url: str | None = None
    waiting_count: int | None = None  # 予約中の場合の待ち人数（わかる場合のみ）


_STATUS_CHOICES = ["貸出可", "貸出中", "予約中", "蔵書なし"]
_STATUS_WEIGHTS = [0.40, 0.25, 0.20, 0.15]  # モックなので少し「貸出可」に寄せておく


def _deterministic_random(seed_text: str) -> random.Random:
    """同じ書籍・同じ図書館なら毎回同じ結果になるよう、文字列からシードを作る。"""
    digest = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:8], 16))


def fetch_availability_mock(isbn13: str) -> list[LibraryAvailability]:
    """モック版: 近隣図書館ごとにそれっぽい蔵書状況を返す。"""
    results: list[LibraryAvailability] = []
    for lib in MOCK_LIBRARY_SYSTEMS:
        rng = _deterministic_random(f"{isbn13}:{lib['systemid']}")
        status = rng.choices(_STATUS_CHOICES, weights=_STATUS_WEIGHTS, k=1)[0]
        reserve_url = (
            f"https://calil.jp/book/{isbn13}" if status != "蔵書なし" else None
        )
        waiting_count = rng.randint(1, 15) if status == "予約中" else None
        results.append(
            LibraryAvailability(
                library_name=lib["name"],
                status=status,
                reserve_url=reserve_url,
                waiting_count=waiting_count,
            )
        )
    return results


def _fetch_waiting_count(reserve_url: str | None) -> int | None:
    """書誌詳細ページ（reserveurl）を取得し「予約数：N」を抜き出す。取得できなければNone。"""
    if not reserve_url:
        return None

    import requests

    try:
        response = requests.get(reserve_url, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        return None

    match = _WAITING_COUNT_RE.search(response.text)
    return int(match.group(1)) if match else None


def fetch_availability_real(isbn13: str) -> list[LibraryAvailability]:
    """
    実際のカーリルAPIを呼び出す版（要 requests, 要 CALIL_APPKEY）。
    MVPでは未使用。CALIL_APPKEY が設定された場合に fetch_availability() から呼ばれる。
    """
    import time

    import requests

    systemids = ",".join(lib["systemid"] for lib in MOCK_LIBRARY_SYSTEMS)
    params = {
        "appkey": CALIL_APPKEY,
        "isbn": isbn13,
        "systemid": systemids,
        "format": "json",
        "callback": "no",
    }
    base_url = "https://api.calil.jp/check"

    data = requests.get(base_url, params=params, timeout=10).json()
    session = data.get("session")

    # カーリルAPIは非同期。continue=1 の間はポーリングする（最大10回まで）
    for _ in range(10):
        if data.get("continue", 0) == 0:
            break
        time.sleep(2)
        data = requests.get(
            base_url, params={"appkey": CALIL_APPKEY, "session": session, "format": "json", "callback": "no"},
            timeout=10,
        ).json()

    results: list[LibraryAvailability] = []
    book_data = data.get("books", {}).get(isbn13, {})
    for lib in MOCK_LIBRARY_SYSTEMS:
        sys_data = book_data.get(lib["systemid"], {})
        libkey = sys_data.get("libkey", {})
        if libkey:
            # 「中央」を含む分館名があればそれを優先表示（中央図書館の状況を見たいため）、
            # なければ先頭の分館を代表として表示
            branch, status = next(
                ((b, s) for b, s in libkey.items() if "中央" in b),
                next(iter(libkey.items())),
            )
            status_text = f"{status}（{branch}）"
            # 図書館システムによっては libkey のステータス文字列自体に
            # 「予約4件」のように件数が埋め込まれていることがあるので、まずそこから
            # 数字を拾う。無ければ書誌詳細ページ（reserveurl）を取得して抜き出す。
            waiting_count = None
            if "予約" in status:
                match = re.search(r"(\d+)", status)
                if match:
                    waiting_count = int(match.group(1))
            if waiting_count is None:
                waiting_count = _fetch_waiting_count(sys_data.get("reserveurl"))
        else:
            status_text = "蔵書なし"
            waiting_count = None
        results.append(
            LibraryAvailability(
                library_name=lib["name"],
                status=status_text,
                reserve_url=sys_data.get("reserveurl"),
                waiting_count=waiting_count,
            )
        )
    return results


def fetch_availability(isbn13: str) -> list[LibraryAvailability]:
    """アプリ本体からはこの関数だけを呼ぶ。APIキーの有無で自動切り替え。"""
    if CALIL_APPKEY:
        return fetch_availability_real(isbn13)
    return fetch_availability_mock(isbn13)
