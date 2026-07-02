"""cross_check の掛け合わせロジックの単体テスト.

subprocess で radon を呼ぶ load_complexity は外部プロセス依存なので、
ここでは純粋関数である build_rows（リスク計算・注意フラグ・並び順）と、
coverage.json をパースする load_coverage の振る舞いを検証する。
"""

import json
import os
import tempfile
import unittest

import cross_check


class TestBuildRows(unittest.TestCase):
    """複雑度とカバレッジの突き合わせ."""

    def test_複雑度が高く分岐が低いほどリスク上位に来る(self):
        complexity = {"heavy": {"complexity": 10, "rank": "C"},
                      "light": {"complexity": 2, "rank": "A"}}
        coverage = {"heavy": {"line_pct": 50.0, "branch_pct": 50.0},
                    "light": {"line_pct": 50.0, "branch_pct": 50.0}}
        rows = cross_check.build_rows(complexity, coverage)
        self.assertEqual(rows[0]["name"], "heavy")

    def test_複雑度と未通過分岐の積がリスクになる(self):
        complexity = {"f": {"complexity": 10, "rank": "C"}}
        coverage = {"f": {"line_pct": 40.0, "branch_pct": 40.0}}
        rows = cross_check.build_rows(complexity, coverage)
        # 10 * (1 - 0.4) = 6.0
        self.assertAlmostEqual(rows[0]["risk"], 6.0)

    def test_複雑で分岐未達の関数は注意フラグが立つ(self):
        complexity = {"f": {"complexity": 6, "rank": "B"}}
        coverage = {"f": {"line_pct": 80.0, "branch_pct": 80.0}}
        rows = cross_check.build_rows(complexity, coverage)
        self.assertTrue(rows[0]["attention"])

    def test_複雑でも分岐100なら注意フラグは立たない(self):
        complexity = {"f": {"complexity": 20, "rank": "F"}}
        coverage = {"f": {"line_pct": 100.0, "branch_pct": 100.0}}
        rows = cross_check.build_rows(complexity, coverage)
        self.assertFalse(rows[0]["attention"])

    def test_複雑度が閾値未満なら分岐が低くても注意しない(self):
        complexity = {"f": {"complexity": 3, "rank": "A"}}
        coverage = {"f": {"line_pct": 10.0, "branch_pct": 10.0}}
        rows = cross_check.build_rows(complexity, coverage)
        self.assertFalse(rows[0]["attention"])

    def test_カバレッジ側にしか無い関数はリスク0で注意しない(self):
        complexity = {}
        coverage = {"only_cov": {"line_pct": 0.0, "branch_pct": 0.0}}
        rows = cross_check.build_rows(complexity, coverage)
        self.assertEqual(rows[0]["risk"], 0.0)
        self.assertFalse(rows[0]["attention"])


class TestLoadCoverage(unittest.TestCase):
    """coverage.json のパース."""

    def _write_coverage(self, functions: dict) -> str:
        data = {"files": {"target.py": {"functions": functions}}}
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.addCleanup(os.remove, path)
        return path

    def test_モジュール直下は突き合わせ対象から除外される(self):
        path = self._write_coverage({
            "": {"summary": {"percent_covered": 100.0,
                             "percent_branches_covered": 100.0}},
            "foo": {"summary": {"percent_covered": 90.0,
                                "percent_branches_covered": 80.0}},
        })
        result = cross_check.load_coverage(path, "target.py")
        self.assertNotIn("", result)
        self.assertIn("foo", result)

    def test_対象ファイルが無ければKeyErrorになる(self):
        path = self._write_coverage({"foo": {"summary": {
            "percent_covered": 100.0, "percent_branches_covered": 100.0}}})
        with self.assertRaises(KeyError):
            cross_check.load_coverage(path, "存在しない.py")


if __name__ == "__main__":
    unittest.main()
