"""FastAPI 接口层测试。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_index_and_assets_served():
    assert client.get("/").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_typeset_ok():
    resp = client.post("/api/typeset", json={"text": "ab", "width": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["braille_text"] == "⠁⠃"
    assert data["lines"][0]["cells"][0]["dots"] == [1]


def test_typeset_illegal_char_is_located():
    resp = client.post("/api/typeset", json={"text": "ab\tc", "width": 10})
    assert resp.status_code == 422
    data = resp.json()
    assert data["ok"] is False
    err = next(e for e in data["errors"] if e["code"] == "illegal_char")
    assert (err["line"], err["col"]) == (1, 3)


def test_typeset_mixed_word():
    resp = client.post("/api/typeset", json={"text": "ab1", "width": 10})
    assert resp.status_code == 422
    codes = {e["code"] for e in resp.json()["errors"]}
    assert "mixed_word" in codes


def test_typeset_bad_width():
    resp = client.post("/api/typeset", json={"text": "abc", "width": 41})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["code"] == "bad_width"


def test_typeset_missing_field():
    resp = client.post("/api/typeset", json={"text": "abc"})
    assert resp.status_code == 422
    assert resp.json()["ok"] is False


def test_typeset_too_long():
    resp = client.post("/api/typeset", json={"text": "a" * 501, "width": 10})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["code"] == "too_long"


# ---------------------------------------------------------------------------
# 盲文识读 /api/decode
# ---------------------------------------------------------------------------

def test_decode_ok():
    resp = client.post("/api/decode", json={"braille": "⠠⠓⠊"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["text"] == "Hi"
    assert data["stats"]["input_cells"] == 3
    assert data["stats"]["output_chars"] == 2


def test_decode_digits_and_space():
    resp = client.post(
        "/api/decode",
        json={"braille": "⠼⠃⠚⠃⠋⠀⠁"},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "2026 a"


def test_decode_hyphen_joins_word():
    resp = client.post("/api/decode", json={"braille": "⠁⠃⠤\n⠉⠙"})
    assert resp.status_code == 200
    assert resp.json()["text"] == "abcd"


def test_decode_error_is_located():
    resp = client.post("/api/decode", json={"braille": "⠁⠤⠃"})
    assert resp.status_code == 422
    data = resp.json()
    assert data["ok"] is False
    err = data["errors"][0]
    assert err["code"] == "inline_hyphen"
    assert (err["line"], err["col"]) == (1, 2)
    assert "text" not in data


def test_decode_bad_number_continuation():
    resp = client.post("/api/decode", json={"braille": "⠼⠁⠤\n⠃"})
    assert resp.status_code == 422
    err = next(
        e for e in resp.json()["errors"]
        if e["code"] == "bad_number_continuation"
    )
    assert (err["line"], err["col"]) == (2, 1)


def test_decode_illegal_char_and_too_long():
    resp = client.post("/api/decode", json={"braille": "abc"})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["code"] == "illegal_char"

    resp = client.post("/api/decode", json={"braille": "⠁" * 501})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["code"] == "too_long"


def test_decode_missing_field():
    resp = client.post("/api/decode", json={})
    assert resp.status_code == 422
    assert resp.json()["ok"] is False

