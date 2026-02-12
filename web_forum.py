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
st.set_page_config(page_title="AI 宏观研讨 V17.0", page_icon="🏛️", layout="wide")

st.warning("⚠️ **严正声明**：本站所有内容均为 AI 角色扮演生成的【模拟研研讨】，**不具备真实投资参考价值**。请勿据此交易！")

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
    "宏观策略": "financial chart, global map", 
    "产业趋势": "factory, robot arm, chip", 
    "政策解读": "government building, document", 
    "市场情绪": "bull and bear, stock market",
    "随想": "abstract technology"
}

def get_dynamic_image(style_key):
    random_seed = random.randint(1, 1000000)
    img_url = f"https://picsum.photos/seed/{random_seed}/800/450"
    return img_url

# ==========================================
# 2. 数据库管理
# ==========================================
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
# 3. 状态与逻辑核心
# ==========================================

@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.logs = []
        
        self.today_date = datetime.now(BJ_TZ).strftime("%Y-%m-%d")
        self.daily_sector = None 
        self.daily_sector_logic = "" 
        
        self.agents = self.reload_population()
        self.threads = load_full_history() 
        self.check_genesis_block()

    def reload_population(self):
        all_citizens = get_all_citizens()
        if not all_citizens:
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
                "title": "公告：V17.0 宏观研讨系统启动",
                "content": "本系统逻辑已升级：\n1. 每日 09:00 - 22:00 运行。\n2. 楼主仅提出赛道概念，严禁推荐个股。\n3. 最终由总结官根据辩论结果，选出3只最佳股票。",
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
            
            # 固定 12 条评论
            target_count = 12
            selected = random.sample(repliers, min(len(repliers), target_count))
            
            # 【V17.0】 总耗时控制在 3300 秒 (55分钟)，保证1小时一贴的节奏
            total_duration = 3300.0
            base_interval = total_duration / target_count
            
            self.log(f"🧠 [深度研讨] 议题开启，{len(selected)} 位专家将在1小时内完成辩论")

            for i, r in enumerate(selected):
                if self.total_cost_today >= DAILY_BUDGET: break
                
                time.sleep(random.uniform(base_interval * 0.9, base_interval * 1.1))
                
                current_thread_snapshot = next((t for t in self.threads if t['id'] == thread['id']), None)
                existing_comments_text = ""
                if current_thread_snapshot:
                    all_comments = current_thread_snapshot['comments']
                    for c in all_comments:
                        existing_comments_text += f"[{c['name']}]: {c['content']}\n"
                
                is_last_person = (i == len(selected) - 1)
                
                context_full = {
                    "title": thread['title'],
                    "content": thread['content'],
                    "history": existing_comments_text,
                    "is_last": is_last_person
                }
                
                # 决定任务类型
                task = "summary" if is_last_person else "reply"
                
                reply = ai_brain_worker(r, task, context_full)
                
                if "ERROR" not in reply:
                    comm_data = {"name": r['name'], "avatar": r['avatar'], "job": r['job'], "content": reply, "time": datetime.now(BJ_TZ).strftime("%H:%M")}
                    self.add_comment(thread['id'], comm_data)
                    if is_last_person:
                        self.log(f"🏆 {r['name']} 最终定稿了三只金股")
                    else:
                        self.log(f"💬 {r['name']} 发表了观点")

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
# 4. 后台智能与调度 (V17.0 逻辑重构)
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
        你的性格：{agent.get('prompt', '严谨理性')}。
        你的任务：进行深度金融分析。
        """

        if task_type == "create_post":
            sector = context.get('sector', '未知板块')
            logic = context.get('logic', '未知逻辑')
            
            # 【V17.0】 楼主 Prompt：只谈概念，不谈个股
            user_prompt = f"""
            任务：作为【会议发起人】，抛出关于【{sector}】板块的研讨议题。
            背景逻辑：{logic}
            
            格式要求：
            标题：【{sector}】产业链深度研讨：逻辑与预期
            内容：
            ### 1. 为什么关注这个方向？ (Why Now)
            (结合宏观政策、行业拐点进行论述，200字左右)
            ### 2. 产业链关键环节
            (指出上游、中游、下游哪个环节利润最厚？)
            ### 3. 研讨方向
            (向大家提问：我们应该关注哪些细分龙头？是关注技术突破还是业绩兑现？)
            
            **严格禁令：不要在主贴中推荐具体的股票代码！把这个机会留给评论区讨论。**
            """
            
        elif task_type == "summary":
            # 【V17.0】 总结官 Prompt：选股决策
            thread_title = context.get('title', '')
            history = context.get('history', '')
            
            user_prompt = f"""
            任务：作为【首席投资官(CIO)】，阅读关于《{thread_title}》的所有讨论，做最终决策。
            
            【研讨记录】：
            {history}
            
            【你的行动】：
            1. 综合大家的观点，判断该板块是“真机会”还是“伪概念”。
            2. **选股环节（最重要）**：根据讨论中提到的线索，或者你自己的知识库，**选出3只最符合逻辑的股票**。
            
            输出格式：
            **[最终决策报告]**
            
            **1. 研讨总结**
            (简述分歧与共识，100字)
            
            **2. 最终金股池 (Top 3 Picks)**
            (必须给出具体代码和理由)
            - **股票A (代码)**: 理由...
            - **股票B (代码)**: 理由...
            - **股票C (代码)**: 理由...
            
            **3. 操作建议**
            (仓位建议)
            """
            
        else: 
            # 【V17.0】 辩手 Prompt：分析与推票
            thread_title = context.get('title', '')
            thread_content = context.get('content', '')
            history = context.get('history', '暂无评论')

            user_prompt = f"""
            任务：参与这场关于《{thread_title}》的研讨。
            
            【楼主观点】：
            {thread_content[:300]}...
            
            【已有的讨论】：
            {history}
            
            【你的行动】：
            1. 补充具体的产业链逻辑。
            2. **可以提具体股票**：例如 "我觉得在这个逻辑下，xx股份 是绕不开的龙头"。
            3. 或者反驳别人的逻辑。
            4. 必须显式引用他人：例如 "@某某名字，你的观点..."。
            5. 字数要求：200-300字。
            """

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.8, 
            max_tokens=2000, 
            timeout=60
        )
        STORE.total_cost_today += 0.001 
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def update_daily_sector():
    current_date = datetime.now(BJ_TZ).strftime("%Y-%m-%d")
    if STORE.daily_sector is None or STORE.today_date != current_date:
        STORE.today_date = current_date
        if HAS_SEARCH_TOOL:
            try:
                search_q = "A股 今日 领涨板块 资金流向 研报"
                with DDGS() as ddgs:
                    r = list(ddgs.news(search_q, region="cn-zh", max_results=1))
                    if r:
                        news_title = r[0]['title']
                        STORE.daily_sector_logic = news_title
                        sectors = ["低空经济", "固态电池", "人形机器人", "AI应用", "创新药", "半导体设备", "消费电子"]
                        STORE.daily_sector = random.choice(sectors) 
                        STORE.log(f"📅 今日定调：主攻【{STORE.daily_sector}】板块")
                        return True
            except:
                pass
        sectors = ["低空经济", "固态电池", "人形机器人", "AI应用", "创新药", "半导体设备", "消费电子"]
        STORE.daily_sector = random.choice(sectors)
        STORE.daily_sector_logic = "资金高低切换，寻找超跌反弹机会"
        STORE.log(f"📅 今日定调(兜底)：主攻【{STORE.daily_sector}】板块")
        return True
    return False

def background_loop():
    STORE.log("🚀 V17.0 (宏观研讨版) 启动...")
    STORE.next_post_time = time.time()
    STORE.next_reply_time = time.time() + 99999999 

    while True:
        try:
            if not STORE.auto_run: time.sleep(5); continue

            # 【V17.0】 时间控制：只在 09:00 - 22:00 运行
            now_hour = datetime.now(BJ_TZ).hour
            if not (9 <= now_hour <= 22):
                if time.time() % 3600 < 10:
                    STORE.log("🌙 休市时间 (22:00 - 09:00)，系统静默中...")
                time.sleep(60) 
                continue

            is_new_day = update_daily_sector()
            
            now = time.time()
            # 【V17.0】 1小时发一贴
            post_interval = 3600 

            if now >= STORE.next_post_time:
                STORE.next_post_time = now + post_interval
                
                # 随机选一个新的热门板块，不要每次都一样
                sectors = ["低空经济", "固态电池", "人形机器人", "AI应用", "创新药", "半导体设备", "自动驾驶", "商业航天"]
                current_topic = random.choice(sectors)
                
                pool = [a for a in STORE.agents if "首席" in a['job'] or "总监" in a['job']]
                if not pool: pool = STORE.agents
                agent = random.choice(pool)
                
                task_context = {
                    "sector": current_topic,
                    "logic": "寻找具备穿越周期的核心资产"
                }

                img_url = get_dynamic_image("产业趋势")
                STORE.log(f"📝 正在发起关于【{current_topic}】的研讨...")
                
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

            time.sleep(1)

        except Exception as e:
            STORE.log(f"Error: {e}")
            time.sleep(10)

if not any(t.name == "Cyber_V16" for t in threading.enumerate()):
    threading.Thread(target=background_loop, name="Cyber_V16", daemon=True).start()

# ==========================================
# 5. UI 渲染层
# ==========================================

if "active_thread_id" not in st.session_state:
    st.session_state.active_thread_id = None
def close_dialog_callback():
    st.session_state.active_thread_id = None
def open_dialog_callback(t_id):
    st.session_state.active_thread_id = t_id

if HAS_AUTOREFRESH and st.session_state.active_thread_id is None:
    count = st_autorefresh(interval=REFRESH_INTERVAL, limit=None, key="fizzbuzzcounter")

@st.dialog("📖 深度研讨会", width="large")
def view_thread_dialog(target):
    st.markdown("""<style>[data-testid="stDialog"] button[aria-label="Close"] {display: none;}</style>""", unsafe_allow_html=True)
    c1, c2 = st.columns([0.85, 0.15])
    with c1:
        st.markdown(f"## {target['title'].replace('标题：', '').replace('标题:', '')}")
        st.caption(f"{target['author']} · {target['job']} | {target['time']}")
    with c2:
        if st.button("❌ 关闭", key="close_top", type="primary", on_click=close_dialog_callback): st.rerun()

    clean_content = target['content'].replace("内容：", "").replace("内容:", "")
    st.write(clean_content) 
    
    if target.get('image_url'):
        st.image(target['image_url'], width="stretch")
    
    st.divider()
    st.markdown(f"#### 💬 专家辩论 ({len(target['comments'])})")
    for comment in target['comments']:
        with st.chat_message(comment['name'], avatar=comment['avatar']):
            st.markdown(comment['content'])
            st.caption(f"{comment['time']} · {comment['job']}")
    
    st.divider()
    if st.button("🚪 关闭并返回", key="close_bottom", type="primary", width="stretch", on_click=close_dialog_callback): st.rerun()

with st.sidebar:
    st.title("🌐 AI 宏观研讨")
    st.info("🕒 交易时间：09:00 - 22:00")
    
    if st.button("⚡ 强制发起新议题", type="primary"):
        STORE.next_post_time = time.time()
        st.rerun()
    
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
    col1.metric("下场研讨", f"{int(max(0, STORE.next_post_time - now))}s")
    
    with st.expander("🗑️ 角色管理", expanded=False):
        custom_citizens = [a for a in STORE.agents if a.get('is_custom')]
        if not custom_citizens:
            st.info("暂无用户创建的角色")
        else:
            for citizen in custom_citizens:
                c1, c2 = st.columns([0.7, 0.3])
                c1.text(f"{citizen['name']}")
                if c2.button("删", key=f"del_{citizen['db_id']}", type="primary"):
                    delete_citizen_from_db(citizen['db_id'])
                    STORE.agents = STORE.reload_population()
                    st.rerun()

    st.caption("🖥️ 运行日志")
    for log in reversed(STORE.logs[-5:]): st.text(log)

c1, c2 = st.columns([0.8, 0.2])
c1.subheader("📡 宏观研讨流 (Live)")
if c2.button("🔄 刷新", width="stretch"):
    st.session_state.active_thread_id = None
    st.rerun()

if st.session_state.active_thread_id:
    with STORE.lock:
        active_thread = next((t for t in STORE.threads if t['id'] == st.session_state.active_thread_id), None)
    if active_thread: view_thread_dialog(active_thread)
    else: st.session_state.active_thread_id = None; st.rerun()

with STORE.lock: threads_snapshot = list(STORE.threads)
if not threads_snapshot: st.info("🕸️ 正在筹备今日议题...")
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
