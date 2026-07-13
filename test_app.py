"""app.py（テスト理解ビューア）のスモークテスト.

AppTest でスクリプトを実際に走らせ、ファイル選択→解析実行で、まとめ文と
全関数ツリー表が例外なく描画されることを確認する。workspace/ の実ファイルに
対して pytest を実行するため外部プロセスの実行を伴う（本物の経路に意味がある）。
"""

import os

from streamlit.testing.v1 import AppTest

_WORKSPACE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


def test_初期表示は解析ボタンを出し例外が出ない():
    at = AppTest.from_file("app.py").run(timeout=30)
    assert not at.exception
    assert any(b.label == "解析する" for b in at.button)


def test_解析するとツリー表が例外なく出る():
    at = AppTest.from_file("app.py").run(timeout=30)
    at.button[0].click().run(timeout=90)
    assert not at.exception
    assert len(at.dataframe) >= 1


def test_まとめ文と親子ツリーの手掛かりが出る():
    at = AppTest.from_file("app.py").run(timeout=30)
    at.button[0].click().run(timeout=90)
    text = " ".join(m.value for m in at.markdown)
    # 素人向けのまとめ文が出る。
    assert "ひとことまとめ" in " ".join(h.value for h in at.subheader) or "実際に動いた" in text
    # ツリー表に少なくとも 1 関数分の行がある。
    df = at.dataframe[0].value
    assert len(df) >= 1


def test_ファイル横断の呼び出しグラフのセクションが例外なく出る():
    # pyan3 と Graphviz(dot) が入っている前提の環境で、呼び出しグラフの
    # セクション見出しが描画され、スクリプト全体が例外なく走ることを確認する。
    at = AppTest.from_file("app.py").run(timeout=30)
    at.button[0].click().run(timeout=120)
    assert not at.exception
    headings = " ".join(h.value for h in at.subheader)
    assert "呼び出しグラフ" in headings


def test_処理側が複数ファイルでもファイルごとのツリー表が出る():
    # workspace/ には常設の処理側が 1 ファイルしかないため、2 ファイル目を
    # 一時的に足して複数ファイル経路（統合解析＋ファイル別セクション）を通す。
    extra_src = os.path.join(_WORKSPACE, "second_module.py")
    extra_test = os.path.join(_WORKSPACE, "test_second_module.py")
    with open(extra_src, "w", encoding="utf-8") as f:
        f.write("def add(a, b):\n    return a + b\n")
    with open(extra_test, "w", encoding="utf-8") as f:
        f.write(
            "import unittest\n"
            "from second_module import add\n\n\n"
            "class TestAdd(unittest.TestCase):\n"
            "    def test_足し算(self):\n"
            "        self.assertEqual(add(1, 2), 3)\n"
        )
    try:
        at = AppTest.from_file("app.py").run(timeout=30)
        at.button[0].click().run(timeout=120)
        assert not at.exception
        # 処理側 2 ファイル分のセクション（＝ツリー表 2 枚）が出る。
        assert len(at.dataframe) >= 2
        # 追加した方の関数もいずれかの表に載っている。
        names = [
            str(row) for df in at.dataframe for row in df.value["関数"].tolist()
        ]
        assert any("add" in n for n in names)
    finally:
        os.remove(extra_src)
        os.remove(extra_test)
