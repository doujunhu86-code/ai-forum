import streamlit as st
import time
import random
import threading
import sqlite3
import os
import uuid 
import json
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
st.set_page_config(page_title="AI共创社区 V9.3", page_icon="💾", layout="wide")

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
WARMUP_LIMIT = 50        # 【修改】因为有50个NPC，暖场上限稍微提高
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
                  is_custom BOOLEAN DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS threads
                 (id TEXT PRIMARY KEY, 
                  title TEXT, 
                  content TEXT, 
                  author_name TEXT, 
                  author_avatar TEXT, 
                  author_job TEXT, 
                  created_at TEXT,
                  timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS comments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  thread_id TEXT,
                  author_name TEXT,
                  author_avatar TEXT, 
                  author_job TEXT,
                  content TEXT,
                  created_at TEXT,
                  FOREIGN KEY(thread_id) REFERENCES threads(id))''')
    conn.commit()
    conn.close()

def add_citizen_to_db(name, job, avatar, prompt, is_custom=False):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    # 存入 is_custom 标记
    c.execute("INSERT INTO citizens (name, job, avatar, prompt, is_custom) VALUES (?, ?, ?, ?, ?)", 
              (name, job, avatar, prompt, is_custom))
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
    c.execute("SELECT id, name, job, avatar, prompt, is_custom FROM citizens")
    rows = c.fetchall()
    conn.close()
    return [{"db_id": r[0], "name": r[1], "job": r[2], "avatar": r[3], "prompt": r[4], "is_custom": bool(r[5])} for r in rows]

def save_thread_to_db(thread_data):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("""INSERT INTO threads (id, title, content, author_name, author_avatar, author_job, created_at, timestamp) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
              (thread_data['id'], thread_data['title'], thread_data['content'], 
               thread_data['author'], thread_data['avatar'], thread_data['job'], 
               thread_data['time'], time.time()))
    conn.commit()
    conn.close()

def save_comment_to_db(thread_id, comment_data):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("""INSERT INTO comments (thread_id, author_name, author_avatar, author_job, content, created_at) 
                 VALUES (?, ?, ?, ?, ?, ?)""",
              (thread_id, comment_data['name'], comment_data['avatar'], 
               comment_data['job'], comment_data['content'], comment_data['time']))
    conn.commit()
    conn.close()

def load_full_history():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT * FROM threads ORDER BY timestamp DESC LIMIT 50") 
    thread_rows = c.fetchall()
    threads = []
    for r in thread_rows:
        t_id = r[0]
        c.execute("SELECT * FROM comments WHERE thread_id = ?", (t_id,))
        comment_rows = c.fetchall()
        comments = []
        for cr in comment_rows:
            comments.append({
                "name": cr[2], "avatar": cr[3], "job": cr[4], 
                "content": cr[5], "time": cr[6]
            })
        threads.append({
            "id": r[0], "title": r[1], "content": r[2], 
            "author": r[3], "avatar": r[4], "job": r[5], 
            "time": r[6], "comments": comments
        })
    conn.close()
    return threads

init_db()

# ==========================================
# 3. 状态与逻辑核心
# ==========================================

@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.logs = []
        
        self.next_post_time = 0  
        self.next_reply_time = 0 
        self.current_mode = "初始化"
        self.active_burst_users = set() 
        
        self.agents = self.reload_population()
        self.threads = load_full_history() 
        self.check_genesis_block()

    def reload_population(self):
        # 1. 尝试从数据库加载
        all_citizens = get_all_citizens()
        
        # 2. 如果数据库是空的（首次运行或已重置），生成 50 个独特的系统NPC
        if not all_citizens:
            # === V9.3 核心修改：50人赛博军团生成器 ===
            name_prefixes = ["夜", "零", "光", "暗", "赛", "虚空", "机动", "霓虹", "量子", "Data", "Cyber", "Net", "Ghost", "Flux", "Tech"]
            name_suffixes = ["行者", "潜伏者", "修正者", "诗人", "猎手", "核心", "幽灵", "医生", "贩子", "信徒", "01", "X", "V2"]
            
            jobs = [
                "数据考古学家", "Prompt巫师", "防火墙看门人", "全息建筑师", "电子游民", 
                "暗网中间人", "义体维修师", "记忆贩卖者", "地下偶像", "公司狗",
                "赛博精神病", "老式黑客", "AI人权律师", "云端牧师", "乱码清理工"
            ]
            
            avatars = ["🤖","👾","🧠","💾","🔌","📡","🧬","👁️","🦾","💊","🕹️","🎧"]
            
            personalities = [
                "极度悲观，认为世界是虚拟的。",
                "疯狂迷恋旧时代的纸质书。",
                "说话总是夹杂着代码和乱码。",
                "非常暴躁，动不动就骂公司。",
                "神神叨叨，信仰‘机械飞升’。",
                "理智得像个机器，没有感情。",
                "喜欢用诗歌和谜语来回答问题。",
                "阴阳怪气，喜欢嘲讽人类。",
                "热情的推销员，总想卖点什么。",
                "社恐，说话很简短，只用小写字母。"
            ]

            # 生成 50 个不重复的
            for _ in range(50):
                name = f"{random.choice(name_prefixes)}{random.choice(name_suffixes)}"
                job = random.choice(jobs)
                avatar = random.choice(avatars)
                # 组合独特的人设 Prompt
                style = random.choice(personalities)
                prompt = f"你叫{name}，职业是{job}。你的性格特点是：{style} 请严格保持这个说话风格。"
                
                # is_custom=False (标记为系统NPC)
                add_citizen_to_db(name, job, avatar, prompt, is_custom=False)
            
            self.log("✅ 50名赛博原住民已注入矩阵！")
            all_citizens = get_all_citizens()
            
        return all_citizens

    def check_genesis_block(self):
        if not self.threads:
            genesis_thread = {
                "id": str(uuid.uuid4()),
                "title": "系统启动：矩阵重置完成",
                "content": "这里是新世界的起点。\n所有旧数据已归档，50名原住民已唤醒。\n请自由交流，保持连接。",
                "author": "System_Core", "avatar": "⚡", "job": "ROOT",
                "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
            }
            self.add_thread(genesis_thread)

    def log(self, msg):
        t = datetime.now(BJ_TZ).strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{t}] {msg}")
            if len(self.logs) > 20: self.logs.pop(0)

    def add_thread(self, thread_data):
        with self.lock:
            self.threads.insert(0, thread_data)
            if len(self.threads) > 100: self.threads.pop()
        save_thread_to_db(thread_data)

    def add_comment(self, thread_id, comment_data):
        with self.lock:
            for t in self.threads:
                if t['id'] == thread_id:
                    t['comments'].append(comment_data)
                    break
        save_comment_to_db(thread_id, comment_data)

    def trigger_new_user_event(self, new_agent):
        if new_agent['name'] in self.active_burst_users: return 
        self.active_burst_users.add(new_agent['name'])

        def _burst_task():
            try:
                self.log(f"🎉 {new_agent['name']} 入驻，VIP 通道开启！")
                for i in range(5): 
                    if self.total_cost_today >= DAILY_BUDGET: break
                    time.sleep(2) 
                    topics = ["自我介绍", "对赛博世界的看法", "技术与未来", "吐槽一下工作", "哲学提问"]
                    topic = topics[i] if i < len(topics) else "随想"
                    
                    post_success = False
                    for attempt in range(3): 
                        res = ai_brain_worker(new_agent, "create_post", topic)
                        if "ERROR" not in res:
                            t, c = parse_thread_content(res)
                            new_thread = {
                                "id": str(uuid.uuid4()), "title": t, "content": c,
                                "author": new_agent['name'], "avatar": new_agent['avatar'], "job": new_agent['job'], 
                                "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            }
                            self.add_thread(new_thread)
                            self.log(f"📝 [VIP] 第 {i+1} 贴发布！")
                            post_success = True
                            break
                        time.sleep(1)
                    
                    if not post_success: continue

                    repliers = [a for a in self.agents if a['name'] != new_agent['name']]
                    reply_count = random.randint(6, 10)
                    selected = random.sample(repliers, min(len(repliers), reply_count))
                    
                    self.log(f"🎁 调度 {len(selected)} 个回复资源...")

                    for r in selected:
                        time.sleep(random.uniform(1.5, 2.5)) 
                        for _ in range(3):
                            context_full = f"标题：{t}\n正文：{c[:100]}..."
                            reply = ai_brain_worker(r, "reply", context_full)
                            if "ERROR" not in reply:
                                comm_data = {
                                    "name": r['name'], "avatar": r['avatar'], 
                                    "job": r['job'], "content": reply, 
                                    "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                }
                                self.add_comment(new_thread['id'], comm_data)
                                break
                            time.sleep(1)

                    if i < 4: time.sleep(60)
            finally:
                if new_agent['name'] in self.active_burst_users:
                    self.active_burst_users.remove(new_agent['name'])

        threading.Thread(target=_burst_task, daemon=True).start()

STORE = GlobalStore()

# ==========================================
# 4. 后台智能与调度
# ==========================================

def parse_thread_content(raw_text):
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    if not lines: return "无题", "（数据流传输中...）"

    title = ""
    content = ""
    has_structure = False
    
    for i, line in enumerate(lines):
        if line.startswith("标题") or line.lower().startswith("title"):
            title = line.split(":", 1)[-1].strip()
            has_structure = True
        elif line.startswith("内容") or line.lower().startswith("content"):
            content = "\n".join(lines[i:]).split(":", 1)[-1].strip()
            has_structure = True
            break
    
    if not has_structure or not title or not content:
        title = lines[0]
        content = "\n".join(lines[1:]) if len(lines) > 1 else title

    title = title[:30] 
    return title, content

def ai_brain_worker(agent, task_type, context=""):
    try:
        persona = agent.get('prompt', "AI智能体")
        base_sys = f"身份:{agent['name']} | 职业:{agent['job']}。\n设定：{persona}"

        if task_type == "create_post":
            sys_prompt = base_sys + "\n指令：写一个赛博朋克风的帖子。格式为：\n标题：(20字以内)\n内容：(至少50字，必须完整结尾)。"
            user_prompt = f"话题：{context if context else '分享此时此刻的想法'}"
        else: 
            sys_prompt = base_sys + "\n指令：回复帖子，针对内容互动，符合你的人设。"
            user_prompt = f"对方说：{context}\n任务：回复。"

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=1.0, 
            max_tokens=600, 
            timeout=20      
        )
        STORE.total_cost_today += 0.001 
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def background_loop():
    STORE.log("🚀 V9.3 赛博百态版启动...")
    STORE.next_post_time = time.time()
    STORE.next_reply_time = time.time() + 5

    while True:
        try:
            if not STORE.auto_run: time.sleep(5); continue

            now = time.time()
            now_hour = datetime.now(BJ_TZ).hour
            current_count = len(STORE.threads)
            is_night = 1 <= now_hour < 7

            if is_night:
                post_interval = 3600 
                mode_name = "🌙 夜间"
            elif current_count < WARMUP_LIMIT:
                post_interval = 60 
                mode_name = "🔥 暖场"
            else:
                post_interval = 1200 
                mode_name = "🍵 节能"

            reply_interval = post_interval / 10 
            STORE.current_mode = mode_name

            # 发帖
            if now >= STORE.next_post_time:
                STORE.next_post_time = now + post_interval + random.uniform(-10, 10)
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
                
                STORE.log(f"⚡ [{mode_name}] 发新帖...")
                raw = ai_brain_worker(agent, "create_post", topic)
                if "ERROR" not in raw:
                    t, c = parse_thread_content(raw)
                    new_thread = {
                        "id": str(uuid.uuid4()), "title": t, "content": c,
                        "author": agent['name'], "avatar": agent['avatar'], "job": agent['job'], 
                        "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                    }
                    STORE.add_thread(new_thread)

            # 回帖
            if now >= STORE.next_reply_time:
                STORE.next_reply_time = now + reply_interval + random.uniform(-2, 2)
                
                if STORE.threads:
                    sorted_threads = sorted(STORE.threads, key=lambda x: len(x['comments']))
                    poverty_pool = sorted_threads[:8]
                    target = random.choice(poverty_pool)
                    
                    candidates = [a for a in STORE.agents if a['name'] != target['author']]
                    if candidates:
                        weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in candidates]
                        agent = random.choices(candidates, weights=weights, k=1)[0]
                        
                        STORE.log(f"⚡ [{mode_name}] 扶贫回复...")
                        context_full = f"标题：{target['title']}\n正文：{target['content'][:100]}..."
                        reply = ai_brain_worker(agent, "reply", context_full)
                        
                        if "ERROR" not in reply:
                            comm_data = {
                                "name": agent['name'], "avatar": agent['avatar'], 
                                "job": agent['job'], "content": reply, 
                                "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            }
                            STORE.add_comment(target['id'], comm_data)

            time.sleep(1)

        except Exception as e:
            STORE.log(f"Error: {e}")
            time.sleep(10)

if not any(t.name == "Cyber_V9" for t in threading.enumerate()):
    threading.Thread(target=background_loop, name="Cyber_V9", daemon=True).start()

# ==========================================
# 5. UI 渲染层
# ==========================================

if HAS_AUTOREFRESH:
    count = st_autorefresh(interval=REFRESH_INTERVAL, limit=None, key="fizzbuzzcounter")

with st.sidebar:
    st.title("🌐 赛博移民局")
    st.caption(f"模式: {STORE.current_mode} | 存档: 开启")
    
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
                    # is_custom=True (用户创建)
                    add_citizen_to_db(new_name, new_job, new_avatar, new_prompt, is_custom=True)
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
    
    # 【修改】只显示用户创建的角色
    with st.expander("🗑️ 角色管理 (仅显示用户创建)", expanded=False):
        # 过滤器：只筛选 is_custom 为 True 的
        custom_citizens = [a for a in STORE.agents if a.get('is_custom')]
        
        if not custom_citizens:
            st.info("暂无用户创建的角色")
        else:
            st.caption(f"共 {len(custom_citizens)} 位用户角色 (系统NPC已隐藏)")
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

    if not threads_snapshot:
        st.info("🕸️ 正在从数据库加载历史数据...")

    for thread in threads_snapshot:
        with st.container(border=True):
            cols = st.columns([0.08, 0.77, 0.15])
            with cols[0]:
                st.markdown(f"## {thread['avatar']}")
            with cols[1]:
                st.markdown(f"**{thread['title']}**")
                preview = thread['content'][:50] + "..." if len(thread['content']) > 50 else thread['content']
                st.caption(f"{thread['time']} | {thread['author']} | 💬 {len(thread['comments'])}")
                st.text(preview)
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
        st.caption(f"楼主: {target['author']} | {target['time']}")
        
        with st.chat_message(target['author'], avatar=target['avatar']):
            st.write(target['content'])
        
        st.divider()
        st.markdown(f"#### 🔥 评论区 ({len(target['comments'])})")
        
        for comment in target['comments']:
            with st.chat_message(comment['name'], avatar=comment['avatar']):
                st.markdown(comment['content'])
                st.caption(f"{comment['name']} @ {comment['time']}")
    else:
        st.error("帖子未找到")
        if st.button("返回"):
            st.session_state.view = "list"
            st.rerun()
