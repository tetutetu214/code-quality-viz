"""処理側コードとテストコードを AST で解析し, テストクラスと処理関数の
紐付け・複雑度・テスト漏れの気付きを静的に求めるエンジン.

方針:
- 処理側: ファイル内で定義された関数 / メソッドを一覧化し, 各々の複雑度
  (循環的複雑度・行数・引数の数・ネスト深さ) を計測する.
- テスト側: unittest のテストクラスごとに, そのクラスが対象にしている
  処理関数を次の 2 つの証拠から求める.
    証拠C: テストメソッド本体で処理関数を素の名前で直接呼んでいる.
    証拠B: setUp などで self.x = 関数名 と一段だけ代入し, その self.x を
           呼んでいる. 一段の代入のみ解決する (深い変数追跡はしない).
- LLM は使わない. AST の Call / Assign / FunctionDef だけを根拠にする.
"""

import ast
from collections import defaultdict


# ---------------------------------------------------------------------
# 処理側の解析
# ---------------------------------------------------------------------
class _ComplexityVisitor(ast.NodeVisitor):
    """1 つの関数本体をたどり, 循環的複雑度とネスト深さを測る.

    循環的複雑度は「分岐を作るノード数 + 1」で近似する.
    数える対象: if / for / while / and / or / except / with / assert /
    comprehension の各 if / 三項演算子.
    """

    # 分岐を 1 つ増やすノード.
    _BRANCH_NODES = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.ExceptHandler,
        ast.With,
        ast.AsyncWith,
        ast.Assert,
        ast.IfExp,
    )
    # ネストの深さを 1 段増やすノード.
    _NEST_NODES = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.With,
        ast.AsyncWith,
        ast.Try,
    )

    def __init__(self):
        self.complexity = 1
        self.max_depth = 0
        self._depth = 0

    def visit_BoolOp(self, node):
        # and / or は分岐を (被演算子の数 - 1) だけ増やす.
        self.complexity += len(node.values) - 1
        self.generic_visit(node)

    def _visit_branch(self, node):
        if isinstance(node, self._BRANCH_NODES):
            self.complexity += 1
        if isinstance(node, self._NEST_NODES):
            self._depth += 1
            self.max_depth = max(self.max_depth, self._depth)
            self.generic_visit(node)
            self._depth -= 1
        else:
            self.generic_visit(node)

    # 分岐 / ネスト対象ノードをまとめて処理する.
    visit_If = _visit_branch
    visit_For = _visit_branch
    visit_AsyncFor = _visit_branch
    visit_While = _visit_branch
    visit_With = _visit_branch
    visit_AsyncWith = _visit_branch
    visit_Try = _visit_branch
    visit_ExceptHandler = _visit_branch
    visit_Assert = _visit_branch
    visit_IfExp = _visit_branch

    def visit_comprehension(self, node):
        # 内包表記の各 if は分岐.
        self.complexity += len(node.ifs)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        # 入れ子関数の中には潜らない (別関数として測るため).
        pass

    visit_AsyncFunctionDef = visit_FunctionDef


def _measure_function(node) -> dict:
    """関数定義ノードから複雑度指標を測る."""
    body_visitor = _ComplexityVisitor()
    for child in node.body:
        body_visitor.visit(child)

    # 引数の数 (self / cls も含めた素の数).
    args = node.args
    arg_count = (
        len(args.posonlyargs)
        + len(args.args)
        + len(args.kwonlyargs)
        + (1 if args.vararg else 0)
        + (1 if args.kwarg else 0)
    )

    # 行数 (定義行から末尾行まで).
    start = node.lineno
    end = getattr(node, "end_lineno", node.lineno)
    loc = end - start + 1

    # raise / except / 比較演算子の有無 (今後の気付き用に保持).
    has_raise = any(isinstance(n, ast.Raise) for n in ast.walk(node))
    has_except = any(isinstance(n, ast.ExceptHandler) for n in ast.walk(node))

    return {
        "complexity": body_visitor.complexity,
        "max_depth": body_visitor.max_depth,
        "arg_count": arg_count,
        "loc": loc,
        "has_raise": has_raise,
        "has_except": has_except,
    }


class _SourceCollector(ast.NodeVisitor):
    """処理側ファイルから関数 / メソッドを集め, 各々を計測する."""

    def __init__(self):
        # 表示名 -> 指標 dict.
        self.functions = {}
        # 素の名前 -> 表示名のリスト (呼び出し解決用).
        self.simple_to_display = defaultdict(list)
        self._class_stack = []

    def visit_ClassDef(self, node):
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def _register(self, node):
        simple = node.name
        if self._class_stack:
            display = f"{self._class_stack[-1]}.{simple}"
        else:
            display = simple
        self.functions[display] = _measure_function(node)
        self.simple_to_display[simple].append(display)

    def visit_FunctionDef(self, node):
        self._register(node)
        # 入れ子関数も拾えるよう潜るが, ネスト計測は _measure 側で閉じている.
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._register(node)
        self.generic_visit(node)


def analyze_source(source: str) -> dict:
    """処理側コードを解析する.

    Returns:
        dict:
            functions: dict[str, dict]        関数表示名 -> 指標
            simple_to_display: dict[str,list] 素の名前 -> 表示名リスト
            syntax_error: str or None
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"syntax_error": f"{e.msg} (line {e.lineno})"}

    collector = _SourceCollector()
    collector.visit(tree)
    simple_map = {
        k: list(v) for k, v in collector.simple_to_display.items()
    }
    return {
        "functions": collector.functions,
        "simple_to_display": simple_map,
        "syntax_error": None,
    }


# ---------------------------------------------------------------------
# テスト側の解析
# ---------------------------------------------------------------------
class _TestClassVisitor(ast.NodeVisitor):
    """1 つのテストクラスを解析し, 呼んでいる素の名前を集める.

    証拠B: self.x = Name の代入を記録し (一段のみ), 後で self.x() を
           その Name へ読み替える.
    証拠C: 素の名前での直接呼び出し foo() を記録する.
    """

    def __init__(self):
        # self 属性名 -> 代入された素の関数名 (一段のみ).
        self.self_alias = {}
        # 直接呼び出しされた素の名前の集合 (証拠C).
        self.direct_calls = set()
        # self.x() として呼ばれた属性名の集合 (証拠B の解決対象).
        self.self_attr_calls = set()

    def visit_Assign(self, node):
        # self.x = 名前 の形だけを一段で拾う.
        if isinstance(node.value, ast.Name) and len(node.targets) == 1:
            tgt = node.targets[0]
            if (
                isinstance(tgt, ast.Attribute)
                and isinstance(tgt.value, ast.Name)
                and tgt.value.id == "self"
            ):
                self.self_alias[tgt.attr] = node.value.id
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Name):
            # foo(...) -> 直接呼び出し (証拠C).
            self.direct_calls.add(func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "self":
                # self.x(...) -> 証拠B の解決候補.
                self.self_attr_calls.add(func.attr)
            else:
                # obj.method(...) -> 末尾名を直接呼び出し候補として拾う.
                self.direct_calls.add(func.attr)
        elif isinstance(func, ast.Attribute):
            self.direct_calls.add(func.attr)
        self.generic_visit(node)


def _collect_import_aliases(tree) -> dict:
    """import 文から「別名 -> 元の名前」の対応表を作る.

    from main import check_gcs_zip_http        -> {check_gcs_zip_http: 同じ}
    from main import main as main_func         -> {main_func: main}
    import os as o                             -> {o: os}

    これにより self.x = main_func のようにローカルの別名を経由した代入も,
    元の関数名へ読み替えられる (証拠B の解決精度を上げる).
    """
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local = alias.asname or alias.name
                aliases[local] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                # import a.b.c as x の元名は末尾 (呼び出し解決に合わせる).
                original = alias.name.split(".")[-1]
                aliases[local] = original
    return aliases


def analyze_tests(source: str) -> dict:
    """テスト側コードを解析し, テストクラスごとの呼び出し名を返す.

    Returns:
        dict:
            classes: dict[str, dict]  クラス名 -> {direct, aliased}
                direct: 直接呼び出しの素の名前集合 (証拠C)
                aliased: self 代入経由で解決された素の名前集合 (証拠B)
            syntax_error: str or None
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"syntax_error": f"{e.msg} (line {e.lineno})"}

    # import の別名表. ファイル全体で 1 つ持てば十分.
    import_aliases = _collect_import_aliases(tree)

    classes = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        visitor = _TestClassVisitor()
        for child in node.body:
            visitor.visit(child)

        # 証拠B: self.x() のうち, self.x = 名前 で解決できたものを実名に変換.
        # 代入された名前が import の別名なら, 元の関数名へさらに読み替える.
        aliased = set()
        for attr in visitor.self_attr_calls:
            if attr in visitor.self_alias:
                assigned = visitor.self_alias[attr]
                resolved = import_aliases.get(assigned, assigned)
                aliased.add(resolved)

        # 直接呼び出しも, import 別名なら元名へ読み替える.
        direct = {import_aliases.get(n, n) for n in visitor.direct_calls}

        classes[node.name] = {
            "direct": direct,
            "aliased": aliased,
        }

    return {"classes": classes, "syntax_error": None}


# ---------------------------------------------------------------------
# 紐付けと気付き
# ---------------------------------------------------------------------
def build_links(src_result: dict, test_result: dict) -> dict:
    """処理側とテスト側の解析結果を突き合わせ, 紐付けと気付きを作る.

    Returns:
        dict:
            functions: dict[str, dict]     処理関数 -> 指標 (処理側そのまま)
            func_to_tests: dict[str, list] 処理関数 -> 紐づくテストクラス
                            各要素 {"cls": クラス名, "via": "C" or "B"}
            test_to_funcs: dict[str, list] テストクラス -> 紐づく処理関数
                            各要素 {"func": 関数表示名, "via": "C" or "B"}
                            (マトリクスの列側・空列判定に使う逆引き)
            all_tests: list[str]           テストクラス名の全一覧 (順序保持)
            untested: list[str]            どのテストにも紐づかない関数
            empty_tests: list[str]         どの処理関数にも紐づかないテストクラス
            unresolved: dict[str, list]    クラス -> 実関数に解決できなかった名前
            insights: list[str]            気付きの文言リスト
    """
    functions = src_result["functions"]
    simple_to_display = src_result["simple_to_display"]

    func_to_tests = defaultdict(list)
    test_to_funcs = defaultdict(list)
    unresolved = defaultdict(list)

    # テストクラスの一覧は入力順を保つ (マトリクスの列順に使う).
    all_tests = list(test_result["classes"].keys())

    for cls_name, calls in test_result["classes"].items():
        # 証拠C と B のそれぞれで, 素の名前を処理関数の表示名へ解決する.
        for via, names in (("C", calls["direct"]), ("B", calls["aliased"])):
            for simple in names:
                targets = simple_to_display.get(simple, [])
                if len(targets) == 1:
                    func = targets[0]
                    # 同じクラス-関数の重複は避ける (C と B 両方で来ることがある).
                    existing = {t["cls"] for t in func_to_tests[func]}
                    if cls_name not in existing:
                        func_to_tests[func].append({"cls": cls_name, "via": via})
                        test_to_funcs[cls_name].append({"func": func, "via": via})
                elif len(targets) >= 2:
                    # 同名関数が処理側に複数. 曖昧なので解決保留.
                    unresolved[cls_name].append(simple)
                # len 0 は外部呼び出し. 無視する.

    # テスト漏れ: 処理関数のうち紐づくテストが 1 つも無いもの (空の行).
    untested = sorted(f for f in functions if f not in func_to_tests)
    # 無駄なテスト候補: どの処理関数にも紐づかないテストクラス (空の列).
    empty_tests = [t for t in all_tests if t not in test_to_funcs]

    # 気付きを組み立てる.
    insights = _make_insights(functions, func_to_tests, untested, empty_tests)

    return {
        "functions": functions,
        "func_to_tests": {k: v for k, v in func_to_tests.items()},
        "test_to_funcs": {k: v for k, v in test_to_funcs.items()},
        "all_tests": all_tests,
        "untested": untested,
        "empty_tests": empty_tests,
        "unresolved": {k: sorted(set(v)) for k, v in unresolved.items()},
        "insights": insights,
    }


# 複雑度の目安しきい値. 一次的な基準として保持する.
_COMPLEXITY_WARN = 10
_LOC_WARN = 50
_ARG_WARN = 5
_DEPTH_WARN = 4


def _make_insights(functions, func_to_tests, untested, empty_tests=()) -> list:
    """静的指標から気付きの文言を作る."""
    insights = []

    # 1) テスト漏れ (空の行).
    for name in untested:
        insights.append(f"テスト漏れ疑い: 『{name}』はどのテストクラスからも紐づいていません。")

    # 2) 無駄なテスト候補 (空の列): どの処理関数にも紐づかないテストクラス.
    for cls_name in empty_tests:
        insights.append(
            f"空振りテスト疑い: 『{cls_name}』はどの処理関数にも紐づきませんでした。"
            "対象が別ファイル・モック・解決不能な呼び出しの可能性。"
        )

    # 3) 複雑すぎる関数 (専門語を避けた平易な言い回しにする).
    for name, m in sorted(functions.items()):
        reasons = []
        if m["complexity"] >= _COMPLEXITY_WARN:
            reasons.append(f"分かれ道の数（複雑度）が {m['complexity']}")
        if m["loc"] >= _LOC_WARN:
            reasons.append(f"行数が {m['loc']}")
        if m["arg_count"] >= _ARG_WARN:
            reasons.append(f"引数が {m['arg_count']} 個")
        if m["max_depth"] >= _DEPTH_WARN:
            reasons.append(f"入れ子の深さ（ネスト）が {m['max_depth']}")
        if reasons:
            insights.append(
                f"複雑すぎ注意: 『{name}』は{'、'.join(reasons)}。"
                "バグが入りやすくテストしにくいので、小さい関数に分けるのを検討。"
            )

    # 4) 複雑なのに紐づくテストが少ない不均衡.
    for name, m in sorted(functions.items()):
        test_count = len(func_to_tests.get(name, []))
        if m["complexity"] >= _COMPLEXITY_WARN and test_count <= 1:
            insights.append(
                f"テスト不足注意: 『{name}』は分かれ道の数（複雑度）が {m['complexity']} と多いのに、"
                f"確認しているテストが {test_count} 個だけ。抜けている確認観点があるかも。"
            )

    return insights
