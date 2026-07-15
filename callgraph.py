"""ファイル横断の静的コールグラフ層（pyan3 委譲）。

自前 `link_analyzer._CallCollector` はファイル単位でしか辺を張れず、別ファイルへの
呼び出し（C1）を取りこぼす。本モジュールは実績ある **pyan3** を subprocess で呼び、
その出力（Graphviz DOT）を解析して「ファイル横断で解決済みの呼び出し辺」を取り出す。
radon / pytest と同じ流儀で `python -m pyan ...` を使い、保守対象を自前から外す
（docs/knowledge.md 2026-07-15 の決定 = FR-11 方針A）。

役割分担:
- pyan3（静的）: 構造＝誰が誰を呼びうるか。ファイル横断・同名関数をスコープ解決で区別。
- 動的（別モジュール）: 実際に通った経路。visitor の動的 dispatch など静的の穴を裏取り。

pyan3 の DOT フォーマット（実測 2026-07-15）:
- ノード定義: `"<id>" [label="<短名>", ... tooltip="<qname>\\n<path>[:<line>]\\n<kind> in <scope>"];`
  - モジュールノードは tooltip が `<name>\\n<path>` の 2 行のみ（`:line` も `in` も無い）。
  - 関数/メソッド/クラスは `<qname>\\n<path>:<line>\\n(function|method|class) in <scope>`。
- 辺: `"<src>" -> "<dst>" [style="solid|dashed", ...];`
  - `dashed` = defines（モジュール→メンバ, クラス→メソッド）。呼び出しではない。
  - `solid`  = uses（実際の呼び出し）。**両端が非モジュール**の solid 辺が関数間の呼び出し。
"""

import os
import re
import shutil
import subprocess
import sys

# pyan の text 出力（--text）に貼るヘッダ等で使う想定の既定タイムアウト（秒）。
_TIMEOUT = 60

# 大きすぎるグラフの一枚絵生成を抑止する閾値（NFR-6）。超えたら起点指定を促す。
MAX_NODES_FOR_FULL_GRAPH = 60


class CallgraphError(Exception):
    """コールグラフ生成に失敗したことを表す。UI 側で hint を導入手順として表示する。"""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


# =====================================================================
# ツール検出（未導入でも落とさず、導入手順を返せるように）
# =====================================================================
def graphviz_available() -> bool:
    """Graphviz の `dot` が PATH にあるか。DOT→画像変換に必須（NFR-2）。"""
    return shutil.which("dot") is not None


def pyan_available() -> bool:
    """pyan3 が import 可能か（`python -m pyan` で起動できるか）。"""
    import importlib.util

    return importlib.util.find_spec("pyan") is not None


def _graphviz_hint() -> str:
    return (
        "Graphviz（`dot` コマンド）が見つかりません。"
        "`sudo apt install graphviz`（Debian/Ubuntu）または "
        "`brew install graphviz`（macOS）で導入してください。"
    )


def _pyan_hint() -> str:
    return "pyan3 が見つかりません。`pip install pyan3` で導入してください。"


# =====================================================================
# 純粋関数: DOT の解析・ツリー化・サブグラフ DOT 生成（subprocess 非依存 → 単体テスト可能）
# =====================================================================
_NODE_RE = re.compile(r'^\s*"(?P<id>[^"]+)"\s*\[(?P<attrs>.*)\];\s*$')
_EDGE_RE = re.compile(
    r'^\s*"(?P<src>[^"]+)"\s*->\s*"(?P<dst>[^"]+)"\s*\[(?P<attrs>.*)\];\s*$'
)
_LABEL_RE = re.compile(r'label="(?P<v>(?:[^"\\]|\\.)*)"')
_TOOLTIP_RE = re.compile(r'tooltip="(?P<v>(?:[^"\\]|\\.)*)"')
_STYLE_RE = re.compile(r'style="(?P<v>[^"]*)"')


def _parse_tooltip(tooltip: str) -> dict:
    r"""tooltip（`qname\n path[:line]\n kind in scope`）を分解する。

    モジュールノード（2 行・`in` 無し）は kind="module" として返す。
    """
    parts = tooltip.split("\\n")
    qname = parts[0].strip() if parts else ""
    file = ""
    line = None
    kind = "module"
    if len(parts) >= 2:
        loc = parts[1].strip()
        m = re.match(r"^(?P<path>.*?):(?P<line>\d+)$", loc)
        if m:
            file = m.group("path")
            line = int(m.group("line"))
        else:
            file = loc
    if len(parts) >= 3:
        # "function in X" / "method in X" / "class in X"
        kind = parts[2].strip().split()[0]
    return {"qname": qname, "file": file, "line": line, "kind": kind}


def parse_pyan_dot(dot: str) -> tuple:
    """pyan3 の DOT を (nodes, call_edges) に解析する。

    Returns:
        nodes: dict[id, {qname, short, file, line, kind, is_module}]
        call_edges: list[(src_id, dst_id)]  両端が非モジュールの solid 辺のみ（＝呼び出し）
    """
    nodes = {}
    edges_raw = []
    for line in dot.splitlines():
        em = _EDGE_RE.match(line)
        if em:
            style = _STYLE_RE.search(em.group("attrs"))
            edges_raw.append(
                (em.group("src"), em.group("dst"), style.group("v") if style else "")
            )
            continue
        nm = _NODE_RE.match(line)
        if nm:
            attrs = nm.group("attrs")
            label_m = _LABEL_RE.search(attrs)
            tip_m = _TOOLTIP_RE.search(attrs)
            info = _parse_tooltip(tip_m.group("v")) if tip_m else {}
            kind = info.get("kind", "module")
            nodes[nm.group("id")] = {
                "qname": info.get("qname", nm.group("id")),
                "short": label_m.group("v") if label_m else nm.group("id"),
                "file": info.get("file", ""),
                "line": info.get("line"),
                "kind": kind,
                "is_module": kind == "module",
            }

    call_edges = []
    seen = set()
    for src, dst, style in edges_raw:
        if style != "solid":
            continue  # dashed = defines（呼び出しではない）
        s, d = nodes.get(src), nodes.get(dst)
        if not s or not d or s["is_module"] or d["is_module"]:
            continue  # モジュール絡みの import レベル辺は落とす
        if src == dst:
            continue
        if (src, dst) in seen:
            continue
        seen.add((src, dst))
        call_edges.append((src, dst))
    return nodes, call_edges


def _is_public(node: dict) -> bool:
    """短名が `_` で始まらない＝公開（外から呼ばれる想定）。"""
    return not node["short"].split(".")[-1].startswith("_")


def build_order(nodes: dict, call_edges: list, start: str = None, max_depth: int = None):
    """呼び出しの親子でインデントした [(id, 深さ)] を返す。

    link_analyzer / app.build_tree_order と同じ意味論:
    - 入口（呼ばれていない＝入次数0）を根に、公開を先に。start 指定時はそれを唯一の根に。
    - 根ごとに DFS で子をぶら下げ、同じ根の中の重複は畳む（最初の1回）。
    - max_depth 指定時はその深さで打ち切る（FR-2 の絞り込み）。
    - どの根からも辿れなかったノード（循環など）は末尾に平置き。

    ノードは非モジュールのみを対象にする（モジュールノードはツリーに出さない）。
    """
    func_nodes = {nid: n for nid, n in nodes.items() if not n["is_module"]}
    callees = {}
    indeg = {nid: 0 for nid in func_nodes}
    for src, dst in call_edges:
        if src in func_nodes and dst in func_nodes:
            callees.setdefault(src, [])
            if dst not in callees[src]:
                callees[src].append(dst)
            indeg[dst] = indeg.get(dst, 0) + 1

    def sort_key(nid):
        n = func_nodes[nid]
        return (0 if _is_public(n) else 1, n["qname"])

    for nid in callees:
        callees[nid].sort(key=sort_key)

    if start is not None:
        roots = [start] if start in func_nodes else []
    else:
        roots = sorted((nid for nid in func_nodes if indeg.get(nid, 0) == 0), key=sort_key)

    order = []

    def walk(nid, depth, visited):
        if nid in visited:
            return
        visited.add(nid)
        order.append((nid, depth))
        if max_depth is not None and depth >= max_depth:
            return
        for child in callees.get(nid, []):
            walk(child, depth + 1, visited)

    for root in roots:
        walk(root, 0, set())

    if start is None:
        emitted = {nid for nid, _ in order}
        for nid in sorted(func_nodes, key=sort_key):
            if nid not in emitted:
                order.append((nid, 0))
    return order


def build_subgraph_dot(nodes: dict, call_edges: list, selected_ids) -> str:
    """選択ノード集合だけの最小 DOT を組む（絞り込み後の画像用, FR-2/FR-3）。

    ノードラベルは qname（同名関数を区別）。ファイル別に色分けせず、判読性優先で簡素に。
    """
    selected = set(selected_ids)
    lines = [
        "digraph callgraph {",
        '  rankdir="LR";',
        '  node [shape="box", style="rounded,filled", fillcolor="#eef3fb", '
        'fontname="sans-serif", fontsize="10"];',
        '  edge [color="#5b6b7f"];',
    ]
    for nid in sorted(selected):
        n = nodes.get(nid)
        if not n:
            continue
        label = n["qname"].replace('"', '\\"')
        lines.append(f'  "{nid}" [label="{label}"];')
    for src, dst in call_edges:
        if src in selected and dst in selected:
            lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)


# =====================================================================
# subprocess ラッパ（ツール実行）
# =====================================================================
def _run(cmd, stdin=None):
    try:
        return subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except FileNotFoundError as e:
        raise CallgraphError(f"コマンドが見つかりません: {cmd[0]}", "") from e
    except subprocess.TimeoutExpired as e:
        raise CallgraphError(
            f"処理がタイムアウトしました（{_TIMEOUT}s）。対象を絞り込んでください。", ""
        ) from e


def generate_dot(files: list, python_exe: str = None) -> str:
    """pyan3 を実行して DOT 文字列を返す。files は解析対象の .py パス群。"""
    if not files:
        raise CallgraphError("解析対象ファイルが空です。", "")
    if not pyan_available():
        raise CallgraphError("pyan3 が未導入です。", _pyan_hint())
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        raise CallgraphError("ファイルが見つかりません: " + ", ".join(missing), "")
    exe = python_exe or sys.executable
    res = _run([exe, "-m", "pyan", *files, "--uses", "--dot"])
    if res.returncode != 0 or not res.stdout.strip():
        raise CallgraphError(
            "pyan3 の実行に失敗しました。", (res.stderr or "").strip()[:2000]
        )
    return res.stdout


def generate_text(files: list, python_exe: str = None) -> str:
    """pyan3 の text 出力を返す（別 AI エージェントへ渡す用, FR-4）。失敗時は空文字。"""
    if not files or not pyan_available():
        return ""
    exe = python_exe or sys.executable
    try:
        res = _run([exe, "-m", "pyan", *files, "--uses", "--defines", "--text"])
    except CallgraphError:
        return ""
    return res.stdout if res.returncode == 0 else ""


def render_svg(dot: str) -> bytes:
    """DOT を Graphviz で SVG 画像（bytes）に変換する。"""
    if not graphviz_available():
        raise CallgraphError("Graphviz が未導入です。", _graphviz_hint())
    try:
        res = subprocess.run(
            ["dot", "-Tsvg"],
            input=dot.encode("utf-8"),
            capture_output=True,
            timeout=_TIMEOUT,
        )
    except FileNotFoundError as e:
        raise CallgraphError("Graphviz が未導入です。", _graphviz_hint()) from e
    except subprocess.TimeoutExpired as e:
        raise CallgraphError("画像生成がタイムアウトしました。", "") from e
    if res.returncode != 0:
        raise CallgraphError(
            "Graphviz の画像生成に失敗しました。",
            (res.stderr or b"").decode("utf-8", "replace")[:2000],
        )
    return res.stdout


# =====================================================================
# オーケストレータ（UI が呼ぶ入口）
# =====================================================================
def analyze(files: list, start: str = None, max_depth: int = None, python_exe: str = None) -> dict:
    """ファイル横断コールグラフを解析し、UI が必要とする一式を返す。

    ツール未導入でも例外を投げず、`ok=False` と `hint`（導入手順）で返す（AC-5）。

    Returns dict:
        ok: bool
        error / hint: str            失敗時のメッセージと導入手順
        nodes: dict[id, {...}]        非モジュール含む全ノード
        call_edges: list[(src,dst)]   ファイル横断で解決済みの呼び出し辺
        order: list[(id, depth)]      インデント用（build_order の結果）
        entry_ids: list[id]           入口関数（起点セレクタの選択肢）
        cross_file_edges: list        別ファイルへ跨ぐ辺のみ（C1 が解けた証拠の可視化用）
        n_nodes: int                  非モジュールノード数
        too_large: bool               一枚絵抑止フラグ（NFR-6）
    """
    try:
        dot = generate_dot(files, python_exe=python_exe)
    except CallgraphError as e:
        return {"ok": False, "error": e.message, "hint": e.hint}

    nodes, call_edges = parse_pyan_dot(dot)
    func_nodes = {nid: n for nid, n in nodes.items() if not n["is_module"]}
    order = build_order(nodes, call_edges, start=start, max_depth=max_depth)

    indeg = {nid: 0 for nid in func_nodes}
    for _, dst in call_edges:
        if dst in func_nodes:
            indeg[dst] = indeg.get(dst, 0) + 1
    entry_ids = sorted(
        (nid for nid in func_nodes if indeg.get(nid, 0) == 0),
        key=lambda nid: func_nodes[nid]["qname"],
    )

    cross_file_edges = [
        (s, d)
        for s, d in call_edges
        if nodes[s]["file"] and nodes[d]["file"] and nodes[s]["file"] != nodes[d]["file"]
    ]

    return {
        "ok": True,
        "error": None,
        "hint": "",
        "nodes": nodes,
        "call_edges": call_edges,
        "order": order,
        "entry_ids": entry_ids,
        "cross_file_edges": cross_file_edges,
        "n_nodes": len(func_nodes),
        "too_large": len(func_nodes) > MAX_NODES_FOR_FULL_GRAPH,
        "raw_dot": dot,
    }
