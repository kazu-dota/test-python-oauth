"""ローカル学習用の共通設定。実ユーザーの情報は扱わない。"""
import base64
import hashlib
from html import escape
from fastapi.responses import HTMLResponse

CLIENT_ID = "print-app"
REDIRECT_URI = "http://localhost:8000/callback"
AUTH_URL = "http://localhost:8001"
API_URL = "http://localhost:8002"
# 学習用の公開された固定値。本番用の資格情報ではありません。
API_USER = "photo-api"
API_PASSWORD = "local-demo-only"

def challenge(verifier: str) -> str:
    """PKCEの秘密の値から、認可画面へ送る照合用の値を作る。

    SHA-256で計算した結果をURLで扱えるBase64文字列へ変換する。
    末尾の「=」を取り除くところまでが、S256方式の計算に含まれる。
    元のverifierは保存し、コード交換のときにだけ発行元へ送る。

    Args:
        verifier: 印刷アプリが作ったランダム文字列（code_verifier）。

    Returns:
        認可リクエストに指定するcode_challenge文字列。
    """
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

def page(title: str, body: str, status: int = 200) -> HTMLResponse:
    """共通の見た目とヘッダーを持つHTMLの返事を作る。

    Args:
        title: ページのタイトル。HTMLとして解釈されないように変換する。
        body: 本文のHTML。呼び出し元が作る信頼済みのHTMLを渡す。
            外部から受け取った値を埋め込む場合は、先にescapeする。
        status: HTTPの返事の番号。通常は成功を表す200。

    Returns:
        キャッシュ抑止などのヘッダーを付けたHTMLResponse。
    """
    return HTMLResponse(f'''<!doctype html><html lang="ja"><meta charset="utf-8">
    <title>{escape(title)}</title><style>
    body {{font-family:system-ui;max-width:850px;margin:48px auto;padding:0 24px;line-height:1.8;background:#f4f7fb;color:#183047}}
    main {{background:white;padding:32px;border-radius:16px}} a,button {{font-size:16px}}
    button {{padding:12px 20px;margin:8px;cursor:pointer}} pre {{white-space:pre-wrap;background:#eef3f8;padding:16px}}
    </style><main><p>Pythonで学ぶOAuth / ローカル学習用</p><h1>{escape(title)}</h1>{body}</main></html>''', status_code=status,
    headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"})