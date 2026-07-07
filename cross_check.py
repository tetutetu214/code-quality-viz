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
import os
import subprocess
import sys


# 複雑度がこの値以上を「複雑寄り」とみなす（radon の rank B=6〜10 の下限に合わせる）。
COMPLEXITY_THRESHOLD = 6


def load_complexity(source_path: str, cwd: str = None, python: str = None) -> dict:
    """radon cc をソースに掛け, 関数キー -> {complexity, rank} の辞書を返す.

    キーの作り方は coverage.json 側に合わせる:
    メソッドは 'クラス名.メソッド名', トップレベル関数は '関数名'.

    python -m radon で呼ぶ（PATH に radon が無い環境=Streamlit の venv からでも
    確実に起動できるようにするため）。cwd を渡すとその作業ディレクトリで実行する。
    """
    python = python or sys.executable
    proc = subprocess.run(
        [python, "-m", "radon", "cc", source_path, "-j"],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    data = json.loads(proc.stdout)
    result = {}
    # radon の出力キーは渡したパスそのもの。1 ファイル分だけ取り出す。
    blocks = data.get(source_path) or next(iter(data.values()), [])
    for block in blocks:
        # class 自体の複雑度行は関数単位の突き合わせでは使わないので飛ばす。
        if block["type"] == "class":
            continue
        classname = block.get("classname")
        key = f"{classname}.{block['name']}" if classname else block["name"]
        result[key] = {"complexity": block["complexity"], "rank": block["rank"]}
    return result


def _match_file_key(files: dict, source_path: str) -> str:
    """coverage.json の files から source_path に対応するキーを探す.

    coverage の記録パスは実行時の作業ディレクトリ依存で相対にも絶対にもなり得る。
    まず完全一致, 無ければファイル名（basename）一致で拾う。
    """
    if source_path in files:
        return source_path
    base = os.path.basename(source_path)
    for key in files:
        if os.path.basename(key) == base:
            return key
    raise KeyError(
        f"coverage.json に {source_path} が見つからない。"
        f"含まれるのは: {list(files.keys())}"
    )


def load_coverage(coverage_json_path: str, source_path: str) -> dict:
    """coverage.json から, 関数キー -> {line_pct, branch_pct} の辞書を返す."""
    with open(coverage_json_path, encoding="utf-8") as f:
        data = json.load(f)
    files = data["files"]
    file_key = _match_file_key(files, source_path)
    result = {}
    for name, info in files[file_key]["functions"].items():
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


def build_file_rows(source_file: str, complexity: dict, coverage: dict) -> list:
    """1 ファイル分の突き合わせ結果に由来ファイルを付ける."""
    rows = build_rows(complexity, coverage)
    for row in rows:
        row["file"] = source_file
    return rows


def _as_list(value) -> list:
    """単一値と複数値の両方をリストにそろえる."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


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


def analyze_project(
    project_dir: str,
    cov_target,
    source_file,
    test_path,
    python: str = None,
) -> dict:
    """実プロジェクトのテストを実行し, 複雑度×実カバレッジの行リストを返す.

    Args:
        project_dir: テストを実行する作業ディレクトリ（本物のフォルダ）。
        cov_target:  カバレッジ対象。pytest の --cov に渡す。複数可。
        source_file: radon を掛ける処理側ファイル。複数可。
        test_path:   実行するテスト。複数可。
        python:      使う Python 実行体。既定は現在の実行体（＝この venv）。

    Returns:
        dict:
            ok: bool               pytest が全て通ったか（returncode==0）
            rows: list             build_rows の結果（カバレッジが取れた場合）
            pytest_output: str     pytest の標準出力＋標準エラー（失敗時の確認用）
            error: str or None     カバレッジ突き合わせに失敗した場合の理由
    """
    python = python or sys.executable
    cov_targets = _as_list(cov_target)
    source_files = _as_list(source_file)
    test_paths = _as_list(test_path)

    if not cov_targets or not source_files or not test_paths:
        return {
            "ok": False,
            "rows": [],
            "pytest_output": "",
            "error": "処理側ファイルとテストファイルを 1 つ以上選んでください。",
        }

    # coverage.json は一時ファイルに出す（project_dir を汚さない）。
    cov_json = os.path.join(project_dir, ".cross_check_cov.json")
    cmd = [python, "-m", "pytest", *test_paths]
    cmd.extend(f"--cov={target}" for target in cov_targets)
    cmd.extend(["--cov-branch", f"--cov-report=json:{cov_json}", "-q"])
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=project_dir
    )
    output = proc.stdout + proc.stderr

    result = {
        "ok": proc.returncode == 0,
        "rows": [],
        "pytest_output": output,
        "error": None,
    }

    # テストが落ちても coverage.json が出ていれば突き合わせは試みる
    # （実測できた分だけでも見せたいため）。
    if not os.path.exists(cov_json):
        result["error"] = "coverage.json が生成されませんでした（テスト実行に失敗）。"
        return result

    try:
        rows = []
        missing_coverage = []
        for current_source in source_files:
            complexity = load_complexity(
                current_source, cwd=project_dir, python=python
            )
            try:
                coverage = load_coverage(cov_json, current_source)
            except KeyError:
                coverage = {}
                missing_coverage.append(current_source)
            rows.extend(build_file_rows(current_source, complexity, coverage))
        rows.sort(key=lambda r: r["risk"], reverse=True)
        result["rows"] = rows
        if missing_coverage:
            joined = "、".join(missing_coverage)
            result["error"] = f"coverage に含まれないファイルがあります: {joined}"
    except (KeyError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
        result["error"] = f"複雑度×カバレッジの突き合わせに失敗: {e}"
    finally:
        # 一時ファイルは残さない。
        if os.path.exists(cov_json):
            os.remove(cov_json)
    return result


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
