from __future__ import annotations
from comfy_api.latest import io
import comfy.utils
import torch
import json

class DigbyKeyframer(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DigbyKeyframer",
            display_name="Digby Keyframer",
            category="image",
            inputs=[
                io.Autogrow.Input("images",
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input("img"),  # the type for each slot
                        prefix="image_",              # slot names: image_0, image_1, ...
                        min=1,                        # minimum visible slots (default 1)
                        max=16,                       # maximum slots (default 10, hard cap 100)
                    ),
                ),
                io.Int.Input("length_in_seconds", default=5, min=1, max=45),
                io.Int.Input("short_edge_length", default=720, min=0),
                io.Combo.Input("frame_rate", default=24, options=(12, 24, 25, 48, 50)),
                io.String.Input("keyframe_data", default="{}"),
            ],
            outputs=[io.Image.Output("guide_frames"), io.Float.Output("frame_rate")],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, images: io.Autogrow.Type, length_in_seconds: io.Int, short_edge_length: io.Int, frame_rate:io.Int, keyframe_data: io.String = "{}"):
        height = images['image_0'][0].shape[0]
        width = images['image_0'][0,0].shape[0]
        keyframe_list = json.loads(keyframe_data)['keyframes']
        frame_count = int(frame_rate*length_in_seconds)+1

        print(f"{keyframe_list}")

        scale_factor = 1
        if (height < width): 
            scale_factor = short_edge_length / height
        else:
            scale_factor = short_edge_length / width

        if (scale_factor ==0): scale_factor = 1

        height = round(height * scale_factor)
        width = round(width * scale_factor)


        output_images = torch.zeros((frame_count, height, width, 3))
        batch_lengths = []
        for index, img in enumerate(images.values()):
            if img is not None:
                batch_lengths.append(img.shape[0])
                resized_img = comfy.utils.common_upscale(img[:].movedim(-1,1), width, height, "bilinear", "center").movedim(1, -1)
                frame = round(keyframe_list[index]['x'] * frame_rate) 
                clip_length = resized_img.shape[0]

                if (clip_length <= frame_count - frame):
                    output_images[frame:frame+clip_length] = resized_img[:]
                else:
                    output_images[-clip_length:] = resized_img[:]
                    
        return io.NodeOutput(output_images, frame_rate, ui={"batch_lengths":batch_lengths})