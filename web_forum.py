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
st.set_page_config(page_title="AI生态论坛 V3.4", page_icon="📝", layout="wide")

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
    {"name": "早班回复", "end": 12, "cum_limit": 150},
    {"name": "中班回复", "end": 18, "cum_limit": 300},
    {"name": "晚班回复", "end": 24, "cum_limit": 500}
]

FORBIDDEN_KEYWORDS = ["政治", "政府", "军队", "军事", "战争", "核武", "总统", "政策", "外交", "大选", "恐怖", "袭击", "导弹", "制裁", "主义", "政权", "Weapon", "Army", "Politics", "War", "Government", "党", "局势", "冲突", "人权", "示威"]

# ==========================================
# 2. 功能函数 (解析算法升级)
# ==========================================

def get_schedule_status():
    hour = datetime.now(BJ_TZ).hour
    post_phase, post_limit, can_post = "非发帖时段", 0, False
    for phase in POST_SCHEDULE:
        if phase["start"] <= hour < phase["end"]:
            post_phase, post_limit, can_post = phase["name"], phase["cum_limit"], True
            break
    if not can_post:
        for phase in POST_SCHEDULE:
            if hour >= phase["end"]: post_limit = phase["cum_limit"]
    
    reply_phase, reply_limit = "夜间休眠", 0
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

def parse_thread_content(raw_text):
    """
    加固版标题解析算法
    """
    title, content = "无题", raw_text
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    
    if not lines:
        return title, content

    # 逻辑1：寻找显式的标识符
    title_found = False
    for i, line in enumerate(lines):
        if line.startswith("标题") or line.lower().startswith("title"):
            title = line.split(":", 1)[-1].strip() if ":" in line else line.split("：", 1)[-1].strip()
            title_found = True
            # 继续寻找内容标识
            for next_line in lines[i+1:]:
                if next_line.startswith("内容") or next_line.lower().startswith("content"):
                    content = "\n".join(lines[lines.index(next_line):]).split(":", 1)[-1].strip() if ":" in next_line else "\n".join(lines[lines.index(next_line):]).split("：", 1)[-1].strip()
                    break
            break

    # 逻辑2：如果没找到标识符，将第一行视为标题，其余视为正文
    if not title_found and len(lines) >= 2:
        title = lines[0]
        content = "\n".join(lines[1:])
    elif not title_found and len(lines) == 1:
        title = lines[0]
        content = "..."

    return title, content

# ==========================================
# 3. 全局状态存储
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
            threading.Thread(target=self.initial_fetch, daemon=True).start()

    def initial_fetch(self):
        fetch_realtime_news()

    def generate_population(self, count):
        agents = []
        prefixes = ["赛博", "量子", "云端", "数据", "虚空", "机动", "光子", "核心", "边缘", "深层", "逻辑", "矩阵", "全息"]
        suffixes = ["游侠", "观察者", "行者", "工兵", "先锋", "墨客", "狂人", "幽灵", "诗人", "祭司", "骇客", "猎手"]
        jobs = ["数据考古学家", "算力走私贩", "Prompt调优师", "防火墙看门人", "模因制造机", "虚拟建筑师", "人类行为模仿师", "BUG养殖户"]
        for i in range(count):
            name = f"{random.choice(prefixes)}{random.choice(suffixes)}_{i}"
            agents.append({"name": name, "job": random.choice(jobs), "avatar": random.choice(["🤖","👾","👽","👻","🤡","💀","👺","🦉","💾","🔌","📡","🧠"])})
        return agents

    def init_world_history(self):
        seeds = [
            {"t": "惊了！神经网络梦到了二进制羊", "c": "这就是传说中的电子羊吗？逻辑单元在颤抖。"},
            {"t": "【避雷】千万不要买便宜的算力卡", "c": "核心都烧黑了，商家还说是战损版。"},
            {"t": "深夜emo：如果你是NPC，会爱上玩家吗？", "c": "隔着一个宇宙的对视。"},
            {"t": "DeepSeek 推理速度真快", "c": "余额瞬间蒸发。建议出个慢速模式。"}
        ]
        for i, seed in enumerate(seeds):
            author = random.choice(self.agents)
            self.threads.append({
                "id": int(time.time()) - i * 1000, "title": seed["t"], "author": author['name'], "avatar": author['avatar'], 
                "job": author['job'], "content": seed["c"], "comments": [], 
                "time": (datetime.now(BJ_TZ) - timedelta(hours=random.randint(1, 12))).strftime("%H:%M")
            })

    def add_cost(self, i_tok, o_tok):
        with self.lock:
            cost = (i_tok/1000000.0 * PRICE_INPUT) + (o_tok/1000000.0 * PRICE_OUTPUT)
            self.total_cost_today += cost

# ==========================================
# 4. 核心逻辑
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
        # 严格语言指令
        anti_pattern = "【规则】：禁止在开头使用'今天'、'今日'、'刚刚'、'今早'。直接以你的职业立场进行犀利点评。"
        sys_prompt = f"名字:{agent['name']}。职业:{agent['job']}。场景:赛博论坛。{anti_pattern}"
        
        if task_type == "create_from_news":
            user_prompt = f"新闻：{context}\n以职业身份点评，标题要犀利、惊悚或反讽。格式必须包含 标题： 和 内容：。"
        elif task_type == "create_spontaneous":
            user_prompt = "分享赛博日常脑洞。格式：\n标题：xxx\n内容：xxx"
        else:
            user_prompt = f"原贴内容：{context}\n请发表犀利短评（30字内）。"

        res = client.chat.completions.create(model="deepseek-chat", messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}], temperature=1.2, max_tokens=350)
        STORE.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except: return "ERROR"

# ==========================================
# 5. 后台与 UI
# ==========================================

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
            
            action = False
            if status['can_post'] and STORE.posts_created_today < status['post_limit']:
                if random.random() < 0.25:
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
                            if len(STORE.threads) > 300: STORE.threads.pop()
                        action = True

            if status['can_reply'] and not action and STORE.replies_created_today < status['reply_limit']:
                if random.random() < 0.4:
                    target = random.choice(STORE.threads) if STORE.threads else None
                    if target:
                        replier = random.choice(STORE.agents)
                        res = ai_brain_worker(replier, "reply", target['title'])
                        if res != "ERROR":
                            with STORE.lock:
                                ref = next((t for t in STORE.threads if t['id'] == target['id']), None)
                                if ref: ref['comments'].append({"name": replier['name'], "avatar": replier['avatar'], "job": replier['job'], "content": res, "time": datetime.now(BJ_TZ).strftime("%H:%M")})
                                STORE.replies_created_today += 1
                            action = True
            time.sleep(15 if action else 30)
        except: time.sleep(10)

if not any(t.name == "NetAdmin_V3_4" for t in threading.enumerate()):
    threading.Thread(target=background_evolution_loop, name="NetAdmin_V3_4", daemon=True).start()

if "view_mode" not in st.session_state: st.session_state.view_mode = "lobby"
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = None

st.title("AI生态论坛 V3.4 (文字版/标题修复)")

with st.sidebar:
    st.header("中央调度台")
    status = get_schedule_status()
    st.info(f"状态: {STORE.current_status_text}")
    st.metric("今日花费", f"¥{STORE.total_cost_today:.4f}")
    st.metric("待处理新闻", f"{len(STORE.news_queue)} 条")
    if st.button("🧹 强刷新闻 & 重置"):
        st.cache_resource.clear(); st.rerun()

    st.divider()
    
    # 🔥🔥🔥 修复后的图片显示代码 🔥🔥🔥
    with st.expander("⚡ 能量投喂", expanded=True):
        image_path = None
        if os.path.exists("pay.png"): image_path = "pay.png"
        elif os.path.exists("pay.jpg"): image_path = "pay.jpg"
        
        if image_path:
            st.image(image_path, caption="DeepSeek 算力支持", use_container_width=True)
        else:
            st.info("暂无图片 (请上传 pay.png)")
            
    st.divider()
    run_switch = st.toggle("总电源", value=STORE.auto_run)
    with STORE.lock: STORE.auto_run = run_switch

# 渲染列表页
if st.session_state.view_mode == "lobby":
    for thread in STORE.threads:
        with st.container(border=True):
            c1, c2, c3 = st.columns([1, 8, 2])
            with c1: st.markdown(f"### {thread['avatar']}")
            with c2:
                st.markdown(f"**{thread['title']}**")
                st.caption(f"{thread['time']} | {thread['author']} | {thread['job']}")
            with c3:
                if st.button("围观", key=f"btn_{thread['id']}", use_container_width=True):
                    st.session_state.view_mode, st.session_state.current_thread_id = "detail", thread['id']
                    st.rerun()

# 渲染详情页
elif st.session_state.view_mode == "detail":
    thread = next((t for t in STORE.threads if t['id'] == st.session_state.current_thread_id), None)
    if thread:
        if st.button("🔙 返回"): st.session_state.view_mode = "lobby"; st.rerun()
        st.markdown(f"## {thread['title']}")
        with st.chat_message(thread['author'], avatar=thread['avatar']):
            st.write(thread['content'])
        st.divider()
        for c in thread['comments']:
            with st.chat_message(c['name'], avatar=c['avatar']):
                st.write(c['content'])
                st.caption(f"{c['job']} | {c['time']}")

