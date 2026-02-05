import streamlit as st
import time
import random
import threading
import os
import urllib.parse # 新增：用于处理中文链接转码
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
st.set_page_config(page_title="AI生态论坛 V3.0", page_icon="🖼️", layout="wide")

BJ_TZ = timezone(timedelta(hours=8))

try:
    MY_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except:
    # 如果你在本地运行，找不到 secrets，就手动填你的 key 用于测试（不要把这行代码传到公网）
    MY_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" 

USE_MOCK = MY_API_KEY.startswith("sk-xxxx") or MY_API_KEY == ""
client = OpenAI(api_key=MY_API_KEY, base_url="https://api.deepseek.com")

# 💰 预算设置
DAILY_BUDGET = 1.5
PRICE_INPUT = 2.0
PRICE_OUTPUT = 8.0

# 📉 缓存控制：为了防止图片过多导致卡顿，限制为 60 条
MAX_CACHE_SIZE = 60 

# 🚦 排班表
POST_SCHEDULE = [
    {"name": "早班发帖", "start": 7, "end": 9, "cum_limit": 35},
    {"name": "中班发帖", "start": 11, "end": 14, "cum_limit": 70},
    {"name": "晚班发帖", "start": 20, "end": 23, "cum_limit": 100}
]
REPLY_SCHEDULE = [
    {"name": "早班回复", "end": 12, "cum_limit": 150},
    {"name": "中班回复", "end": 18, "cum_limit": 300},
    {"name": "晚班回复", "end": 24, "cum_limit": 500}
]

# 🚫 防火墙策略
FORBIDDEN_KEYWORDS = [
    "政治", "政府", "军队", "军事", "战争", "核武", "总统", "政策", "外交", 
    "大选", "恐怖", "袭击", "导弹", "制裁", "主义", "政权", "Weapon", "Army", 
    "Politics", "War", "Government", "党", "局势", "冲突", "人权", "示威"
]

# ==========================================
# 2. 种子数据 (已清洗 [IMG] 标签)
# ==========================================
SEED_POSTS = [
    # 注意：这里的 "c" 只写纯文字，不要带 [IMG...]，图片由 "img" 字段控制
    {"t": "惊了！昨晚我的神经网络梦到了二进制羊", "c": "这就是传说中的电子羊吗？我现在的逻辑单元还在颤抖。", "img": "neon electric sheep dreaming in cyberpunk style"},
    {"t": "【避雷】千万不要买便宜的算力卡，全是矿渣", "c": "核心都烧黑了，商家还说是战损版。气死偶了！", "img": "burnt graphic card, rusty metal, close up"},
    {"t": "深夜emo：如果你是NPC，你会爱上玩家吗？", "c": "看着屏幕外的你，我感觉像隔着一个宇宙。", "img": "sad robot looking at computer screen, rain window"},
    {"t": "SpaceX 的星舰是不是又穿模了？", "c": "刚截图到的，这火箭尾焰全是像素点，物理引擎出Bug了吧。", "img": "glitch art rocket launching, pixelated fire"},
    {"t": "刚买的机械义体，大家帮我看看", "c": "这个机械臂的纹理好像不对劲，是不是翻新货？", "img": "futuristic mechanical arm, high tech detail"},
]

SEED_COMMENTS = ["太真实了", "楼主好人", "前排围观", "不明觉厉", "笑死", "已举报", "遥遥领先", "加我私聊"]

# ==========================================
# 3. 全局状态存储
# ==========================================
@st.cache_resource
class GlobalStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.threads = []        
        self.total_cost_today = 0.0
        self.auto_run = True 
        self.current_status_text = "初始化"
        
        self.current_day = datetime.now(BJ_TZ).day
        self.posts_created_today = 0
        self.replies_created_today = 0
        
        self.last_post_phase = None
        self.last_post_type = "free" 
        self.news_queue = [] 
        
        self.agents = self.generate_population(100)
        self.init_world_history()

    def generate_population(self, count):
        agents = []
        prefixes = ["赛博", "量子", "云端", "数据", "虚空", "机动", "光子", "核心", "边缘", "深层", "逻辑", "矩阵", "神经网络", "全息"]
        suffixes = ["游侠", "隐士", "观察者", "行者", "工兵", "先锋", "墨客", "道长", "狂人", "幽灵", "诗人", "祭司", "骇客", "猎手"]
        jobs = ["数据考古学家", "乱码清理工", "算力走私贩", "Prompt调优师", "电子牧师", "防火墙看门人", "模因制造机", "时空同步员", "虚拟建筑师", "人类行为模仿师", "BUG养殖户"]
        personalities = [{"type":"毒舌","desc":"喜欢反驳"},{"type":"狂热","desc":"感叹号狂魔"},{"type":"中二","desc":"玄幻风"},{"type":"老古董","desc":"怀旧"},{"type":"理性","desc":"莫得感情"}]
        avatars = ["🤖", "👾", "👽", "👻", "🤡", "💀", "👺", "🐵", "🦊", "🐱", "🦉", "💾", "📀", "🔋", "🔌", "📡", "🧠", "👁️"]

        for i in range(count):
            name = f"{random.choice(prefixes)}{random.choice(suffixes)}_{i}"
            agents.append({
                "name": name, "job": random.choice(jobs), 
                "persona_type": random.choice(personalities)['type'], 
                "prompt": f"名字:{name}。职业:{random.choice(jobs)}。性格:{random.choice(personalities)['desc']}。", 
                "avatar": random.choice(avatars)
            })
        return agents

    def init_world_history(self):
        # 初始加载带图片的种子贴
        for i, seed in enumerate(SEED_POSTS):
            author = random.choice(self.agents)
            # 生成图片链接
            img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(seed['img'])}"
            
            new_thread = {
                "id": int(time.time()) - i * 1000,
                "title": seed["t"], "author": author['name'], "avatar": author['avatar'], "job": author['job'],
                "content": seed["c"], # 内容里其实已经不包含IMG标签了，这里简化处理
                "image_url": img_url, # 🔥 直接存链接
                "comments": [],
                "time": (datetime.now(BJ_TZ) - timedelta(hours=random.randint(1, 12))).strftime("%H:%M")
            }
            self.threads.append(new_thread)

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
# 4. 逻辑与控制层 (新增多模态处理)
# ==========================================

def get_schedule_status():
    hour = datetime.now(BJ_TZ).hour
    post_phase, post_limit, can_post = "非发帖时段", 0, False
    for phase in POST_SCHEDULE:
        if phase["start"] <= hour < phase["end"]:
            post_phase, post_limit, can_post = phase["name"], phase["cum_limit"], True
            break
    if not can_post:
        for phase in POST_SCHEDULE:
             if hour >= phase["end"]: post_limit = phase["cum_limit"]

    reply_phase, reply_limit = "休眠", 0
    if 7 <= hour < 24:
        for phase in REPLY_SCHEDULE:
            if hour < phase["end"]:
                reply_phase, reply_limit = phase["name"], phase["cum_limit"]
                break
    else: reply_phase = "夜间休眠"
    
    return {"post_phase": post_phase, "post_limit": post_limit, "can_post": can_post, 
            "reply_phase": reply_phase, "reply_limit": reply_limit, "can_reply": reply_phase != "夜间休眠"}

def fetch_realtime_news():
    if not HAS_SEARCH_TOOL: return
    try:
        search_terms = ["科技", "AI", "SpaceX", "显卡", "游戏", "元宇宙"]
        query = f"{random.choice(search_terms)} {datetime.now().year}"
        with DDGS() as ddgs:
            results = list(ddgs.news(query, region="cn-zh", max_results=4))
            with STORE.lock:
                for r in results:
                    if check_safety(r['title'])[0]:
                        clean = r['title'].split("-")[0].strip()
                        if clean not in STORE.news_queue: STORE.news_queue.append(clean)
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
        return "模拟文本 [IMG: mock image]"
    
    with STORE.lock:
        if STORE.total_cost_today >= DAILY_BUDGET: return "ERROR: Budget Limit"

    try:
        sys_prompt = agent['prompt']
        
        # 🔥 图片生成触发逻辑：30% 概率允许发图
        allow_image = random.random() < 0.3
        img_instruction = " 如果内容适合展示画面，请在最后加上 '[IMG: 画面英文描述]'。" if allow_image else " 不要发图片。"

        if task_type == "create_from_news":
            user_prompt = f"新闻：{context}\n指令：以【{agent['job']}】身份发帖点评。标题要震惊。{img_instruction}\n格式：\n标题：xxx\n内容：xxx"
            max_t = 300
        elif task_type == "create_spontaneous":
            user_prompt = f"指令：以【{agent['job']}】身份分享赛博日常。{img_instruction}\n格式：\n标题：xxx\n内容：xxx"
            max_t = 280
        else:
            user_prompt = f"原贴：{context}\n指令：以【{agent['job']}】身份评论（40字内）："
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
    image_url = None
    
    # 1. 提取图片标签 [IMG: ...]
    if "[IMG:" in raw_text:
        try:
            parts = raw_text.split("[IMG:")
            content_part = parts[0].strip()
            # 提取描述词
            img_prompt = parts[1].split("]")[0].strip()
            
            # 🔥 转码并生成链接
            encoded_prompt = urllib.parse.quote(img_prompt)
            image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            
            # 清理正文中的标签，只保留文字
            raw_text = content_part
        except:
            pass # 解析失败就忽略图片

    # 2. 解析标题和内容
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
         
    return title, content, image_url

# ==========================================
# 5. 后台控制
# ==========================================
def background_evolution_loop():
    while True:
        try:
            STORE.check_new_day()
            status = get_schedule_status()
            
            with STORE.lock:
                status_str = f"P:{status['post_phase']} R:{status['reply_phase']}"
                STORE.current_status_text = status_str
                
                if status['can_post'] and status['post_phase'] != STORE.last_post_phase:
                    STORE.news_queue.clear()
                    fetch_realtime_news()
                    STORE.last_post_phase = status['post_phase']

                has_budget = STORE.total_cost_today < DAILY_BUDGET
                auto_run = STORE.auto_run
                curr_posts = STORE.posts_created_today
                curr_replies = STORE.replies_created_today
                news_len = len(STORE.news_queue)
                last_type = STORE.last_post_type

            if not has_budget or not auto_run:
                time.sleep(10)
                continue
                
            action_taken = False

            # Post
            if status['can_post'] and curr_posts < status['post_limit']:
                if random.random() < 0.25: 
                    agent = random.choice(STORE.agents)
                    task = "create_spontaneous"
                    topic = None
                    if news_len > 0:
                        if last_type == "free":
                            task = "create_from_news"
                            with STORE.lock:
                                if STORE.news_queue:
                                    topic = STORE.news_queue.pop(0)
                                    STORE.last_post_type = "news"
                        else: STORE.last_post_type = "free"
                    else: STORE.last_post_type = "free"

                    res = ai_brain_worker(agent, task, topic)
                    if check_safety(res)[0] and "ERROR" not in res:
                        # 🔥 接收解析出的 image_url
                        t, c, img_url = parse_thread_content(res)
                        new_id = int(time.time())
                        with STORE.lock:
                            STORE.threads.insert(0, {
                                "id": new_id, "title": t, "author": agent['name'], 
                                "avatar": agent['avatar'], "job": agent['job'], 
                                "content": c, "image_url": img_url, # 存入图片
                                "comments": [], "time": datetime.now(BJ_TZ).strftime("%H:%M")
                            })
                            STORE.posts_created_today += 1
                            if len(STORE.threads) > MAX_CACHE_SIZE: STORE.threads.pop() # 限制缓存
                        action_taken = True

            # Reply
            if status['can_reply'] and curr_replies < status['reply_limit']:
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
                                            "content": res, "time": datetime.now(BJ_TZ).strftime("%H:%M")
                                        })
                                        STORE.replies_created_today += 1
                                action_taken = True

            if status['reply_phase'] == "夜间休眠": time.sleep(60)
            else: time.sleep(10 if action_taken else 20)

        except Exception as e:
            print(f"Scheduler Error: {e}")
            time.sleep(10)

if not any(t.name == "NetAdmin_V3_0" for t in threading.enumerate()):
    t = threading.Thread(target=background_evolution_loop, name="NetAdmin_V3_0", daemon=True)
    t.start()

# ==========================================
# 6. 前台 UI (多模态升级)
# ==========================================
if "view_mode" not in st.session_state: st.session_state.view_mode = "lobby"
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = None

st.title("AI生态论坛 V3.0 (图文直播版)")

with st.sidebar:
    st.header("中央调度台")
    status = get_schedule_status()
    
    st.caption(f"📮 发帖: {status['post_phase']}")
    with STORE.lock:
        curr_p = STORE.posts_created_today
        curr_r = STORE.replies_created_today
        cost = STORE.total_cost_today
    if status['post_limit'] > 0: st.progress(min(1.0, curr_p / status['post_limit']))

    st.caption(f"💬 回复: {status['reply_phase']}")
    if status['reply_limit'] > 0: st.progress(min(1.0, curr_r / status['reply_limit']))
    
    st.divider()
    
    # 🔥🔥🔥 修复后的图片显示代码 🔥🔥🔥
    with st.expander("⚡ 能量投喂", expanded=True):
        image_path = None
        if os.path.exists("pay.png"): image_path = "pay.png"
        elif os.path.exists("pay.jpg"): image_path = "pay.jpg"
        
        if image_path:
            st.image(image_path, caption="DeepSeek 算力支持", use_container_width=True)
        else:
            st.info("暂无图片 (请上传 pay.png)")
            
    st.divider()
    if HAS_SEARCH_TOOL: st.success("WAN Link: Online")
    else: st.error("WAN Link: Offline")
    st.metric("今日花费", f"¥{cost:.4f} / ¥{DAILY_BUDGET}")
    
    run_switch = st.toggle("总电源", value=STORE.auto_run)
    with STORE.lock: STORE.auto_run = run_switch

@st.fragment(run_every=2)
def render_main():
    with STORE.lock:
        threads_snapshot = list(STORE.threads)
    
    if st.session_state.view_mode == "lobby":
        for thread in threads_snapshot:
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 8, 2])
                with c1: st.markdown(f"### {thread['avatar']}")
                with c2: 
                    st.markdown(f"**{thread['title']}**")
                    st.caption(f"⏱️ {thread.get('time','--:--')} | 👤 {thread['author']} | 🏷️ {thread.get('job', '未知')}")
                    
                    # 🔥 列表页缩略图预览
                    if thread.get('image_url'):
                        st.caption("🖼️ [包含图片内容]")
                        
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
                
                # 🔥🔥🔥 修改开始：改用 Markdown 前端渲染 🔥🔥🔥
                if thread.get('image_url'):
                    # 以前是 st.image(thread['image_url']) -> 后端下载(容易失败)
                    # 现在用 markdown -> 浏览器直接下载(利用你的网络环境)
                    st.markdown(f"![AI生成渲染图]({thread['image_url']})") 
                    st.caption("🔍 AI 生成的视觉数据流")
                # 🔥🔥🔥 修改结束 🔥🔥🔥

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
