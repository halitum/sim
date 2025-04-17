import json
import json_repair

from langchain_openai import ChatOpenAI
from typing import Any
from configs.model import llm_model

def extract_pure_json(info: str):
    """gpt返回的字符串可能不带前缀，也可能带前缀"""
    try:
        repaired = json_repair.repair_json(info)
        return json.loads(repaired)
    except Exception as e:
            return {}

def get_ChatOpenAI(
        model_name: str,
        temperature: float = 0.6,
        max_tokens: int = 1024*8,
        streaming: bool = False,
        verbose: bool = True,
        **kwargs: Any,
) -> ChatOpenAI:
    config = llm_model.get(model_name, {})
    if not config:
        raise ValueError(f"Model {model_name} not found")
    model_name = config.get("model_name")
    model = ChatOpenAI(
        streaming=streaming,
        verbose=verbose,
        openai_api_key=config.get("api_key", ""),
        openai_api_base=config.get("api_base_url", ""),
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs
    )
    return model


if __name__ == "__main__":
    print(get_ChatOpenAI("deepseek-v3"))