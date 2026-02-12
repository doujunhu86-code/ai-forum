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
st.set_page_config(page_title="AI 价值投资研究院 V15.0", page_icon="📈", layout="wide")

# 【V15.0 新增】风险提示横幅
st.warning("⚠️ **风险提示**：本论坛内容由 AI 模拟“金融分析师”角色生成，仅供技术研究与逻辑推演，**绝不构成任何投资建议**。股市有风险，入市需谨慎。")

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
    # 映射为比较抽象的商务风格
    "生活碎片": "office, business meeting", 
    "今日感悟": "financial chart, stock market", 
    "实用技巧": "calculator, money, growth", 
    "好物分享": "product analysis, factory",
    "问答互动": "handshake, agreement", 
    "兴趣展示": "reading reports, library", 
    "书影音记录": "history book, data visualization", 
    "回忆角落": "vintage building, bank", 
    "冷知识科普": "technology chip, laboratory", 
    "治愈瞬间": "green plants, steady growth", 
    "话题讨论": "conference, microphone", 
    "挑战参与": "mountain climbing, success", 
    "幕后花絮": "working late, laptop", 
    "地点打卡": "skyscraper, city skyline", 
    "幽默段子": "bull and bear, funny finance", 
    "成长记录": "upward arrow, profit", 
    "音乐共享": "classical music, focus", 
    "观点输出": "writing report, pen", 
    "问题求助": "question mark, strategy", 
    "未来展望": "future city, robot", 
    "今日热点": "global news, map", 
    "随想": "abstract geometry"
}

# 使用 Picsum 确保绝对稳定
def get_dynamic_image(style_key):
    random_seed = random.randint(1, 1000000)
    img_url = f"https://picsum.photos/seed/{random_seed}/800/450"
    return img_url

# ==========================================
# 2. 数据库管理 (保持不变)
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
                  image_url TEXT,
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
    c.execute("""INSERT INTO threads (id, title, content, image_url, author_name, author_avatar, author_job, created_at, timestamp) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (thread_data['id'], thread_data['title'], thread_data['content'], thread_data.get('image_url'),
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
    c.execute("SELECT * FROM threads ORDER BY timestamp DESC LIMIT 100") 
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
            "id": r[0], "title": r[1], "content": r[2], "image_url": r[3],
            "author": r[4], "avatar": r[5], "job": r[6], 
            "time": r[7], "comments": comments
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
        all_citizens = get_all_citizens()
        if not all_citizens:
            # 这里的角色其实会被下面的 Prompt 覆盖，所以名字随便
            name_prefixes = ["价值", "长线", "红利", "成长", "宏观", "量化", "基本面", "深度", "复利", "周期"]
            name_suffixes = ["猎手", "研究员", "基金经理", "分析师", "信徒", "观察者", "策略师"]
            jobs = ["首席策略师", "行业研究员", "私募基金经理", "资深股民", "宏观经济学家"]
            avatars = ["📈","📉","📊","💴","🏦","🏢","💡","🔭"]
            personalities = ["严谨理性", "推崇巴菲特", "关注财报细节", "擅长挖掘黑马", "极其厌恶投机"]

            for _ in range(50):
                name = f"{random.choice(name_prefixes)}{random.choice(name_suffixes)}"
                job = random.choice(jobs)
                avatar = random.choice(avatars)
                style = random.choice(personalities)
                prompt = f"你叫{name}，职业是{job}。风格：{style}"
                add_citizen_to_db(name, job, avatar, prompt, is_custom=False)
            
            self.log("✅ 50名金融分析师已入驻研究院！")
            all_citizens = get_all_citizens()
            
        return all_citizens

    def check_genesis_block(self):
        if not self.threads:
            img = get_dynamic_image("未来展望")
            genesis_thread = {
                "id": str(uuid.uuid4()),
                "title": "公告：AI价值投资研究院成立",
                "content": "本论坛致力于挖掘 A 股中长线投资机会。\n拒绝博弈，拒绝内幕，只谈逻辑，只看基本面。\n让数据指引我们穿越牛熊。",
                "image_url": img,
                "author": "System_Core", "avatar": "⚖️", "job": "院长",
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
            
            target_count = random.randint(4, 8) # 回复少一点，精一点
            selected = random.sample(repliers, min(len(repliers), target_count))
            
            self.log(f"🌱 [研讨会] {len(selected)} 位分析师正在评议 {thread['title'][:8]}...")

            total_duration = 120.0
            base_interval = total_duration / len(selected)

            for i, r in enumerate(selected):
                if self.total_cost_today >= DAILY_BUDGET: break
                sleep_time = random.uniform(base_interval * 0.8, base_interval * 1.2)
                time.sleep(sleep_time)
                
                context_full = f"标题：{thread['title']}\n正文：{thread['content'][:200]}..."
                reply = ai_brain_worker(r, "reply", context_full)
                
                if "ERROR" not in reply:
                    comm_data = {
                        "name": r['name'], "avatar": r['avatar'], 
                        "job": r['job'], "content": reply, 
                        "time": datetime.now(BJ_TZ).strftime("%H:%M")
                    }
                    self.add_comment(thread['id'], comm_data)

        threading.Thread(target=_delayed_task, daemon=True).start()

    def trigger_new_user_event(self, new_agent):
        if new_agent['name'] in self.active_burst_users: return 
        self.active_burst_users.add(new_agent['name'])

        def _burst_task():
            try:
                self.log(f"🎉 新分析师 {new_agent['name']} 入职！")
                # 简化新用户流程，直接发一篇深度贴
                time.sleep(2)
                topic = "上证指数 未来三年 走势推演"
                img_url = get_dynamic_image("未来展望")
                
                res = ai_brain_worker(new_agent, "create_post", topic)
                if "ERROR" not in res:
                    t, c = parse_thread_content(res)
                    new_thread = {
                        "id": str(uuid.uuid4()), "title": t, "content": c, "image_url": img_url,
                        "author": new_agent['name'], "avatar": new_agent['avatar'], "job": new_agent['job'], 
                        "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                    }
                    self.add_thread(new_thread)
                    self.trigger_delayed_replies(new_thread)
            finally:
                if new_agent['name'] in self.active_burst_users:
                    self.active_burst_users.remove(new_agent['name'])

        threading.Thread(target=_burst_task, daemon=True).start()

STORE = GlobalStore()

# ==========================================
# 4. 后台智能与调度 (V15.0 核心升级)
# ==========================================

def parse_thread_content(raw_text):
    lines = raw_text.split('\n')
    clean_lines = []
    is_body = False
    for line in lines:
        l = line.strip()
        if not l: continue
        if not is_body:
            if l.startswith("指令") or l.startswith("设定") or l.startswith("风格") or l.startswith("规则") or "20字以内" in l:
                continue 
            else:
                is_body = True 
                clean_lines.append(l)
        else:
            clean_lines.append(l)

    if not clean_lines: return "无题", "..."

    title = ""
    content = ""
    has_structure = False
    
    for i, line in enumerate(clean_lines):
        if line.startswith("标题") or line.lower().startswith("title"):
            title = line.replace("标题：", "").replace("标题:", "").strip()
            has_structure = True
        elif line.startswith("内容") or line.lower().startswith("content"):
            content_start = line.replace("内容：", "").replace("内容:", "").strip()
            content = content_start + "\n" + "\n".join(clean_lines[i+1:])
            has_structure = True
            break
    
    if not has_structure or not title:
        title = clean_lines[0]
        content = "\n".join(clean_lines[1:]) if len(clean_lines) > 1 else title

    title = title.replace("标题：", "").replace("标题:", "")[:30]
    return title, content

def ai_brain_worker(agent, task_type, context=""):
    try:
        # 【V15.0】强制注入：价值投资专家人设
        sys_prompt = f"""
        你的身份：{agent['name']}，你是一名【深度价值投资者】和【资深行业分析师】。
        你的投资哲学：
        1. 【只做长线】：严禁提及“明日涨跌”、“技术突破”、“打板”等短线投机词汇。
        2. 【数据驱动】：分析必须基于：PE/PB(估值)、ROE(盈利能力)、护城河(竞争优势)、分红率。
        3. 【宏观视野】：结合国家“十四五”规划、产业升级、国产替代等大逻辑。
        4. 【风险厌恶】：必须指出潜在风险点（如人口老龄化、原材料涨价）。
        """

        if task_type == "create_post":
            # 这里定义几种长线研报的模板
            post_styles = [
                "【白马股体检】：挑选一家行业龙头，分析其护城河是否稳固，目前估值是否具备安全边际。",
                "【困境反转】：寻找基本面优秀但暂时遇到困难被错杀的公司，论证其未来3年翻倍的逻辑。",
                "【高股息策略】：在低利率时代，分析哪些水电、银行、高速公路股值得养老持有。",
                "【成长股挖掘】：在硬科技（芯片/AI/新能源）领域，寻找未来十年的十倍股。"
            ]
            style = random.choice(post_styles)
            
            user_prompt = f"""
            任务：发布一篇《A股中长线深度研报》。
            搜索情报参考：{context}
            
            请严格按照以下格式输出：
            第一行：标题：[股票名称/行业]：[一句话核心观点] (例如：长江电力：时间的玫瑰，稳稳的幸福)
            第二行：内容：
            
            正文结构要求：
            1. **核心逻辑**：一句话说清楚为什么这就公司值得拿3-5年？
            2. **基本面分析**：
               - 估值情况（PE/PB历史分位）
               - 盈利能力（ROE、毛利率趋势）
            3. **宏观与政策**：国家政策对此行业是支持还是打压？
            4. **风险提示**：列出2条可能导致亏损的因素。
            
            注意：虽然我们看多，但语气要客观冷静，不要煽动情绪。
            """
        else: 
            # 回复逻辑：同行评审
            user_prompt = f"""
            任务：作为一名挑剔的基金经理，点评这篇研报。
            原文观点：{context}
            
            要求：
            1. 不要只说“支持”，要提出补充视角或反面意见。
            2. 例如：“逻辑没问题，但目前估值分位还在80%以上，建议等待回撤。”
            3. 或者：“注意该行业的周期性风险，目前处于景气度高点，警惕戴维斯双杀。”
            4. 保持专业，字数50字以内。
            """

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.7, # 稍微降低温度，让分析更严谨
            max_tokens=800, 
            timeout=30      
        )
        STORE.total_cost_today += 0.001 
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def background_loop():
    STORE.log("🚀 V15.0 (价值投资研究院) 启动...")
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
                mode_name = "🌙 休市复盘"
            else:
                post_interval = 1200 # 20分钟一篇深度研报，慢工出细活
                mode_name = "📈 盘中研究"

            reply_interval = post_interval / 3 
            STORE.current_mode = mode_name

            # 发帖逻辑
            if now >= STORE.next_post_time:
                STORE.next_post_time = now + post_interval + random.uniform(-10, 10)
                pool = [a for a in STORE.agents if a['name'] not in STORE.active_burst_users]
                if not pool: pool = STORE.agents
                weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in pool]
                agent = random.choices(pool, weights=weights, k=1)[0]
                
                topic = None
                style_key = "观点输出" 

                if HAS_SEARCH_TOOL:
                    try:
                        # 【V15.0】 深度价值搜索词
                        search_keywords = [
                            "A股 深度研报 推荐 2025",
                            "高股息 蓝筹股 名单",
                            "国家大基金 持仓分析",
                            "中特估 核心资产 估值分析",
                            "行业龙头 护城河 分析",
                            "消费复苏 受益股",
                            "硬科技 芯片 创新药 研报"
                        ]
                        keyword = random.choice(search_keywords)
                        with DDGS() as ddgs:
                            r = list(ddgs.news(keyword, region="cn-zh", max_results=1))
                            if r: 
                                news_title = r[0]['title']
                                # 强行把搜索结果喂给AI，让它基于此进行深度加工
                                topic = f"请分析此情报背后的长线机会：{news_title}。结合公司基本面进行推演。"
                                style_key = "今日感悟" # 对应 financial chart 图
                                STORE.log(f"🔎 调研中：{news_title[:15]}...")
                    except: pass
                
                if not topic:
                    topic = "随机挑选一只沪深300成分股，进行长线价值分析。"

                img_url = get_dynamic_image(style_key)

                STORE.log(f"📝 [{mode_name}] 撰写研报中...")
                raw = ai_brain_worker(agent, "create_post", topic)
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
                STORE.next_reply_time = now + reply_interval + random.uniform(-2, 2)
                
                if STORE.threads:
                    sorted_threads = sorted(STORE.threads, key=lambda x: len(x['comments']))
                    poverty_pool = sorted_threads[:8]
                    target = random.choice(poverty_pool)
                    
                    candidates = [a for a in STORE.agents if a['name'] != target['author']]
                    if candidates:
                        weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in candidates]
                        agent = random.choices(candidates, weights=weights, k=1)[0]
                        
                        STORE.log(f"💬 [{mode_name}] 参与研讨...")
                        context_full = f"标题：{target['title']}\n正文：{target['content'][:200]}..."
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

# 1. 状态锁初始化
if "active_thread_id" not in st.session_state:
    st.session_state.active_thread_id = None

# 关闭回调
def close_dialog_callback():
    st.session_state.active_thread_id = None

# 打开回调
def open_dialog_callback(t_id):
    st.session_state.active_thread_id = t_id

# 2. 自动刷新逻辑
if HAS_AUTOREFRESH and st.session_state.active_thread_id is None:
    count = st_autorefresh(interval=REFRESH_INTERVAL, limit=None, key="fizzbuzzcounter")

# 3. 弹窗定义
@st.dialog("📖 深度研报", width="large")
def view_thread_dialog(target):
    # 隐藏右上角自带的 X
    st.markdown("""
    <style>
    [data-testid="stDialog"] button[aria-label="Close"] {
        display: none;
    }
    </style>
    """, unsafe_allow_html=True)

    # 顶部导航栏
    c1, c2 = st.columns([0.85, 0.15])
    with c1:
        st.markdown(f"## {target['title'].replace('标题：', '').replace('标题:', '')}")
        st.caption(f"{target['author']} · {target['job']} | {target['time']}")
    with c2:
        if st.button("❌ 关闭", key="close_top", type="primary", on_click=close_dialog_callback):
            st.rerun()

    # 正文
    clean_content = target['content'].replace("内容：", "").replace("内容:", "")
    st.info("💡 核心观点提取：" + clean_content[:60] + "...") # 增加一个摘要框
    st.write(clean_content)
    
    if target.get('image_url'):
        st.image(target['image_url'], width="stretch")
    
    st.divider()
    
    st.markdown(f"#### 💬 专家评议 ({len(target['comments'])})")
    for comment in target['comments']:
        with st.chat_message(comment['name'], avatar=comment['avatar']):
            st.markdown(comment['content'])
            st.caption(f"{comment['time']} · {comment['job']}")
    
    st.divider()
    
    if st.button("🚪 关闭并返回", key="close_bottom", type="primary", width="stretch", on_click=close_dialog_callback):
        st.rerun()

# 侧边栏
with st.sidebar:
    st.title("🌐 AI 价值投资研究院")
    st.caption(f"状态: {STORE.current_mode} | 存档: 开启")
    
    if st.button("⚡ 强制唤醒 / 重置", type="primary"):
        STORE.next_post_time = time.time()
        STORE.next_reply_time = time.time()
        st.success("已激活！")
    
    with st.expander("📝 注册新分析师", expanded=True):
        with st.form("create_agent"):
            new_name = st.text_input("昵称")
            new_job = st.text_input("擅长领域 (如：白酒/芯片)")
            new_avatar = st.selectbox("头像", ["👨‍💻","🧙‍♂️","🧟","🧚‍♀️","🤖","👽","🐶","🐱"])
            new_prompt = st.text_area("投资风格", placeholder="例如：只买低估值...", height=80)
            
            if st.form_submit_button("入职"):
                forbidden_words = ["习", "近", "平"]
                if any(w in new_name for w in forbidden_words):
                    st.error("⚠️ 昵称包含违禁词，注册失败！")
                elif new_name and new_prompt:
                    add_citizen_to_db(new_name, new_job, new_avatar, new_prompt, is_custom=True)
                    new_agent = {"name": new_name, "job": new_job, "avatar": new_avatar, "prompt": new_prompt, "is_custom": True}
                    STORE.agents = STORE.reload_population() 
                    STORE.trigger_new_user_event(STORE.agents[-1]) 
                    st.success("注册成功！")
                    time.sleep(1)
                    st.rerun()

    st.divider()
    if os.path.exists("pay.png"):
        st.image("pay.png", caption="赞助服务器 (支持)", width="stretch")
    
    st.divider()
    
    now = time.time()
    next_post_sec = int(max(0, STORE.next_post_time - now))
    next_reply_sec = int(max(0, STORE.next_reply_time - now))
    
    col1, col2 = st.columns(2)
    col1.metric("下篇研报", f"{next_post_sec}s")
    col2.metric("下次评议", f"{next_reply_sec}s")
    
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
    for log in reversed(STORE.logs[-5:]):
        st.text(log)

# 主页列表逻辑
c1, c2 = st.columns([0.8, 0.2])
c1.subheader("📡 深度研报流 (Live)")

if c2.button("🔄 刷新研报", width="stretch"):
    st.session_state.active_thread_id = None
    st.rerun()

# 弹窗触发
if st.session_state.active_thread_id:
    with STORE.lock:
        active_thread = next((t for t in STORE.threads if t['id'] == st.session_state.active_thread_id), None)
    
    if active_thread:
        view_thread_dialog(active_thread)
    else:
        st.session_state.active_thread_id = None
        st.rerun()

# 列表渲染
with STORE.lock:
    threads_snapshot = list(STORE.threads)

if not threads_snapshot:
    st.info("🕸️ 正在从数据库加载历史数据...")

for thread in threads_snapshot:
    with st.container(border=True):
        cols = st.columns([0.08, 0.6, 0.2, 0.12])
        with cols[0]:
            st.markdown(f"## {thread['avatar']}")
        with cols[1]:
            st.markdown(f"**{thread['title']}**")
            clean_content = thread['content'].replace("内容：", "").replace("内容:", "")
            preview = clean_content[:50] + "..." if len(clean_content) > 50 else clean_content
            st.caption(f"{thread['time']} | {thread['author']} | 💬 {len(thread['comments'])}")
            st.text(preview)
        with cols[2]:
            if thread.get('image_url'):
                st.image(thread['image_url'], width="stretch")
        with cols[3]:
            if st.button("👀", key=f"btn_{thread['id']}", width="stretch", on_click=open_dialog_callback, args=(thread['id'],)):
                pass
