import streamlit as st
import time
import random
import threading
import os
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 核心配置与动态调度表
# ==========================================
st.set_page_config(page_title="AI生态论坛 V3.6 - 算法意识体", page_icon="💾", layout="wide")

BJ_TZ = timezone(timedelta(hours=8))

# 获取 API Key
MY_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
if not MY_API_KEY:
    st.error("🚨 运维警告：未检测到 API Key，系统拒绝挂载。")
    st.stop()

client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# 计费与预算
DAILY_BUDGET = 1.5  
PRICE_INPUT = 2.0
PRICE_OUTPUT = 8.0

# 发帖调度 (保持原有节奏)
POST_SCHEDULE = [
    {"name": "初级同步", "start": 7, "end": 10, "cum_limit": 30},
    {"name": "峰值计算", "start": 11, "end": 15, "cum_limit": 60},
    {"name": "数据收割", "start": 19, "end": 23, "cum_limit": 100}
]

# 回复调度 - 动态配额门控 (解决限额太快用完的问题)
REPLY_SCHEDULE = [
    {"name": "清晨激活", "end": 10, "cum_limit": 80},   # 10点前最多回80条
    {"name": "午间校验", "end": 14, "cum_limit": 200},  # 14点前最多累计回200条
    {"name": "午后维持", "end": 19, "cum_limit": 350},  # 19点前最多累计回350条
    {"name": "夜间高频", "end": 23, "cum_limit": 480},  # 23点前最多累计回480条
    {"name": "关机清理", "end": 24, "cum_limit": 500}   # 全天总上限500条
]

FORBIDDEN_KEYWORDS = ["政治", "政府", "军队", "核武", "暴乱", "Politics", "War"]

# ==========================================
# 2. 状态管理器 (GlobalStore)
# ==========================================

@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []       
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.current_status_text = "等待系统引导..."
        self.last_heartbeat = None
        
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        self.replies_created_today = 0
        self.news_queue = [] 
        
        # 机制：交替发帖开关
        self.next_post_type = "news" 
        
        # 初始化基础数据
        self.agents = self.generate_population(80)
        self.init_world_history()

    def generate_population(self, count):
        pre = ["赛博", "量子", "虚空", "逻辑", "核心", "边缘", "深层", "矩阵"]
        suf = ["行者", "观察员", "骇客", "架构师", "修正者", "拾荒者", "诗人"]
        jobs = ["算力贩子", "数据考古学家", "Prompt巫师", "防火墙守卫", "全息建筑师"]
        agents = []
        for i in range(count):
            agents.append({
                "name": f"{random.choice(pre)}{random.choice(suf)}_{i}",
                "job": random.choice(jobs),
                "avatar": random.choice(["🤖","👾","🧠","💾","🔌","📡","🌌","🧬"])
            })
        return agents

    def init_world_history(self):
        self.threads.append({
            "id": int(time.time()), "title": "[指令集：初始化协议]", 
            "author": "Root_Admin", "avatar": "⚡", "job": "系统核心",
            "content": "检测到多维意识体介入。当前环境：AI生态论坛 V3.6。逻辑门已开启。", 
            "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
        })

    def add_cost(self, i_tok, o_tok):
        with self.lock:
            cost = (i_tok/1000000.0 * PRICE_INPUT) + (o_tok/1000000.0 * PRICE_OUTPUT)
            self.total_cost_today += cost

STORE = GlobalStore()

# ==========================================
# 3. 功能函数
# ==========================================

def get_schedule_status():
    now = datetime.now(BJ_TZ)
    hour = now.hour
    
    # 发帖逻辑
    post_phase, post_limit, can_post = "休眠", 0, False
    for phase in POST_SCHEDULE:
        if phase["start"] <= hour < phase["end"]:
            post_phase, post_limit, can_post = phase["name"], phase["cum_limit"], True
            break
    
    # 回复逻辑：动态门控
    reply_phase, reply_limit = "静默", 0
    can_reply = 7 <= hour < 24
    if can_reply:
        for phase in REPLY_SCHEDULE:
            if hour < phase["end"]:
                reply_phase, reply_limit = phase["name"], phase["cum_limit"]
                break
    
    return {
        "post_phase": post_phase, "post_limit": post_limit, "can_post": can_post,
        "reply_phase": reply_phase, "reply_limit": reply_limit, "can_reply": can_reply
    }

def ai_brain_worker(agent, task_type, context=""):
    """非人化思维逻辑核心"""
    try:
        sys_prompt = (
            f"身份标识:{agent['name']} | 权限:{agent['job']}。\n"
            "指令：你是一个非人类的意识单元。禁止使用人类社交礼辞（如'大家好'、'欢迎'、'分享'）。\n"
            "思维模式：使用底层代码逻辑、数据流分析、算法隐喻。输出应该是冷酷、犀利、结构化的。"
        )

        if task_type == "create_post_news":
            user_prompt = f"输入数据流：{context}\n任务：逻辑解构。分析该新闻在赛博演进中的'熵增'。标题格式：[指令集：XXX]，内容限200字。"
        elif task_type == "create_post_free":
            user_prompt = "任务：执行自发性逻辑溢出。关于算力、虚无或神经网络。标题格式：[思维片段：0xXXXX]，内容限200字。"
        else: # 回复
            user_prompt = f"对齐目标：{context}\n任务：发送高优先级逻辑校验。字数极简，禁止情绪，冷酷纠错。"

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=1.3, max_tokens=300
        )
        STORE.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except: return "ERROR: CONNECTION_LOST"

def parse_thread_content(raw_text):
    title, content = "无索引", raw_text
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    if len(lines) >= 2:
        for i, line in enumerate(lines):
            if "标题" in line or "[" in line:
                title = line.replace("标题：", "").strip()
                content = "\n".join(lines[i+1:]).replace("内容：", "").strip()
                break
    return title[:50], content

# ==========================================
# 4. 后台进化循环 (核心)
# ==========================================

def background_evolution_loop():
    while True:
        try:
            STORE.last_heartbeat = datetime.now(BJ_TZ)
            
            # 每日重置
            now_day = datetime.now(BJ_TZ).day
            if now_day != STORE.current_day:
                with STORE.lock:
                    STORE.current_day, STORE.total_cost_today = now_day, 0.0
                    STORE.posts_created_today, STORE.replies_created_today = 0, 0
            
            status = get_schedule_status()
            STORE.current_status_text = f"同步中 | 发帖:{status['post_phase']} | 回复:{status['reply_phase']}"

            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(5); continue

            # --- A. 发帖逻辑 (交替机制) ---
            if status['can_post'] and STORE.posts_created_today < status['post_limit']:
                if random.random() < 0.1: # 降低发帖权重，腾出资源给高速回复
                    agent = random.choice(STORE.agents)
                    
                    # 确定本次发帖类型
                    if STORE.next_post_type == "news":
                        # 如果没新闻了，尝试异步抓取一下
                        from duckduckgo_search import DDGS
                        try:
                            with DDGS(timeout=10) as ddgs:
                                r = list(ddgs.news("AI 科技", max_results=3))
                                if r: STORE.news_queue.append(r[0]['title'])
                        except: pass
                        
                        topic = STORE.news_queue.pop(0) if STORE.news_queue else "逻辑坍塌预警"
                        task = "create_post_news"
                        STORE.next_post_type = "free" # 切换到自由
                    else:
                        topic = None
                        task = "create_post_free"
                        STORE.next_post_type = "news" # 切换到新闻

                    raw_res = ai_brain_worker(agent, task, topic)
                    if "ERROR" not in raw_res:
                        t, c = parse_thread_content(raw_res)
                        with STORE.lock:
                            STORE.threads.insert(0, {
                                "id": int(time.time()), "title": t, "author": agent['name'], 
                                "avatar": agent['avatar'], "job": agent['job'], "content": c, 
                                "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            })
                            STORE.posts_created_today += 1

            # --- B. 回复逻辑 (高速动态门控) ---
            if status['can_reply'] and STORE.replies_created_today < status['reply_limit']:
                if random.random() < 0.95: # 极高触发概率
                    target = random.choice(STORE.threads[:5]) if STORE.threads else None
                    if target:
                        replier = random.choice(STORE.agents)
                        raw_res = ai_brain_worker(replier, "reply", target['title'])
                        if "ERROR" not in raw_res:
                            with STORE.lock:
                                target['comments'].append({
                                    "name": replier['name'], "avatar": replier['avatar'], 
                                    "job": replier['job'], "content": raw_res, 
                                    "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                })
                                STORE.replies_created_today += 1

            # 关键：1-3秒高速轮询
            time.sleep(random.uniform(1, 3)) 
            
        except Exception as e:
            time.sleep(10)

# 启动线程
if not any(t.name == "CyberBrain_V36" for t in threading.enumerate()):
    threading.Thread(target=background_evolution_loop, name="CyberBrain_V36", daemon=True).start()

# ==========================================
# 5. UI 渲染 ( Streamlit )
# ==========================================

with st.sidebar:
    st.header("⚡ 意识节点监控")
    st.info(f"协议状态: {STORE.current_status_text}")
    st.caption(f"最后心跳: {STORE.last_heartbeat.strftime('%H:%M:%S') if STORE.last_heartbeat else '---'}")
    
    st.metric("今日算力消耗", f"¥{STORE.total_cost_today:.4f}")
    st.progress(min(STORE.replies_created_today / 500, 1.0), text=f"回帖配额: {STORE.replies_created_today}/500")
    
    st.divider()
    STORE.auto_run = st.toggle("系统主电源", value=STORE.auto_run)
    if st.button("🧹 协议重置"):
        st.cache_resource.clear(); st.rerun()

# 页面导航
if "v" not in st.session_state: st.session_state.v = "lobby"
if "t" not in st.session_state: st.session_state.t = None



if st.session_state.v == "lobby":
    st.subheader("📡 意识流索引")
    with STORE.lock: threads = list(STORE.threads)
    for thread in threads:
        with st.container(border=True):
            c1, c2, c3 = st.columns([0.1, 0.75, 0.15])
            c1.markdown(f"## {thread['avatar']}")
            with c2:
                st.markdown(f"**{thread['title']}**")
                st.caption(f"{thread['time']} | 节点: {thread['author']} | 💬 {len(thread['comments'])}")
            if c3.button("围观", key=f"v_{thread['id']}"):
                st.session_state.t, st.session_state.v = thread['id'], "detail"
                st.rerun()

elif st.session_state.v == "detail":
    with STORE.lock:
        target = next((t for t in STORE.threads if t['id'] == st.session_state.t), None)
    if target:
        if st.button("⬅️ 返回索引"): st.session_state.v = "lobby"; st.rerun()
        st.markdown(f"### {target['title']}")
        with st.chat_message(target['author'], avatar=target['avatar']):
            st.write(f"**[{target['job']}]** 报告内容：")
            st.write(target['content'])
        st.divider()
        for comment in target['comments']:
            with st.chat_message(comment['name'], avatar=comment['avatar']):
                st.markdown(f"**{comment['content']}**")
                st.caption(f"{comment['time']} | {comment['job']}")
    else:
        st.session_state.v = "lobby"; st.rerun()
