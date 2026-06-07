import os
from typing import Dict, List, Optional

from openai import OpenAI

from biz.llm.client.base import BaseClient
from biz.llm.types import NotGiven, NOT_GIVEN
from biz.utils.log import logger


class DeepSeekClient(BaseClient):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = os.getenv("DEEPSEEK_API_BASE_URL", "https://api.deepseek.com")
        if not self.api_key:
            raise ValueError(
                "API key is required. Please provide it or set it in the environment variables."
            )

        self.client = OpenAI(
            api_key=self.api_key, base_url=self.base_url
        )  # DeepSeek supports OpenAI API SDK
        self.default_model = os.getenv("DEEPSEEK_API_MODEL", "deepseek-chat")

    def completions(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] | NotGiven = NOT_GIVEN,
    ) -> str:
        try:
            model = model or self.default_model
            logger.debug(
                f"Sending request to DeepSeek API. Model: {model}, Messages: {messages}"
            )

            completion = self.client.chat.completions.create(
                model=model, messages=messages
            )

            if not completion or not completion.choices:
                logger.error("Empty response from DeepSeek API")
                return "Empty response from AI service, please retry later."

            return completion.choices[0].message.content

        except Exception as e:
            logger.error(f"DeepSeek API error: {str(e)}")
            # Check for authentication error
            if "401" in str(e):
                return "DeepSeek API authentication failed, please check if the API key is correct."
            elif "404" in str(e):
                return "DeepSeek API endpoint not found, please check if the API URL is correct."
            else:
                return f"Error calling DeepSeek API: {str(e)}"
