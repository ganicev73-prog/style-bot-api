import time
from io import BytesIO

from PIL import Image

from bot_helpers import validate_image_file, save_result_copy, apply_watermark, make_caption, cleanup


async def run_miniapp_generation(
    *,
    loop,
    uid: int,
    image_bytes: bytes,
    mode: int,
    sid: int,
    style_name: str,
    spent_source: str,
    results_dir: str,
    bot_username: str,
    process_lock,
    job_status: dict,
    create_job,
    update_job,
    use_free,
    use_paid,
    refund_use,
    remaining_free,
    remaining_paid,
    add_history,
    log_funnel_event,
    pixelate,
    run_blocking_generation,
    neural_stylize_fast,
    neural_stylize_deep,
    neural_stylize_ultra,
):
    in_path = f"/tmp/miniapp_in_{uid}_{int(time.time())}.jpg"
    out_path = f"/tmp/miniapp_out_{uid}_{int(time.time())}.jpg"

    with open(in_path, "wb") as f:
        f.write(image_bytes)
    validate_image_file(in_path, 4096)

    use_ok = use_free(uid) if spent_source == "free" else use_paid(uid)
    if not use_ok:
        cleanup(in_path)
        raise RuntimeError("Недостаточно стилизаций")

    if process_lock.locked():
        cleanup(in_path)
        raise RuntimeError("Сейчас обрабатывается другой запрос")

    async with process_lock:
        mode_name_for_job = {0: "pixel", 1: "fast", 2: "deep", 3: "ultra"}.get(mode, "unknown")
        job_id = create_job(uid, "running", mode_name_for_job, style_name)
        job_status[uid] = "обработка из mini app"
        start_t = time.time()

        try:
            if mode == 0:
                pixelate(in_path, out_path, style_id=sid)
            else:
                style_func = {1: neural_stylize_fast, 2: neural_stylize_deep, 3: neural_stylize_ultra}[mode]
                await run_blocking_generation(loop, style_func, in_path, sid, out_path)
        except Exception:
            refund_use(uid, spent_source)
            update_job(job_id, "failed", "miniapp generation error")
            cleanup(in_path)
            cleanup(out_path)
            raise

        elapsed = time.time() - start_t
        update_job(job_id, "done")
        if spent_source == "free":
            apply_watermark(out_path, f"@{bot_username}")

        saved_path = save_result_copy(uid, out_path, results_dir, "miniapp")
        mode_label = {0: "🟦 Пиксель-арт", 1: "🎨 Быстрая", 2: "🖌 Глубокий CPU", 3: "🏆 Максимум качества"}.get(mode, "?")
        add_history(uid, mode_label, style_name, saved_path)
        log_funnel_event(uid, "result_received")

        buf = BytesIO()
        buf.name = "result.jpg"
        Image.open(out_path).save(buf, "JPEG", quality=92)
        result_bytes = buf.getvalue()
        caption = make_caption(mode_label, style_name, remaining_free(uid), remaining_paid(uid), elapsed)

        cleanup(in_path)
        cleanup(out_path)

        return {
            "job_id": job_id,
            "caption": caption,
            "image_bytes": result_bytes,
            "elapsed": elapsed,
        }
