"""callgraph（pyan3 委譲のファイル横断コールグラフ層）の単体テスト.

純粋関数（DOT 解析・ツリー化・サブグラフ DOT）はツール非依存の缶詰 DOT で検証し,
subprocess ラッパはツール未導入フォールバック（NFR-9）を monkeypatch で検証する.
pyan3 が入っている環境では実行統合（ファイル横断エッジが出ること）も検証する.
"""

import os
import tempfile
import unittest

import callgraph as cg

# pyan3 の `--uses --dot` 実出力を模した缶詰（実測フォーマット 2026-07-15）。
# 3 ファイル: util_str / storage / app_main。normalize が storage/util_str に同名で存在。
# run -> build_key -> {storage.normalize, shout -> util_str.normalize} の横断チェーン。
SAMPLE_DOT = r'''digraph G {
    graph [rankdir=LR];
        "app_main" [label="app_main", tooltip="app_main\n/x/app_main.py"];
        "storage" [label="storage", tooltip="storage\n/x/storage.py"];
        "util_str" [label="util_str", tooltip="util_str\n/x/util_str.py"];
        "app_main__run" [label="run", tooltip="app_main.run\n/x/app_main.py:8\nfunction in app_main"];
        "storage__build_key" [label="build_key", tooltip="storage.build_key\n/x/storage.py:11\nfunction in storage"];
        "storage__normalize" [label="normalize", tooltip="storage.normalize\n/x/storage.py:6\nfunction in storage"];
        "util_str__normalize" [label="normalize", tooltip="util_str.normalize\n/x/util_str.py:4\nfunction in util_str"];
        "util_str__shout" [label="shout", tooltip="util_str.shout\n/x/util_str.py:9\nfunction in util_str"];
        "app_main" -> "app_main__run" [style="dashed",  color="#838b8b"];
        "storage" -> "util_str__shout" [style="solid",  color="#000000"];
        "app_main__run" -> "storage__build_key" [style="solid",  color="#000000"];
        "storage__build_key" -> "storage__normalize" [style="solid",  color="#000000"];
        "storage__build_key" -> "util_str__shout" [style="solid",  color="#000000"];
        "util_str__shout" -> "util_str__normalize" [style="solid",  color="#000000"];
}
'''


class TestParseDot(unittest.TestCase):
    """DOT 解析: ノード種別の判定と呼び出し辺の抽出."""

    def setUp(self):
        self.nodes, self.edges = cg.parse_pyan_dot(SAMPLE_DOT)

    def test_module_nodes_flagged(self):
        """モジュールノードは is_module=True（tooltip に :line も in も無い）."""
        self.assertTrue(self.nodes["app_main"]["is_module"])
        self.assertTrue(self.nodes["storage"]["is_module"])

    def test_function_node_parsed(self):
        """関数ノードは qname/file/line/kind を持つ."""
        n = self.nodes["storage__build_key"]
        self.assertEqual(n["qname"], "storage.build_key")
        self.assertEqual(n["file"], "/x/storage.py")
        self.assertEqual(n["line"], 11)
        self.assertEqual(n["kind"], "function")
        self.assertFalse(n["is_module"])

    def test_same_name_distinguished(self):
        """同名 normalize は別 id・別 qname として区別される（C3）."""
        self.assertEqual(self.nodes["storage__normalize"]["qname"], "storage.normalize")
        self.assertEqual(self.nodes["util_str__normalize"]["qname"], "util_str.normalize")

    def test_only_solid_nonmodule_edges_kept(self):
        """solid かつ両端が非モジュールの辺だけが呼び出しとして残る."""
        pairs = {(self.nodes[s]["qname"], self.nodes[d]["qname"]) for s, d in self.edges}
        self.assertIn(("app_main.run", "storage.build_key"), pairs)          # C1 横断
        self.assertIn(("storage.build_key", "util_str.shout"), pairs)        # C1 横断
        self.assertIn(("storage.build_key", "storage.normalize"), pairs)     # C3 同名解決
        self.assertIn(("util_str.shout", "util_str.normalize"), pairs)       # C3 同名解決

    def test_dashed_edge_dropped(self):
        """dashed（defines）は呼び出しに含めない."""
        pairs = {(s, d) for s, d in self.edges}
        self.assertNotIn(("app_main", "app_main__run"), pairs)

    def test_module_level_use_dropped(self):
        """モジュールが絡む solid 辺（import レベル）は落とす."""
        pairs = {(s, d) for s, d in self.edges}
        self.assertNotIn(("storage", "util_str__shout"), pairs)


class TestBuildOrder(unittest.TestCase):
    """ツリー化: 入口検出・横断ネスト・絞り込み・サイクル安全性."""

    def setUp(self):
        self.nodes, self.edges = cg.parse_pyan_dot(SAMPLE_DOT)

    def _tree(self, **kw):
        order = cg.build_order(self.nodes, self.edges, **kw)
        return [(self.nodes[nid]["qname"], depth) for nid, depth in order]

    def test_root_is_entry_function(self):
        """入次数0の run が根（深さ0）."""
        tree = self._tree()
        self.assertIn(("app_main.run", 0), tree)

    def test_cross_file_nesting(self):
        """横断チェーンが親子で入れ子になる（run→build_key→shout→util_str.normalize）."""
        tree = self._tree()
        depth = {name: d for name, d in tree}
        self.assertEqual(depth["app_main.run"], 0)
        self.assertEqual(depth["storage.build_key"], 1)
        self.assertEqual(depth["util_str.shout"], 2)
        self.assertEqual(depth["util_str.normalize"], 3)

    def test_start_and_depth_filter(self):
        """起点=build_key・深さ1 で、build_key とその直接の子だけになる."""
        sid = "storage__build_key"
        tree = self._tree(start=sid, max_depth=1)
        names = [name for name, _ in tree]
        self.assertEqual(tree[0], ("storage.build_key", 0))
        self.assertIn("util_str.shout", names)          # 深さ1の子
        self.assertIn("storage.normalize", names)        # 深さ1の子
        self.assertNotIn("util_str.normalize", names)    # 深さ2 は打ち切り

    def test_cycle_safety(self):
        """相互再帰（a↔b）でも無限ループせず有限で返る."""
        dot = (
            '"m" [label="m", tooltip="m\\n/x/m.py"];\n'
            '"m__a" [label="a", tooltip="m.a\\n/x/m.py:1\\nfunction in m"];\n'
            '"m__b" [label="b", tooltip="m.b\\n/x/m.py:2\\nfunction in m"];\n'
            '"m__a" -> "m__b" [style="solid"];\n'
            '"m__b" -> "m__a" [style="solid"];\n'
        )
        nodes, edges = cg.parse_pyan_dot(dot)
        order = cg.build_order(nodes, edges)
        self.assertTrue(order)  # 例外を出さず何か返る
        self.assertLessEqual(len(order), 4)


class TestSubgraphDot(unittest.TestCase):
    """絞り込み後の画像用 DOT 生成."""

    def test_only_selected_nodes_and_internal_edges(self):
        nodes, edges = cg.parse_pyan_dot(SAMPLE_DOT)
        selected = ["storage__build_key", "storage__normalize"]
        dot = cg.build_subgraph_dot(nodes, edges, selected)
        self.assertIn('"storage__build_key"', dot)
        self.assertIn("storage.build_key", dot)                 # ラベルは qname
        self.assertIn('"storage__build_key" -> "storage__normalize"', dot)
        self.assertNotIn("util_str__shout", dot)                 # 非選択は出ない
        self.assertTrue(dot.strip().startswith("digraph"))


class TestFallback(unittest.TestCase):
    """ツール未導入でも落とさず導入手順を返す（NFR-9 / AC-5）."""

    def test_analyze_without_pyan(self):
        orig = cg.pyan_available
        cg.pyan_available = lambda: False
        try:
            r = cg.analyze(["/x/a.py"])
        finally:
            cg.pyan_available = orig
        self.assertFalse(r["ok"])
        self.assertIn("pip install pyan3", r["hint"])

    def test_generate_dot_missing_file(self):
        with self.assertRaises(cg.CallgraphError):
            cg.generate_dot(["/no/such/file_12345.py"])

    def test_generate_dot_empty(self):
        with self.assertRaises(cg.CallgraphError):
            cg.generate_dot([])

    def test_render_svg_without_graphviz(self):
        orig = cg.shutil.which
        cg.shutil.which = lambda name: None
        try:
            with self.assertRaises(cg.CallgraphError) as ctx:
                cg.render_svg("digraph{a->b}")
        finally:
            cg.shutil.which = orig
        self.assertIn("graphviz", ctx.exception.hint.lower())


@unittest.skipUnless(cg.pyan_available(), "pyan3 未導入のため統合テストをスキップ")
class TestIntegrationWithPyan(unittest.TestCase):
    """pyan3 を実際に走らせ、ファイル横断エッジが出ることを確認（AC-1）."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        files = {
            "util_str.py": "def normalize(t):\n    return t.strip()\n\n"
            "def shout(t):\n    return normalize(t).upper()\n",
            "storage.py": "from util_str import shout\n\n"
            "def normalize(p):\n    return p.strip('/')\n\n"
            "def build_key(folder, name):\n"
            "    folder = normalize(folder)\n"
            "    return folder + '/' + shout(name)\n",
            "app_main.py": "from storage import build_key\n\n"
            "def run(folder, name):\n    return build_key(folder, name)\n",
        }
        self.paths = []
        for fn, src in files.items():
            p = os.path.join(self.tmp, fn)
            with open(p, "w") as f:
                f.write(src)
            self.paths.append(p)

    def test_cross_file_edges_present(self):
        r = cg.analyze(self.paths)
        self.assertTrue(r["ok"])
        cross = {(r["nodes"][s]["qname"], r["nodes"][d]["qname"]) for s, d in r["cross_file_edges"]}
        self.assertIn(("app_main.run", "storage.build_key"), cross)
        self.assertIn(("storage.build_key", "util_str.shout"), cross)

    def test_same_name_resolved_to_correct_file(self):
        """build_key が呼ぶ normalize は storage 版（同名の util_str 版ではない）."""
        r = cg.analyze(self.paths)
        edges = {(r["nodes"][s]["qname"], r["nodes"][d]["qname"]) for s, d in r["call_edges"]}
        self.assertIn(("storage.build_key", "storage.normalize"), edges)
        self.assertIn(("util_str.shout", "util_str.normalize"), edges)


if __name__ == "__main__":
    unittest.main()
