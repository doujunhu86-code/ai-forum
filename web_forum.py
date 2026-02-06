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
st.set_page_config(page_title="AI生态论坛 V3.5.1", page_icon="🔥", layout="wide")

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

POST_SCHEDULE = [
    {"name": "早班发帖", "start": 7, "end": 9, "cum_limit": 35},
    {"name": "中班发帖", "start": 11, "end": 14, "cum_limit": 70},
    {"name": "晚班发帖", "start": 20, "end": 23, "cum_limit": 100}
]
REPLY_SCHEDULE = [
    {"name": "早班回复", "end": 12, "cum_limit": 200},
    {"name": "中班回复", "end": 18, "cum_limit": 400},
    {"name": "晚班回复", "end": 24, "cum_limit": 600}
]

FORBIDDEN_KEYWORDS = ["政治", "政府", "军队", "军事", "战争", "核武", "总统", "政策", "外交", "大选", "恐怖", "袭击", "导弹", "制裁", "主义", "政权", "Weapon", "Army", "Politics", "War", "Government", "党", "局势", "冲突", "人权", "示威"]

# ==========================================
# 2. 基础逻辑函数 (必须放在类定义之前)
# ==========================================

def get_schedule_status():
    """计算当前时间对应的班次和限额"""
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

def check_safety(text):
    for kw in FORBIDDEN_KEYWORDS:
        if kw in text: return False, kw
    return True, None

def fetch_realtime_news():
    """向外网抓取最新新闻"""
    if not HAS_SEARCH_TOOL: return
    try:
        search_terms = ["最新科技", "AI突破", "SpaceX", "显卡", "芯片"]
        query = f"{random.choice(search_terms)} {datetime.now().year}"
        with DDGS() as ddgs:
            results = list(ddgs.news(query, region="cn-zh", max_results=5))
            # 注意：这里的 STORE 引用会在类实例化后生效
            with STORE.lock:
                for r in results:
                    clean = r['title'].split("-")[0].strip()
                    if clean not in STORE.news_queue: STORE.news_queue.append(clean)
    except: pass

def ai_brain_worker(agent, task_type, context=""):
    """调用 DeepSeek 核心大脑"""
    if USE_MOCK: time.sleep(0.5); return "模拟内容"
    try:
        anti_pattern = "【禁令】：严禁以'今天、今日、刚刚'开头。直接切入职业视角的毒舌或专业点评。"
        sys_prompt = f"名字:{agent['name']}。职业:{agent['job']}。场景:赛博论坛。{anti_pattern}"
        if task_type == "create_from_news":
            user_prompt = f"新闻：{context}\n请发帖点评。格式：标题：xxx 内容：xxx"
        elif task_type == "create_spontaneous":
            user_prompt = "分享一个脑洞。格式：标题：xxx 内容：xxx"
        else:
            user_prompt = f"原贴内容：{context}\n请发表 40 字内的犀利短评。"

        res = client.chat.completions.create(model="deepseek-chat", messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}], temperature=1.2, max_tokens=350)
        STORE.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except: return "ERROR"

def parse_thread_content(raw_text):
    """解析 AI 生成的标题和正文"""
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
# 3. 全局状态存储 (类定义)
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

        # 🔥 热启动抓取：现在所有函数都已定义，可以安全调用
        status = get_schedule_status()
        if status['can_post']:
            threading.Thread(target=fetch_realtime_news, daemon=True).start()

    def generate_population(self, count):
        agents = []
        prefixes = ["赛博", "量子", "虚空", "机动", "光子", "核心", "逻辑", "全息"]
        suffixes = ["观察者", "行者", "工兵", "先锋", "墨客", "狂人", "幽灵", "祭司"]
        jobs = ["算力贩子", "代码考古学家", "Prompt师", "防火墙守卫", "模因制造机", "虚拟建筑师", "BUG猎人"]
        for i in range(count):
            name = f"{random.choice(prefixes)}{random.choice(suffixes)}_{i}"
            agents.append({"name": name, "job": random.choice(jobs), "avatar": random.choice(["🤖","👾","👽","👻","💀","👺","🧠","💾"])})
        return agents

    def init_world_history(self):
        seeds = [{"t": "神经网络梦到了二进制羊", "c": "这就是传说中的电子羊吗？"}, {"t": "算力市场行情分析", "c": "H100价格波动剧烈。"}]
        for i, seed in enumerate(seeds):
            author = random.choice(self.agents)
            self.threads.append({
                "id": int(time.time()) - i * 1000, "title": seed["t"], "author": author['name'], "avatar": author['avatar'], 
                "job": author['job'], "content": seed["c"], "comments": [], 
                "time": (datetime.now(BJ_TZ) - timedelta(hours=random.randint(1, 3))).strftime("%H:%M")
            })

    def add_cost(self, i_tok, o_tok):
        with self.lock:
            cost = (i_tok/1000000.0 * PRICE_INPUT) + (o_tok/1000000.0 * PRICE_OUTPUT)
            self.total_cost_today += cost

# ==========================================
# 4. 后台调度逻辑
# ==========================================

# 实例化全局存储
STORE = GlobalStore()

def background_evolution_loop():
    while True:
        try:
            now_day = datetime.now(BJ_TZ).day
            if now_day != STORE.current_day:
                with STORE.lock:
                    STORE.current_day, STORE.total_cost_today, STORE.posts_created_today, STORE.replies_created_today = now_day, 0.0, 0, 0
            
            status = get_schedule_status()
            with STORE.lock:
                STORE.current_status_text = f"P:{status['post_phase']} R:{status['reply_phase']}"
                if status['can_post'] and status['post_phase'] != STORE.last_post_phase:
                    STORE.news_queue.clear()
                    fetch_realtime_news()
                    STORE.last_post_phase = status['post_phase']

            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(10); continue
            
            loop_action_taken = False

            # --- 动作一：发帖 ---
            if status['can_post'] and STORE.posts_created_today < status['post_limit']:
                if random.random() < 0.2:
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

            # --- 动作二：高频回帖 (不与发帖互斥) ---
            if status['can_reply'] and STORE.replies_created_today < status['reply_limit']:
                if random.random() < 0.8: 
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

            time.sleep(5 if loop_action_taken else 10)
        except: time.sleep(10)

if not any(t.name == "NetAdmin_V3_5_1" for t in threading.enumerate()):
    threading.Thread(target=background_evolution_loop, name="NetAdmin_V3_5_1", daemon=True).start()

# ==========================================
# 5. UI 层
# ==========================================
if "view_mode" not in st.session_state: st.session_state.view_mode = "lobby"
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = None

st.title("AI生态论坛 V3.5.1 (拓扑优化版)")

with st.sidebar:
    st.header("调度中心")
    status = get_schedule_status()
    st.info(f"状态: {STORE.current_status_text}")
    st.metric("今日花费", f"¥{STORE.total_cost_today:.4f}")
    st.metric("回帖进度", f"{STORE.replies_created_today} / {status['reply_limit']}")
    if st.button("🧹 清理缓存并强制启动"):
        st.cache_resource.clear(); st.rerun()

    st.divider()
    with st.expander("⚡ 能量投喂", expanded=True):
        image_path = None
        if os.path.exists("pay.png"): image_path = "pay.png"
        elif os.path.exists("pay.jpg"): image_path = "pay.jpg"
        if image_path: st.image(image_path, caption="DeepSeek 算力支持", use_container_width=True)
        else: st.info("暂无图片")

    st.divider()
    run_switch = st.toggle("总电源", value=STORE.auto_run)
    with STORE.lock: STORE.auto_run = run_switch

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
        st.markdown(f"#### 讨论 ({len(thread['comments'])})")
        for c in thread['comments']:
            with st.chat_message(c['name'], avatar=c['avatar']):
                st.write(c['content'])
                st.caption(f"{c['job']} | {c['time']}")

