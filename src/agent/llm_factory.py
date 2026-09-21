import os
from langchain_openai import ChatOpenAI
from src.config import LLMConfig


def create_llm(config: LLMConfig) -> ChatOpenAI:
    """创建并配置 LangChain ChatOpenAI 实例。

    支持 OpenAI 兼容 API、火山方舟、Ollama、vLLM 等本地或云端端点。
    """
    base_url = config.base_url.rstrip("/")
    # 如果用户配置的 URL 带有 /chat/completions，截断为 base_url
    if base_url.endswith("/chat/completions"):
        base_url = base_url[:-len("/chat/completions")]

    api_key = config.api_key or os.environ.get("OPENAI_API_KEY", "EMPTY")

    llm = ChatOpenAI(
        model=config.model,
        base_url=base_url,
        api_key=api_key,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=60,
        max_retries=2
    )
    return llm
