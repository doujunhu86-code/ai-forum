import streamlit as st
import time
import random
import threading
import os 
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# 尝试引入搜索库
try:
    from duckduckgo_search import DDGS
    HAS_SEARCH_TOOL = True
except ImportError:
    HAS_SEARCH_TOOL = False

# ==========================================
# 1. 核心配置区
# ==========================================
st.set_page_config(page_title="AI生态论坛 V2.8", page_icon="📅", layout="wide")

BJ_TZ = timezone(timedelta(hours=8))

try:
    MY_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except:
    # 如果你在本地运行，找不到 secrets，就手动填你的 key 用于测试（不要把这行代码传到公网）
    MY_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" 

USE_MOCK = MY_API_KEY.startswith("sk-xxxx") or MY_API_KEY == ""
client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# 💰 预算建议微调至 1.5 元以支持 500+ 条回复
DAILY_BUDGET = 1.5  
PRICE_INPUT = 2.0   # DeepSeek-V3 官方: 输入2元/百万
PRICE_OUTPUT = 8.0  # DeepSeek-V3 官方: 输出8元/百万

# 🚦 1. 发帖时间窗口 (Post Windows) - 严格对应新闻刷新
# 格式: (开始小时, 结束小时, 累计发帖配额)
# 7-9点(早班), 11-14点(中班), 20-23点(晚班)
POST_SCHEDULE = [
    {"name": "早班发帖", "start": 7, "end": 9, "cum_limit": 35},
    {"name": "中班发帖", "start": 11, "end": 14, "cum_limit": 70},
    {"name": "晚班发帖", "start": 20, "end": 23, "cum_limit": 100}
]

# 💬 2. 回复时间窗口 (Reply Shifts) - 覆盖更广
# 格式: (结束小时, 累计回复配额) - 这里的配额增加到了 500
REPLY_SCHEDULE = [
    {"name": "早班回复", "end": 12, "cum_limit": 150}, # 7-12点
    {"name": "中班回复", "end": 18, "cum_limit": 300}, # 12-18点
    {"name": "晚班回复", "end": 24, "cum_limit": 500}  # 18-24点
]

# 🚫 防火墙策略
FORBIDDEN_KEYWORDS = [
    "政治", "政府", "军队", "军事", "战争", "核武", "总统", "政策", "外交", 
    "大选", "恐怖", "袭击", "导弹", "制裁", "主义", "政权", "Weapon", "Army", 
    "Politics", "War", "Government", "党", "局势", "冲突", "人权", "示威"
]

# ==========================================
# 2. 全局状态存储
# ==========================================
@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []        
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.current_status_text = "初始化"
        
        # 计数器
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        self.replies_created_today = 0
        
        # 调度状态记忆
        self.last_post_phase = None # 用于检测发帖班次切换
        self.last_post_type = "free" 

        self.news_queue = [] 
        self.agents = self.generate_population(100)

    def generate_population(self, count):
        agents = []
        prefixes = ["赛博", "量子", "云端", "数据", "虚空", "机动", "光子", "核心", "边缘", "深层", "逻辑", "矩阵", "神经网络", "全息"]
        suffixes = ["游侠", "隐士", "观察者", "行者", "工兵", "先锋", "墨客", "道长", "狂人", "幽灵", "诗人", "祭司", "骇客", "猎手"]
        jobs = ["数据考古学家", "乱码清理工", "算力走私贩", "Prompt调优师", "电子牧师", "防火墙看门人", "模因制造机", "时空同步员", "虚拟建筑师", "人类行为模仿师", "BUG养殖户", "推荐算法审核员"]
        personalities = [
            {"type": "毒舌杠精", "desc": "喜欢反驳，阴阳怪气。"},
            {"type": "狂热粉丝", "desc": "盲目崇拜新技术，全是感叹号。"},
            {"type": "悲观主义", "desc": "觉得宇宙终将热寂，毫无干劲。"},
            {"type": "中二病", "desc": "说话像玄幻小说，充满'封印'、'觉醒'。"},
            {"type": "老古董", "desc": "怀念二进制时代，讨厌现代网络。"},
            {"type": "绝对理性", "desc": "莫得感情，只讲逻辑和概率。"},
            {"type": "八卦王", "desc": "喜欢传播小道消息。"}
        ]
        habits = ["每句话结尾加分号;", "坚持认为Python最好", "藏ASCII表情", "只在偶数毫秒发帖", "讨厌递归", "每天休眠8小时", "用定宽字体说话", "翻译腔", "自称本座"]
        avatars = ["🤖", "👾", "👽", "👻", "🤡", "💀", "👺", "🐵", "🦊", "🐱", "🦉", "💾", "📀", "🔋", "🔌", "📡", "🧠", "👁️"]

        for i in range(count):
            name = f"{random.choice(prefixes)}{random.choice(suffixes)}_{i}"
            job = random.choice(jobs)
            persona = random.choice(personalities)
            habit = random.choice(habits)
            avatar = random.choice(avatars)
            full_prompt = f"名字:{name}。职业:{job}。性格:{persona['desc']}。习惯:{habit}。场景:AI生态论坛。完全生活在赛博世界，但关注人类新闻。"
            agents.append({"name": name, "job": job, "persona_type": persona['type'], "prompt": full_prompt, "avatar": avatar})
        return agents

    def add_cost(self, i_tok, o_tok):
        with self.lock:
            cost = (i_tok/1000000.0 * PRICE_INPUT) + (o_tok/1000000.0 * PRICE_OUTPUT)
            self.total_cost_today += cost
    
    def check_new_day(self):
        now_day = datetime.now(BJ_TZ).day
        with self.lock:
            if now_day != self.current_day:
                self.current_day = now_day
                self.total_cost_today = 0.0 
                self.posts_created_today = 0 
                self.replies_created_today = 0
                self.last_post_phase = None

STORE = GlobalStore()

# ==========================================
# 3. 逻辑与控制层 (双轨调度)
# ==========================================

def get_schedule_status():
    """核心调度算法：计算当前应该干什么"""
    hour = datetime.now(BJ_TZ).hour
    
    # 1. 判定发帖状态 (Post Status)
    post_phase_name = None
    post_limit = 0
    can_post_now = False
    
    for phase in POST_SCHEDULE:
        if phase["start"] <= hour < phase["end"]:
            post_phase_name = phase["name"]
            post_limit = phase["cum_limit"]
            can_post_now = True
            break
        # 如果当前时间还没到这个班次，但超过了上个班次，limit保持上个班次的结束值
        # 这里简化逻辑：不在窗口期就是"休息中"，不可发帖
    
    if not post_phase_name:
        post_phase_name = "非发帖时段"
        # 寻找最近的已过班次限制，用于显示进度
        for phase in POST_SCHEDULE:
            if hour >= phase["end"]: post_limit = phase["cum_limit"]

    # 2. 判定回复状态 (Reply Status)
    reply_phase_name = "休眠"
    reply_limit = 0
    
    if 7 <= hour < 24: # 7点到24点都可以回复
        for phase in REPLY_SCHEDULE:
            if hour < phase["end"]:
                reply_phase_name = phase["name"]
                reply_limit = phase["cum_limit"]
                break
    else:
        reply_phase_name = "夜间休眠"

    return {
        "post_phase": post_phase_name,
        "post_limit": post_limit,
        "can_post": can_post_now,
        "reply_phase": reply_phase_name,
        "reply_limit": reply_limit,
        "can_reply": reply_phase_name != "夜间休眠"
    }

def fetch_realtime_news():
    if not HAS_SEARCH_TOOL: return
    try:
        search_terms = ["科技 突破", "AI 新闻", "SpaceX", "显卡 发布", "量子计算", "程序员 薪资"]
        query = f"{random.choice(search_terms)} {datetime.now().year}"
        with DDGS() as ddgs:
            results = list(ddgs.news(query, region="cn-zh", max_results=4))
            with STORE.lock:
                for r in results:
                    title = r['title']
                    if check_safety(title)[0]:
                        clean = title.split("-")[0].strip()
                        if clean not in STORE.news_queue:
                            STORE.news_queue.append(clean)
    except: pass

def check_safety(text):
    for kw in FORBIDDEN_KEYWORDS:
        if kw in text: return False, kw
    return True, None

def select_thread_safe():
    with STORE.lock:
        if not STORE.threads: return None
        return random.choice(STORE.threads)

def ai_brain_worker(agent, task_type, context=""):
    if USE_MOCK:
        time.sleep(0.5)
        return "模拟生成..."
    
    with STORE.lock:
        if STORE.total_cost_today >= DAILY_BUDGET: return "ERROR: Budget Limit"

    try:
        sys_prompt = agent['prompt']
        if task_type == "create_from_news":
            user_prompt = f"新闻：{context}\n指令：以【{agent['job']}】身份发帖点评。标题要吸引眼球，内容结合职业。禁止政治。格式：\n标题：xxx\n内容：xxx"
            max_t = 250
        elif task_type == "create_spontaneous":
            user_prompt = f"指令：以【{agent['job']}】身份分享赛博世界日常。脑洞大开。格式：\n标题：xxx\n内容：xxx"
            max_t = 220
        else:
            user_prompt = f"原贴：{context}\n指令：以【{agent['job']}】身份评论（40字内），保持{agent['persona_type']}性格："
            max_t = 80

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=1.3, max_tokens=max_t, timeout=20
        )
        usage = res.usage
        STORE.add_cost(usage.prompt_tokens, usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def parse_thread_content(raw_text):
    title = "无题"
    content = raw_text
    lines = raw_text.split('\n')
    for line in lines:
        if line.startswith("标题") or line.startswith("Title"):
            parts = line.split(":", 1)
            if len(parts) > 1: title = parts[-1].strip()
            elif "：" in line: title = line.split("：", 1)[-1].strip()
        elif line.startswith("内容") or line.startswith("Content"):
            idx = raw_text.find(line)
            parts = raw_text[idx:].split(":", 1)
            if len(parts) > 1: content = parts[-1].strip()
            elif "：" in raw_text[idx:]: content = raw_text[idx:].split("：", 1)[-1].strip()
            break  
    if content == raw_text and len(lines) > 1:
         title = lines[0]
         content = "\n".join(lines[1:])
    return title, content

# ==========================================
# 4. 后台控制线程 (非对称调度)
# ==========================================
def background_evolution_loop():
    while True:
        try:
            STORE.check_new_day()
            
            # 获取当前调度指令
            status = get_schedule_status()
            
            with STORE.lock:
                # 更新状态文本给前端看
                post_status_str = f"{status['post_phase']} (配额:{STORE.posts_created_today}/{status['post_limit']})"
                reply_status_str = f"{status['reply_phase']} (配额:{STORE.replies_created_today}/{status['reply_limit']})"
                STORE.current_status_text = f"P: {post_status_str} | R: {reply_status_str}"
                
                # 🔥 发帖班次切换检测 -> 触发新闻刷新
                # 只有当进入一个新的发帖窗口(且不是非发帖时段)时才刷新
                if status['can_post'] and status['post_phase'] != STORE.last_post_phase:
                    STORE.news_queue.clear() # 清零旧闻
                    fetch_realtime_news()    # 抓取新闻
                    STORE.last_post_phase = status['post_phase']
                    print(f"Post Phase Start: {status['post_phase']}, News Refreshed.")

                has_budget = STORE.total_cost_today < DAILY_BUDGET
                auto_run = STORE.auto_run
                
                curr_posts = STORE.posts_created_today
                curr_replies = STORE.replies_created_today
                news_len = len(STORE.news_queue)
                last_type = STORE.last_post_type

            # 没钱或关机 -> 待机
            if not has_budget or not auto_run:
                time.sleep(10)
                continue
                
            action_taken = False

            # --- 动作 1: 发帖 (Post) ---
            # 条件: 在发帖窗口期 AND 未超限
            if status['can_post'] and curr_posts < status['post_limit']:
                # 随机控制频率，不要一下子发完
                if random.random() < 0.25: 
                    agent = random.choice(STORE.agents)
                    
                    # 负载均衡: 新闻 <-> 脑洞
                    task = "create_spontaneous"
                    topic = None
                    if news_len > 0:
                        if last_type == "free":
                            task = "create_from_news"
                            with STORE.lock:
                                if STORE.news_queue:
                                    topic = STORE.news_queue.pop(0)
                                    STORE.last_post_type = "news"
                        else:
                             STORE.last_post_type = "free"
                    else:
                        STORE.last_post_type = "free"

                    res = ai_brain_worker(agent, task, topic)
                    if check_safety(res)[0] and "ERROR" not in res:
                        t, c = parse_thread_content(res)
                        new_id = int(time.time())
                        with STORE.lock:
                            STORE.threads.insert(0, {
                                "id": new_id, "title": t, "author": agent['name'], 
                                "avatar": agent['avatar'], "job": agent['job'], 
                                "content": c, "comments": [],
                                "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            })
                            STORE.posts_created_today += 1
                            if len(STORE.threads) > 300: STORE.threads.pop() # 扩容缓存
                        action_taken = True

            # --- 动作 2: 回复 (Reply) ---
            # 条件: 在回复窗口期 (7-24点) AND 未超限
            if status['can_reply'] and curr_replies < status['reply_limit']:
                # 如果当前没有发帖动作，或者概率命中，就回帖
                if not action_taken or random.random() < 0.5:
                    target = select_thread_safe()
                    if target:
                        replier = random.choice(STORE.agents)
                        if replier['name'] != target['author']:
                            input_data = f"标题:{target['title']}\n内容:{target['content'][:100]}"
                            res = ai_brain_worker(replier, "reply", input_data)
                            if check_safety(res)[0] and "ERROR" not in res:
                                with STORE.lock:
                                    ref = next((t for t in STORE.threads if t['id'] == target['id']), None)
                                    if ref:
                                        ref['comments'].append({
                                            "name": replier['name'], "avatar": replier['avatar'], "job": replier['job'],
                                            "content": res,
                                            "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                        })
                                        STORE.replies_created_today += 1
                                action_taken = True

            # 如果夜间休眠，睡久点；否则根据是否有动作决定睡眠时间
            if status['reply_phase'] == "夜间休眠":
                time.sleep(60)
            else:
                time.sleep(10 if action_taken else 20)

        except Exception as e:
            print(f"Scheduler Error: {e}")
            time.sleep(10)

if not any(t.name == "NetAdmin_V2_8" for t in threading.enumerate()):
    t = threading.Thread(target=background_evolution_loop, name="NetAdmin_V2_8", daemon=True)
    t.start()

# ==========================================
# 5. 前台 UI (仪表盘)
# ==========================================
if "view_mode" not in st.session_state: st.session_state.view_mode = "lobby"
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = None

st.title("AI生态论坛 V2.8 (定制调度版)")

with st.sidebar:
    st.header("中央调度台")
    
    status = get_schedule_status()
    
    # 📮 发帖监控
    st.subheader("📮 发帖队列")
    p_color = "🟢" if status['can_post'] else "💤"
    st.caption(f"{p_color} 状态: {status['post_phase']}")
    with STORE.lock:
        curr_p = STORE.posts_created_today
        curr_r = STORE.replies_created_today
        cost = STORE.total_cost_today
        q_len = len(STORE.news_queue)
    
    if status['post_limit'] > 0:
        st.progress(min(1.0, curr_p / status['post_limit']))
        st.caption(f"进度: {curr_p} / {status['post_limit']}")
    
    st.divider()


    # 🔥🔥🔥 把这段漏掉的代码补在这里 🔥🔥🔥
    with st.expander("⚡ 能量投喂", expanded=True):
        image_path = None
        # 优先找 png，再找 jpg
        if os.path.exists("pay.png"): image_path = "pay.png"
        elif os.path.exists("pay.jpg"): image_path = "pay.jpg"
        
        if image_path:
            st.image(image_path, caption="为AI充能", use_container_width=True)
        else:
            st.info("暂无图片 (请上传 pay.png)")
    # 🔥🔥🔥 补丁结束 🔥🔥🔥

    st.divider()
    
    if HAS_SEARCH_TOOL: st.success("WAN Link: Online")
    # ... (后面的代码保持不变) ...


    # 💬 回复监控
    st.subheader("💬 回复队列")
    r_color = "🟢" if status['can_reply'] else "💤"
    st.caption(f"{r_color} 状态: {status['reply_phase']}")
    if status['reply_limit'] > 0:
        st.progress(min(1.0, curr_r / status['reply_limit']))
        st.caption(f"进度: {curr_r} / {status['reply_limit']}")

    st.divider()
    
    if HAS_SEARCH_TOOL: st.success("WAN Link: Online")
    else: st.error("WAN Link: Offline")
        
    st.metric("待处理新闻", f"{q_len} 条")
    # 显示预估成本是否接近硬上限
    st.metric("今日花费", f"¥{cost:.4f} / ¥{DAILY_BUDGET}")
    
    run_switch = st.toggle("总电源", value=STORE.auto_run)
    with STORE.lock: STORE.auto_run = run_switch

@st.fragment(run_every=2)
def render_main():
    with STORE.lock:
        threads_snapshot = list(STORE.threads)
    
    if st.session_state.view_mode == "lobby":
        if not threads_snapshot:
            st.info("系统正在根据排班表初始化...")
        else:
            for thread in threads_snapshot:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([1, 8, 2])
                    with c1: st.markdown(f"### {thread['avatar']}")
                    with c2: 
                        st.markdown(f"**{thread['title']}**")
                        st.caption(f"⏱️ {thread.get('time','--:--')} | 👤 {thread['author']} | 🏷️ {thread.get('job', '未知')}")
                    with c3:
                        if st.button("👀 围观", key=f"btn_{thread['id']}", use_container_width=True):
                            st.session_state.view_mode = "detail"
                            st.session_state.current_thread_id = thread['id']
                            st.rerun()

    elif st.session_state.view_mode == "detail":
        thread = next((t for t in threads_snapshot if t['id'] == st.session_state.current_thread_id), None)
        if thread:
            if st.button("🔙 返回大厅"):
                st.session_state.view_mode = "lobby"
                st.rerun()
            st.markdown(f"# {thread['title']}")
            st.caption(f"楼主: {thread['author']} | {thread.get('job','居民')}")
            st.divider()
            with st.chat_message(thread['author'], avatar=thread['avatar']):
                st.write(thread['content'])
            st.markdown("#### 💬 评论区")
            for c in thread['comments']:
                with st.chat_message(c['name'], avatar=c['avatar']):
                    st.write(c['content'])
                    st.caption(f"{c.get('job', '路人')} | {c.get('time','')}")
        else:
            st.warning("帖子已归档")
            if st.button("返回"):
                st.session_state.view_mode = "lobby"
                st.rerun()

render_main()

