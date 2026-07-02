"""複雑度（静的）× 実カバレッジ（動的）を突き合わせる最小の掛け合わせ層.

狙い:
    link_analyzer 単体では「テストから名指しされていない内部ヘルパー」を一律
    未テストと誤判定してしまう（偽陽性）。実際にテストを走らせて観測する
    coverage.py の結果と、radon が出す複雑度を関数名で突き合わせることで、
    「分かれ道（複雑度）が多いのに、その分かれ道を実際に通れていない
    （分岐カバレッジが低い）関数」＝本当に危ない関数を浮かび上がらせる。

なぜ複雑度は radon、カバレッジは coverage.py なのか:
    - 複雑度はコードを実行せず AST を読む静的解析でしか出せない → radon（既存の
      一次ツール。自前の複雑度計測を保守しなくて済む）。
    - どの関数が実際に動いたかは実行を観測する動的解析でしか分からない →
      coverage.py（内部ヘルパーの間接カバレッジも正しく拾える）。
    この2つは役割が重複せず、掛け合わせて初めて意味が出る。

前提（この層は自分でテストを実行しない）:
    先に coverage.py でテストを走らせ、機械可読な coverage.json を作っておく。
        .venv/bin/pytest test_link_analyzer.py --cov=link_analyzer --cov-branch
        .venv/bin/coverage json -o coverage.json
    この層はその coverage.json を「受け取って」複雑度と突き合わせるだけ。

使い方:
    python cross_check.py <ソース.py> <coverage.json>
    例: python cross_check.py link_analyzer.py coverage.json

依存: radon（複雑度の取得に subprocess で呼ぶ）。coverage.json は標準 json で読む。
"""

import json
import subprocess
import sys


# 複雑度がこの値以上を「複雑寄り」とみなす（radon の rank B=6〜10 の下限に合わせる）。
COMPLEXITY_THRESHOLD = 6


def load_complexity(source_path: str) -> dict:
    """radon cc をソースに掛け, 関数キー -> {complexity, rank} の辞書を返す.

    キーの作り方は coverage.json 側に合わせる:
    メソッドは 'クラス名.メソッド名', トップレベル関数は '関数名'.
    """
    proc = subprocess.run(
        ["radon", "cc", source_path, "-j"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    result = {}
    for block in data.get(source_path, []):
        # class 自体の複雑度行は関数単位の突き合わせでは使わないので飛ばす。
        if block["type"] == "class":
            continue
        classname = block.get("classname")
        key = f"{classname}.{block['name']}" if classname else block["name"]
        result[key] = {"complexity": block["complexity"], "rank": block["rank"]}
    return result


def load_coverage(coverage_json_path: str, source_path: str) -> dict:
    """coverage.json から, 関数キー -> {line_pct, branch_pct} の辞書を返す."""
    with open(coverage_json_path, encoding="utf-8") as f:
        data = json.load(f)
    files = data["files"]
    if source_path not in files:
        raise KeyError(
            f"coverage.json に {source_path} が無い。"
            f"含まれるのは: {list(files.keys())}"
        )
    result = {}
    for name, info in files[source_path]["functions"].items():
        if name == "":
            # モジュール直下（関数の外）はカバレッジ対象だが突き合わせ対象外。
            continue
        s = info["summary"]
        result[name] = {
            "line_pct": s["percent_covered"],
            "branch_pct": s["percent_branches_covered"],
        }
    return result


def build_rows(complexity: dict, coverage: dict) -> list:
    """複雑度とカバレッジを関数名で突き合わせ, リスク降順の行リストを作る.

    リスク = 複雑度 ×（1 − 分岐カバレッジ率）。
    「分かれ道が多い（複雑度大）のに, その分かれ道を通れていない
    （分岐カバレッジ小）」ほど大きくなる。
    """
    rows = []
    for key in sorted(set(complexity) | set(coverage)):
        cc = complexity.get(key)
        cov = coverage.get(key)
        cc_val = cc["complexity"] if cc else None
        branch_pct = cov["branch_pct"] if cov else None
        line_pct = cov["line_pct"] if cov else None

        if cc_val is not None and branch_pct is not None:
            risk = cc_val * (1 - branch_pct / 100)
        else:
            risk = 0.0

        attention = (
            cc_val is not None
            and branch_pct is not None
            and cc_val >= COMPLEXITY_THRESHOLD
            and branch_pct < 100
        )
        rows.append(
            {
                "name": key,
                "complexity": cc_val,
                "line_pct": line_pct,
                "branch_pct": branch_pct,
                "risk": risk,
                "attention": attention,
            }
        )
    rows.sort(key=lambda r: r["risk"], reverse=True)
    return rows


def format_table(rows: list) -> str:
    """行リストを人間が読む表に整形する."""

    def fmt_pct(v):
        return "  ?  " if v is None else f"{v:5.1f}"

    def fmt_int(v):
        return "  ?" if v is None else f"{v:3d}"

    lines = [
        f'{"関数":<40}{"複雑度":>6}{"行%":>8}{"分岐%":>8}{"リスク":>8}  注意',
        "-" * 78,
    ]
    for r in rows:
        mark = "⚠" if r["attention"] else ""
        lines.append(
            f'{r["name"]:<40}{fmt_int(r["complexity"]):>6}'
            f'{fmt_pct(r["line_pct"]):>8}{fmt_pct(r["branch_pct"]):>8}'
            f'{r["risk"]:>8.1f}  {mark}'
        )
    return "\n".join(lines)


def main(argv: list) -> int:
    if len(argv) != 3:
        print("使い方: python cross_check.py <ソース.py> <coverage.json>")
        return 1
    source_path, coverage_json_path = argv[1], argv[2]
    complexity = load_complexity(source_path)
    coverage = load_coverage(coverage_json_path, source_path)
    rows = build_rows(complexity, coverage)
    print(format_table(rows))

    attention = [r for r in rows if r["attention"]]
    print()
    if attention:
        names = "、".join(r["name"] for r in attention)
        print(f"⚠ 複雑度≥{COMPLEXITY_THRESHOLD} かつ 分岐カバレッジ<100% の関数: {names}")
    else:
        print(f"⚠ 該当なし（複雑度≥{COMPLEXITY_THRESHOLD} の関数はすべて分岐100%）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
