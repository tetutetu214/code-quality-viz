# todo.md — タスク管理

## 完了（2026-07-01）
- [x] projects/code-quality-viz にフォルダ作成・作りかけコードを配置
- [x] SOW.md の方針で書き換え
  - [x] エンジンに逆引き（test_to_funcs）・空列検出（empty_tests）・空振り気付きを追加
  - [x] 規模判定（ノード数・密度でリスト/マトリクスを自動推奨）
  - [x] リスト改善（未テスト最上部固定・クラス単位グルーピング・記号併用）
  - [x] 隣接マトリクス新規実装（空行=薄赤／空列=薄橙／縦書き列見出し／クロスヘア／並べ替え）
  - [x] カバレッジ%サマリ・色覚配慮（赤/青＋記号）
  - [x] st.components.v1.html → st.html へ移行（非推奨解消）
- [x] 単体テスト 20 件パス、AppTest でリスト/マトリクス両経路の実機検証

## 完了（2026-07-01 追加対応）
- [x] リスト表示を削除しマトリクスのみに（規模判定・表示切替ラジオも撤去）
- [x] 複雑さの説明を平易化（「この表の見方」expander・行ごとの評価⚠/気になる点・気付き文言から専門語を除去）

## 完了（2026-07-02）
- [x] link_analyzer 自身を pytest --cov で実測し、テスト漏れ判定が偽陽性であることを確認
- [x] radon 採用を決定（自前 _ComplexityVisitor は保守対象外へ）
- [x] 掛け合わせ層 cross_check.py を試作（複雑度×実カバレッジ、リスク降順・⚠フラグ）
- [x] cross_check の単体テスト 8 件パス
- [x] knowledge.md に静的×動的ハイブリッドの知見を記録

## 完了（2026-07-02 追加）
- [x] ⚠ の関数に実テスト追加 → link_analyzer を行・分岐とも 100% に（テスト 20→35 件）
- [x] cross_check を app.py へ統合（フォルダ解析モード新設）
  - [x] workspace/ に実ファイルを置き、画面から処理側/テストを選んで実行する方式
  - [x] cross_check.analyze_project() 追加（pytest --cov 実行→radon→突き合わせ）
  - [x] coverage.json のファイルキーを basename でも照合（相対/絶対の揺れ吸収）
  - [x] 貼り付け（静的）/ フォルダ解析（動的）をサイドバーのモード切替で並存
  - [x] AppTest スモーク 3 件・cross_check 統合テスト追加 → 全 51 件パス

## 完了（2026-07-02 UI 全面刷新）
- [x] 貼り付け/モード切替を撤去し「フォルダ解析1本」へ一本化
- [x] link_analyzer に呼び出し関係の抽出を追加（_CallCollector / _compute_calls）
- [x] 出力を「全関数を呼び出しの親子でぶら下げたツリー表1枚」に作り替え
  - [x] 各行に 種類(公開/ヘルパー)・複雑さ・担当テスト・動いた・カバー分岐%・状態
  - [x] 用語の凡例パネルを常設（造語「名指しなし」は廃止）
  - [x] 素人向け「ひとことまとめ」を先頭に
  - [x] マトリクス・気付き・pytestログは詳細expanderへ格納
- [x] AppTest を新UIに更新、全51件パス

## 完了（2026-07-06 複数ファイル解析対応）
- [x] 処理側・テストファイルを st.multiselect で複数選択可能に（デフォルト=全ファイル）
- [x] cross_check.analyze_project を複数対応（pytest 1回実行で --cov 複数指定、行に由来ファイル付与）
- [x] link_analyzer に analyze_source_files / analyze_test_files を追加（統合名前空間、衝突時のみ `ファイル名.関数名` / `test_file.py::Class` にリネーム）
- [x] 同名関数は import 文のモジュール名で解決、解決不能は「保留」維持
- [x] 一部ファイルのみ構文エラー時はファイル名付きでエラー表示
- [x] 呼び出しツリーはファイルごとのセクション表示（ファイル横断ツリー統合はスコープ外）
- [x] テスト 51→98 件パス（複数ファイルE2E含む）。実装は Codex 委譲、レビュー・E2E追加は Claude

## 次フェーズ：呼び出しグラフ機能の強化（要件 = docs/requirements-callgraph.md）
OSS調査を要件化。自前 _CallCollector の限界（ファイル横断×／動的dispatch×）を実績OSSで埋める。
静的×動的ハイブリッドを踏襲（radon 採用時と同じ「自前を保守対象から外す」判断）。
- [x] フェーズ0: PoC（Python 3.11+Graphviz で pyan3/code2flow/pydeps/gprof2dot/snakeviz を実コードで検証、採否確定、knowledge.md に記録 2026-07-15）
  - 横断/同名/動的dispatch を仕込んだ3ファイルfixtureで5ツール＋自前を実走比較。全ツール Python 3.11 で動作確認（code2flow は `--use-pep517` 必須）。
  - 実測: pyan3 が C1(横断) を解消し C3(同名) も symtable で正しく解決。動的(cProfile+gprof2dot)のみ C2(動的dispatch `visit→visit_Call`) を捕捉 → FR-8 の静的×動的補完を実データで裏付け。
- [x] フェーズ0: 自前 _CallCollector の撤去可否を pyan3 のファイル横断解決の実測で判断 → **FR-11 方針A採用**（静的は pyan3 に一本化。ただし既存インデントツリーUIは pyan3 のエッジから組み直して維持＝両取りをフェーズ1第一候補に）
- [x] フェーズ1: pyan3 でファイル横断の静的コールグラフ統合＋起点/深さ絞り込み＋画像書き出し（FR-1〜4）2026-07-15
  - `callgraph.py` 新設: `python -m pyan --uses --dot` を subprocess 実行→DOT解析（solid×非モジュール辺=呼び出し）→qnameで同名区別→横断ツリー生成→絞り込み(起点+深さ)→サブグラフDOT/SVG。ツール未導入は導入手順付きで非致命(AC-5)。
  - app.py に「ファイル横断コールグラフ」パネル追加（st.graphviz_chart で図表示・SVG保存・pyan text をFR-4詳細に・横断エッジ一覧をC1証拠として表示）。既存表示は非改変(FR-9/10)。
  - test_callgraph.py 17件（DOTパース/ツリー/絞り込み/サブグラフ/フォールバック/pyan統合）＋app AppTestスモーク2件。全117件パス。
  - requirements.txt に pyan3 追記。README に機能・Graphviz前提・VS Code Call Hierarchy運用を追記。
- [ ] フェーズ1: pydeps のモジュール依存図・循環import検出パネル（FR-5, 任意・未着手）
- [x] フェーズ2: cProfile+gprof2dot の実行経路グラフ、静的×動的の並置（FR-6, FR-8）2026-07-16
  - callgraph.py に動的層を追加: pytest を `python -m cProfile -o pstats -m pytest` で実行→`gprof2dot -f pstats`→DOT解析。ラベル `module:line:func` からモジュール=stemで source 判定、内包表記の疑似関数(`<genexpr>`等)は除外。一時 pstats は削除(NFR-7)。
  - 突き合わせ `compare_static_dynamic`（キー=モジュール/関数名/定義行, 近似）で only_static（静的にあるが未実行）/ only_dynamic を算出。外部→source の `dispatch_edges`（`ast.visit→visit_*`）を C2 の証拠として抽出。
  - app.py: 静的パネル下に「実行経路（動的）で裏取り」をチェックボックスで追加。実行経路グラフ・メトリクス・動的dispatch一覧・未通過呼び出し一覧を表示。gprof2dot 未導入は導入手順(AC-5)。
  - **副次修正**: 「解析する」ボタンを session_state でラッチ（one-shot ボタンだとチェック操作の再実行で解析結果が消えるUXバグを修正）。
  - test 9件（gprof2dotパース/dispatch辺/内包表記除外/比較/フォールバック/実走統合）＋app 動的スモーク1件。全127件パス。
- [x] フェーズ2: snakeviz の icicle 階層ツリー導線（任意, FR-7）→ 起動はせず、`cProfile -o` + `snakeviz` のコマンドを画面に案内（WSL2でURL手動オープン想定, NFR-4）
- [ ] フェーズ3: 用語凡例・限界注記・README（Graphviz導入/VS Code Call Hierarchy 運用）・requirements.txt 追記（★ Graphviz/VS Code/requirements はフェーズ1・2で対応済み。用語凡例の常設だけ残）

## 次にやること（候補）
- [x] ファイル横断の呼び出しツリー統合（→ 上記フェーズ計画として要件化。docs/requirements-callgraph.md）
- [ ] てつてつの実機フィードバック反映（ツリーの見やすさ・列の要不要）
- [ ] workspace サンプルに「わざと穴がある版」を足し、⚠ が出る例も見せる
- [ ] 呼び出しツリーの限界メモ（visitorパターン等の動的dispatchは静的に辿れない）
- [ ] 依存が多いプロジェクトを解析する場合の venv 指定
- [ ] details-on-demand（セルクリックで実コード対応をポップアップ）※今回スコープ外
- [ ] 列（テスト）側の並べ替え・seriation（現状は入力順固定）
- [ ] 数百規模でのモジュール階層化・フィルタ（SOW ステップ2 の大規模対応）
