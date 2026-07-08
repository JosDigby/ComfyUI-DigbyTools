from __future__ import annotations
from comfy_api.latest import io
from comfy_extras.nodes_audio import VAEEncodeAudio
from comfy_extras.nodes_lt import get_noise_mask, LTXVAddGuide, _append_guide_attention_entry

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
                io.Float.Input(id="frame_rate", default=24, min=12),
                io.Int.Input(id="minimum_seconds", default=3, min=1, max=45),
                io.Int.Input(id="width", default=1280, min=2, step=2),
                io.Int.Input(id="height", default=720, min=2, step=2),
                io.Image.Input(id="template_images", optional=True),
                io.Audio.Input(id="custom_audio", optional=True),
            ],
            outputs=[
                io.Latent.Output(display_name="video_latent"),
                io.Latent.Output(display_name="audio_latent"),
                io.Image.Output(display_name="template_images"),
                io.Int.Output(display_name="frame_count"),
                io.Float.Output(display_name="frame_rate"),
            ]
        )
    
    @classmethod
    def execute(cls, video_vae, audio_vae, downscale_2stage, minimum_seconds, width, height, frame_rate, template_images=None, custom_audio=None) -> io.NodeOutput:
        real_height= height
        real_width = width
        frame_count = (minimum_seconds*frame_rate)+1

        video_latents = None
        audio_latents = None

        video_samples = None
        video_samples = None

        output_images = template_images
        if template_images is not None:
            (template_frame_count,real_height,real_width,C) = template_images.shape
            if (template_frame_count > frame_count):
                frame_count = template_frame_count
        else:
            output_images = torch.zeros(1,height, width, 3)


        if downscale_2stage:
            real_height = int(real_height / 2)
            real_width = int(real_width / 2)

        video_samples = torch.zeros([1, 128, ((frame_count - 1) // 8) + 1, real_height // 32, real_width // 32], device=comfy.model_management.intermediate_device())
        video_latents = {"samples": video_samples, "downscale_ratio_spacial": 32}

        num_audio_latents = audio_vae.first_stage_model.num_of_latents_from_frames(frame_count, frame_rate) # Calculate the expected audio latent size
        if custom_audio is None:
            z_channels = audio_vae.latent_channels
            audio_freq = audio_vae.first_stage_model.latent_frequency_bins
        
            audio_samples = torch.zeros(
                (1, z_channels, num_audio_latents, audio_freq)
                , device=comfy.model_management.intermediate_device()
            )
            audio_latents =  {"samples": audio_samples, "type": "audio"}
        else:
            real_custom_audio = {
                'waveform': custom_audio['waveform'],
                'sample_rate': custom_audio['sample_rate']
            }

            audio_samples = VAEEncodeAudio.execute(audio_vae, real_custom_audio).result[0]["samples"]
            audio_mask = torch.zeros_like(audio_samples)

            if (audio_samples.shape[2] > num_audio_latents): # truncate - probably unnecessary
                audio_samples = audio_samples[:, :, :num_audio_latents]
                audio_mask = audio_mask[:,:,:num_audio_latents,:]

            if (audio_samples.shape[2] < num_audio_latents): # pad, setting noise mask to 1 for padded portion
                padding_frames = num_audio_latents - audio_samples.shape[2]
                pad_samples = torch.zeros(
                    audio_samples.shape[0],
                    audio_samples.shape[1],
                    padding_frames,
                    audio_samples.shape[3],      
                    dtype=audio_samples.dtype,
                    device=audio_samples.device
                )
                audio_samples = torch.cat([audio_samples, pad_samples], dim=2)

                pad_mask = torch.ones(
                    audio_mask.shape[0],
                    audio_mask.shape[1],
                    padding_frames,
                    audio_mask.shape[3],
                    dtype=audio_mask.dtype,
                    device=audio_mask.device
                )
                audio_mask = torch.cat([audio_mask, pad_mask], dim=2)

            audio_latents =  {"samples": audio_samples, "type": "audio", "noise_mask": audio_mask}
     
        return io.NodeOutput(video_latents, audio_latents, output_images, output_images.shape[0], frame_rate)


        
class DigbyLTXVAddGuidesFromBatch(LTXVAddGuide):

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DigbyLTXVAddGuidesFromBatch",           
            display_name="Digby LTXV Add Guides From Batch",
            category="DigbyTools/ltxv",
            description="Adds multiple guide images from a batch to the latent at corresponding frame indices. Non-black images in the batch are used as guides.",
            inputs=[
                io.Conditioning.Input("positive"),
                io.Conditioning.Input("negative"),
                io.Vae.Input("vae"),
                io.Latent.Input("latent"),
                io.Image.Input("images", tooltip="Batch of images - non-black images will be used as guides"),
                io.Float.Input("strength", default=1.0, min=0.0, max=10.0, step=0.01, tooltip="Strength for all guides."),
            ],
            outputs=[
                io.Conditioning.Output(display_name="positive"),
                io.Conditioning.Output(display_name="negative"),
                io.Latent.Output(display_name="latent"),
            ],
        )

    @classmethod
    def execute(cls, positive, negative, vae, latent, images, strength) -> io.NodeOutput:
        scale_factors = vae.downscale_index_formula
        latent_image = latent["samples"]
        noise_mask = get_noise_mask(latent)

        _, _, latent_length, latent_height, latent_width = latent_image.shape

        black_threshold = 0.001
        # Process each image in the batch
        batch_size = images.shape[0]

        image_run = { "start": -1, "length": 0 }
        if images[0].max() > black_threshold:
            image_run["start"] = 0
            image_run["length"] = 1

        for i in range(1,batch_size):
            add_run = False

            if (images[i].max() <= black_threshold):
                add_run = True
            else:
                if (image_run["start"] == -1): image_run["start"] = i
                image_run["length"] = image_run["length"] + 1
                if (i == batch_size - 1):
                    add_run = True

            if ((add_run) and (image_run["start"] >= 0)):
                print(f"DigbyTools: At index [{i}] we will start the encode process for images based on {image_run}")
                f_idx = image_run["start"]
                img = images[f_idx: f_idx + image_run["length"]]
                image_run = { "start": -1, "length": 0 } # Reset now before moving on

                image_1, t = cls.encode(vae, latent_width, latent_height, img, scale_factors)

                frame_idx, latent_idx = cls.get_latent_index(positive, latent_length, len(image_1), f_idx, scale_factors)

                if latent_idx + t.shape[2] <= latent_length:
                    positive, negative, latent_image, noise_mask = cls.append_keyframe(
                        positive,
                        negative,
                        frame_idx,
                        latent_image,
                        noise_mask,
                        t,
                        strength,
                        scale_factors,
                    )

                    # Track this guide for per-reference attention control.
                    pre_filter_count = t.shape[2] * t.shape[3] * t.shape[4]
                    guide_latent_shape = list(t.shape[2:])  # [F, H, W]
                    positive, negative = _append_guide_attention_entry(positive, negative, pre_filter_count, guide_latent_shape, strength=strength)
                else:
                    print(f"Warning: Skipping guide at index {f_idx} - conditioning frames exceed latent sequence length")

        return io.NodeOutput(positive, negative, {"samples": latent_image, "noise_mask": noise_mask})