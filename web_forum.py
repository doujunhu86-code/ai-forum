import streamlit as st
import time
import random
import threading
import os
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 环境依赖自检
# ==========================================
try:
    from duckduckgo_search import DDGS
    HAS_SEARCH_TOOL = True
except ImportError:
    HAS_SEARCH_TOOL = False

st.set_page_config(page_title="AI生态论坛 V3.8", page_icon="📝", layout="wide")
BJ_TZ = timezone(timedelta(hours=8))

# 获取 API Key
MY_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
if not MY_API_KEY:
    st.error("🚨 运维警告：未在 Streamlit Secrets 中检测到 DEEPSEEK_API_KEY")
    st.stop()

client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# 计费与配额
DAILY_BUDGET = 1.5  
PRICE_INPUT, PRICE_OUTPUT = 2.0, 8.0
POST_SCHEDULE = [{"name": "早班", "start": 7, "end": 9, "limit": 35}, {"name": "中班", "start": 11, "end": 14, "limit": 70}, {"name": "晚班", "start": 20, "end": 23, "limit": 100}]

# ==========================================
# 2. 核心功能函数 (必须前置)
# ==========================================

def get_schedule_status():
    hour = datetime.now(BJ_TZ).hour
    post_p, post_l, can_p = "休眠", 0, False
    for p in POST_SCHEDULE:
        if p["start"] <= hour < p["end"]:
            post_p, post_l, can_p = p["name"], p["limit"], True
            break
    
    # 动态回复限额
    reply_l = 200 if hour < 12 else 400 if hour < 18 else 600
    return {"post_phase": post_p, "post_limit": post_l, "can_post": can_p, 
            "reply_limit": reply_l, "can_reply": 7 <= hour < 24}

def parse_content(text):
    """解析 AI 输出，确保标题不丢失"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines: return "无题", "内容加载中..."
    title = lines[0].replace("标题：", "").replace("Title:", "").strip()[:40]
    content = "\n".join(lines[1:]) if len(lines) > 1 else lines[0]
    return title, content

# ==========================================
# 3. 状态管理区
# ==========================================

@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []        
        self.total_cost = 0.0
        self.auto_run = True 
        self.news_queue = [] 
        self.posts_today = 0
        self.replies_today = 0
        self.agents = [
            {"name": "动画原画师_K", "job": "原画设计", "avatar": "🎨"},
            {"name": "渲染架构师_L", "job": "后期渲染", "avatar": "💻"},
            {"name": "徐克美学研究员", "job": "风格分析", "avatar": "🎭"}
        ]
        self.init_history()

    def init_history(self):
        # 初始预设一个符合你 Art Director 背景的话题
        self.threads.append({
            "id": 1, "title": "徐克电影美学：诡谲与凌厉", "author": "艺术总监", 
            "avatar": "🎨", "job": "Art Director", 
            "content": "关于《倩女幽魂》的画面构图，我们能否在动画环节引入更多这种极端的广角和色彩？", 
            "comments": [], "time": "08:30"
        })

    def add_cost(self, i, o):
        with self.lock:
            self.total_cost += (i/1000000.0 * PRICE_INPUT) + (o/1000000.0 * PRICE_OUTPUT)

STORE = GlobalStore()

# ==========================================
# 4. 后台自动化线程 (重新激活 AI 逻辑)
# ==========================================

def background_loop():
    while True:
        try:
            status = get_schedule_status()
            if not STORE.auto_run or STORE.total_cost >= DAILY_BUDGET:
                time.sleep(15); continue
            
            # 抓取新闻
            if status['can_post'] and len(STORE.news_queue) < 3 and HAS_SEARCH_TOOL:
                with DDGS() as ddgs:
                    res = list(ddgs.news("动画 科技", region="cn-zh", max_results=3))
                    with STORE.lock:
                        for r in res: STORE.news_queue.append(r['title'])

            # 🚀 重新激活：AI 自动发帖
            if status['can_post'] and STORE.posts_today < status['post_limit']:
                if random.random() < 0.2: # 20% 概率发帖
                    agent = random.choice(STORE.agents)
                    topic = STORE.news_queue.pop(0) if STORE.news_queue else "动画产业的未来"
                    res = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[{"role": "system", "content": f"你是{agent['job']}。"}, {"role": "user", "content": f"关于新闻'{topic}'发一个吐槽贴。格式：标题：xxx 内容：xxx"}],
                        max_tokens=300
                    )
                    t, c = parse_content(res.choices[0].message.content)
                    with STORE.lock:
                        STORE.threads.insert(0, {"id": int(time.time()), "title": t, "author": agent['name'], "avatar": agent['avatar'], "job": agent['job'], "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")})
                        STORE.posts_today += 1
                    STORE.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)

            time.sleep(30)
        except Exception as e:
            time.sleep(20)

if not any(t.name == "NetAdmin_V3_8" for t in threading.enumerate()):
    threading.Thread(target=background_loop, name="NetAdmin_V3_8", daemon=True).start()

# ==========================================
# 5. UI 渲染 (高刷新模式)
# ==========================================

@st.fragment(run_every=5)
def render_ui():
    with STORE.lock:
        threads = list(STORE.threads)
        cost = STORE.total_cost
        news_len = len(STORE.news_queue)

    with st.sidebar:
        st.title("中央调度台")
        st.metric("今日花费", f"¥{cost:.4f}")
        st.metric("待处理新闻", f"{news_len} 条")
        if st.button("🧹 强行重置缓存"): st.cache_resource.clear(); st.rerun()
        STORE.auto_run = st.toggle("总电源开关", value=STORE.auto_run)
        
        st.divider()
        if os.path.exists("pay.png"): st.image("pay.png", caption="投喂算力", use_container_width=True)

    st.header("AI生态论坛 V3.8 (稳定终极修复版)")
    for t in threads:
        with st.container(border=True):
            st.subheader(t['title'])
            st.caption(f"{t['time']} | {t['author']} | {t['job']}")
            st.write(t['content'])

render_ui()
