"""処理側コードとテストコードを貼ると, テストクラスと処理関数の紐付き・
複雑度・テスト漏れの気付きを表示する Streamlit アプリ.

方針:
- 左に処理側コード, 右にテストコードを貼る (2 入力欄).
- 紐付きは図で線を引かず, 関数ごとに紐づくテストクラスを右に並べるリストで示す
  (多対多でも崩れないようにするため).
- 複雑度と気付きは別セクションに分けて出す.

使い方:
    streamlit run app.py
依存: streamlit のみ (解析は標準ライブラリ ast, link_analyzer に実装).
"""

import html
import json

import streamlit as st

import link_analyzer


st.set_page_config(page_title="テスト×関数 紐付けビューア", layout="wide")

# --- セッション状態の初期化 ---
if "src_code" not in st.session_state:
    st.session_state.src_code = ""
if "test_code" not in st.session_state:
    st.session_state.test_code = ""
if "analyzed" not in st.session_state:
    st.session_state.analyzed = False

st.title("テスト×関数 紐付けビューア")
st.caption(
    "左に処理側コード、右にテストコードを貼って解析すると、どの処理関数が"
    "どのテストクラスに紐づいているか、テスト漏れはないか、複雑度が高すぎる"
    "関数はどれかを静的に表示します。LLM は使わず ast だけで解析します。"
)

# =====================================================================
# 保存ファイルの読み込み (サイドバー)
# =====================================================================
with st.sidebar:
    st.header("保存 / 読込")
    st.caption("保存した .testmap.json を読み込むと、両方のコードが復元されます。")
    uploaded = st.file_uploader("保存ファイルを読み込む", type=["json"])
    if uploaded is not None:
        if st.button("このファイルで復元する"):
            try:
                data = json.loads(uploaded.read().decode("utf-8"))
                st.session_state.src_code = data.get("src_code", "")
                st.session_state.test_code = data.get("test_code", "")
                st.session_state.analyzed = True
                st.success("復元しました。メイン画面に反映されています。")
            except Exception as e:
                st.error(f"読み込みに失敗しました: {e}")

# =====================================================================
# コード入力 (2 カラム)
# =====================================================================
col_src, col_test = st.columns(2)
with col_src:
    src_code = st.text_area(
        "処理側コード (main.py 相当)",
        value=st.session_state.src_code,
        height=320,
        placeholder="# ここに処理側の Python コードを貼る",
    )
with col_test:
    test_code = st.text_area(
        "テストコード (unittest)",
        value=st.session_state.test_code,
        height=320,
        placeholder="# ここに unittest 形式のテストコードを貼る",
    )

run = st.button("解析する", type="primary")

if run:
    st.session_state.src_code = src_code
    st.session_state.test_code = test_code
    st.session_state.analyzed = True

if not st.session_state.analyzed:
    st.info("処理側コードとテストコードを貼って「解析する」を押してください。")
    st.stop()

current_src = src_code if run else st.session_state.src_code
current_test = test_code if run else st.session_state.test_code

if not current_src.strip():
    st.warning("処理側コードが空です。")
    st.stop()
if not current_test.strip():
    st.warning("テストコードが空です。")
    st.stop()

# =====================================================================
# 解析
# =====================================================================
with st.spinner("解析中…"):
    src_result = link_analyzer.analyze_source(current_src)
    test_result = link_analyzer.analyze_tests(current_test)

if src_result.get("syntax_error"):
    st.error(f"処理側コードの構文エラー: {src_result['syntax_error']}")
    st.stop()
if test_result.get("syntax_error"):
    st.error(f"テストコードの構文エラー: {test_result['syntax_error']}")
    st.stop()

if not src_result["functions"]:
    st.info("処理側に関数定義が見つかりませんでした。")
    st.stop()

link = link_analyzer.build_links(src_result, test_result)
functions = link["functions"]
func_to_tests = link["func_to_tests"]
test_to_funcs = link["test_to_funcs"]
all_tests = link["all_tests"]
untested = link["untested"]
empty_tests = link["empty_tests"]


def _group_of(name: str) -> str:
    """関数の表示名からグループ (クラス名) を取り出す.

    "Class.method" -> "Class" / モジュール直下の関数 -> "(モジュール直下)".
    1 ファイル前提のため, グルーピングの粒度はクラスまで.
    """
    return name.split(".", 1)[0] if "." in name else "(モジュール直下)"


# =====================================================================
# サマリ (カバレッジ率を俯瞰位置に置く: overview first)
# =====================================================================
tested_count = len(functions) - len(untested)
coverage_pct = round(100 * tested_count / len(functions)) if functions else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("処理関数の数", len(functions))
c2.metric("テストクラスの数", len(all_tests))
c3.metric("テスト済み率", f"{coverage_pct}%")
c4.metric("テスト漏れ疑い", len(untested))
c5.metric("空振りテスト疑い", len(empty_tests))

# =====================================================================
# 関数×テスト マトリクス (行=関数, 列=テスト, 交点に記号)
# =====================================================================
st.subheader("関数×テスト マトリクス")
st.caption(
    "行=処理関数、列=テストクラス、交点の ● =直接(C) / ○ =self 経由(B)。"
    "空の行（薄赤）=テスト漏れ、空の列（薄橙）=どの関数にも紐づかないテスト。"
    "セルにマウスを載せると行と列が強調されます。"
)

sort_mode = st.radio(
    "行の並べ替え",
    ["テスト数が少ない順", "グループ順", "名前順"],
    horizontal=True,
    help="漏れを上に出すならテスト数が少ない順、構造を見るならグループ順。",
)
if sort_mode.startswith("名前"):
    ordered = sorted(functions)
elif sort_mode.startswith("グループ"):
    ordered = sorted(functions, key=lambda n: (_group_of(n), n))
else:
    ordered = sorted(functions, key=lambda n: (len(func_to_tests.get(n, [])), n))

if not all_tests:
    st.warning("テストクラスが見つからないため、マトリクスの列がありません。")
else:
    # 関数 -> {テストクラス: via} の索引を作る (セル描画用).
    cell_via = {
        n: {t["cls"]: t["via"] for t in func_to_tests.get(n, [])}
        for n in ordered
    }

    # ヘッダ行 (テストクラス名を縦書きで並べる).
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
        mark = "⚠ " if row_empty else ""
        cells = [
            f'<th class="rowhead {row_cls}" title="複雑度 '
            f'{functions[name]["complexity"]}／紐づくテスト '
            f'{len(func_to_tests.get(name, []))}">'
            f'{mark}{html.escape(name)}</th>'
        ]
        for j, cls in enumerate(all_tests):
            col_empty = "col-empty" if cls in empty_tests else ""
            via = cell_via[name].get(cls)
            if via:
                sym = "●" if via == "C" else "○"
                tip = "直接呼び出し(C)" if via == "C" else "self 代入経由(B)"
                inner = f'<span class="mk" title="{html.escape(name)} × {html.escape(cls)}｜{tip}">{sym}</span>'
            else:
                inner = ""
            cells.append(f'<td class="cell {col_empty}" data-col="{j}">{inner}</td>')
        body_rows.append(f'<tr class="{row_cls}">{"".join(cells)}</tr>')

    matrix_html = f"""
<style>
  #cq-matrix {{ overflow:auto; max-height:640px; font-family:sans-serif; }}
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
  /* 空の行=テスト漏れ (薄赤), 空の列=空振りテスト (薄橙). 色だけに頼らず記号も併用 */
  #cq-matrix tr.row-empty .rowhead {{ background:#fff5f5; color:#b3261e; }}
  #cq-matrix tr.row-empty .cell {{ background:#fff8f8; }}
  #cq-matrix .col-empty {{ background:#fff7ec; }}
  #cq-matrix th.col-empty span {{ color:#b26a00; }}
  /* クロスヘア強調: 行は :hover, 列は JS で cq-hl を付与 */
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
    # 生 HTML+CSS+JS (クロスヘア) をインライン描画.
    st.html(matrix_html, unsafe_allow_javascript=True)

    st.caption("凡例: ● 直接呼び出し(C)／○ self 代入経由(B)／薄赤の行=テスト漏れ／薄橙の列=空振りテスト")

st.divider()

# =====================================================================
# 関数の複雑さチェック
# =====================================================================
st.subheader("関数の複雑さチェック")

# 各項目の「注意ライン」と、超えると何が困るかの平易な説明.
# しきい値は解析エンジンと同じ値を参照し、二重管理を避ける.
_METRIC_HELP = [
    ("分かれ道の数（複雑度）", link_analyzer._COMPLEXITY_WARN,
     "if・for・and などで処理が枝分かれする数。多いほど通り道が増え、"
     "全部をテストで確認しきれず、バグが隠れやすくなる。"),
    ("行数", link_analyzer._LOC_WARN,
     "関数の長さ。長いほど1つの関数があれこれやり過ぎで、読むのも直すのも大変。"),
    ("引数の数", link_analyzer._ARG_WARN,
     "関数に渡す値の数。多いほど呼ぶ側が順番や意味を間違えやすい。"),
    ("入れ子の深さ（ネスト）", link_analyzer._DEPTH_WARN,
     "if の中の if …と入れ子になる深さ。深いほど頭の中で処理を追いにくい。"),
]

with st.expander("この表の見方（数値が大きいと何が悪いの？）"):
    st.markdown(
        "**数値が大きいほど、その関数は「複雑」です。** "
        "複雑な関数はバグが入りやすく、テストで確認しきれず、"
        "直すときに他の場所を壊しやすくなります。"
        "下の目安を超えたら、**小さい関数に分ける**のを検討しましょう。"
    )
    for label, warn, desc in _METRIC_HELP:
        st.markdown(f"- **{label}**：{desc}　→ 目安 **{warn} 以上で要注意**")
    st.markdown(
        "- **テスト数**：その関数を確認しているテストの数。"
        "**0 なら未テスト（漏れ）**。複雑なのにテストが少ないのも危険。"
    )

st.caption("「評価」が ⚠ の関数から手を入れるのがおすすめです。上ほど複雑です。")


def _row_note(m: dict) -> list:
    """関数の指標から、注意ラインを超えた項目を平易な言葉で返す."""
    notes = []
    if m["complexity"] >= link_analyzer._COMPLEXITY_WARN:
        notes.append("分かれ道が多い")
    if m["loc"] >= link_analyzer._LOC_WARN:
        notes.append("長い")
    if m["arg_count"] >= link_analyzer._ARG_WARN:
        notes.append("引数が多い")
    if m["max_depth"] >= link_analyzer._DEPTH_WARN:
        notes.append("入れ子が深い")
    return notes


# 複雑度の高い順に並べる (気になる関数を上に出す).
complexity_ordered = sorted(
    functions.keys(),
    key=lambda n: (-functions[n]["complexity"], n),
)
table_rows = []
for name in complexity_ordered:
    m = functions[name]
    test_n = len(func_to_tests.get(name, []))
    notes = _row_note(m)
    if name in untested:
        notes = ["テスト漏れ"] + notes
    table_rows.append(
        {
            "評価": "⚠ 要注意" if notes else "OK",
            "関数": name,
            "分かれ道(複雑度)": m["complexity"],
            "行数": m["loc"],
            "引数": m["arg_count"],
            "入れ子(ネスト)": m["max_depth"],
            "テスト数": test_n,
            "気になる点": "／".join(notes) if notes else "問題なし",
        }
    )
st.dataframe(table_rows, width="stretch", hide_index=True)

st.divider()

# =====================================================================
# 気付き
# =====================================================================
st.subheader("気付き")
if link["insights"]:
    for msg in link["insights"]:
        st.markdown(f"- {msg}")
else:
    st.success("特に指摘はありません。")

# 解決できなかった呼び出し (同名関数が処理側に複数など) があれば知らせる.
if link["unresolved"]:
    st.caption("※ 次の呼び出しは処理側に同名関数が複数あるため紐付けを保留しました:")
    for cls_name, names in link["unresolved"].items():
        st.caption(f"　{cls_name}: {', '.join(names)}")

# =====================================================================
# 書き出し (サイドバー)
# =====================================================================
with st.sidebar:
    st.divider()
    st.header("書き出し")
    save_payload = {
        "format": "testmap",
        "version": 1,
        "src_code": current_src,
        "test_code": current_test,
    }
    st.download_button(
        "保存ファイル（両方のコード）",
        data=json.dumps(save_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="graph.testmap.json",
        mime="application/json",
    )
