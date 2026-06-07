import os

from dotenv import load_dotenv

from biz.llm.factory import Factory
from biz.utils.log import logger

# Path to env file
ENV_FILE_PATH = "conf/.env"
load_dotenv(ENV_FILE_PATH)


REQUIRED_ENV_VARS = [
    "LLM_PROVIDER",
]

# Allowed LLM providers
LLM_PROVIDERS = {"anthropic", "zhipuai", "openai", "deepseek", "ollama", "qwen"}

# Required keys per provider
LLM_REQUIRED_KEYS = {
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_API_BASE_URL", "ANTHROPIC_API_MODEL"],
    "zhipuai": ["ZHIPUAI_API_KEY", "ZHIPUAI_API_MODEL"],
    "openai": ["OPENAI_API_KEY", "OPENAI_API_MODEL"],
    "deepseek": ["DEEPSEEK_API_KEY", "DEEPSEEK_API_MODEL"],
    "ollama": ["OLLAMA_API_BASE_URL", "OLLAMA_API_MODEL"],
    "qwen": ["QWEN_API_KEY", "QWEN_API_MODEL"],
}


def check_env_vars():
    """Check environment variables"""
    missing_vars = [var for var in REQUIRED_ENV_VARS if var not in os.environ]
    if missing_vars:
        logger.warning(f"Missing environment variables: {', '.join(missing_vars)}")
    else:
        logger.info("All required environment variables are set.")


def check_llm_provider() -> bool:
    """Check LLM provider configuration"""
    llm_provider = os.getenv("LLM_PROVIDER")

    if not llm_provider:
        logger.error("LLM_PROVIDER is not set!")
        return False

    if llm_provider not in LLM_PROVIDERS:
        logger.error(f"Invalid LLM_PROVIDER value, must be one of {LLM_PROVIDERS}.")
        return False

    required_keys = LLM_REQUIRED_KEYS.get(llm_provider, [])
    missing_keys = [key for key in required_keys if not os.getenv(key)]

    if missing_keys:
        logger.error(
            f"Current LLM provider is {llm_provider}, but missing required environment variables: {', '.join(missing_keys)}"
        )
        return False
    else:
        logger.info(f"LLM provider {llm_provider} configuration is set.")
        return True


def check_llm_connectivity():
    client = Factory().getClient()
    logger.info(f"Checking LLM provider connectivity...")
    if client.ping():
        logger.info("LLM connected successfully.")
    else:
        logger.error("LLM connection may have issues, please check the configuration.")


def check_config():
    """Main check entry point"""
    logger.info("Starting configuration check...")
    check_env_vars()
    provider_ok = check_llm_provider()
    if not provider_ok:
        logger.error("Skipping LLM connectivity check: LLM_PROVIDER or its configuration is invalid.")
        return
    check_llm_connectivity()
    logger.info("Configuration check completed.")
