from comfy_api.latest import ComfyExtension, io
from .DigbyKeyframer import DigbyKeyframer
from .ltx_nodes import DigbyLTXVLatentPrep, DigbyLTXVAddGuidesFromBatch

class DigbyToolsExtension(ComfyExtension):
    async def get_node_list(self):
        return [
            DigbyKeyframer, 
            DigbyLTXVLatentPrep,
            DigbyLTXVAddGuidesFromBatch,
            ]
