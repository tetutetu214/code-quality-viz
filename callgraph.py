"""ファイル横断の静的コールグラフを pyan3 で生成する薄い統合層.

狙い:
    link_analyzer の自前呼び出し抽出（_CallCollector）は同じファイル内の呼び出し
    しか辿れず、別ファイルへの呼び出しや `import x as y` の別名を解決できない。
    pyan3 は ast + symtable で defines/uses を解析し、ファイル横断・別名 import を
    解決した関数/メソッド粒度のコールグラフを出せる（PoC で実測確認済み。
    docs/knowledge.md 2026-07-13）。この層は pyan3 を subprocess で呼び、DOT を得て
    Graphviz(dot) で SVG に描くだけの薄いラッパ。自分では解析ロジックを持たない。

なぜ subprocess で `python -m pyan` なのか:
    cross_check が radon/pytest を呼ぶのと同じ理由。PATH に実行体が無い環境
    （Streamlit の venv からの起動）でも、同じ Python の -m で確実に起動できる。

限界（正直に）:
    静的解析なので visitor パターンの self.visit() のような動的 dispatch は辿れない。
    その経路のメソッドは親を持たず入口として並ぶ。全静的ツール共通の原理限界で、
    実際に通った経路は動的解析（cross_check のカバレッジ）で裏取りする住み分け。

依存: pyan3（`python -m pyan`）と Graphviz の dot コマンド。どちらも無い場合は
    エラー文字列を返し、呼び出し側で導入手順を案内できるようにする。
"""

import os
import shutil
import subprocess
import sys


# ノード数がこれを超えたら「判読しづらい」警告を出す目安（NFR-6）。
# 起点関数の指定や粒度(depth)の調整、ファイル数の削減を促す。
NODE_WARN_THRESHOLD = 60

# pyan の粒度(depth)ラベル。画面の selectbox にそのまま使う。
DEPTH_CHOICES = {
    "関数・メソッドまで（詳細）": "max",
    "メソッドまで": "2",
    "クラス・トップレベル関数まで": "1",
    "モジュールのみ": "0",
}

_DIRECTIONS = {"down", "up", "both"}


def module_available(module: str, python: str = None) -> bool:
    """指定モジュールがその Python で import できるかを返す."""
    python = python or sys.executable
    proc = subprocess.run(
        [python, "-c", f"import {module}"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def dot_available() -> bool:
    """Graphviz の dot コマンドが使えるかを返す."""
    return shutil.which("dot") is not None


def build_pyan_command(
    python: str,
    files: list,
    fmt: str = "dot",
    function: str = None,
    direction: str = "down",
    depth: str = "max",
    colored: bool = True,
    grouped: bool = True,
    annotated: bool = False,
) -> list:
    """pyan3 を呼ぶコマンド列を組み立てる（副作用なし・単体テスト対象）.

    uses（呼び出し）だけを辺にし、defines（定義所属）は辺にしない
    （呼び出し関係を読むのが目的なので）。function を渡したときだけ
    起点フィルタ（--function ＋ --direction）を付ける。
    """
    cmd = [python, "-m", "pyan", *files, "--uses", "--no-defines", f"--{fmt}"]
    if colored:
        cmd.append("--colored")
    if grouped:
        cmd.append("--grouped")
    if annotated:
        cmd.append("--annotated")
    if depth is not None:
        cmd.extend(["--depth", str(depth)])
    if function:
        if direction not in _DIRECTIONS:
            direction = "both"
        cmd.extend(["--function", function, "--direction", direction])
    return cmd


def count_dot_nodes(dot_text: str) -> int:
    """DOT 文字列中のノード定義（[label=...] を持つ行）数を数える."""
    return sum(1 for line in dot_text.splitlines() if "[label=" in line)


def count_dot_edges(dot_text: str) -> int:
    """DOT 文字列中のエッジ（-> を含む行）数を数える."""
    return sum(1 for line in dot_text.splitlines() if "->" in line)


def _run(cmd: list, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def run_pyan(
    files: list,
    cwd: str,
    python: str = None,
    fmt: str = "dot",
    **options,
) -> dict:
    """pyan3 を実行し, 出力（DOT/text 等）を得る.

    Returns:
        dict: ok(bool) / output(str) / error(str or None)
    """
    python = python or sys.executable
    if not files:
        return {"ok": False, "output": "", "error": "対象ファイルがありません。"}
    if not module_available("pyan", python):
        return {
            "ok": False,
            "output": "",
            "error": "pyan3 が見つかりません。`pip install pyan3` を実行してください。",
        }
    cmd = build_pyan_command(python, files, fmt=fmt, **options)
    proc = _run(cmd, cwd)
    if proc.returncode != 0:
        return {
            "ok": False,
            "output": proc.stdout,
            "error": f"pyan3 の実行に失敗しました:\n{proc.stderr.strip()}",
        }
    if not proc.stdout.strip():
        return {
            "ok": False,
            "output": "",
            "error": (
                "コールグラフが空でした。起点関数の名前（モジュール名.関数名）が"
                "正しいか、対象ファイルに呼び出し関係があるか確認してください。"
            ),
        }
    return {"ok": True, "output": proc.stdout, "error": None}


def render_dot(dot_text: str, cwd: str, fmt: str = "svg") -> dict:
    """DOT 文字列を Graphviz の dot で画像（既定 SVG）に変換する.

    Returns:
        dict: ok(bool) / data(str, テキスト系フォーマットの中身) / error(str or None)
    """
    if not dot_available():
        return {
            "ok": False,
            "data": "",
            "error": "Graphviz の dot が見つかりません。`sudo apt install graphviz` を実行してください。",
        }
    proc = subprocess.run(
        ["dot", f"-T{fmt}"],
        input=dot_text,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "data": "",
            "error": f"dot による描画に失敗しました:\n{proc.stderr.strip()}",
        }
    return {"ok": True, "data": proc.stdout, "error": None}


def analyze(
    files: list,
    cwd: str,
    python: str = None,
    function: str = None,
    direction: str = "down",
    depth: str = "max",
) -> dict:
    """ファイル横断の静的コールグラフを生成して, 表示に必要な一式を返す.

    pyan3 で DOT を作り, dot で SVG に描き, 併せて text（階層ツリー・AI 供給用）も
    取る。ツール未導入や描画失敗でも, 取れたところまで返して落とさない。

    Args:
        files:     対象 .py の相対パス（cwd から辿れるもの）。
        cwd:       実行の作業ディレクトリ（workspace/ など）。
        python:    使う Python 実行体。既定は現在の実行体（＝この venv）。
        function:  起点関数（`モジュール名.関数名`）。None なら全体。
        direction: 'down'（呼ぶ先）/'up'（呼び元）/'both'。
        depth:     粒度。'max'/'2'/'1'/'0'。

    Returns:
        dict:
            ok(bool)          SVG まで生成できたか
            dot(str)          DOT テキスト（空なら未生成）
            svg(str)          SVG テキスト（空なら未描画）
            text(str)         pyan --text の階層ツリー（取れなければ空）
            node_count(int)   ノード数
            edge_count(int)   エッジ数
            error(str|None)   致命的な失敗理由
            warning(str|None) 生成はできたが判読性などの注意
    """
    python = python or sys.executable
    result = {
        "ok": False,
        "dot": "",
        "svg": "",
        "text": "",
        "node_count": 0,
        "edge_count": 0,
        "error": None,
        "warning": None,
    }

    dot_run = run_pyan(
        files, cwd, python=python, fmt="dot",
        function=function, direction=direction, depth=depth,
    )
    if not dot_run["ok"]:
        result["error"] = dot_run["error"]
        return result

    dot_text = dot_run["output"]
    result["dot"] = dot_text
    result["node_count"] = count_dot_nodes(dot_text)
    result["edge_count"] = count_dot_edges(dot_text)

    if result["node_count"] > NODE_WARN_THRESHOLD and not function:
        result["warning"] = (
            f"ノードが {result['node_count']} 個と多く、全体表示は読みづらいかもしれません。"
            "起点関数の指定・粒度の変更・ファイル数の削減で絞り込めます。"
        )

    # text（階層ツリー・AI 供給用）。失敗しても致命的ではないので握りつぶす。
    text_run = run_pyan(
        files, cwd, python=python, fmt="text",
        function=function, direction=direction, depth=depth,
        colored=False, grouped=True,
    )
    if text_run["ok"]:
        result["text"] = text_run["output"]

    svg = render_dot(dot_text, cwd, fmt="svg")
    if svg["ok"]:
        result["svg"] = svg["data"]
        result["ok"] = True
    else:
        # DOT は取れているので、描画だけ失敗した旨を警告として残す。
        result["error"] = svg["error"]
    return result
