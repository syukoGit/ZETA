from xai_sdk.chat import tool
from xai_sdk.tools import web_search, x_search

from ibkr.toolRegistry import get_tools


def get_grok_tool():
    return [
        x_search(enable_image_understanding=True, enable_video_understanding=True),
        web_search(enable_image_understanding=True),
        *[
            tool(
                name=k,
                description=v.description,
                parameters=v.args_model.model_json_schema()
            )
            for k, v in get_tools().items()
        ]
    ]