import torch
from numpy import linspace

import comfy.sample
import comfy.samplers
import comfy.utils
import comfy.model_sampling

from comfy_api.latest import io

import latent_preview

# Forked from https://github.com/stduhpf/ComfyUI-WanMoeKSampler

def _2stage_ksampler(model_high_noise, model_low_noise, seed, steps, cfgs, sampler_name, scheduler, positive, negative, latent, boundary = 0.875, denoise=1.0, disable_noise=False, start_step=None, last_step=None, force_full_denoise=False, high_steps=99):
    # boundary is .9 for i2v, .875 for t2v
    latent_image = latent["samples"]

    if disable_noise:
        noise = torch.zeros(latent_image.size(), dtype=latent_image.dtype, layout=latent_image.layout, device="cpu")
    else:
        batch_inds = latent["batch_index"] if "batch_index" in latent else None
        noise = comfy.sample.prepare_noise(latent_image, seed, batch_inds)

    noise_mask = None
    if "noise_mask" in latent:
        noise_mask = latent["noise_mask"]

    disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED
    assert start_step is None or start_step < steps
    assert last_step is None or last_step >= start_step
    if start_step is None:
        start_step = 0
    if last_step is None:
        last_step=99

    # first, we get all sigmas - Disabled by Wayland 2025-11-24.  Incorrect sigmas for the WAN2.2 model
    sampling = model_high_noise.get_model_object("model_sampling")
    sigmas = comfy.samplers.calculate_sigmas(sampling,scheduler,steps)

    switching_step = steps

    # Wayland Reid - Set switching step manually 
    if (high_steps < steps):
        print("Switching step set manually.")
        switching_step = high_steps

    print(f"DigbyTools: Switching model at step {switching_step}")
    start_with_high = start_step<switching_step
    end_wth_low = last_step>=switching_step

    if start_with_high:
        print("DigbyTools: Running Stage 1 model...")
        callback = latent_preview.prepare_callback(model_high_noise, steps)
        end_step = min(last_step,switching_step)
        latent_image = comfy.sample.fix_empty_latent_channels(model_high_noise, latent_image)
        latent_image = comfy.sample.sample(model_high_noise, noise, steps, cfgs[0], sampler_name, scheduler, positive, negative, latent_image,
                                    denoise=denoise, disable_noise=end_wth_low or disable_noise, start_step=start_step, last_step=end_step,
                                    force_full_denoise=end_wth_low or force_full_denoise, noise_mask=noise_mask, callback=callback, disable_pbar=disable_pbar, seed=seed,
                                    sigmas=sigmas.detach().clone().to(model_high_noise.load_device))


    if end_wth_low:
        print("DigbyTools: Running Stage 2 model...")
        callback = latent_preview.prepare_callback(model_low_noise, steps)
        begin_step = max(start_step, switching_step)
        latent_image = comfy.sample.fix_empty_latent_channels(model_low_noise, latent_image)
        latent_image = comfy.sample.sample(model_low_noise, noise, steps, cfgs[1], sampler_name, scheduler, positive, negative, latent_image,
                                    denoise=denoise, disable_noise=disable_noise, start_step=begin_step, last_step=last_step,
                                    force_full_denoise=force_full_denoise, noise_mask=noise_mask, callback=callback, disable_pbar=disable_pbar, seed=seed,
                                    sigmas=sigmas.detach().clone().to(model_low_noise.load_device))

    out = latent.copy()
    out["samples"] = latent_image
    return (out, )


class Digby2StageKSampler(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="Digby2StageKSampler",
            display_name="Digby 2 Stage KSampler",
            category="DigbyTools/ksamplers",
            description="Uses two models to perform sampling, switching at the speficied step.",
            inputs=[
                io.Model.Input(id="stage_1_model", tooltip="The first stage model used for denoising the input latent."),
                io.Model.Input(id="stage_2_model", tooltip="The second stage model used for denoising the input latent."),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF, control_after_generate=True),
                io.Int.Input(id="stage_1_steps", default=2, min=0, max=50),
                io.Int.Input(id="stage_2_steps", default=4, min=0, max=50),
                io.Combo.Input(id="sampler_name", options=comfy.samplers.KSampler.SAMPLERS),
                io.Combo.Input(id="scheduler",  options=comfy.samplers.KSampler.SCHEDULERS),                        
                io.Conditioning.Input(id="positive"),
                io.Latent.Input(id="latent"),
            ],
            outputs=[
                io.Latent.Output(id="latent"),
            ],
        )

    @classmethod
    def execute(self, stage_1_model, stage_2_model, seed, stage_1_steps, stage_2_steps, sampler_name, scheduler, positive, latent):
        cfg = 1.0
        denoise = 1.0

        negative = []
        for t in positive:
            d = t[1].copy()
            pooled_output = d.get("pooled_output", None)
            if pooled_output is not None:
                d["pooled_output"] = torch.zeros_like(pooled_output)
            conditioning_lyrics = d.get("conditioning_lyrics", None)
            if conditioning_lyrics is not None:
                d["conditioning_lyrics"] = torch.zeros_like(conditioning_lyrics)
            n = [torch.zeros_like(t[0]), d]
            negative.append(n)

        return _2stage_ksampler(stage_1_model, stage_2_model, seed, stage_2_steps + stage_1_steps, (cfg, cfg), sampler_name, scheduler, positive, negative, latent, denoise=denoise, high_steps=stage_1_steps)
