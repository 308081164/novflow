"""本地/API 冒烟测试，输出写入 verify_result.txt"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api/v1"
lines: list[str] = []


def log(msg: str) -> None:
    print(msg)
    lines.append(msg)


def req(method: str, path: str, data: dict | None = None, token: str | None = None):
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        raw = resp.read().decode()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw


def main() -> int:
    try:
        health = req("GET", "/health")
        log(f"health: {health}")

        email = "verify_test@example.com"
        password = "test123456"
        try:
            auth = req("POST", "/auth/register", {"email": email, "password": password, "display_name": "测试"})
        except urllib.error.HTTPError as e:
            if e.code == 400:
                auth = req("POST", "/auth/login", {"email": email, "password": password})
            else:
                raise
        token = auth["access_token"]
        log(f"auth ok user={auth['user']['email']}")

        settings = req("PUT", "/settings", {"deepseek_api_key": "sk-test-key", "display_name": "测试"}, token=token)
        log(f"settings: configured={settings['deepseek_configured']}")

        book = req(
            "POST",
            "/books",
            {
                "title": "冒烟测试书",
                "blurb": "测试梗概",
                "premise": "测试梗概",
                "genre": "测试",
                "template_id": "blank",
                "target_chapters": 20,
                "platform": "fanqie",
            },
            token=token,
        )
        bid = book["id"]
        log(f"book: id={bid} setup_step={book['setup_step']}")

        wv = req("GET", f"/books/{bid}/worldview", token=token)
        log(f"worldview: id={wv['id']}")

        chars = req("GET", f"/books/{bid}/characters", token=token)
        log(f"characters: count={len(chars)}")

        ch = req("GET", f"/books/{bid}/chapters/1", token=token)
        log(f"chapter1: status={ch['status']}")

        log("ALL CHECKS PASSED")
        return 0
    except Exception as exc:
        log(f"FAILED: {exc}")
        return 1
    finally:
        out = __file__.replace("verify_api.py", "verify_result.txt")
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
