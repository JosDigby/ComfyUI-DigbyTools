from comfy_api.latest import ComfyExtension, io
from .DigbyKeyframer import DigbyKeyframer
from .ltx_nodes import DigbyLTXVLatentPrep, DigbyLTXVAddGuidesFromBatch
from .krea2_nodes import DigbyKrea2Patch, DigbyRange
from .twostage_sampler import Digby2StageKSampler

class DigbyToolsExtension(ComfyExtension):
    async def get_node_list(self):
        return [
            DigbyKeyframer, 
            DigbyLTXVLatentPrep,
            DigbyLTXVAddGuidesFromBatch,
            DigbyKrea2Patch,
            DigbyRange,
            Digby2StageKSampler,
            ]
