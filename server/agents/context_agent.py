from typing import Dict, List
from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from server.utils import get_ChatOpenAI, extract_pure_json


class ContextAgent:
    def __init__(self, initial_context: Dict, model_name: str = "gpt-3.5-turbo"):
        self.name = "context_agent"
        self._context = initial_context.copy()  # 存储上下文数据
        self.system_prompt = """你是一个世界经济影响分析专家。
根据给定的行动和当前经济数据，分析并更新各国经济指标。
国家行动会对本国和其他国家产生影响。请基于经济学原理进行合理的数据调整。

以下行动可能对数据产生的影响参考（非强制）：
- 设定/更改关税: 对本国可能导致通胀率上升(+0.1~0.3)，对目标国GDP下降(-0.1~0.3)
- 实施报复性关税: 对本国可能导致GDP小幅下降(-0.1)、失业率上升(+0.1~0.3)
- 建立/加入贸易联盟: 对本国可能提高GDP(+0.1~0.3)，降低失业率(-0.1)
- 退出贸易联盟: 短期内可能降低GDP(-0.1~0.2)
- 设置贸易限制: 对本国可能提高失业率(+0.1)，对目标国降低GDP(-0.1~0.2)
- 提供补贴: 可能提高通胀率(+0.1)，降低失业率(-0.1)

评估当前行动影响并返回更新后的完整经济数据，格式为JSON。

例如:
{{
  "china": {{"GDP": 6.8, "失业率": 3.9, "通胀率": 2.1}},
  "us": {{"GDP": 3.5, "失业率": 4.2, "通胀率": 2.8}}
}}
"""
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("human", "{input}")
        ])
        self.model = get_ChatOpenAI(model_name)
        self.chain = self.prompt | self.model | StrOutputParser()

    def get_context(self) -> Dict:
        """获取当前上下文数据"""
        return self._context.copy()

    @staticmethod
    def _format_context(context: Dict) -> str:
        """格式化上下文数据为易读形式"""
        lines = []
        for country, data in context.items():
            lines.append(f"{country}: GDP={data['GDP']}, 失业率={data['失业率']}, 通胀率={data['通胀率']}")
        return "\n".join(lines)

    @staticmethod
    def _validate_context_format(context: Dict, original_context: Dict) -> bool:
        """验证context格式是否有效"""
        if not isinstance(context, dict):
            return False

        # 检查是否包含所有原始国家
        for country in original_context:
            if country not in context:
                return False

            # 检查每个国家是否包含所有必要指标
            country_data = context[country]
            if not all(key in country_data for key in ['GDP', '失业率', '通胀率']):
                return False

        return True

    def extract_target_countries(action_detail: str) -> List[str]:
        """从行动详情中提取目标国家"""
        target_countries = []
        countries = ["us", "china", "canada", "vietnam"]
        for country in countries:
            if country.lower() in action_detail.lower():
                target_countries.append(country)
        return target_countries

    async def update_context(self, action_agent: str, action: str, action_detail: str) -> None:
        """根据agent的行动更新经济上下文数据"""
        # 构建输入信息
        input_text = f"""
行动agent: {action_agent}
行动: {action}
行动详情: {action_detail}

当前经济数据:
{self._format_context(self._context)}

请分析此行动对各国经济指标的影响，并返回更新后的完整经济数据。
"""
        # 获取LLM的响应
        response = await self.chain.ainvoke({"input": input_text})
        # 解析JSON格式的响应
        updated_context = extract_pure_json(response)

        # 验证返回的数据格式
        if not self._validate_context_format(updated_context, self._context):
            print("警告: 上下文格式无效，保持原始数据")
            return

        # 更新内部状态
        self._context = updated_context