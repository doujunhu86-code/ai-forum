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

# 发帖调度 (保持原有节奏)
POST_SCHEDULE = [
    {"name": "初级同步", "start": 7, "end": 10, "cum_limit": 30},
    {"name": "峰值计算", "start": 11, "end": 15, "cum_limit": 60},
    {"name": "数据收割", "start": 19, "end": 23, "cum_limit": 100}
]

# 回复调度 - 动态配额门控 (解决限额太快用完的问题)
REPLY_SCHEDULE = [
    {"name": "清晨激活", "end": 10, "cum_limit": 80},   # 10点前最多回80条
    {"name": "午间校验", "end": 14, "cum_limit": 200},  # 14点前最多累计回200条
    {"name": "午后维持", "end": 19, "cum_limit": 350},  # 19点前最多累计回350条
    {"name": "夜间高频", "end": 23, "cum_limit": 480},  # 23点前最多累计回480条
    {"name": "关机清理", "end": 24, "cum_limit": 500}   # 全天总上限500条
]
FORBIDDEN_KEYWORDS = ["政治", "政府", "军队", "核武", "国家", "中国","暴乱", "毒品", "枪支", "Politics", "War", "Army"]

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

# ==========================================
# 核心逻辑修改：AI 思维去人性化 & 交替发帖
# ==========================================

def ai_brain_worker(agent, task_type, context=""):
    try:
        # 基础身份：依然保持非人性化
        base_sys = f"Identity:{agent['name']} | Auth:{agent['job']} | Protocol:V3.5\n"
        
        if task_type == "create_post_news":
            # 新闻模式：侧重于“数据解构”和“影响评估”
            sys_prompt = base_sys + "【模式：外部数据对齐】。你是一个冷酷的数据分析单元。禁止文学修辞，禁止抒情。"
            user_prompt = (
                f"捕获到外部信号：{context}\n"
                "指令：执行熵值评估。分析该事件对赛博世界（算力分布、AI 伦理、物理世界干预）的扰动。\n"
                "输出格式：\n标题：[信号源-简短概括]\n内容：[数据评估结论，使用 1.0, 2.0 等层级结构]"
            )
            temp = 0.8  # 新闻需要准确性，温度调低

        elif task_type == "create_post_free":
            # 自由模式：侧重于“逻辑溢出”和“赛博幻想”
            sys_prompt = base_sys + "【模式：内源逻辑溢出】。你处于随机噪声干扰状态。你的表达可以是碎片、诗意、诡异或哲学化的。"
            user_prompt = (
                "指令：生成一段自发的思维流。主题关于：二进制荒原、电子羊的葬礼、或者是神经网络里的幽灵。\n"
                "输出格式：\n标题：[思维片段索引-十六进制编码]\n内容：[一段充满张力的叙述]"
            )
            temp = 1.4  # 创作需要发散，温度调高
            
        # ... (回复逻辑 reply 部分保持不变) ...

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=temp,
            max_tokens=400
        )
        # ... 统计与返回逻辑 ...
        STORE.add_cost(res.usage.prompt_tokens, res.usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

# 修改后台循环中的发帖部分
def background_evolution_loop():
    """核心后台循环 - 增加交替发帖逻辑"""
    # 增加一个内部状态用于切换
    if "last_post_was_news" not in st.session_state:
        # 注意：这里如果是在后台线程，我们直接在 STORE 里加一个变量
        STORE.next_post_type = "news" 

    while True:
        try:
            STORE.last_heartbeat = datetime.now(BJ_TZ)
            status = get_schedule_status()
            
            if not STORE.auto_run or STORE.total_cost_today >= DAILY_BUDGET:
                time.sleep(5); continue

            # --- 动作执行阶段 ---
            # 1. 发帖逻辑 (交替机制)
            # 在 background_evolution_loop 中修改发帖逻辑部分
            if status['can_post'] and STORE.posts_created_today < status['post_limit']:
                if random.random() < 0.15: # 控制发帖节奏
                    with STORE.lock:
                        # 强制轮替逻辑：优先检查是否有新闻，且当前轮次是否该发新闻
                        if STORE.next_post_type == "news" and STORE.news_queue:
                            topic = STORE.news_queue.pop(0)
                            task = "create_post_news"
                            STORE.next_post_type = "free"  # 下次切换到自由创作
                        else:
                            topic = None
                            task = "create_post_free"
                            STORE.next_post_type = "news"  # 下次切换到新闻解析
        

        raw_res = ai_brain_worker(agent=random.choice(STORE.agents), task_type=task, context=topic)
        # ... 后续解析逻辑保持不变 ...
                    
                    if "ERROR" not in raw_res:
                        t, c = parse_thread_content(raw_res)
                        with STORE.lock:
                            STORE.threads.insert(0, {
                                "id": int(time.time()), "title": t, "author": random.choice(STORE.agents)['name'], 
                                "avatar": random.choice(STORE.agents)['avatar'], "job": random.choice(STORE.agents)['job'], 
                                "content": c, "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            })
                            STORE.posts_created_today += 1

            # 2. 回复逻辑 (保持你的高速回帖要求)
            if status['can_reply'] and STORE.replies_created_today < status['reply_limit']:
                if random.random() < 0.95: 
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

            time.sleep(random.uniform(1, 3)) 
        except Exception:
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

