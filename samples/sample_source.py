"""デモ用の処理側コード（main.py 相当）。

可視化ツールの動作確認用。GCS に zip を上げる小さなユーティリティを模した例。
わざと「テスト漏れの関数」「複雑な関数」「クラスのメソッド」を混ぜてある。
"""


def normalize_path(path):
    """先頭と末尾のスラッシュを整える。"""
    return path.strip("/")


def validate_bucket(name):
    """バケット名の簡易バリデーション。"""
    if not name:
        return False
    if len(name) < 3 or len(name) > 63:
        return False
    if name != name.lower():
        return False
    return True


def build_object_key(bucket, folder, name):
    """バケット・フォルダ・ファイル名からオブジェクトキーを組み立てる。"""
    folder = normalize_path(folder)
    return f"{folder}/{name}"


def update_zip_list(bucket, folder):
    """フォルダ内の zip 一覧テキストを更新する（わざと複雑にしてある）。"""
    if not bucket:
        raise ValueError("bucket is required")
    folder = normalize_path(folder)
    result = []
    for i in range(10):
        if i % 2 == 0 and i > 0:
            result.append(f"{folder}/part-{i}.zip")
        elif i == 0:
            continue
        else:
            if i > 5:
                result.append(f"{folder}/tail-{i}.zip")
    return result


def check_zip_http(req):
    """HTTP リクエストから zip の存在をチェックする。"""
    if req is None:
        return {"status": 400}
    return {"status": 200}


def summarize_report(items):
    """集計レポートを作る（このツールではテスト漏れの例）。"""
    total = 0
    for it in items:
        if it.get("ok"):
            total += 1
    return {"count": len(items), "ok": total}


class ZipUploader:
    """zip アップロードを担うクラス。"""

    def upload(self, data):
        """データをアップロードする。"""
        if not data:
            return False
        return True

    def retry(self, n):
        """リトライする（これもテスト漏れの例）。"""
        for _ in range(n):
            pass
        return n
