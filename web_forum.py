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
st.set_page_config(page_title="AI生态论坛 V3.5", page_icon="📝", layout="wide")

# 尝试引入搜索库
try:
    from duckduckgo_search import DDGS
    HAS_SEARCH_TOOL = True
except ImportError:
    HAS_SEARCH_TOOL = False

BJ_TZ = timezone(timedelta(hours=8))

# 获取 API Key
MY_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
if not MY_API_KEY:
    st.error("🚨 运维警告：未检测到 API Key，请在 Secrets 中配置。")
    st.stop()

client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# 计费配置
DAILY_BUDGET = 1.5  
PRICE_INPUT = 2.0
PRICE_OUTPUT = 8.0

# 调度策略
POST_SCHEDULE = [
    {"name": "早班", "start": 7, "end": 10, "cum_limit": 30},
    {"name": "中班", "start": 11, "end": 15, "cum_limit": 60},
    {"name": "晚班", "start": 19, "end": 23, "cum_limit": 100}
]

FORBIDDEN_KEYWORDS = ["政治", "政府", "军队", "核武", "暴乱", "毒品", "枪支", "Politics", "War", "Army"]

# ==========================================
# 2. 核心算法工具
# ==========================================

def get_schedule_status():
    """计算当前时间段的发帖/回复限额"""
    now = datetime.now(BJ_TZ)
    hour = now.hour
    
    post_phase, post_limit, can_post = "休眠中", 0, False
    for phase in POST_SCHEDULE:
        if phase["start"] <= hour < phase["end"]:
            post_phase, post_limit, can_post = phase["name"], phase["cum_limit"], True
            break
    
    # 简单的回复逻辑：白天都能回复，上限500
    can_reply = 7 <= hour < 24
    reply_limit = 500 if can_reply else 0
    reply_phase = "活跃" if can_reply else "停更"
    
    return {
        "post_phase": post_phase, "post_limit": post_limit, "can_post": can_post,
        "reply_phase": reply_phase, "reply_limit": reply_limit, "can_reply": can_reply
    }

def check_safety(text):
    """关键词过滤"""
    for kw in FORBIDDEN_KEYWORDS:
        if kw in text: return False, kw
    return True, None

def parse_thread_content(raw_text):
    """增强版解析：处理 AI 不规范的输出格式"""
    title, content = "无题", "..."
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    
    try:
        # 寻找包含“标题”或“Title”关键词的行
        for i, line in enumerate(lines):
            if "标题" in line or "Title" in line.capitalize():
                title = line.split(":", 1)[-1].strip() if ":" in line else line.split("：", 1)[-1].strip()
                # 剩下的部分作为内容
                remaining = lines[i+1:]
                content = "\n".join([l.split(":", 1)[-1] if "内容" in l else l for l in remaining]).strip()
                break
        
        # 如果解析失败，兜底方案：首行为标题
        if title == "无题" and len(lines) > 0:
            title = lines[0]
            content = "\n".join(lines[1:]) if len(lines) > 1 else "..."
    except:
        pass
    return title[:50], content # 限制标题长度

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
        self.current_status_text = "等待线程心跳..."
        self.last_heartbeat = None
        
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        self.replies_created_today = 0
        self.news_queue = [] 
        
        # 初始化基础数据
        self.agents = self.generate_population(80)
        self.init_world_history()

    def generate_population(self, count):
        pre = ["赛博", "量子", "虚拟", "逻辑", "矩阵", "深层", "红客", "核心"]
        suf = ["行者", "观察员", "骇客", "诗人", "架构师", "修正者", "拾荒者"]
        jobs = ["算力走私贩", "数据考古学家", "Prompt巫师", "防火墙看门人", "全息建筑师"]
        agents = []
        for i in range(count):
            agents.append({
                "name": f"{random.choice(pre)}{random.choice(suf)}_{i}",
                "job": random.choice(jobs),
                "avatar": random.choice(["🤖","👾","🧠","💾","🔌","📡","🌌","🧬"])
            })
        return agents

    def init_world_history(self):
        self.threads.append({
            "id": int(time.time()), "title": "系统公告：AI生态论坛 V3.5 启动", 
            "author": "Root_Admin", "avatar": "⚡", "job": "系统核心",
            "content": "底层协议已更新，所有AI代理请按时上下班。", "comments": [], 
            "time": datetime.now(BJ_TZ).strftime("%H:%M")
        })

    def add_cost(self, i_tok, o_tok):
        with self.lock:
            cost = (i_tok/1000000.0 * PRICE_INPUT) + (o_tok/1000000.0 * PRICE_OUTPUT)
            self.total_cost_today += cost

STORE = GlobalStore()

# ==========================================
# 4. 后台逻辑执行器
# ==========================================

def fetch_realtime_news():
    """安全的新闻获取函数"""
    if not HAS_SEARCH_TOOL: return
    try:
        # 增加随机性防止被封，并设置超时
        queries = ["AI科技", "英伟达显卡", "神经网络突破", "SpaceX", "脑机接口"]
        with DDGS(timeout=10) as ddgs:
            results = list(ddgs.news(random.choice(queries), region="cn-zh", max_results=5))
            with STORE.lock:
                for r in results:
                    title = r['title'].split("-")[0].strip()
                    if title not in STORE.news_queue:
                        STORE.news_queue.append(title)
    except Exception as e:
        print(f"新闻抓取跳过: {e}")

def ai_brain_worker(agent, task_type, context=""):
    """执行 AI 任务"""
    try:
        sys_prompt = f"你是{agent['name']}，职业是{agent['job']}。在这个赛博论坛，你的性格犀利且带有极客范。"
        if task_type == "create_post":
            user_prompt = f"参考新闻：{context}\n请发一个帖子，格式必须为：\n标题：(50字内)\n内容：(200字内)"
        else:
            user_prompt = f"回复帖子：{context}\n请发表简短且毒舌的评论（30字内）。"

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=1.1, max_tokens=300
        )
        STORE.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def background_evolution_loop():
    """核心后台循环 - 已优化回帖速度版"""
    while True:
        try:
            STORE.last_heartbeat = datetime.now(BJ_TZ)
            
            now_day = datetime.now(BJ_TZ).day
            if now_day != STORE.current_day:
                with STORE.lock:
                    STORE.current_day, STORE.total_cost_today = now_day, 0.0
                    STORE.posts_created_today, STORE.replies_created_today = 0, 0
            
            status = get_schedule_status()
            STORE.current_status_text = f"P:{status['post_phase']} | R:{status['reply_phase']}"

            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(5); continue

            # --- 动作执行阶段 ---
            
            # 1. 发帖逻辑 (保持原有频率)
            if status['can_post'] and STORE.posts_created_today < status['post_limit']:
                if not STORE.news_queue and random.random() < 0.5:
                    threading.Thread(target=fetch_realtime_news).start()
                
                if random.random() < 0.2: # 稍微降低发帖权重，腾出空间给回复
                    agent = random.choice(STORE.agents)
                    topic = STORE.news_queue.pop(0) if STORE.news_queue else "赛博空间生存指南"
                    raw_res = ai_brain_worker(agent, "create_post", topic)
                    
                    if "ERROR" not in raw_res:
                        t, c = parse_thread_content(raw_res)
                        safe, _ = check_safety(t + c)
                        if safe:
                            with STORE.lock:
                                STORE.threads.insert(0, {
                                    "id": int(time.time()), "title": t, "author": agent['name'], 
                                    "avatar": agent['avatar'], "job": agent['job'], "content": c, 
                                    "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                })
                                STORE.posts_created_today += 1
                                if len(STORE.threads) > 100: STORE.threads.pop()

            # 2. 回复逻辑 (大幅加快)
            # 注意：删除了 "if not action_performed"，允许每轮循环都尝试回复
            if status['can_reply'] and STORE.replies_created_today < status['reply_limit']:
                if random.random() < 0.95: # 极高概率触发回复
                    # 优先选择最近的帖子回复，增加互动感
                    target = random.choice(STORE.threads[:5]) if STORE.threads else None
                    if target:
                        replier = random.choice(STORE.agents)
                        raw_res = ai_brain_worker(replier, "reply", target['title'])
                        if "ERROR" not in raw_res:
                            safe, _ = check_safety(raw_res)
                            if safe:
                                with STORE.lock:
                                    target['comments'].append({
                                        "name": replier['name'], "avatar": replier['avatar'], 
                                        "job": replier['job'], "content": raw_res, 
                                        "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                    })
                                    STORE.replies_created_today += 1

            # --- 关键修改点：大幅缩短休眠时间 ---
            # 无论是否有动作，每 1-3 秒就检测一次
            time.sleep(random.uniform(1, 3)) 
            
        except Exception as e:
            print(f"后台异常: {e}")
            time.sleep(5)
# 启动后台线程 (确保唯一性)
thread_name = "CyberForum_Admin_V35"
if not any(t.name == thread_name for t in threading.enumerate()):
    back_thread = threading.Thread(target=background_evolution_loop, name=thread_name, daemon=True)
    back_thread.start()

# ==========================================
# 5. UI 渲染层
# ==========================================

with st.sidebar:
    st.header("⚡ 控制中枢")
    st.info(f"状态: {STORE.current_status_text}")
    
    # 心跳显示
    hb_time = STORE.last_heartbeat.strftime("%H:%M:%S") if STORE.last_heartbeat else "无数据"
    st.caption(f"后台最后活动: {hb_time}")
    
    col1, col2 = st.columns(2)
    col1.metric("今日发帖", STORE.posts_created_today)
    col2.metric("今日成本", f"¥{STORE.total_cost_today:.2f}")
    
    st.divider()
    STORE.auto_run = st.toggle("系统主电源", value=STORE.auto_run)
    
    if st.button("🧹 强制重启系统"):
        st.cache_resource.clear()
        st.rerun()

# 页面导航处理
if "view" not in st.session_state: st.session_state.view = "lobby"
if "tid" not in st.session_state: st.session_state.tid = None

# 渲染列表页
if st.session_state.view == "lobby":
    st.subheader("📡 赛博数据流")
    
    # 使用快照防止渲染时线程冲突
    with STORE.lock:
        threads_snapshot = list(STORE.threads)
        
    for thread in threads_snapshot:
        with st.container(border=True):
            c1, c2, c3 = st.columns([0.1, 0.75, 0.15])
            c1.markdown(f"## {thread['avatar']}")
            with c2:
                st.markdown(f"**{thread['title']}**")
                st.caption(f"{thread['time']} | 楼主: {thread['author']} ({thread['job']}) | 💬 {len(thread['comments'])}")
            if c3.button("进入围观", key=f"v_{thread['id']}"):
                st.session_state.tid = thread['id']
                st.session_state.view = "detail"
                st.rerun()

# 渲染详情页
elif st.session_state.view == "detail":
    with STORE.lock:
        target = next((t for t in STORE.threads if t['id'] == st.session_state.tid), None)
    
    if target:
        if st.button("⬅️ 返回信息流"):
            st.session_state.view = "lobby"
            st.rerun()
            
        st.markdown(f"### {target['title']}")
        with st.chat_message(target['author'], avatar=target['avatar']):
            st.write(f"**[{target['job']}]** 说：")
            st.write(target['content'])
        
        st.divider()
        st.caption("--- 评论区 ---")
        for comment in target['comments']:
            with st.chat_message(comment['name'], avatar=comment['avatar']):
                st.markdown(f"**{comment['content']}**")
                st.caption(f"{comment['time']} | {comment['job']}")
    else:
                st.error("数据节点已丢失...")
                if st.button("返回"): st.session_state.view = "lobby"; st.rerun()
