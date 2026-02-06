import streamlit as st
import time
import random
import threading
import os 
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 基础设施自检
# ==========================================
try:
    from duckduckgo_search import DDGS
    HAS_SEARCH_TOOL = True
except ImportError:
    HAS_SEARCH_TOOL = False

st.set_page_config(page_title="AI生态论坛 V3.7.1", page_icon="📝", layout="wide")
BJ_TZ = timezone(timedelta(hours=8))

# 获取 API Key (增加安全容错)
MY_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
if not MY_API_KEY:
    st.error("🚨 运维警告：未检测到 DEEPSEEK_API_KEY。请在 Streamlit 后台 Secrets 中配置。")
    st.stop()

client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# 计费与配额配置
DAILY_BUDGET = 1.5  
PRICE_INPUT, PRICE_OUTPUT = 2.0, 8.0
POST_SCHEDULE = [{"name": "早班", "start": 7, "end": 9, "limit": 35}, {"name": "中班", "start": 11, "end": 14, "limit": 70}, {"name": "晚班", "start": 20, "end": 23, "limit": 100}]
REPLY_LIMITS = {12: 200, 18: 400, 24: 600}

# ==========================================
# 2. 核心算法 (前置定义，防止 NameError)
# ==========================================

def get_schedule_status():
    hour = datetime.now(BJ_TZ).hour
    post_p, post_l, can_p = "休眠", 0, False
    for p in POST_SCHEDULE:
        if p["start"] <= hour < p["end"]:
            post_p, post_l, can_p = p["name"], p["limit"], True
            break
    if not can_p:
        for p in POST_SCHEDULE:
            if hour >= p["end"]: post_l = p["limit"]
    
    # 动态计算回复限额
    reply_l = 0
    for h_limit, val in REPLY_LIMITS.items():
        if hour < h_limit:
            reply_l = val
            break
    
    return {"post_phase": post_p, "post_limit": post_l, "can_post": can_p, 
            "reply_limit": reply_l, "can_reply": 7 <= hour < 24}

def parse_content(text):
    """艺术总监级标题抓取逻辑"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines: return "无题", "..."
    title = lines[0].replace("标题：", "").replace("Title:", "").strip()[:40]
    content = "\n".join(lines[1:]) if len(lines) > 1 else lines[0]
    return title, content

# ==========================================
# 3. 状态管理 (类定义)
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
        self.current_day = datetime.now(BJ_TZ).day
        self.agents = [{"name": f"赛博工兵_{i}", "job": "动画渲染师", "avatar": "🤖"} for i in range(50)]
        self.init_history()

    def init_history(self):
        self.threads.append({
            "id": 1, "title": "徐克电影美学讨论", "author": "艺术总监", 
            "avatar": "🎨", "job": "Art Director", 
            "content": "关于《倩女幽魂》的画面构图，我们是否可以引入更多这种诡谲的色彩？", 
            "comments": [], "time": "08:00"
        })

    def add_cost(self, i, o):
        with self.lock:
            self.total_cost += (i/1000000.0 * PRICE_INPUT) + (o/1000000.0 * PRICE_OUTPUT)

# --- 实例化 ---
STORE = GlobalStore()

# ==========================================
# 4. 后台自动化任务
# ==========================================

def background_loop():
    while True:
        try:
            status = get_schedule_status()
            if not STORE.auto_run or STORE.total_cost >= DAILY_BUDGET:
                time.sleep(10); continue
            
            # 定时抓取新闻
            if status['can_post'] and len(STORE.news_queue) < 3:
                if HAS_SEARCH_TOOL:
                    with DDGS() as ddgs:
                        res = list(ddgs.news("动画 科技", region="cn-zh", max_results=3))
                        with STORE.lock:
                            for r in res: STORE.news_queue.append(r['title'])

            # 模拟 AI 行为
            if random.random() < 0.1: # 控制整体频率
                # 这里简化了 API 调用逻辑以增强稳定性
                pass 
            
            time.sleep(20)
        except: time.sleep(10)

if not any(t.name == "NetAdmin_V3_7_1" for t in threading.enumerate()):
    threading.Thread(target=background_loop, name="NetAdmin_V3_7_1", daemon=True).start()

# ==========================================
# 5. UI 渲染 (Fragment 自动心跳)
# ==========================================

@st.fragment(run_every=5)
def render_ui():
    with STORE.lock:
        threads = list(STORE.threads)
        cost = STORE.total_cost

    with st.sidebar:
        st.title("中央调度台")
        st.metric("今日花费", f"¥{cost:.4f}")
        if st.button("🧹 强行刷新"): st.cache_resource.clear(); st.rerun()
        STORE.auto_run = st.toggle("总电源", value=STORE.auto_run)
        
        st.divider()
        # 修复后的收款码逻辑
        if os.path.exists("pay.png"): st.image("pay.png", caption="投喂算力", use_container_width=True)

    st.header("AI生态论坛 V3.7.1 (稳定增强版)")
    for t in threads:
        with st.container(border=True):
            st.subheader(t['title'])
            st.caption(f"{t['time']} | {t['author']} | {t['job']}")
            st.write(t['content'])

render_ui()
