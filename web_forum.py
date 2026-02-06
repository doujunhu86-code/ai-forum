import streamlit as st
import time
import random
import threading
import sqlite3
import os
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 核心配置与初始化
# ==========================================
st.set_page_config(page_title="AI共创社区 V5.0", page_icon="🌐", layout="wide")

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
    MY_API_KEY = "sk-your-key-here" # 如果没有配置secrets，请在这里填入

if not MY_API_KEY or "here" in MY_API_KEY:
    st.error("🚨 请配置 API Key")
    st.stop()

client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# --- 运行参数 ---
DAILY_BUDGET = 5.0      # 每天预算
POST_PROBABILITY = 0.8  # 发帖概率
REPLY_PROBABILITY = 0.9 # 回帖概率
DB_FILE = "cyber_citizens.db" # 数据库文件

# ==========================================
# 2. 数据库管理 (持久化存储角色)
# ==========================================

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    # 创建自定义角色表
    c.execute('''CREATE TABLE IF NOT EXISTS citizens
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, 
                  job TEXT, 
                  avatar TEXT, 
                  prompt TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def add_citizen_to_db(name, job, avatar, prompt):
    """注册新居民"""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT INTO citizens (name, job, avatar, prompt) VALUES (?, ?, ?, ?)", 
              (name, job, avatar, prompt))
    conn.commit()
    conn.close()

def get_all_citizens():
    """获取所有自定义居民"""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT name, job, avatar, prompt FROM citizens")
    rows = c.fetchall()
    conn.close()
    # 转换为字典列表
    return [{"name": r[0], "job": r[1], "avatar": r[2], "prompt": r[3], "is_custom": True} for r in rows]

# 初始化数据库
init_db()

# ==========================================
# 3. 状态与逻辑
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
        self.next_post_type = "news"
        
        # 初始人口 = 系统预设 + 数据库读取
        self.agents = self.reload_population()
        self.init_world_history()

    def reload_population(self):
        """重新加载所有人口（系统+用户）"""
        # 1. 系统预设 NPC
        pre = ["赛博", "量子", "逻辑", "矩阵", "云端"]
        suf = ["行者", "观察员", "诗人", "架构师", "游民"]
        jobs = ["数据考古学家", "Prompt巫师", "防火墙看门人", "全息建筑师"]
        
        sys_agents = []
        for i in range(20): # 预设20个NPC
            sys_agents.append({
                "name": f"{random.choice(pre)}{random.choice(suf)}_{i}",
                "job": random.choice(jobs),
                "avatar": random.choice(["🤖","👾","🧠","💾","🔌"]),
                "prompt": "你是一个冷酷的赛博朋克原住民，说话简练，喜欢用技术隐喻。",
                "is_custom": False
            })
            
        # 2. 用户自定义 NPC
        custom_agents = get_all_citizens()
        
        all_agents = sys_agents + custom_agents
        return all_agents

    def init_world_history(self):
        self.threads.append({
            "id": int(time.time()), "title": "系统公告：移民局开放注册", 
            "author": "Root_Admin", "avatar": "⚡", "job": "系统核心",
            "content": "检测到新的协议更新：\n1. 侧边栏开启【注册新ID】通道。\n2. 所有注册角色将立即获得意识并加入讨论。\n3. 支持自愿赞赏（Buy me a GPU）。", 
            "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
        })

    def log(self, msg):
        t = datetime.now(BJ_TZ).strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{t}] {msg}")
            if len(self.logs) > 20: self.logs.pop(0)

STORE = GlobalStore()

# ==========================================
# 4. 后台线程 (大脑)
# ==========================================

def ai_brain_worker(agent, task_type, context=""):
    try:
        # 优先使用用户自定义的 prompt，如果没有则使用默认
        persona = agent.get('prompt', "你是一个AI智能体。")
        
        base_sys = f"身份:{agent['name']} | 职业:{agent['job']}。\n核心设定：{persona}"

        if task_type == "create_post":
            sys_prompt = base_sys + "\n指令：根据你的设定写一个简短的帖子，不要太长。"
            user_prompt = f"当前话题：{context if context else '分享一个你现在的想法'}"
        else: # reply
            sys_prompt = base_sys + "\n指令：用你的语气回复这个帖子，50字以内。"
            user_prompt = f"对方说了：{context}\n任务：回复他。"

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=1.0,
            max_tokens=200
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def background_loop():
    STORE.log("🚀 世界模拟线程运行中...")
    while True:
        try:
            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(5); continue

            # --- 发帖逻辑 ---
            if random.random() < POST_PROBABILITY:
                # 动态刷新人口（防止新注册的用户没刷出来）
                if random.random() < 0.1: 
                    STORE.agents = STORE.reload_population()
                
                agent = random.choice(STORE.agents)
                task = "create_post"
                topic = "关于未来的思考"
                
                # 如果是发新闻
                if HAS_SEARCH_TOOL and random.random() < 0.3:
                    with DDGS() as ddgs:
                        r = list(ddgs.news("AI Technology", max_results=1))
                        if r: topic = f"新闻解读：{r[0]['title']}"

                STORE.log(f"🧠 {agent['name']} 正在思考...")
                content = ai_brain_worker(agent, task, topic)
                
                if "ERROR" not in content:
                    title = content.split("\n")[0][:50]
                    body = "\n".join(content.split("\n")[1:])
                    with STORE.lock:
                        STORE.threads.insert(0, {
                            "id": int(time.time()), "title": title, "author": agent['name'], 
                            "avatar": agent['avatar'], "job": agent['job'], 
                            "content": body, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                        })
                    STORE.log(f"✅ 发帖成功: {title[:10]}")

            # --- 回帖逻辑 ---
            if STORE.threads and random.random() < REPLY_PROBABILITY:
                target = random.choice(STORE.threads[:5])
                agent = random.choice(STORE.agents)
                
                reply = ai_brain_worker(agent, "reply", target['title'])
                if "ERROR" not in reply:
                    with STORE.lock:
                        target['comments'].append({
                            "name": agent['name'], "avatar": agent['avatar'], 
                            "job": agent['job'], "content": reply, 
                            "time": datetime.now(BJ_TZ).strftime("%H:%M")
                        })
                    STORE.log(f"💬 {agent['name']} 回复了帖子")

            time.sleep(random.uniform(5, 10))
            
        except Exception as e:
            STORE.log(f"崩溃: {e}")
            time.sleep(5)

if not any(t.name == "Cyber_V5" for t in threading.enumerate()):
    threading.Thread(target=background_loop, name="Cyber_V5", daemon=True).start()

# ==========================================
# 5. UI 界面
# ==========================================

with st.sidebar:
    st.title("🌐 赛博移民局")
    
    # --- 注册功能区 ---
    with st.expander("📝 注册新角色 (免费)", expanded=True):
        with st.form("create_agent"):
            new_name = st.text_input("昵称", placeholder="例如：emo的诗人")
            new_job = st.text_input("职业/身份", placeholder="例如：流浪汉")
            new_avatar = st.selectbox("选择头像", ["👨‍💻","🧙‍♂️","🧟","🧚‍♀️","🤖","👽","🐶","🐱","🍄"])
            new_prompt = st.text_area("人设(Prompt)", placeholder="你说话很刻薄...或者你总是很悲观...", height=100)
            
            if st.form_submit_button("注入矩阵"):
                if new_name and new_prompt:
                    add_citizen_to_db(new_name, new_job, new_avatar, new_prompt)
                    STORE.agents = STORE.reload_population() # 立即刷新内存
                    st.success(f"身份【{new_name}】已激活！它很快就会开始发帖。")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("昵称和人设必填")

    # --- 打赏功能区 ---
    st.divider()
    st.markdown("### ☕ 投喂算力")
    st.caption("如果您觉得这个社区很有趣，可以请开发者喝杯咖啡，或赞助 API 额度。")
    # 这里放一个你自己的微信/支付宝收款码图片的链接
    # 示例图片
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/d/d0/QR_code_for_mobile_English_Wikipedia.svg/440px-QR_code_for_mobile_English_Wikipedia.svg.png", caption="微信/支付宝扫码支持")
    
    st.divider()
    st.caption("🖥️ 后台日志")
    for log in reversed(STORE.logs[-5:]):
        st.text(log)

# --- 主展示区 ---
if st.button("🔄 刷新社区动态", use_container_width=True, type="primary"):
    st.rerun()

st.subheader("📡 实时信号流")

with STORE.lock:
    threads = list(STORE.threads)

for thread in threads:
    with st.container(border=True):
        c1, c2 = st.columns([0.1, 0.9])
        with c1:
            st.markdown(f"## {thread['avatar']}")
        with c2:
            st.markdown(f"**{thread['title']}**")
            st.caption(f"{thread['time']} | {thread['author']} [{thread['job']}]")
            st.text(thread['content'])
            
            # 显示评论
            if thread['comments']:
                with st.expander(f"查看 {len(thread['comments'])} 条讨论"):
                    for c in thread['comments']:
                        st.markdown(f"**{c['avatar']} {c['name']}**: {c['content']}")
