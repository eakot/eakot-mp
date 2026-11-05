#!/usr/bin/env python3
"""Paint the wiki's plates on a ComfyUI server: mood art with no text, never a fact.

The prompts live in wiki.json under "plates": {"style": "...", "prompts": {"<plate name>": "<scene>"}}.
A plate the config names but `prompts` lacks is skipped with a note.

    python3 plates.py SITE/wiki.json --comfy http://HOST:8188            # render the missing plates
    python3 plates.py SITE/wiki.json --comfy http://HOST:8188 --force hero
    python3 plates.py SITE/wiki.json --comfy URL --workflow my-graph.json  # another model

The default graph is Qwen-Image 2512 with the Lightning 4-step LoRA (about 100 s a plate on an RTX 3090). That model
garbles any text it draws, which is why every prompt ends in "no text". A --workflow file is a ComfyUI API-format graph
whose strings may hold {{PROMPT}}, {{NEG}}, {{SEED}}, {{W}} and {{H}}; its SaveImage node must have id "11".
Output: SITE/art/<name>.webp (needs Pillow). Run by hand; a site build never calls ComfyUI.
"""
import argparse
import io
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request
import uuid

W, H = 1664, 928  # 16:9 at Qwen-Image's native budget

STYLE = (
    "cinematic hard sci-fi concept art, matte painting, deep navy and black palette, "
    "cyan holographic light with amber accents, volumetric haze, thin glowing data lines, "
    "ultra detailed, wide establishing shot, no text, no letters, no labels, no logos"
)
NEG = "text, letters, words, captions, watermark, signature, logo, blurry, cartoon, anime, lowres"


def workflow(prompt: str, seed: int) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2512_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "Qwen-Image-2512-Lightning-4steps-V1.0-fp32.safetensors", "strength_model": 1.0}},
        "3": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["2", 0], "shift": 3.1}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": NEG}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["3", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0], "seed": seed, "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["5", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": "scifiwiki"}},
    }


def custom(path: str, prompt: str, seed: int) -> dict:
    text = pathlib.Path(path).read_text(encoding="utf-8")
    for k, v in {"PROMPT": prompt, "NEG": NEG}.items():
        text = text.replace("{{%s}}" % k, json.dumps(v)[1:-1])
    for k, v in {"SEED": seed, "W": W, "H": H}.items():
        text = text.replace('"{{%s}}"' % k, str(v)).replace("{{%s}}" % k, str(v))
    return json.loads(text)


def render(comfy: str, graph: dict, name: str) -> bytes:
    COMFY = comfy.rstrip("/")
    body = json.dumps({"prompt": graph, "client_id": str(uuid.uuid4())}).encode()
    req = urllib.request.Request(f"{COMFY}/prompt", body, {"Content-Type": "application/json"})
    pid = json.load(urllib.request.urlopen(req, timeout=30))["prompt_id"]
    deadline = time.time() + 900
    while time.time() < deadline:
        hist = json.load(urllib.request.urlopen(f"{COMFY}/history/{pid}", timeout=30)).get(pid, {})
        if hist.get("status", {}).get("status_str") == "error":
            raise RuntimeError(f"{name}: {json.dumps(hist['status'])[:500]}")
        if hist.get("outputs"):
            img = hist["outputs"]["11"]["images"][0]
            q = urllib.parse.urlencode({k: img[k] for k in ("filename", "subfolder", "type")})
            return urllib.request.urlopen(f"{COMFY}/view?{q}", timeout=60).read()
        time.sleep(3)
    raise TimeoutError(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", help="SITE/wiki.json")
    ap.add_argument("names", nargs="*", help="plates to render (default: every missing one)")
    ap.add_argument("--comfy", required=True, help="ComfyUI base URL, e.g. http://127.0.0.1:8188")
    ap.add_argument("--workflow", help="an API-format graph with {{PROMPT}} {{NEG}} {{SEED}} {{W}} {{H}}")
    ap.add_argument("--force", action="store_true", help="re-render even if the file exists")
    ap.add_argument("--seed", type=int, default=46)
    args = ap.parse_args()
    from PIL import Image  # only this script needs Pillow

    cfg_path = pathlib.Path(args.config).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    plates = cfg.get("plates", {})
    style, prompts = plates.get("style", STYLE), plates.get("prompts", {})
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import wiki
    cfg["_site"], cfg["_root"] = cfg_path.parent, cfg_path.parent
    art = cfg_path.parent / "art"
    art.mkdir(exist_ok=True)
    for name in args.names or sorted(wiki.wanted_plates(cfg)):
        out = art / f"{name}.webp"
        if out.exists() and not args.force:
            continue
        if name not in prompts:
            print(f"{name}: no prompt in wiki.json plates.prompts; skipped")
            continue
        prompt = f"{prompts[name]}, {style}"
        graph = custom(args.workflow, prompt, args.seed) if args.workflow else workflow(prompt, args.seed)
        t = time.time()
        png = render(args.comfy, graph, name)
        Image.open(io.BytesIO(png)).convert("RGB").save(out, "WEBP", quality=80, method=6)
        print(f"{name}: {out.stat().st_size // 1024} KiB in {time.time() - t:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
