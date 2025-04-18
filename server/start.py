import asyncio
import json
from collections import defaultdict

from server.agents import ContextAgent
from configs import stimulus_inducer, MIN_SCORE_THRESHOLD, MAX_ITERATIONS, context
from server.agents import ChinaAgent, CanadaAgent, VietnamAgent, USAgent

from typing import AsyncIterable
from fastapi.responses import StreamingResponse

context_agent = ContextAgent(initial_context=context, model_name="deepseek-v3")

# 参与模拟的agent列表
agents = {
    "us": USAgent("deepseek-v3"),
    "china": ChinaAgent("deepseek-v3"),
    "canada": CanadaAgent("deepseek-v3"),
    "vietnam": VietnamAgent("deepseek-v3")
}

agent_memories = defaultdict(list)

async def agent_raise(initiator, content, current_context, iteration_num=0):
    async def process_agent_response(name, agent, content, agent_context):
        """处理单个agent的响应"""
        # 获取当前agent的历史记忆
        memory = agent_memories[name]
        memory_text = ""
        if memory:
            memory_text = "\n\n历史交互记录:\n" + "\n".join([
                f"迭代{i + 1}: {mem['initiator']}说: {mem['content'][:100]}{'...' if len(mem['content']) > 100 else ''}"
                for i, mem in enumerate(memory)
            ])

        # 向agent提供带有记忆的增强输入
        enhanced_content = f"{content}{memory_text}"
        response = await agent.start(enhanced_content, context=agent_context)
        return {
            "agent": name,
            "response": response
        }

    tasks = []
    for name, agent in agents.items():
        if name != initiator:
            # 为每个agent获取当前上下文的副本
            agent_context = current_context.copy()
            # 创建协程任务
            task = asyncio.create_task(process_agent_response(name, agent, content, agent_context))
            tasks.append(task)

    # 并行执行所有任务
    response_list = await asyncio.gather(*tasks)

    # 更新所有参与此轮的agent记忆
    for resp in response_list:
        agent_name = resp["agent"]
        agent_memories[agent_name].append({
            "initiator": initiator,
            "content": content,
            "iteration": iteration_num
        })

    return response_list


async def agent_announce(resp_list, iteration_num=None):
    """处理所有得分最高的agents"""
    # 打印所有agent的响应
    iter_text = f"迭代 {iteration_num}" if iteration_num is not None else "初始响应"
    print(f"\n{'=' * 20} {iter_text} {'=' * 20}")
    print(f"{'Agent':<10} {'Score':<8} {'Action':<20} {'Action Detail'}")
    print("-" * 70)

    # 按分数排序显示
    sorted_responses = sorted(
        resp_list,
        key=lambda x: int(x['response'].get('score', 0)),
        reverse=True
    )
    for resp in sorted_responses:
        agent = resp['agent']
        score = resp['response'].get('score', 0)
        action = resp['response'].get('action', 'N/A')
        detail = resp['response'].get('action_detail', 'N/A')
        if len(detail) > 40:
            detail = detail[:37] + "..."
        print(f"{agent:<10} {score:<8} {action:<20} {detail}")

    # 找出最高分数
    max_score = max(resp_list, key=lambda x: int(x['response'].get('score', 0)))['response'].get('score', 0)
    # 筛选所有达到最高分的agents
    highest_score_agents = [resp for resp in resp_list if int(resp['response'].get('score', 0)) == int(max_score)]

    print(f"\n执行所有最高分agent (分数: {max_score}):")
    for agent in highest_score_agents:
        agent_name = agent['agent']
        action = agent['response'].get('action', '')
        action_detail = agent['response'].get('action_detail', '')

        print(f"- {agent_name} 执行: {action}")

        # 记录高分agent的行动到所有agent的记忆中
        action_record = f"{agent_name}执行了: {action}，详情: {action_detail}"
        for name in agents.keys():
            if name != agent_name:  # 不需要记录自己的行动
                agent_memories[name].append({
                    "initiator": agent_name,
                    "content": action_record,
                    "iteration": iteration_num if iteration_num is not None else 0
                })

        # 使用context_agent更新上下文
        await context_agent.update_context(agent_name, action, action_detail)

    return highest_score_agents[0] if highest_score_agents else None, int(max_score)


async def start() -> StreamingResponse:

    async def iterator() -> AsyncIterable[str]:
        # 初始设置
        initiator = stimulus_inducer["name"]
        content = stimulus_inducer["content"]
        print(f"\n{'='*20} 初始刺激 {'='*20}")
        print(f"来源: {stimulus_inducer['name']}")
        print(f"内容: {stimulus_inducer['content']}")

        # 返回初始刺激信息
        data = {
            "type": "stimulus",
            "data": {
                "source": stimulus_inducer["name"],
                "content": stimulus_inducer["content"]
            },
            "iteration": 0
        }
        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        highest_score = 100
        iteration_count = 0

        # 合并初始响应和迭代循环
        while highest_score > MIN_SCORE_THRESHOLD and iteration_count <= MAX_ITERATIONS:
            # 获取当前上下文
            current_context = context_agent.get_context()

            # 返回迭代开始信息
            iter_text = "初始响应" if iteration_count == 0 else f"迭代 {iteration_count}"
            data = {
                "type": "iteration_start",
                "data": {
                    "iteration_text": iter_text,
                    "initiator": initiator,
                    "content": content
                },
                "iteration": iteration_count
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            # 获取响应
            resp_list = await agent_raise(
                initiator=initiator,
                content=content,
                current_context=current_context,
                iteration_num=iteration_count
            )

            # 处理高分agents并返回所有响应
            formatted_responses = []
            for resp in sorted(resp_list,
                              key=lambda x: int(x['response'].get('score', 0)),
                              reverse=True):
                agent = resp['agent']
                score = resp['response'].get('score', 0)
                action = resp['response'].get('action', 'N/A')
                detail = resp['response'].get('action_detail', 'N/A')
                print(f"{agent:<10} {score:<8} {action:<20} {detail[:37] + '...' if len(detail) > 40 else detail}")

                formatted_responses.append({
                    "agent": agent,
                    "score": score,
                    "action": action,
                    "action_detail": detail
                })

            data = {
                "type": "agent_responses",
                "data": {
                    "responses": formatted_responses
                },
                "iteration": iteration_count
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            # 处理高分agents
            highest_response, highest_score = await agent_announce(
                resp_list,
                None if iteration_count == 0 else iteration_count
            )

            # 返回最高分agent执行结果
            highest_agents_data = []
            if highest_response:
                highest_agents_data.append({
                    "agent": highest_response['agent'],
                    "action": highest_response['response'].get('action', ''),
                    "action_detail": highest_response['response'].get('action_detail', '')
                })

            data = {
                "type": "agent_announce",
                "data": {
                    "score": highest_score,
                    "agents": highest_agents_data
                },
                "iteration": iteration_count
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            # 处理经济数据
            print("\n当前经济数据:")
            current_context = context_agent.get_context()
            economic_data = {}
            for country, data in current_context.items():
                print(f"{country}: GDP={data['GDP']}, 失业率={data['失业率']}, 通胀率={data['通胀率']}")
                economic_data[country] = data

            data = {
                "type": "economic_data",
                "data": economic_data,
                "iteration": iteration_count
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            # 为下一次迭代更新参数
            if highest_response:
                initiator = highest_response['agent']
                content = highest_response['response'].get('action_detail', '')

            iteration_count += 1

        # 迭代结束，返回总结信息
        termination_reason = '达到最大迭代次数' if iteration_count > MAX_ITERATIONS else '低于最小分数阈值'
        print(f"\n{'=' * 20} 迭代结束 {'=' * 20}")
        print(f"总迭代次数: {iteration_count - 1}")
        print(f"终止原因: {termination_reason}")

        data = {
            "type": "iteration_end",
            "data": {
                "total_iterations": iteration_count - 1,
                "termination_reason": termination_reason
            },
            "iteration": iteration_count - 1
        }
        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        iterator(),
        media_type="text/event-stream",
    )

async def fake_start():
    async def iterator():
        data_list = [
            {"type": "stimulus", "data": {"source": "us", "content": "美国总统特朗普签署行政令，宣布：对所有贸易伙伴加征10%的关税。对与美国贸易逆差最大的国家和地区征收更高的“对等关税”"}, "iteration": 0},
            {"type": "iteration_start", "data": {"iteration_text": "初始响应", "initiator": "us", "content": "美国总统特朗普签署行政令，宣布：对所有贸易伙伴加征10%的关税。对与美国贸易逆差最大的国家和地区征收更高的“对等关税”"}, "iteration": 0},
            {"type": "agent_responses", "data": {"responses": [{"agent": "china", "score": "85", "action": "实施报复性关税", "action_detail": "针对美国对中国高科技产品加征20%关税的行为，中国将对来自美国的农产品（如大豆、猪肉）和能源产品（如液化天然气）加征25%的关税。同时，考虑限制稀土等关键原材料对美国的出口，以保护国家安全和产业链稳定。"}, {"agent": "canada", "score": "75", "action": "发起/响应谈判", "action_detail": "鉴于美国对所有贸易伙伴加征10%的关税，加拿大应主动提议与美国进行双边贸易谈判。谈判重点应包括：1) 讨论加拿大特定行业的豁免清单，特别是能源和农产品；2) 确保USMCA框架下的贸易便利化措施不受影响；3) 探讨在清洁能源和关键矿产领域的合作机会。同时，加拿大应与中国保持沟通，寻求在农产品出口方面的潜在合作机会，以多元化贸易伙伴。"}, {"agent": "vietnam", "score": "30", "action": "观望", "action_detail": "越南将保持中立观望态度，暂不采取任何报复性关税措施。我们将密切关注中美贸易摩擦的发展，评估其对越南出口和外资企业的影响。同时，越南将继续加强与东盟成员国的合作，推动区域经济一体化，以降低对单一市场的依赖。"}]}, "iteration": 0},
            {"type": "agent_announce", "data": {"score": 85, "agents": [{"agent": "china", "action": "实施报复性关税", "action_detail": "针对美国对中国高科技产品加征20%关税的行为，中国将对来自美国的农产品（如大豆、猪肉）和能源产品（如液化天然气）加征25%的关税。同时，考虑限制稀土等关键原材料对美国的出口，以保护国家安全和产业链稳定。"}]}, "iteration": 0},
            {"type": "economic_data", "data": {"us": {"GDP": 20.0, "失业率": 5.8, "通胀率": 3.5}, "china": {"GDP": 17.8, "失业率": 5.8, "通胀率": 2.4}, "canada": {"GDP": 2.1, "失业率": 5.5, "通胀率": 4.2}, "vietnam": {"GDP": 0.4, "失业率": 2.3, "通胀率": 3.8}}, "iteration": 0},
            {"type": "iteration_start", "data": {"iteration_text": "迭代 1", "initiator": "china", "content": "针对美国对中国高科技产品加征20%关税的行为，中国将对来自美国的农产品（如大豆、猪肉）和能源产品（如液化天然气）加征25%的关税。同时，考虑限制稀土等关键原材料对美国的出口，以保护国家安全和产业链稳定。"}, "iteration": 1},
            {"type": "agent_responses", "data": {"responses": [{"agent": "us", "score": "75", "action": "发起/响应谈判", "action_detail": "鉴于中国对美国农产品和能源产品加征25%关税的报复性措施，美国应主动提议与中国进行双边贸易谈判。谈判重点应包括：1) 讨论降低或取消部分高科技产品关税的可能性；2) 探讨稀土等关键原材料的供应链稳定性；3) 寻求在农产品和能源贸易上的平衡点。同时，美国应强调保持半导体等关键技术领先地位的重要性，并考虑在谈判中提出部分农产品关税的让步以换取中国在稀土出口上的保证。"}, {"agent": "canada", "score": 70, "action": "寻求对冲性合作 (新贸易协定)", "action_detail": "鉴于中美贸易紧张局势升级，加拿大应积极寻求与亚太地区其他国家（如越南）建立新的贸易协定，以多元化贸易伙伴，减少对单一市场的依赖。同时，加拿大应继续维护USMCA框架，确保与美国的贸易关系稳定。此外，加拿大可以提议与中国进行双边贸易谈判，讨论降低或取消相互加征的关税，特别是在农产品和高科技产品领域。"}, {"agent": "vietnam", "score": "30", "action": "观望", "action_detail": "越南政府将保持中立立场，不直接参与中美贸易争端。我们将密切关注事态发展，评估对越南出口和外资的影响，同时加强与东盟成员国的协调，确保区域供应链稳定。"}]}, "iteration": 1},
            {"type": "agent_announce", "data": {"score": 75, "agents": [{"agent": "us", "action": "发起/响应谈判", "action_detail": "鉴于中国对美国农产品和能源产品加征25%关税的报复性措施，美国应主动提议与中国进行双边贸易谈判。谈判重点应包括：1) 讨论降低或取消部分高科技产品关税的可能性；2) 探讨稀土等关键原材料的供应链稳定性；3) 寻求在农产品和能源贸易上的平衡点。同时，美国应强调保持半导体等关键技术领先地位的重要性，并考虑在谈判中提出部分农产品关税的让步以换取中国在稀土出口上的保证。"}]}, "iteration": 1},
            {"type": "economic_data", "data": {"us": {"GDP": 20.0, "失业率": 5.8, "通胀率": 3.6}, "china": {"GDP": 17.8, "失业率": 5.8, "通胀率": 2.4}, "canada": {"GDP": 2.1, "失业率": 5.5, "通胀率": 4.2}, "vietnam": {"GDP": 0.4, "失业率": 2.3, "通胀率": 3.8}}, "iteration": 1},
            {"type": "iteration_end", "data": {"total_iterations": 1, "termination_reason": "达到最大迭代次数"}, "iteration": 1}
        ]

        for data in data_list:
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        iterator(),
        media_type="text/event-stream",
    )
    

#
# if __name__ == "__main__":
#     asyncio.run(start())