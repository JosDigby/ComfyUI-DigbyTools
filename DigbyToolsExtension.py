from comfy_api.latest import ComfyExtension, io
from .DigbyKeyframer import DigbyKeyframer

class DigbyToolsExtension(ComfyExtension):
    async def get_node_list(self):
        return [DigbyKeyframer]
