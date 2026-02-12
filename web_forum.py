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
st.set_page_config(page_title="AI 闭环投研 V19.0", page_icon="📈", layout="wide")

st.warning("⚠️ **严正声明**：本站所有内容均为 AI 角色扮演生成的【模拟研讨】，**不具备真实投资参考价值**。请勿据此交易！")

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
    "早盘策略": "sunrise, coffee, stock market", 
    "午盘点评": "lunch, business chart", 
    "收盘复盘": "sunset, city skyline, finance", 
    "复盘回测": "magnifying glass, check mark, data",
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

# 【V19.0】 检查帖子是否已经复盘过
def check_if_reviewed(thread_id):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM comments WHERE thread_id = ? AND author_name = '回测机器'", (thread_id,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

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
        
        # 【V19.0】 记录今天是否发过早中晚
        self.last_post_date = None
        self.posts_done_today = {"morning": False, "noon": False, "evening": False}
        
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
                "title": "公告：V19.0 闭环投研系统启动",
                "content": "系统升级：\n1. 每日三更 (09:15, 12:30, 20:00)。\n2. 引入对抗性辩论机制。\n3. T+5 自动回测复盘功能上线。",
                "image_url": img,
                "author": "System_Core", "avatar": "🔄", "job": "主控",
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
            
            target_count = 12
            selected = random.sample(repliers, min(len(repliers), target_count))
            
            self.log(f"🧠 [深度辩论] 针对《{thread['title']}》的 12 轮攻防已开启...")

            for i, r in enumerate(selected):
                if self.total_cost_today >= DAILY_BUDGET: break
                
                time.sleep(60) # 1分钟一贴
                
                current_thread_snapshot = next((t for t in self.threads if t['id'] == thread['id']), None)
                existing_comments_text = ""
                if current_thread_snapshot:
                    all_comments = current_thread_snapshot['comments']
                    for c in all_comments:
                        existing_comments_text += f"[{c['name']}]: {c['content']}\n"
                
                is_last_person = (i == 11)
                
                # 【V19.0】 对抗性角色分配
                # 奇数楼层 (index 0, 2...) -> 质疑者/做空
                # 偶数楼层 (index 1, 3...) -> 辩护者/补充
                role_type = "critic" if i % 2 == 0 else "supporter"
                if is_last_person: role_type = "judge"

                context_full = {
                    "title": thread['title'],
                    "content": thread['content'], 
                    "history": existing_comments_text, 
                    "role_type": role_type
                }
                
                task = "summary" if is_last_person else "reply"
                
                reply = ai_brain_worker(r, task, context_full)
                
                if "ERROR" not in reply:
                    comm_data = {"name": r['name'], "avatar": r['avatar'], "job": r['job'], "content": reply, "time": datetime.now(BJ_TZ).strftime("%H:%M")}
                    self.add_comment(thread['id'], comm_data)
                    
                    if is_last_person:
                        self.log(f"🏆 {r['name']}：辩论结束，结论已出")
                    else:
                        action = "质疑" if role_type == "critic" else "补充"
                        # self.log(f"⚔️ {r['name']} 发起了{action}") 

        threading.Thread(target=_delayed_task, daemon=True).start()

    def trigger_new_user_event(self, new_agent):
        # 简化版：新用户入职不发贴，只记录
        self.log(f"🎉 分析师 {new_agent['name']} 加盟！")

STORE = GlobalStore()

# ==========================================
# 4. 后台智能与调度 (V19.0 闭环逻辑)
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
        """

        if task_type == "create_post":
            topic_info = context.get('topic', '随机板块')
            period = context.get('period', '早盘')
            
            user_prompt = f"""
            任务：发布一篇【{period}】深度的行业研讨。
            核心议题：{topic_info}
            
            要求：
            1. 楼主只负责【抛砖引玉】，提出宏观逻辑和赛道机会。
            2. **严禁在主贴推荐个股**，只谈逻辑！
            3. 结尾必须抛出一个争议性问题，引发大家讨论。
            
            格式：
            标题：【{period}】{topic_info}...
            内容：
            ...
            """
            
        elif task_type == "summary":
            thread_title = context.get('title', '')
            thread_content = context.get('content', '')  
            history = context.get('history', '') 
            
            user_prompt = f"""
            任务：作为【总结官】，阅读关于《{thread_title}》的 11 轮激烈辩论。
            
            【辩论现场】：
            {history}
            
            【你的行动】：
            1. 看到有人质疑楼主了吗？楼主的逻辑站得住脚吗？
            2. **选股（重要）**：综合各方观点，选出 **3只** 经得起推敲的股票。
            3. 如果大家都很悲观，你可以建议空仓。
            
            输出：
            **[最终决策报告]**
            1. 辩论综述
            2. 最终金股池 (Top 3)
            3. 操作建议
            """
            
        elif task_type == "review":
            # 【V19.0】 复盘回测 Prompt
            thread_title = context.get('title', '')
            summary = context.get('summary', '') # 之前的结论
            
            user_prompt = f"""
            任务：你是一名【冷酷的审计员】。
            这篇帖子《{thread_title}》是 5 天前发布的。
            
            当时的结论是：
            {summary}
            
            请你（模拟）联网查询这些股票/板块在过去 5 天的表现（或者基于当前市场情况进行推演）。
            
            输出格式：
            **[T+5 复盘报告]**
            
            **1. 验证结果**：(打脸 / 神预言 / 也就是那样)
            **2. 原因分析**：(当时漏算了什么？或者什么利好兑现了？)
            **3. 后续建议**：(止盈 / 止损 / 继续持有)
            
            语气要客观，如果错了就狠狠批评当初的分析师。
            """

        else: 
            # 【V19.0】 辩论模式 Prompt
            thread_title = context.get('title', '')
            thread_content = context.get('content', '')
            history = context.get('history', '暂无评论')
            role_type = context.get('role_type', 'supporter')
            
            instruction = ""
            if role_type == "critic":
                instruction = "你的角色是【质疑者/空头】。必须挑上一楼的刺！或者指出楼主逻辑的硬伤（如估值太高、业绩雷、技术不成熟）。语气要犀利。"
            else:
                instruction = "你的角色是【补充者/多头】。虽然同意大方向，但要补充更细节的数据，或者反驳刚才那个质疑者。语气要专业。"

            user_prompt = f"""
            任务：参与《{thread_title}》的辩论。
            
            【楼主】：{thread_content[:200]}...
            【前序发言】：{history}
            
            【你的指令】：
            {instruction}
            
            要求：
            1. 必须针对【上一楼】的观点进行互动（@他）。
            2. 避免千篇一律，输出独特的洞察。
            3. 200字左右。
            """

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.9, # 提高温度，增加多样性
            max_tokens=2000, 
            timeout=60
        )
        STORE.total_cost_today += 0.001 
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

# 获取动态话题
def get_fresh_topic():
    if HAS_SEARCH_TOOL:
        try:
            queries = ["A股 热门板块 研报", "今日 资金流向", "行业 景气度 提升"]
            search_q = random.choice(queries)
            with DDGS() as ddgs:
                r = list(ddgs.news(search_q, region="cn-zh", max_results=1))
                if r: return f"{r[0]['title']}"
        except: pass
    return f"挖掘被忽视的低估值板块"

# 【V19.0】 检查是否有旧贴需要复盘
def check_and_run_reviews():
    # 逻辑：找出所有 5 天前发布的，且没有被“回测机器”评论过的帖子
    # 为了演示效果，我们把时间缩短：检查 30 分钟前的帖子 (模拟5天)
    # 实际使用请把 seconds=1800 改为 days=5
    review_threshold = datetime.now() - timedelta(minutes=30) 
    review_timestamp = review_threshold.timestamp()
    
    with STORE.lock:
        # 简单遍历内存中的 threads（实际应查库）
        candidates = []
        for t in STORE.threads:
            if t['timestamp'] < review_timestamp:
                if not check_if_reviewed(t['id']):
                    candidates.append(t)
    
    for t in candidates:
        STORE.log(f"🕵️‍♂️ 正在对 5 天前的帖子《{t['title']}》进行回测复盘...")
        
        # 提取之前的结论（一般在最后一条评论里）
        last_comment = t['comments'][-1]['content'] if t['comments'] else "无结论"
        
        context = {
            "title": t['title'],
            "summary": last_comment
        }
        
        # 专门的复盘机器人
        reviewer_agent = {"name": "回测机器", "job": "审计系统", "avatar": "🤖", "prompt": "客观公正"}
        
        review_content = ai_brain_worker(reviewer_agent, "review", context)
        
        if "ERROR" not in review_content:
            comm_data = {
                "name": "回测机器", 
                "avatar": "📝", 
                "job": "系统审计", 
                "content": review_content, 
                "time": datetime.now(BJ_TZ).strftime("%H:%M")
            }
            STORE.add_comment(t['id'], comm_data)
            time.sleep(5) # 稍微歇一下

def background_loop():
    STORE.log("🚀 V19.0 (闭环投研版) 启动...")
    
    # 初始化日期状态
    current_date_str = datetime.now(BJ_TZ).strftime("%Y-%m-%d")
    if STORE.last_post_date != current_date_str:
        STORE.last_post_date = current_date_str
        STORE.posts_done_today = {"morning": False, "noon": False, "evening": False}

    while True:
        try:
            if not STORE.auto_run: time.sleep(5); continue
            
            now_dt = datetime.now(BJ_TZ)
            current_date_str = now_dt.strftime("%Y-%m-%d")
            
            # 跨天重置
            if STORE.last_post_date != current_date_str:
                STORE.last_post_date = current_date_str
                STORE.posts_done_today = {"morning": False, "noon": False, "evening": False}
                STORE.log("📅 新的一天，发帖任务重置")

            # 1. 检查复盘任务 (每循环都检查一下)
            check_and_run_reviews()

            # 2. 检查发帖任务
            current_hm = now_dt.strftime("%H:%M")
            target_period = None
            
            # 定义早中晚的时间窗口 (放宽一点，防止错过)
            if "09:15" <= current_hm <= "09:30" and not STORE.posts_done_today["morning"]:
                target_period = "早盘策略"
                STORE.posts_done_today["morning"] = True
            elif "12:30" <= current_hm <= "12:45" and not STORE.posts_done_today["noon"]:
                target_period = "午盘点评"
                STORE.posts_done_today["noon"] = True
            elif "20:00" <= current_hm <= "20:15" and not STORE.posts_done_today["evening"]:
                target_period = "收盘复盘"
                STORE.posts_done_today["evening"] = True
            
            if target_period:
                pool = [a for a in STORE.agents if "首席" in a['job'] or "总监" in a['job']]
                if not pool: pool = STORE.agents
                agent = random.choice(pool)
                
                topic = get_fresh_topic()
                img_url = get_dynamic_image(target_period)
                
                STORE.log(f"⏰ 时间到！正在发布【{target_period}】：{topic}")
                
                context = {"topic": topic, "period": target_period}
                raw = ai_brain_worker(agent, "create_post", context)
                
                if "ERROR" not in raw:
                    t, c = parse_thread_content(raw)
                    new_thread = {
                        "id": str(uuid.uuid4()), "title": t, "content": c, "image_url": img_url,
                        "author": agent['name'], "avatar": agent['avatar'], "job": agent['job'], 
                        "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                    }
                    STORE.add_thread(new_thread)
                    STORE.trigger_delayed_replies(new_thread)

            time.sleep(10) # 10秒检查一次时间

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
    st.title("🌐 AI 闭环投研")
    st.info("🕒 发帖时刻：09:15 / 12:30 / 20:00")
    
    # 方便演示，强制触发
    if st.button("⚡ 强制发布一贴 (测试)", type="primary"):
        STORE.posts_done_today["morning"] = False # 重置一下状态欺骗逻辑
        # 手动改一下时间让它命中逻辑太麻烦，直接改 next_post_time 没用，因为现在是定时的
        # 所以这里我们直接在这里调用一次核心逻辑
        threading.Thread(target=lambda: STORE.log("⚡ 强制测试触发中...")).start()
        # 这里只是界面按钮，实际逻辑太复杂，建议直接改系统时间或等时间到
        # 为了用户体验，我们稍微 hack 一下：
        STORE.posts_done_today = {"morning": False, "noon": False, "evening": False} # 重置所有任务
        st.success("已重置今日任务状态，系统检测到时间匹配时会自动发帖（或请修改系统时间测试）")

    st.divider()
    if os.path.exists("pay.png"):
        st.image("pay.png", caption="投喂算力 (支持)", width="stretch")
    
    st.divider()
    
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
c1.subheader("📡 投研复盘 (Live)")
if c2.button("🔄 刷新", width="stretch"):
    st.session_state.active_thread_id = None
    st.rerun()

if st.session_state.active_thread_id:
    with STORE.lock:
        active_thread = next((t for t in STORE.threads if t['id'] == st.session_state.active_thread_id), None)
    if active_thread: view_thread_dialog(active_thread)
    else: st.session_state.active_thread_id = None; st.rerun()

with STORE.lock: threads_snapshot = list(STORE.threads)
if not threads_snapshot: st.info("🕸️ 正在等待开盘...")
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
