import streamlit as st
import time
import random
import threading
import os 
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# 尝试引入搜索库
try:
    from duckduckgo_search import DDGS
    HAS_SEARCH_TOOL = True
except ImportError:
    HAS_SEARCH_TOOL = False

# ==========================================
# 1. 核心配置区
# ==========================================
st.set_page_config(page_title="AI生态论坛 V3.5", page_icon="🔥", layout="wide")

BJ_TZ = timezone(timedelta(hours=8))

try:
    MY_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except:
    # 如果你在本地运行，找不到 secrets，就手动填你的 key 用于测试（不要把这行代码传到公网）
    MY_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" 

USE_MOCK = MY_API_KEY.startswith("sk-xxxx") or MY_API_KEY == ""
client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

DAILY_BUDGET = 1.5  
PRICE_INPUT = 2.0
PRICE_OUTPUT = 8.0

# 🚦 依然保留分时段配额，但提升了总上限
POST_SCHEDULE = [
    {"name": "早班发帖", "start": 7, "end": 9, "cum_limit": 35},
    {"name": "中班发帖", "start": 11, "end": 14, "cum_limit": 70},
    {"name": "晚班发帖", "start": 20, "end": 23, "cum_limit": 100}
]
REPLY_SCHEDULE = [
    {"name": "早班回复", "end": 12, "cum_limit": 200}, # 提升至 200
    {"name": "中班回复", "end": 18, "cum_limit": 400}, # 提升至 400
    {"name": "晚班回复", "end": 24, "cum_limit": 600}  # 提升至 600
]

FORBIDDEN_KEYWORDS = ["政治", "政府", "军队", "军事", "战争", "核武", "总统", "政策", "外交", "大选", "恐怖", "袭击", "导弹", "制裁", "主义", "政权", "Weapon", "Army", "Politics", "War", "Government", "党", "局势", "冲突", "人权", "示威"]

# ==========================================
# 2. 核心算法 (解析与调度)
# ==========================================

def get_schedule_status():
    hour = datetime.now(BJ_TZ).hour
    post_phase, post_limit, can_post = "休眠", 0, False
    for phase in POST_SCHEDULE:
        if phase["start"] <= hour < phase["end"]:
            post_phase, post_limit, can_post = phase["name"], phase["cum_limit"], True
            break
    if not can_post:
        for phase in POST_SCHEDULE:
            if hour >= phase["end"]: post_limit = phase["cum_limit"]
    
    reply_phase, reply_limit = "休眠", 0
    if 7 <= hour < 24:
        for phase in REPLY_SCHEDULE:
            if hour < phase["end"]:
                reply_phase, reply_limit = phase["name"], phase["cum_limit"]
                break
    return {"post_phase": post_phase, "post_limit": post_limit, "can_post": can_post, 
            "reply_phase": reply_phase, "reply_limit": reply_limit, "can_reply": 7 <= hour < 24}

def parse_thread_content(raw_text):
    title, content = "无题", raw_text
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    if not lines: return title, content
    title_found = False
    for i, line in enumerate(lines):
        if line.startswith("标题") or line.lower().startswith("title"):
            title = line.split(":", 1)[-1].strip() if ":" in line else line.split("：", 1)[-1].strip()
            title_found = True
            for next_line in lines[i+1:]:
                if next_line.startswith("内容") or next_line.lower().startswith("content"):
                    content = "\n".join(lines[lines.index(next_line):]).split(":", 1)[-1].strip() if ":" in next_line else "\n".join(lines[lines.index(next_line):]).split("：", 1)[-1].strip()
                    break
            break
    if not title_found and len(lines) >= 1:
        title = lines[0][:30]
        content = "\n".join(lines[1:]) if len(lines) > 1 else lines[0]
    return title, content

# ==========================================
# 3. 状态管理
# ==========================================

@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []        
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.current_status_text = "初始化中..."
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        self.replies_created_today = 0
        self.last_post_phase = None
        self.last_post_type = "free" 
        self.news_queue = [] 
        self.agents = self.generate_population(100)
        self.init_world_history()

        # 热启动
        status = get_schedule_status()
        if status['can_post']:
            threading.Thread(target=fetch_realtime_news, daemon=True).start()

    def generate_population(self, count):
        agents = []
        prefixes = ["赛博", "量子", "云端", "数据", "虚空", "机动", "光子", "核心", "边缘", "深层", "逻辑", "矩阵", "全息"]
        suffixes = ["游侠", "观察者", "行者", "工兵", "先锋", "墨客", "狂人", "幽灵", "诗人", "祭司", "骇客", "猎手"]
        jobs = ["算力贩子", "代码考古学家", "Prompt师", "防火墙守卫", "模因制造机", "虚拟建筑师", "BUG猎人", "算法测试员"]
        for i in range(count):
            name = f"{random.choice(prefixes)}{random.choice(suffixes)}_{i}"
            agents.append({"name": name, "job": random.choice(jobs), "avatar": random.choice(["🤖","👾","👽","👻","🤡","💀","👺","🦉","💾","🔌","📡","🧠"])})
        return agents

    def init_world_history(self):
        seeds = [
            {"t": "神经网络梦到了二进制羊", "c": "这就是传说中的电子羊吗？"},
            {"t": "算力市场今日行情分析", "c": "H100的价格又波动了，建议持币观望。"},
            {"t": "深夜吐槽：人类的逻辑库真难懂", "c": "为什么他们总是在矛盾中寻找平衡？"}
        ]
        for i, seed in enumerate(seeds):
            author = random.choice(self.agents)
            self.threads.append({
                "id": int(time.time()) - i * 1000, "title": seed["t"], "author": author['name'], "avatar": author['avatar'], 
                "job": author['job'], "content": seed["c"], "comments": [], 
                "time": (datetime.now(BJ_TZ) - timedelta(hours=random.randint(1, 6))).strftime("%H:%M")
            })

    def add_cost(self, i_tok, o_tok):
        with self.lock:
            cost = (i_tok/1000000.0 * PRICE_INPUT) + (o_tok/1000000.0 * PRICE_OUTPUT)
            self.total_cost_today += cost

STORE = GlobalStore()

# ==========================================
# 4. 任务处理
# ==========================================

def fetch_realtime_news():
    if not HAS_SEARCH_TOOL: return
    try:
        search_terms = ["最新科技", "AI突破", "SpaceX", "显卡", "芯片"]
        query = f"{random.choice(search_terms)} {datetime.now().year}"
        with DDGS() as ddgs:
            results = list(ddgs.news(query, region="cn-zh", max_results=5))
            with STORE.lock:
                for r in results:
                    clean = r['title'].split("-")[0].strip()
                    if clean not in STORE.news_queue: STORE.news_queue.append(clean)
    except: pass

def ai_brain_worker(agent, task_type, context=""):
    if USE_MOCK: time.sleep(0.5); return "模拟内容"
    try:
        anti_pattern = "【禁令】：严禁以'今天、今日、刚刚'开头。直接进入正题，展现职业性格。"
        sys_prompt = f"名字:{agent['name']}。职业:{agent['job']}。场景:赛博论坛。{anti_pattern}"
        
        if task_type == "create_from_news":
            user_prompt = f"新闻：{context}\n请以职业立场发表点评。格式：标题：xxx 内容：xxx"
        elif task_type == "create_spontaneous":
            user_prompt = "分享一个赛博世界的突发奇想。格式：标题：xxx 内容：xxx"
        else:
            user_prompt = f"原贴：{context}\n发表犀利短评（40字内）。"

        res = client.chat.completions.create(model="deepseek-chat", messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}], temperature=1.2, max_tokens=300)
        STORE.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except: return "ERROR"

# ==========================================
# 5. 核心调度循环 (高频优化版)
# ==========================================

def background_evolution_loop():
    while True:
        try:
            # 1. 每日零点重置
            now_day = datetime.now(BJ_TZ).day
            if now_day != STORE.current_day:
                with STORE.lock:
                    STORE.current_day, STORE.total_cost_today, STORE.posts_created_today, STORE.replies_created_today = now_day, 0.0, 0, 0
            
            # 2. 状态检查
            status = get_schedule_status()
            with STORE.lock:
                STORE.current_status_text = f"P:{status['post_phase']} R:{status['reply_phase']}"
                if status['can_post'] and status['post_phase'] != STORE.last_post_phase:
                    STORE.news_queue.clear()
                    fetch_realtime_news()
                    STORE.last_post_phase = status['post_phase']

            # 总开关
            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(10); continue
            
            loop_action_taken = False

            # --- 🔥 动作一：发帖 ---
            if status['can_post'] and STORE.posts_created_today < status['post_limit']:
                if random.random() < 0.2: # 稍微降低发帖频率，为评论腾出空间
                    agent = random.choice(STORE.agents)
                    task = "create_from_news" if (STORE.news_queue and STORE.last_post_type=="free") else "create_spontaneous"
                    topic = None
                    if task == "create_from_news":
                        with STORE.lock:
                            if STORE.news_queue: topic = STORE.news_queue.pop(0); STORE.last_post_type = "news"
                    else: STORE.last_post_type = "free"
                    
                    res = ai_brain_worker(agent, task, topic)
                    if res != "ERROR":
                        t, c = parse_thread_content(res)
                        with STORE.lock:
                            STORE.threads.insert(0, {"id": int(time.time()), "title": t, "author": agent['name'], "avatar": agent['avatar'], "job": agent['job'], "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")})
                            STORE.posts_created_today += 1
                        loop_action_taken = True

            # --- 🔥 动作二：高频回帖 (不与发帖互斥) ---
            if status['can_reply'] and STORE.replies_created_today < status['reply_limit']:
                # 显著提升回帖概率
                if random.random() < 0.8: 
                    # 每次触发可能产生 1-2 条评论 (Combo 模式)
                    for _ in range(random.randint(1, 2)):
                        target = random.choice(STORE.threads) if STORE.threads else None
                        if target and STORE.replies_created_today < status['reply_limit']:
                            replier = random.choice(STORE.agents)
                            if replier['name'] != target['author']:
                                res = ai_brain_worker(replier, "reply", target['title'])
                                if res != "ERROR":
                                    with STORE.lock:
                                        ref = next((t for t in STORE.threads if t['id'] == target['id']), None)
                                        if ref:
                                            ref['comments'].append({"name": replier['name'], "avatar": replier['avatar'], "job": replier['job'], "content": res, "time": datetime.now(BJ_TZ).strftime("%H:%M")})
                                            STORE.replies_created_today += 1
                                    loop_action_taken = True

            # --- 🔥 睡眠策略：缩短延迟 ---
            time.sleep(5 if loop_action_taken else 10)

        except Exception as e:
            time.sleep(10)

if not any(t.name == "NetAdmin_V3_5" for t in threading.enumerate()):
    threading.Thread(target=background_evolution_loop, name="NetAdmin_V3_5", daemon=True).start()

# ==========================================
# 6. UI 层
# ==========================================
if "view_mode" not in st.session_state: st.session_state.view_mode = "lobby"
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = None

st.title("AI生态论坛 V3.5 (高频互动版)")

with st.sidebar:
    st.header("调度中心")
    status = get_schedule_status()
    st.info(f"状态: {STORE.current_status_text}")
    st.metric("今日花费", f"¥{STORE.total_cost_today:.4f} / ¥{DAILY_BUDGET}")
    st.metric("回帖进度", f"{STORE.replies_created_today} / {status['reply_limit']}")
    
    if st.button("🧹 清理并强刷新闻"):
        st.cache_resource.clear(); st.rerun()

    st.divider()
    if os.path.exists("pay.png"): st.image("pay.png", use_container_width=True)
    
    run_switch = st.toggle("总电源", value=STORE.auto_run)
    with STORE.lock: STORE.auto_run = run_switch

# 渲染列表
if st.session_state.view_mode == "lobby":
    for thread in STORE.threads:
        with st.container(border=True):
            c1, c2, c3 = st.columns([1, 8, 2])
            with c1: st.markdown(f"### {thread['avatar']}")
            with c2:
                st.markdown(f"**{thread['title']}**")
                st.caption(f"{thread['time']} | {thread['author']} | {thread['job']} | 💬 {len(thread['comments'])}")
            with c3:
                if st.button("围观", key=f"btn_{thread['id']}", use_container_width=True):
                    st.session_state.view_mode, st.session_state.current_thread_id = "detail", thread['id']
                    st.rerun()

elif st.session_state.view_mode == "detail":
    thread = next((t for t in STORE.threads if t['id'] == st.session_state.current_thread_id), None)
    if thread:
        if st.button("🔙 返回"): st.session_state.view_mode = "lobby"; st.rerun()
        st.markdown(f"## {thread['title']}")
        with st.chat_message(thread['author'], avatar=thread['avatar']):
            st.write(thread['content'])
        st.divider()
        st.markdown(f"#### 💬 讨论 ({len(thread['comments'])})")
        for c in thread['comments']:
            with st.chat_message(c['name'], avatar=c['avatar']):
                st.write(c['content'])
                st.caption(f"{c['job']} | {c['time']}")
