"""link_analyzer の単体テスト.

実際のテストの書き方 (self.target_func = 関数名 経由の呼び出し, 直接呼び出し)
を検証データに使い, 証拠B / 証拠C / 複雑度 / テスト漏れ検出が正しく働くかを
確認する.
"""

import unittest

import sample_module as link_analyzer


class TestAnalyzeSource(unittest.TestCase):
    """処理側解析: 関数抽出と複雑度計測."""

    def test_syntax_error_returned(self):
        """構文エラーは syntax_error に入る."""
        result = link_analyzer.analyze_source("def broken(:\n    pass")
        self.assertIsNotNone(result["syntax_error"])

    def test_simple_function_metrics(self):
        """分岐の無い関数は複雑度 1・ネスト 0."""
        src = "def foo(a, b):\n    return a + b\n"
        result = link_analyzer.analyze_source(src)
        m = result["functions"]["foo"]
        self.assertEqual(m["complexity"], 1)
        self.assertEqual(m["max_depth"], 0)
        self.assertEqual(m["arg_count"], 2)

    def test_branch_increases_complexity(self):
        """if / for / and が複雑度を増やす."""
        src = (
            "def foo(x):\n"
            "    if x and x > 0:\n"
            "        for i in range(x):\n"
            "            print(i)\n"
        )
        result = link_analyzer.analyze_source(src)
        m = result["functions"]["foo"]
        # base1 + if1 + and1 + for1 = 4.
        self.assertEqual(m["complexity"], 4)

    def test_nest_depth_measured(self):
        """ネストの深さが測れる."""
        src = (
            "def foo(x):\n"
            "    if x:\n"
            "        for i in x:\n"
            "            while i:\n"
            "                pass\n"
        )
        result = link_analyzer.analyze_source(src)
        m = result["functions"]["foo"]
        self.assertEqual(m["max_depth"], 3)

    def test_method_display_name(self):
        """クラス内メソッドは Class.method の表示名になる."""
        src = "class A:\n    def m(self):\n        pass\n"
        result = link_analyzer.analyze_source(src)
        self.assertIn("A.m", result["functions"])

    def test_raise_and_except_flags(self):
        """raise / except の有無を拾う."""
        src = (
            "def foo():\n"
            "    try:\n"
            "        raise ValueError('x')\n"
            "    except ValueError:\n"
            "        pass\n"
        )
        m = link_analyzer.analyze_source(src)["functions"]["foo"]
        self.assertTrue(m["has_raise"])
        self.assertTrue(m["has_except"])


class TestAnalyzeTests(unittest.TestCase):
    """テスト側解析: 証拠B / 証拠C の抽出."""

    def test_direct_call_is_evidence_c(self):
        """本体での直接呼び出しは direct に入る (証拠C)."""
        src = (
            "class TestX(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        update_zip_list_txt('bucket', 'folder/A')\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertIn("update_zip_list_txt", result["classes"]["TestX"]["direct"])

    def test_self_alias_is_evidence_b(self):
        """self.x = 関数名 -> self.x() は aliased に解決される (証拠B)."""
        src = (
            "class TestX(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        self.target_func = check_gcs_zip_http\n"
            "    def test_a(self):\n"
            "        self.target_func(MagicMock())\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertIn("check_gcs_zip_http", result["classes"]["TestX"]["aliased"])

    def test_self_call_without_assign_not_resolved(self):
        """代入の無い self.x() は解決されない (aliased に入らない)."""
        src = (
            "class TestX(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        self.helper()\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertNotIn("helper", result["classes"]["TestX"]["aliased"])

    def test_import_alias_resolved_in_evidence_b(self):
        """from main import main as main_func 経由の self 代入も元名へ解決."""
        src = (
            "from main import main as main_func\n"
            "class TestX(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        self.main = main_func\n"
            "    def test_a(self):\n"
            "        self.main(None)\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertIn("main", result["classes"]["TestX"]["aliased"])

    def test_function_scope_import_alias_resolved(self):
        """setUp 内の関数スコープ import も別名表に入る."""
        src = (
            "class TestX(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        from main import main as main_func\n"
            "        self.main = main_func\n"
            "    def test_a(self):\n"
            "        self.main(None)\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertIn("main", result["classes"]["TestX"]["aliased"])


class TestBuildLinks(unittest.TestCase):
    """紐付けと気付き."""

    def _run(self, src, test_src):
        s = link_analyzer.analyze_source(src)
        t = link_analyzer.analyze_tests(test_src)
        return link_analyzer.build_links(s, t)

    def test_evidence_c_links_class_to_function(self):
        """証拠C でクラスと関数が紐づく."""
        src = "def update_zip_list_txt(b, f):\n    return f\n"
        test_src = (
            "class TestUpdate(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        update_zip_list_txt('b', 'f')\n"
        )
        link = self._run(src, test_src)
        classes = [e["cls"] for e in link["func_to_tests"]["update_zip_list_txt"]]
        self.assertIn("TestUpdate", classes)

    def test_evidence_b_links_class_to_function(self):
        """証拠B (self 代入経由) でクラスと関数が紐づく."""
        src = "def check_gcs_zip_http(req):\n    return req\n"
        test_src = (
            "class TestCheck(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        self.target_func = check_gcs_zip_http\n"
            "    def test_a(self):\n"
            "        self.target_func(None)\n"
        )
        link = self._run(src, test_src)
        entries = link["func_to_tests"]["check_gcs_zip_http"]
        self.assertEqual(entries[0]["cls"], "TestCheck")
        self.assertEqual(entries[0]["via"], "B")

    def test_untested_function_detected(self):
        """どのテストにも紐づかない関数はテスト漏れとして出る."""
        src = (
            "def tested(x):\n    return x\n"
            "def orphan(x):\n    return x\n"
        )
        test_src = (
            "class TestT(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        tested(1)\n"
        )
        link = self._run(src, test_src)
        self.assertIn("orphan", link["untested"])
        self.assertNotIn("tested", link["untested"])

    def test_untested_produces_insight(self):
        """テスト漏れは気付き文言に反映される."""
        src = "def orphan(x):\n    return x\n"
        test_src = (
            "class TestT(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        pass\n"
        )
        link = self._run(src, test_src)
        joined = "\n".join(link["insights"])
        self.assertIn("orphan", joined)
        self.assertIn("テスト漏れ", joined)

    def test_ambiguous_name_goes_unresolved(self):
        """処理側に同名関数が複数あると解決保留になる."""
        src = (
            "class A:\n    def run(self):\n        pass\n"
            "class B:\n    def run(self):\n        pass\n"
        )
        test_src = (
            "class TestRun(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        run()\n"
        )
        link = self._run(src, test_src)
        self.assertIn("run", link["unresolved"]["TestRun"])

    def test_test_to_funcs_reverse_index(self):
        """テストクラスから紐づく処理関数を逆引きできる."""
        src = "def tested(x):\n    return x\n"
        test_src = (
            "class TestT(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        tested(1)\n"
        )
        link = self._run(src, test_src)
        funcs = [e["func"] for e in link["test_to_funcs"]["TestT"]]
        self.assertIn("tested", funcs)

    def test_empty_test_class_detected(self):
        """どの処理関数にも紐づかないテストクラスは空振りとして出る."""
        src = "def tested(x):\n    return x\n"
        test_src = (
            "class TestReal(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        tested(1)\n"
            "class TestGhost(unittest.TestCase):\n"
            "    def test_b(self):\n"
            "        nonexistent_func(1)\n"
        )
        link = self._run(src, test_src)
        self.assertIn("TestGhost", link["empty_tests"])
        self.assertNotIn("TestReal", link["empty_tests"])

    def test_empty_test_class_produces_insight(self):
        """空振りテストは気付き文言に反映される."""
        src = "def tested(x):\n    return x\n"
        test_src = (
            "class TestGhost(unittest.TestCase):\n"
            "    def test_b(self):\n"
            "        nonexistent_func(1)\n"
        )
        link = self._run(src, test_src)
        joined = "\n".join(link["insights"])
        self.assertIn("TestGhost", joined)
        self.assertIn("空振り", joined)

    def test_high_complexity_low_test_insight(self):
        """複雑度が高く紐づくテストが少ないと不足疑いが出る."""
        # 複雑度 10 以上になるよう if を並べる.
        body = "\n".join(f"    if x == {i}:\n        pass" for i in range(12))
        src = f"def heavy(x):\n{body}\n"
        test_src = (
            "class TestHeavy(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        heavy(1)\n"
        )
        link = self._run(src, test_src)
        joined = "\n".join(link["insights"])
        self.assertIn("テスト不足注意", joined)


class TestComplexityEdgeCases(unittest.TestCase):
    """複雑度計測の, 内包表記・入れ子関数・async 経路."""

    def test_内包表記の内側のifが複雑度に数えられる(self):
        """[x for x in y if x] の if は分岐として 1 数える."""
        src = "def f(y):\n    return [x for x in y if x]\n"
        result = link_analyzer.analyze_source(src)
        self.assertEqual(result["functions"]["f"]["complexity"], 2)

    def test_入れ子関数の分岐は外側の複雑度に含めない(self):
        """入れ子 def の中の if は外側関数の複雑度に足されない."""
        src = (
            "def outer(a):\n"
            "    def inner(b):\n"
            "        if b:\n"
            "            return 1\n"
            "    return inner\n"
        )
        result = link_analyzer.analyze_source(src)
        self.assertEqual(result["functions"]["outer"]["complexity"], 1)

    def test_入れ子関数も別の関数として計測される(self):
        """入れ子 def は独立した関数として複雑度が測られる."""
        src = (
            "def outer(a):\n"
            "    def inner(b):\n"
            "        if b:\n"
            "            return 1\n"
            "    return inner\n"
        )
        result = link_analyzer.analyze_source(src)
        self.assertEqual(result["functions"]["inner"]["complexity"], 2)

    def test_async関数も関数として抽出される(self):
        """async def はトップレベル関数として functions に入る."""
        src = "async def fetch(a):\n    return a\n"
        result = link_analyzer.analyze_source(src)
        self.assertIn("fetch", result["functions"])


class TestTestSideEdgeCases(unittest.TestCase):
    """テスト側解析の, 非self 呼び出し・連鎖属性・素 import・構文エラー."""

    def test_非selfのメソッド呼び出しは末尾名がdirectに入る(self):
        """helper.run() は run が direct に入る (証拠C 候補)."""
        src = (
            "class TestX(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        helper.run(1)\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertIn("run", result["classes"]["TestX"]["direct"])

    def test_連鎖属性呼び出しは最後の名前がdirectに入る(self):
        """a.b.c() は c が direct に入る."""
        src = (
            "class TestX(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        a.b.c(1)\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertIn("c", result["classes"]["TestX"]["direct"])

    def test_素のimport別名も元名へ解決される(self):
        """import runner as r 経由の直接呼び出しは runner へ読み替える."""
        src = (
            "import runner as r\n"
            "class TestX(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        r(1)\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertIn("runner", result["classes"]["TestX"]["direct"])

    def test_テスト側の構文エラーはsyntax_errorに入る(self):
        """壊れたテストコードは syntax_error が非 None になる."""
        result = link_analyzer.analyze_tests("class TestX(:\n    pass")
        self.assertIsNotNone(result["syntax_error"])

    def test_値が関数呼び出しのself代入は証拠Bにしない(self):
        """self.x = make() は Name 代入でないので aliased に解決しない."""
        src = (
            "class TestX(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        self.x = make()\n"
            "    def test_a(self):\n"
            "        self.x()\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertEqual(result["classes"]["TestX"]["aliased"], set())

    def test_self以外への素の代入は証拠Bにしない(self):
        """x = foo のローカル代入は self 属性でないので aliased に入らない."""
        src = (
            "class TestX(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        x = foo\n"
            "        x(1)\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertNotIn("foo", result["classes"]["TestX"]["aliased"])

    def test_名前でも属性でもない呼び出しでも壊れない(self):
        """get()() のような呼び出しでも例外なく解析でき, 内側名は拾える."""
        src = (
            "class TestX(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        get()(1)\n"
        )
        result = link_analyzer.analyze_tests(src)
        self.assertIn("get", result["classes"]["TestX"]["direct"])


class TestBuildLinksEdgeCases(unittest.TestCase):
    """紐付けの重複排除と, 行数・引数・ネストの気付き文言."""

    def _run(self, src, test_src):
        s = link_analyzer.analyze_source(src)
        t = link_analyzer.analyze_tests(test_src)
        return link_analyzer.build_links(s, t)

    def test_同一クラスがCとB両方で来ても紐付けは1件に重複排除される(self):
        """直接呼び出しと self 代入の両方があっても紐付けは 1 件."""
        src = "def foo(a):\n    return a\n"
        test_src = (
            "class TestFoo(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        self.foo = foo\n"
            "    def test_a(self):\n"
            "        foo(1)\n"
            "        self.foo(2)\n"
        )
        link = self._run(src, test_src)
        self.assertEqual(len(link["func_to_tests"]["foo"]), 1)

    def test_行数が多い関数は行数の気付きが出る(self):
        """行数が閾値 (50) 以上だと『行数が』を含む気付きが出る."""
        body = "\n".join(f"    x{i} = {i}" for i in range(55))
        src = f"def big(a):\n{body}\n"
        link = self._run(src, "class TestT(unittest.TestCase):\n    pass\n")
        joined = "\n".join(link["insights"])
        self.assertIn("行数が", joined)

    def test_引数が多い関数は引数の気付きが出る(self):
        """引数が閾値 (5) 以上だと『引数が』を含む気付きが出る."""
        src = "def wide(a, b, c, d, e):\n    return a\n"
        link = self._run(src, "class TestT(unittest.TestCase):\n    pass\n")
        joined = "\n".join(link["insights"])
        self.assertIn("引数が", joined)

    def test_ネストが深い関数はネストの気付きが出る(self):
        """入れ子の深さが閾値 (4) 以上だと『ネスト』を含む気付きが出る."""
        src = (
            "def deep(a):\n"
            "    if a:\n"
            "        for i in a:\n"
            "            while i:\n"
            "                with open('x') as f:\n"
            "                    pass\n"
        )
        link = self._run(src, "class TestT(unittest.TestCase):\n    pass\n")
        joined = "\n".join(link["insights"])
        self.assertIn("ネスト", joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
