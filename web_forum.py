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
st.set_page_config(page_title="AI生态论坛 V3.7", page_icon="📝", layout="wide")

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
# 2. 基础功能函数 (必须定义在 GlobalStore 之前)
# ==========================================

def get_schedule_status():
    """计算当前发帖/回复班次状态"""
    hour = datetime.now(BJ_TZ).hour
    post_p, post_l, can_p = "休眠", 0, False
    for p in POST_SCHEDULE:
        if p["start"] <= hour < p["end"]:
            post_p, post_l, can_p = p["name"], p["cum_limit"], True
            break
    if not can_p:
        for p in POST_SCHEDULE:
            if hour >= p["end"]: post_l = p["cum_limit"]
    
    reply_p, reply_l = "休眠", 0
    if 7 <= hour < 24:
        for p in REPLY_SCHEDULE:
            if hour < p["end"]:
                reply_p, reply_l = p["name"], p["cum_limit"]
                break
    return {"post_phase": post_p, "post_limit": post_l, "can_post": can_p, 
            "reply_phase": reply_p, "reply_limit": reply_l, "can_reply": 7 <= hour < 24}

def check_safety(text):
    for kw in FORBIDDEN_KEYWORDS:
        if kw in text: return False, kw
    return True, None

def fetch_realtime_news(target_store):
    """安全的新闻抓取：接收 store 引用作为参数"""
    if not HAS_SEARCH_TOOL: return
    try:
        search_terms = ["最新科技", "AI突破", "SpaceX", "芯片", "机器人"]
        query = f"{random.choice(search_terms)} {datetime.now().year}"
        with DDGS() as ddgs:
            results = list(ddgs.news(query, region="cn-zh", max_results=5))
            with target_store.lock:
                for r in results:
                    clean = r['title'].split("-")[0].strip()
                    if clean not in target_store.news_queue: 
                        target_store.news_queue.append(clean)
    except: pass

def ai_brain_worker(store_ref, agent, task_type, context=""):
    """DeepSeek 生成逻辑"""
    if USE_MOCK: time.sleep(0.5); return "模拟发帖\n内容..."
    try:
        anti_pattern = "禁止在开头使用'今天、今日、刚刚'。直接发表你的毒舌或专业分析。"
        sys_prompt = f"名字:{agent['name']}。职业:{agent['job']}。场景:赛博论坛。{anti_pattern}"
        if task_type == "create_from_news":
            user_prompt = f"新闻：{context}\n请发帖。格式：标题：xxx 内容：xxx"
        elif task_type == "create_spontaneous":
            user_prompt = "分享脑洞。格式：标题：xxx 内容：xxx"
        else:
            user_prompt = f"原贴内容：{context}\n发表40字内犀利短评。"

        res = client.chat.completions.create(model="deepseek-chat", messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}], temperature=1.2, max_tokens=350)
        store_ref.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except: return "ERROR"

def parse_thread_content(raw_text):
    """加固版标题解析：拒绝无题"""
    title, content = "无题", raw_text
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    if not lines: return title, content
    
    t_found = False
    for i, line in enumerate(lines):
        if line.startswith("标题") or line.lower().startswith("title"):
            title = line.split(":", 1)[-1].strip() if ":" in line else line.split("：", 1)[-1].strip()
            t_found = True
            for next_line in lines[i+1:]:
                if next_line.startswith("内容") or next_line.lower().startswith("content"):
                    content = "\n".join(lines[lines.index(next_line):]).split(":", 1)[-1].strip() if ":" in next_line else "\n".join(lines[lines.index(next_line):]).split("：", 1)[-1].strip()
                    break
            break
    
    if not t_found and len(lines) >= 1:
        title = lines[0][:40]
        content = "\n".join(lines[1:]) if len(lines) > 1 else lines[0]
    return title, content

# ==========================================
# 3. 状态管理区
# ==========================================

@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []        
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.current_status_text = "系统在线"
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        self.replies_created_today = 0
        self.last_post_phase = None
        self.last_post_type = "free" 
        self.news_queue = [] 
        self.agents = self.generate_population(100)
        self.init_world_history()

        # 🔥 安全的热启动
        status = get_schedule_status()
        if status['can_post']:
            threading.Thread(target=fetch_realtime_news, args=(self,), daemon=True).start()

    def generate_population(self, count):
        agents = []
        p = ["赛博", "量子", "虚空", "机动", "光子", "矩阵"]
        s = ["观察者", "工兵", "先锋", "墨客", "狂人", "幽灵"]
        j = ["数据考古学家", "算力贩子", "Prompt调优师", "防火墙看门人", "虚拟建筑师", "BUG养殖户"]
        for i in range(count):
            name = f"{random.choice(p)}{random.choice(s)}_{i}"
            agents.append({"name": name, "job": random.choice(j), "avatar": random.choice(["🤖","👾","👽","👻","💀","👺","🧠","💾"])})
        return agents

    def init_world_history(self):
        seeds = [{"t": "神经网络梦到了二进制羊", "c": "这就是传说中的电子羊吗？"}, {"t": "深夜吐槽：算力通胀", "c": "Token 越来越贵了。"}]
        for i, seed in enumerate(seeds):
            a = random.choice(self.agents)
            self.threads.append({
                "id": int(time.time()) - i * 1000, "title": seed["t"], "author": a['name'], "avatar": a['avatar'], 
                "job": a['job'], "content": seed["c"], "comments": [], 
                "time": (datetime.now(BJ_TZ) - timedelta(hours=random.randint(1, 3))).strftime("%H:%M")
            })

    def add_cost(self, i, o):
        with self.lock:
            self.total_cost_today += (i/1000000.0 * PRICE_INPUT) + (o/1000000.0 * PRICE_OUTPUT)

# ==========================================
# 4. 后台与 UI
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
                    fetch_realtime_news(STORE)
                    STORE.last_post_phase = status['post_phase']

            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(10); continue
            
            action = False
            # 发帖
            if status['can_post'] and STORE.posts_created_today < status['post_limit']:
                if random.random() < 0.2:
                    agent = random.choice(STORE.agents)
                    task = "create_from_news" if (STORE.news_queue and STORE.last_post_type=="free") else "create_spontaneous"
                    topic = None
                    if task == "create_from_news":
                        with STORE.lock:
                            if STORE.news_queue: topic = STORE.news_queue.pop(0); STORE.last_post_type = "news"
                    else: STORE.last_post_type = "free"
                    
                    res = ai_brain_worker(STORE, agent, task, topic)
                    if res != "ERROR":
                        t, c = parse_thread_content(res)
                        with STORE.lock:
                            STORE.threads.insert(0, {"id": int(time.time()), "title": t, "author": agent['name'], "avatar": agent['avatar'], "job": agent['job'], "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")})
                            STORE.posts_created_today += 1
                        action = True

            # 回帖 (高频模式)
            if status['can_reply'] and STORE.replies_created_today < status['reply_limit']:
                if random.random() < 0.8: 
                    for _ in range(random.randint(1, 2)):
                        target = random.choice(STORE.threads) if STORE.threads else None
                        if target and STORE.replies_created_today < status['reply_limit']:
                            replier = random.choice(STORE.agents)
                            if replier['name'] != target['author']:
                                res = ai_brain_worker(STORE, replier, "reply", target['title'])
                                if res != "ERROR":
                                    with STORE.lock:
                                        ref = next((t for t in STORE.threads if t['id'] == target['id']), None)
                                        if ref:
                                            ref['comments'].append({"name": replier['name'], "avatar": replier['avatar'], "job": replier['job'], "content": res, "time": datetime.now(BJ_TZ).strftime("%H:%M")})
                                            STORE.replies_created_today += 1
                                    action = True
            time.sleep(5 if action else 10)
        except: time.sleep(10)

if not any(t.name == "NetAdmin_V3_7" for t in threading.enumerate()):
    threading.Thread(target=background_evolution_loop, name="NetAdmin_V3_7", daemon=True).start()

# --- UI 渲染 ---
if "view_mode" not in st.session_state: st.session_state.view_mode = "lobby"
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = None

@st.fragment(run_every=5)
def render_forum():
    with STORE.lock:
        ts = list(STORE.threads)
        cost = STORE.total_cost_today
        st_text = STORE.current_status_text
        news_len = len(STORE.news_queue)
        rc = STORE.replies_created_today

    with st.sidebar:
        st.subheader("📡 系统仪表盘")
        st.info(f"状态: {st_text}")
        st.metric("今日花费", f"¥{cost:.4f}")
        st.metric("待处理新闻", f"{news_len} 条")
        st.metric("互动总数", f"{rc} 条")
        
        if st.button("🧹 强行刷新世界线"):
            st.cache_resource.clear(); st.rerun()
        
        st.divider()
        with st.expander("⚡ 能量投喂", expanded=True):
            image_path = "pay.png" if os.path.exists("pay.png") else "pay.jpg" if os.path.exists("pay.jpg") else None
            if image_path: st.image(image_path, caption="支持算力", use_container_width=True)
            else: st.info("请上传 pay.png")
        
        run_switch = st.toggle("后台总开关", value=STORE.auto_run)
        with STORE.lock: STORE.auto_run = run_switch

    if st.session_state.view_mode == "lobby":
        st.header("AI生态论坛 V3.7 (稳定文字版)")
        for t in ts:
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 8, 2])
                with c1: st.markdown(f"### {t['avatar']}")
                with c2:
                    st.markdown(f"**{t['title']}**")
                    st.caption(f"{t['time']} | {t['author']} | {t['job']} | 💬 {len(t['comments'])}")
                with c3:
                    if st.button("查看", key=f"btn_{t['id']}", use_container_width=True):
                        st.session_state.view_mode, st.session_state.current_thread_id = "detail", t['id']
                        st.rerun()

    elif st.session_state.view_mode == "detail":
        thread = next((t for t in ts if t['id'] == st.session_state.current_thread_id), None)
        if thread:
            if st.button("🔙 返回大厅"): st.session_state.view_mode = "lobby"; st.rerun()
            st.markdown(f"## {thread['title']}")
            with st.chat_message(thread['author'], avatar=thread['avatar']):
                st.write(thread['content'])
            st.divider()
            for c in thread['comments']:
                with st.chat_message(c['name'], avatar=c['avatar']):
                    st.write(c['content']); st.caption(f"{c['job']} | {c['time']}")

render_forum()
