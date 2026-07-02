"""app.py（テスト理解ビューア）のスモークテスト.

AppTest でスクリプトを実際に走らせ、ファイル選択→解析実行で、まとめ文と
全関数ツリー表が例外なく描画されることを確認する。workspace/ の実ファイルに
対して pytest を実行するため外部プロセスの実行を伴う（本物の経路に意味がある）。
"""

from streamlit.testing.v1 import AppTest


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
