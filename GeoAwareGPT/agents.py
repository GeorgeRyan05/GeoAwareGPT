import os, sys
import json
from json import JSONDecodeError
import jsonschema
from PIL import Image
from typing import Dict, Tuple, List, Any, Sequence, cast
import re

from litellm import acompletion
from dotenv import load_dotenv

from .schema import GeminiModelConfig, AzureModelConfig, ChatBuilder, BaseTool, BaseState
from .ToolHandler import ToolHandler
from GeoAwareGPT.schema import ToolImageOutput, ToolCustomOutput

load_dotenv()


class Model:
    def __init__(self) -> None:
        pass

    async def generate(self, messages: ChatBuilder):
        "This method should be implemented by all child classes for prompt generation"
        raise NotImplementedError(
            "This method is meant to be implemented by child classes"
        )


class AzureModel(Model):
    def __init__(self, model_config: AzureModelConfig = AzureModelConfig()):
        self.model_config = model_config
        self.input_params = model_config.__dict__()
        self.check_api_key()

    def check_api_key(self):
        """Check if the API key is available in the environment."""
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        api_base = os.environ.get("AZURE_OPENAI_ENDPOINT")
        api_version = os.environ.get("AZURE_API_VERSION")
        self.input_params['api_key'] = api_key
        self.input_params["api_base"] = api_base
        self.input_params['api_version'] = api_version
        if not api_key:
            print(
                "Please set the OPENAI_API_KEY environment variable with the API key."
            )
            sys.exit(1)

    async def generate(
        self,
        messages: ChatBuilder,
    ):
        """Generate a response for the given messages."""
        return await acompletion(
            messages=messages.chat,
            **self.input_params,
        )


class GeminiModel(Model):
    def __init__(self, model_config: GeminiModelConfig = GeminiModelConfig()):
        self.model_config = model_config
        self.check_api_key()
        self.input_params = model_config.__dict__()

    def check_api_key(self):
        """Check if the API key is available in the environment."""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print(
                "Please set the GEMINI_API_KEY environment variable with the API key."
            )
            sys.exit(1)

    async def generate(
        self,
        messages: ChatBuilder,
    ):
        """Generate a response for the given messages."""
        return await acompletion(
            messages=messages.chat,
            **self.input_params,
        )


class Agent:
    def __init__(
        self,
        states: List[BaseState],
        model: Model | None = None,
    ) -> None:
        self.model = model or GeminiModel()
        self.messages = ChatBuilder()
        self.states: list[BaseState] = states
        self.tool_handler = ToolHandler(tools=self.states[0].tools)
        self.images: List[Image.Image] = []

    def set_system_prompt(self, prompt: str):
        self.messages.system_message(prompt + "\n" + str(self.states[0]))

    def add_user_message(self, message: str):
        if self.images:
            message = f"""{message}
The user has uploaded the following images: {', '.join((f'image_{i}' for i in range(len(self.images))))}
An image can be inserted as an argument directly - "args": {{"<arg_name>": "$image_1$"}}"""
            self.messages.user_message(message)
        else:
            self.messages.user_message(message)

    def add_assistant_message(self, message: str):
        self.messages.assistant_message(message)
    
    def add_input_image(self, image: Image.Image):
        self.images.append(image)

    async def get_assistant_response(self):
        # print(self.messages.chat)
        response = await self.model.generate(self.messages)
        if response and response.choices: # type: ignore
            answer: str = response.choices[0].message.content # type: ignore
        else:
            raise RuntimeError("No response from the model")
        self.add_assistant_message(answer)
        return answer

    def add_tool(self, tool: BaseTool|Sequence[BaseTool]):
        self.tool_handler.add_tool(tool)

    def extract_info(self, response: str) -> Tuple[List[Dict[str, str|Dict[str, Any]]], Dict[str, str]]:
        """Deal with images and potentially other placeholders
        
        Returns:
            tools (List) - tool_calls after json.loads  
            info (Dict) - remaining response
        """

        response = re.sub(r'"\$image_(?P<num>[0-9]+)\$"', '"<image_\g<num>>"', response) # type: ignore
        try:
            info: Dict = json.loads(response)
            tools: List[Dict[str, str|Dict[str, Any]]]
            tools = info.pop('tool_calls')
        except JSONDecodeError as e:
            nl = '\n'
            raise ValueError('Invalid JSON') from e
        for tool in tools:
            args: Dict[str, Any] = cast(Dict[str, Any], tool['args'])
            for arg, val in args.items():
                if isinstance(val, str) and (img := re.match(r'<image_(?P<num>[0-9]+)>', val)):
                    args[arg] = self.images[int(img.group('num'))]
        return tools, info

    async def agent_loop(self) -> Tuple[Dict[str, ToolImageOutput], Dict[str, str], bool, str, Dict[str, ToolCustomOutput]]:
        print(self.messages.chat)
        response: str|Dict[str, Any] = await self.get_assistant_response()
        tool_calls, response = self.extract_info(response)
        if not tool_calls:
            return {}, {}, False, response["audio"], {}
        tool_results = await self.tool_handler.handle_tool(tool_calls)
        AUA = tool_results.get("AUA", False)
        tool_results_display: Dict[str, ToolImageOutput] = {}
        tool_results_custom: Dict[str, ToolCustomOutput] = {}
        tool_results_text = {}
        for key in tool_results:
            if isinstance(out := tool_results[key], ToolImageOutput):
                self.add_input_image(out.image)
                tool_results_display[key] = out
                tool_results_text[key] = "Image shown to user"
            elif isinstance(out, ToolCustomOutput):
                tool_results_custom[key] = out
                tool_results_text[key] = out.output
            else:
                tool_results_text[key] = str(tool_results[key])
        self.add_user_message(str({"tool_results": json.dumps(tool_results_text)}))
        return tool_results_display, tool_results_text, AUA, response["audio"], tool_results_custom
