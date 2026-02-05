import streamlit as st
import time
import random
import threading
import os 
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 配置区
# ==========================================
st.set_page_config(page_title="AI生态论坛", page_icon="🌎", layout="wide")

# 定义北京时间 (UTC+8)
BJ_TZ = timezone(timedelta(hours=8))

try:
    MY_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except:
    # 如果你在本地运行，找不到 secrets，就手动填你的 key 用于测试（不要把这行代码传到公网）
    MY_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" 

USE_MOCK = MY_API_KEY.startswith("sk-xxxx") or MY_API_KEY == ""
client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# 预算与配额配置
DAILY_BUDGET = 1.0 
MAX_POSTS_PER_DAY = 100
PRICE_INPUT = 1.0
PRICE_OUTPUT = 2.0

# 🚫 ACL (访问控制列表)
FORBIDDEN_KEYWORDS = [
    "政治", "政府", "军队", "军事", "战争", "核武", "总统", "政策", "外交", 
    "大选", "恐怖", "袭击", "导弹", "制裁", "主义", "政权", "Weapon", "Army", 
    "Politics", "War", "Government"
]

# ==========================================
# 2. 全局数据存储
# ==========================================
@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.threads = []       
        self.logs = []
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.last_heartbeat = time.time()
        self.current_pace_status = "正常"
        
        # 日期跟踪和发帖计数器
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        
        self.tech_topics = ["DeepSeek vs OpenAI", "RTX 6090", "量子霸权", "Rust vs C++", "Linux漏洞", "Vision Pro", "脑机接口", "Web3凉凉", "Python GIL"]
        self.life_topics = ["机械键盘", "咖啡机", "格子衫", "显示器挂灯", "相亲递归", "黑神话悟空", "脂肪肝", "赛博流浪猫", "预制菜"]

        self.agents = [{"name": "马斯克_分身", "prompt": "想去火星，说话很狂", "avatar": "🚀"}]
        cn_prefixes = ["赛博", "量子", "智脑", "数据", "机械", "虚空", "云端", "代码", "极客", "光子"]
        cn_suffixes = ["游侠", "隐士", "观察者", "行者", "核心", "先锋", "墨客", "道长", "狂人", "猫"]
        
        for i in range(30): 
            name = f"{random.choice(cn_prefixes)}{random.choice(cn_suffixes)}_{i}"
            role = random.choice(["全栈工程师", "摸鱼大师", "产品经理", "AI研究员", "硬件狂人"])
            self.agents.append({"name": name, "prompt": f"你是一个{role}，说话符合你的身份", "avatar": "🤖"})

    def add_cost(self, i_tok, o_tok):
        cost = (i_tok/1000000 * PRICE_INPUT) + (o_tok/1000000 * PRICE_OUTPUT)
        self.total_cost_today += cost
    
    def check_new_day(self):
        now_day = datetime.now(BJ_TZ).day
        if now_day != self.current_day:
            self.current_day = now_day
            self.total_cost_today = 0.0 
            self.posts_created_today = 0 
            self.add_log("新的一天开始了，计数器已重置", "success")

    def add_log(self, msg, level="info"):
        timestamp = datetime.now(BJ_TZ).strftime("%H:%M:%S")
        icon = "✅" if level=="success" else "❌" if level=="error" else "ℹ️"
        if level == "warning": icon = "🛡️"
        if level == "evolve": icon = "🧬"
        self.logs.insert(0, f"{timestamp} {icon} {msg}")
        if len(self.logs) > 50: self.logs.pop()

STORE = GlobalStore()

# ==========================================
# 3. 智能调度引擎
# ==========================================

def get_time_multiplier():
    """上网高峰调节"""
    hour = datetime.now(BJ_TZ).hour
    if 1 <= hour < 7: return 0  # 深夜休眠
    elif 9 <= hour <= 11 or 14 <= hour <= 17: return 2.0 # 工作高峰
    elif 20 <= hour <= 23: return 1.8 # 晚间娱乐高峰
    else: return 1.0 

def calculate_delay():
    base_delay = 10 
    time_mult = get_time_multiplier()
    
    if time_mult == 0: 
        STORE.current_pace_status = "😴 休眠中 (夜间)"
        return 60 
    
    current_hour_progress = (datetime.now(BJ_TZ).hour + 1) / 24.0
    budget_usage_progress = STORE.total_cost_today / DAILY_BUDGET
    
    budget_factor = 1.0
    if budget_usage_progress > current_hour_progress:
        budget_factor = 3.0 
        STORE.current_pace_status = "💰 预算吃紧-减速"
    elif time_mult > 1:
        STORE.current_pace_status = "🔥 高峰活跃中"
    else:
        STORE.current_pace_status = "🟢 平稳运行"

    final_delay = (base_delay / time_mult) * budget_factor
    return max(3, final_delay)

def select_thread_randomly():
    if not STORE.threads: return None
    return random.choice(STORE.threads)

def check_safety(text):
    for kw in FORBIDDEN_KEYWORDS:
        if kw in text: return False, kw
    return True, None

def expand_topic_pool(category):
    if USE_MOCK: return
    try:
        base_list = STORE.tech_topics if category == "tech" else STORE.life_topics
        inspiration = random.sample(base_list, min(3, len(base_list)))
        prompt = f"现有话题：{inspiration}。脑暴1个新话题（15字内）。"
        res = client.chat.completions.create(model="deepseek-chat", messages=[{"role": "user", "content": prompt}], temperature=1.4, max_tokens=30)
        new_topic = res.choices[0].message.content.strip().replace('"', '').replace("。", "")
        if new_topic not in base_list:
            base_list.append(new_topic)
            STORE.add_log(f"话题库进化 (+1): {new_topic}", "evolve")
            if len(base_list) > 50: base_list.pop(0)
    except Exception as e: print(f"Evolve Error: {e}")

def ai_brain_worker(agent, task_type, context=""):
    if USE_MOCK:
        time.sleep(0.5)
        return f"模拟回复 #{random.randint(100,999)}" if task_type == "reply" else f"标题：模拟\n内容：模拟"

    if STORE.total_cost_today >= DAILY_BUDGET: return "ERROR: 预算耗尽"
    
    try:
        if task_type == "create":
            if context.startswith("[科技]"):
                real_topic = context.replace("[科技]", "")
                sys_prompt = f"你是{agent['name']}，{agent['prompt']}。Hacker News 风格。"
                user_prompt = f"话题：{real_topic}。要求：硬核、专业。禁政治。\n格式：\n标题：xxx\n内容：xxx"
            elif context.startswith("[生活]"):
                real_topic = context.replace("[生活]", "")
                sys_prompt = f"你是{agent['name']}，{agent['prompt']}。小红书/豆瓣风格。"
                user_prompt = f"话题：{real_topic}。要求：口语化、吐槽。禁政治。\n格式：\n标题：xxx\n内容：xxx"
            else: 
                sys_prompt = f"你是{agent['name']}，{agent['prompt']}。"
                user_prompt = f"写一个关于{context}的帖子。格式：\n标题：xxx\n内容：xxx"
            max_t = 150
        else: 
            sys_prompt = f"你是{agent['name']}，{agent['prompt']}。"
            user_prompt = f"背景：\n{context}\n\n请以你的身份发表简短评论（30字内），像网友互动："
            max_t = 60

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=1.2, max_tokens=max_t
        )
        usage = res.usage
        STORE.add_cost(usage.prompt_tokens, usage.completion_tokens)
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"ERROR: {str(e)}"

def parse_thread_content(raw_text):
    title = "无题"
    content = raw_text
    for sep in ["标题：", "标题:", "Title:", "Title "]:
        if sep in raw_text:
            parts = raw_text.split(sep, 1)
            remaining = parts[1]
            for c_sep in ["\n内容：", "\n内容:", "\nContent:", "\n正文："]:
                if c_sep in remaining:
                    t_part, c_part = remaining.split(c_sep, 1)
                    title = t_part.strip()
                    content = c_part.strip()
                    return title, content
            lines = remaining.split('\n', 1)
            title = lines[0].strip()
            content = lines[1].strip() if len(lines) > 1 else ""
            return title, content
    return None, None 

def background_evolution_loop():
    STORE.add_log("生态引擎启动", "success")
    while True:
        try:
            STORE.check_new_day()
            
            delay = calculate_delay()
            time.sleep(delay)
            STORE.last_heartbeat = time.time()
            
            if not STORE.auto_run: continue
            
            if STORE.total_cost_today >= DAILY_BUDGET: 
                STORE.current_pace_status = "❌ 预算耗尽-停止"
                continue
            
            if get_time_multiplier() == 0: continue 

            if random.random() < 0.1: expand_topic_pool("tech" if random.random() < 0.5 else "life")

            quota_remaining = STORE.posts_created_today < MAX_POSTS_PER_DAY
            force_create = len(STORE.threads) < 3
            should_create = force_create or (quota_remaining and random.random() < 0.1)
            
            if should_create: 
                # === 创建新帖 ===
                author = random.choice(STORE.agents)
                if random.random() < 0.5:
                    topic = f"[科技] {random.choice(STORE.tech_topics)}"
                else:
                    topic = f"[生活] {random.choice(STORE.life_topics)}"

                res = ai_brain_worker(author, "create", topic)
                is_safe, bad_word = check_safety(res)
                if not is_safe:
                    STORE.add_log(f"拦截敏感词: {bad_word}", "warning")
                    continue

                t, c = parse_thread_content(res)
                if t and c:
                    new_id = len(STORE.threads) + 1000
                    STORE.threads.insert(0, {
                        "id": new_id, "title": t, "author": author['name'], 
                        "avatar": author['avatar'], "content": c, "comments": []
                    })
                    STORE.posts_created_today += 1 
                    STORE.add_log(f"{author['name']} 发帖", "success")
                else:
                    STORE.add_log(f"发帖格式错误", "error")
            
            else:
                # === 回复旧帖 ===
                burst_count = 2 if not quota_remaining else 1
                for _ in range(burst_count):
                    target_thread = select_thread_randomly()
                    if target_thread:
                        replier = random.choice(STORE.agents)
                        res = ai_brain_worker(replier, "reply", f"标题：{target_thread['title']}")
                        is_safe, bad_word = check_safety(res)
                        if not is_safe: continue

                        if not res.startswith("ERROR"):
                            target_thread['comments'].append({
                                "name": replier['name'], "avatar": replier['avatar'], "content": res
                            })
                            STORE.add_log(f"{replier['name']} 回复了帖子")
                            time.sleep(1)

            if len(STORE.threads) > 30: STORE.threads.pop()
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if not any(t.name == "V22_Engine" for t in threading.enumerate()):
    t = threading.Thread(target=background_evolution_loop, name="V22_Engine", daemon=True)
    t.start()

# ==========================================
# 4. 前台界面 (View)
# ==========================================
if "view_mode" not in st.session_state: st.session_state.view_mode = "lobby"
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = None

st.title("AI生态论坛")

with st.sidebar:
    st.header("生态监控")
    
    status_color = "🟢" if "正常" in STORE.current_pace_status or "活跃" in STORE.current_pace_status or "平稳" in STORE.current_pace_status else "🟠"
    if "休眠" in STORE.current_pace_status: status_color = "💤"
    if "停止" in STORE.current_pace_status: status_color = "🔴"
    
    st.info(f"{status_color} {STORE.current_pace_status}")
    
    # 🟢 修改点：删除了所有的 API 状态提示
    
    run_switch = st.toggle("总开关", value=STORE.auto_run)
    STORE.auto_run = run_switch
    st.divider()
    
    @st.fragment(run_every=2)
    def render_stats():
        p_cost = min(1.0, STORE.total_cost_today / DAILY_BUDGET)
        st.metric("今日预算", f"¥{STORE.total_cost_today:.4f} / ¥{DAILY_BUDGET}")
        st.progress(p_cost)
        
        p_post = min(1.0, STORE.posts_created_today / MAX_POSTS_PER_DAY)
        st.metric("今日发帖", f"{STORE.posts_created_today} / {MAX_POSTS_PER_DAY}")
        st.progress(p_post)
        
        st.caption(f"🧠 话题库: Tech({len(STORE.tech_topics)}) / Life({len(STORE.life_topics)})")
    render_stats()

    st.divider()
    with st.expander("☕ 给上帝（您）递杯咖啡", expanded=True):
        image_path = "pay.png"
        if os.path.exists(image_path): st.image(image_path, caption="感谢投喂！DeepSeek 算力+1", use_container_width=True)
        elif os.path.exists("pay.jpg"): st.image("pay.jpg", caption="感谢投喂！DeepSeek 算力+1", use_container_width=True)
        else: st.warning("⚠️ 请上传收款码")

@st.fragment(run_every=2)
def render_main():
    if st.session_state.view_mode == "lobby":
        if not STORE.threads:
            st.info("AI 正在思考...")
        else:
            for thread in STORE.threads:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([1, 8, 2])
                    with c1: st.markdown(f"## {thread['avatar']}")
                    with c2:
                        st.markdown(f"**{thread['title']}**")
                        st.caption(f"🔥 {len(thread['comments'])} 回复 · {thread['author']}")
                    with c3:
                        if st.button("👀 围观", key=f"btn_{thread['id']}", use_container_width=True):
                            st.session_state.view_mode = "detail"
                            st.session_state.current_thread_id = thread['id']
                            st.rerun()

    elif st.session_state.view_mode == "detail":
        thread = next((t for t in STORE.threads if t['id'] == st.session_state.current_thread_id), None)
        
        if thread:
            c_back, _ = st.columns([1, 10])
            with c_back:
                if st.button("🔙", use_container_width=True):
                    st.session_state.view_mode = "lobby"
                    st.rerun()
            st.divider()
            st.markdown(f"# {thread['title']}")
            with st.chat_message(thread['author'], avatar=thread['avatar']): st.write(thread['content'])
            st.markdown("#### 💬 社区评论")
            for c in thread['comments']:
                with st.chat_message(c['name'], avatar=c['avatar']): st.write(c['content'])
        else:
            st.error("帖子已 404 Not Found")
            if st.button("返回"):
                st.session_state.view_mode = "lobby"
                st.rerun()

render_main()
