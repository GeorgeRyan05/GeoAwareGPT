from typing import List, Dict, Sequence
from asyncio import iscoroutinefunction
import warnings
import re

from .schema import BaseTool, ToolImageOutput

DEBUG = False
class ToolHandler:
    def __init__(self, tools: List[BaseTool]):
        self.tools: Dict[str, BaseTool] = {tool.name: tool for tool in tools}
    
    def add_tool(self, tool: BaseTool|Sequence[BaseTool]):
        def validate(tool: BaseTool):
            if not isinstance(tool, BaseTool):
                raise TypeError('Tool should inherit from base tool')
            if tool.name in self.tools:
                warnings.warn('Tool already exists. Overwriting.', category=RuntimeWarning)
            return tool
        if isinstance(tool, BaseTool):
            self.tools[tool.name] = validate(tool)
        else:
            self.tools.update({_tool.name: validate(_tool) for _tool in tool})

    async def call_tool(self, tool_name, args):
        return self.tools[tool_name].run(**args) if not iscoroutinefunction(self.tools[tool_name].run) else await self.tools[tool_name].run(**args)

    async def handle_tool(self, llm_output: List):
        tool_results = {}
        for i in range(len(llm_output)):
            tool_name = llm_output[i]["name"]
            args = llm_output[i]["args"]
            if self.tools[tool_name].tool_type == "AUA":
                tool_results["AUA"] = True
            try:
                tool_output = await self.call_tool(tool_name, args)
            except Exception as e:
                tool_output = "An error occurred while running the tool."
                if DEBUG:
                    print(llm_output)
                    raise e

            # if isinstance(tool_output, ToolImageOutput):
                
            #     # tool_results['image'].append(tool_output)
            #     ...
            tool_results[tool_name] = tool_output
        return tool_results
# class ToolImageOutput:
#     """A class representing the output of a tool with an image.

#     Attributes:
#         image_url (str): The URL of the image output.
#         args (dict): The arguments for the tool.

#     Methods:
#         __str__(): Returns a string representation of the tool image output.
#     """

#     def __init__(self):
#         self.image = None

#     def __str__(self):
#         """Returns a string representation of the tool image output."""
#         return f"Image URL: {self.image}"