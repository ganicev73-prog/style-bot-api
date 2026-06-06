import asyncio
import time


async def run_blocking_generation(loop, func, *args, **kwargs):
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def make_progress_callback(loop, send_progress, uid, bot, msg, start_t):
    def prog_cb(step, total, img_path):
        elapsed = time.time() - start_t[0]
        asyncio.run_coroutine_threadsafe(
            send_progress(uid, bot, msg, step, total, img_path, elapsed),
            loop,
        )

    return prog_cb
