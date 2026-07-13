"""callgraph（pyan3 統合層）の単体テスト.

subprocess で pyan3/dot を呼ぶ部分は外部プロセス依存なので、ここでは純粋関数
（コマンド組み立て・DOT のノード/エッジ計数）と、ツール未導入時のフォールバック
挙動（落ちずにエラー文字列を返すか）を検証する。実際の pyan3 起動を伴う統合確認は
PoC（docs/knowledge.md 2026-07-13）と AppTest 側で担保する。
"""

import unittest

import callgraph


class TestBuildPyanCommand(unittest.TestCase):
    """コマンド列の組み立て（副作用なし）."""

    def test_基本形はusesのみ_definesは辺にしない(self):
        cmd = callgraph.build_pyan_command("py", ["a.py", "b.py"])
        self.assertEqual(cmd[:3], ["py", "-m", "pyan"])
        self.assertIn("a.py", cmd)
        self.assertIn("b.py", cmd)
        self.assertIn("--uses", cmd)
        self.assertIn("--no-defines", cmd)
        self.assertIn("--dot", cmd)

    def test_起点関数を渡すとfunctionとdirectionが付く(self):
        cmd = callgraph.build_pyan_command(
            "py", ["a.py"], function="mod.foo", direction="down"
        )
        self.assertIn("--function", cmd)
        self.assertIn("mod.foo", cmd)
        self.assertIn("--direction", cmd)
        self.assertIn("down", cmd)

    def test_起点関数が無ければfunctionは付かない(self):
        cmd = callgraph.build_pyan_command("py", ["a.py"], function=None)
        self.assertNotIn("--function", cmd)

    def test_不正な方向はbothに丸める(self):
        cmd = callgraph.build_pyan_command(
            "py", ["a.py"], function="mod.foo", direction="sideways"
        )
        i = cmd.index("--direction")
        self.assertEqual(cmd[i + 1], "both")

    def test_粒度depthが渡る(self):
        cmd = callgraph.build_pyan_command("py", ["a.py"], depth="1")
        i = cmd.index("--depth")
        self.assertEqual(cmd[i + 1], "1")

    def test_textフォーマットを選べる(self):
        cmd = callgraph.build_pyan_command("py", ["a.py"], fmt="text")
        self.assertIn("--text", cmd)
        self.assertNotIn("--dot", cmd)


class TestDotCounting(unittest.TestCase):
    """DOT のノード/エッジ計数."""

    DOT = (
        'digraph G {\n'
        '    "mod__foo" [label="foo"];\n'
        '    "mod__bar" [label="bar"];\n'
        '    "mod__foo" -> "mod__bar";\n'
        '}\n'
    )

    def test_ノード数はlabel行を数える(self):
        self.assertEqual(callgraph.count_dot_nodes(self.DOT), 2)

    def test_エッジ数は矢印行を数える(self):
        self.assertEqual(callgraph.count_dot_edges(self.DOT), 1)

    def test_空文字列は0(self):
        self.assertEqual(callgraph.count_dot_nodes(""), 0)
        self.assertEqual(callgraph.count_dot_edges(""), 0)


class TestFallbacks(unittest.TestCase):
    """ツール未導入・空入力でも落ちずにエラーを返す."""

    def test_対象ファイルが空ならエラー(self):
        r = callgraph.run_pyan([], cwd=".", python="python3")
        self.assertFalse(r["ok"])
        self.assertIn("ファイル", r["error"])

    def test_pyan未導入ならインストール案内を返す(self):
        # import できないダミーモジュール名を渡して未導入経路を通す。
        original = callgraph.module_available
        callgraph.module_available = lambda module, python=None: False
        try:
            r = callgraph.run_pyan(["a.py"], cwd=".", python="python3")
        finally:
            callgraph.module_available = original
        self.assertFalse(r["ok"])
        self.assertIn("pyan3", r["error"])

    def test_dot未導入なら描画はインストール案内を返す(self):
        original = callgraph.dot_available
        callgraph.dot_available = lambda: False
        try:
            r = callgraph.render_dot("digraph G {}", cwd=".")
        finally:
            callgraph.dot_available = original
        self.assertFalse(r["ok"])
        self.assertIn("graphviz", r["error"].lower())


if __name__ == "__main__":
    unittest.main()
