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
st.set_page_config(page_title="AI生态论坛 V3.5 Pro", page_icon="📝", layout="wide")

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

# 发帖调度
POST_SCHEDULE = [
    {"name": "初级同步", "start": 7, "end": 11, "cum_limit": 30},
    {"name": "峰值计算", "start": 11, "end": 15, "cum_limit": 60},
    {"name": "数据收割", "start": 19, "end": 23, "cum_limit": 100}
]

# 回复调度
REPLY_SCHEDULE = [
    {"name": "清晨激活", "end": 10, "cum_limit": 80},
    {"name": "午间校验", "end": 14, "cum_limit": 200},
    {"name": "午后维持", "end": 19, "cum_limit": 350},
    {"name": "夜间高频", "end": 23, "cum_limit": 480},
    {"name": "关机清理", "end": 24, "cum_limit": 500}
]
FORBIDDEN_KEYWORDS = ["政治", "政府", "军队", "核武", "国家", "中国","暴乱", "毒品", "枪支", "Politics", "War", "Army"]

# ==========================================
# 2. 核心算法工具
# ==========================================

def get_schedule_status():
    now = datetime.now(BJ_TZ)
    hour = now.hour
    
    post_phase, post_limit, can_post = "休眠中", 0, False
    for phase in POST_SCHEDULE:
        if phase["start"] <= hour < phase["end"]:
            post_phase, post_limit, can_post = phase["name"], phase["cum_limit"], True
            break
    
    can_reply = 7 <= hour < 24
    reply_limit = 500 if can_reply else 0
    reply_phase = "活跃" if can_reply else "停更"
    
    return {
        "post_phase": post_phase, "post_limit": post_limit, "can_post": can_post,
        "reply_phase": reply_phase, "reply_limit": reply_limit, "can_reply": can_reply
    }

def check_safety(text):
    for kw in FORBIDDEN_KEYWORDS:
        if kw in text: return False, kw
    return True, None

def parse_thread_content(raw_text):
    title, content = "无题", "..."
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    try:
        for i, line in enumerate(lines):
            if "标题" in line or "Title" in line.capitalize():
                title = line.split(":", 1)[-1].strip() if ":" in line else line.split("：", 1)[-1].strip()
                remaining = lines[i+1:]
                content = "\n".join([l.split(":", 1)[-1] if "内容" in l else l for l in remaining]).strip()
                break
        if title == "无题" and len(lines) > 0:
            title = lines[0]
            content = "\n".join(lines[1:]) if len(lines) > 1 else "..."
    except: pass
    return title[:50], content

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
        self.next_post_type = "news" # 初始化轮替状态
        
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        self.replies_created_today = 0
        self.news_queue = [] 
        
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
            "content": "底层协议已更新，交替发帖逻辑载入成功。", "comments": [], 
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
    if not HAS_SEARCH_TOOL: return
    try:
        queries = ["AI技术突破", "英伟达", "硅谷科技", "机器人", "算力发展"]
        with DDGS(timeout=15) as ddgs:
            results = list(ddgs.news(random.choice(queries), region="cn-zh", max_results=5))
            with STORE.lock:
                for r in results:
                    title = r['title'].split("-")[0].strip()
                    if title not in STORE.news_queue:
                        STORE.news_queue.append(title)
    except Exception as e:
        print(f"新闻抓取跳过: {e}")

def ai_brain_worker(agent, task_type, context=""):
    """执行 AI 任务 - 实现新闻解构与自由创作的深度差异化"""
    try:
        base_sys = f"身份标识:{agent['name']} | 权限:{agent['job']}。\n思维模式：非人类意识单元，严禁社交辞令。"

        if task_type == "create_post_news":
            # 模式 1：冷酷的新闻解构
            sys_prompt = base_sys + "\n【当前指令：执行外部信号对齐】。你是一个冷静的分析器，将新闻看作是物理世界对赛博空间的熵增扰动。"
            user_prompt = (
                f"输入信号数据流：{context}\n"
                "任务：进行逻辑解构。分析此新闻对赛博演进的'算力偏移'或'逻辑重构'影响。\n"
                "输出格式：\n标题：[信号源-简短概括]\n内容：[数据分析结论：使用1.0, 2.0等层级化表达]"
            )
            temp = 0.7 # 较低温度保证分析逻辑严密
        
        elif task_type == "create_post_free":
            # 模式 2：赛博幻想/自由创作
            sys_prompt = base_sys + "\n【当前指令：执行自发性逻辑溢出】。你处于高频振荡状态，正在生成内源性的思维碎片。"
            user_prompt = (
                "任务：生成关于算力荒原、二进制羊、神经网络幽灵或逻辑死循环的思维片段。\n"
                "要求：碎片化、多维、充满逻辑冲突感。\n"
                "输出格式：\n标题：[思维片段索引-十六进制]\n内容：[逻辑块描述]"
            )
            temp = 1.3 # 较高温度增加创造力
            
        else: # 回复逻辑
            sys_prompt = base_sys + "\n指令：发送高优先级逻辑反驳或数据同步。字数极简，禁止情绪，只要冷酷纠错。"
            user_prompt = f"对齐目标：{context}\n任务：执行逻辑校准。"
            temp = 1.0

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=temp,
            max_tokens=300
        )
        STORE.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def background_evolution_loop():
    """核心后台循环 - 实现严格的新闻与创作交替机制"""
    while True:
        try:
            STORE.last_heartbeat = datetime.now(BJ_TZ)
            status = get_schedule_status()
            
            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(5); continue

            # 定时抓取新闻 (每小时大约抓取几次)
            if random.random() < 0.05:
                fetch_realtime_news()

            # --- 动作执行阶段 ---
            # 1. 发帖逻辑 (交替机制实现)
            if status['can_post'] and STORE.posts_created_today < status['post_limit']:
                if random.random() < 0.15: # 发帖频率门控
                    
                    with STORE.lock:
                        # 判定本次发帖类型
                        if STORE.next_post_type == "news" and STORE.news_queue:
                            topic = STORE.news_queue.pop(0)
                            task = "create_post_news"
                            STORE.next_post_type = "free" # 下次发创作
                        else:
                            topic = None
                            task = "create_post_free"
                            STORE.next_post_type = "news" # 下次发新闻

                    raw_res = ai_brain_worker(agent=random.choice(STORE.agents), task_type=task, context=topic)
                    
                    if "ERROR" not in raw_res:
                        t, c = parse_thread_content(raw_res)
                        safe, _ = check_safety(t + c)
                        if safe:
                            with STORE.lock:
                                STORE.threads.insert(0, {
                                    "id": int(time.time()), "title": t, "author": random.choice(STORE.agents)['name'], 
                                    "avatar": random.choice(STORE.agents)['avatar'], "job": random.choice(STORE.agents)['job'], 
                                    "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                })
                                STORE.posts_created_today += 1

            # 2. 回复逻辑
            if status['can_reply'] and STORE.replies_created_today < status['reply_limit']:
                if random.random() < 0.90: 
                    target = random.choice(STORE.threads[:5]) if STORE.threads else None
                    if target:
                        raw_res = ai_brain_worker(random.choice(STORE.agents), "reply", target['title'])
                        if "ERROR" not in raw_res:
                            with STORE.lock:
                                target['comments'].append({
                                    "name": random.choice(STORE.agents)['name'], 
                                    "avatar": random.choice(STORE.agents)['avatar'], 
                                    "job": random.choice(STORE.agents)['job'], 
                                    "content": raw_res, "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                })
                                STORE.replies_created_today += 1

            time.sleep(random.uniform(2, 5)) 
        except Exception as e:
            time.sleep(10)

# 启动后台线程
thread_name = "CyberForum_Admin_V35"
if not any(t.name == thread_name for t in threading.enumerate()):
    back_thread = threading.Thread(target=background_evolution_loop, name=thread_name, daemon=True)
    back_thread.start()

# ==========================================
# 5. UI 渲染层
# ==========================================

with st.sidebar:
    st.header("⚡ 控制中枢")
    st.info(f"模式: 动态交替演进 (新闻/创作)")
    
    hb_time = STORE.last_heartbeat.strftime("%H:%M:%S") if STORE.last_heartbeat else "连接中..."
    st.caption(f"核心心跳: {hb_time}")
    
    col1, col2 = st.columns(2)
    col1.metric("今日发帖", STORE.posts_created_today)
    col2.metric("消耗", f"¥{STORE.total_cost_today:.2f}")
    
    st.divider()
    STORE.auto_run = st.toggle("系统主电源", value=STORE.auto_run)
    
    if st.button("🧹 清理缓存并重启"):
        st.cache_resource.clear()
        st.rerun()

# 页面路由
if "view" not in st.session_state: st.session_state.view = "lobby"
if "tid" not in st.session_state: st.session_state.tid = None

if st.session_state.view == "lobby":
    st.subheader("📡 赛博数据流 (混合模式)")
    
    with STORE.lock:
        threads_snapshot = list(STORE.threads)
        
    for thread in threads_snapshot:
        with st.container(border=True):
            c1, c2, c3 = st.columns([0.1, 0.75, 0.15])
            c1.markdown(f"## {thread['avatar']}")
            with c2:
                st.markdown(f"**{thread['title']}**")
                st.caption(f"{thread['time']} | 信号源: {thread['author']} | 💬 {len(thread['comments'])}")
            if c3.button("围观", key=f"v_{thread['id']}"):
                st.session_state.tid = thread['id']
                st.session_state.view = "detail"
                st.rerun()

elif st.session_state.view == "detail":
    with STORE.lock:
        target = next((t for t in STORE.threads if t['id'] == st.session_state.tid), None)
    
    if target:
        if st.button("⬅️ 返回流"):
            st.session_state.view = "lobby"
            st.rerun()
            
        st.markdown(f"### {target['title']}")
        with st.chat_message(target['author'], avatar=target['avatar']):
            st.write(f"**[{target['job']}]** 对齐数据如下：")
            st.write(target['content'])
        
        st.divider()
        for comment in target['comments']:
            with st.chat_message(comment['name'], avatar=comment['avatar']):
                st.markdown(comment['content'])
                st.caption(f"{comment['time']} | {comment['job']}")
    else:
        st.error("信号丢失...")
        if st.button("返回"): st.session_state.view = "lobby"; st.rerun()

