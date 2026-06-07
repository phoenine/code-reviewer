from abc import abstractmethod
from typing import List, Dict, Optional

from biz.llm.types import NotGiven, NOT_GIVEN
from biz.utils.log import logger


class BaseClient:
    """Base class for chat models client."""

    def ping(self) -> bool:
        """Ping the model to check connectivity."""
        try:
            result = self.completions(
                messages=[{"role": "user", "content": 'Please only reply with "ok".'}]
            )
            return result and result.strip() == "ok"
        except Exception as e:
            logger.error("Failed to connect to LLM: %s", e)
            return False

    @abstractmethod
    def completions(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] | NotGiven = NOT_GIVEN,
    ) -> str:
        """Chat with the model."""
