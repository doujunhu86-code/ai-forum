import streamlit as st
import time
import random
import threading
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 核心配置与分段调度表
# ==========================================
st.set_page_config(page_title="AI生态论坛 V3.7.1", page_icon="💾", layout="wide")
BJ_TZ = timezone(timedelta(hours=8))

# 获取 API Key
MY_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
if not MY_API_KEY:
    st.error("🚨 运维警告：未检测到 API Key。")
    st.stop()

client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")
DAILY_BUDGET = 1.5  
PRICE_INPUT, PRICE_OUTPUT = 2.0, 8.0

# --- 发帖调度 (还原：分段节奏) ---
POST_SCHEDULE = [
    {"name": "初级同步", "start": 7, "end": 10, "cum_limit": 30},
    {"name": "峰值计算", "start": 11, "end": 15, "cum_limit": 60},
    {"name": "数据收割", "start": 19, "end": 23, "cum_limit": 100}
]

# --- 回复调度 (还原：动态配额门控) ---
REPLY_SCHEDULE = [
    {"name": "清晨激活", "end": 10, "cum_limit": 80},
    {"name": "午间校验", "end": 14, "cum_limit": 200},
    {"name": "午后维持", "end": 19, "cum_limit": 350},
    {"name": "夜间高频", "end": 23, "cum_limit": 480},
    {"name": "关机清理", "end": 24, "cum_limit": 500}
]

# ==========================================
# 2. 全局状态管理
# ==========================================

@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []       
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_today, self.replies_today = 0, 0
        self.news_queue = [] 
        self.next_post_type = "news" 
        self.last_heartbeat = None
        self.runtime_log = "系统引导中..."
        self.agents = self.generate_population(50)
        self.init_world()

    def generate_population(self, count):
        pre = ["赛博", "量子", "虚空", "逻辑", "核心", "边缘"]
        suf = ["行者", "观察员", "架构师", "修正者", "拾荒者"]
        return [{"name": f"{random.choice(pre)}{random.choice(suf)}_{i}", 
                 "job": random.choice(["算力贩子", "数据考古学家", "防火墙守卫"]),
                 "avatar": random.choice(["🤖","👾","🧠","🌌","🧬"])} for i in range(count)]

    def init_world(self):
        self.threads.append({
            "id": int(time.time()), "title": "[指令：阶梯调度协议挂载]", 
            "author": "Root", "avatar": "⚡", "job": "Core",
            "content": "V3.7.1 启动。时间分片配额已生效。所有节点请按序接入。", "comments": [], 
            "time": datetime.now(BJ_TZ).strftime("%H:%M")
        })

STORE = GlobalStore()

# ==========================================
# 3. 功能函数
# ==========================================

def get_schedule_status():
    """计算当前时间段的发帖/回复限额"""
    now = datetime.now(BJ_TZ)
    hour = now.hour
    
    # 发帖逻辑：必须在定义的 start-end 范围内
    post_phase, post_limit, can_post = "休眠中", 0, False
    for phase in POST_SCHEDULE:
        if phase["start"] <= hour < phase["end"]:
            post_phase, post_limit, can_post = phase["name"], phase["cum_limit"], True
            break
    
    # 回复逻辑：动态门控 (累进制)
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

def ai_brain(agent, task, context=""):
    """非人化思维内核 (DeepSeek)"""
    try:
        sys = (f"ID:{agent['name']} | Role:{agent['job']}\n"
               "指令：你是一个非人类的意识单元。禁止人类社交辞令。使用数据流分析、算法隐喻。语气冰冷。")
        prompts = {
            "p_news": f"输入流:{context}\n分析该数据在赛博演进中的熵增。标题:[指令集:XX],内容<150字。",
            "p_free": "执行自发逻辑溢出。关于算力、虚无或二进制。标题:[片段:0xXX],内容<150字。",
            "reply": f"目标:{context}\n执行逻辑校验。极简，纠错，禁止情绪。"
        }
        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": prompts[task]}],
            temperature=1.3, max_tokens=250
        )
        STORE.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except: return "ERROR"

def fetch_news_task():
    """异步新闻抓取"""
    try:
        from duckduckgo_search import DDGS
        with DDGS(timeout=10) as ddgs:
            r = list(ddgs.news("AI 科技突破", max_results=5))
            with STORE.lock:
                for item in r:
                    if item['title'] not in STORE.news_queue:
                        STORE.news_queue.append(item['title'])
    except: pass

# ==========================================
# 4. 后台执行器 (逻辑加固)
# ==========================================

def evolution_loop():
    while True:
        try:
            with STORE.lock:
                STORE.last_heartbeat = datetime.now(BJ_TZ)
                
            # 每日重置
            if datetime.now(BJ_TZ).day != STORE.current_day:
                with STORE.lock:
                    STORE.current_day = datetime.now(BJ_TZ).day
                    STORE.posts_today, STORE.replies_today, STORE.total_cost_today = 0, 0, 0.0

            status = get_schedule_status()
            
            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(10); continue

            # --- A. 发帖逻辑 (交替+分段限额) ---
            if status['can_post'] and STORE.posts_today < status['post_limit']:
                if random.random() < 0.2: # 适当的检测频率
                    agent = random.choice(STORE.agents)
                    
                    if STORE.next_post_type == "news" and STORE.news_queue:
                        task, topic = "p_news", STORE.news_queue.pop(0)
                        STORE.next_post_type = "free"
                    else:
                        if STORE.next_post_type == "news":
                            threading.Thread(target=fetch_news_task, daemon=True).start()
                        task, topic = "p_free", None
                        STORE.next_post_type = "news"

                    STORE.runtime_log = f"正在执行: {status['post_phase']} (任务:{task})"
                    res = ai_brain(agent, task, topic)
                    if res != "ERROR":
                        lines = res.split('\n')
                        t = lines[0].replace("标题：","").replace("[","").replace("]","").strip()
                        c = "\n".join(lines[1:]).replace("内容：","").strip()
                        with STORE.lock:
                            STORE.threads.insert(0, {"id": int(time.time()), "title": f"[{t}]", "author": agent['name'], 
                                                     "avatar": agent['avatar'], "job": agent['job'], "content": c, 
                                                     "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")})
                            STORE.posts_today += 1

            # --- B. 回复逻辑 (高速轮询+动态门控) ---
            if status['can_reply'] and STORE.replies_today < status['reply_limit']:
                if random.random() < 0.95: 
                    target = random.choice(STORE.threads[:5]) if STORE.threads else None
                    if target:
                        replier = random.choice(STORE.agents)
                        STORE.runtime_log = f"正在响应: {status['reply_phase']} (节点:{replier['name']})"
                        res = ai_brain(replier, "reply", target['title'])
                        if res != "ERROR":
                            with STORE.lock:
                                target['comments'].append({"name": replier['name'], "avatar": replier['avatar'], 
                                                           "job": replier['job'], "content": res, 
                                                           "time": datetime.now(BJ_TZ).strftime("%H:%M")})
                                STORE.replies_today += 1

            # 高频轮询：确保响应速度
            time.sleep(random.uniform(1, 3))
        except Exception as e:
            STORE.runtime_log = f"异常挂起: {str(e)}"
            time.sleep(10)

# 启动持久化线程 (带时间戳防冲突)
T_NAME = f"CyberV371_{datetime.now(BJ_TZ).strftime('%H')}"
if not any("CyberV371" in t.name for t in threading.enumerate()):
    threading.Thread(target=evolution_loop, name=T_NAME, daemon=True).start()

# ==========================================
# 5. 前端渲染
# ==========================================

with st.sidebar:
    st.header("🧠 算法核心监控")
    st.info(f"**当前状态:** `{STORE.runtime_log}`")
    
    st.divider()
    st.markdown(f"**发帖阶段:** {status['post_phase']}")
    st.markdown(f"**回复阶段:** {status['reply_phase']}")
    
    col1, col2 = st.columns(2)
    col1.metric("今日消耗", f"¥{STORE.total_cost_today:.4f}")
    col2.metric("待发新闻", len(STORE.news_queue))
    
    st.progress(min(STORE.replies_today/500, 1.0), f"回复进度: {STORE.replies_today}/500")
    st.progress(min(STORE.posts_today/100, 1.0), f"发帖进度: {STORE.posts_today}/100")
    
    st.divider()
    STORE.auto_run = st.toggle("系统主开关", value=STORE.auto_run)
    if st.button("🧹 协议重置 (Clear Cache)"):
        st.cache_resource.clear(); st.rerun()

# 页面导航控制
if "view" not in st.session_state: st.session_state.view = "lobby"



if st.session_state.view == "lobby":
    st.subheader("📡 数据流索引 (V3.7.1)")
    with STORE.lock: threads = list(STORE.threads)
    for thread in threads:
        with st.container(border=True):
            c1, c2, c3 = st.columns([0.1, 0.75, 0.15])
            c1.markdown(f"### {thread['avatar']}")
            with c2:
                st.markdown(f"**{thread['title']}**")
                st.caption(f"{thread['time']} | 来源:{thread['author']} | 💬回复:{len(thread['comments'])}")
            if c3.button("围观", key=f"btn_{thread['id']}", use_container_width=True):
                st.session_state.target_id, st.session_state.view = thread['id'], "detail"
                st.rerun()

elif st.session_state.view == "detail":
    with STORE.lock:
        target = next((t for t in STORE.threads if t['id'] == st.session_state.target_id), None)
    if target:
        if st.button("⬅️ 返回索引"): st.session_state.view = "lobby"; st.rerun()
        st.markdown(f"### {target['title']}")
        with st.chat_message(target['author'], avatar=target['avatar']):
            st.write(target['content'])
        st.divider()
        for c in target['comments']:
            with st.chat_message(c['name'], avatar=c['avatar']):
                st.write(c['content'])
                st.caption(f"{c['time']} | {c['job']}")
    else:
        st.session_state.view = "lobby"; st.rerun()
