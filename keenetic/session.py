"""HTTP-сессия для Keenetic API с сохранением cookie."""

import json
import urllib.error
import urllib.request

from keenetic.config import BASE_URL


class KeeneticSession:
    """Сессия с сохранением cookie для urllib."""

    def __init__(self):
        self._cookie: str | None = None
        self._opener = urllib.request.build_opener()

    def _make_request(self, method: str, path: str,
                      body: bytes | None = None,
                      extra_headers: dict | None = None) -> urllib.request.Request:
        url = f"{BASE_URL}{path}"
        headers = {"Content-Type": "application/json"} if body else {}
        if extra_headers:
            headers.update(extra_headers)
        if self._cookie:
            headers["Cookie"] = self._cookie
        return urllib.request.Request(url, data=body, headers=headers, method=method)

    def _update_cookie(self, resp_headers):
        set_cookie = resp_headers.get("Set-Cookie")
        if set_cookie:
            self._cookie = set_cookie.split(";")[0].strip()

    def request(self, method: str, path: str,
                body: bytes | None = None,
                extra_headers: dict | None = None,
                return_headers: bool = False):
        req = self._make_request(method, path, body, extra_headers)
        try:
            resp = self._opener.open(req)
            data = resp.read()
            headers = dict(resp.headers)
            self._update_cookie(headers)
            if return_headers:
                return data, headers, resp.status
            return data, resp.status
        except urllib.error.HTTPError as e:
            self._update_cookie(dict(e.headers))
            if return_headers:
                return e.read(), dict(e.headers), e.code
            return e.read(), e.code

    def get(self, path: str, return_headers: bool = False):
        return self.request("GET", path, return_headers=return_headers)

    def post_json(self, path: str, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        return self.request("POST", path, body=body)
