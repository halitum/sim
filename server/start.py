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

#
# if __name__ == "__main__":
#     asyncio.run(start())