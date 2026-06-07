#!/usr/bin/env python3
import asyncio
import base64
import os

from flask import Flask, jsonify, request
from PIL import Image, ImageDraw

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
from neural_style import (
    STYLE_NAMES,
    stylize_fast as neural_stylize_fast,
    stylize_deep as neural_stylize_deep,
    stylize_ultra as neural_stylize_ultra,
)
from services.generation import run_blocking_generation
from services.miniapp_generation import run_miniapp_generation


app = Flask(__name__)
RESULTS = {}
PROCESS_LOCK = asyncio.Lock()
JOB_STATUS = {}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

db_init()


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
                if sum(abs(a - b) for a, b in zip(c, cr)) > 200:
                    x = int((px + 1) * pixel_w)
                    draw.line([(x, int(py * pixel_h)), (x, int((py + 1) * pixel_h))], fill=0, width=2)
            if py < small_h - 1:
                cd = small.getpixel((px, py + 1))
                if sum(abs(a - b) for a, b in zip(c, cd)) > 200:
                    y = int((py + 1) * pixel_h)
                    draw.line([(int(px * pixel_w), y), (int((px + 1) * pixel_w), y)], fill=0, width=2)
    result.save(out_path, quality=95)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"ok": True})


@app.route("/api/campaigns", methods=["GET"])
def api_campaigns():
    return jsonify({"campaigns": list_campaigns(20)})


@app.route("/api/profile", methods=["GET"])
def api_profile():
    user_id = request.args.get("user_id", "")
    if not user_id.isdigit():
        return jsonify({"error": "user_id is required"}), 400
    return jsonify({"user": get_user(int(user_id))})


@app.route("/api/result", methods=["GET"])
def api_result():
    job_id = request.args.get("job_id", "")
    if not job_id.isdigit():
        return jsonify({"error": "job_id is required"}), 400
    result = RESULTS.get(int(job_id))
    if not result:
        return jsonify({"error": "result not found"}), 404
    return jsonify(result)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    payload = request.get_json(silent=True) or {}
    user_id = payload.get("user_id")
    image_b64 = payload.get("image_base64", "")
    mode = int(payload.get("mode", 1))
    style_id = int(payload.get("style_id", 0))

    if not isinstance(user_id, int):
        return jsonify({"error": "user_id is required"}), 400
    if not image_b64:
        return jsonify({"error": "image_base64 is required"}), 400
    if style_id < 0 or style_id >= len(STYLE_NAMES):
        return jsonify({"error": "invalid style_id"}), 400

    create_user(user_id)
    free = remaining_free(user_id)
    paid = remaining_paid(user_id)
    if free <= 0 and paid <= 0:
        return jsonify({"error": "Недостаточно стилизаций"}), 400

    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        return jsonify({"error": "invalid image_base64"}), 400

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
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"generation failed: {e}"}), 500
    finally:
        loop.close()

    RESULTS[result["job_id"]] = {
        "job_id": result["job_id"],
        "caption": result["caption"],
        "elapsed": result["elapsed"],
        "image_base64": base64.b64encode(result["image_bytes"]).decode("ascii"),
    }
    return jsonify({"ok": True, "job_id": result["job_id"]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8787, debug=False)
