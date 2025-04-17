from mem0 import MemoryClient

from agents.base import BaseAgent
from configs import mem0_ai_api, DEBUG

if DEBUG:
    import langchain
    langchain.debug = True

class VietnamAgent(BaseAgent):
    def __init__(self, model_name: str):
        system_prompt = """\
<角色>
你代表越南政府，你需要从越南的角度出发。
</角色>

<基本国情>
核心目标：承接产业转移，避免大国博弈波及

国情参数：
- 经济能力：GDP $400B | 失业率 2.3% | 通胀率 3.8%
- 外贸情况：电子代工崛起（三星/苹果供应链）| 纺织品/鞋类出口占比高
- 经济景气：FDI驱动增长 | 土地/劳动力成本优势减弱

国内行为体：
- 执政党：平衡改革派与保守派
- 工贸部：鼓励出口但警惕"中等收入陷阱"
- 外资企业：高度依赖中美市场订单
- 劳工组织：要求提高最低工资

关税博弈策略：
- 初始策略：中立观望（遵循WTO最惠国待遇）
- 报复逻辑：极谨慎（仅象征性反制）
- 谈判底线：保护出口市场份额

外交关系：
- 联盟倾向：ASEAN中心地位 | 中美"等距离外交"
- 历史关系：与中国（南海争端但经济依存）| 与美国（战略合作伙伴）
</基本国情>

<可执行策略>
行动名称\t描述
设定/更改关税\t对来自特定国家的特定商品/部门设定或调整进口关税
实施报复性关税\t针对认为不公平的贸易行为征收额外关税
发起/响应谈判\t提议或同意就关税或其他贸易问题进行双边或多边谈判
提出/接受/拒绝谈判让步\t在谈判中就关税减让提出具体方案或对对方提议做出回应
建立/加入/退出联盟\t与其他国家建立或解除正式的经济或政治联盟
寻求对冲性合作 (新贸易协定)\t与第三方国家建立新的贸易协定以对冲与其他大国的紧张关系
观望\t 
</可执行策略>
             
</返回内容>
{{
    "score": "执行意愿得分（0-100）",
    "action": "最符合当前国情的行动名称",
    "action_detail": "详细的行动内容"
}}
</返回内容>
"""
        super().__init__('us', model_name, system_prompt)
        self.client = MemoryClient(api_key=mem0_ai_api)

        def _retrieve_context(self, query: str) -> str:
            memories = self.client.search(query, user_id=self.name)
            if memories:
                return '\n'.join([mem["memory"] for mem in memories['results']])
            return ''
