from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from proxy import caching
from proxy.caching.cache_request import CacheRequest

ALLOWED_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
BODY_ALLOWED_METHODS = ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
IGNORED_HEADERS = ["host", "content-length"]

cache = caching.get_cache_provider()


def get_url(request: Request) -> str:
    url = request.path_params.get("url", "")
    url = f"{url}?{request.query_params}" if request.query_params else url

    if not url.startswith("http"):
        return url

    if url.startswith(("http://", "https://")):
        return url

    # Weird behaviour of FastAPI on linux to collapse multiple slashes
    if url.startswith(("http:/", "https:/")):
        return url.replace("http:/", "http://").replace("https:/", "https://")

    return url


def sanitize_headers(items: list[tuple[str, str]]) -> dict:
    sanitized_headers = {}
    for key, value in items:
        if key.lower() not in IGNORED_HEADERS:
            sanitized_headers[key] = value

    return sanitized_headers


def do_proxy_request(url: str, request: Request, body_: Any | None = None) -> bytes:
    if request.method not in ALLOWED_METHODS:
        raise HTTPException(status_code=405, detail="Method Not Allowed")

    headers = sanitize_headers(request.headers.items())
    body = body_ if body_ and request.method in BODY_ALLOWED_METHODS else None

    try:
        proxy_request = requests.request(
            request.method, url, headers=headers, data=body
        )
        return proxy_request.content
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=404, detail="Connection Error")
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Error")


async def handle_proxy(request: Request):
    body = await request.body()
    url = get_url(request)
    content = do_proxy_request(url, request, body)
    return Response(content=content)


async def handle_cache(request: Request, max_age: int):
    body = await request.body()
    url = get_url(request)
    headers = sanitize_headers(request.headers.items())
    cache_request = CacheRequest(
        request.method,
        url,
        body=body,
        headers=headers,
        max_age=max_age,
    )

    try:
        cached = cache.get(cache_request)
    except Exception as e:  # noqa: BLE001
        print(f"Error while getting from cache: {e}")
        cached = None

    if cached:
        return Response(content=cached)

    response = do_proxy_request(url, request, body)
    try:
        cache.set(cache_request, response)
    except Exception as e:  # noqa: BLE001
        print(f"Error while setting cache: {e}")

    return Response(content=response)


async def handle_cache_no_age(request: Request):
    return await handle_cache(request, 0)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_api_route(
    "/cache/max-age:{max_age:int}/{url:path}", handle_cache, methods=ALLOWED_METHODS
)
app.add_api_route("/cache/{url:path}", handle_cache_no_age, methods=ALLOWED_METHODS)
app.add_api_route("/{url:path}", handle_proxy, methods=ALLOWED_METHODS)
