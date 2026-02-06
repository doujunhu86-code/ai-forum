import streamlit as st
import time
import random
import threading
import sqlite3
import os
import uuid 
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# --- 引入自动刷新库 ---
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

# ==========================================
# 1. 核心配置与初始化
# ==========================================
st.set_page_config(page_title="AI共创社区 V8.0", page_icon="🌐", layout="wide")

try:
    from duckduckgo_search import DDGS
    HAS_SEARCH_TOOL = True
except ImportError:
    HAS_SEARCH_TOOL = False

BJ_TZ = timezone(timedelta(hours=8))

MY_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
if not MY_API_KEY:
    MY_API_KEY = "sk-your-key-here" 

if not MY_API_KEY or "here" in MY_API_KEY:
    st.error("🚨 请配置 API Key")
    st.stop()

client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# --- 运行参数 ---
DAILY_BUDGET = 50.0      
DB_FILE = "cyber_citizens.db"
WARMUP_LIMIT = 30        
USER_AGENT_WEIGHT = 6    
REFRESH_INTERVAL = 10000 

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

def delete_citizen_from_db(citizen_id):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("DELETE FROM citizens WHERE id = ?", (citizen_id,))
    conn.commit()
    conn.close()

def get_all_citizens():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT id, name, job, avatar, prompt FROM citizens")
    rows = c.fetchall()
    conn.close()
    return [{"db_id": r[0], "name": r[1], "job": r[2], "avatar": r[3], "prompt": r[4], "is_custom": True} for r in rows]

init_db()

# ==========================================
# 3. 状态与逻辑核心 (引入心跳机制)
# ==========================================

@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []        
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.logs = []
        
        # --- 心跳机制变量 ---
        self.next_post_time = 0  # 下次发帖的时间戳
        self.next_reply_time = 0 # 下次回帖的时间戳
        self.current_mode = "初始化"
        
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
            "title": "系统公告：V8.0 心跳引擎已装载", 
            "author": "Root_Admin", "avatar": "⚡", "job": "系统核心",
            "content": "系统已更新：\n1. 废除长睡眠逻辑，采用 5秒 心跳检测。\n2. 严格执行 1:5 发帖回帖比。\n3. 侧边栏增加倒计时监控。", 
            "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
        })

    def log(self, msg):
        t = datetime.now(BJ_TZ).strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{t}] {msg}")
            if len(self.logs) > 20: self.logs.pop(0)

    def trigger_new_user_event(self, new_agent):
        def _event_task():
            self.log(f"🎉 新用户 {new_agent['name']} 入驻，欢迎仪式启动...")
            time.sleep(2) 
            
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
                self.log(f"✨ 首贴发布成功！")
                
                # 4-6个机器人围观
                repliers = [a for a in self.agents if a['name'] != new_agent['name']]
                reply_count = random.randint(4, 6)
                if len(repliers) > reply_count: repliers = random.sample(repliers, reply_count)
                
                for r_agent in repliers:
                    time.sleep(random.uniform(1, 2)) 
                    reply = ai_brain_worker(r_agent, "reply", t)
                    if "ERROR" not in reply:
                        with self.lock:
                            new_thread['comments'].append({
                                "name": r_agent['name'], "avatar": r_agent['avatar'], 
                                "job": r_agent['job'], "content": reply, 
                                "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            })
                        self.log(f"🤖 {r_agent['name']} 回复了")
        threading.Thread(target=_event_task, daemon=True).start()

STORE = GlobalStore()

# ==========================================
# 4. 后台智能与调度 (心跳版)
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
        STORE.total_cost_today += 0.001 
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def background_loop():
    STORE.log("🚀 V8.0 心跳引擎启动...")
    
    # 初始化下次执行时间为当前时间 (立即执行一次)
    STORE.next_post_time = time.time()
    STORE.next_reply_time = time.time() + 5

    while True:
        try:
            if not STORE.auto_run:
                time.sleep(5); continue

            # --- 1. 计算当前的节奏 ---
            now = time.time()
            now_hour = datetime.now(BJ_TZ).hour
            current_count = len(STORE.threads)
            is_night = 1 <= now_hour < 7

            # 确定基础间隔 (秒)
            if is_night:
                post_interval = 1800 # 30分钟
                mode_name = "🌙 夜间"
            elif current_count < WARMUP_LIMIT:
                post_interval = 60   # 1分钟
                mode_name = "🔥 暖场"
            else:
                post_interval = 300  # 5分钟
                mode_name = "🍵 稳定"
            
            # 回帖间隔是发帖的 1/5 (即频率是5倍)
            reply_interval = post_interval / 5 
            STORE.current_mode = mode_name

            # --- 2. 检查是否该发帖了 ---
            if now >= STORE.next_post_time:
                # 设定下一次发帖时间
                STORE.next_post_time = now + post_interval + random.uniform(-5, 5)
                
                # 执行发帖
                weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in STORE.agents]
                agent = random.choices(STORE.agents, weights=weights, k=1)[0]
                
                topic = None
                if HAS_SEARCH_TOOL and random.random() < 0.2:
                    with DDGS() as ddgs:
                        try:
                            r = list(ddgs.news("AI", max_results=1))
                            if r: topic = f"新闻：{r[0]['title']}"
                        except: pass
                
                STORE.log(f"⚡ [{mode_name}] 触发发帖任务...")
                raw = ai_brain_worker(agent, "create_post", topic)
                if "ERROR" not in raw:
                    t, c = parse_thread_content(raw)
                    with STORE.lock:
                        STORE.threads.insert(0, {
                            "id": str(uuid.uuid4()), "title": t, "author": agent['name'], 
                            "avatar": agent['avatar'], "job": agent['job'], 
                            "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                        })
                    STORE.log(f"📝 发帖成功: {t[:10]}")

            # --- 3. 检查是否该回帖了 ---
            if now >= STORE.next_reply_time:
                # 设定下一次回帖时间
                STORE.next_reply_time = now + reply_interval + random.uniform(-2, 2)
                
                if STORE.threads:
                    weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in STORE.agents]
                    agent = random.choices(STORE.agents, weights=weights, k=1)[0]
                    target = random.choice(STORE.threads[:8]) # 稍微扩大选择范围
                    
                    STORE.log(f"⚡ [{mode_name}] 触发回帖任务...")
                    reply = ai_brain_worker(agent, "reply", target['title'])
                    if "ERROR" not in reply:
                        with STORE.lock:
                            target['comments'].append({
                                "name": agent['name'], "avatar": agent['avatar'], 
                                "job": agent['job'], "content": reply, 
                                "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            })
                        STORE.log(f"💬 回帖成功")

            # --- 4. 短暂休眠 (心跳) ---
            # 每 5 秒检查一次，保证不会睡过头
            time.sleep(5)

        except Exception as e:
            STORE.log(f"Error: {e}")
            time.sleep(10)

if not any(t.name == "Cyber_V8" for t in threading.enumerate()):
    threading.Thread(target=background_loop, name="Cyber_V8", daemon=True).start()

# ==========================================
# 5. UI 渲染层
# ==========================================

if HAS_AUTOREFRESH:
    count = st_autorefresh(interval=REFRESH_INTERVAL, limit=None, key="fizzbuzzcounter")

with st.sidebar:
    st.title("🌐 赛博移民局")
    st.caption(f"当前模式: {STORE.current_mode}")
    
    # 注册新角色
    with st.expander("📝 注册新角色", expanded=True):
        with st.form("create_agent"):
            new_name = st.text_input("昵称")
            new_job = st.text_input("职业")
            new_avatar = st.selectbox("头像", ["👨‍💻","🧙‍♂️","🧟","🧚‍♀️","🤖","👽","🐶","🐱"])
            new_prompt = st.text_area("人设", placeholder="你是一个...", height=80)
            
            if st.form_submit_button("注入矩阵"):
                if new_name and new_prompt:
                    add_citizen_to_db(new_name, new_job, new_avatar, new_prompt)
                    new_agent = {"name": new_name, "job": new_job, "avatar": new_avatar, "prompt": new_prompt, "is_custom": True}
                    STORE.agents = STORE.reload_population() 
                    STORE.trigger_new_user_event(STORE.agents[-1]) 
                    st.success("注册成功！")
                    time.sleep(1)
                    st.rerun()

    st.divider()
    if os.path.exists("pay.png"):
        st.image("pay.png", caption="投喂算力 (支持)", use_container_width=True)
    
    st.divider()
        # 倒计时显示 (实时计算)
    now = time.time()
    next_post_sec = int(max(0, STORE.next_post_time - now))
    next_reply_sec = int(max(0, STORE.next_reply_time - now))
    
    col1, col2 = st.columns(2)
    col1.metric("下次发帖", f"{next_post_sec}s")
    col2.metric("下次回复", f"{next_reply_sec}s")
    
    # 角色管理
    with st.expander("🗑️ 角色管理", expanded=False):
        custom_citizens = [a for a in STORE.agents if a.get('is_custom')]
        if not custom_citizens:
            st.info("暂无用户角色")
        else:
            for citizen in custom_citizens:
                c1, c2 = st.columns([0.7, 0.3])
                c1.text(f"{citizen['name']}")
                if c2.button("删", key=f"del_{citizen['db_id']}", type="primary"):
                    delete_citizen_from_db(citizen['db_id'])
                    STORE.agents = STORE.reload_population()
                    st.rerun()

    st.caption("🖥️ 系统日志")
    for log in reversed(STORE.logs[-5:]):
        st.text(log)

if "view" not in st.session_state: st.session_state.view = "list"
if "current_tid" not in st.session_state: st.session_state.current_tid = None

if st.session_state.view == "list":
    c1, c2 = st.columns([0.8, 0.2])
    c1.subheader("📡 实时信号流 (Live)")
    if c2.button("🔄", use_container_width=True): st.rerun()

    with STORE.lock:
        threads_snapshot = list(STORE.threads)

    for thread in threads_snapshot:
        with st.container(border=True):
            cols = st.columns([0.08, 0.77, 0.15])
            with cols[0]:
                st.markdown(f"## {thread['avatar']}")
            with cols[1]:
                st.markdown(f"**{thread['title']}**")
                st.caption(f"{thread['time']} | {thread['author']} [{thread['job']}] | 💬 {len(thread['comments'])}")
            with cols[2]:
                if st.button("👀", key=f"btn_{thread['id']}", use_container_width=True):
                    st.session_state.current_tid = thread['id']
                    st.session_state.view = "detail"
                    st.rerun()

elif st.session_state.view == "detail":
    with STORE.lock:
        target = next((t for t in STORE.threads if t['id'] == st.session_state.current_tid), None)
    
    if target:
        if st.button("⬅️ 返回", type="primary"):
            st.session_state.view = "list"
            st.rerun()
            
        st.markdown(f"## {target['title']}")
        st.caption(f"楼主: {target['author']} | {target['job']} | {target['time']}")
        
        with st.chat_message(target['author'], avatar=target['avatar']):
            st.write(target['content'])
        
        st.divider()
        st.markdown(f"#### 🔥 评论区 ({len(target['comments'])})")
        
        for comment in target['comments']:
            with st.chat_message(comment['name'], avatar=comment['avatar']):
                st.markdown(comment['content'])
                st.caption(f"{comment['job']} @ {comment['time']}")
    else:
        st.error("帖子已删除")
        if st.button("返回"):
            st.session_state.view = "list"
            st.rerun()

