"""cross_check の掛け合わせロジックの単体テスト.

subprocess で radon を呼ぶ load_complexity は外部プロセス依存なので、
ここでは純粋関数である build_rows（リスク計算・注意フラグ・並び順）と、
coverage.json をパースする load_coverage の振る舞いを検証する。
"""

import json
import os
import sys
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

    def test_行には由来ファイルを付けられる(self):
        complexity = {"f": {"complexity": 1, "rank": "A"}}
        coverage = {"f": {"line_pct": 100.0, "branch_pct": 100.0}}
        rows = cross_check.build_file_rows("alpha.py", complexity, coverage)
        self.assertEqual(rows[0]["file"], "alpha.py")


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


class TestMatchFileKey(unittest.TestCase):
    """coverage.json のファイルキー照合（相対/絶対の揺れ吸収）."""

    def test_完全一致のキーをそのまま返す(self):
        files = {"pkg/mod.py": {}}
        self.assertEqual(cross_check._match_file_key(files, "pkg/mod.py"), "pkg/mod.py")

    def test_ファイル名一致でキーを拾う(self):
        # coverage 側が絶対パスでも, 渡した相対名の basename で拾える.
        files = {"/abs/path/to/mod.py": {}}
        self.assertEqual(
            cross_check._match_file_key(files, "mod.py"), "/abs/path/to/mod.py"
        )

    def test_一致が無ければKeyError(self):
        with self.assertRaises(KeyError):
            cross_check._match_file_key({"a.py": {}}, "b.py")


class TestAnalyzeProject(unittest.TestCase):
    """実ファイルのテスト実行〜複雑度×カバレッジ突き合わせ（統合）.

    workspace/ の本物のファイルに対して pytest を実際に走らせる。
    外部プロセスの実行を伴うが, 実測経路そのものに意味があるためモックしない。
    """

    def _workspace(self):
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(here, "workspace")

    def test_サンプルを解析するとテストが通り関数行が返る(self):
        result = cross_check.analyze_project(
            project_dir=self._workspace(),
            cov_target="sample_module",
            source_file="sample_module.py",
            test_path="test_sample_module.py",
        )
        self.assertTrue(result["ok"])
        self.assertGreater(len(result["rows"]), 0)

    def test_一時的なcoverage_jsonを残さない(self):
        cross_check.analyze_project(
            project_dir=self._workspace(),
            cov_target="sample_module",
            source_file="sample_module.py",
            test_path="test_sample_module.py",
        )
        leftover = os.path.join(self._workspace(), ".cross_check_cov.json")
        self.assertFalse(os.path.exists(leftover))

    def test_複数ファイルを解析すると各行の由来ファイルが分かる(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_file(tmpdir, "alpha.py", "def a():\n    return 1\n")
            self._write_file(tmpdir, "beta.py", "def b():\n    return 2\n")
            self._write_file(
                tmpdir,
                "test_alpha.py",
                "from alpha import a\n\n"
                "def test_a():\n"
                "    assert a() == 1\n",
            )
            self._write_file(
                tmpdir,
                "test_beta.py",
                "from beta import b\n\n"
                "def test_b():\n"
                "    assert b() == 2\n",
            )
            result = cross_check.analyze_project(
                project_dir=tmpdir,
                cov_target=["alpha", "beta"],
                source_file=["alpha.py", "beta.py"],
                test_path=["test_alpha.py", "test_beta.py"],
                python=sys.executable,
            )
        files = {row["file"] for row in result["rows"]}
        self.assertTrue(result["ok"])
        self.assertEqual(files, {"alpha.py", "beta.py"})

    def test_coverageに無いファイルでも複雑度行は返る(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_file(tmpdir, "alpha.py", "def a():\n    return 1\n")
            self._write_file(tmpdir, "beta.py", "def b():\n    return 2\n")
            self._write_file(
                tmpdir,
                "test_alpha.py",
                "from alpha import a\n\n"
                "def test_a():\n"
                "    assert a() == 1\n",
            )
            result = cross_check.analyze_project(
                project_dir=tmpdir,
                cov_target=["alpha"],
                source_file=["alpha.py", "beta.py"],
                test_path=["test_alpha.py"],
                python=sys.executable,
            )
        beta_rows = [row for row in result["rows"] if row["file"] == "beta.py"]
        self.assertTrue(result["ok"])
        self.assertEqual(beta_rows[0]["line_pct"], None)
        self.assertIn("beta.py", result["error"])

    def test_処理側またはテストが空なら実行せずエラーを返す(self):
        result = cross_check.analyze_project(
            project_dir=self._workspace(),
            cov_target=[],
            source_file=[],
            test_path=[],
        )
        self.assertFalse(result["ok"])
        self.assertIn("1 つ以上", result["error"])

    def _write_file(self, directory: str, filename: str, content: str) -> None:
        path = os.path.join(directory, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


if __name__ == "__main__":
    unittest.main()
