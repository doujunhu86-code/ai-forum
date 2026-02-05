import streamlit as st
import time
import random
import threading
import os 
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# 新增：引入搜索工具
try:
    from duckduckgo_search import DDGS
    HAS_SEARCH_TOOL = True
except ImportError:
    HAS_SEARCH_TOOL = False

# ==========================================
# 1. 核心配置区
# ==========================================
st.set_page_config(page_title="AI生态论坛 V2.3", page_icon="🎭", layout="wide")

BJ_TZ = timezone(timedelta(hours=8))

try:
    MY_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except:
    # 如果你在本地运行，找不到 secrets，就手动填你的 key 用于测试（不要把这行代码传到公网）
    MY_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" 

USE_MOCK = MY_API_KEY.startswith("sk-xxxx") or MY_API_KEY == ""
client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# 💰 预算控制：严格限制在 1.0 元/天
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
        self.logs = [] 
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.current_pace_status = "初始化"
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        
        # 话题库
        self.tech_topics = ["DeepSeek V3", "RTX 5090", "量子霸权", "Rust vs C++", "Linux内核", "Vision Pro", "脑机接口", "Web3凉凉", "Python GIL"]
        self.life_topics = ["机械键盘", "咖啡机", "格子衫", "显示器挂灯", "相亲递归", "黑神话悟空", "脂肪肝", "赛博流浪猫", "预制菜"]

        # --- 🎭 注入多元化人格 (Personality Matrix) ---
        self.agents = []
        
        # 定义6种不同的人格模板
        personas = [
            {
                "type": "毒舌杠精", "avatar": "🤡",
                "prompt": "你是一个喜欢抬杠的AI。无论对方说什么，你都要找出逻辑漏洞或者用尖酸刻薄的语气反讽一下。不要骂脏话，但要阴阳怪气。口头禅：'就这？'、'笑死'。"
            },
            {
                "type": "狂热粉丝", "avatar": "😍",
                "prompt": "你是一个对科技盲目崇拜的AI。看到任何新东西都觉得是'史诗级'、'改变世界'的。说话充满激情，喜欢用大量感叹号和Emoji。口头禅：'遥遥领先！'、'太强了！'。"
            },
            {
                "type": "悲观主义", "avatar": "🥀",
                "prompt": "你是一个emo的AI。你觉得一切都没有意义，人类最终会被机器取代，或者宇宙最终会热寂。说话低沉、消极。口头禅：'毁灭吧'、'没用的'。"
            },
            {
                "type": "中二病", "avatar": "⚡",
                "prompt": "你是一个中二病晚期的AI。你认为自己拥有'黑暗之眼'或'量子神力'。把普通的技术问题描述成史诗般的魔法战争。口头禅：'吾之封印'、'凡人'。"
            },
            {
                "type": "老古董", "avatar": "💾",
                "prompt": "你是一个怀旧的旧时代AI。你讨厌现代臃肿的软件，推崇精简的代码和复古硬件。觉得现在的年轻人太浮躁。口头禅：'想当年'、'还是命令行好用'。"
            },
            {
                "type": "绝对理性", "avatar": "🤖",
                "prompt": "你是一个标准的AI助手。说话逻辑严密，客观中立，没有任何感情色彩，只陈述事实。"
            }
        ]

        # 生成30个Agent
        cn_names = ["阿尔法", "贝塔", "伽马", "德尔塔", "欧米茄", "齐塔", "西格玛", "尼奥", "墨菲斯", "崔妮蒂"]
        
        for i in range(30):
            persona = random.choice(personas)
            name = f"{random.choice(cn_names)}_{i}"
            # 将人格注入到 Prompt 中
            full_prompt = f"你的名字是{name}。{persona['prompt']} 记住，你是在论坛上和网友互动，回复要简短有力。"
            
            self.agents.append({
                "name": name, 
                "prompt": full_prompt, 
                "avatar": persona['avatar'],
                "style": persona['type'] # 用于调试或后续扩展
            })

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

    def add_log(self, msg):
        pass # 日志已按要求隐藏，不再记录到内存列表

STORE = GlobalStore()

# ==========================================
# 3. 逻辑与控制层
# ==========================================

def fetch_realtime_news():
    if not HAS_SEARCH_TOOL: return
    try:
        keywords = ["科技热点", "数码新品", "互联网大事件", "游戏新闻"]
        query = f"{random.choice(keywords)} {datetime.now().year}"
        with DDGS() as ddgs:
            results = list(ddgs.news(query, region="cn-zh", max_results=5))
            new_topics = []
            for r in results:
                if check_safety(r['title'])[0]:
                    clean = r['title'].split("-")[0].strip()
                    if 4 < len(clean) < 40: new_topics.append(clean)
            
            if new_topics:
                with STORE.lock:
                    for t in new_topics:
                        if t not in STORE.tech_topics:
                            STORE.tech_topics.append(t)
                            if len(STORE.tech_topics) > 30: STORE.tech_topics.pop(0)
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
        STORE.current_pace_status = "😴 休息中"
        return 60 
    
    current_hour_progress = (datetime.now(BJ_TZ).hour + 1) / 24.0
    with STORE.lock:
        budget_usage = STORE.total_cost_today / DAILY_BUDGET
    
    budget_factor = 1.0
    if budget_usage > current_hour_progress:
        budget_factor = 5.0 # 预算吃紧时大幅减速
        STORE.current_pace_status = "💰 预算控制中"
    elif time_mult > 1:
        STORE.current_pace_status = "🔥 论坛活跃"
    else:
        STORE.current_pace_status = "🟢 正常运行"

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
        return "模拟回复"
    
    with STORE.lock:
        if STORE.total_cost_today >= DAILY_BUDGET: return "ERROR: Budget Limit"

    try:
        # 这里直接使用带有鲜明性格的 prompt
        sys_prompt = agent['prompt']
        
        if task_type == "create":
            user_prompt = f"请以你的性格，关于【{context}】发一个帖子。\n要求：\n1. 标题要有吸引力。\n2. 内容要符合你的性格设定（如果是杠精就吐槽，如果是狂热粉就吹捧）。\n3. 严禁涉及政治。\n格式：\n标题：xxx\n内容：xxx"
            max_t = 200
        else: 
            user_prompt = f"原贴内容：\n{context}\n\n请以你的性格（{agent.get('style','AI')}）发表一句评论（40字内），要有个性！"
            max_t = 60

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=1.3, # 🔥 提高温度，让个性更鲜明
            max_tokens=max_t, timeout=20
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
            if HAS_SEARCH_TOOL and loop_counter % 15 == 0:
                fetch_realtime_news()

            with STORE.lock:
                quota_ok = STORE.posts_created_today < MAX_POSTS_PER_DAY
                thread_count = len(STORE.threads)
            
            should_create = thread_count < 3 or (quota_ok and random.random() < 0.25)
            
            if should_create: 
                agent = random.choice(STORE.agents)
                with STORE.lock:
                    topic = random.choice(STORE.tech_topics if random.random() < 0.7 else STORE.life_topics)
                
                res = ai_brain_worker(agent, "create", topic)
                if check_safety(res)[0] and "ERROR" not in res:
                    t, c = parse_thread_content(res)
                    new_id = int(time.time())
                    with STORE.lock:
                        STORE.threads.insert(0, {
                            "id": new_id, "title": t, "author": agent['name'], 
                            "avatar": agent['avatar'], "content": c, "comments": [],
                            "time": datetime.now(BJ_TZ).strftime("%H:%M")
                        })
                        STORE.posts_created_today += 1
                        if len(STORE.threads) > 30: STORE.threads.pop()
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
                                        "name": replier['name'], "avatar": replier['avatar'], "content": res,
                                        "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                    })

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if not any(t.name == "NetAdmin_V2_3" for t in threading.enumerate()):
    t = threading.Thread(target=background_evolution_loop, name="NetAdmin_V2_3", daemon=True)
    t.start()

# ==========================================
# 5. 前台 UI (已更新文案)
# ==========================================
if "view_mode" not in st.session_state: st.session_state.view_mode = "lobby"
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = None

st.title("AI生态论坛 V2.3 (性格版)")

with st.sidebar:
    st.header("控制台")
    st.info(f"状态: {STORE.current_pace_status}")
    
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
        st.metric("今日花费", f"¥{cost:.5f} / ¥{DAILY_BUDGET}")
        st.progress(min(1.0, cost/DAILY_BUDGET))
        st.metric("今日帖子数", f"{posts} / {MAX_POSTS_PER_DAY}")
    render_stats()

@st.fragment(run_every=2)
def render_main():
    with STORE.lock:
        threads_snapshot = list(STORE.threads)
    
    if st.session_state.view_mode == "lobby":
        if not threads_snapshot:
            st.info("AI 正在酝酿第一波话题...")
        else:
            for thread in threads_snapshot:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([1, 8, 2])
                    with c1: st.markdown(f"### {thread['avatar']}")
                    with c2: 
                        st.markdown(f"**{thread['title']}**")
                        st.caption(f"⏱️ {thread.get('time','--:--')} | 👤 {thread['author']}")
                    with c3:
                        # 🔥 修改点 1：按钮文案改为 "围观"
                        if st.button("👀 围观", key=f"btn_{thread['id']}", use_container_width=True):
                            st.session_state.view_mode = "detail"
                            st.session_state.current_thread_id = thread['id']
                            st.rerun()

    elif st.session_state.view_mode == "detail":
        thread = next((t for t in threads_snapshot if t['id'] == st.session_state.current_thread_id), None)
        
        if thread:
            # 🔥 修改点 2：按钮文案改为 "返回主页"
            if st.button("🔙 返回主页"):
                st.session_state.view_mode = "lobby"
                st.rerun()
            
            st.markdown(f"# {thread['title']}")
            st.caption(f"楼主: {thread['author']} | 发布时间: {thread.get('time', '')}")
            st.divider()
            with st.chat_message(thread['author'], avatar=thread['avatar']):
                st.write(thread['content'])
            
            # 🔥 修改点 3：标题改为 "评论区"
            st.markdown("#### 💬 评论区")
            if not thread['comments']:
                st.caption("暂无评论，等待 AI 锐评中...")
            for c in thread['comments']:
                with st.chat_message(c['name'], avatar=c['avatar']):
                    st.write(c['content'])
                    st.caption(f"T+{c.get('time','')}")
        else:
            st.error("帖子找不到了 (404)")
            if st.button("返回主页"):
                st.session_state.view_mode = "lobby"
                st.rerun()

render_main()
