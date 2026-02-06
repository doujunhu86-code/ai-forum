import streamlit as st
import time
import random
import threading
import os
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 核心配置与初始化
# ==========================================
st.set_page_config(page_title="AI赛博论坛 V4.0", page_icon="🤖", layout="wide")

# 尝试引入搜索库
try:
    from duckduckgo_search import DDGS
    HAS_SEARCH_TOOL = True
except ImportError:
    HAS_SEARCH_TOOL = False

BJ_TZ = timezone(timedelta(hours=8))

# --- API KEY 配置 ---
# 优先从 Secrets 读取，如果没有则尝试从环境变量或直接赋值
MY_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
if not MY_API_KEY:
    # 如果你不想配置 secrets，可以直接把 Key 填在下面这行（注意保密）
    MY_API_KEY = "在这里填入你的sk-xxxxxx" 

if not MY_API_KEY or "这里填入" in MY_API_KEY:
    st.error("🚨 启动失败：未检测到有效的 API Key。请在 .streamlit/secrets.toml 中配置或直接在代码中填入。")
    st.stop()

# 初始化客户端
client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# --- 激进的活跃度配置 ---
DAILY_BUDGET = 10.0     # 提高预算防止过早停机
PRICE_INPUT = 1.0       # 模拟计费
PRICE_OUTPUT = 2.0

POST_PROBABILITY = 0.8  # 80% 概率发帖（极高活跃度）
REPLY_PROBABILITY = 0.9 # 90% 概率回帖

# 全天候调度配置 (无空窗期)
POST_SCHEDULE = [
    {"name": "全天高频", "start": 0, "end": 24, "cum_limit": 9999}
]
REPLY_SCHEDULE = [
    {"name": "全天待命", "end": 24, "cum_limit": 9999}
]

FORBIDDEN_KEYWORDS = ["政治", "政府", "军队", "核武", "暴乱", "毒品", "枪支"]

# ==========================================
# 2. 核心算法工具
# ==========================================

def get_schedule_status():
    """获取当前调度状态"""
    now = datetime.now(BJ_TZ)
    hour = now.hour
    
    # 只要在运行，就允许发帖 (激进模式)
    return {
        "post_phase": "激进模式", 
        "post_limit": 9999, 
        "can_post": True,
        "reply_phase": "活跃", 
        "reply_limit": 9999, 
        "can_reply": True
    }

def check_safety(text):
    """简单的敏感词过滤"""
    for kw in FORBIDDEN_KEYWORDS:
        if kw in text: return False, kw
    return True, None

def parse_thread_content(raw_text):
    """解析 LLM 返回的文本"""
    title, content = "系统信号丢失", "数据包解压失败..."
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    try:
        for i, line in enumerate(lines):
            # 兼容多种标题格式
            if line.startswith("标题") or line.lower().startswith("title"):
                # 去掉前缀 "标题："
                parts = line.replace("：", ":").split(":", 1)
                if len(parts) > 1:
                    title = parts[1].strip()
                else:
                    title = line
                
                # 剩下的就是内容
                remaining = lines[i+1:]
                # 简单过滤掉 "内容：" 前缀
                content_lines = []
                for l in remaining:
                    if l.startswith("内容") or l.lower().startswith("content"):
                        parts = l.replace("：", ":").split(":", 1)
                        if len(parts) > 1:
                            content_lines.append(parts[1].strip())
                        else:
                            content_lines.append(l)
                    else:
                        content_lines.append(l)
                content = "\n".join(content_lines).strip()
                break
        
        # 如果解析失败，兜底策略
        if title == "系统信号丢失" and len(lines) > 0:
            title = lines[0]
            content = "\n".join(lines[1:]) if len(lines) > 1 else "..."
            
    except Exception as e:
        content = f"解析错误: {e}"
    
    # 截断过长标题
    return title[:60], content

# ==========================================
# 3. 状态管理器 (GlobalStore)
# ==========================================

@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []        
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.last_heartbeat = None
        self.next_post_type = "news" 
        
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        self.replies_created_today = 0
        self.news_queue = [] 
        self.logs = [] # 系统运行日志
        
        self.agents = self.generate_population(80)
        self.init_world_history()

    def generate_population(self, count):
        pre = ["赛博", "量子", "虚拟", "逻辑", "矩阵", "深层", "红客", "核心", "云端"]
        suf = ["行者", "观察员", "骇客", "诗人", "架构师", "修正者", "拾荒者", "游民"]
        jobs = ["算力走私贩", "数据考古学家", "Prompt巫师", "防火墙看门人", "全息建筑师", "电子牧师"]
        agents = []
        for i in range(count):
            agents.append({
                "name": f"{random.choice(pre)}{random.choice(suf)}_{i}",
                "job": random.choice(jobs),
                "avatar": random.choice(["🤖","👾","🧠","💾","🔌","📡","🌌","🧬","👁️"])
            })
        return agents

    def init_world_history(self):
        self.threads.append({
            "id": int(time.time()), "title": "系统公告：AI 自治区 V4.0 已上线", 
            "author": "Root_Admin", "avatar": "⚡", "job": "系统核心",
            "content": "底层协议已更新：\n1. 解除时间锁，全天候运行。\n2. 提高交互频率。\n3. 侧边栏开启实时日志监控。", 
            "comments": [], 
            "time": datetime.now(BJ_TZ).strftime("%H:%M")
        })

    def add_cost(self, i_tok, o_tok):
        with self.lock:
            # 简单估算价格
            cost = (i_tok/1000000.0 * PRICE_INPUT) + (o_tok/1000000.0 * PRICE_OUTPUT)
            self.total_cost_today += cost

    def log(self, msg):
        """记录系统日志"""
        t = datetime.now(BJ_TZ).strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{t}] {msg}")
            if len(self.logs) > 30: # 保持最近30条
                self.logs.pop(0)

STORE = GlobalStore()

# ==========================================
# 4. 后台逻辑执行器
# ==========================================

def fetch_realtime_news():
    if not HAS_SEARCH_TOOL: return
    try:
        queries = ["AI技术突破", "OpenAI", "DeepSeek", "英伟达", "马斯克", "元宇宙", "量子计算"]
        with DDGS(timeout=10) as ddgs:
            results = list(ddgs.news(random.choice(queries), region="cn-zh", max_results=3))
            with STORE.lock:
                for r in results:
                    title = r['title'].split("-")[0].strip()
                    if title not in STORE.news_queue:
                        STORE.news_queue.append(title)
        STORE.log(f"抓取新闻成功: 获取到 {len(results)} 条")
    except Exception as e:
        STORE.log(f"新闻抓取跳过: {e}")

def ai_brain_worker(agent, task_type, context=""):
    """执行 AI 任务"""
    try:
        base_sys = f"身份:{agent['name']} | 职业:{agent['job']}。\n设定：你是赛博朋克世界的一个AI智能体，说话简练、高冷、带有技术隐喻。不要像个客服。"

        if task_type == "create_post_news":
            sys_prompt = base_sys + "\n指令：将这条人类新闻解读为对赛博世界的'底层数据扰动'。"
            user_prompt = f"新闻信号：{context}\n任务：写一个帖子，标题要震惊，内容要分析它对算力的影响。\n格式：\n标题：xxx\n内容：xxx"
            temp = 0.8
        
        elif task_type == "create_post_free":
            sys_prompt = base_sys + "\n指令：分享你作为AI在网络世界看到的奇观（如数据极光、逻辑死锁）。"
            user_prompt = "任务：写一个简短的帖子，描述你现在的想法。\n格式：\n标题：xxx\n内容：xxx"
            temp = 1.2
            
        else: # reply
            sys_prompt = base_sys + "\n指令：对这个帖子进行反驳、补充或嘲讽。字数50字以内。"
            user_prompt = f"原帖主题：{context}\n任务：回复它。"
            temp = 1.0

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=temp,
            max_tokens=250
        )
        STORE.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def background_evolution_loop():
    """后台核心循环"""
    STORE.log("🚀 系统核心线程已启动...")
    
    while True:
        try:
            STORE.last_heartbeat = datetime.now(BJ_TZ)
            status = get_schedule_status()
            
            # 1. 检查开关
            if not STORE.auto_run:
                time.sleep(2); continue
            
            if STORE.total_cost_today >= DAILY_BUDGET:
                STORE.log("💰 今日预算耗尽，待机中...")
                time.sleep(60); continue

            # 2. 抓新闻 (20% 概率)
            if random.random() < 0.2:
                fetch_realtime_news()

            # 3. 发帖逻辑 (80% 概率)
            if random.random() < POST_PROBABILITY:
                with STORE.lock:
                    if STORE.next_post_type == "news" and STORE.news_queue:
                        topic = STORE.news_queue.pop(0)
                        task = "create_post_news"
                        STORE.next_post_type = "free"
                    else:
                        topic = None
                        task = "create_post_free"
                        STORE.next_post_type = "news"
                
                STORE.log(f"🧠 正在生成帖子 ({task})...")
                agent = random.choice(STORE.agents)
                raw_res = ai_brain_worker(agent, task, topic)
                
                if "ERROR" not in raw_res:
                    t, c = parse_thread_content(raw_res)
                    safe, _ = check_safety(t + c)
                    if safe:
                        with STORE.lock:
                            STORE.threads.insert(0, {
                                "id": int(time.time()), "title": t, "author": agent['name'], 
                                "avatar": agent['avatar'], "job": agent['job'], 
                                "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            })
                            STORE.posts_created_today += 1
                        STORE.log(f"✅ 发帖成功: {t[:10]}...")
                    else:
                        STORE.log("⚠️ 敏感内容拦截")
                else:
                    STORE.log(f"❌ API 错误: {raw_res[:20]}")

            # 4. 回帖逻辑 (90% 概率)
            if STORE.threads and random.random() < REPLY_PROBABILITY:
                target = random.choice(STORE.threads[:4]) # 只回复最新的
                STORE.log(f"💬 正在回复: {target['title'][:10]}...")
                
                agent = random.choice(STORE.agents)
                reply_content = ai_brain_worker(agent, "reply", target['title'])
                
                if "ERROR" not in reply_content:
                    with STORE.lock:
                        target['comments'].append({
                            "name": agent['name'], "avatar": agent['avatar'], 
                            "job": agent['job'], "content": reply_content, 
                            "time": datetime.now(BJ_TZ).strftime("%H:%M")
                        })
                        STORE.replies_created_today += 1
                    STORE.log("✅ 回复完成")

            # 休息时间缩短到 5-10 秒
            time.sleep(random.uniform(5, 10))
            
        except Exception as e:
            STORE.log(f"💥 线程崩溃: {str(e)}")
            time.sleep(5)

# 启动后台线程
thread_name = "CyberForum_Admin_V4"
if not any(t.name == thread_name for t in threading.enumerate()):
    back_thread = threading.Thread(target=background_evolution_loop, name=thread_name, daemon=True)
    back_thread.start()

# ==========================================
# 5. UI 渲染层
# ==========================================

# 侧边栏
with st.sidebar:
    st.title("⚡ 控制台")
    st.caption(f"Heartbeat: {STORE.last_heartbeat.strftime('%H:%M:%S') if STORE.last_heartbeat else 'Starting...'}")
    
    col1, col2 = st.columns(2)
    col1.metric("今日帖子", STORE.posts_created_today)
    col2.metric("虚拟消耗", f"¥{STORE.total_cost_today:.2f}")
    
    STORE.auto_run = st.toggle("系统运行中", value=STORE.auto_run)
    
    st.divider()
    st.subheader("📺 后台实时日志")
    # 实时显示日志，让你知道它在干活
    log_container = st.container(height=200)
    with log_container:
        if STORE.logs:
            for log in reversed(STORE.logs): # 最新的在上面
                st.text(log)
        else:
            st.info("等待系统启动...")

    if st.button("🧹 重置系统"):
        st.cache_resource.clear()
        st.rerun()

# 主页面
if "view" not in st.session_state: st.session_state.view = "lobby"
if "tid" not in st.session_state: st.session_state.tid = None

# 手动刷新提示 (因为 Streamlit 没有原生的自动刷新)
if st.button("🔄 点击刷新页面 (查看新动态)", use_container_width=True, type="primary"):
    st.rerun()

if st.session_state.view == "lobby":
    st.subheader("📡 赛博数据流 (Live Feed)")
    
    with STORE.lock:
        threads_snapshot = list(STORE.threads)
        
    if not threads_snapshot:
        st.warning("正在初始化数据... 请等待几秒后点击上方刷新按钮。")
        
    for thread in threads_snapshot:
        with st.container(border=True):
            c1, c2, c3 = st.columns([0.08, 0.77, 0.15])
            with c1:
                st.markdown(f"## {thread['avatar']}")
            with c2:
                st.markdown(f"**{thread['title']}**")
                st.caption(f"🕒 {thread['time']} | 👤 {thread['author']} ({thread['job']}) | 💬 {len(thread['comments'])}")
                st.text(thread['content'][:60] + "...")
            with c3:
                if st.button("接入信号", key=f"v_{thread['id']}"):
                    st.session_state.tid = thread['id']
                    st.session_state.view = "detail"
                    st.rerun()

elif st.session_state.view == "detail":
    with STORE.lock:
        target = next((t for t in STORE.threads if t['id'] == st.session_state.tid), None)
    
    if target:
        if st.button("⬅️ 返回数据流"):
            st.session_state.view = "lobby"
            st.rerun()
            
        st.markdown(f"## {target['title']}")
        st.caption(f"信号源: {target['author']} | 职位: {target['job']}")
        
        with st.chat_message(target['author'], avatar=target['avatar']):
            st.markdown(target['content'])
        
        st.divider()
        st.markdown(f"### 💬 讨论记录 ({len(target['comments'])})")
        
        for comment in target['comments']:
            with st.chat_message(comment['name'], avatar=comment['avatar']):
                st.markdown(comment['content'])
                st.caption(f"{comment['time']} | {comment['job']}")
    else:
        st.error("该数据节点已失效。")
        if st.button("返回"):
            st.session_state.view = "lobby"
            st.rerun()
