#!/usr/bin/env python3
import base64
import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw

from config import WEB_API_HOST, WEB_API_PORT
from db import (
    init as db_init,
    get_user,
    list_campaigns,
    create_user,
    remaining_free,
    remaining_paid,
    use_free,
    use_paid,
    refund_use,
    add_history,
    create_job,
    update_job,
    log_funnel_event,
)
from payment import BOT_USERNAME
from neural_style import STYLE_NAMES, stylize_fast as neural_stylize_fast, stylize_deep as neural_stylize_deep, stylize_ultra as neural_stylize_ultra
from services.generation import run_blocking_generation
from services.miniapp_generation import run_miniapp_generation


RESULTS = {}
PROCESS_LOCK = asyncio.Lock()
JOB_STATUS = {}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def pixelate(in_path, out_path, style_id=0, pixel_size=48, n_colors=32):
    img = Image.open(in_path).convert("RGB")
    w, h = img.size
    ratio = min(pixel_size / w, pixel_size / h)
    small_w = max(int(w * ratio), 8)
    small_h = max(int(h * ratio), 8)
    small = img.resize((small_w, small_h), Image.LANCZOS)

    style_path = os.path.join(BASE_DIR, f"style_{style_id}.jpg")
    if os.path.exists(style_path):
        style_img = Image.open(style_path).convert("RGB")
        style_pal = style_img.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT)
        small = small.quantize(palette=style_pal, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
    else:
        small = small.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT).convert("RGB")

    result = small.resize(img.size, Image.NEAREST)
    pixel_w = w / small_w
    pixel_h = h / small_h
    draw = ImageDraw.Draw(result)
    for py in range(small_h):
        for px in range(small_w):
            c = small.getpixel((px, py))
            if px < small_w - 1:
                cr = small.getpixel((px + 1, py))
                if sum(abs(a-b) for a, b in zip(c, cr)) > 200:
                    x = int((px + 1) * pixel_w)
                    draw.line([(x, int(py * pixel_h)), (x, int((py + 1) * pixel_h))], fill=0, width=2)
            if py < small_h - 1:
                cd = small.getpixel((px, py + 1))
                if sum(abs(a-b) for a, b in zip(c, cd)) > 200:
                    y = int((py + 1) * pixel_h)
                    draw.line([(int(px * pixel_w), y), (int((px + 1) * pixel_w), y)], fill=0, width=2)
    result.save(out_path, quality=95)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send(200, {"ok": True})
            return
        if parsed.path == "/api/campaigns":
            self._send(200, {"campaigns": list_campaigns(20)})
            return
        if parsed.path == "/api/profile":
            params = parse_qs(parsed.query)
            user_id = params.get("user_id", [""])[0]
            if not user_id.isdigit():
                self._send(400, {"error": "user_id is required"})
                return
            user = get_user(int(user_id))
            self._send(200, {"user": user})
            return
        if parsed.path == "/api/result":
            params = parse_qs(parsed.query)
            job_id = params.get("job_id", [""])[0]
            if not job_id.isdigit():
                self._send(400, {"error": "job_id is required"})
                return
            result = RESULTS.get(int(job_id))
            if not result:
                self._send(404, {"error": "result not found"})
                return
            self._send(200, result)
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/generate":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send(400, {"error": "invalid json"})
            return

        user_id = payload.get("user_id")
        image_b64 = payload.get("image_base64", "")
        mode = int(payload.get("mode", 1))
        style_id = int(payload.get("style_id", 0))

        if not isinstance(user_id, int):
            self._send(400, {"error": "user_id is required"})
            return
        if not image_b64:
            self._send(400, {"error": "image_base64 is required"})
            return
        if style_id < 0 or style_id >= len(STYLE_NAMES):
            self._send(400, {"error": "invalid style_id"})
            return

        create_user(user_id)
        free = remaining_free(user_id)
        paid = remaining_paid(user_id)
        if free <= 0 and paid <= 0:
            self._send(400, {"error": "Недостаточно стилизаций"})
            return

        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception:
            self._send(400, {"error": "invalid image_base64"})
            return

        spent_source = "free" if free > 0 else "paid"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                run_miniapp_generation(
                    loop=loop,
                    uid=user_id,
                    image_bytes=image_bytes,
                    mode=mode,
                    sid=style_id,
                    style_name=STYLE_NAMES[style_id],
                    spent_source=spent_source,
                    results_dir=RESULTS_DIR,
                    bot_username=BOT_USERNAME,
                    process_lock=PROCESS_LOCK,
                    job_status=JOB_STATUS,
                    create_job=create_job,
                    update_job=update_job,
                    use_free=use_free,
                    use_paid=use_paid,
                    refund_use=refund_use,
                    remaining_free=remaining_free,
                    remaining_paid=remaining_paid,
                    add_history=add_history,
                    log_funnel_event=log_funnel_event,
                    pixelate=pixelate,
                    run_blocking_generation=run_blocking_generation,
                    neural_stylize_fast=neural_stylize_fast,
                    neural_stylize_deep=neural_stylize_deep,
                    neural_stylize_ultra=neural_stylize_ultra,
                )
            )
        except RuntimeError as e:
            self._send(400, {"error": str(e)})
            return
        except Exception as e:
            self._send(500, {"error": f"generation failed: {e}"})
            return
        finally:
            loop.close()

        RESULTS[result["job_id"]] = {
            "job_id": result["job_id"],
            "caption": result["caption"],
            "elapsed": result["elapsed"],
            "image_base64": base64.b64encode(result["image_bytes"]).decode("ascii"),
        }
        self._send(200, {"ok": True, "job_id": result["job_id"]})


def main():
    db_init()
    server = ThreadingHTTPServer((WEB_API_HOST, WEB_API_PORT), Handler)
    print(f"Web API listening on http://{WEB_API_HOST}:{WEB_API_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
