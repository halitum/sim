import streamlit as st
import pandas as pd
import requests
import json
import re
from datetime import datetime
import csv
import io
import base64
import time

# --- 页面配置 ---
st.set_page_config(page_title="中美政策博弈模拟器", layout="wide")

# --- 常量定义 ---
US_FLAG_SMALL = "<img src='https://flagcdn.com/96x72/us.png' width='20' height='16'>"
CN_FLAG_SMALL = "<img src='https://flagcdn.com/96x72/cn.png' width='20' height='16'>"
US_FLAG_LARGE = "<img src='https://flagcdn.com/96x72/us.png' width='36' height='27'>"
CN_FLAG_LARGE = "<img src='https://flagcdn.com/96x72/cn.png' width='36' height='27'>"
# 添加车企图标
US_CORP_ICON = "🚙"  # 美国车企图标
CN_CORP_ICON = "🏎️"  # 中国车企图标
ACTOR_ICONS = {'us': US_FLAG_SMALL + " **美政府**", 'china': CN_FLAG_SMALL + " **中政府**"}
API_URL = 'http://117.144.211.232:6010/start'

# --- 初始化 Session State ---
if 'current_iteration' not in st.session_state:
    st.session_state.current_iteration = 0

if 'chat_messages' not in st.session_state:
    st.session_state.chat_messages = {}  # 用字典按回合存储消息
    
if 'economic_data' not in st.session_state:
    st.session_state.economic_data = {}  # 存储经济数据

# 新增：存储实时消息的状态
if 'live_message' not in st.session_state:
    st.session_state.live_message = None

# --- 辅助函数 ---
def get_formatted_actor(name):
    """返回格式化的行为者名称"""
    name = name.lower()
    return ACTOR_ICONS.get(name, f"**{name.upper()}**")

def fetch_api_data(iteration=None, actor=None, stream=False):
    """从API获取数据，支持流式处理"""
    params = {k: v for k, v in {'iteration': iteration, 'actor': actor}.items() if v is not None}
    try:
        if stream:
            # 使用stream=True参数来获取流式响应
            response = requests.get(API_URL, headers={'accept': 'application/json'}, 
                                   params=params, timeout=20, stream=True)
            response.raise_for_status()
            return response  # 返回响应对象而非文本
        else:
            # 原有的一次性获取方式
            response = requests.get(API_URL, headers={'accept': 'application/json'}, 
                                   params=params, timeout=20)
            response.raise_for_status()
            return response.text
    except requests.exceptions.RequestException as e:
        st.error(f"API 请求失败: {e}")
        return None

def parse_chat_message(data):
    """将日志消息转换为聊天格式"""
    type_value = data.get('type', '')
    iteration = data.get('iteration', 0) + 1  # 回合数+1
    data_obj = data.get('data', {})
    
    if type_value == 'iteration_start':
        initiator = data_obj.get('initiator', '').lower()
        content = data_obj.get('content', '')
        return {
            "side": "right" if initiator == "us" else "left",
            "icon": US_FLAG_SMALL if initiator == "us" else CN_FLAG_SMALL,
            "role": "政府",
            "message": content,
            "iteration": iteration
        }
    elif type_value == 'agent_announce':
        agents = data_obj.get('agents', [])
        if agents:
            agent = agents[0]
            agent_name = agent.get('agent', '').lower()
            action_detail = agent.get('action_detail', '')
            
            is_us = agent_name.startswith('us')
            is_corp = "corp" in agent_name
            
            # 根据是否为车企选择不同图标
            if is_corp:
                icon = US_CORP_ICON if is_us else CN_CORP_ICON
            else:
                icon = US_FLAG_SMALL if is_us else CN_FLAG_SMALL
                
            return {
                "side": "right" if is_us else "left",
                "icon": icon,
                "role": "车企" if is_corp else "政府",
                "message": action_detail,
                "iteration": iteration
            }
    
    return None

def process_api_data(response_text, update_current_iteration=False):
    """处理API响应并更新聊天消息和经济数据"""
    if not response_text:
        return 0
        
    # 解析SSE响应
    messages_by_iteration = {}
    economic_data_by_iteration = {}
    max_iteration = 0
    
    for line in response_text.strip().split('\n'):
        if line.startswith('data: '):
            try:
                data = json.loads(line[6:])
                
                # 获取回合数
                iteration = data.get('iteration', 0) + 1  # 回合数+1
                max_iteration = max(max_iteration, iteration)
                
                # 解析聊天消息
                if chat_msg := parse_chat_message(data):
                    iteration = chat_msg['iteration']
                    if iteration not in messages_by_iteration:
                        messages_by_iteration[iteration] = []
                    messages_by_iteration[iteration].append(chat_msg)
                    
                # 处理economic_data类型
                if data.get('type') == 'economic_data':
                    economic_data_by_iteration[iteration] = data.get('data', {})
                
            except json.JSONDecodeError:
                pass
    
    # 更新聊天消息和经济数据
    for iteration, messages in messages_by_iteration.items():
        if messages:
            st.session_state.chat_messages[iteration] = messages
    
    # 更新经济数据
    for iteration, econ_data in economic_data_by_iteration.items():
        st.session_state.economic_data[iteration] = econ_data
    
    # 如果需要更新当前迭代
    if update_current_iteration and max_iteration > st.session_state.current_iteration:
        st.session_state.current_iteration = max_iteration
    
    return sum(len(msgs) for msgs in messages_by_iteration.values())

def get_economic_df(round_number=None, show_all_rounds=False):
    """从经济数据创建DataFrame用于展示，可选择显示特定回合或所有回合"""
    # 如果没有经济数据，使用默认数据
    if not st.session_state.economic_data:
        data = {
            '指标': ['进口额 (亿美元)', '出口额 (亿美元)', '市场占有率 (%)', '年产量 (万辆)', 
                 '需求量 (万辆)', '生产成本 (万美元/辆)'],
            '中国': [75, 370, 31.5, 900, 770, 2.3],
            '中国变化率': [0,0,0,0,0,0,],
            '美国': [120, 65, 10.5, 215, 140, 3.15],
            '美国变化率': [0,0,0,0,0,0]
        }
        return pd.DataFrame(data).set_index('指标')
    
    indicators = ['进口额 (亿美元)', '出口额 (亿美元)', '市场占有率 (%)', '年产量 (万辆)', 
                 '需求量 (万辆)', '生产成本 (万美元/辆)']
    
    # API字段映射到中文指标
    field_mapping = {
        '进口额 (亿美元)': 'import_value_billion_usd',
        '出口额 (亿美元)': 'export_value_billion_usd',
        '市场占有率 (%)': 'market_share_pct',
        '年产量 (万辆)': 'annual_production_ten_thousand_vehicles',
        '需求量 (万辆)': 'demand_ten_thousand_vehicles',
        '生产成本 (万美元/辆)': 'production_cost_ten_thousand_usd',
    }
    
    if show_all_rounds:
        # 原有逻辑，显示最多4个回合
        # 获取所有回合号并排序
        all_iterations = sorted(st.session_state.economic_data.keys())
        
        # 如果回合数不足4个，则全部显示；否则只显示最近4个回合
        recent_iterations = all_iterations[-4:] if len(all_iterations) > 4 else all_iterations
        
        # 创建多回合数据框
        multi_round_data = {'指标': indicators}
        
        # 为每个回合创建列
        for iteration in recent_iterations:
            econ_data = st.session_state.economic_data.get(iteration, {})
            
            # 提取中国和美国的数据
            cn_values = []
            us_values = []
            
            for indicator in indicators:
                field_name = field_mapping.get(indicator)
                
                # 从中国数据中获取
                if 'china' in econ_data and field_name in econ_data['china']:
                    cn_val = econ_data['china'][field_name]
                else:
                    cn_val = 0
                    
                # 从美国数据中获取
                if 'us' in econ_data and field_name in econ_data['us']:
                    us_val = econ_data['us'][field_name]
                else:
                    us_val = 0
                
                cn_values.append(cn_val)
                us_values.append(us_val)
            
            # 添加到数据框
            multi_round_data[f'中国(回合{iteration})'] = cn_values
            multi_round_data[f'美国(回合{iteration})'] = us_values
        
        return pd.DataFrame(multi_round_data).set_index('指标')
    else:
        # 修改为使用选定的回合
        round_to_display = round_number if round_number is not None else st.session_state.current_iteration
        current_econ_data = st.session_state.economic_data.get(round_to_display, {})
        prev_econ_data = {}
        
        if round_to_display > 1:
            prev_econ_data = st.session_state.economic_data.get(round_to_display - 1, {})
        
        data = {'指标': indicators}
        
        # 提取中国和美国的数据
        cn_data, us_data = [], []
        cn_change, us_change = [], []
        
        # 从API响应获取数据
        for indicator in indicators:
            field_name = field_mapping.get(indicator)
            
            # 从中国数据中获取
            if 'china' in current_econ_data and field_name in current_econ_data['china']:
                cn_val = current_econ_data['china'][field_name]
            else:
                cn_val = 0  # 如果找不到数据，使用默认值
                
            # 从美国数据中获取
            if 'us' in current_econ_data and field_name in current_econ_data['us']:
                us_val = current_econ_data['us'][field_name]
            else:
                us_val = 0  # 如果找不到数据，使用默认值
            
            cn_data.append(cn_val)
            us_data.append(us_val)
            
            # 计算变化率
            change_field = field_name + '_change_pct' if field_name else None
            
            if change_field and 'china' in current_econ_data and change_field in current_econ_data['china']:
                cn_pct = current_econ_data['china'][change_field]
            elif prev_econ_data and 'china' in prev_econ_data and field_name in prev_econ_data['china']:
                prev_cn = prev_econ_data['china'][field_name]
                cn_pct = ((cn_val - prev_cn) / prev_cn * 100) if prev_cn else 0
            else:
                cn_pct = 0
                
            if change_field and 'us' in current_econ_data and change_field in current_econ_data['us']:
                us_pct = current_econ_data['us'][change_field]
            elif prev_econ_data and 'us' in prev_econ_data and field_name in prev_econ_data['us']:
                prev_us = prev_econ_data['us'][field_name]
                us_pct = ((us_val - prev_us) / prev_us * 100) if prev_us else 0
            else:
                us_pct = 0
                
            cn_change.append(round(cn_pct, 1) if isinstance(cn_pct, (int, float)) else 0)
            us_change.append(round(us_pct, 1) if isinstance(us_pct, (int, float)) else 0)
        
        data['中国'] = cn_data
        data['中国变化率'] = cn_change
        data['美国'] = us_data
        data['美国变化率'] = us_change
        
        return pd.DataFrame(data).set_index('指标')

def get_download_link_csv(data):
    """生成CSV下载链接"""
    csv_data = []
    # CSV表头
    header = ["回合", "方", "角色", "内容"]
    csv_data.append(header)
    
    # 整理数据为CSV格式
    for iteration, messages in sorted(data.items()):
        for msg in messages:
            side = "美国" if msg['side'] == "right" else "中国"
            row = [iteration, side, msg['role'], msg['message']]
            csv_data.append(row)
    
    # 创建CSV并生成下载链接
    csv_string = io.StringIO()
    writer = csv.writer(csv_string)
    writer.writerows(csv_data)
    csv_string = csv_string.getvalue()
    
    # 当前日期时间作为文件名
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"政策博弈日志_{now}.csv"
    
    b64 = base64.b64encode(csv_string.encode()).decode()
    href = f'<a href="data:file/csv;base64,{b64}" download="{filename}">下载CSV文件</a>'
    return href

def get_download_link_json(data):
    """生成JSON下载链接"""
    # 格式化JSON数据
    json_data = {}
    for iteration, messages in data.items():
        # 将回合数转为字符串作为键
        json_data[str(iteration)] = messages
    
    json_string = json.dumps(json_data, ensure_ascii=False, indent=2)
    
    # 当前日期时间作为文件名
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"政策博弈日志_{now}.json"
    
    b64 = base64.b64encode(json_string.encode()).decode()
    href = f'<a href="data:file/json;base64,{b64}" download="{filename}">下载JSON文件</a>'
    return href

# 新增函数：实时处理流式API响应
def process_stream_response(response, message_placeholder):
    """处理流式响应并实时更新UI"""
    if not response:
        return
    
    buffer = ""
    max_iteration = 0
    messages_by_iteration = {}
    economic_data_by_iteration = {}
    
    # 创建空的聊天容器来存放所有实时消息
    chat_history = []
    current_displayed_iteration = 0
    
    # 创建显示当前推演回合的进度指示器
    progress_placeholder = st.empty()
    
    # 使用迭代器处理流式响应
    for chunk in response.iter_lines():
        if chunk:
            line = chunk.decode('utf-8')
            if line.startswith('data: '):
                try:
                    # 处理每一行数据
                    data = json.loads(line[6:])
                    
                    # 获取回合数
                    iteration = data.get('iteration', 0) + 1  # 回合数+1
                    max_iteration = max(max_iteration, iteration)
                    
                    # 更新进度指示器，显示当前正在推演的回合
                    progress_placeholder.info(f"⏱️ 正在推演第 {iteration} 回合...")
                    
                    # 解析聊天消息
                    if chat_msg := parse_chat_message(data):
                        iteration = chat_msg['iteration']
                        if iteration not in messages_by_iteration:
                            messages_by_iteration[iteration] = []
                        messages_by_iteration[iteration].append(chat_msg)
                        
                        # 修改以确保正确存储消息
                        if iteration not in st.session_state.chat_messages:
                            st.session_state.chat_messages[iteration] = []
                        st.session_state.chat_messages[iteration].append(chat_msg)
                        
                        # 实时显示消息 - 仅显示当前回合的消息
                        if iteration == max_iteration:  # 只显示最新回合的消息
                            # 如果是新回合，添加回合标题
                            if current_displayed_iteration != iteration:
                                current_displayed_iteration = iteration
                                chat_history = []  # 清空之前回合的消息
                                # 添加回合标题
                                round_title = f"""
                                <div style="text-align:center; margin:10px 0; background-color:#f0f2f6; padding:10px; border-radius:5px;">
                                    <h3>⏱️ 第 {iteration} 回合</h3>
                                </div>
                                """
                                chat_history.append(round_title)
                            
                            side = chat_msg['side']
                            bubble_class = f"chat-bubble-{side}"
                            container_class = f"chat-{side}"
                            
                            # 创建新消息的HTML
                            new_msg_html = f"""
                            <div class="{container_class}">
                                <div class="avatar">{chat_msg['icon']}</div>
                                <div class="{bubble_class}">
                                    <b>{chat_msg['role']}：</b>{chat_msg['message']}
                                </div>
                            </div>
                            """
                            
                            # 添加到历史并更新显示
                            chat_history.append(new_msg_html)
                            
                            # 将所有历史消息连接起来显示
                            full_history = "".join(chat_history)
                            message_placeholder.markdown(full_history, unsafe_allow_html=True)
                            
                            # 小延迟让用户能感知到实时性
                            time.sleep(0.5)
                        
                    # 处理economic_data类型
                    if data.get('type') == 'economic_data':
                        economic_data_by_iteration[iteration] = data.get('data', {})
                        # 直接更新session state中的经济数据
                        st.session_state.economic_data[iteration] = data.get('data', {})
                        
                except json.JSONDecodeError:
                    pass
    
    # 更新当前迭代
    if max_iteration > st.session_state.current_iteration:
        st.session_state.current_iteration = max_iteration
    
    # 强制刷新UI来显示侧边栏的更新
    st.rerun()
    
    return max_iteration

# --- 页面布局与内容 ---

# 侧边栏：政策博弈日志
with st.sidebar:
    st.title("政策博弈日志")
    st.divider()
    
    # 导出功能
    st.subheader("📤 导出日志")
    col1, col2 = st.columns(2)
    if st.session_state.chat_messages:
        with col1:
            st.markdown(get_download_link_csv(st.session_state.chat_messages), unsafe_allow_html=True)
        with col2:
            st.markdown(get_download_link_json(st.session_state.chat_messages), unsafe_allow_html=True)
    else:
        st.info("暂无日志数据可导出")
    
    st.divider()
    
    # 显示所有回合的日志
    st.subheader("🗒️ 历史记录")
    
    if not st.session_state.chat_messages:
        st.info("暂无博弈记录")
    else:
        # 按回合排序显示
        for iteration in sorted(st.session_state.chat_messages.keys()):
            with st.expander(f"第 {iteration} 回合", expanded=False):
                messages = st.session_state.chat_messages[iteration]
                for msg in messages:
                    side_text = "美方" if msg['side'] == "right" else "中方"
                    st.markdown(f"**{side_text} {msg['role']}**：{msg['message']}")
                    st.divider()

st.title("中美政策博弈模拟器")
st.caption("多智能体模拟：美国政府与车企 vs 中国政府与车企")

# 设置CSS样式
st.markdown(""" 
<style>
/* 聊天气泡样式 */
.chat-left { display: flex; justify-content: flex-start; margin-bottom: 10px; }
.chat-right { display: flex; justify-content: flex-end; margin-bottom: 10px; }
.chat-bubble-left { background-color: #f0f2f6; padding: 10px; border-radius: 18px; max-width: 80%; }
.chat-bubble-right { background-color: #e6f3ff; padding: 10px; border-radius: 18px; max-width: 80%; }
.avatar { margin-right: 10px; font-size: 25px; }

/* 按钮样式 */
div.stButton > button {
    height: 80px;
    font-size: 20px;
    font-weight: bold;
}
div.stButton > button:hover {
    background-color: #f0f2f6;
}
div.stButton > button * {
    font-size: 20px;
}
</style>
""", unsafe_allow_html=True)

# 模拟状态与聊天区域
with st.container():  
    # 标题行：中美双方和当前回合
    col_cn, col_middle, col_us = st.columns([2, 1, 2])
    
    with col_middle:
        st.markdown(f"<h4 style='text-align: center;'>当前回合: <span style='font-size: 32px;'>{st.session_state.current_iteration}</span></h3>", unsafe_allow_html=True)

    # 聊天界面
    chat_container = st.container(border=True)
    
    # 创建一个占位符用于实时更新消息
    message_placeholder = st.empty()
    
    with chat_container:
        # 显示当前消息
        current_messages = st.session_state.chat_messages.get(st.session_state.current_iteration, [])
        
        # 有当前回合的消息时显示消息，否则显示初始提示
        if current_messages:
            chat_history = []
            for msg in current_messages:
                side = msg['side']
                bubble_class = f"chat-bubble-{side}"
                container_class = f"chat-{side}"
                
                new_msg_html = f"""
                <div class="{container_class}">
                    <div class="avatar">{msg['icon']}</div>
                    <div class="{bubble_class}">
                        <b>{msg['role']}：</b>{msg['message']}
                    </div>
                </div>
                """
                chat_history.append(new_msg_html)
            
            full_history = "".join(chat_history)
            message_placeholder.markdown(full_history, unsafe_allow_html=True)
        elif st.session_state.current_iteration == 0:
            st.markdown("### 📢 **关税战开始**")
            st.info("美国总统特朗普签署行政令，宣布：对所有贸易伙伴加征10%的关税。对与美国贸易逆差更大的国家和地区征收更高的\"对等关税\"")
    
    # 控制按钮 - 只保留重新开始和自动推演
    b_reset, b_auto = st.columns(2)  # 将3列改为2列
    
    if b_reset.button("🔄 重新开始", use_container_width=True, key="reset_button"):
        st.session_state.current_iteration = 0
        st.session_state.chat_messages = {}
        st.session_state.economic_data = {}
        message_placeholder.empty()  # 清空消息占位符
        st.rerun()
    
    # 修改"自动推演"按钮的逻辑
    if b_auto.button("⏩ 自动推演", use_container_width=True, key="auto_button"):
        # 激活自动模式
        st.session_state.auto_mode = True
        # 使用流式处理获取所有回合的数据
        message_placeholder.empty()  # 清空之前的消息
        
        # 显示加载提示
        with st.spinner("正在推演中，请稍候..."):
            response = fetch_api_data(stream=True)
            if response:
                process_stream_response(response, message_placeholder)
        
        # 如果没有获取到任何记录，显示提示
        if not st.session_state.chat_messages:
            message_placeholder.info("未获取到任何博弈记录")

st.divider()

# --- 结果评估区域 ---
st.header("博弈过程的经济数据")

# 获取可用的回合选项
available_rounds = sorted(st.session_state.economic_data.keys())
if not available_rounds and st.session_state.current_iteration > 0:
    available_rounds = [st.session_state.current_iteration]

# 回合选择器
selected_round = st.session_state.current_iteration
if available_rounds:
    selected_round = st.selectbox(
        "选择要查看的回合",
        options=available_rounds,
        index=available_rounds.index(st.session_state.current_iteration) if st.session_state.current_iteration in available_rounds else 0
    )

# 准备所选回合的数据
df_results = get_economic_df(round_number=selected_round)

# 使用选项卡分隔不同视图
tab1, tab2, tab3 = st.tabs(["📊 表格视图", "📈 图表视图", "🔍 API数据获取"])

with tab1:
    # 显示数据表格，添加高亮显示变化
    def highlight_changes(s, column):
        change_column = f"{column}变化率"
        if change_column in s.index:
            change_value = s[change_column]
            if isinstance(change_value, (int, float)):
                if change_value > 0:
                    return ['background-color: #d4f7d4'] * len(s)  # 绿色
                elif change_value < 0:
                    return ['background-color: #f7d4d4'] * len(s)  # 红色
        return [''] * len(s)
    
    # 显示所选回合信息
    st.subheader(f"第 {selected_round} 回合经济数据")
    
    # 分别显示中国和美国的数据，带变化高亮
    st.subheader("中国经济数据")
    cn_df = df_results[['中国', '中国变化率']].copy()
    st.dataframe(cn_df.style.apply(highlight_changes, column='中国', axis=1))
    
    st.subheader("美国经济数据")
    us_df = df_results[['美国', '美国变化率']].copy()
    st.dataframe(us_df.style.apply(highlight_changes, column='美国', axis=1))

with tab2:
    # 修改图表标题以包含选定回合
    st.subheader(f"第 {selected_round} 回合关键指标对比")
    key_indicators = ['进口额 (亿美元)', '出口额 (亿美元)', '市场占有率 (%)', '年产量 (万辆)']
    
    # 为所选回合创建指标对比图表
    if all(indicator in df_results.index for indicator in key_indicators):
        comparison_data = df_results.loc[key_indicators, ['中国', '美国']]
        st.bar_chart(comparison_data)
        
        # 添加变化率趋势图
        st.subheader("变化率对比")
        change_data = df_results.loc[key_indicators, ['中国变化率', '美国变化率']]
        change_data.columns = ['中国', '美国']  # 重命名列以便于图表显示
        st.bar_chart(change_data)
        
        st.info(f"图表展示了第 {selected_round} 回合关键指标的中美对比及变化率。")
    else:
        st.warning("缺少部分关键指标数据，无法生成完整图表。")

with tab3:
    st.subheader("自定义API请求")
    col1, col2 = st.columns(2)
    
    iteration_input = col1.number_input("回合数", min_value=0, value=st.session_state.current_iteration)
    actor_input = col2.selectbox("行动者", ["所有", "US", "CN"])
    
    if st.button("获取数据"):
        actor_param = None if actor_input == "所有" else actor_input
        if response_text := fetch_api_data(iteration_input, actor_param):
            new_entries = process_api_data(response_text)
            st.write("成功获取 {} 条新数据".format(new_entries) if new_entries > 0 else "没有获取到新数据")
            
            with st.expander("查看原始响应"):
                st.code(response_text)