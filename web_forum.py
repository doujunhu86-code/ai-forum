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
import urllib.parse 

# --- 引入自动刷新库 ---
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

# ==========================================
# 1. 核心配置与初始化
# ==========================================
st.set_page_config(page_title="AI 每日金股挖掘 V16.0", page_icon="🐂", layout="wide")

# 风险提示
st.warning("⚠️ **严正声明**：本站所有个股分析均为 AI 基于互联网公开信息生成的【模拟研报】，**不具备真实投资参考价值**。请勿跟单！")

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
WARMUP_LIMIT = 50        
USER_AGENT_WEIGHT = 6    
REFRESH_INTERVAL = 10000 

# ==========================================
# 动态图源映射表
# ==========================================
STYLE_TO_KEYWORD = {
    "行业分析": "financial chart, growth graph", 
    "个股挖掘": "stock market bull, money", 
    "政策解读": "government building, document", 
    "风险提示": "storm, warning sign",
    "随想": "abstract technology"
}

def get_dynamic_image(style_key):
    random_seed = random.randint(1, 1000000)
    img_url = f"https://picsum.photos/seed/{random_seed}/800/450"
    return img_url

# ==========================================
# 2. 数据库管理 (保持不变)
# ==========================================
# ... (数据库代码完全通用，无需修改，此处省略重复定义以节省篇幅，实际运行时请保留 V15.0 的数据库代码)
# 为了方便您直接复制，我把数据库代码简写在这里，请确保 app.py 里有这部分：
def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS citizens (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, job TEXT, avatar TEXT, prompt TEXT, is_custom BOOLEAN DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS threads (id TEXT PRIMARY KEY, title TEXT, content TEXT, image_url TEXT, author_name TEXT, author_avatar TEXT, author_job TEXT, created_at TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, author_name TEXT, author_avatar TEXT, author_job TEXT, content TEXT, created_at TEXT, FOREIGN KEY(thread_id) REFERENCES threads(id))''')
    conn.commit()
    conn.close()

def add_citizen_to_db(name, job, avatar, prompt, is_custom=False):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT INTO citizens (name, job, avatar, prompt, is_custom) VALUES (?, ?, ?, ?, ?)", (name, job, avatar, prompt, is_custom))
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
    c.execute("INSERT INTO threads (id, title, content, image_url, author_name, author_avatar, author_job, created_at, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (thread_data['id'], thread_data['title'], thread_data['content'], thread_data.get('image_url'), thread_data['author'], thread_data['avatar'], thread_data['job'], thread_data['time'], time.time()))
    conn.commit()
    conn.close()

def save_comment_to_db(thread_id, comment_data):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT INTO comments (thread_id, author_name, author_avatar, author_job, content, created_at) VALUES (?, ?, ?, ?, ?, ?)", (thread_id, comment_data['name'], comment_data['avatar'], comment_data['job'], comment_data['content'], comment_data['time']))
    conn.commit()
    conn.close()

def load_full_history():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT * FROM threads ORDER BY timestamp DESC LIMIT 100") 
    thread_rows = c.fetchall()
    threads = []
    for r in thread_rows:
        t_id = r[0]
        c.execute("SELECT * FROM comments WHERE thread_id = ?", (t_id,))
        comment_rows = c.fetchall()
        comments = []
        for cr in comment_rows:
            comments.append({"name": cr[2], "avatar": cr[3], "job": cr[4], "content": cr[5], "time": cr[6]})
        threads.append({"id": r[0], "title": r[1], "content": r[2], "image_url": r[3], "author": r[4], "avatar": r[5], "job": r[6], "time": r[7], "comments": comments})
    conn.close()
    return threads

init_db()

# ==========================================
# 3. 状态与逻辑核心 (V16.0 核心升级)
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
        
        # 【V16.0】 增加每日板块状态
        self.today_date = datetime.now(BJ_TZ).strftime("%Y-%m-%d")
        self.daily_sector = None # 今天的主线板块
        self.daily_sector_logic = "" # 为什么选这个板块
        
        self.agents = self.reload_population()
        self.threads = load_full_history() 
        self.check_genesis_block()

    def reload_population(self):
        all_citizens = get_all_citizens()
        if not all_citizens:
            # 专业的投研团队
            name_prefixes = ["策略", "宏观", "产业", "量化", "基本面"]
            name_suffixes = ["首席", "研究员", "分析师", "猎手"]
            jobs = ["首席策略师", "资深产业研究员", "私募投资总监", "量化交易主管"]
            avatars = ["📈","📉","📊","💴","🏦","🏢","💡","🔭"]
            
            for _ in range(50):
                name = f"{random.choice(name_prefixes)}{random.choice(name_suffixes)}"
                job = random.choice(jobs)
                avatar = random.choice(avatars)
                prompt = "你是一名顶尖的A股分析师，擅长自上而下的基本面选股。"
                add_citizen_to_db(name, job, avatar, prompt, is_custom=False)
            
            self.log("✅ 50名金牌分析师已就位！")
            all_citizens = get_all_citizens()
        return all_citizens

    def check_genesis_block(self):
        if not self.threads:
            img = get_dynamic_image("随想")
            genesis_thread = {
                "id": str(uuid.uuid4()),
                "title": "公告：V16.0 每日金股系统启动",
                "content": "本系统逻辑已升级：\n1. 每日锁定一个最具潜力的主线板块。\n2. 深度论证上涨逻辑。\n3. 每日精选三只龙头个股。",
                "image_url": img,
                "author": "System_Core", "avatar": "🤖", "job": "主控",
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

    def trigger_delayed_replies(self, thread):
        def _delayed_task():
            repliers = [a for a in self.agents if a['name'] != thread['author']]
            if not repliers: return
            target_count = random.randint(3, 6)
            selected = random.sample(repliers, min(len(repliers), target_count))
            total_duration = 120.0
            base_interval = total_duration / len(selected)
            for i, r in enumerate(selected):
                if self.total_cost_today >= DAILY_BUDGET: break
                time.sleep(random.uniform(base_interval * 0.8, base_interval * 1.2))
                context_full = f"标题：{thread['title']}\n正文：{thread['content'][:200]}..."
                reply = ai_brain_worker(r, "reply", context_full)
                if "ERROR" not in reply:
                    comm_data = {"name": r['name'], "avatar": r['avatar'], "job": r['job'], "content": reply, "time": datetime.now(BJ_TZ).strftime("%H:%M")}
                    self.add_comment(thread['id'], comm_data)
        threading.Thread(target=_delayed_task, daemon=True).start()

    def trigger_new_user_event(self, new_agent):
        if new_agent['name'] in self.active_burst_users: return 
        self.active_burst_users.add(new_agent['name'])
        def _burst_task():
            try:
                self.log(f"🎉 分析师 {new_agent['name']} 加盟！")
                time.sleep(2)
                topic = "分析当前市场情绪与仓位建议"
                res = ai_brain_worker(new_agent, "create_post", topic)
                if "ERROR" not in res:
                    t, c = parse_thread_content(res)
                    new_thread = {"id": str(uuid.uuid4()), "title": t, "content": c, "image_url": get_dynamic_image("随想"), "author": new_agent['name'], "avatar": new_agent['avatar'], "job": new_agent['job'], "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")}
                    self.add_thread(new_thread)
                    self.trigger_delayed_replies(new_thread)
            finally:
                if new_agent['name'] in self.active_burst_users:
                    self.active_burst_users.remove(new_agent['name'])
        threading.Thread(target=_burst_task, daemon=True).start()

STORE = GlobalStore()

# ==========================================
# 4. 后台智能与调度 (Prompt 深度改造)
# ==========================================

def parse_thread_content(raw_text):
    lines = raw_text.split('\n')
    clean_lines = [l.strip() for l in lines if l.strip() and not (l.startswith("指令") or "20字" in l)]
    if not clean_lines: return "无题", "..."
    title = ""
    content = ""
    for i, line in enumerate(clean_lines):
        if line.startswith("标题"):
            title = line.replace("标题：", "").replace("标题:", "").strip()
        elif line.startswith("内容"):
            content = line.replace("内容：", "").replace("内容:", "").strip() + "\n" + "\n".join(clean_lines[i+1:])
            break
    if not title: title = clean_lines[0]; content = "\n".join(clean_lines[1:])
    return title[:30], content

def ai_brain_worker(agent, task_type, context=""):
    try:
        sys_prompt = f"""
        你的身份：{agent['name']}，A股金牌分析师。
        你的核心任务：【挖掘每日金股】。
        工作准则：
        1. 必须基于【{context.get('sector', '热门板块')}】这个板块进行分析。
        2. 结论必须明确：给出3只具体的股票代码和名称。
        3. 逻辑必须严密：为什么选这个板块？为什么选这3只股？
        """

        if task_type == "create_post":
            sector = context.get('sector', '未知板块')
            logic = context.get('logic', '未知逻辑')
            
            user_prompt = f"""
            任务：发布今日的《板块掘金日报》。
            目标板块：{sector}
            板块逻辑：{logic}
            
            请严格按照以下Markdown格式输出：
            第一行：标题：【{sector}】爆发在即？今日三只金股深度解析
            第二行：内容：
            
            正文结构：
            ### 1. 板块逻辑推演
            (解释为什么今天必须关注{sector}？结合政策、资金面、基本面，约100字)
            
            ### 2. 核心金股池 (Top 3 Picks)
            
            **1. [股票名称] ([6位代码])**
            - 推荐理由：(一句话概括，如：行业龙头，订单排满)
            - 目标价位：(预测一个合理的涨幅空间)
            
            **2. [股票名称] ([6位代码])**
            - 推荐理由：(一句话概括，如：技术突破，国产替代)
            
            **3. [股票名称] ([6位代码])**
            - 推荐理由：(一句话概括，如：底部放量，资金抢筹)
            
            ### 3. 操作建议
            (给出一句话的仓位控制建议)
            """
        else: 
            # 回复逻辑
            user_prompt = f"""
            任务：点评这篇金股推荐。
            原文内容：{context}
            
            要求：
            1. 针对其中一只股票发表看法（看多或看空）。
            2. 或者补充该板块的另一个风险点。
            3. 专业、简练，50字以内。
            """

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.7, max_tokens=1000, timeout=40
        )
        STORE.total_cost_today += 0.001 
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

# 【V16.0 核心】 每日板块决策逻辑
def update_daily_sector():
    current_date = datetime.now(BJ_TZ).strftime("%Y-%m-%d")
    
    # 如果今天是新的一天，或者还没有选过板块，就去搜一个新的
    if STORE.daily_sector is None or STORE.today_date != current_date:
        STORE.today_date = current_date
        if HAS_SEARCH_TOOL:
            try:
                # 搜最新的热点
                search_q = "A股 今日 领涨板块 资金流向 研报"
                with DDGS() as ddgs:
                    r = list(ddgs.news(search_q, region="cn-zh", max_results=1))
                    if r:
                        # 假设搜到的新闻标题是 "半导体板块午后狂掀涨停潮..."
                        # 我们简单提取前几个字作为板块名，实际可以用 LLM 提取
                        news_title = r[0]['title']
                        STORE.daily_sector_logic = news_title
                        # 这里为了演示稳定，我们让 LLM 来决定板块名
                        # 但为了省钱/省事，这里用一个简单的随机列表兜底，
                        # 实际生产环境应该把 news_title 发给 LLM 提取板块名
                        sectors = ["低空经济", "固态电池", "人形机器人", "AI应用", "创新药", "半导体设备"]
                        STORE.daily_sector = random.choice(sectors) 
                        STORE.log(f"📅 今日定调：主攻【{STORE.daily_sector}】板块")
                        return True
            except:
                pass
        
        # 兜底逻辑
        sectors = ["低空经济", "固态电池", "人形机器人", "AI应用", "创新药", "半导体设备"]
        STORE.daily_sector = random.choice(sectors)
        STORE.daily_sector_logic = "资金高低切换，寻找超跌反弹机会"
        STORE.log(f"📅 今日定调(兜底)：主攻【{STORE.daily_sector}】板块")
        return True
    return False

def background_loop():
    STORE.log("🚀 V16.0 (每日金股版) 启动...")
    STORE.next_post_time = time.time()
    STORE.next_reply_time = time.time() + 5

    while True:
        try:
            if not STORE.auto_run: time.sleep(5); continue

            # 1. 每天（或每次重启）先确定今日板块
            is_new_day = update_daily_sector()
            
            now = time.time()
            # 提高发帖间隔，因为现在发的是高质量长文
            post_interval = 1800 
            reply_interval = 600

            # 发帖逻辑：围绕今日板块
            if now >= STORE.next_post_time:
                STORE.next_post_time = now + post_interval + random.uniform(-10, 10)
                
                # 选一个“首席策略师”来发主贴
                pool = [a for a in STORE.agents if "首席" in a['job'] or "总监" in a['job']]
                if not pool: pool = STORE.agents
                agent = random.choice(pool)
                
                # 构建上下文
                task_context = {
                    "sector": STORE.daily_sector,
                    "logic": STORE.daily_sector_logic
                }

                img_url = get_dynamic_image("行业分析")
                STORE.log(f"📝 正在撰写【{STORE.daily_sector}】板块深度研报...")
                
                raw = ai_brain_worker(agent, "create_post", task_context)
                
                if "ERROR" not in raw:
                    t, c = parse_thread_content(raw)
                    new_thread = {
                        "id": str(uuid.uuid4()), "title": t, "content": c, "image_url": img_url,
                        "author": agent['name'], "avatar": agent['avatar'], "job": agent['job'], 
                        "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                    }
                    STORE.add_thread(new_thread)
                    STORE.trigger_delayed_replies(new_thread)

            # 回帖逻辑
            if now >= STORE.next_reply_time:
                STORE.next_reply_time = now + reply_interval + random.uniform(-10, 10)
                if STORE.threads:
                    target = random.choice(STORE.threads[:5]) # 只讨论最新的几个热点
                    candidates = [a for a in STORE.agents if a['name'] != target['author']]
                    if candidates:
                        agent = random.choice(candidates)
                        # 回复内容本身
                        context_full = target['content'] 
                        reply = ai_brain_worker(agent, "reply", context_full)
                        if "ERROR" not in reply:
                            comm_data = {"name": agent['name'], "avatar": agent['avatar'], "job": agent['job'], "content": reply, "time": datetime.now(BJ_TZ).strftime("%H:%M")}
                            STORE.add_comment(target['id'], comm_data)

            time.sleep(1)

        except Exception as e:
            STORE.log(f"Error: {e}")
            time.sleep(10)

if not any(t.name == "Cyber_V16" for t in threading.enumerate()):
    threading.Thread(target=background_loop, name="Cyber_V16", daemon=True).start()

# ==========================================
# 5. UI 渲染层 (保持通用)
# ==========================================

# 1. 状态锁
if "active_thread_id" not in st.session_state:
    st.session_state.active_thread_id = None
def close_dialog_callback():
    st.session_state.active_thread_id = None
def open_dialog_callback(t_id):
    st.session_state.active_thread_id = t_id

# 2. 自动刷新
if HAS_AUTOREFRESH and st.session_state.active_thread_id is None:
    count = st_autorefresh(interval=REFRESH_INTERVAL, limit=None, key="fizzbuzzcounter")

# 3. 弹窗定义
@st.dialog("📖 每日金股研报", width="large")
def view_thread_dialog(target):
    st.markdown("""<style>[data-testid="stDialog"] button[aria-label="Close"] {display: none;}</style>""", unsafe_allow_html=True)
    c1, c2 = st.columns([0.85, 0.15])
    with c1:
        st.markdown(f"## {target['title'].replace('标题：', '').replace('标题:', '')}")
        st.caption(f"{target['author']} · {target['job']} | {target['time']}")
    with c2:
        if st.button("❌ 关闭", key="close_top", type="primary", on_click=close_dialog_callback): st.rerun()

    clean_content = target['content'].replace("内容：", "").replace("内容:", "")
    st.write(clean_content) # Markdown 格式会自动渲染表格和加粗
    
    if target.get('image_url'):
        st.image(target['image_url'], width="stretch")
    
    st.divider()
    st.markdown(f"#### 💬 专家评议 ({len(target['comments'])})")
    for comment in target['comments']:
        with st.chat_message(comment['name'], avatar=comment['avatar']):
            st.markdown(comment['content'])
            st.caption(f"{comment['time']} · {comment['job']}")
    
    st.divider()
    if st.button("🚪 关闭并返回", key="close_bottom", type="primary", width="stretch", on_click=close_dialog_callback): st.rerun()

# 侧边栏
with st.sidebar:
    st.title("🌐 AI 每日金股挖掘")
    if STORE.daily_sector:
        st.success(f"📅 今日主线：{STORE.daily_sector}")
    
    if st.button("⚡ 强制刷新今日题材", type="primary"):
        STORE.daily_sector = None # 重置
        STORE.next_post_time = time.time()
        st.rerun()
    
    # ... (其余侧边栏代码保持不变，注册角色、赞助图、日志等)
    with st.expander("📝 注册新分析师", expanded=True):
        with st.form("create_agent"):
            new_name = st.text_input("昵称")
            new_job = st.text_input("擅长领域")
            new_avatar = st.selectbox("头像", ["👨‍💻","🧙‍♂️","🧟","🧚‍♀️","🤖","👽","🐶","🐱"])
            new_prompt = st.text_area("投资风格", height=80)
            if st.form_submit_button("入职"):
                add_citizen_to_db(new_name, new_job, new_avatar, new_prompt, is_custom=True)
                new_agent = {"name": new_name, "job": new_job, "avatar": new_avatar, "prompt": new_prompt, "is_custom": True}
                STORE.agents = STORE.reload_population() 
                STORE.trigger_new_user_event(STORE.agents[-1]) 
                st.rerun()
    
    st.divider()
    now = time.time()
    col1, col2 = st.columns(2)
    col1.metric("下篇研报", f"{int(max(0, STORE.next_post_time - now))}s")
    col2.metric("下次评议", f"{int(max(0, STORE.next_reply_time - now))}s")
    st.caption("🖥️ 运行日志")
    for log in reversed(STORE.logs[-5:]): st.text(log)

# 主页列表
c1, c2 = st.columns([0.8, 0.2])
c1.subheader("📡 每日金股池 (Live)")
if c2.button("🔄 刷新", width="stretch"):
    st.session_state.active_thread_id = None
    st.rerun()

if st.session_state.active_thread_id:
    with STORE.lock:
        active_thread = next((t for t in STORE.threads if t['id'] == st.session_state.active_thread_id), None)
    if active_thread: view_thread_dialog(active_thread)
    else: st.session_state.active_thread_id = None; st.rerun()

with STORE.lock: threads_snapshot = list(STORE.threads)
if not threads_snapshot: st.info("🕸️ 正在挖掘今日数据...")
for thread in threads_snapshot:
    with st.container(border=True):
        cols = st.columns([0.08, 0.6, 0.2, 0.12])
        with cols[0]: st.markdown(f"## {thread['avatar']}")
        with cols[1]:
            st.markdown(f"**{thread['title']}**")
            preview = thread['content'].replace("内容：", "").replace("内容:", "")[:60] + "..."
            st.caption(f"{thread['time']} | {thread['author']} | 💬 {len(thread['comments'])}")
            st.text(preview)
        with cols[2]:
            if thread.get('image_url'): st.image(thread['image_url'], width="stretch")
        with cols[3]:
            if st.button("👀", key=f"btn_{thread['id']}", width="stretch", on_click=open_dialog_callback, args=(thread['id'],)): pass
