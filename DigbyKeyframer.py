from __future__ import annotations
from comfy_api.latest import io
import torch

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
                io.Int.Input("frame_count", default=121, min=1),
                io.Int.Input("short_edge_length", default=720, min=1),
            ],
            outputs=[io.Image.Output("guide_frames")],
        )

    @classmethod
    def execute(cls, images: io.Autogrow.Type):
        # images is a dict: {"image_0": tensor, "image_1": tensor, ...}
        tensors = [v for v in images.values() if v is not None]
        return io.NodeOutput(torch.cat(tensors, dim=0))