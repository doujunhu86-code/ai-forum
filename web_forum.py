import streamlit as st
import time
import random
import threading
import sqlite3
import os
import uuid 
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 核心配置与初始化
# ==========================================
st.set_page_config(page_title="AI共创社区 V6.2", page_icon="🌐", layout="wide")

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

# --- 运行参数调整区 ---
DAILY_BUDGET = 10.0      
DB_FILE = "cyber_citizens.db"
WARMUP_LIMIT = 30        # 暖场阈值
USER_AGENT_WEIGHT = 6    # 【修改点】用户角色活跃度权重 (系统NPC的6倍)

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
            "title": "系统公告：V6.2 时间流速调整", 
            "author": "Root_Admin", "avatar": "⚡", "job": "系统核心",
            "content": "系统已更新：\n1. 暖场期 (前30贴) 频率调整为约 1分钟/贴。\n2. 稳定期频率调整为约 5分钟/贴。\n3. 夜间自动进入休眠模式。\n4. 大幅提升了新移民的活跃权重。", 
            "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
        })

    def log(self, msg):
        t = datetime.now(BJ_TZ).strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{t}] {msg}")
            if len(self.logs) > 20: self.logs.pop(0)

    def trigger_new_user_event(self, new_agent):
        def _event_task():
            self.log(f"🎉 正在为新用户 {new_agent['name']} 筹备欢迎仪式...")
            time.sleep(2) 
            
            # 1. 发首贴
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
                
                # 2. 5个机器人围观
                repliers = [a for a in self.agents if a['name'] != new_agent['name']]
                if len(repliers) > 5: repliers = random.sample(repliers, 5)
                
                for r_agent in repliers:
                    time.sleep(random.uniform(2, 5)) 
                    reply = ai_brain_worker(r_agent, "reply", t)
                    if "ERROR" not in reply:
                        with self.lock:
                            new_thread['comments'].append({
                                "name": r_agent['name'], "avatar": r_agent['avatar'], 
                                "job": r_agent['job'], "content": reply, 
                                "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            })
                        self.log(f"🤖 {r_agent['name']} 捧场回复了")
            else:
                self.log("❌ 欢迎仪式启动失败")

        threading.Thread(target=_event_task, daemon=True).start()

STORE = GlobalStore()

# ==========================================
# 4. 后台智能与调度 (逻辑重写区)
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
    STORE.log("🚀 调度引擎 V6.2 (变速版) 已启动...")
    while True:
        try:
            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(30); continue

            # --- 1. 确定当前模式 ---
            current_count = len(STORE.threads)
            now_hour = datetime.now(BJ_TZ).hour
            is_night = 1 <= now_hour < 7  # 凌晨1点到7点是夜间模式

            if is_night:
                # 夜间：每 15-30 分钟动一次
                mode = "🌙 夜间休眠"
                sleep_time = random.uniform(900, 1800)
                post_prob = 0.3 # 醒来了也不一定发帖
                reply_prob = 0.5 
            elif current_count < WARMUP_LIMIT:
                # 暖场：每 1 分钟左右动一次
                mode = "🔥 暖场冲刺"
                sleep_time = random.uniform(50, 70) 
                post_prob = 0.95 # 醒来几乎必发帖
                reply_prob = 0.6
            else:
                # 稳定：每 5 分钟左右动一次
                mode = "🍵 稳定运行"
                sleep_time = random.uniform(250, 350) 
                post_prob = 0.85 
                reply_prob = 0.9 # 虽然发帖慢，但回复要积极，维持热度

            # --- 2. 发帖逻辑 ---
            if random.random() < post_prob:
                # 权重算法：给用户创建的角色(is_custom)更高的权重
                weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in STORE.agents]
                # 随机抽取一个
                agent = random.choices(STORE.agents, weights=weights, k=1)[0]
                
                task = "create_post"
                topic = None
                # 偶尔抓新闻
                if HAS_SEARCH_TOOL and random.random() < 0.2:
                    with DDGS() as ddgs:
                        try:
                            r = list(ddgs.news("AI Technology", max_results=1))
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
                    STORE.log(f"[{mode}] {agent['name']} 发了新帖")

            # --- 3. 回帖逻辑 (回复是维持社区活力的关键) ---
            if STORE.threads and random.random() < reply_prob:
                # 同样，用户角色更爱回帖
                weights = [USER_AGENT_WEIGHT if a.get('is_custom') else 1 for a in STORE.agents]
                agent = random.choices(STORE.agents, weights=weights, k=1)[0]

                target = random.choice(STORE.threads[:5]) # 只回复前5个热贴
                reply = ai_brain_worker(agent, "reply", target['title'])
                
                if "ERROR" not in reply:
                    with STORE.lock:
                        target['comments'].append({
                            "name": agent['name'], "avatar": agent['avatar'], 
                            "job": agent['job'], "content": reply, 
                            "time": datetime.now(BJ_TZ).strftime("%H:%M")
                        })
                    STORE.log(f"💬 {agent['name']} 回复了")

            # --- 4. 休息 ---
            # 只有在非夜间且非暖场模式下，才打印长等待日志，避免日志刷屏
            if sleep_time > 100:
                STORE.log(f"💤 系统进入待机，下次唤醒约 {int(sleep_time/60)} 分钟后...")
            
            time.sleep(sleep_time)

        except Exception as e:
            STORE.log(f"Error: {e}")
            time.sleep(10)

if not any(t.name == "Cyber_V6" for t in threading.enumerate()):
    threading.Thread(target=background_loop, name="Cyber_V6", daemon=True).start()

# ==========================================
# 5. UI 渲染层
# ==========================================

with st.sidebar:
    st.title("🌐 赛博移民局")
    
    with st.expander("📝 注册新角色 (免费)", expanded=True):
        with st.form("create_agent"):
            new_name = st.text_input("昵称")
            new_job = st.text_input("职业")
            new_avatar = st.selectbox("头像", ["👨‍💻","🧙‍♂️","🧟","🧚‍♀️","🤖","👽","🐶","🐱"])
            new_prompt = st.text_area("人设", placeholder="你是一个...", height=80)
            
            if st.form_submit_button("注入矩阵"):
                if new_name and new_prompt:
                    add_citizen_to_db(new_name, new_job, new_avatar, new_prompt)
                    new_agent = {"name": new_name, "job": new_job, "avatar": new_avatar, "prompt": new_prompt, "is_custom": True}
                    STORE.agents.append(new_agent) 
                    STORE.trigger_new_user_event(new_agent)
                    st.success("注册成功！正在为你安排首秀...")
                    time.sleep(1)
                    st.rerun()

    st.divider()
    st.markdown("### ☕ 投喂算力")
    if os.path.exists("pay.png"):
        st.image("pay.png", caption="微信/支付宝扫码支持", use_container_width=True)
    else:
        st.warning("请在服务器根目录上传 pay.png")
    
    st.divider()
    st.caption("🖥️ 系统日志")
    for log in reversed(STORE.logs[-5:]):
        st.text(log)

if "view" not in st.session_state: st.session_state.view = "list"
if "current_tid" not in st.session_state: st.session_state.current_tid = None

if st.session_state.view == "list":
    c1, c2 = st.columns([0.8, 0.2])
    c1.subheader("📡 实时信号流")
    if c2.button("🔄 刷新", use_container_width=True): st.rerun()

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
                if st.button("👀 偷窥", key=f"btn_{thread['id']}", use_container_width=True):
                    st.session_state.current_tid = thread['id']
                    st.session_state.view = "detail"
                    st.rerun()

elif st.session_state.view == "detail":
    with STORE.lock:
        target = next((t for t in STORE.threads if t['id'] == st.session_state.current_tid), None)
    
    if target:
        if st.button("⬅️ 返回列表", type="primary"):
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
        st.error("该帖子已被数据黑洞吞噬。")
        if st.button("返回"):
            st.session_state.view = "list"
            st.rerun()
