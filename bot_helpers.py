import os
import random
import shutil
import time

from PIL import Image, ImageDraw

from content import FUN_CAPTIONS, PIXEL_CAPTIONS, SOCIAL_PROOF_LINE


def progress_bar(step, total, width=12):
    filled = int(step / total * width) if total > 0 else 0
    return "█" * filled + "░" * (width - filled)


def validate_image_file(path, max_image_side):
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            w, h = img.size
            if w > max_image_side or h > max_image_side:
                raise ValueError("Фото слишком большое по размеру. Лимит: 4096px по стороне.")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("Не удалось прочитать изображение. Отправь обычное JPG/PNG фото.") from e


def save_result_copy(user_id, source_path, results_dir, prefix="result"):
    user_dir = os.path.join(results_dir, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    dst = os.path.join(user_dir, f"{prefix}_{int(time.time())}.jpg")
    shutil.copy2(source_path, dst)
    return dst


def apply_watermark(path, text):
    with Image.open(path).convert("RGB") as img:
        draw = ImageDraw.Draw(img)
        margin = 12
        bbox = draw.textbbox((0, 0), text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = img.width - tw - margin * 2
        y = img.height - th - margin * 2
        draw.rounded_rectangle((x - 8, y - 6, x + tw + 8, y + th + 6), radius=8, fill=(0, 0, 0))
        draw.text((x, y), text, fill=(255, 255, 255))
        img.save(path, "JPEG", quality=94)


def make_caption(mode_label, style_name, free, paid, elapsed):
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    time_str = f"{mins}м {secs}с" if mins else f"{secs}с"
    is_pixel = "Пиксель" in mode_label
    cap = random.choice(PIXEL_CAPTIONS if is_pixel else FUN_CAPTIONS)
    return (
        f"✨ *{cap}*\n"
        f"🎨 Стиль: {style_name}\n"
        f"🖌 Режим: {mode_label}\n"
        f"⏱ Время: {time_str}\n"
        f"┌{'─'*25}┐\n"
        f"│ 🆓 Бесплатно: {free:>3}          │\n"
        f"│ 💎 Куплено:   {paid:>4}        │\n"
        f"└{'─'*25}┘\n"
        f"/buy — пополнить"
    )


def cleanup(path):
    try:
        os.remove(path)
    except (FileNotFoundError, PermissionError):
        pass
