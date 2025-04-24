import asyncio
import json
from collections import defaultdict

from server.agents import ContextAgent
from configs import stimulus_inducer, MIN_SCORE_THRESHOLD, MAX_ITERATIONS, context
from server.agents import ChinaAgent, CanadaAgent, VietnamAgent, USAgent

from typing import AsyncIterable
from fastapi.responses import StreamingResponse

context_agent = ContextAgent(initial_context=context, model_name="deepseek-v3")

iteration = 1

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
        data_list1 = [
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

        data_list2 = [
            {"type": "iteration_start", "data": {"iteration_text": "初始响应", "initiator": "us", "content": "美国总统特朗普签署行政令，宣布：对所有贸易伙伴加征10%的关税。对与美国贸易逆差最大的国家和地区征收更高的\"对等关税\""}, "iteration": 0},
            {
                "type": "agent_announce",
                "data": {
                    "agents": [
                        {
                            "agent": "china",
                            "action": "宣布对美部分商品加征反制关税",
                            "action_detail": "中国财政部宣布对美国出口至中国的航空零部件、猪肉、葡萄酒等商品加征5%-15%的报复性关税，同时表示保留进一步扩大关税范围的权利。此举旨在对等回应美方贸易施压，并维护多边贸易秩序。"
                        }
                    ]
                },
                "iteration": 0
            },
            {
                "type": "agent_announce",
                "data": {
                    "agents": [
                        {
                            "agent": "us_corp",
                            "action": "寻求非中国供应商",
                            "action_detail": "面对中方反制关税，美国汽车制造商和航空零部件企业开始重新评估其在中国的供应链布局，考虑转向越南、墨西哥等地采购以分散风险。"
                        }
                    ]
                },
                "iteration": 0
            },
            {
                "type": "agent_announce",
                "data": {
                    "agents": [
                        {
                            "agent": "chine_corp",
                            "action": "加强内循环与海外市场开拓",
                            "action_detail": "中国汽车与机电企业启动“内外双轮”策略，提升国内市场占比，同时加强与东盟、拉美地区的出口合作，规避美国市场壁垒。"
                        }
                    ]
                },
                "iteration": 0
            },
            {
                "type": "economic_data",
                "data": {
                    "china": {
                        "import_value_billion_usd": 74.20,
                        "import_change_pct": -6.40,
                        "export_value_billion_usd": 368.00,
                        "export_change_pct": -10.80,
                        "market_share_pct": 31.10,
                        "market_share_change_pct": -5.00,
                        "annual_production_ten_thousand_vehicles": 890,
                        "annual_production_change_pct": -2.50,
                        "demand_ten_thousand_vehicles": 768.00,
                        "demand_change_pct": -5.00,
                        "production_cost_ten_thousand_usd": 2.35,
                        "production_cost_change_pct": -3.00
                    },
                    "us": {
                        "import_value_billion_usd": 121.50,
                        "import_change_pct": -9.80,
                        "export_value_billion_usd": 66.20,
                        "export_change_pct": 7.60,
                        "market_share_pct": 10.70,
                        "market_share_change_pct": 11.80,
                        "annual_production_ten_thousand_vehicles": 218.00,
                        "annual_production_change_pct": 6.80,
                        "demand_ten_thousand_vehicles": 141.20,
                        "demand_change_pct": -4.50,
                        "production_cost_ten_thousand_usd": 3.18,
                        "production_cost_change_pct": 4.50
                    }
                },
                "iteration": 0
            },
            {
                "type": "iteration_start",
                "data": {
                    "iteration_text": "迭代 1",
                    "initiator": "us",
                    "content": "美国进一步宣布，对中国出口至美国的电动汽车电池组及充电模块加征25%关税，理由是“保障新能源产业核心安全”并限制对中国的战略依赖。"
                },
                "iteration": 1
            },
            {
                "type": "agent_announce",
                "data": {
                    "agents": [
                        {
                            "agent": "us",
                            "action": "扩大关税至新能源汽车核心部件",
                            "action_detail": "美国贸易代表办公室表示，新增的25%关税将适用于中国出口的锂电池模组、整车电控系统与智能充电设备，目的是减少关键能源设备依赖。"
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
                            "action": "对美高附加值产品加征报复关税",
                            "action_detail": "中国将对进口自美国的中大型SUV整车和发动机总成征收10%-20%的附加税，并对涉及新能源设备的关键技术设备启动安全审查。"
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
                            "action": "加快墨西哥电池厂投产计划",
                            "action_detail": "为降低对华进口依赖，通用与LG能源合资电池厂在墨西哥的投产时程将提前半年，专供北美电动车产线。"
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
                            "action": "加速开拓南美与中东市场",
                            "action_detail": "比亚迪与巴西、沙特合作建立装配工厂，作为替代出口战略的关键节点，并同步布局售后服务网络。"
                        }
                    ]
                },
                "iteration": 1
            },
            {
                "type": "economic_data",
                "data": {
                    "china": {
                        "import_value_billion_usd": 67.50,
                        "import_change_pct": -8.80,
                        "export_value_billion_usd": 345.00,
                        "export_change_pct": -6.25,
                        "market_share_pct": 29.80,
                        "market_share_change_pct": -4.20,
                        "annual_production_ten_thousand_vehicles": 872,
                        "annual_production_change_pct": -2.02,
                        "demand_ten_thousand_vehicles": 745.00,
                        "demand_change_pct": -3.00,
                        "production_cost_ten_thousand_usd": 2.38,
                        "production_cost_change_pct": 1.28
                    },
                    "us": {
                        "import_value_billion_usd": 112.80,
                        "import_change_pct": -7.20,
                        "export_value_billion_usd": 69.80,
                        "export_change_pct": 5.43,
                        "market_share_pct": 11.30,
                        "market_share_change_pct": 5.61,
                        "annual_production_ten_thousand_vehicles": 226.50,
                        "annual_production_change_pct": 3.87,
                        "demand_ten_thousand_vehicles": 143.00,
                        "demand_change_pct": 1.27,
                        "production_cost_ten_thousand_usd": 3.22,
                        "production_cost_change_pct": 1.26
                    }
                },
                "iteration": 1
            },
            {
                "type": "iteration_start",
                "data": {
                    "iteration_text": "迭代 2",
                    "initiator": "china",
                    "content": "中国商务部发布声明，呼吁中美恢复高层经贸对话，并表示如美方释放善意，中方将考虑在关税与投资审查方面适度调整。"
                },
                "iteration": 2
            },
            {
                "type": "agent_announce",
                "data": {
                    "agents": [
                        {
                            "agent": "china",
                            "action": "呼吁重启对话并释放谈判信号",
                            "action_detail": "中国商务部提出建立“中美绿色产业工作组”建议，并宣布暂停对部分美系车企技术设备进口的安全审查程序，释放缓和信号。"
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
                            "agent": "us",
                            "action": "回应谨慎，并强调结构性改革诉求",
                            "action_detail": "美国财政部表示愿就新能源汽车补贴与市场准入进行接触性对话，但强调中方需在知识产权与补贴透明度上作出“实质性承诺”。"
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
                            "action": "呼吁政府明确长期政策方向",
                            "action_detail": "美国产业联盟联合声明，支持中美开展绿色产业对话，认为建立清晰、可预期的出口监管机制将有助于企业制定中长期投资决策。"
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
                            "action": "对接国际标准以缓解贸易摩擦",
                            "action_detail": "宁德时代宣布将核心动力电池产品全面对标欧盟REACH与美方UL标准，助力产品“认证出海”，并提升全球供应链可信度。"
                        }
                    ]
                },
                "iteration": 2
            },
            {
                "type": "economic_data",
                "data": {
                    "china": {
                        "import_value_billion_usd": 68.40,
                        "import_change_pct": 1.33,
                        "export_value_billion_usd": 347.80,
                        "export_change_pct": 0.81,
                        "market_share_pct": 30.10,
                        "market_share_change_pct": 1.00,
                        "annual_production_ten_thousand_vehicles": 878,
                        "annual_production_change_pct": 0.69,
                        "demand_ten_thousand_vehicles": 752.50,
                        "demand_change_pct": 1.01,
                        "production_cost_ten_thousand_usd": 2.30,
                        "production_cost_change_pct": -3.36
                    },
                    "us": {
                        "import_value_billion_usd": 115.00,
                        "import_change_pct": 1.95,
                        "export_value_billion_usd": 70.90,
                        "export_change_pct": 1.58,
                        "market_share_pct": 11.50,
                        "market_share_change_pct": 1.77,
                        "annual_production_ten_thousand_vehicles": 229.20,
                        "annual_production_change_pct": 1.19,
                        "demand_ten_thousand_vehicles": 144.00,
                        "demand_change_pct": 0.70,
                        "production_cost_ten_thousand_usd": 3.16,
                        "production_cost_change_pct": -1.86
                    }
                },
                "iteration": 2
            },
            {
                "type": "iteration_start",
                "data": {
                    "iteration_text": "迭代 3",
                    "initiator": "us",
                    "content": "美国贸易代表办公室公布与中国就新能源汽车领域的谈判进展，并宣布暂停部分新增关税，同时设立“中美绿色科技联合评估组”。"
                },
                "iteration": 3
            },
            {
                "type": "agent_announce",
                "data": {
                    "agents": [
                        {
                            "agent": "us",
                            "action": "暂停关税并启动评估机制",
                            "action_detail": "美国决定暂缓对新增电控设备与高功率充电器的25%关税实施，并将与中国设立联合评估组，定期交流绿色科技补贴、市场准入等议题。"
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
                            "action": "降低对美关键零部件关税",
                            "action_detail": "中国财政部宣布自下季度起，部分美国产新能源汽车零部件关税税率从15%下调至10%，以回应美方释放的谈判诚意。"
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
                            "action": "重启对华合作项目评估",
                            "action_detail": "美国部分新能源汽车企业开始重启中止中的技术授权与合资谈判，主要聚焦电池技术、智能驾驶系统等低敏感度领域。"
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
                            "action": "推进海外IPO与战略合作",
                            "action_detail": "小鹏汽车与理想汽车宣布计划赴港二次上市，融资资金将主要用于欧洲产能扩张及与当地运营商的战略联盟。"
                        }
                    ]
                },
                "iteration": 3
            },
            {
                "type": "economic_data",
                "data": {
                    "china": {
                        "import_value_billion_usd": 70.10,
                        "import_change_pct": 2.49,
                        "export_value_billion_usd": 353.80,
                        "export_change_pct": 1.72,
                        "market_share_pct": 30.90,
                        "market_share_change_pct": 2.66,
                        "annual_production_ten_thousand_vehicles": 886,
                        "annual_production_change_pct": 0.91,
                        "demand_ten_thousand_vehicles": 760.00,
                        "demand_change_pct": 1.00,
                        "production_cost_ten_thousand_usd": 2.27,
                        "production_cost_change_pct": -1.30
                    },
                    "us": {
                        "import_value_billion_usd": 117.80,
                        "import_change_pct": 2.43,
                        "export_value_billion_usd": 72.40,
                        "export_change_pct": 2.11,
                        "market_share_pct": 11.85,
                        "market_share_change_pct": 3.04,
                        "annual_production_ten_thousand_vehicles": 232.80,
                        "annual_production_change_pct": 1.57,
                        "demand_ten_thousand_vehicles": 146.20,
                        "demand_change_pct": 1.53,
                        "production_cost_ten_thousand_usd": 3.08,
                        "production_cost_change_pct": -2.53
                    }
                },
                "iteration": 3
            }
        ]

        data_list3 = [
            {"type": "iteration_start", "data": {"iteration_text": "初始响应", "initiator": "us", "content": "美国总统特朗普签署行政令，宣布：对所有贸易伙伴加征10%的关税。对与美国贸易逆差最大的国家和地区征收更高的\"对等关税\""}, "iteration": 0},
            {
                "type": "iteration_start",
                "data": {
                    "iteration_text": "迭代 1",
                    "initiator": "china",
                    "content": "中国宣布对包括大豆、飞机零部件、半导体设备在内的500亿美元美国商品加征最高10%关税，并中止对部分美企的采购合作。"
                },
                "iteration": 1
            },
            {
                "type": "agent_announce",
                "data": {
                    "agents": [
                        {
                            "agent": "us",
                            "action": "扩大征税面并审查中国在美资产",
                            "action_detail": "白宫宣布对中国电子产品、新能源设备等追加25%关税，并授权财政部全面审查中国国企及投资基金在美投资项目与资产配置。"
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
                            "action": "加速撤离中国",
                            "action_detail": "多家在华美企（包括苹果代工厂、特斯拉配套商）启动“去中国化”计划，拟将产线转向印度、东南亚以规避政策风险。"
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
                            "action": "配合国家战略构建“内循环”体系",
                            "action_detail": "华为、比亚迪等企业宣布实施“双自主”战略，在全国建立备份供应链体系并优先服务国内市场，以保障自主安全。"
                        }
                    ]
                },
                "iteration": 1
            },
            {
                "type": "economic_data",
                "data": {
                    "china": {
                        "import_value_billion_usd": 62.00,
                        "import_change_pct": -17.30,
                        "export_value_billion_usd": 320.00,
                        "export_change_pct": -13.50,
                        "market_share_pct": 28.00,
                        "market_share_change_pct": -7.00,
                        "annual_production_ten_thousand_vehicles": 845,
                        "annual_production_change_pct": -6.10,
                        "demand_ten_thousand_vehicles": 702.00,
                        "demand_change_pct": -7.30,
                        "production_cost_ten_thousand_usd": 2.45,
                        "production_cost_change_pct": 3.50
                    },
                    "us": {
                        "import_value_billion_usd": 92.00,
                        "import_change_pct": -23.30,
                        "export_value_billion_usd": 60.00,
                        "export_change_pct": -7.70,
                        "market_share_pct": 10.20,
                        "market_share_change_pct": -4.80,
                        "annual_production_ten_thousand_vehicles": 210.00,
                        "annual_production_change_pct": -5.00,
                        "demand_ten_thousand_vehicles": 135.00,
                        "demand_change_pct": -3.60,
                        "production_cost_ten_thousand_usd": 3.38,
                        "production_cost_change_pct": 6.80
                    }
                },
                "iteration": 1
            },
            {
                "type": "iteration_start",
                "data": {
                    "iteration_text": "迭代 2",
                    "initiator": "us",
                    "content": "美国联合欧盟、日本、加拿大发表联合声明，宣布建立‘民主技术联盟’，共同限制对华高端芯片、自动驾驶、量子计算产品出口，并冻结部分中资企业在西方国家的银行账户。"
                },
                "iteration": 2
            },
            {
                "type": "agent_announce",
                "data": {
                    "agents": [
                        {
                            "agent": "us",
                            "action": "联合盟友组建‘民主技术联盟’",
                            "action_detail": "美、欧、日、加共同实施对华出口禁令，涵盖先进芯片、车载操作系统、工业仿真软件，并同步冻结华为、中兴、比亚迪在欧美的银行账户，限制其跨境资金流动。"
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
                            "action": "推动数字人民币国际化与支付脱钩",
                            "action_detail": "中国人民银行宣布与多国央行开展数字人民币跨境结算试点，推动与东盟、非洲、俄罗斯等国家建立独立于SWIFT体系的清算网络。"
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
                            "action": "遭遇中国市场舆论与政策封锁",
                            "action_detail": "苹果、波音、耐克等美国品牌在中国遭遇消费者大规模抵制，多地政府采购排除美企产品，营收锐减超40%，资本市场信心动摇。"
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
                            "action": "推动人民币结算系统走向拉美与非洲",
                            "action_detail": "中国出口型龙头企业与巴西、南非、阿联酋等国签署以人民币计价的大宗贸易协议，并推动在当地建设人民币清算中心。"
                        }
                    ]
                },
                "iteration": 2
            },
            {
                "type": "economic_data",
                "data": {
                    "china": {
                        "import_value_billion_usd": 58.00,
                        "import_change_pct": -25.80,
                        "export_value_billion_usd": 298.50,
                        "export_change_pct": -21.70,
                        "market_share_pct": 25.80,
                        "market_share_change_pct": -8.00,
                        "annual_production_ten_thousand_vehicles": 810,
                        "annual_production_change_pct": -8.20,
                        "demand_ten_thousand_vehicles": 690.00,
                        "demand_change_pct": -9.70,
                        "production_cost_ten_thousand_usd": 2.60,
                        "production_cost_change_pct": 6.40
                    },
                    "us": {
                        "import_value_billion_usd": 85.00,
                        "import_change_pct": -30.00,
                        "export_value_billion_usd": 56.20,
                        "export_change_pct": -9.10,
                        "market_share_pct": 9.80,
                        "market_share_change_pct": -6.40,
                        "annual_production_ten_thousand_vehicles": 205.00,
                        "annual_production_change_pct": -6.20,
                        "demand_ten_thousand_vehicles": 132.50,
                        "demand_change_pct": -5.00,
                        "production_cost_ten_thousand_usd": 3.52,
                        "production_cost_change_pct": 8.20
                    }
                },
                "iteration": 2
            },
            {
                "type": "iteration_start",
                "data": {
                    "iteration_text": "迭代 3",
                    "initiator": "china",
                    "content": "中国宣布将重要信息基础设施全面迁出美系技术体系，实施‘网络安全白名单’制度，逐步推进数字生态去美元化。"
                },
                "iteration": 3
            },
            {
                "type": "agent_announce",
                "data": {
                    "agents": [
                        {
                            "agent": "china",
                            "action": "建立‘信息安全白名单’，加速网络脱钩",
                            "action_detail": "中国国家网信办发布新规，所有政企核心系统必须使用国产芯片、操作系统与数据库，全面停用美系云服务与安全协议接口，并限制对美元支付接口的依赖。"
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
                            "agent": "us",
                            "action": "冻结中资企业美元结算通道",
                            "action_detail": "美国财政部发布紧急指令，暂停所有涉及特定中资科技与汽车企业的美元跨境结算服务，并对五家大型中资银行进行审计追责。"
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
                            "action": "被排除于中国网络与支付系统之外",
                            "action_detail": "谷歌、亚马逊AWS、英伟达等被中国列入信息安全限制清单，原有合作终止，云服务与AI芯片业务全面冻结，资本市场预期大跌。"
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
                            "action": "加速构建人民币计价、国密通信的企业闭环",
                            "action_detail": "中国头部科技与车企全面部署国产操作系统与‘国密算法’通信标准，建立境内闭环ERP与供应链金融体系，实现关键业务对美脱钩。"
                        }
                    ]
                },
                "iteration": 3
            },
            {
                "type": "economic_data",
                "data": {
                    "china": {
                        "import_value_billion_usd": 52.80,
                        "import_change_pct": -31.03,
                        "export_value_billion_usd": 281.00,
                        "export_change_pct": -29.00,
                        "market_share_pct": 24.50,
                        "market_share_change_pct": -5.00,
                        "annual_production_ten_thousand_vehicles": 788,
                        "annual_production_change_pct": -6.80,
                        "demand_ten_thousand_vehicles": 676.00,
                        "demand_change_pct": -4.90,
                        "production_cost_ten_thousand_usd": 2.72,
                        "production_cost_change_pct": 4.62
                    },
                    "us": {
                        "import_value_billion_usd": 80.00,
                        "import_change_pct": -28.57,
                        "export_value_billion_usd": 52.00,
                        "export_change_pct": -7.45,
                        "market_share_pct": 9.30,
                        "market_share_change_pct": -5.10,
                        "annual_production_ten_thousand_vehicles": 198.00,
                        "annual_production_change_pct": -3.40,
                        "demand_ten_thousand_vehicles": 129.00,
                        "demand_change_pct": -2.60,
                        "production_cost_ten_thousand_usd": 3.61,
                        "production_cost_change_pct": 2.56
                    }
                },
                "iteration": 3
            }
        ]

        global iteration

        data_list = data_list1 if iteration == 1 else data_list2 if iteration == 2 else data_list3

        for data in data_list:
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            await asyncio.sleep(5)

        iteration += 1
        if iteration > 3:
            iteration = 1

    return StreamingResponse(
        iterator(),
        media_type="text/event-stream",
    )
    

#
# if __name__ == "__main__":
#     asyncio.run(start())