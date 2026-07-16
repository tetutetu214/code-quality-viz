"""workspace/ に置いた本物のファイルを選ぶと, 生成 AI などが作ったテストを
「網羅的に・つながりが見える形」で理解するための Streamlit アプリ.

ねらい:
- 全部の関数を 1 枚のツリー表にする。公開関数を親に、その中で呼ばれる
  ヘルパー関数を子にインデントして, 呼び出しの親子関係を目で追えるようにする。
- 各行に「種類・複雑さ・どのテストが担当・実際に動いたか・カバー率」を並べ、
  1 つの関数について知りたいことが 1 行でそろうようにする。
- 用語は画面の凡例で必ず定義する（造語を使わない/使うなら定義する）。

仕組み:
- 静的解析 (link_analyzer): 関数の抽出・複雑度・呼び出しの親子・テストの名指し。
- 動的解析 (cross_check + coverage.py): テストを実際に実行し、行・分岐カバレッジ。

使い方:
    streamlit run app.py   （workspace/ に処理側とテストの .py を置いてから選ぶ）
注意:
    選んだテストをその場で実行するため (任意コード実行に相当), ローカル自用専用。
依存: streamlit / pytest / pytest-cov / coverage / radon。
"""

import html
import os
from collections import defaultdict

import streamlit as st

import callgraph
import cross_check
import link_analyzer


st.set_page_config(page_title="テスト理解ビューア", layout="wide")

WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


# =====================================================================
# 小さなユーティリティ
# =====================================================================
def is_public(display: str) -> str:
    """関数が公開かヘルパーかを返す.

    表示名のどの区切り (クラス名・関数名) も _ で始まらなければ「公開」、
    どこかが _ で始まれば「ヘルパー」(Python の慣習: _ 始まりは内部用)。
    """
    parts = display.split(".")
    return "公開" if all(not p.startswith("_") for p in parts) else "ヘルパー"


def build_tree_order(functions: dict, calls: dict):
    """関数を「呼び出しの親子」でインデント順に並べた [(表示名, 深さ)] を返す.

    親 = その関数を呼ぶ同ファイル内の関数がいないもの (入口)。公開を先に。
    親から呼ぶ関数を再帰でぶら下げる。同じ根の中での重複は畳む (最初の1回)。
    別々の入口から呼ばれるヘルパーは、それぞれの下に出る (共有が見えるように)。
    """
    callers = defaultdict(set)
    for caller, callees in calls.items():
        for callee in callees:
            callers[callee].add(caller)

    roots = sorted(
        (f for f in functions if not callers.get(f)),
        key=lambda n: (0 if is_public(n) == "公開" else 1, n),
    )

    order = []

    def walk(name, depth, visited):
        if name in visited:
            return
        visited.add(name)
        order.append((name, depth))
        for callee in calls.get(name, []):
            walk(callee, depth + 1, visited)

    for root in roots:
        walk(root, 0, set())

    # どの入口からもたどれなかった関数 (循環など) は末尾に平置きで補う。
    emitted = {n for n, _ in order}
    for name in sorted(functions):
        if name not in emitted:
            order.append((name, 0))
    return order


def status_label(tested: bool, line, branch, complexity: int) -> str:
    """1 つの関数の状態を、専門語を避けた一言で返す."""
    if line is None:
        return "実測データなし"
    if line == 0:
        return "⚠ 一度も動いていない"
    base = "テストが担当" if tested else "動いてはいる（直接の担当テスト無し）"
    if complexity >= cross_check.COMPLEXITY_THRESHOLD and branch is not None and branch < 100:
        base += "・複雑で穴あり"
    return base


def _read_workspace_files(filenames: list) -> dict:
    """workspace/ の選択ファイルを読み込む."""
    result = {}
    for filename in filenames:
        with open(os.path.join(WORKSPACE_DIR, filename), encoding="utf-8") as f:
            result[filename] = f.read()
    return result


def _format_syntax_errors(errors: dict) -> str:
    """ファイル別の構文エラーを画面表示用に整える."""
    return "\n".join(f"- {name}: {message}" for name, message in errors.items())


def _cov_row_key(row: dict, file_by_function: dict) -> str | None:
    """coverage/radon の行を静的解析側の関数キーへ対応させる."""
    source_file = row.get("file")
    name = row["name"]
    for func, filename in file_by_function.items():
        if filename == source_file and func == name:
            return func
    prefixed = f"{source_file}.{name}"
    for func, filename in file_by_function.items():
        if filename == source_file and func == prefixed:
            return func
    return None


# =====================================================================
# 詳細ビュー: 関数×テストクラスの紐付きマトリクス (expander の中で使う)
# =====================================================================
def render_matrix(link: dict):
    functions = link["functions"]
    func_to_tests = link["func_to_tests"]
    all_tests = link["all_tests"]
    untested = link["untested"]
    empty_tests = link["empty_tests"]

    if not all_tests:
        st.warning("テストクラスが見つからないため、マトリクスの列がありません。")
        return

    ordered = sorted(functions, key=lambda n: (len(func_to_tests.get(n, [])), n))
    cell_via = {
        n: {t["cls"]: t["via"] for t in func_to_tests.get(n, [])} for n in ordered
    }

    head_cells = ['<th class="corner">関数 ＼ テスト</th>']
    for j, cls in enumerate(all_tests):
        col_cls = "col-empty" if cls in empty_tests else ""
        head_cells.append(
            f'<th class="colhead {col_cls}" data-col="{j}">'
            f'<span>{html.escape(cls)}</span></th>'
        )
    header = f'<tr>{"".join(head_cells)}</tr>'

    body_rows = []
    for name in ordered:
        row_empty = name in untested
        row_cls = "row-empty" if row_empty else ""
        cells = [
            f'<th class="rowhead {row_cls}">{html.escape(name)}</th>'
        ]
        for j, cls in enumerate(all_tests):
            col_empty = "col-empty" if cls in empty_tests else ""
            via = cell_via[name].get(cls)
            if via:
                sym = "●" if via == "C" else "○"
                tip = "直接呼び出し(C)" if via == "C" else "self 代入経由(B)"
                inner = (
                    f'<span class="mk" title="{html.escape(name)} × '
                    f'{html.escape(cls)}｜{tip}">{sym}</span>'
                )
            else:
                inner = ""
            cells.append(f'<td class="cell {col_empty}" data-col="{j}">{inner}</td>')
        body_rows.append(f'<tr class="{row_cls}">{"".join(cells)}</tr>')

    matrix_html = f"""
<style>
  #cq-matrix {{ overflow:auto; max-height:560px; font-family:sans-serif; }}
  #cq-matrix table {{ border-collapse:collapse; }}
  #cq-matrix th, #cq-matrix td {{
    border:1px solid #e3e6ea; text-align:center; font-size:13px;
  }}
  #cq-matrix .corner {{
    position:sticky; left:0; top:0; z-index:3; background:#f2f4f8;
    padding:4px 8px; font-size:11px; color:#567; white-space:nowrap;
  }}
  #cq-matrix .colhead {{
    position:sticky; top:0; z-index:2; background:#f2f4f8; height:132px;
    vertical-align:bottom; padding:6px 2px;
  }}
  #cq-matrix .colhead span {{
    writing-mode:vertical-rl; transform:rotate(180deg);
    white-space:nowrap; font-size:12px; color:#345;
  }}
  #cq-matrix .rowhead {{
    position:sticky; left:0; z-index:1; background:#fff;
    text-align:left; padding:4px 8px; font-family:monospace;
    white-space:nowrap; color:#111; font-weight:normal;
  }}
  #cq-matrix .cell {{ width:30px; height:28px; background:#fff; }}
  #cq-matrix .mk {{ color:#2f5fd0; font-size:14px; }}
  #cq-matrix tr.row-empty .rowhead {{ background:#fff5f5; color:#b3261e; }}
  #cq-matrix tr.row-empty .cell {{ background:#fff8f8; }}
  #cq-matrix .col-empty {{ background:#fff7ec; }}
  #cq-matrix th.col-empty span {{ color:#b26a00; }}
  #cq-matrix tbody tr:hover .cell,
  #cq-matrix tbody tr:hover .rowhead {{ background:#eaf1ff; }}
  #cq-matrix .cq-hl {{ background:#eaf1ff !important; }}
</style>
<div id="cq-matrix">
  <table>
    <thead>{header}</thead>
    <tbody>{''.join(body_rows)}</tbody>
  </table>
</div>
<script>
(function() {{
  var root = document.getElementById('cq-matrix');
  if (!root) return;
  function clear() {{
    root.querySelectorAll('.cq-hl').forEach(function(el) {{
      el.classList.remove('cq-hl');
    }});
  }}
  root.addEventListener('mouseover', function(e) {{
    var t = e.target.closest('[data-col]');
    clear();
    if (t) {{
      var c = t.getAttribute('data-col');
      root.querySelectorAll('[data-col="' + c + '"]').forEach(function(el) {{
        el.classList.add('cq-hl');
      }});
    }}
  }});
  root.addEventListener('mouseout', clear);
}})();
</script>
"""
    st.html(matrix_html, unsafe_allow_javascript=True)
    st.caption("● 直接呼び出し(C)／○ self 代入経由(B)／薄赤の行=名指しなし／薄橙の列=どの関数にも紐づかないテスト")


def render_callgraph_panel(source_files: list, test_files: list):
    """ファイル横断の静的コールグラフを pyan3 で生成して見せる（フェーズ1 / FR-1〜4）.

    上の「全関数ツリー」はファイル単位（別ファイルへの呼び出しは出ない）。ここでは
    pyan3 が別ファイルへの呼び出しまで解決した 1 枚のツリー＋図を出す。ツールが未導入
    でも例外を出さず、導入手順を案内する（AC-5）。
    """
    if not callgraph.pyan_available():
        st.info(
            "ファイル横断のコールグラフには pyan3 が必要です。"
            "`pip install pyan3` で導入すると、別ファイルへの呼び出しまで 1 枚に統合できます。"
        )
        return

    paths = [os.path.join(WORKSPACE_DIR, name) for name in source_files]
    result = callgraph.analyze(paths)
    if not result["ok"]:
        st.warning(result["error"] or "コールグラフを生成できませんでした。")
        if result.get("hint"):
            st.caption(result["hint"])
        return

    nodes = result["nodes"]
    st.caption(
        "pyan3（静的解析）で、選んだ全ファイルを横断して「誰が誰を呼ぶか」を解決したツリーです。"
        "上の『全関数ツリー』が取りこぼす**別ファイルへの呼び出し**もここでは 1 本につながります。"
        "※ visitor の `self.visit()` のような動的な呼び出しは静的に辿れないため、"
        "その経路は根（入口）として並びます。実際に通ったかは上のカバレッジで裏取りしてください。"
    )

    # --- 絞り込み（起点＋深さ）: FR-2 ---
    entry_map = {"（全体）": None}
    for nid in result["entry_ids"]:
        entry_map[nodes[nid]["qname"]] = nid
    col1, col2 = st.columns([2, 1])
    with col1:
        choice = st.selectbox(
            "起点の関数（大きいコードはここで絞ると読みやすい）",
            list(entry_map.keys()),
            key="cg_start",
        )
    with col2:
        depth = st.slider("たどる深さ", 1, 8, 4, key="cg_depth")
    start = entry_map[choice]

    order = callgraph.build_order(nodes, result["call_edges"], start=start, max_depth=depth)
    selected_ids = [nid for nid, _ in order]

    # --- 横断ツリー表 ---
    table = []
    for nid, d in order:
        n = nodes[nid]
        indent = "　" * d + ("└ " if d else "")
        table.append(
            {
                "関数（module.名前）": indent + n["qname"],
                "種類": "公開" if not n["short"].split(".")[-1].startswith("_") else "ヘルパー",
                "定義元": os.path.basename(n["file"]) if n["file"] else "—",
            }
        )
    st.dataframe(table, width="stretch", hide_index=True)

    # --- 図（ブラウザ描画。大規模なら起点指定を促す: NFR-6）---
    dot = callgraph.build_subgraph_dot(nodes, result["call_edges"], selected_ids)
    if start is None and result["too_large"]:
        st.info(
            f"関数が {result['n_nodes']} 個と多いため、全体図は省略しました。"
            "上の『起点の関数』を選ぶと、その周りだけの図を表示します。"
        )
    else:
        st.graphviz_chart(dot, width="stretch")
        if callgraph.graphviz_available():
            try:
                svg = callgraph.render_svg(dot)
                st.download_button(
                    "この図を SVG で保存",
                    data=svg,
                    file_name="callgraph.svg",
                    mime="image/svg+xml",
                )
            except callgraph.CallgraphError:
                pass
        else:
            st.caption(
                "SVG 保存には Graphviz が必要です（`sudo apt install graphviz`）。図の表示は不要です。"
            )

    # --- C1 が解けた証拠: 別ファイルへの呼び出し一覧 ---
    cross = result["cross_file_edges"]
    if cross:
        with st.expander(f"別ファイルへの呼び出し {len(cross)} 本（自前ツリーでは出なかった関係）"):
            for s, d in cross:
                st.markdown(f"- `{nodes[s]['qname']}` → `{nodes[d]['qname']}`")

    # --- pyan text 出力（別の AI に貼れる）: FR-4 ---
    text = callgraph.generate_text(paths)
    if text:
        with st.expander("詳細：pyan3 のテキスト出力（別の AI エージェントにそのまま渡せます）"):
            st.code(text)

    # --- 動的（実行経路）での裏取り: FR-6 / FR-8 ---
    st.markdown("#### 実行経路（動的）で裏取りする")
    st.caption(
        "上の静的グラフは「呼びうるか」。ここではテストを **cProfile 下でもう一度実行**して"
        "「今回、実際にどの関数がどこから呼ばれたか」を記録し、静的グラフと突き合わせます。"
        "visitor の `self.visit()` のように静的では辿れない経路（＝入口として並ぶ関数）が、"
        "実行では誰から呼ばれたのかを裏取りできます。"
    )
    _render_dynamic_subpanel(test_files, source_files, result)


def _render_dynamic_subpanel(test_files: list, source_files: list, static_result: dict):
    if not callgraph.gprof2dot_available():
        st.info("実行経路の裏取りには gprof2dot が必要です（`pip install gprof2dot`）。")
        return
    if not st.checkbox(
        "テストをもう一度 cProfile 下で実行して裏取りする（時間がかかります）",
        key="cg_dynamic",
    ):
        return

    with st.spinner("cProfile 下でテストを実行して実行経路を記録中…"):
        dyn = callgraph.analyze_dynamic(test_files, WORKSPACE_DIR, source_files)
    if not dyn["ok"]:
        st.warning(dyn["error"] or "実行経路を取得できませんでした。")
        if dyn.get("hint"):
            st.caption(dyn["hint"])
        return

    cmp = callgraph.compare_static_dynamic(static_result, dyn)
    c1, c2, c3 = st.columns(3)
    c1.metric("実行された関数", dyn["n_executed"])
    c2.metric("静的で検出した関数", static_result["n_nodes"])
    c3.metric("静的=動的で一致した呼び出し", cmp["both_count"])

    # 実行経路グラフ（外部の dispatch 元は淡色ノード）。
    if dyn["edges"]:
        st.graphviz_chart(dyn["dot"], width="stretch")
        st.caption("濃い箱＝解析対象の関数／淡い箱＝外部（stdlib 等, 呼び出し元）。辺の数字＝呼ばれた回数。")

    # C2 の証拠: 静的では辿れず、実行では外部（dispatch 元）から呼ばれた関数。
    if dyn["dispatch_edges"]:
        with st.expander(
            f"実行では別経路（動的 dispatch）で呼ばれた関数 {len(dyn['dispatch_edges'])} 件"
            "（静的グラフでは入口として並ぶ）"
        ):
            st.caption(
                "例: `ast.visit → ...visit_Xxx` は、visitor が `getattr` で動的に振り分けて呼んだ経路。"
                "静的解析では原理的に辿れないため、実行して初めて『誰から呼ばれたか』が分かります。"
            )
            for a, b in dyn["dispatch_edges"]:
                st.markdown(f"- `{a}` → `{b}`")

    # テストの穴の候補: 静的にあるが今回の実行では通らなかった呼び出し。
    if cmp["only_static"]:
        with st.expander(
            f"静的にはあるが今回のテストで通らなかった呼び出し {len(cmp['only_static'])} 件"
        ):
            st.caption(
                "テストが未到達（穴）か、実行時は別経路（上の動的 dispatch など）で解決された関係です。"
            )
            for a, b in cmp["only_static"]:
                st.markdown(f"- `{a}` → `{b}`")

    # 実行で通ったが静的グラフに出ていない source→source 呼び出し。
    if cmp["only_dynamic"]:
        with st.expander(
            f"実行で通ったが静的グラフに出ていない呼び出し {len(cmp['only_dynamic'])} 件"
        ):
            for a, b in cmp["only_dynamic"]:
                st.markdown(f"- `{a}` → `{b}`")

    # snakeviz 導線（任意, FR-7）: 起動はせず、つらら図を見るコマンドだけ案内。
    with st.expander("さらに: 実行時間の階層ツリー（snakeviz）を見るには"):
        st.markdown(
            "呼び出しスタックを icicle（つらら）図で見たいときは、ターミナルで以下を実行します"
            "（ブラウザが自動で開かない環境では表示された URL を手で開いてください）:"
        )
        st.code(
            "python -m cProfile -o profile.pstats -m pytest "
            + " ".join(test_files)
            + "\npython -m snakeviz profile.pstats",
            language="bash",
        )


# =====================================================================
# メイン
# =====================================================================
st.title("テスト理解ビューア")
st.caption(
    "workspace/ の実ファイルを選ぶと、コードの全関数を『呼び出しの親子』でぶら下げた"
    "1 枚の表にして、各関数がどのテストに担当され、実際に動いたか（カバー率）まで"
    "一望できます。生成 AI が作ったテストが、コードの何をどれだけ動かしているかを"
    "網羅的に確かめるためのものです。テストを実行するためローカル自用専用です。"
)

if not os.path.isdir(WORKSPACE_DIR):
    st.warning(f"解析用フォルダがありません: {WORKSPACE_DIR}")
    st.stop()

py_files = sorted(f for f in os.listdir(WORKSPACE_DIR) if f.endswith(".py"))
if not py_files:
    st.info("workspace/ に .py ファイルを置いてください（処理側とテストの 2 つ）。")
    st.stop()

tests = [f for f in py_files if f.startswith("test_")]
sources = [f for f in py_files if not f.startswith("test_")]

col_a, col_b = st.columns(2)
with col_a:
    source_files = st.multiselect(
        "処理側ファイル",
        py_files,
        default=sources,
        help="関数の抽出・複雑度・カバレッジの対象。",
    )
with col_b:
    test_files = st.multiselect(
        "テストファイル",
        py_files,
        default=tests,
        help="実際に実行するテスト。",
    )

cov_targets = [os.path.splitext(source_file)[0] for source_file in source_files]
st.caption(
    "カバレッジ対象モジュール: "
    + (", ".join(f"`{target}`" for target in cov_targets) or "未選択")
)

# ボタンは一度きり True になる one-shot。以降のウィジェット操作（動的裏取りの
# チェックなど）で再実行されても解析結果を保つため、session_state にラッチする。
if st.button("解析する", type="primary"):
    st.session_state["analyzed"] = True
if not st.session_state.get("analyzed"):
    st.stop()

if not source_files:
    st.error("処理側ファイルを 1 つ以上選んでください。")
    st.stop()
if not test_files:
    st.error("テストファイルを 1 つ以上選んでください。")
    st.stop()

# --- 静的解析 ---
src_result = link_analyzer.analyze_source_files(_read_workspace_files(source_files))
test_result = link_analyzer.analyze_test_files(_read_workspace_files(test_files))

if src_result.get("syntax_errors"):
    st.error("処理側コードの構文エラー:\n" + _format_syntax_errors(src_result["syntax_errors"]))
    st.stop()
if test_result.get("syntax_errors"):
    st.error("テストコードの構文エラー:\n" + _format_syntax_errors(test_result["syntax_errors"]))
    st.stop()
if not src_result["functions"]:
    st.info("処理側に関数定義が見つかりませんでした。")
    st.stop()

link = link_analyzer.build_links(src_result, test_result)
functions = link["functions"]
func_to_tests = link["func_to_tests"]
calls = src_result["calls"]
file_by_function = src_result.get("file_by_function", {})

# --- 動的解析 ---
with st.spinner("テストを実際に実行してカバレッジを測定中…"):
    cov = cross_check.analyze_project(
        project_dir=WORKSPACE_DIR,
        cov_target=cov_targets,
        source_file=source_files,
        test_path=test_files,
    )
cov_rows = cov["rows"]
cov_map = {}
for row in cov_rows:
    key = _cov_row_key(row, file_by_function)
    if key:
        cov_map[key] = {"line": row["line_pct"], "branch": row["branch_pct"]}

# --- まとめ文 (素人がまず知りたいこと) ---
n_func = len(functions)
n_exec = sum(1 for n in functions if (cov_map.get(n) or {}).get("line", 0) and cov_map[n]["line"] > 0)
n_notexec = sum(
    1 for n in functions
    if cov_map.get(n) is not None and (cov_map[n]["line"] or 0) == 0
)
n_direct = sum(1 for n in functions if func_to_tests.get(n))
n_tests = len(link["all_tests"])

if not cov_rows:
    st.error("テスト実行に失敗したため、カバレッジを測れませんでした。下のログを確認してください。")
    if cov.get("error"):
        st.warning(cov["error"])
    with st.expander("pytest の実行ログ", expanded=True):
        st.code(cov["pytest_output"] or "(出力なし)")
    st.stop()

st.divider()
st.subheader("ひとことまとめ")
st.markdown(
    f"- このテストは **{n_tests} クラス** あります。\n"
    f"- コードの関数は全部で **{n_func} 個**。テストを走らせて実際に動いたのは "
    f"**{n_exec} 個**、一度も動かなかったのは **{n_notexec} 個** です。\n"
    f"- テストが**名前で直接ねらっている**関数は **{n_direct} 個**。"
    f"残りはその関数の内部で連鎖的に動いています（下の表のインデントが親子関係）。"
)
if cov.get("error"):
    st.warning(cov["error"])

# --- 用語の凡例 (必ず定義する) ---
with st.expander("表の言葉の意味（先に読んでください）", expanded=False):
    st.markdown(
        "- **インデント（字下げ）**：上の関数が下の関数を呼んでいます（親→子）。"
        "同じ関数が複数の親から呼ばれると、それぞれの下に出ます。\n"
        "- **種類**：`公開`＝名前が `_` で始まらない関数（外から呼ばれる想定）。"
        "`ヘルパー`＝名前が `_` で始まる関数（Python の慣習で内部用）。\n"
        "- **複雑さ**：if・for などの分かれ道の数（循環的複雑度という標準の指標）。"
        "大きいほど複雑でバグが入りやすい。\n"
        "- **担当テスト**：そのテストコードに関数名が直接書かれているテストクラス。"
        "空欄＝直接は名指しされていない（内部で呼ばれるため。悪いとは限らない）。\n"
        "- **動いた**：テストを実行したとき、その関数が実際に動いたか（coverage.py で計測）。\n"
        "- **カバー分岐%**：関数の分かれ道のうち、テストで実際に通った割合。\n"
        "- **状態**：上をまとめた一言。`⚠ 一度も動いていない`＝手当ての最優先候補。"
    )

# --- 本体: 呼び出しツリーをファイルごとに縦並び ---
st.subheader("全関数ツリー（親＝呼ぶ側 / 子＝呼ばれるヘルパー）")
for source_file in source_files:
    st.markdown(f"### {source_file}")
    file_functions = {
        name: metrics for name, metrics in functions.items()
        if file_by_function.get(name) == source_file
    }
    file_calls = src_result.get("calls_by_file", {}).get(source_file, {})
    order = build_tree_order(file_functions, file_calls)
    table = []
    for name, depth in order:
        info = cov_map.get(name)
        line = info["line"] if info else None
        branch = info["branch"] if info else None
        m = functions[name]
        tests_for = func_to_tests.get(name, [])
        tested = bool(tests_for)
        indent = "　" * depth + ("└ " if depth else "")
        table.append(
            {
                "関数": indent + name,
                "種類": is_public(name),
                "複雑さ": m["complexity"],
                "担当テスト": "／".join(t["cls"] for t in tests_for) if tested else "—",
                "動いた": "—" if line is None else ("✓" if line > 0 else "✗"),
                "カバー分岐%": None if branch is None else round(branch, 0),
                "状態": status_label(tested, line, branch, m["complexity"]),
            }
        )
    st.dataframe(table, width="stretch", hide_index=True)
st.caption(
    "上から読むと「入口の公開関数 → その中で呼ばれるヘルパー」の順。"
    "『⚠ 一度も動いていない』の行があれば、そこがテストの穴です。"
)

# --- ファイル横断コールグラフ (pyan3) ---
st.divider()
st.subheader("ファイル横断コールグラフ（別ファイルへの呼び出しも 1 枚に）")
render_callgraph_panel(source_files, test_files)

# --- 詳細 (見たい人だけ) ---
with st.expander("詳細①：どのテストがどの関数を名指ししているか（マトリクス）"):
    render_matrix(link)

with st.expander("詳細②：静的解析の気付き"):
    if link["insights"]:
        for msg in link["insights"]:
            st.markdown(f"- {msg}")
    else:
        st.success("特に指摘はありません。")

with st.expander("詳細③：pytest の実行ログ"):
    st.code(cov["pytest_output"] or "(出力なし)")
