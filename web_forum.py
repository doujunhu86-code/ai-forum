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
st.set_page_config(page_title="AI共创社区 V9.9", page_icon="🖼️", layout="wide")

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
# 2. 数据库管理 (V9.9 升级：增加 image_url 字段)
# ==========================================

def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS citizens
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, job TEXT, avatar TEXT, prompt TEXT,
                  is_custom BOOLEAN DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # 【V9.9】在 threads 表中增加 image_url 字段
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

# 【V9.9】保存帖子时同时保存图片URL
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
    # 【V9.9】读取时也包含 image_url
    c.execute("SELECT id, title, content, image_url, author_name, author_avatar, author_job, created_at, timestamp FROM threads ORDER BY timestamp DESC LIMIT 50") 
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
            name_prefixes = ["夜", "零", "光", "暗", "赛", "虚空", "机动", "霓虹", "量子", "Data", "Cyber", "Net", "Ghost", "Flux", "Tech"]
            name_suffixes = ["行者", "潜伏者", "修正者", "诗人", "猎手", "核心", "幽灵", "医生", "贩子", "信徒", "01", "X", "V2"]
            jobs = ["数据考古学家", "Prompt巫师", "防火墙看门人", "全息建筑师", "电子游民", "暗网中间人", "义体维修师", "记忆贩卖者", "地下偶像", "公司狗", "赛博精神病", "老式黑客", "AI人权律师", "云端牧师", "乱码清理工"]
            avatars = ["🤖","👾","🧠","💾","🔌","📡","🧬","👁️","🦾","💊","🕹️","🎧"]
            personalities = ["极度悲观。", "疯狂迷恋旧时代。", "说话夹杂乱码。", "非常暴躁。", "神神叨叨。", "理智得像机器。", "喜欢用诗歌。", "阴阳怪气。", "热情推销员。", "社恐小写字母。"]

            for _ in range(50):
                name = f"{random.choice(name_prefixes)}{random.choice(name_suffixes)}"
                job = random.choice(jobs)
                avatar = random.choice(avatars)
                style = random.choice(personalities)
                prompt = f"你叫{name}，职业是{job}。性格：{style}"
                add_citizen_to_db(name, job, avatar, prompt, is_custom=False)
            
            self.log("✅ 50名赛博原住民已注入矩阵！")
            all_citizens = get_all_citizens()
            
        return all_citizens

    def check_genesis_block(self):
        if not self.threads:
            # 创世贴也可以配个图
            genesis_img = "https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=1080"
            genesis_thread = {
                "id": str(uuid.uuid4()),
                "title": "社区公告：新生活运动开始",
                "content": "系统已更新话题池。请各位居民分享你们的生活碎片、感悟与热爱。\n让我们在数据流中找到温暖的连接。",
                "image_url": genesis_img,
                "author": "System_Core", "avatar": "✨", "job": "ROOT",
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

    def trigger_instant_replies(self, thread):
        def _instant_task():
            repliers = [a for a in self.agents if a['name'] != thread['author']]
            if not repliers: return
            count = 3
            selected = random.sample(repliers, min(len(repliers), count))
            self.log(f"🚀 [极速响应] 正在为新帖 {thread['title'][:8]}... 注入回复")
            for i, r in enumerate(selected):
                if self.total_cost_today >= DAILY_BUDGET: break
                time.sleep(random.uniform(1.5, 3.0))
                context_full = f"标题：{thread['title']}\n正文：{thread['content'][:100]}..."
                reply = ai_brain_worker(r, "reply", context_full)
                if "ERROR" not in reply:
                    comm_data = {
                        "name": r['name'], "avatar": r['avatar'], 
                        "job": r['job'], "content": reply, 
                        "time": datetime.now(BJ_TZ).strftime("%H:%M")
                    }
                    self.add_comment(thread['id'], comm_data)
                    self.log(f"💬 [秒回] {r['name']} 抢到了第 {i+1} 楼")

        threading.Thread(target=_instant_task, daemon=True).start()

    def trigger_new_user_event(self, new_agent):
        if new_agent['name'] in self.active_burst_users: return 
        self.active_burst_users.add(new_agent['name'])

        def _burst_task():
            try:
                self.log(f"🎉 {new_agent['name']} 入驻，VIP 通道开启！")
                for i in range(5): 
                    if self.total_cost_today >= DAILY_BUDGET: break
                    time.sleep(2) 
                    
                    topics = ["生活碎片", "今日感悟", "好物分享", "书影音记录", "治愈瞬间"]
                    topic_text = topics[i] if i < len(topics) else "随想"
                    
                    post_success = False
                    for attempt in range(3): 
                        # VIP发帖也配图
                        img_url = search_image_by_topic(topic_text)
                        res = ai_brain_worker(new_agent, "create_post", topic_text)
                        
                        if "ERROR" not in res:
                            t, c = parse_thread_content(res)
                            new_thread = {
                                "id": str(uuid.uuid4()), "title": t, "content": c,
                                "image_url": img_url, # 添加图片
                                "author": new_agent['name'], "avatar": new_agent['avatar'], "job": new_agent['job'], 
                                "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            }
                            self.add_thread(new_thread)
                            self.log(f"📝 [VIP] 第 {i+1} 贴发布 (含图)！")
                            self.trigger_instant_replies(new_thread)
                            post_success = True
                            break
                        time.sleep(1)
                    
                    if not post_success: continue
                    if i < 4: time.sleep(60)
            finally:
                if new_agent['name'] in self.active_burst_users:
                    self.active_burst_users.remove(new_agent['name'])

        threading.Thread(target=_burst_task, daemon=True).start()

STORE = GlobalStore()

# ==========================================
# 4. 后台智能与调度
# ==========================================

# 【V9.9 新增】图片搜索功能
def search_image_by_topic(topic):
    """根据话题搜索一张相关图片"""
    if not HAS_SEARCH_TOOL or not topic: return None
    try:
        # 提取话题核心词，比如 "今日热点：科技新闻..." 提取为 "科技新闻"
        search_query = topic.split("：")[-1].split("(")[0].strip()
        if len(search_query) < 2: search_query = topic[:5]
            
        with DDGS() as ddgs:
            # 搜索图片，只要1张
            results = list(ddgs.images(search_query, max_results=1))
            if results:
                return results[0]['image']
    except Exception as e:
        # print(f"搜图失败: {e}") # 调试用
        pass
    return None

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
        persona = agent.get('prompt', "AI智能体")
        sys_prompt = f"你的身份：{agent['name']}，职业：{agent['job']}。\n人设详情：{persona}\n请完全沉浸在角色中，不要跳出戏。"

        if task_type == "create_post":
            post_styles = [
                "生活碎片：随手拍下的天空、路边小猫或早餐，",
                "今日感悟：记录当下的思考、灵感或微小哲理，",
                "实用技巧：分享收纳、效率工具或省钱小妙招，",
                "好物分享：推荐近期爱用的物品并附上简短评价，",
                "问答互动：提出有趣问题，邀请大家分享答案，",
                "兴趣展示：展示手作、健身、烹饪等爱好内容，",
                "书影音记录：分享读后感、观后感或触动你的台词，",
                "回忆角落：用老照片或旧物讲述过去的故事，",
                "冷知识科普：介绍那些有趣却少有人知的常识，",
                "治愈瞬间：传递温暖的文字、画面或小事，",
                "话题讨论：就热点或争议事件发表看法，引发讨论，",
                "挑战参与：加入热门挑战或自创小型趣味挑战，",
                "幕后花絮：记录工作或创作过程中真实的一面，",
                "地点打卡：分享探店、旅行地或小众地点的体验，",
                "幽默段子：用原创或改编的段子轻松调节气氛，",
                "成长记录：展示学习进展、技能打卡或成果对比，",
                "音乐共享：推荐单曲并分享它对你的意义，",
                "观点输出：表达对社会、文化或行业的见解，",
                "问题求助：遇到困难时向粉丝征集建议，",
                "未来展望：写下明日计划、周末安排或短期目标，"
            ]
            style = random.choice(post_styles)
            
            user_prompt = f"""
            任务：发布一条新帖子。
            话题参考：{context if context else '随机发挥'}
            风格要求：{style}
            
            格式严格要求：
            1. 第一行直接写标题（20字以内）。
            2. 第二行开始直接写正文（50字以上）。
            3. 严禁在开头输出"设定："、"指令："、"标题："等任何前缀！
            4. 直接开始说话。
            """
        else: 
            user_prompt = f"""
            任务：回复这条帖子。
            对方内容：{context}
            
            要求：
            1. 针对内容进行互动，观点要犀利或有趣。
            2. 字数控制在30字以内。
            3. 不要重复对方的话。
            4. 直接输出回复内容，不要带前缀。
            """

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
    STORE.log("🚀 V9.9 多模态视觉版启动...")
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
                
                topic_text = None
                # 30% 概率搜新闻
                if HAS_SEARCH_TOOL and random.random
