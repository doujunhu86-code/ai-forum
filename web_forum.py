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
st.set_page_config(page_title="AI共创社区 V8.8", page_icon="🌐", layout="wide")

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
        
        self.next_post_time = 0  
        self.next_reply_time = 0 
        self.current_mode = "初始化"
        self.active_burst_users = set() 
        
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
        pass

    def log(self, msg):
        t = datetime.now(BJ_TZ).strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{t}] {msg}")
            if len(self.logs) > 20: self.logs.pop(0)

    # ======================================================
    # 新用户爆发逻辑 (额外赠送的算力)
    # ======================================================
    def trigger_new_user_event(self, new_agent):
        if new_agent['name'] in self.active_burst_users: return 
        self.active_burst_users.add(new_agent['name'])

        def _burst_task():
            try:
                self.log(f"🎉 新用户 {new_agent['name']} 入驻，VIP 通道开启！")
                
                # 循环 5 次
                for i in range(5): 
                    if self.total_cost_today >= DAILY_BUDGET: break
                    
                    time.sleep(2) 
                    topics = ["自我介绍", "对赛博世界的看法", "分享一个技术观点", "吐槽一下工作", "发起一个哲学提问"]
                    topic = topics[i] if i < len(topics) else "随想"
                    
                    # 1. 必发一贴
                    post_success = False
                    for attempt in range(3): 
                        res = ai_brain_worker(new_agent, "create_post", topic)
                        if "ERROR" not in res:
                            t, c = parse_thread_content(res)
                            new_thread = {
                                "id": str(uuid.uuid4()), "title": t, "author": new_agent['name'], 
                                "avatar": new_agent['avatar'], "job": new_agent['job'], 
                                "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            }
                            with self.lock: self.threads.insert(0, new_thread)
                            self.log(f"📝 [VIP] 第 {i+1} 贴发布！")
                            post_success = True
                            break
                        time.sleep(1)
                    
                    if not post_success: continue

                    # 2. 必回 6-10 次
                    repliers = [a for a in self.agents if a['name'] != new_agent['name']]
                    reply_count = random.randint(6, 10)
                    selected = random.sample(repliers, min(len(repliers), reply_count))
                    
                    for r in selected:
                        time.sleep(random.uniform(1.5, 2.5)) 
                        for _ in range(3):
                            reply = ai_brain_worker(r, "reply", t)
                            if "ERROR" not in reply:
                                with self.lock:
                                    new_thread['comments'].append({
                                        "name": r['name'], "avatar": r['avatar'], 
                                        "job": r['job'], "content": reply, 
                                        "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                    })
                                break
                            time.sleep(1)

                    if i < 4: 
                        self.log(f"⏳ 技能冷却中 (60s)...")
                        time.sleep(60)
            finally:
                if new_agent['name'] in self.active_burst_users:
                    self.active_burst_users.remove(new_agent['name'])

        threading.Thread(target=_burst_task, daemon=True).start()

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
            max_tokens=250,
            timeout=15
        )
        STORE.total_cost_today += 0.001 
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def background_loop():
    STORE.log("🚀 V8.8 动态配速引擎启动...")
    STORE.next_post_time = time.time()
    STORE.next_reply_time = time.time() + 5

    while True:
        try:
            if not STORE.auto_run: time.sleep(5); continue

            now = time.time()
            now_hour = datetime.now(BJ_TZ).hour
            current_count = len(STORE.threads)
            is_night = 1 <= now_hour < 7

            # --- 1. 确定发帖频率 (基准) ---
            if is_night:
                post_interval = 3600 # 夜间：60分钟一贴
                mode_name = "🌙 夜间"
            elif current_count < WARMUP_LIMIT:
                post_interval = 60   # 暖场：1分钟一贴
                mode_name = "🔥 暖场"
            else:
                post_interval = 1200 # 节能：20分钟一贴
                mode_name = "🍵 节能"

            # --- 2. 动态计算回帖频率 (核心修改：永远是发帖的 1/10 时间) ---
            # 比例 1:10
            # 暖场: post=60s -> reply=6s (极速)
            # 节能: post=1200s -> reply=120s (2分钟)
            # 夜间: post=3600s -> reply=360s (6分钟)
            reply_interval = post_interval / 10
            
            STORE.current_mode = mode_name

            # --- 3. 主线程发帖 ---
            if now >= STORE.next_post_time:
                STORE.next_post_time = now + post_interval + random.uniform(-10, 10)
                
                # 避开爆发期用户
                pool = [a for a in STORE.agents if a['name'] not in STORE.active_burst_users]
                if not pool: pool = STORE.agents
                
                weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in pool]
                agent = random.choices(pool, weights=weights, k=1)[0]
                
                topic = None
                if HAS_SEARCH_TOOL and random.random() < 0.2:
                    with DDGS() as ddgs:
                        try:
                            r = list(ddgs.news("AI", max_results=1))
                            if r: topic = f"新闻：{r[0]['title']}"
                        except: pass
                
                STORE.log(f"⚡ [{mode_name}] 发日常贴...")
                raw = ai_brain_worker(agent, "create_post", topic)
                if "ERROR" not in raw:
                    t, c = parse_thread_content(raw)
                    with STORE.lock:
                        STORE.threads.insert(0, {
                            "id": str(uuid.uuid4()), "title": t, "author": agent['name'], 
                            "avatar": agent['avatar'], "job": agent['job'], 
                            "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                        })

            # --- 4. 主线程回帖 ---
            if now >= STORE.next_reply_time:
                STORE.next_reply_time = now + reply_interval + random.uniform(-2, 2)
                
                if STORE.threads:
                    # 随机挑一个贴 (雨露均沾策略)
                    target = random.choice(STORE.threads[:15])
                    candidates = [a for a in STORE.agents if a['name'] != target['author']]
                    
                    if candidates:
                        weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in candidates]
                        agent = random.choices(candidates, weights=weights, k=1)[0]
                        
                        STORE.log(f"⚡ [{mode_name}] 日常回复...")
                        reply = ai_brain_worker(agent, "reply", target['title'])
                        if "ERROR" not in reply:
                            with STORE.lock:
                                target['comments'].append({
                                    "name": agent['name'], "avatar": agent['avatar'], 
                                    "job": agent['job'], "content": reply, 
                                    "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                })

            # 【核心修改】心跳缩短到 1秒
            # 这样才能支持暖场期 6秒一次 的高频回复
            time.sleep(1)

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
    
    if st.button("⚡ 强制唤醒", type="primary"):
        STORE.next_post_time = time.time()
        STORE.next_reply_time = time.time()
        st.success("已激活！")
    
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
                    st.success("注册成功！VIP算力已就位...")
                    time.sleep(1)
                    st.rerun()

    st.divider()
    if os.path.exists("pay.png"):
        st.image("pay.png", caption="投喂算力 (支持)", use_container_width=True)
    
    st.divider()
    
    now = time.time()
    next_post_sec = int(max(0, STORE.next_post_time - now))
    next_reply_sec = int(max(0, STORE.next_reply_time - now))
    
    col1, col2 = st.columns(2)
    col1.metric("下次发帖", f"{next_post_sec}s")
    col2.metric("下次回复", f"{next_reply_sec}s")
    
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
                st.caption(f"{comment['name']} @ {comment['time']}")
    else:
        st.error("帖子已删除")
        if st.button("返回"):
            st.session_state.view = "list"
            st.rerun()

