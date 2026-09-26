"""FastAPI 后端：排版接口 + 静态页面托管。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .braille import ValidationError, typeset
from .reader import MAX_CELLS, decode

app = FastAPI(title="六点盲文排版台", version="1.0.0")


class TypesetIn(BaseModel):
    # 范围与长度由 braille.validate 统一处理并给出定位错误；
    # 这里仅约束基本类型。
    text: str = Field(..., description="ASCII 字母、数字、空格与换行，不超过 500 字符")
    width: int = Field(..., description="每行 10～40 格")


class DecodeIn(BaseModel):
    braille: str = Field(
        ...,
        description=f"Unicode 六点盲文格（允许盲文空格与换行），不超过 {MAX_CELLS} 格",
    )


@app.exception_handler(RequestValidationError)
async def _on_validation_error(_request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        errors.append({
            "code": "bad_request",
            "field": loc,
            "message": f"参数 {loc or '请求体'} 格式有误：{err.get('msg', '')}",
        })
    return JSONResponse(status_code=422, content={"ok": False, "errors": errors})


@app.post("/api/typeset")
def api_typeset(payload: TypesetIn):
    try:
        result = typeset(payload.text, payload.width)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "errors": exc.errors})
    result["ok"] = True
    return result


@app.post("/api/decode")
def api_decode(payload: DecodeIn):
    """盲文识读：Unicode 六点盲文 -> ASCII 字母、数字、空格与换行。"""
    try:
        result = decode(payload.braille)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "errors": exc.errors})
    result["ok"] = True
    return result


@app.get("/api/health")
def health():
    return {"ok": True}


app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def index():
    return FileResponse("app/static/index.html")
