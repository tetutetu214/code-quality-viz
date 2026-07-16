# knowledge.md — 知見・決定事項

## 学習済み概念

### 2026-07-06 複数ファイル解析対応の設計（理解度テスト合格）
- **カバレッジは pytest 1回の実行で `--cov` を複数指定する理由**: テストごとに分けて実行すると、テストAがモジュールB の関数を間接的に動かす「間接カバレッジ」を取りこぼす。全テスト×全モジュールを同時計測して初めて実態が出る。
- **検出ツールの「安全側」は保留**: 同名関数がどのファイルの物か判断に迷ったとき「両方テスト済み扱い」にすると、本当は未テストの関数が済みに見えて漏れ検出という目的自体が壊れる（初回誤答→再テストで定着）。import 文（`from utils import foo`）は確実な証拠として解決に使える。ファイル名プレフィックスは表示上の区別であって紐付けの根拠ではない。
- **ファイル横断の呼び出しツリー統合をスコープ外にした理由**: import 解決（別名・as・同名の区別）が中途半端だと誤った親子関係を自信満々に表示するリスクがあるため、初期版は確実な情報（ファイル単位ツリー）に絞る。

### 2026-07-01 情報可視化の設計判断（SOW.md ベース）
- **多対多で密な紐付けにノードリンク図（二部グラフ）を使わない理由**: 線の交差（hairball）が原理上発生し、交差最小化は NP 困難で完全解消できない。隣接マトリクスは各紐付きに固有セルがあるため重なりゼロで、特定ペアの有無を交点で即確認できる（Ghoniem et al. 2004）。
- **preattentive processing（事前注意的処理）**: 色・位置・輝度などは意識的に探す前に並列処理され、約200ms 未満＝眼球運動を始める前に検知される。だから「テスト漏れを赤」にすると探さなくても飛び込んでくる。使いすぎると効果が消える（Ware の「タカ」原則）ので、強調は未カバーだけに絞る。
- **リスト↔マトリクスの切替閾値**: ノード合計（関数数＋テストクラス数）≤15 かつ疎（1関数あたり平均1〜2テスト）ならリストで十分。15超、または多対多が密（1関数が3テスト以上に紐づくケースが多い）ならマトリクスへ倒す。ノードリンク図はどの規模でも本用途では非推奨（唯一の優位タスク＝経路探索が該当しないため）。

## 決定事項

### 2026-07-06 複数ファイル解析対応の設計
- カバレッジは pytest **1回の実行**に `--cov=<module>` を複数指定して取る（間接カバレッジの取りこぼし防止）。coverage.json はファイル別なので行に由来ファイル（`row["file"]`）を付けて集計。
- 関数・テストクラスの表示名は**衝突したときだけ**リネーム（`ファイル名.関数名` / `test_file.py::Class`）。1ファイル選択時は従来表示を完全維持（後方互換）。
- 同名関数の紐付けは import 文のモジュール名（`from utils import foo`）で解決できる場合のみ確定。解決できなければ「保留」（両方テスト済み扱いは漏れ検出ツールとして最悪の偽表示になるため禁止）。
- ファイル横断の呼び出しツリー統合はスコープ外（import 解決が中途半端だと誤った親子関係を表示するリスク）。次フェーズ候補として todo.md に記載。
- 実装は Codex（gpt-5.5）へ委譲し、Claude（Fable）が設計・レビュー・複数ファイルE2Eテスト追加を担当。

### 2026-07-01 ツール構成の書き換え方針
- 既存の app.py は「2カラムリスト（形式1）」のみだったため、SOW ステップ0〜3 を実装する形へ書き換える。
- 方針: リスト改善（未テスト最上部固定・クラス単位グルーピング・記号併用）＋隣接マトリクス新規実装＋規模で自動推奨＋手動切替。
- details-on-demand（セルクリックで実コードをポップアップ / 関数クリックでジャンプ）は Streamlit で重いため今回スコープ外。ホバーのツールチップに留める。
- グルーピングの粒度: 1ファイル前提のため「機能モジュール」はクラス粒度まで。モジュール直下の関数は「(モジュール直下)」グループにまとめる。
- 配色: 赤/緑を避け赤/青＋記号併用（色覚多様性への配慮）。

### 2026-07-02 静的解析の限界を実測で確認し、静的×動的のハイブリッドへ
- **link_analyzer のテスト漏れ判定は偽陽性が出る（実測で確定）**: link_analyzer は「テストから名指し（`link_analyzer.xxx(...)`）で呼ばれた関数」しか証拠に拾えず、公開関数の内部で間接的に動く `_measure_function` などのヘルパーを一律「未テスト」と誤判定する。link_analyzer 自身を対象に `pytest --cov=link_analyzer --cov-branch` を回すと、誤判定されたヘルパーは実測で `_measure_function` 100%・`_visit_branch` 100%・`_make_insights` 86% とちゃんとカバーされていた。原因はコードを実行しない静的解析だから。
- **逆に動的計測でしか出ない本物の穴が見つかった**: `visit_comprehension`・`visit_FunctionDef`・`visit_AsyncFunctionDef` が行0%（内包表記/ネスト関数/`async def` をテストで一度も食わせていない）、`visit_Assign`/`visit_Call` が分岐50%。静的な名指し紐付けでは原理的に見えない。
- **役割分担の結論**: ①どの関数が実際に動いたか（カバレッジ）→ coverage.py / pytest-cov（動的）に置き換える。②複雑度・LOC 等の静的メトリクス → radon を採用（自前 `_ComplexityVisitor` を保守しなくて済む＋Halstead/MI も標準で出る。※「複雑度の正確さで radon が勝つ」わけではない）。③両者を突き合わせる薄い層を新設。
- **掛け合わせ層 `cross_check.py` を試作**: radon の複雑度 × coverage.json の関数別カバレッジを関数名（メソッドは `Class.method`）で突き合わせ、`リスク = 複雑度 ×（1 − 分岐カバレッジ率）` で降順表示。`複雑度≥6 かつ 分岐<100%` を ⚠。複雑度は「分かれ道の数」、分岐カバレッジは「実際に通った分かれ道」で対になる。
- **coverage の「受け取る」＝ coverage json**: `coverage report` は人間向けの表、`coverage json` は別プログラムが読む機械可読データ。掛け合わせ層は後者を受け取る。
- **限界（正直な認識）**: リスクは複雑度×未通過分岐なので、複雑度1で行0%（分岐なし）の関数は ⚠ に上がらない。単純だが未実行の関数は行% で別途拾う住み分け。
- ツール導入は `.venv/`（gitignore 済み）に pytest/pytest-cov/coverage/radon。`.coverage`・`coverage.json`・`.pytest_cache/` も gitignore に追加。

### 2026-07-02 貼り付けUIとカバレッジは両立しない → フォルダ解析モードで解決
- **矛盾の正体**: 貼り付けアプリは「2つのテキスト文字列を ast で読むだけ」で実体が無い。coverage.py は「本物のファイルのテストを実行して観測する」ため実体ファイルが必須。よって貼り付けた文字列にカバレッジは載せられない（水と油）。
- **解決策（てつてつ発案）**: コードを貼らせず、`workspace/` に置いた実ファイルを画面から選ばせる。処理側ファイルとテストファイルを選び、アプリがその場でテスト実行→カバレッジ測定→複雑度と突き合わせ。実体があるので coverage が普通に動く。
- **実装**: サイドバーでモード切替（貼り付け=静的マトリクス / フォルダ解析=カバレッジ×複雑度）。既存の貼り付けフローは壊さず、新モード選択時は `render_workspace_mode()` を描画して `st.stop()`。`cross_check.analyze_project(project_dir, cov_target, source_file, test_path)` が `python -m pytest --cov=... --cov-branch --cov-report=json:` を subprocess 実行し、radon と突き合わせて行リストを返す。一時 coverage.json は使用後に削除。
- **実行系の注意**: radon は PATH 非依存で確実に呼ぶため `python -m radon` を使う（Streamlit の venv から起動できる）。pytest は `--cov-report=json:<path>` で coverage.json を直接出せる。coverage の記録パスは cwd 依存で相対/絶対が揺れるため、ファイルキーは basename でも照合する（`_match_file_key`）。
- **セキュリティ**: 選んだテストを実際に実行する＝任意コード実行に相当。ローカル自用専用とし、画面にも明記。Web 公開はしない。
- **テスト**: AppTest で両モードのスモーク（切替・実行・表表示が例外なし）、cross_check は build_rows・load_coverage・basename照合・analyze_project(統合) を検証。全 51 件パス。
- **runtime 依存**: フォルダ解析は pytest/pytest-cov/coverage/radon を実行時に使うため requirements.txt に追加（貼り付けモードは従来どおり ast のみで外部依存なし）。

### 2026-07-02 UI 刷新: 「呼び出しツリー1枚」に統合（素人がテストを理解するため）
- **きっかけ（てつてつのフィードバック）**: 表が4つ5つに分かれ、同じ20関数が別々に出て繋がりが見えず「意味が伝わらない」。専門用語（特に造語「名指しなし」）を定義せず使ったのが不信の元。加えて「これでいい？と素人に設計を選ばせるな、見やすい形を決めるのはお前の仕事」。→ 設計はこちらが決めて出す方針へ。
- **本質要求**: 生成AIが作ったテストを「網羅的に・つながりが見える形で」理解したい。関数単位で全部を、呼び出しの親子で。
- **対応**: (1) link_analyzer に呼び出し関係抽出を追加（`_CallCollector` が関数本体の Call を走査、入れ子関数には潜らない。`_compute_calls` が素の名前を一意に解決して辺を張る）。(2) app.py を「全関数を親子でインデントした1枚のツリー表」に作り替え。列＝種類/複雑さ/担当テスト/動いた/カバー分岐%/状態。(3) 用語凡例を常設し造語を廃止。(4) 先頭に平文の「ひとことまとめ」。(5) マトリクス等は詳細expanderへ。
- **静的呼び出しグラフの限界（正直に）**: visitor パターンの `self.visit()`/`generic_visit()` のような動的 dispatch は静的に辿れないので、その経路のメソッドは親を持たず入口（根）として並ぶ。主要な公開関数→ヘルパーの鎖は辿れる。
- **教訓（メモリ化済み）**: 素人ユーザーには設計の二択を投げず、良い形をこちらで決めて作って見せる。用語は出すたびその場で定義し、造語なら「これは自分の言い方」と明示する。

### 2026-07-15 呼び出しグラフOSSツール PoC（フェーズ0）を実測 → pyan3 採用（FR-11 方針A）
要件 `docs/requirements-callgraph.md` のフェーズ0を実施。ファイル横断呼び出し(C1)・同名関数(C3)・動的dispatch(C2)を意図的に仕込んだ3ファイルのフィクスチャ（`app_main.run → storage.build_key → util_str.shout → normalize`、`normalize` は storage/util_str に同名別実装、`_Counter(ast.NodeVisitor)` で `visit → visit_Call` の動的dispatch）を作り、5ツール＋自前 `_CallCollector` を実走させて突き合わせた。環境は Python 3.11 + Graphviz 2.43。

- **一次結論: pyan3 は自前 `_CallCollector` を機能面で上回る（C1 を解消、C3 も正しく解決）**。実測エッジの比較：
  | エッジ | 種類 | 自前 `_CallCollector` | pyan3 | 動的(cProfile+gprof2dot) |
  |---|---|---|---|---|
  | `run → build_key` | C1 横断 | ❌ 欠落 | ✅ | ✅ |
  | `build_key → shout` | C1 横断 | ❌ 欠落 | ✅ | ✅ |
  | `build_key → normalize` | C3 同名 | ✅ storage版 | ✅ storage版 | ✅ storage版 |
  | `shout → normalize` | C3 同名 | ✅ util_str版 | ✅ util_str版 | ✅ util_str版 |
  | `visit → visit_Call` | C2 動的dispatch | ❌ | ❌（原理的に不可） | ✅（2×, 実行で捕捉） |
- **自前 `_CallCollector` はファイル横断(C1)を全て取りこぼすことが実測で確定**。`_compute_calls` はファイル単位で辺を張るため、`run → build_key`・`build_key → shout` のような別ファイル呼び出しが一切出ない（自前ツリーで `run` も `build_key` の子として `shout` も出ない）。C3（同名 `normalize`）は自前でも解決できたが、これは「2つの `normalize` がたまたま別ファイルで、ファイル単位に見ると各ファイル内で一意」だったため。**同一ファイル内に同名関数が2つある場合は `len(targets)==1` 条件で自前は保留（辺を張らない）に落ちる**のに対し、pyan3 は symtable のスコープ解決で正しく区別する（DOT の namespace 付きID `storage__normalize` / `util_str__normalize` で確認）。
- **C2（動的dispatch）は静的3ツール全滅、動的だけが捕捉**。visitorパターンの `NodeVisitor.visit` は `getattr(self, 'visit_'+type)` で分岐するため、pyan3・code2flow・自前のいずれも `visit → visit_Call` を静的に辿れない（＝要件 R-1 の通り原理的限界）。cProfile+gprof2dot は実行して `ast:414:visit → app_main:19:visit_Call`（呼び出し2回）を回数付きで捕捉。→ **静的で構造・動的で裏取り（FR-8）は実データで裏付けられた**。
- **各ツールの動作確認（Python 3.11 で全て可）**:
  - **pyan3**: `python -m pyan *.py --uses --defines`。`--text`（AIエージェント供給用、短縮名で表示）／`--dot`（namespace付きID、同名区別はこちらで確認可）／`--svg`/`--html`。C1・C3 の主役として採用。
  - **code2flow**: `code2flow *.py -o out.svg`、`--target-function run --downstream-depth N` で局所展開。**pip インストールは `--use-pep517` が必須**（素の `pip install code2flow` は setuptools の `install_layout` 廃止でwheelビルド失敗）。静的の副（全体一枚絵）として採用。
  - **pydeps**: `pydeps app_main.py --show-dot --no-show`。`util_str → storage → app_main` のモジュール依存を正しく検出。**関数ではなくモジュール粒度**（役割を混同しない）。
  - **gprof2dot**: `python -m gprof2dot -f pstats run.pstats`。**デフォルトは `--node-thres=0.5 --edge-thres=0.1` で軽い関数が刈られる**ので、小さい対象では `--node-thres=0 --edge-thres=0` を付けないと自作関数が消える（PoCで踏んだ）。ラベルは `module:lineno:funcname\n%\n(self%)\nN×` 形式。
  - **snakeviz**: インストール・import・pstats入力を確認。ブラウザ(icicle)起動系のためヘッドレスCIでの全経路検証は不可、導線のみ確認（NFR-4: URL手動オープン想定と整合）。
- **決定（FR-11 = 方針A採用）**: 静的コールグラフは **pyan3 に一本化**する（radon 導入と同じ「自前解析を保守対象から外す」判断）。自前 `_CallCollector`/`_compute_calls` は撤去または「簡易版」として詳細へ格納。
  - **ただし既存UI（インデント1枚ツリー）を捨てる必要はない**: pyan3 の DOT エッジ（namespace付きID）を読んで**同じインデントツリーを pyan3 のエッジから組み直せば**、C1（横断）と C3（同名）を直したまま「見慣れたツリー表」を維持できる（両取り）。フェーズ1の実装方針としてこれを第一候補にする。
  - リスク（要件 R-3）: pyan3 は2026年に開発再開直後。PoCの範囲（3.11・小規模）では安定動作を確認したが、大規模・別名import多用での安定性はフェーズ1で実コード（`link_analyzer.py` 自身など）に対して継続確認する。
- **前提**: Graphviz(`dot`) が全静的ツールで必須（`apt install graphviz`）。未導入時は落とさず導入手順を画面表示する（AC-5）。追加依存 `pyan3`/`code2flow`/`pydeps`/`gprof2dot`/`snakeviz` は実装フェーズで `requirements.txt` に追記予定（PoC段階ではまだ追記しない）。
- **PoCフィクスチャはスクラッチ限定でリポジトリ未コミット**（`workspace/` にわざと穴のある横断サンプルを足すのは todo の別項として実装フェーズで対応）。

### 2026-07-15 フェーズ1: ファイル横断コールグラフを pyan3 で実装（FR-1〜4）
PoCの方針A（静的は pyan3 へ委譲）を実装。新モジュール `callgraph.py` を追加し、app.py にパネルを統合。全117件パス（98→+19: callgraph単体17＋app AppTest2）。

- **pyan3 の DOT を「呼び出し辺」に変換する規則（実装の核）**: `python -m pyan <files> --uses --dot` の出力で、**`style="solid"` かつ両端が非モジュールノード**の辺だけが関数間の呼び出し。`dashed` は defines（モジュール→メンバ, クラス→メソッド）なので捨てる。モジュールノードは tooltip が2行（`name\npath`）で `:line` も `in` も無いことで判別（関数/メソッド/クラスは `qname\npath:line\nkind in scope`）。同名関数は pyan の namespace 付きノードID（`storage__normalize` / `util_str__normalize`）と tooltip の qname で区別できる（C3 解決）。
- **既存インデントツリーUIを捨てずに横断対応**: `build_order` を link_analyzer/app.build_tree_order と同じ意味論（入次数0を根・公開優先・DFS・重複畳み・孤立は末尾）で実装し、pyan のエッジから同じ形のツリーを組み直した。表示名は qname（`module.関数`）にして同名を区別。→ 「見慣れたツリー」を保ったまま C1（横断）と C3（同名）が直る両取り。
- **純粋関数と subprocess を分離してテスト可能に**: `parse_pyan_dot` / `build_order` / `build_subgraph_dot` は缶詰DOTで単体テスト（pyan非依存）。subprocess ラッパ（`generate_dot` / `render_svg` / `generate_text`）はツール未導入を monkeypatch で検証（NFR-9）。pyan 実走の統合テストは `@skipUnless(pyan_available())` でガード。
- **図の表示と保存で必要物が違う**: 表示は `st.graphviz_chart(dot)`（ブラウザ内 viz.js 描画なので**ローカル Graphviz 不要**）、SVG保存は `dot -Tsvg`（**ローカル Graphviz 必要**）。この非対称を利用し、Graphviz 未導入でも図は出す／保存ボタンだけ導入手順に差し替える設計。ツール未導入は一切 raise せず `analyze()` が `ok=False`+`hint` を返す（AC-5）。
- **絞り込みは pyan フラグでなく自前で**: pyan の `--depth` は名前空間のネスト深さで、呼び出し連鎖の深さではない。起点＋連鎖深さの絞り込みは `build_order(start=, max_depth=)` で自前実装した方が正確でテストしやすい（FR-2）。大規模（>60関数）は全体図を抑止して起点指定を促す（NFR-6）。
- **C2（動的dispatch）は静的では出せないまま**: `visit→visit_Call` 等は pyan でも辿れず入口として並ぶ。画面キャプションで明記し「実際に通ったかは上のカバレッジで裏取り」と誘導（フェーズ2で cProfile 側を並置予定）。
- **`use_container_width` は非推奨**（streamlit 1.59系）。`width="stretch"` を使う（st.graphviz_chart も width 対応済み）。
- **既存テストの回帰に注意**: 横断ツリー表を足したことで AppTest の「全dataframe走査」が別列の表で KeyError を起こした。`"関数" in df.columns` で対象表を絞って修正（新パネルは列名が異なる）。

### 2026-07-16 フェーズ2: 実行経路（動的）での裏取りを cProfile+gprof2dot で実装（FR-6/FR-8）
静的グラフ（pyan3）の下に「実行経路で裏取り」を追加。テストを cProfile 下で実行し、gprof2dot でコールグラフ化して静的と突き合わせる。全127件パス（117→+10）。

- **動的グラフの作り方**: `python -m cProfile -o <pstats> -m pytest <tests>` を project_dir で実行（既存カバレッジ実行とは別プロセス）→ `python -m gprof2dot -f pstats --node-thres=0 --edge-thres=0 <pstats>` で DOT 化。gprof2dot はデフォルト閾値（node 0.5% / edge 0.1%）で軽い関数を刈るので、小規模では **閾値0が必須**（PoC で確認済みの罠）。一時 pstats は finally で削除（NFR-7）。
- **gprof2dot ラベルの解釈**: `module:lineno:funcname\n<total%>\n(<self%>)\n<calls>×`。**module はファイルの stem** で pyan の tooltip の qname の頭（＝ファイル stem）と一致するため、静的↔動的の突き合わせキーを `(module_stem, funcname, 定義行)` に揃えられる。行番号は両者とも def 行を指すので概ね一致（デコレータで稀にずれるため比較は「近似」と明記）。
- **内包表記の疑似関数はノイズ**: cProfile は `<genexpr>`/`<listcomp>`/`<dictcomp>`/`<setcomp>`/`<lambda>` を独立コードオブジェクトとして記録する（3.11）。pyan は呼び出し対象として扱わないので、グラフ・比較の両方から `<...>` を除外しないと only_dynamic がそれらで埋まって意味が消える（実測で確認 → 除外後は差分が明快に）。
- **C2（動的dispatch）を実データで見せられた**: source 関数への呼び出しのうち **呼び元が外部（stdlib 等）の辺** = `dispatch_edges`。sample_module（visitorパターン）で `ast.visit → sample_module.visit_BoolOp / visit_comprehension / visit_Call ...` が出る。静的（pyan含む）ではこれらは根として並ぶだけ。「静的では入口に見えるが、実行では ast.visit の getattr dispatch で呼ばれている」を画面で提示できた。
- **突き合わせの3バケット（FR-8）**: only_static＝静的にあるが今回のテストで通らなかった呼び出し（テストの穴 or 実行時は別経路で解決）、only_dynamic＝実行で通ったが静的に無い source→source、both＝一致。sample_module では only_static=16・only_dynamic=0・both=10（only_dynamic が0なのは、静的が引けない経路が軒並み外部dispatch経由＝source→source ではないため。dispatch_edges 側に出る）。
- **重要なUXバグ修正（ラッチ）**: `if not st.button(...): st.stop()` は one-shot。動的裏取りのチェックボックスを押すと Streamlit が再実行し、ボタンは False に戻って `st.stop()` で**解析結果ごと消える**。`st.button` を `st.session_state["analyzed"]=True` にラッチし、以降の再実行でも解析を保持するよう修正。AppTest でチェック操作を検証して再発防止。
- **コスト**: 裏取りはチェックボックスで明示的にONにしたときだけ cProfile 実行（毎回のカバレッジ実行に加えて更にpytestを1回走らせるため）。ローカル自用前提なので許容。
- **snakeviz（FR-7 任意）**: 起動はアプリからせず、`cProfile -o profile.pstats -m pytest ...` と `snakeviz profile.pstats` のコマンドを画面に案内するだけに留めた（ブラウザ起動系はヘッドレス/WSL2で自動で開かない、NFR-4）。
