from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from mem0 import MemoryClient
from utils import get_ChatOpenAI, extract_pure_json
from configs import llm_model, embed_model, mem0_ai_api


class BaseAgent:
    def __init__(self, agent_name: str, model_name: str, system_prompt: str):
        # 原有初始化代码保持不变
        self.name = agent_name
        self.prompt_template = system_prompt  # 保存原始模板
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}")
        ])
        self.model = get_ChatOpenAI(model_name)
        self.chain = self.prompt | self.model | StrOutputParser()

    def _retrieve_context(self, query: str) -> str:
        """检索相关上下文（需要子类实现）"""
        raise NotImplementedError("子类必须实现_retrieve_context方法")

    async def start(self, input: str, context=None) -> str:
        """处理输入并返回JSON响应，可选择传入最新上下文"""
        if context:
            # 使用最新上下文构建当前状态信息
            current_state = self._format_context(context)
            # 在输入中添加上下文信息
            enhanced_input = f"当前状态：\n{current_state}\n\n{input}"
        else:
            enhanced_input = input

        response = await self.chain.ainvoke({"input": enhanced_input})
        return extract_pure_json(response)

    def _format_context(self, context):
        """格式化上下文数据，可由子类重写以自定义格式"""
        lines = []
        for country, data in context.items():
            country_info = [f"{country}:"]
            for key, value in data.items():
                country_info.append(f"  {key}: {value}")
            lines.append(" ".join(country_info))
        return "\n".join(lines)