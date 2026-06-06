import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchvision.models as M
import torchvision.transforms as T
from PIL import Image, ImageFilter

STYLE_PATHS = [os.path.join(os.path.dirname(__file__), f"style_{i}.jpg") for i in range(3)]
STYLE_NAMES = ["Van Gogh", "Monet", "Picasso"]
STYLE_DESCRIPTIONS = [
    "Яркие мазки, густое масло",
    "Мягкие переходы, пастель",
    "Геометрические формы, контуры",
]

NUM_STEPS = 30
LR = 0.05
CONTENT_WEIGHT = 1.0
STYLE_WEIGHT = 1e8
TV_WEIGHT = 1e-3
MAX_SIZE = 350
STYLE_GRAM_SIZE = 600

torch.set_num_threads(1)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

CANCEL_CHECK_INTERVAL = 5


class VGGFeatures(nn.Module):
    def __init__(self):
        super().__init__()
        vgg = M.vgg19(weights=M.VGG19_Weights.IMAGENET1K_V1).features.to(device).eval()
        for p in vgg.parameters():
            p.requires_grad = False
        blocks = nn.ModuleList()
        cur = nn.Sequential()
        for m in vgg:
            if isinstance(m, nn.ReLU):
                m.inplace = False
            cur.append(m)
            if isinstance(m, nn.MaxPool2d):
                blocks.append(cur)
                cur = nn.Sequential()
        blocks.append(cur)
        self.blocks = blocks
        for b in self.blocks:
            for p in b.parameters():
                p.requires_grad = False

    def forward(self, x):
        style_feats = []
        content_feat = None
        for i, block in enumerate(self.blocks):
            x = block(x)
            if i in (0, 2, 4, 6):
                style_feats.append(x)
            if i == 4:
                content_feat = x
        return content_feat, style_feats


_vgg_cache: VGGFeatures | None = None
_style_gram_cache: dict[int, list[torch.Tensor]] = {}


def get_vgg():
    global _vgg_cache
    if _vgg_cache is None:
        _vgg_cache = VGGFeatures()
    return _vgg_cache


def get_style_grams(style_id: int):
    if style_id not in _style_gram_cache:
        style_img = load_img(STYLE_PATHS[style_id], max_size=STYLE_GRAM_SIZE)
        vgg = get_vgg()
        with torch.no_grad():
            _, sf = vgg(style_img)
            _style_gram_cache[style_id] = [gram(s).detach() for s in sf]
    return _style_gram_cache[style_id]


def gram(x):
    N, C, H, W = x.shape
    f = x.view(N, C, H * W)
    return f.bmm(f.transpose(1, 2)) / (C * H * W)


def load_img(path, max_size=MAX_SIZE):
    img = Image.open(path).convert("RGB")
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)
    t = T.ToTensor()(img).unsqueeze(0).to(device)
    return t * 2 - 1


def save_img(tensor, path, quality=95):
    t = (tensor.detach().cpu().squeeze(0) + 1) / 2
    t = t.clamp(0, 1)
    T.ToPILImage()(t).save(path, quality=quality)


def should_cancel(cancel_check):
    if cancel_check:
        return cancel_check()
    return False


def run_phase(vgg, opt, target, content_feat, style_grams, n_steps, scale_name,
              total_steps, done, output_path, progress_callback, cancel_check,
              cw=0.8, sw=2e8, tv=1e-4):
    for _ in range(n_steps):
        if done[0] % CANCEL_CHECK_INTERVAL == 0 and should_cancel(cancel_check):
            raise InterruptedError("Cancelled")
        opt.zero_grad()
        cf, sfs = vgg(target)
        c_loss = F.mse_loss(cf, content_feat)
        s_loss = sum(F.mse_loss(gram(sf), sg) for sf, sg in zip(sfs, style_grams)) / len(sfs)
        tv_loss = F.l1_loss(target[:,:,1:,:], target[:,:,:-1,:]) + F.l1_loss(target[:,:,:,1:], target[:,:,:,:-1])
        loss = cw * c_loss + sw * s_loss + tv * tv_loss
        loss.backward()
        if sw > 1e8:
            torch.nn.utils.clip_grad_norm_([target], 10.0)
        opt.step()
        done[0] += 1
        d = done[0]
        if d % 10 == 0 or d == 1:
            print(f"  [{d}/{total_steps}] {scale_name} l={loss.item():.0f} c={c_loss.item():.2f} s={s_loss.item():.0f}", flush=True)
        if d % 10 == 0 and progress_callback:
            prog_path = f"{output_path}.prog{d}.jpg"
            save_img(target, prog_path)
            progress_callback(d, total_steps, prog_path)


def stylize(content_path: str, style_id: int, output_path: str,
            progress_callback=None, cancel_check=None) -> str:
    content = load_img(content_path)
    _, _, h, w = content.shape

    if should_cancel(cancel_check):
        raise InterruptedError("Cancelled")

    target = content.clone().requires_grad_(True)
    vgg = get_vgg()
    style_grams = get_style_grams(style_id)
    with torch.no_grad():
        content_feat = vgg(content)[0].detach()

    opt = optim.Adam([target], lr=LR)
    print(f"[sty] style={STYLE_NAMES[style_id]} size={h}x{w} steps={NUM_STEPS}", flush=True)
    for step in range(NUM_STEPS):
        if step % CANCEL_CHECK_INTERVAL == 0 and should_cancel(cancel_check):
            raise InterruptedError("Cancelled")
        opt.zero_grad()
        cf, sfs = vgg(target)
        c_loss = F.mse_loss(cf, content_feat)
        s_loss = sum(F.mse_loss(gram(sf), sg) for sf, sg in zip(sfs, style_grams)) / len(sfs)
        tv = F.l1_loss(target[:, :, 1:, :], target[:, :, :-1, :]) + F.l1_loss(target[:, :, :, 1:], target[:, :, :, :-1])
        loss = CONTENT_WEIGHT * c_loss + STYLE_WEIGHT * s_loss + TV_WEIGHT * tv
        loss.backward()
        opt.step()
        if step % 20 == 0 or step == 0:
            print(f"  [{step}/{NUM_STEPS}] l={loss.item():.0f} c={c_loss.item():.3f} s={s_loss.item():.3f}", flush=True)
        if step % 10 == 0 and progress_callback:
            prog_path = f"{output_path}.prog{step}.jpg"
            save_img(target, prog_path)
            progress_callback(step, NUM_STEPS, prog_path)

    save_img(target, output_path)
    print(f"[sty] done: {output_path}", flush=True)
    return output_path


def stylize_custom(content_path: str, style_path: str, output_path: str,
                   progress_callback=None, cancel_check=None) -> str:
    content = load_img(content_path, max_size=600)
    style = load_img(style_path, max_size=400)
    _, _, h, w = content.shape

    if should_cancel(cancel_check):
        raise InterruptedError("Cancelled")

    target = content + 0.02 * torch.randn_like(content)
    target.requires_grad_(True)

    vgg = get_vgg()
    with torch.no_grad():
        _, sf = vgg(style)
        style_grams = [gram(s).detach() for s in sf]
        content_feat = vgg(content)[0].detach()

    style_name = os.path.splitext(os.path.basename(style_path))[0]
    opt = optim.Adam([target], lr=0.05)
    NUM = 60
    print(f"[sty_custom] style={style_name} size={h}x{w} steps={NUM}", flush=True)
    for step in range(NUM):
        if step % CANCEL_CHECK_INTERVAL == 0 and should_cancel(cancel_check):
            raise InterruptedError("Cancelled")
        opt.zero_grad()
        cf, sfs = vgg(target)
        c_loss = F.mse_loss(cf, content_feat)
        s_loss = sum(F.mse_loss(gram(sf), sg) for sf, sg in zip(sfs, style_grams)) / len(sfs)
        tv = F.l1_loss(target[:,:,1:,:], target[:,:,:-1,:]) + F.l1_loss(target[:,:,:,1:], target[:,:,:,:-1])
        loss = 0.8 * c_loss + 2e8 * s_loss + 3e-4 * tv
        loss.backward()
        opt.step()
        if step % 10 == 0 or step == 0:
            print(f"  [{step}/{NUM}] l={loss.item():.0f} c={c_loss.item():.2f} s={s_loss.item():.0f}", flush=True)
        if step % 10 == 0 and progress_callback:
            prog_path = f"{output_path}.prog{step}.jpg"
            save_img(target, prog_path)
            progress_callback(step, NUM, prog_path)

    save_img(target, output_path)
    Image.open(output_path).filter(ImageFilter.UnsharpMask(radius=1, percent=80, threshold=3)).save(output_path, quality=95)
    print(f"[sty_custom] done: {output_path}", flush=True)
    return output_path


def stylize_fast(content_path: str, style_id: int, output_path: str,
                 progress_callback=None, cancel_check=None,
                 cw=0.8, sw=2e8, tv=3e-4) -> str:
    content = load_img(content_path, max_size=600)
    _, _, h, w = content.shape

    if should_cancel(cancel_check):
        raise InterruptedError("Cancelled")

    target = content + 0.02 * torch.randn_like(content)
    target.requires_grad_(True)

    vgg = get_vgg()
    style_grams = get_style_grams(style_id)
    with torch.no_grad():
        content_feat = vgg(content)[0].detach()

    opt = optim.Adam([target], lr=0.05)
    NUM = 80
    print(f"[sty_fast] style={STYLE_NAMES[style_id]} size={h}x{w} steps={NUM}", flush=True)
    for step in range(NUM):
        if step % CANCEL_CHECK_INTERVAL == 0 and should_cancel(cancel_check):
            raise InterruptedError("Cancelled")
        opt.zero_grad()
        cf, sfs = vgg(target)
        c_loss = F.mse_loss(cf, content_feat)
        s_loss = sum(F.mse_loss(gram(sf), sg) for sf, sg in zip(sfs, style_grams)) / len(sfs)
        tv_loss = F.l1_loss(target[:,:,1:,:], target[:,:,:-1,:]) + F.l1_loss(target[:,:,:,1:], target[:,:,:,:-1])
        loss = cw * c_loss + sw * s_loss + tv * tv_loss
        loss.backward()
        opt.step()
        if step % 10 == 0 or step == 0:
            print(f"  [{step}/{NUM}] l={loss.item():.0f} c={c_loss.item():.2f} s={s_loss.item():.0f}", flush=True)
        if step % 10 == 0 and progress_callback:
            prog_path = f"{output_path}.prog{step}.jpg"
            save_img(target, prog_path)
            progress_callback(step, NUM, prog_path)

    save_img(target, output_path)
    Image.open(output_path).filter(ImageFilter.UnsharpMask(radius=1, percent=80, threshold=3)).save(output_path, quality=95)
    print(f"[sty_fast] done: {output_path}", flush=True)
    return output_path


def stylize_deep(content_path: str, style_id: int, output_path: str,
                 progress_callback=None, cancel_check=None,
                 cw=0.7, sw=3e8, tv=3e-4) -> str:
    vgg = get_vgg()
    style_grams = get_style_grams(style_id)

    content0 = load_img(content_path, max_size=200)
    _, _, h0, w0 = content0.shape
    target = content0 + 0.02 * torch.randn_like(content0)
    target.requires_grad_(True)
    with torch.no_grad():
        content_feat0 = vgg(content0)[0].detach()
    total_steps = 100 + 120
    done = [0]

    print(f"[sty_deep] style={STYLE_NAMES[style_id]} multi-scale: 200px→400px {total_steps}steps", flush=True)

    opt1 = optim.Adam([target], lr=0.08)
    run_phase(vgg, opt1, target, content_feat0, style_grams, 100, "200px",
              total_steps, done, output_path, progress_callback, cancel_check,
              cw=cw, sw=sw, tv=tv)

    if should_cancel(cancel_check):
        raise InterruptedError("Cancelled")
    content = F.interpolate(content0, scale_factor=2, mode="bicubic", align_corners=False)
    target = F.interpolate(target.detach(), scale_factor=2, mode="bicubic", align_corners=False)
    target = target + 0.02 * torch.randn_like(target)
    _, _, h, w = target.shape
    target.requires_grad_(True)
    with torch.no_grad():
        content_feat = vgg(content)[0].detach()

    opt2 = optim.Adam([target], lr=0.04)
    run_phase(vgg, opt2, target, content_feat, style_grams, 120, "400px",
              total_steps, done, output_path, progress_callback, cancel_check,
              cw=cw, sw=sw, tv=tv)

    save_img(target, output_path)
    Image.open(output_path).filter(ImageFilter.UnsharpMask(radius=1, percent=80, threshold=3)).save(output_path, quality=95)
    print(f"[sty_deep] done: {output_path}", flush=True)
    return output_path


def stylize_ultra(content_path: str, style_id: int, output_path: str,
                  progress_callback=None, cancel_check=None,
                  cw=0.65, sw=4e8, tv=4e-4) -> str:
    vgg = get_vgg()
    style_grams = get_style_grams(style_id)

    content0 = load_img(content_path, max_size=260)
    target = content0 + 0.02 * torch.randn_like(content0)
    target.requires_grad_(True)
    with torch.no_grad():
        content_feat0 = vgg(content0)[0].detach()

    total_steps = 160 + 200
    done = [0]
    print(f"[sty_ultra] style={STYLE_NAMES[style_id]} multi-scale: 260px->520px {total_steps}steps", flush=True)

    opt1 = optim.Adam([target], lr=0.07)
    run_phase(vgg, opt1, target, content_feat0, style_grams, 160, "260px",
              total_steps, done, output_path, progress_callback, cancel_check,
              cw=cw, sw=sw, tv=tv)

    if should_cancel(cancel_check):
        raise InterruptedError("Cancelled")
    content = F.interpolate(content0, scale_factor=2, mode="bicubic", align_corners=False)
    target = F.interpolate(target.detach(), scale_factor=2, mode="bicubic", align_corners=False)
    target = target + 0.015 * torch.randn_like(target)
    target.requires_grad_(True)
    with torch.no_grad():
        content_feat = vgg(content)[0].detach()

    opt2 = optim.Adam([target], lr=0.035)
    run_phase(vgg, opt2, target, content_feat, style_grams, 200, "520px",
              total_steps, done, output_path, progress_callback, cancel_check,
              cw=cw, sw=sw, tv=tv)

    save_img(target, output_path)
    Image.open(output_path).filter(ImageFilter.UnsharpMask(radius=1, percent=90, threshold=2)).save(output_path, quality=96)
    print(f"[sty_ultra] done: {output_path}", flush=True)
    return output_path
