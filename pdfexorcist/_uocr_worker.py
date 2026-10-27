"""Baidu Unlimited-OCR 2 in a subprocess, under $PDFEXORCIST_UOCR_PYTHON (needs transformers 4.52).

Protocol as _vision_worker: a 4-byte length and a PNG in, one JSON string out.
"""

import io
import json
import sys
import time

import torch
from PIL import Image
from transformers import AutoModel, AutoTokenizer

MODEL = "baidu/Unlimited-OCR-2"


def load() -> tuple:
    """The model on CUDA, else MPS, else CPU."""
    from transformers import dynamic_module_utils as dmu

    # triton has no macOS build; the model's code imports it only inside try blocks
    get_imports = dmu.get_imports
    dmu.get_imports = lambda f: [m for m in get_imports(f) if m != "triton"]
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    m = AutoModel.from_pretrained(
        MODEL, trust_remote_code=True, use_safetensors=True, torch_dtype=torch.bfloat16
    ).eval()
    if torch.cuda.is_available():
        return m.cuda(), tok
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    # the remote code calls .cuda() on an image mask
    torch.Tensor.cuda = lambda t, *a, **k: t.to(device)
    return m.to(device), tok


def main() -> None:
    out, sys.stdout = sys.stdout, sys.stderr  # the model's code prints; stdout carries replies
    model, tok = load()
    stdin = sys.stdin.buffer
    while len(head := stdin.read(4)) == 4:
        img = Image.open(io.BytesIO(stdin.read(int.from_bytes(head, "big")))).convert("RGB")
        # gundam tiles; the n-gram block stops a repeated row looping to max_new_tokens
        t0 = time.time()
        text = model.infer(
            tok, image_file=img, eval_mode=True, crop_mode=True,
            no_repeat_ngram_size=35, ngram_window=128, max_new_tokens=8192,
        )  # fmt: skip
        out.write(json.dumps(text) + "\n")
        out.flush()
        print(f"{img.size} {time.time() - t0:.0f}s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
