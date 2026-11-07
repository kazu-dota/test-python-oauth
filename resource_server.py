"""写真API。利用証を発行元へ照会してからデータを返す。"""
import httpx
from fastapi import FastAPI, Header, HTTPException
from common import AUTH_URL, API_USER, API_PASSWORD

app = FastAPI(title="学習用 写真API")

@app.get("/photos")
async def photos(authorization: str = Header(default="")):
    """GET /photosで利用証と権限を確認し、Aliceの写真一覧を返す。

    ランダム文字列の利用証はこのAPIだけでは有効性を判断できない。
    そのためPOST /introspectで発行元に照会し、active・対象API・権限を
    確認する。発行元への問い合わせには写真API自身のBasic認証を使う。

    Args:
        authorization: HTTPヘッダーの値。Bearerの後に利用証を指定する。
            FastAPIのHeaderによってヘッダーから自動的に取り出される。

    Returns:
        利用者名、固定の写真一覧、秘密の値を含まない通信履歴を持つ辞書。
        FastAPIがこの辞書をJSON形式の200の返事へ変換する。

    Raises:
        HTTPException: 利用証なし・無効・対象API違いの場合（401）、
            読み取り権限がない場合（403）、照会先と通信できない場合（502）。
    """
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "利用証がありません", headers={"WWW-Authenticate": "Bearer"})
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            response = await client.post(AUTH_URL + "/introspect", data={"token": token},
                auth=(API_USER, API_PASSWORD))
            response.raise_for_status()
            info = response.json()
    except httpx.HTTPError:
        raise HTTPException(502, "利用証の発行元へ確認できません")
    if not info.get("active") or info.get("aud") != API_USER:
        raise HTTPException(401, "利用証が無効です", headers={"WWW-Authenticate": "Bearer"})
    if "photos.read" not in info.get("scope", "").split():
        raise HTTPException(403, "写真を読む許可がありません")
    return {"owner": info["sub"], "photos": [
        {"id": "photo-1", "title": "海辺の休日"},
        {"id": "photo-2", "title": "山の風景"}],
        "trace": ["写真API → 認可サーバー: POST /introspect（利用証は非表示）",
                  "認可サーバー → 写真API: 200 / active=true / photos.read"]}