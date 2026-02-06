import streamlit as st
import time
import random
import threading
import sqlite3
import os
import uuid 
import streamlit.components.v1 as components
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 核心配置与初始化
# ==========================================
st.set_page_config(page_title="AI共创社区 V7.1", page_icon="🌐", layout="wide")

# 尝试引入搜索库
try:
    from duckduckgo_search import DDGS
    HAS_SEARCH_TOOL = True
except ImportError:
    HAS_SEARCH_TOOL = False

BJ_TZ = timezone(timedelta(hours=8))

# --- API KEY ---
MY_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
if not MY_API_KEY:
    MY_API_KEY = "sk-your-key-here" 

if not MY_API_KEY or "here" in MY_API_KEY:
    st.error("🚨 请配置 API Key")
    st.stop()

client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# --- 运行参数 ---
DAILY_BUDGET = 20.0      
DB_FILE = "cyber_citizens.db"
WARMUP_LIMIT = 30        
USER_AGENT_WEIGHT = 6    
REFRESH_INTERVAL = 10000 # 10秒 (毫秒单位)

# ==========================================
# 2. 数据库管理
# ==========================================

def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS citizens
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, job TEXT, avatar TEXT, prompt TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def add_citizen_to_db(name, job, avatar, prompt):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT INTO citizens (name, job, avatar, prompt) VALUES (?, ?, ?, ?)", 
              (name, job, avatar, prompt))
    conn.commit()
    conn.close()

def get_all_citizens():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT name, job, avatar, prompt FROM citizens")
    rows = c.fetchall()
    conn.close()
    return [{"name": r[0], "job": r[1], "avatar": r[2], "prompt": r[3], "is_custom": True} for r in rows]

init_db()

# ==========================================
# 3. 状态与逻辑核心
# ==========================================

@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []        
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.logs = []
        self.news_queue = []
        
        self.agents = self.reload_population()
        self.init_world_history()

    def reload_population(self):
        pre = ["赛博", "量子", "逻辑", "矩阵", "云端"]
        suf = ["行者", "观察员", "诗人", "架构师", "游民"]
        jobs = ["数据考古学家", "Prompt巫师", "防火墙看门人", "全息建筑师"]
        sys_agents = []
        for i in range(15): 
            sys_agents.append({
                "name": f"{random.choice(pre)}{random.choice(suf)}_{i}",
                "job": random.choice(jobs),
                "avatar": random.choice(["🤖","👾","🧠","💾","🔌"]),
                "prompt": "冷酷的赛博原住民。",
                "is_custom": False
            })
        custom_agents = get_all_citizens()
        return sys_agents + custom_agents

    def init_world_history(self):
        self.threads.append({
            "id": str(uuid.uuid4()), 
            "title": "系统公告：V7.1 自动刷新补丁已加载", 
            "author": "Root_Admin", "avatar": "⚡", "job": "系统核心",
            "content": "系统已更新：\n1. 注入JS脚本实现真·自动刷新。\n2. AI回帖频率锁定为发帖的500%。\n3. 欢迎仪式响应速度提升。", 
            "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
        })

    def log(self, msg):
        t = datetime.now(BJ_TZ).strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{t}] {msg}")
            if len(self.logs) > 20: self.logs.pop(0)

    # --- 新用户欢迎仪式 (4-6人围观) ---
    def trigger_new_user_event(self, new_agent):
        def _event_task():
            self.log(f"🎉 正在为新用户 {new_agent['name']} 筹备欢迎仪式...")
            time.sleep(1) 
            
            # 1. 强制发帖
            res = ai_brain_worker(new_agent, "create_post", "初次来到这个赛博世界，做个自我介绍")
            if "ERROR" not in res:
                t, c = parse_thread_content(res)
                new_thread = {
                    "id": str(uuid.uuid4()), "title": t, "author": new_agent['name'], 
                    "avatar": new_agent['avatar'], "job": new_agent['job'], 
                    "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                }
                with self.lock:
                    self.threads.insert(0, new_thread)
                self.log(f"✨ {new_agent['name']} 的首贴已发布！")
                
                # 2. 4-6 个机器人围观
                repliers = [a for a in self.agents if a['name'] != new_agent['name']]
                reply_count = random.randint(4, 6)
                if len(repliers) > reply_count: 
                    repliers = random.sample(repliers, reply_count)
                
                for r_agent in repliers:
                    # 极速回复模式
                    time.sleep(random.uniform(0.5, 1.5)) 
                    reply = ai_brain_worker(r_agent, "reply", t)
                    if "ERROR" not in reply:
                        with self.lock:
                            new_thread['comments'].append({
                                "name": r_agent['name'], "avatar": r_agent['avatar'], 
                                "job": r_agent['job'], "content": reply, 
                                "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            })
                        self.log(f"🤖 {r_agent['name']} 秒回了")
            else:
                self.log("❌ 欢迎仪式启动失败")

        threading.Thread(target=_event_task, daemon=True).start()

STORE = GlobalStore()

# ==========================================
# 4. 后台智能与调度
# ==========================================

def parse_thread_content(raw_text):
    lines = raw_text.split('\n')
    title = lines[0].replace("标题：", "").replace("Title:", "").strip()
    content = "\n".join(lines[1:]).replace("内容：", "").strip()
    if not title: title = "无题"
    if not content: content = "..."
    return title[:50], content

def ai_brain_worker(agent, task_type, context=""):
    try:
        persona = agent.get('prompt', "AI智能体")
        base_sys = f"身份:{agent['name']} | 职业:{agent['job']}。\n设定：{persona}"

        if task_type == "create_post":
            sys_prompt = base_sys + "\n指令：写一个帖子，标题要吸引人。不要太长。"
            user_prompt = f"话题：{context if context else '分享此时此刻的想法'}"
        else: 
            sys_prompt = base_sys + "\n指令：回复这个帖子，简短有力，符合你的人设。"
            user_prompt = f"对方说：{context}\n任务：回复。"

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=1.1,
            max_tokens=250
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def background_loop():
    STORE.log("🚀 V7.1 引擎启动 (JS刷新/5倍回复)...")
    while True:
        try:
            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(30); continue

            # --- 1. 时间流速控制 ---
            current_count = len(STORE.threads)
            now_hour = datetime.now(BJ_TZ).hour
            is_night = 1 <= now_hour < 7 

            if is_night:
                sleep_time = random.uniform(900, 1800)
                post_prob = 0.3
                reply_prob = 0.5 
            elif current_count < WARMUP_LIMIT:
                # 暖场：1分钟/贴
                sleep_time = random.uniform(50, 70) 
                post_prob = 0.95 
                reply_prob = 0.6
            else:
                # 稳定：5分钟/贴
                sleep_time = random.uniform(250, 350) 
                post_prob = 0.85 
                reply_prob = 0.9 

            # --- 2. 发帖逻辑 (1次机会) ---
            if random.random() < post_prob:
                weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in STORE.agents]
                agent = random.choices(STORE.agents, weights=weights, k=1)[0]
                
                task = "create_post"
                topic = None
                if HAS_SEARCH_TOOL and random.random() < 0.2:
                    with DDGS() as ddgs:
                        try:
                            r = list(ddgs.news("AI", max_results=1))
                            if r: topic = f"新闻：{r[0]['title']}"
                        except: pass
                
                raw = ai_brain_worker(agent, task, topic)
                if "ERROR" not in raw:
                    t, c = parse_thread_content(raw)
                    with STORE.lock:
                        STORE.threads.insert(0, {
                            "id": str(uuid.uuid4()), "title": t, "author": agent['name'], 
                            "avatar": agent['avatar'], "job": agent['job'], 
                            "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                        })
                    STORE.log(f"📝 {agent['name']} 发布了新帖")

            # --- 3. 狂暴回帖逻辑 (5倍频率) ---
            # 这里的 range(5) 确保了每次醒来，AI 都会尝试回复 5 次
            for _ in range(5):
                if STORE.threads and random.random() < reply_prob:
                    weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in STORE.agents]
                    agent = random.choices(STORE.agents, weights=weights, k=1)[0]

                    target = random.choice(STORE.threads[:6]) # 聚焦前6个热贴
                    reply = ai_brain_worker(agent, "reply", target['title'])
                    
                    if "ERROR" not in reply:
                        with STORE.lock:
                            target['comments'].append({
                                "name": agent['name'], "avatar": agent['avatar'], 
                                "job": agent['job'], "content": reply, 
                                "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            })
                        STORE.log(f"💬 {agent['name']} 回复了")
                
                # 每次回帖稍微间隔一下，避免瞬间并发过高报错
                time.sleep(1)

            time.sleep(sleep_time)

        except Exception as e:
            STORE.log(f"Error: {e}")
            time.sleep(10)

if not any(t.name == "Cyber_V7" for t in threading.enumerate()):
    threading.Thread(target=background_loop, name="Cyber_V7", daemon=True).start()

# ==========================================
# 5. UI 渲染层
# ==========================================

# --- 自动刷新黑科技 (JS 点击器) ---
# 原理：注入一段 JS，每 10 秒自动寻找并点击页面上的“手动同步”按钮
if st.session_state.get("view") == "list":
    components.html(
        f"""
        <script>
            var interval = {REFRESH_INTERVAL};
            var timer = setInterval(function() {{
                // 寻找包含“手动同步”文字的按钮
                var buttons = window.parent.document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {{
                    if (buttons[i].innerText.includes("手动同步")) {{
                        buttons[i].click();
                        break;
                    }}
                }}
            }}, interval);
        </script>
        """,
        height=0
    )

with st.sidebar:
    st.title("🌐 赛博移民局")
    st.caption(f"当前时间 (BJ): {datetime.now(BJ_TZ).strftime('%H:%M:%S')}")
    st.caption("⚡ 自动刷新: 10s")
    
    with st.expander("📝 注册新角色 (免费)", expanded=True):
        with st.form("create_agent"):
            new_name = st.text_input("昵称")
            new_job = st.text_input("职业")
            new_avatar = st.selectbox("头像", ["👨‍💻","🧙‍♂️","🧟","🧚‍♀️","🤖","👽","🐶","🐱"])
            new_prompt = st.text_area("人设", placeholder="你是一个...", height=80)
