"""app.py の 2 モード（貼り付け / フォルダ解析）のスモークテスト.

Streamlit の AppTest でスクリプトを実際に走らせ、モード切替と
フォルダ解析の実行結果表示が例外なく成立することを確認する。
フォルダ解析は workspace/ の実ファイルに対して pytest を実行するため、
外部プロセスの実行を伴う（モックしない：本物の経路を通すことに意味がある）。
"""

from streamlit.testing.v1 import AppTest


def test_初期表示は貼り付けモードで入力を促す():
    at = AppTest.from_file("app.py").run(timeout=30)
    assert not at.exception
    # 既定（貼り付け）はコード未入力なので入力を促す info が出る。
    assert any("解析する" in i.value for i in at.info)


def test_フォルダ解析モードに切り替えても例外が出ない():
    at = AppTest.from_file("app.py").run(timeout=30)
    at.radio[0].set_value("フォルダ解析（カバレッジ×複雑度）").run(timeout=30)
    assert not at.exception


def test_フォルダ解析でリスク表が表示される():
    at = AppTest.from_file("app.py").run(timeout=30)
    at.radio[0].set_value("フォルダ解析（カバレッジ×複雑度）").run(timeout=30)
    # 「解析する」を押すとテスト実行→カバレッジ測定→表表示。
    at.button[0].click().run(timeout=90)
    assert not at.exception
    assert len(at.dataframe) >= 1
