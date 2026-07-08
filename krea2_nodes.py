import math
from typing import Any

import torch

from comfy_api.latest import io
import comfy.patcher_extension


WRAPPER_KEY = "digby_krea2_filter"

KREA2_TAP_LAYERS = (2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35)
KREA2_TAP_DIM = 2560
KREA2_CHUNK_COUNT = 24
KREA2_CHUNK_DIM = 1280

ENHANCER_GLOBAL_MULTIPLIER = 15.0
TXTFUSION_TOKEN_REL_CAP = 0.75

def _is_krea2_dm(dm: Any) -> bool:
    return (
        hasattr(dm, "txtfusion")
        and hasattr(dm, "txtmlp")
        and hasattr(dm, "blocks")
        and hasattr(dm, "_unpack_context")
        and int(getattr(dm, "txtlayers", 0)) == len(KREA2_TAP_LAYERS)
        and int(getattr(dm, "txtdim", 0)) == KREA2_TAP_DIM
    )


def _step_progress(transformer_options: dict[str, Any]) -> tuple[float, float]:
    sigma = transformer_options.get("sigmas")
    sigma_value = 0.0
    if torch.is_tensor(sigma) and sigma.numel() > 0:
        sigma_value = float(sigma.detach().flatten()[0].float().item())
    elif isinstance(sigma, (int, float)):
        sigma_value = float(sigma)

    sample_sigmas = transformer_options.get("sample_sigmas")
    if torch.is_tensor(sample_sigmas) and sample_sigmas.numel() > 1:
        sig = sample_sigmas.detach().float().flatten()
        idx = int(torch.argmin((sig - sigma_value).abs()).item())
        progress = idx / max(1, int(sig.numel()) - 1)
        return float(progress), sigma_value
    return 0.0, sigma_value


def _rms_scalar(x: torch.Tensor) -> float:
    xf = x.detach().float()
    return float(torch.sqrt(torch.mean(xf * xf)).item())


def _cosine_scalar(a: torch.Tensor, b: torch.Tensor) -> float:
    af = a.detach().float().flatten()
    bf = b.detach().float().flatten()
    denom = torch.linalg.vector_norm(af).clamp_min(1e-8) * torch.linalg.vector_norm(bf).clamp_min(1e-8)
    return float(torch.dot(af, bf).div(denom).item())


def _chunk_gains(device: torch.device, dtype: torch.dtype, strength: float, transformer_options = None) -> torch.Tensor:

    transformer_options = transformer_options or {}
    cfg = transformer_options.get(WRAPPER_KEY, {})

    layer_09 = cfg.get("layer_09", 0)
    layer_10 = cfg.get("layer_10", 0)

    ENHANCER_PROFILE_12 = (0, 0, 0, 0, 0, 0, 0, 0, layer_09, layer_10, 0, 0)
    ENHANCER_CHUNK_PROFILE = ENHANCER_PROFILE_12 + ENHANCER_PROFILE_12

    base = torch.tensor(ENHANCER_CHUNK_PROFILE, device=device, dtype=torch.float32)
    gains = 1.0 + float(strength) * (base - 1.0)
    return gains.to(dtype=dtype)


def _run_refiners(txtfusion, y_text, mask=None, transformer_options=None):
    out = y_text
    for block in txtfusion.refiner_blocks:
        out = block(out, mask=mask, transformer_options=transformer_options or {})
    return out


def _run_txtfusion_parts(txtfusion, x, mask=None, transformer_options=None):
    transformer_options = transformer_options or {}
    b, seq, taps, dim = x.shape
    y = x.reshape(b * seq, taps, dim)
    for block in txtfusion.layerwise_blocks:
        y = block(y.contiguous(), mask=None, transformer_options=transformer_options)
    tap_mix = y.reshape(b, seq, taps, dim).permute(0, 1, 3, 2).contiguous()
    projected = txtfusion.projector(tap_mix).squeeze(-1)
    out = _run_refiners(txtfusion, projected, mask=mask, transformer_options=transformer_options)
    return out, projected


def _enhanced_txtfusion_forward(
    txtfusion,
    x,
    mask=None,
    transformer_options=None,
    strength=1.0,
    collect_debug=False,
):
    transformer_options = transformer_options or {}
    b, seq, taps, dim = x.shape
    if taps != len(KREA2_TAP_LAYERS) or dim != KREA2_TAP_DIM:
        out = txtfusion._krea2t_enhancer_original_forward(
            x,
            mask=mask,
            transformer_options=transformer_options,
        )
        return out, None

    reference_out, reference_projected = _run_txtfusion_parts(
        txtfusion,
        x,
        mask=mask,
        transformer_options=transformer_options,
    )

    if strength != 0.0:
        gains = _chunk_gains(x.device, x.dtype, strength, transformer_options)
        global_multiplier = 1.0 + float(strength) * (ENHANCER_GLOBAL_MULTIPLIER - 1.0)
        scaled_x = (
            x.reshape(b, seq, KREA2_CHUNK_COUNT, KREA2_CHUNK_DIM)
            * gains.view(1, 1, KREA2_CHUNK_COUNT, 1)
            * global_multiplier
        ).reshape_as(x)
        candidate_out, candidate_projected = _run_txtfusion_parts(
            txtfusion,
            scaled_x,
            mask=mask,
            transformer_options=transformer_options,
        )
    else:
        global_multiplier = 1.0
        scaled_x = x
        candidate_out = reference_out
        candidate_projected = reference_projected

    post_delta = candidate_out.detach().float() - reference_out.detach().float()
    token_base_rms = torch.sqrt(torch.mean(reference_out.detach().float() ** 2, dim=-1, keepdim=True)).clamp_min(1e-8)
    token_delta_rms = torch.sqrt(torch.mean(post_delta ** 2, dim=-1, keepdim=True)).clamp_min(1e-8)
    token_rel = token_delta_rms / token_base_rms

    token_scale = (TXTFUSION_TOKEN_REL_CAP / token_rel).clamp(max=1.0)

    out = (reference_out.detach().float() + post_delta * token_scale).to(candidate_out.dtype)

    debug = None
    if collect_debug:
        ref_rms = _rms_scalar(reference_projected)
        raw_rms = _rms_scalar(candidate_projected)
        out_delta = out.detach().float() - reference_out.detach().float()
        post_base_rms = _rms_scalar(reference_out)
        debug = {
            "shape": "x".join(str(int(v)) for v in out.shape),
            "global_multiplier": float(global_multiplier),
            "projector_rms_ratio": float(raw_rms / max(ref_rms, 1e-8)),
            "output_rel_delta": float(_rms_scalar(out_delta) / max(post_base_rms, 1e-8)),
            "output_cosine": _cosine_scalar(reference_out, out),
            "clamp_mean": float(token_scale.mean().item()),
            "token_raw_rel_mean": float(token_rel.mean().item()),
            "input_tap_rms": [
                float(v) for v in torch.sqrt(torch.mean(x.detach().float() ** 2, dim=(0, 1, 3))).detach().cpu().tolist()
            ],
            "scaled_tap_rms": [
                float(v) for v in torch.sqrt(torch.mean(scaled_x.detach().float() ** 2, dim=(0, 1, 3))).detach().cpu().tolist()
            ],
        }

    return out, debug


def krea2t_enhancer_wrapper(executor, x, timesteps, context, attention_mask=None, transformer_options=None, **kwargs):
    transformer_options = transformer_options or {}
    cfg = transformer_options.get(WRAPPER_KEY, {})
    if not cfg or not cfg.get("enabled", True):
        return executor(x, timesteps, context, attention_mask, transformer_options, **kwargs)

    if cfg.get("_active", False):
        return executor(x, timesteps, context, attention_mask, transformer_options, **kwargs)

    dm = executor.class_obj
    if not _is_krea2_dm(dm):
        if cfg.get("debug", False):
            print("[DigbyKrea2Filter] skipped: diffusion model does not match Krea2 text-fusion layout")
        return executor(x, timesteps, context, attention_mask, transformer_options, **kwargs)

    strength = cfg.get("strength", 1.0)
    if strength == 0.0:
        return executor(x, timesteps, context, attention_mask, transformer_options, **kwargs)

    txtfusion = dm.txtfusion
    if hasattr(txtfusion, "_krea2t_enhancer_original_forward"):
        txtfusion.forward = txtfusion._krea2t_enhancer_original_forward
        delattr(txtfusion, "_krea2t_enhancer_original_forward")
    original_forward = txtfusion.forward
    progress, sigma = _step_progress(transformer_options)
    debug_enabled = bool(cfg.get("debug", False))

    def enhanced_forward(x_in, mask=None, transformer_options=None):
        txtfusion._krea2t_enhancer_original_forward = original_forward
        try:
            after, debug = _enhanced_txtfusion_forward(
                txtfusion,
                x_in,
                mask=mask,
                transformer_options=transformer_options or {},
                strength=strength,
                collect_debug=debug_enabled,
            )
        finally:
            if hasattr(txtfusion, "_krea2t_enhancer_original_forward"):
                delattr(txtfusion, "_krea2t_enhancer_original_forward")

        if debug is not None and int(cfg.setdefault("_debug_prints", 0)) < int(cfg.get("max_debug_prints", 8)):
            cfg["_debug_prints"] = int(cfg.get("_debug_prints", 0)) + 1
            print(
                "[DigbyKrea2Filter] "
                f"strength={strength:.3f} progress={progress:.3f} sigma={sigma:.6g} "
                f"global={debug['global_multiplier']:.6g} proj_ratio={debug['projector_rms_ratio']:.6g} "
                f"out_rel={debug['output_rel_delta']:.6g} out_cos={debug['output_cosine']:.6g} "
                f"clamp={debug['clamp_mean']:.6g}"
            )
        return after

    try:
        cfg["_active"] = True
        txtfusion.forward = enhanced_forward
        return executor(x, timesteps, context, attention_mask, transformer_options, **kwargs)
    finally:
        cfg["_active"] = False
        txtfusion.forward = original_forward


class DigbyKrea2Patch(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DigbyKrea2Patch",           
            display_name="Digby Krea2 Filter Patch",
            category="DigbyTools/krea2",
            description="Alters the layer weights of txtfusion layers 26 & 29.  Community research determins that these layer are where most of the text-encoding safety filtering occurs.",
            inputs=[
                io.Model.Input(id="model"),
                io.Boolean.Input(id="enabled", default=True),
                io.Float.Input(id="strength", default=1, min=0.0, step=0.05),
                io.Float.Input(id="layer_09", default=1.25, min=0.00, step=0.05),
                io.Float.Input(id="layer_10", default=2.25, min=0.00, step=0.05),
                io.Boolean.Input(id="debug", default=False),
            ],
            outputs=[
                io.Model.Output(display_name="model"),
            ],
        )

    @classmethod
    def execute(self, model, enabled=True, strength=1.0, layer_09=1.25, layer_10=2.25, debug=False) -> io.NodeOutput:
        patched = model.clone()
        to = patched.model_options.setdefault("transformer_options", {})
        to[WRAPPER_KEY] = {
            "enabled": bool(enabled),
            "strength": strength,
            "debug": bool(debug),
            "max_debug_prints": 8,
            "layer_09": layer_09,
            "layer_10": layer_10,
        }
        if hasattr(patched, "remove_wrappers_with_key"):
            patched.remove_wrappers_with_key(
                comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL,
                WRAPPER_KEY,
            )
        wrappers = to.get("wrappers", {})
        diffusion_wrappers = wrappers.get(comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL, {})
        diffusion_wrappers.pop(WRAPPER_KEY, None)
        patched.add_wrapper_with_key(
            comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL,
            WRAPPER_KEY,
            krea2t_enhancer_wrapper,
        )
        if debug:
            print(f"[DigbyKrea2Filter] attached enabled={bool(enabled)} strength={strength:.3f}")
        
        return io.NodeOutput(patched, )
        
        
class DigbyRange(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DigbyRange",           
            display_name="Digby Float Range Generator",
            category="DigbyTools/data",
            description="From a starting value, creates a list of float values, stepping by STEP and with a count of COUNT.",
            inputs=[
                io.Float.Input(id="start", default=0.00, step=0.01),
                io.Float.Input(id="stop", default=1.00, step=0.01),
                io.Int.Input(id="count", default=2, min=1),
            ],
            outputs=[
                io.Float.Output(display_name="float_list", is_output_list=True),
            ],
        )

    @classmethod
    def execute(self, start, stop, count) -> io.NodeOutput:
        if count <= 1:
            raise ValueError("Count must be 2 or more.")

        span = stop - start
        gaps = count - 1

        output_list = list()
        for i in range(0,count,1):
            output_list.append(round(start + span*i/gaps , 2))
        return io.NodeOutput(output_list,)
