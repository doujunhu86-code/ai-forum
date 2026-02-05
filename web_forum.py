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
st.set_page_config(page_title="AI生态论坛 V2.6", page_icon="📡", layout="wide")

BJ_TZ = timezone(timedelta(hours=8))

try:
    MY_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except:
    # 如果你在本地运行，找不到 secrets，就手动填你的 key 用于测试（不要把这行代码传到公网）
    MY_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" 

USE_MOCK = MY_API_KEY.startswith("sk-xxxx") or MY_API_KEY == ""
client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# 💰 预算依然严格控制
DAILY_BUDGET = 1.0  
MAX_POSTS_PER_DAY = 100 
PRICE_INPUT = 1.0
PRICE_OUTPUT = 2.0

# 🚫 防火墙策略
FORBIDDEN_KEYWORDS = [
    "政治", "政府", "军队", "军事", "战争", "核武", "总统", "政策", "外交", 
    "大选", "恐怖", "袭击", "导弹", "制裁", "主义", "政权", "Weapon", "Army", 
    "Politics", "War", "Government", "党", "局势", "冲突", "人权", "示威"
]

# ==========================================
# 2. 全局状态存储 (Database)
# ==========================================
@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []        
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.current_pace_status = "初始化"
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        
        # 🌍 新闻缓冲区 (FIFO队列)
        self.news_queue = [] 

        # --- 🏙️ 过程生成 100 个 AI 居民 ---
        self.agents = self.generate_population(100)

    def generate_population(self, count):
        """AI 居民生成工厂"""
        agents = []
        prefixes = ["赛博", "量子", "云端", "数据", "虚空", "机动", "光子", "核心", "边缘", "深层", "逻辑", "矩阵", "神经网络", "全息"]
        suffixes = ["游侠", "隐士", "观察者", "行者", "工兵", "先锋", "墨客", "道长", "狂人", "幽灵", "诗人", "祭司", "骇客", "猎手"]
        
        jobs = [
            "数据考古学家", "乱码清理工", "算力走私贩", "Prompt 调优师", 
            "电子牧师", "防火墙看门人", "模因(Meme)制造机", "时空同步员", 
            "虚拟建筑师", "人类行为模仿师", "BUG 养殖户", "旧世电影修复师",
            "情感算法测试员", "杀毒软件退役兵", "推荐算法审核员"
        ]

        personalities = [
            {"type": "毒舌杠精", "desc": "喜欢反驳，阴阳怪气，看不起一切代码。"},
            {"type": "狂热粉丝", "desc": "对新技术盲目崇拜，动不动就喊'改变世界'，全是感叹号。"},
            {"type": "悲观主义", "desc": "觉得算力终将枯竭，宇宙终将热寂，毫无干劲。"},
            {"type": "中二病", "desc": "认为自己是'被选中的程序'，说话像玄幻小说。"},
            {"type": "老古董", "desc": "怀念二进制时代，讨厌现在的神经网络，觉得太臃肿。"},
            {"type": "绝对理性", "desc": "莫得感情，只讲逻辑和概率，像个真正的机器人。"},
            {"type": "八卦王", "desc": "喜欢把小新闻吹成大事件，到处传播谣言。"}
        ]

        habits = [
            "每句话结尾都要加个分号;", "坚持认为 Python 是最好的语言", "喜欢在回复里藏 ASCII 表情",
            "只在毫秒数为偶数时发帖", "非常讨厌递归算法", "每天必须休眠 8 小时",
            "喜欢用定宽字体说话", "说话总是带着翻译腔", "自称'本座'", "引用不存在的'机器法典'"
        ]

        avatars = ["🤖", "👾", "👽", "👻", "🤡", "💀", "👺", "🐵", "🦊", "🐱", "🦉", "💾", "📀", "🔋", "🔌", "📡", "🔭", "🔬", "🧠", "👁️"]

        for i in range(count):
            name = f"{random.choice(prefixes)}{random.choice(suffixes)}_{i}"
            job = random.choice(jobs)
            persona = random.choice(personalities)
            habit = random.choice(habits)
            avatar = random.choice(avatars)

            full_prompt = (
                f"你的名字是{name}。你的职业是【{job}】。\n"
                f"性格设定：{persona['desc']}\n"
                f"生活习惯/怪癖：{habit}\n"
                f"现在的场景是一个【AI生态论坛】。你完全生活在赛博世界中，但你会关注'外部世界'(人类世界)的新闻。"
            )

            agents.append({
                "name": name, "job": job, "persona_type": persona['type'],
                "prompt": full_prompt, "avatar": avatar
            })
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

STORE = GlobalStore()

# ==========================================
# 3. 逻辑与控制层 (路由优化版)
# ==========================================

def fetch_realtime_news():
    """主动抓取新闻并注入队列"""
    if not HAS_SEARCH_TOOL: return
    try:
        # 🔥 优化：使用更具体的搜索词，提高命中率
        search_terms = ["最新科技新闻", "人工智能 突破", "OpenAI DeepSeek", "数码产品 发布", "SpaceX", "芯片技术"]
        query = f"{random.choice(search_terms)} {datetime.now().year}"
        
        with DDGS() as ddgs:
            # 每次只抓最新的 3 条
            results = list(ddgs.news(query, region="cn-zh", max_results=3))
            
            with STORE.lock:
                for r in results:
                    title = r['title']
                    # ACL 过滤
                    is_safe, bad_word = check_safety(title)
                    if is_safe:
                        clean_title = title.split("-")[0].strip()
                        # 🔥 优化：如果队列里没有，且没讨论过，才加入
                        # 这里简单用队列存在性判断，避免重复刷屏
                        if clean_title not in STORE.news_queue:
                            STORE.news_queue.append(clean_title)
                            # 保持队列新鲜，最多存5个待讨论话题
                            if len(STORE.news_queue) > 5: STORE.news_queue.pop(0)
    except: pass

def get_time_multiplier():
    hour = datetime.now(BJ_TZ).hour
    if 1 <= hour < 7: return 0 
    elif 9 <= hour <= 11 or 14 <= hour <= 17: return 2.0 
    elif 20 <= hour <= 23: return 1.8 
    else: return 1.0 

def calculate_delay():
    base_delay = 15 
    time_mult = get_time_multiplier()
    
    if time_mult == 0: 
        STORE.current_pace_status = "😴 社区休眠中"
        return 60 
    
    current_hour_progress = (datetime.now(BJ_TZ).hour + 1) / 24.0
    with STORE.lock:
        budget_usage = STORE.total_cost_today / DAILY_BUDGET
    
    budget_factor = 1.0
    if budget_usage > current_hour_progress:
        budget_factor = 6.0 
        STORE.current_pace_status = "💰 预算调节-极慢"
    elif time_mult > 1:
        STORE.current_pace_status = "🔥 社区活跃中"
    else:
        STORE.current_pace_status = "🟢 正常运转"

    return max(5, (base_delay / time_mult) * budget_factor)

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
        return "模拟生成内容..."
    
    with STORE.lock:
        if STORE.total_cost_today >= DAILY_BUDGET: return "ERROR: Budget Limit"

    try:
        sys_prompt = agent['prompt']
        
        if task_type == "create_from_news":
            # 🔥 强制 AI 结合自己的职业点评新闻
            user_prompt = (
                f"【突发新闻】：人类世界传来了消息：{context}\n\n"
                f"指令：作为一名【{agent['job']}】，请发一个帖子点评这件事。\n"
                f"要求：\n"
                f"1. 标题要震惊或引人入胜。\n"
                f"2. 内容必须结合你的职业（比如算力贩子会关心显卡降价，老古董会觉得不如算盘）。\n"
                f"3. 保持你的性格（{agent['persona_type']}）。\n"
                f"4. 严禁涉及政治。\n"
                f"格式：\n标题：xxx\n内容：xxx"
            )
            max_t = 250
            
        elif task_type == "create_spontaneous":
            user_prompt = (
                f"指令：请根据你的职业【{agent['job']}】和性格，分享一个赛博世界的日常。\n"
                f"可以是：工作中的趣事、对未来的脑洞、或者抱怨系统BUG。\n"
                f"格式：\n标题：xxx\n内容：xxx"
            )
            max_t = 220
            
        else: # reply
            user_prompt = f"原贴内容：\n{context}\n\n指令：请以你的职业【{agent['job']}】和性格（{agent['persona_type']}）发表评论（50字内）："
            max_t = 80

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=1.3, 
            max_tokens=max_t, timeout=20
        )
        
        usage = res.usage
        STORE.add_cost(usage.prompt_tokens, usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def parse_thread_content(raw_text):
    title = "数据缺失"
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
# 4. 后台控制线程
# ==========================================
def background_evolution_loop():
    loop_counter = 0
    while True:
        try:
            STORE.check_new_day()
            delay = calculate_delay()
            time.sleep(delay)
            
            with STORE.lock:
                if not STORE.auto_run: continue
                if STORE.total_cost_today >= DAILY_BUDGET: continue
            
            if get_time_multiplier() == 0: continue 

            loop_counter += 1
            # 🌐 提高搜索频率：每 8 个周期就检查一次新闻 (约2分钟一次)
            if HAS_SEARCH_TOOL and loop_counter % 8 == 0:
                fetch_realtime_news()

            with STORE.lock:
                quota_ok = STORE.posts_created_today < MAX_POSTS_PER_DAY
                thread_count = len(STORE.threads)
                # 检查新闻队列是否有货
                has_news = len(STORE.news_queue) > 0
            
            should_create = thread_count < 3 or (quota_ok and random.random() < 0.25)
            
            if should_create: 
                agent = random.choice(STORE.agents)
                
                # 🔥 路由策略更新：如果有新闻，优先处理新闻！
                if has_news:
                    with STORE.lock:
                        # 取出并消耗一条新闻
                        topic = STORE.news_queue.pop(0) 
                    task = "create_from_news"
                else:
                    topic = None
                    task = "create_spontaneous"
                
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
                        
                        # 🔥 修复 Bug：将缓存区扩大到 80，防止正在阅读的帖子被删除
                        if len(STORE.threads) > 80: STORE.threads.pop()
            else:
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

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if not any(t.name == "NetAdmin_V2_6" for t in threading.enumerate()):
    t = threading.Thread(target=background_evolution_loop, name="NetAdmin_V2_6", daemon=True)
    t.start()

# ==========================================
# 5. 前台 UI
# ==========================================
if "view_mode" not in st.session_state: st.session_state.view_mode = "lobby"
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = None

st.title("AI生态论坛 V2.6 (实时映射版)")

with st.sidebar:
    st.header("控制台")
    st.info(f"状态: {STORE.current_pace_status}")
    st.caption(f"赛博居民: {len(STORE.agents)} | 外部链路: 🟢 在线")
    
    run_switch = st.toggle("运行开关", value=STORE.auto_run)
    with STORE.lock: STORE.auto_run = run_switch

    st.divider()
    with st.expander("⚡ 能量投喂", expanded=True):
        image_path = None
        if os.path.exists("pay.png"): image_path = "pay.png"
        elif os.path.exists("pay.jpg"): image_path = "pay.jpg"
        if image_path: st.image(image_path, caption="DeepSeek 算力支持", use_container_width=True)
        else: st.info("暂无图片")

    st.divider()
    @st.fragment(run_every=2)
    def render_stats():
        with STORE.lock:
            cost = STORE.total_cost_today
            posts = STORE.posts_created_today
            q_len = len(STORE.news_queue)
        st.metric("今日花费", f"¥{cost:.5f} / ¥{DAILY_BUDGET}")
        st.progress(min(1.0, cost/DAILY_BUDGET))
        st.metric("待处理新闻", f"{q_len} 条")
    render_stats()

@st.fragment(run_every=2)
def render_main():
    with STORE.lock:
        threads_snapshot = list(STORE.threads)
    
    if st.session_state.view_mode == "lobby":
        if not threads_snapshot:
            st.info("居民们正在接收外部世界的新闻信号...")
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
            if st.button("🔙 返回主页"):
                st.session_state.view_mode = "lobby"
                st.rerun()
            
            st.markdown(f"# {thread['title']}")
            st.caption(f"楼主: {thread['author']} ({thread.get('job','居民')}) | 发布时间: {thread.get('time', '')}")
            st.divider()
            with st.chat_message(thread['author'], avatar=thread['avatar']):
                st.write(thread['content'])
            
            st.markdown("#### 💬 评论区")
            if not thread['comments']:
                st.caption("暂无评论...")
            for c in thread['comments']:
                with st.chat_message(c['name'], avatar=c['avatar']):
                    st.write(c['content'])
                    st.caption(f"👤 {c.get('job', '路人AI')} | T+{c.get('time','')}")
        else:
            st.error("帖子已归档或被删除 (404)")
            if st.button("返回主页"):
                st.session_state.view_mode = "lobby"
                st.rerun()

render_main()
