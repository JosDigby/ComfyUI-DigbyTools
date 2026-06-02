from __future__ import annotations
from comfy_api.latest import io
from comfy_extras.nodes_audio import VAEEncodeAudio
import comfy.model_management
import torch


class DigbyLTXVLatentPrep(io.ComfyNode):
    @classmethod
    
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="DigbyLTXVLatentPrep",
            display_name="Digby LTXV Latent Prep",
            category="DigbyTools/ltxv",
            inputs=[
                io.Vae.Input(id="video_vae", tooltip="LTXV Video VAE"),
                io.Vae.Input(id="audio_vae", tooltip="LTXV Audio VAE"),
                io.Boolean.Input(id="downscale_2stage", default=True),
                io.Int.Input(id="length_in_seconds", default=5, min=1, max=45),
                io.Int.Input(id="width", default=1280, min=2, step=2),
                io.Int.Input(id="height", default=720, min=2, step=2),
                io.Image.Input(id="template_images", optional=True),
                io.Audio.Input(id="custom_audio", optional=True),
            ],
            outputs=[
                io.Latent.Output(display_name="video_latent"),
                io.Latent.Output(display_name="audio_latent"),
                io.Image.Output(display_name="template_images")
            ]
        )
    
    @classmethod
    def execute(cls, video_vae, audio_vae, downscale_2stage, length_in_seconds, width, height, template_images=None, custom_audio=None) -> io.NodeOutput:
        real_height= height
        real_width = width
        frame_count = (length_in_seconds*24)+1

        video_latents = None
        audio_latents = None

        video_samples = None
        video_samples = None

        output_images = template_images
        if template_images is not None:
            (frame_count,real_height,real_width,C) = template_images.shape
        else:
            output_images = torch.zeros(1,height, width, 3)


        if downscale_2stage:
            real_height = int(real_height / 2)
            real_width = int(real_width / 2)

        video_samples = torch.zeros([1, 128, ((frame_count - 1) // 8) + 1, real_height // 32, real_width // 32], device=comfy.model_management.intermediate_device())
        video_latents = {"samples": video_samples, "downscale_ratio_spacial": 32}

        if custom_audio is None:
            z_channels = audio_vae.latent_channels
            audio_freq = audio_vae.first_stage_model.latent_frequency_bins
            num_audio_latents = audio_vae.first_stage_model.num_of_latents_from_frames(frame_count, 24)

            audio_samples = torch.zeros(
                (1, z_channels, num_audio_latents, audio_freq)
                , device=comfy.model_management.intermediate_device()
            )
            audio_latents =  {"samples": audio_samples, "type": "audio", }
        else:
            audio_samples = VAEEncodeAudio.execute(audio_vae, custom_audio).result[0]["samples"]
            audio_mask = torch.zeros(1, 1,real_height, real_width)
            audio_latents =  {"samples": audio_samples, "type": "audio", "noise_mask": audio_mask}
        

        return io.NodeOutput(video_latents, audio_latents, output_images)


        
