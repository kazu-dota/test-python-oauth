"""許可画面・認可コード・アクセストークンを管理するサーバー。"""
import re
import secrets
import time
from html import escape
from urllib.parse import urlencode
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from common import CLIENT_ID, REDIRECT_URI, API_USER, API_PASSWORD, challenge, page

app = FastAPI(title="学習用 認可サーバー")
pending = {}
codes = {}
tokens = {}
basic = HTTPBasic()

@app.get("/authorize")
def authorize(response_type: str, client_id: str, redirect_uri: str,
              scope: str, state: str, code_challenge: str, code_challenge_method: str):
    """GET /authorizeを受け、要求内容を確認して許可画面を表示する。

    この時点ではコードも利用証も発行しない。入力をサーバー側の
    pendingに保存し、ブラウザーのCookieには保存先を探す番号だけを返す。

    Args:
        response_type: 欲しい返事の種類。このデモではcodeのみ。
        client_id: 許可を求めているアプリの登録名札。
        redirect_uri: 許可操作の後にブラウザーを戻す登録済みURL。
        scope: 要求する操作。photos.read、または権限不足実験用の空文字。
        state: 印刷アプリが連携操作を対応付けるために作った照合番号。
        code_challenge: PKCEの秘密の値を計算して作った照合用の文字列。
        code_challenge_method: 計算方式。このデモではS256のみ。

    Returns:
        許可・拒否ボタンとauth_session Cookieを含むHTMLResponse。

    Raises:
        HTTPException: アプリ、戻り先、その他の入力が不正な場合（400）。
    """
    # 戻り先が不正な場合、そのURLへリダイレクトしない。
    if client_id != CLIENT_ID or redirect_uri != REDIRECT_URI:
        raise HTTPException(400, "登録済みのアプリ・戻り先と一致しません")
    if (response_type != "code" or scope not in ("photos.read", "")
        or not state or code_challenge_method != "S256"
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", code_challenge)):
        raise HTTPException(400, "認可リクエストが不正です")
    session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    pending[session_id] = dict(client_id=client_id, redirect_uri=redirect_uri,
        scope=scope, state=state, challenge=code_challenge, csrf=csrf, exp=time.time()+300)
    response = page("写真の読み取りを許可しますか？", f'''
    <p>あなたは <b>Alice</b> としてログイン済みです（学習用の仮定）。</p>
    <p>お願いしているアプリ：写真印刷アプリ（print-app）</p>
    <p>許可する操作：{escape(scope) if scope else 'なし（権限不足の実験）'}</p>
    <p>パスワードを印刷アプリに渡すことはありません。</p>
    <form method="post" action="/approve"><input type="hidden" name="csrf" value="{csrf}">
    <button name="decision" value="allow">許可する</button>
    <button name="decision" value="deny">拒否する</button></form>''')
    response.set_cookie("auth_session", session_id, httponly=True, samesite="lax", max_age=300)
    return response

@app.post("/approve")
def approve(request: Request, csrf: str = Form(...), decision: str = Form(...)):
    """POST /approveで利用者の選択を受け取り、印刷アプリへ戻す。

    Cookieとフォームの照合値を確認することで、表示した許可画面からの
    操作かを確かめる。許可なら60秒だけ有効な認可コードを保存する。
    拒否ならコードを作らず、access_deniedを戻り先へ送る。

    Args:
        request: Cookieなどを読めるFastAPIのリクエスト情報。
        csrf: 許可画面に埋め込んだ、意図しないフォーム送信を防ぐ照合値。
        decision: 押されたボタンの値。allowが許可、denyが拒否。

    Returns:
        ブラウザーへコールバックURLのGETを指示する303の返事。

    Raises:
        HTTPException: 許可画面の期限切れ、照合失敗、不正な選択の場合（400）。
    """
    sid = request.cookies.get("auth_session", "") # cookiesのauthセッションの値から復元
    item = pending.get(sid) # authorizeで設定したパラメータを復元
    if not item or item["exp"] < time.time() or not secrets.compare_digest(csrf, item["csrf"]):
        raise HTTPException(400, "許可画面の期限切れ、または不正な操作です")
    if decision not in ("allow", "deny"):
        raise HTTPException(400, "選択が不正です")
    pending.pop(sid) # セッションの値をpendingより削除
    params = {"state": item["state"]} #stateの更新
    if decision == "deny":
        params["error"] = "access_denied"
    else:
        code = secrets.token_urlsafe(32)
        codes[code] = {**item, "exp": time.time()+60}
        params["code"] = code
    response = RedirectResponse(REDIRECT_URI + "?" + urlencode(params), status_code=303)
    response.delete_cookie("auth_session")
    return response

@app.post("/token")
async def token(grant_type: str = Form(...), code: str = Form(...),
          client_id: str = Form(...), redirect_uri: str = Form(...), code_verifier: str = Form(...)):
    """POST /tokenで一度限りの認可コードを利用証へ交換する。

    コードの存在・期限・アプリ・戻り先・PKCEをすべて検証する。
    検証後にコードを削除し、新しい利用証とその権限をtokensへ保存する。
    単一プロセスのイベントループで動かし、検証から削除までawaitを
    挟まないことで、同じコードを並行して交換することを防ぐ。

    Args:
        grant_type: 交換方法の名前。authorization_codeのみ受け付ける。
        code: 許可操作で発行された一度限りの引換券。
        client_id: 交換を要求しているアプリの登録名札。
        redirect_uri: 認可要求時と同じ戻り先URL。
        code_verifier: 印刷アプリが保持していたPKCEの元の秘密の値。

    Returns:
        成功時は利用証・種類・有効秒数・権限を含む200のJSONResponse。
        検証失敗時はinvalid_grantを含む400のJSONResponse。
    """
    item = codes.get(code)
    valid = (item and item["exp"] > time.time() and grant_type == "authorization_code"
        and client_id == item["client_id"] and redirect_uri == item["redirect_uri"]
        and re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", code_verifier)
        and secrets.compare_digest(challenge(code_verifier), item["challenge"]))
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
    if not valid:
        return JSONResponse({"error": "invalid_grant"}, status_code=400, headers=headers)
    codes.pop(code)  # 検証・削除は同期処理内。一度しか交換できない。
    access_token = secrets.token_urlsafe(32)
    tokens[access_token] = {"sub": "alice", "scope": item["scope"],
        "aud": API_USER, "exp": int(time.time())+300}
    return JSONResponse({"access_token": access_token, "token_type": "Bearer",
        "expires_in": 300, "scope": item["scope"]}, headers=headers)

@app.post("/introspect")
def introspect(token: str = Form(...), credentials: HTTPBasicCredentials = Depends(basic)):
    """POST /introspectで、写真APIからの利用証の照会に答える。

    利用者のログイン確認ではなく、問い合わせ元が写真APIかを
    HTTP Basic認証で確認する。利用証の中身をブラウザーへ返す窓口ではない。

    Args:
        token: 写真APIが確認したいアクセストークン。
        credentials: AuthorizationヘッダーからFastAPIが取り出す
            写真APIのユーザー名とパスワード（学習用の固定値）。

    Returns:
        有効ならactive=trueと利用者・権限・対象API・期限を含むJSONResponse。
        不明または期限切れならactive=falseだけを返す。

    Raises:
        HTTPException: 問い合わせ元の認証に失敗した場合（401）。
    """
    if not (secrets.compare_digest(credentials.username.encode(), API_USER.encode())
            and secrets.compare_digest(credentials.password.encode(), API_PASSWORD.encode())):
        raise HTTPException(401, "写真APIの認証に失敗", headers={"WWW-Authenticate": "Basic"})
    item = tokens.get(token)
    result = {"active": True, **item} if item and item["exp"] > time.time() else {"active": False}
    return JSONResponse(result, headers={"Cache-Control": "no-store"})