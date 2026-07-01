"""デモ用のテストコード（unittest 形式）。

証拠C（直接呼び出し）と証拠B（self への代入経由）の両方、
それに「どの関数にも紐づかない空振りテスト」を混ぜてある。
"""

import unittest

from main import check_zip_http


class TestNormalize(unittest.TestCase):
    def test_strips_slash(self):
        self.assertEqual(normalize_path("/a/b/"), "a/b")


class TestValidateBucket(unittest.TestCase):
    def test_rejects_empty(self):
        self.assertFalse(validate_bucket(""))

    def test_accepts_valid(self):
        self.assertTrue(validate_bucket("my-bucket"))


class TestBuildKey(unittest.TestCase):
    def test_builds_key(self):
        # build_object_key と normalize_path の両方を呼ぶ（1テストが多関数をカバー）
        key = build_object_key("b", "/folder/", "x.zip")
        normalize_path("/folder/")
        self.assertEqual(key, "folder/x.zip")


class TestUpdateZipBasic(unittest.TestCase):
    def test_returns_list(self):
        self.assertIsInstance(update_zip_list("b", "f"), list)


class TestUpdateZipEdge(unittest.TestCase):
    def test_empty_folder(self):
        update_zip_list("b", "")


class TestUpdateZipError(unittest.TestCase):
    def test_missing_bucket_raises(self):
        # update_zip_list を 3 つのクラスがカバー（多対多で密＝マトリクス向き）
        with self.assertRaises(ValueError):
            update_zip_list("", "f")


class TestCheckZipHttp(unittest.TestCase):
    def setUp(self):
        # 証拠B: self への代入経由で対象関数を保持する書き方
        self.target = check_zip_http

    def test_none_request(self):
        self.assertEqual(self.target(None)["status"], 400)


class TestZipUploader(unittest.TestCase):
    def test_upload_empty(self):
        # メソッド名の直接呼び出し（ZipUploader.upload に解決される）
        uploader = ZipUploader()
        self.assertFalse(uploader.upload(None))


class TestGhost(unittest.TestCase):
    def test_calls_removed_function(self):
        # どの処理関数にも紐づかない「空振りテスト」の例
        removed_helper(123)


if __name__ == "__main__":
    unittest.main()
