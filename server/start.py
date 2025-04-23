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
    # "canada": CanadaAgent("deepseek-v3"),
    # "vietnam": VietnamAgent("deepseek-v3")
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
            {"type": "iteration_start", "data": {"iteration_text": "初始响应", "initiator": "us", "content": "美国总统特朗普签署行政令，宣布：对所有贸易伙伴加征10%的关税。对与美国贸易逆差最大的国家和地区征收更高的\"对等关税\""}, "iteration": 0},
            {"type": "agent_announce", "data": {"agents": [{"agent": "china", "action": "实施报复性关税", "action_detail": "针对美国加征关税的行为，中国将采取非对称打击策略，重点对美国农产品（如大豆、玉米）和关键工业原材料（如稀土）加征报复性关税。同时，中国将利用其在稀土等关键原材料上的优势地位，限制对美国的出口，以保护国内产业链安全和推动人民币国际化。此举旨在向美国施压，促使其重新考虑贸易政策，并在谈判中争取更有利的条件。"}]}, "iteration": 0},
            {"type": "agent_announce", "data": {"agents": [{"agent": "us_corp", "action": "扩大本土产能", "action_detail": "在关税保护政策推动下，美国车企计划扩大本土生产线，同时加快关键零部件国产化进程，以提高整体供应链稳定性。"}]}, "iteration": 0},
            {"type": "agent_announce", "data": {"agents": [{"agent": "chine_corp", "action": "寻求多元化出口", "action_detail": "面对美国市场的关税壁垒，中国车企积极开拓‘一带一路’沿线国家市场，寻求多元化出口渠道，同时加快新能源汽车研发以增强国际市场竞争力。"}]}, "iteration": 0},
            {
                "type": "economic_data",
                "data": {
                "china": {
                    "import_value_billion_usd": 75,
                    "import_change_pct": -7.58,
                    "export_value_billion_usd": 370,
                    "export_change_pct": -11.51,
                    "market_share_pct": 31.5,
                    "market_share_change_pct": -5.48,
                    "annual_production_ten_thousand_vehicles": 900,
                    "annual_production_change_pct": -3.23,
                    "demand_ten_thousand_vehicles": 770,
                    "demand_change_pct": -4.94,
                    "production_cost_ten_thousand_usd": 2.3,
                    "production_cost_change_pct": -4.17
                },
                "us": {
                    "import_value_billion_usd": 120,
                    "import_change_pct": -11.11,
                    "export_value_billion_usd": 65,
                    "export_change_pct": 8.33,
                    "market_share_pct": 10.5,
                    "market_share_change_pct": 12.90,
                    "annual_production_ten_thousand_vehicles": 215,
                    "annual_production_change_pct": 7.50,
                    "demand_ten_thousand_vehicles": 140,
                    "demand_change_pct": -4.76,
                    "production_cost_ten_thousand_usd": 3.15,
                    "production_cost_change_pct": 5.00
                }
                },
                "iteration": 0
            },
                {
                    "type": "iteration_start",
                    "data": {
                        "iteration_text": "迭代 1",
                        "initiator": "us",
                        "content": "美国宣布对中国新能源汽车及其电池零部件加征20%关税，并启动对中国补贴政策的调查，理由是“维护美国产业公平竞争”。"
                    },
                    "iteration": 1
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "us",
                                "action": "加征关税并调查补贴",
                                "action_detail": "美国贸易代表办公室（USTR）将在90天内完成对中国新能源汽车补贴的全面调查，同时对相关产品征收20%关税，以限制中国新能源汽车在美市场份额。"
                            }
                        ]
                    },
                    "iteration": 1
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "china",
                                "action": "对美关键原材料加征关税",
                                "action_detail": "中国将对美国出口的锂、镍等动力电池关键原材料加征15%的报复性关税，并宣布对美国进口车加征5%附加税。"
                            }
                        ]
                    },
                    "iteration": 1
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "us_corp",
                                "action": "寻求供应链多元化",
                                "action_detail": "主要美国车企与墨西哥和加拿大电池厂商签署长期采购合约，同时评估在东南亚设立零部件工厂的可行性。"
                            }
                        ]
                    },
                    "iteration": 1
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "chine_corp",
                                "action": "加速技术升级",
                                "action_detail": "中国车企宣布增加30%的研发预算，用于固态电池与智能驾驶系统，以提升产品附加值并降低对美出口依赖。"
                            }
                        ]
                    },
                    "iteration": 1
                },
                {
                    "type": "economic_data",
                    "data": {
                        "china": {
                            "import_value_billion_usd": 65.63,
                            "import_change_pct": -12.50,
                            "export_value_billion_usd": 314.50,
                            "export_change_pct": -15.00,
                            "market_share_pct": 28.98,
                            "market_share_change_pct": -8.00,
                            "annual_production_ten_thousand_vehicles": 855,
                            "annual_production_change_pct": -5.00,
                            "demand_ten_thousand_vehicles": 723.80,
                            "demand_change_pct": -6.00,
                            "production_cost_ten_thousand_usd": 2.37,
                            "production_cost_change_pct": 3.00
                        },
                        "us": {
                            "import_value_billion_usd": 102.00,
                            "import_change_pct": -15.00,
                            "export_value_billion_usd": 71.50,
                            "export_change_pct": 10.00,
                            "market_share_pct": 12.08,
                            "market_share_change_pct": 15.00,
                            "annual_production_ten_thousand_vehicles": 236.50,
                            "annual_production_change_pct": 10.00,
                            "demand_ten_thousand_vehicles": 147.00,
                            "demand_change_pct": 5.00,
                            "production_cost_ten_thousand_usd": 3.21,
                            "production_cost_change_pct": 2.00
                        }
                    },
                    "iteration": 1
                },

                {
                    "type": "iteration_start",
                    "data": {
                        "iteration_text": "迭代 2",
                        "initiator": "us",
                        "content": "美国财政部公布初步调查结果，指责中国补贴导致市场扭曲，同时暗示若中方让步可放缓关税升级。"
                    },
                    "iteration": 2
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "us",
                                "action": "提出附带条件谈判",
                                "action_detail": "美国建议与中国开启磋商，条件是中国削减补贴规模30%，否则将对其他输美零部件加征25%关税。"
                            }
                        ]
                    },
                    "iteration": 2
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "china",
                                "action": "扩大报复关税范围",
                                "action_detail": "中国宣布对进口美产大型排量汽车加征10%关税，并启动对美国在华企业享受税收优惠的合规审查。"
                            }
                        ]
                    },
                    "iteration": 2
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "us_corp",
                                "action": "加强供应链本土化",
                                "action_detail": "美国车企决定将关键电子控制单元(ECU)生产迁回本土，并寻求联邦补贴以抵消成本上升。"
                            }
                        ]
                    },
                    "iteration": 2
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "chine_corp",
                                "action": "转向东盟与非洲市场",
                                "action_detail": "中国车企与泰国及南非政府签署组装工厂协议，以绕过美方关税并扩大新兴市场份额。"
                            }
                        ]
                    },
                    "iteration": 2
                },
                {
                    "type": "economic_data",
                    "data": {
                        "china": {
                            "import_value_billion_usd": 60.00,
                            "import_change_pct": -20.00,
                            "export_value_billion_usd": 303.40,
                            "export_change_pct": -18.00,
                            "market_share_pct": 28.35,
                            "market_share_change_pct": -10.00,
                            "annual_production_ten_thousand_vehicles": 846,
                            "annual_production_change_pct": -6.00,
                            "demand_ten_thousand_vehicles": 708.40,
                            "demand_change_pct": -8.00,
                            "production_cost_ten_thousand_usd": 2.42,
                            "production_cost_change_pct": 5.00
                        },
                        "us": {
                            "import_value_billion_usd": 90.00,
                            "import_change_pct": -25.00,
                            "export_value_billion_usd": 61.75,
                            "export_change_pct": -5.00,
                            "market_share_pct": 11.34,
                            "market_share_change_pct": 8.00,
                            "annual_production_ten_thousand_vehicles": 240.80,
                            "annual_production_change_pct": 12.00,
                            "demand_ten_thousand_vehicles": 135.80,
                            "demand_change_pct": -3.00,
                            "production_cost_ten_thousand_usd": 3.34,
                            "production_cost_change_pct": 6.00
                        }
                    },
                    "iteration": 2
                },

                {
                    "type": "iteration_start",
                    "data": {
                        "iteration_text": "迭代 3",
                        "initiator": "us",
                        "content": "在多方压力下，美国宣布暂缓对新增零部件关税，提出建立中美新能源汽车补贴透明机制的框架协议草案。"
                    },
                    "iteration": 3
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "us",
                                "action": "暂缓部分关税并提议补贴透明框架",
                                "action_detail": "美国将延后原定于60天后生效的额外25%关税，并邀请中国在WTO框架下共同制定新能源汽车补贴披露规则。"
                            }
                        ]
                    },
                    "iteration": 3
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "china",
                                "action": "同意谈判并降低部分关税",
                                "action_detail": "中国同意参与补贴透明机制谈判，并宣布对部分美国农产品关税减让2%，作为善意回应。"
                            }
                        ]
                    },
                    "iteration": 3
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "us_corp",
                                "action": "扩大对欧盟出口计划",
                                "action_detail": "预期关税缓和后，美国车企将利用产能过剩向欧盟市场出口高端电动车，以分散对中国零部件依赖。"
                            }
                        ]
                    },
                    "iteration": 3
                },
                {
                    "type": "agent_announce",
                    "data": {
                        "agents": [
                            {
                                "agent": "chine_corp",
                                "action": "提升绿色制造能力",
                                "action_detail": "中国车企宣布全面升级生产线以降低碳排放，并计划在欧洲建立电池回收网络，提升品牌形象。"
                            }
                        ]
                    },
                    "iteration": 3
                },
                {
                    "type": "economic_data",
                    "data": {
                        "china": {
                            "import_value_billion_usd": 63.75,
                            "import_change_pct": -15.00,
                            "export_value_billion_usd": 325.60,
                            "export_change_pct": -12.00,
                            "market_share_pct": 29.61,
                            "market_share_change_pct": -6.00,
                            "annual_production_ten_thousand_vehicles": 864,
                            "annual_production_change_pct": -4.00,
                            "demand_ten_thousand_vehicles": 746.90,
                            "demand_change_pct": -3.00,
                            "production_cost_ten_thousand_usd": 2.25,
                            "production_cost_change_pct": -2.00
                        },
                        "us": {
                            "import_value_billion_usd": 108.00,
                            "import_change_pct": -10.00,
                            "export_value_billion_usd": 68.25,
                            "export_change_pct": 5.00,
                            "market_share_pct": 11.55,
                            "market_share_change_pct": 10.00,
                            "annual_production_ten_thousand_vehicles": 232.20,
                            "annual_production_change_pct": 8.00,
                            "demand_ten_thousand_vehicles": 142.80,
                            "demand_change_pct": 2.00,
                            "production_cost_ten_thousand_usd": 3.12,
                            "production_cost_change_pct": -1.00
                        }
                    },
                    "iteration": 3
                }
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