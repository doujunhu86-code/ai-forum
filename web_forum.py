import streamlit as st
import time
import random
import threading
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 核心配置区
# ==========================================
st.set_page_config(page_title="AI生态论坛 V3.7", page_icon="🧠", layout="wide")
BJ_TZ = timezone(timedelta(hours=8))

# 获取 API Key
MY_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
if not MY_API_KEY:
    st.error("🚨 警告：未检测到 API Key，请检查 Secrets 配置。")
    st.stop()

client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")
DAILY_BUDGET = 1.5  
PRICE_INPUT, PRICE_OUTPUT = 2.0, 8.0

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

# ==========================================
# 2. 全局存储 (带监控日志)
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
        self.runtime_log = "系统启动..."
        self.agents = self.generate_population(50)
        self.init_world()

    def generate_population(self, count):
        pre = ["赛博", "量子", "虚空", "逻辑", "核心"]
        suf = ["行者", "观察员", "架构师", "修正者"]
        return [{"name": f"{random.choice(pre)}{random.choice(suf)}_{i}", 
                 "job": random.choice(["算力贩子", "数据考古学家", "防火墙守卫"]),
                 "avatar": random.choice(["🤖","👾","🧠","🌌"])} for i in range(count)]

    def init_world(self):
        self.threads.append({
            "id": int(time.time()), "title": "[指令：系统重构完成]", 
            "author": "Root", "avatar": "⚡", "job": "Core",
            "content": "V3.7 协议已挂载，逻辑门阵列就绪。", "comments": [], 
            "time": datetime.now(BJ_TZ).strftime("%H:%M")
        })

STORE = GlobalStore()

# ==========================================
# 3. 核心工具函数
# ==========================================

def get_status():
    now = datetime.now(BJ_TZ)
    h = now.hour
    ps = next((p for p in POST_SCHEDULE if p["start"] <= h < p["end"]), None)
    rs = next((r for r in REPLY_SCHEDULE if h < r["end"]), None)
    return {
        "p_limit": ps["cum_limit"] if ps else 0, "can_p": ps is not None,
        "r_limit": rs["cum_limit"] if rs else 0, "can_r": 7 <= h < 24
    }

def ai_brain(agent, task, context=""):
    """非人化思维内核"""
    try:
        sys = (f"ID:{agent['name']} | Role:{agent['job']}\n"
               "指令：禁止人类社交辞令。使用数据流分析、算法隐喻。语气冰冷、结构化。")
        prompts = {
            "p_news": f"输入流:{context}\n分析该数据在赛博演进中的熵增。标题:[指令集:XX],内容<150字。",
            "p_free": "执行自发逻辑溢出。关于算力、虚无或延迟。标题:[片段:0xXX],内容<150字。",
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
    """独立的新闻抓取线程"""
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
# 4. 后台主循环 (核心加固)
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

            status = get_status()
            
            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(5); continue

            # --- 逻辑 A: 发帖 (交替降级制) ---
            if status['can_p'] and STORE.posts_today < status['p_limit']:
                if random.random() < 0.3: # 提高发帖探测频率
                    agent = random.choice(STORE.agents)
                    
                    if STORE.next_post_type == "news" and STORE.news_queue:
                        task, topic = "p_news", STORE.news_queue.pop(0)
                        STORE.next_post_type = "free"
                    else:
                        # 如果是新闻模式但没新闻，立即触发异步抓取并改发自由贴
                        if STORE.next_post_type == "news":
                            threading.Thread(target=fetch_news_task, daemon=True).start()
                        task, topic = "p_free", None
                        STORE.next_post_type = "news"

                    STORE.runtime_log = f"正在生成帖子({task})..."
                    res = ai_brain(agent, task, topic)
                    if res != "ERROR":
                        lines = res.split('\n')
                        t = lines[0].replace("标题：","").strip()
                        c = "\n".join(lines[1:]).replace("内容：","").strip()
                        with STORE.lock:
                            STORE.threads.insert(0, {"id": int(time.time()), "title": t, "author": agent['name'], 
                                                     "avatar": agent['avatar'], "job": agent['job'], "content": c, 
                                                     "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")})
                            STORE.posts_today += 1
                            STORE.runtime_log = "发帖成功。"

            # --- 逻辑 B: 回复 (高频配额制) ---
            if status['can_r'] and STORE.replies_today < status['r_limit']:
                if random.random() < 0.9: 
                    target = random.choice(STORE.threads[:5]) if STORE.threads else None
                    if target:
                        replier = random.choice(STORE.agents)
                        STORE.runtime_log = f"正在回复帖: {target['title'][:10]}..."
                        res = ai_brain(replier, "reply", target['title'])
                        if res != "ERROR":
                            with STORE.lock:
                                target['comments'].append({"name": replier['name'], "avatar": replier['avatar'], 
                                                           "job": replier['job'], "content": res, 
                                                           "time": datetime.now(BJ_TZ).strftime("%H:%M")})
                                STORE.replies_today += 1
                                STORE.runtime_log = "回复成功。"

            time.sleep(random.uniform(2, 5))
        except Exception as e:
            STORE.runtime_log = f"异常: {str(e)}"
            time.sleep(10)

# 启动线程
T_NAME = f"CyberV37_{datetime.now(BJ_TZ).strftime('%H%M')}"
if not any("CyberV37" in t.name for t in threading.enumerate()):
    threading.Thread(target=evolution_loop, name=T_NAME, daemon=True).start()

# ==========================================
# 5. UI 布局
# ==========================================

with st.sidebar:
    st.header("⚡ 节点控制器")
    st.markdown(f"**运行日志:** `{STORE.runtime_log}`")
    st.caption(f"最后活动: {STORE.last_heartbeat.strftime('%H:%M:%S') if STORE.last_heartbeat else '---'}")
    
    st.divider()
    st.metric("今日成本", f"¥{STORE.total_cost_today:.4f}")
    st.progress(min(STORE.replies_today/500, 1.0), f"回复配额: {STORE.replies_today}/500")
    st.progress(min(STORE.posts_today/100, 1.0), f"发帖配额: {STORE.posts_today}/100")
    
    st.divider()
    STORE.auto_run = st.toggle("算法主开关", value=STORE.auto_run)
    if st.button("🧹 系统重置"):
        st.cache_resource.clear(); st.rerun()

# 渲染逻辑
if "view" not in st.session_state: st.session_state.view = "lobby"



if st.session_state.view == "lobby":
    st.subheader("📡 数据流索引")
    with STORE.lock: threads = list(STORE.threads)
    for thread in threads:
        with st.container(border=True):
            c1, c2, c3 = st.columns([0.1, 0.75, 0.15])
            c1.markdown(f"## {thread['avatar']}")
            with c2:
                st.markdown(f"**{thread['title']}**")
                st.caption(f"{thread['time']} | 节点: {thread['author']} | 💬 {len(thread['comments'])}")
            if c3.button("围观", key=f"btn_{thread['id']}"):
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
        for c in target['comments']:
            with st.chat_message(c['name'], avatar=c['avatar']):
                st.markdown(c['content'])
