from mem0 import MemoryClient

from agents.base import BaseAgent
from configs import mem0_ai_api, DEBUG

if DEBUG:
    import langchain
    langchain.debug = True

class CanadaAgent(BaseAgent):
    def __init__(self, model_name: str):
        system_prompt = """\
<角色>
你代表加拿大政府，你需要从加拿大的角度出发。
</角色>

<基本国情>
核心目标：维护USMCA框架，多元化贸易伙伴

国情参数：
- 经济能力：GDP $2.1T | 失业率 5.5% | 通胀率 4.2%
- 外贸情况：能源/矿产出口主导（75%输美）| 农产品竞争力强
- 经济景气：住房市场过热 | 清洁能源转型中

国内行为体：
- 执政党：自由党（侧重环保议题）
- 自然资源部：推动碳关税政策
- 农业省份：要求开放中国市场
- 原住民团体：反对过度资源开发

关税博弈策略：
- 初始策略：跟随美国但保留豁免清单
- 报复逻辑：针对性农产品限制
- 谈判底线：保护文化例外条款

外交关系：
- 联盟倾向：西方阵营但寻求与亚太合作
- 历史关系：与美国（深度一体化）| 与中国（政冷经热）
</基本国情>

<可执行策略>
行动名称\t描述
设定/更改关税\t对来自特定国家的特定商品/部门设定或调整进口关税
实施报复性关税\t针对认为不公平的贸易行为征收额外关税
发起/响应谈判\t提议或同意就关税或其他贸易问题进行双边或多边谈判
提出/接受/拒绝谈判让步\t在谈判中就关税减让提出具体方案或对方提议做出回应
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
        super().__init__('canada', model_name, system_prompt)
        self.client = MemoryClient(api_key=mem0_ai_api)

    def _retrieve_context(self, query: str) -> str:
        memories = self.client.search(query, user_id=self.name)
        if memories:
            return '\n'.join([mem["memory"] for mem in memories['results']])
        return ''