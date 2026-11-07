"""利用者が操作する写真印刷アプリ。秘密の値はサーバー内に保持。"""
import json
import secrets
import time
from html import escape
from urllib.parse import urlencode
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from common import CLIENT_ID, REDIRECT_URI, AUTH_URL, API_URL, challenge, page

app = FastAPI(title="学習用 写真印刷アプリ")
sessions = {}

@app.get("/")
def home():
    """GET /で、連携を始めるためのトップ画面を表示する。

    Returns:
        通常の連携リンクと、権限不足の実験用リンクを含むHTMLResponse。
    """
    return page("写真印刷アプリ", '''<p>写真サービスからAliceの写真一覧を取得します。</p>
    <p>まず、別サービスの許可画面で写真の読み取りを許可してください。</p>
    <p><a href="/connect">写真サービスと連携する</a></p>
    <details><summary>権限不足の実験</summary><a href="/connect?experiment=no-scope">読み取り権限を要求せず連携する</a></details>''')

@app.get("/connect")
def connect(experiment: str = ""):
    """GET /connectで連携の準備をし、ブラウザーを許可画面へ送る。

    セッション番号、state、PKCEの秘密の値を別々に生成する。
    stateと秘密の値はsessionsに保存し、Cookieには番号だけを入れる。
    この関数が認可サーバーへHTTP通信するのではなく、302の返事を
    受け取ったブラウザーが認可サーバーへGETする。

    Args:
        experiment: no-scopeなら写真を読む権限を要求しない実験を行う。
            それ以外は通常のphotos.read権限を要求する。

    Returns:
        許可画面への移動先とclient_session Cookieを含む302の返事。
    """
    sid, state, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    sessions[sid] = {"state": state, "verifier": verifier, "exp": time.time()+300}
    params = dict(response_type="code", client_id=CLIENT_ID, redirect_uri=REDIRECT_URI,
        scope="" if experiment == "no-scope" else "photos.read", state=state,
        code_challenge=challenge(verifier), code_challenge_method="S256")
    response = RedirectResponse(AUTH_URL + "/authorize?" + urlencode(params), status_code=302)
    response.set_cookie("client_session", sid, httponly=True, samesite="lax", max_age=300)
    return response

@app.get("/callback")
async def callback(request: Request, state: str = "", code: str = "", error: str = ""):
    """GET /callbackで戻りを受け、コード交換と写真取得を順に行う。

    まずstateを照合する。利用者が拒否した場合はここで終了する。
    許可された場合だけ、印刷アプリからPOST /token、GET /photosを送る。
    利用証をURLや画面へ出さず、サーバー間のヘッダーに付けて利用する。

    Args:
        request: client_session Cookieを読むためのリクエスト情報。
        state: 認可サーバーからURLで戻ってきた操作の照合番号。
        code: 許可されたときに戻ってくる認可コード。
        error: 拒否されたときのaccess_deniedなどのエラー文字列。

    Returns:
        成功時は写真一覧と値を伏せた通信履歴を含むHTMLResponse。
        拒否時は案内画面、不正な戻りは400、権限不足は403、
        HTTP通信の失敗は502の画面を返す。
    """
    sid = request.cookies.get("client_session", "")
    item = sessions.pop(sid, None)
    if not item or item["exp"] < time.time() or not secrets.compare_digest(state, item["state"]):
        return page("連携を中止しました", "<p>stateが一致しないか、操作の有効期限が切れています。</p><a href='/'>最初から</a>", 400)
    if error:
        return page("アクセスは許可されませんでした", "<p>写真APIを呼ばずに終了しました。</p><a href='/'>最初から</a>")
    if not code:
        return page("コードがありません", "<a href='/'>最初から</a>", 400)
    trace = ["ブラウザー → 印刷アプリ: GET /callback（code・stateは非表示）", "stateの照合: 成功"]
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            response = await client.post(AUTH_URL + "/token", data={
                "grant_type": "authorization_code", "code": code, "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI, "code_verifier": item["verifier"]})
            trace.append(f"印刷アプリ → 認可サーバー: POST /token → {response.status_code}")
            response.raise_for_status()
            access_token = response.json()["access_token"]
            response = await client.get(API_URL + "/photos", headers={"Authorization": f"Bearer {access_token}"})
            trace.append(f"印刷アプリ → 写真API: GET /photos → {response.status_code}（利用証は非表示）")
            if response.status_code == 403:
                return page("写真を読む権限がありません", "<p>利用証は取得できましたが、写真APIが403を返しました。</p><pre>"+escape("\n".join(trace))+"</pre><a href='/'>戻る</a>", 403)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError:
        return page("通信に失敗しました", "<p>3つのサーバーが起動しているか確認してください。</p><pre>"+escape("\n".join(trace))+"</pre>", 502)
    trace.extend(result.pop("trace", []))
    return page("Aliceの写真一覧を取得できました", "<p>許可 → コード交換 → 写真取得まで成功しました。</p><h2>取得データ</h2><pre>"
        +escape(json.dumps(result, ensure_ascii=False, indent=2))+"</pre><h2>通信履歴（秘密の値は非表示）</h2><pre>"
        +escape("\n".join(trace))+"</pre><a href='/'>もう一度試す</a>")