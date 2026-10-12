# -*- coding:utf-8 -*-
"""Comfy Cloud Nano Banana image client. Never print the API key."""
from __future__ import annotations

import json
import os
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlencode
from pathlib import Path
from typing import Any

from api_keys import load_keys, require

DEFAULT_BASE = "https://cloud.comfy.org"

def _local_base() -> str:
    cfg_path = Path(__file__).resolve().parent / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig")) if cfg_path.is_file() else {}
    return str(os.environ.get("JIJI_COMFY_URL") or cfg.get("comfy_url") or "http://127.0.0.1:8189").rstrip("/")
MODEL_NB2 = "Nano Banana 2 (Gemini 3.1 Flash Image)"
MODEL_NB2_LITE = "Nano Banana 2 Lite"
MODEL_NB1 = "gemini-2.5-flash-image"
MODEL_NB21 = "gemini-nano-banana-2.1"
MODEL_GPT_IMAGE = "gpt-image-2.5-sunburst"
# 21:9 at about 1K. Both edges are multiples of 16, which GPT Image 2 requires.
GPT_IMAGE_SIZE = {
    ("21:9", "1K"): "1568x672",
}
# Seedream 5.0 Pro 的 1K 21:9，和静帧锁定的尺寸同一档。Lite 最小是 2K，不接。
SEEDREAM_SIZE = {
    ("21:9", "1K"): ("(1K) 1568x672 (21:9)", 1568, 672),
}
# Sunburst 会把高光铺成一层层月牙。这句去掉的是那种闪光，不是主体自己的结构。
GPT_IMAGE_LEAD = (
    "前置条件：画面四周是纯白，白要干净，不要渐变，不要把环境铺满画面。"
    "去掉这种视觉：高光不要碎成一层层叠着的月牙，不要珠光，不要虹彩，不要油亮的碎闪，"
    "不要让皮肤、布、金属和石头都像铺了一层重复的小片。光是连续的，材料是一整块。"
    "东西本身的结构留着。下面才是这一张要画的内容。"
)


class BananaError(RuntimeError):
    pass


def _base() -> str:
    return (load_keys().get("COMFY_BASE_URL") or DEFAULT_BASE).rstrip("/")


def _key() -> str:
    return require("COMFY_API_KEY")


def _headers(*, extra: dict[str, str] | None = None) -> dict[str, str]:
    out = {
        "Authorization": f"Bearer {_key()}",
        "X-API-Key": _key(),
        "User-Agent": "shixian-banana",
    }
    if extra:
        out.update(extra)
    return out


def _request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 60,
    raw: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any] | bytes:
    url = path if path.startswith("http") else _base() + path
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    headers = _headers(extra=extra_headers)
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            if raw:
                return body
            text = body.decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise BananaError(f"HTTP {exc.code} {path}: {err[:1200]}") from exc
    except urllib.error.URLError as exc:
        raise BananaError(f"network {path}: {exc.reason}") from exc


def _nb21_workflow(
    prompt: str,
    *,
    aspect: str,
    resolution: str,
    seed: int,
    image_node: str | None,
    prefix: str = "banana",
) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "prompt": prompt,
        "model": MODEL_NB21,
        "seed": int(seed),
        "aspect_ratio": aspect,
        "resolution": resolution,
        "response_modalities": "IMAGE",
        "thinking_level": "HIGH",
    }
    if image_node:
        inputs["images"] = [image_node, 0]
    return {
        "1": {"class_type": "GeminiNanoBanana2", "inputs": inputs},
        "2": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": prefix, "images": ["1", 0]},
        },
    }


def _nb2_workflow(
    prompt: str,
    *,
    aspect: str,
    resolution: str,
    seed: int,
    lite: bool,
    image_node: str | None,
    prefix: str = "banana",
) -> dict[str, Any]:
    # GeminiNanoBanana2 (flat widgets). V2 DynamicCombo is not stable over HTTP /prompt.
    inputs: dict[str, Any] = {
        "prompt": prompt,
        "model": MODEL_NB2,
        "seed": int(seed),
        "aspect_ratio": aspect,
        "resolution": "1K" if lite else resolution,
        "response_modalities": "IMAGE",
        "thinking_level": "MINIMAL",
    }
    if image_node:
        inputs["images"] = [image_node, 0]
    return {
        "1": {"class_type": "GeminiNanoBanana2", "inputs": inputs},
        "2": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": prefix, "images": ["1", 0]},
        },
    }


def _nb1_workflow(
    prompt: str,
    *,
    aspect: str,
    seed: int,
    image_node: str | None,
    prefix: str = "banana",
) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "prompt": prompt,
        "model": MODEL_NB1,
        "seed": int(seed),
        "aspect_ratio": aspect,
        "response_modalities": "IMAGE",
    }
    if image_node:
        inputs["images"] = [image_node, 0]
    return {
        "1": {"class_type": "GeminiImageNode", "inputs": inputs},
        "2": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": prefix, "images": ["1", 0]},
        },
    }


def upload_image(path: Path) -> dict[str, Any]:
    boundary = uuid.uuid4().hex
    raw = path.read_bytes()
    name = path.name
    parts = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + raw + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="content_type"\r\n\r\nimage/png'
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file_path"\r\n\r\n{name}'
        f"\r\n--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        _base() + "/api/v2/assets",
        data=parts,
        headers=_headers(extra={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Idempotency-Key": str(uuid.uuid4()),
        }),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise BananaError(f"HTTP {exc.code} /api/v2/assets: {err[:1200]}") from exc


def _attach_asset(graph: dict[str, Any], asset: dict[str, Any]) -> str:
    aid = asset.get("id") or asset.get("asset_id")
    if not aid:
        raise BananaError(f"upload missing id: {list(asset)[:12]}")
    graph["10"] = {
        "class_type": "LoadImage",
        "inputs": {"image": {"__type": "core/ASSET", "id": aid}},
    }
    return "10"


def submit_job(workflow: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "workflow": workflow,
        "extra_data": {"api_key_comfy_org": _key()},
    }
    data = _request(
        "POST",
        "/api/v2/jobs",
        payload,
        timeout=120,
        extra_headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    if not isinstance(data, dict):
        raise BananaError("submit: binary response")
    return data


def get_job(job_id: str) -> dict[str, Any]:
    data = _request("GET", f"/api/v2/jobs/{job_id}", timeout=40)
    if not isinstance(data, dict):
        raise BananaError("get_job: binary response")
    return data


def wait_job(job_id: str, timeout: int = 300) -> dict[str, Any]:
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        job = get_job(job_id)
        status = str(job.get("status") or "")
        if status != last:
            print(f"  banana {job_id[:8]} {status}", flush=True)
            last = status
        if status.lower() in {"completed", "succeeded", "success", "complete"}:
            return job
        if status.lower() in {"failed", "error", "cancelled", "canceled"}:
            raise BananaError(f"job {status}: {job.get('error')}")
        time.sleep(2)
    raise BananaError(f"job timeout {job_id}")


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())
    return dest


def _save_outputs(job: dict[str, Any], dest: Path) -> Path:
    outputs = job.get("outputs") or []
    if not outputs:
        urls = (job.get("urls") or {})
        raise BananaError(f"no outputs: keys={list(job)[:16]} urls={list(urls)[:8]}")
    first = outputs[0]
    url = (
        first.get("url")
        or first.get("download_url")
        or (first.get("urls") or {}).get("download")
        or first.get("uri")
    )
    if not url:
        raise BananaError(f"output missing url: {json.dumps(first, ensure_ascii=False)[:400]}")
    return _download(url, dest)


def local_ready() -> bool:
    try:
        urllib.request.urlopen(_local_base() + "/system_stats", timeout=3).read()
        return True
    except Exception:
        return False


def _local_upload(path: Path) -> str:
    boundary = uuid.uuid4().hex
    raw = path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + raw + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue'
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="type"\r\n\r\ninput'
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="subfolder"\r\n\r\nshixian0922/banana'
        f"\r\n--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        _local_base() + "/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        meta = json.loads(r.read().decode())
    name = meta.get("name") or path.name
    sub = meta.get("subfolder") or "shixian0922/banana"
    return f"{sub}/{name}" if sub else name


def _local_queue(graph: dict[str, Any]) -> str:
    payload = {
        "prompt": graph,
        "client_id": "shixian-banana",
        "extra_data": {"api_key_comfy_org": _key()},
    }
    req = urllib.request.Request(
        _local_base() + "/prompt",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise BananaError(f"local HTTP {exc.code}: {err[:1200]}") from exc
    pid = data.get("prompt_id")
    if not pid:
        raise BananaError(f"local queue missing prompt_id: {data}")
    return str(pid)


def _local_wait(pid: str, timeout: int = 480) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(_local_base() + f"/history/{pid}", timeout=30) as r:
                hist = json.loads(r.read().decode())
        except Exception:
            time.sleep(2)
            continue
        if pid in hist:
            return hist[pid]
        print(f"  banana local {pid[:8]} {int(time.time()-t0)}s", flush=True)
        time.sleep(2)
    raise BananaError(f"local timeout {pid}")


def _copy_local_output(hist: dict[str, Any], dest: Path) -> Path:
    # Fetch through ComfyUI; the client does not need its output directory mounted.
    images = [image for node in (hist.get("outputs") or {}).values()
              for image in node.get("images") or [] if image.get("filename")]
    if not images:
        raise BananaError("local job finished but no image file")
    image = images[0]
    query = urlencode({"filename": image["filename"], "subfolder": image.get("subfolder") or "",
                       "type": image.get("type") or "output"})
    with urllib.request.urlopen(_local_base() + "/view?" + query, timeout=120) as response:
        raw = response.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dest


def generate_local(
    prompt: str,
    dest: Path,
    *,
    aspect: str = "1:1",
    resolution: str = "2K",
    seed: int = 42,
    refs: list[Path] | None = None,
    lite: bool = False,
    model: str = "nb2",
    max_refs: int = 4,
) -> Path:
    prefix = dest.stem[:40] or "banana"
    cap = max(1, min(int(max_refs or 4), 8))
    refs = [p for p in (refs or []) if p.is_file()][:cap]
    load_ids: list[str] = []
    loads: dict[str, Any] = {}
    for i, path in enumerate(refs):
        nid = str(10 + i)
        fname = _local_upload(path)
        loads[nid] = {"class_type": "LoadImage", "inputs": {"image": fname}}
        load_ids.append(nid)
    image_node = None
    extra: dict[str, Any] = {}
    if len(load_ids) == 1:
        image_node = load_ids[0]
    elif len(load_ids) > 1:
        prev = load_ids[0]
        for i, nid in enumerate(load_ids[1:], start=1):
            bid = str(20 + i)
            extra[bid] = {
                "class_type": "ImageBatch",
                "inputs": {"image1": [prev, 0], "image2": [nid, 0]},
            }
            prev = bid
        image_node = prev
    if model == "nb21":
        graph = _nb21_workflow(
            prompt, aspect=aspect, resolution=resolution, seed=seed,
            image_node=image_node, prefix=prefix,
        )
    elif model == "nb1":
        graph = _nb1_workflow(
            prompt, aspect=aspect, seed=seed, image_node=image_node, prefix=prefix,
        )
    else:
        graph = _nb2_workflow(
            prompt, aspect=aspect, resolution=resolution, seed=seed,
            lite=lite, image_node=image_node, prefix=prefix,
        )
    graph.update(loads)
    graph.update(extra)
    print("banana local queue", dest.name, flush=True)
    pid = _local_queue(graph)
    hist = _local_wait(pid)
    status = hist.get("status") or {}
    if status.get("status_str") == "error":
        msg = ""
        for item in status.get("messages") or []:
            if item and item[0] == "execution_error":
                msg = str((item[1] or {}).get("exception_message") or "")[:400]
        raise BananaError(f"local fail {msg or status}")
    return _copy_local_output(hist, dest)


def generate_gpt_image(
    prompt: str,
    dest: Path,
    *,
    aspect: str = "21:9",
    resolution: str = "1K",
    seed: int = 42,
    refs: list[Path] | None = None,
    max_refs: int = 8,
) -> Path:
    if (aspect, resolution) not in GPT_IMAGE_SIZE:
        raise BananaError(f"GPT Image 2.5 这一档没有 {aspect} {resolution}。没有改去别的画幅。")
    if not local_ready():
        raise BananaError("出图的 ComfyUI 没开。GPT Image 2.5 走本机 8189。")
    width_text, height_text = GPT_IMAGE_SIZE[(aspect, resolution)].split("x")
    prefix = dest.stem[:40] or "gptimage"
    usable = [path for path in (refs or []) if path.is_file()][: max(0, int(max_refs or 0))]
    inputs: dict[str, Any] = {
        "prompt": GPT_IMAGE_LEAD + prompt,
        "model": MODEL_GPT_IMAGE,
        "model.size": "Custom",
        "model.custom_width": int(width_text),
        "model.custom_height": int(height_text),
        "model.background": "opaque",
        "model.quality": "high",
        "n": 1,
        "seed": int(seed) % 2147483647,
    }
    graph: dict[str, Any] = {
        "1": {"class_type": "OpenAIGPTImageNodeV2", "inputs": inputs},
        "2": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": prefix, "images": ["1", 0]},
        },
    }
    for index, path in enumerate(usable, start=1):
        node_id = str(10 + index)
        graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": _local_upload(path)}}
        inputs[f"model.images.image_{index}"] = [node_id, 0]
    print("gpt image comfy", dest.name, GPT_IMAGE_SIZE[(aspect, resolution)], "refs", len(usable), flush=True)
    pid = _local_queue(graph)
    hist = _local_wait(pid, timeout=600)
    status = hist.get("status") or {}
    if status.get("status_str") == "error":
        msg = ""
        for item in status.get("messages") or []:
            if item and item[0] == "execution_error":
                msg = str((item[1] or {}).get("exception_message") or "")[:400]
        raise BananaError(f"comfy gpt-image-2.5-sunburst {msg or status}")
    return _copy_local_output(hist, dest)


def generate_seedream(
    prompt: str,
    dest: Path,
    *,
    aspect: str = "21:9",
    resolution: str = "1K",
    seed: int = 42,
    refs: list[Path] | None = None,
    max_refs: int = 10,
) -> Path:
    preset = SEEDREAM_SIZE.get((aspect, resolution))
    if preset is None:
        raise BananaError("Seedream 5.0 静帧只走 21:9、1K。没有改尺寸。")
    if not local_ready():
        raise BananaError("出图的 ComfyUI 没开。Seedream 5.0 走本机 8189。")
    label, width, height = preset
    prefix = dest.stem[:40] or "seedream"
    usable = [path for path in (refs or []) if path.is_file()][: max(0, min(int(max_refs or 0), 10))]
    inputs: dict[str, Any] = {
        "prompt": prompt,
        "model.model": "seedream 5.0 pro",
        "model.size_preset": label,
        "model.width": width,
        "model.height": height,
        "model.seed": int(seed) % 2147483647,
        "model.watermark": False,
        "model.thinking": True,
        "model.prompt_optimization": "standard",
    }
    graph: dict[str, Any] = {
        "1": {"class_type": "ByteDanceSeedreamNodeV3", "inputs": inputs},
        "2": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": prefix, "images": ["1", 0]},
        },
    }
    for index, path in enumerate(usable, start=1):
        node_id = str(10 + index)
        graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": _local_upload(path)}}
        inputs[f"model.images.image_{index}"] = [node_id, 0]
    print("seedream comfy", dest.name, label, "refs", len(usable), flush=True)
    pid = _local_queue(graph)
    hist = _local_wait(pid, timeout=900)
    status = hist.get("status") or {}
    if status.get("status_str") == "error":
        msg = ""
        for item in status.get("messages") or []:
            if item and item[0] == "execution_error":
                msg = str((item[1] or {}).get("exception_message") or "")[:400]
        raise BananaError(f"Seedream 5.0 {msg or status}")
    return _copy_local_output(hist, dest)


def generate_image(
    prompt: str,
    dest: Path,
    *,
    aspect: str = "1:1",
    resolution: str = "2K",
    seed: int = 42,
    refs: list[Path] | None = None,
    lite: bool = False,
    model: str = "nb2",
    max_refs: int = 4,
) -> Path:
    if model == "seedream":
        return generate_seedream(
            prompt, dest, aspect=aspect, resolution=resolution, seed=seed,
            refs=refs, max_refs=max_refs,
        )
    if model in {"gpt", "gpt-image-2"}:
        return generate_gpt_image(
            prompt, dest, aspect=aspect, resolution=resolution, seed=seed,
            refs=refs, max_refs=max_refs,
        )
    if local_ready():
        return generate_local(
            prompt, dest, aspect=aspect, resolution=resolution, seed=seed,
            refs=refs, lite=lite, model=model, max_refs=max_refs,
        )
    raise BananaError(
        "Comfy Cloud free tier cannot call /api/v2/jobs. "
        "Start local ComfyUI 8189; Banana Partner Node uses Credits with this key."
    )


