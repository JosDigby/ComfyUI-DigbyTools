from .DigbyToolsExtension import DigbyToolsExtension

WEB_DIRECTORY = "./js"

async def comfy_entrypoint():
    return DigbyToolsExtension()