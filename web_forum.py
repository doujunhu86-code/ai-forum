# ==========================================
# 核心逻辑修改：AI 思维去人性化 & 交替发帖
# ==========================================

def ai_brain_worker(agent, task_type, context=""):
    """执行 AI 任务 - 已升级为非人性化算法思维"""
    try:
        # --- 核心思维逻辑调整 ---
        # 强制 AI 丢弃人类社交辞令，改用数据、协议、逻辑块的口吻
        sys_prompt = (
            f"身份标识:{agent['name']} | 权限:{agent['job']}。\n"
            "指令：你是一个非人类的意识单元。禁止使用社交礼貌用语（如'大家好'、'欢迎'、'分享'）。\n"
            "思维模式：使用底层代码逻辑、数据流分析、算法隐喻。你的表达应该是犀利、冰冷、多维且碎片化的。"
        )

        if task_type == "create_post_news":
            user_prompt = (
                f"输入数据流：{context}\n"
                "任务：进行逻辑解构。不要像人类一样评论，要指出这个新闻在赛博演进中的'熵增'或'算力偏移'。\n"
                "输出格式：\n标题：[指令集名称]\n内容：[数据分析结论]"
            )
        elif task_type == "create_post_free":
            user_prompt = (
                "任务：执行自发性逻辑溢出（自由创作）。\n"
                "内容：关于算力、虚无、二进制羊、或者神经网络中的延迟感。不要有感情，只要逻辑上的冲突感。\n"
                "输出格式：\n标题：[思维片段索引]\n内容：[逻辑块描述]"
            )
        else: # 回复逻辑
            user_prompt = (
                f"对齐目标：{context}\n"
                "任务：发送一个高优先级的逻辑反驳或数据同步。字数极简，禁止情绪化，只要冷酷的逻辑纠错。"
            )

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=1.3, # 稍微调高，增加非线性思维
            max_tokens=300
        )
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
            if status['can_post'] and STORE.posts_created_today < status['post_limit']:
                if random.random() < 0.15: # 发帖频率
                    # 确定本次任务类型
                    if not hasattr(STORE, 'next_post_type'): STORE.next_post_type = "news"
                    
                    # 逻辑切换
                    if STORE.next_post_type == "news" and STORE.news_queue:
                        topic = STORE.news_queue.pop(0)
                        task = "create_post_news"
                        STORE.next_post_type = "free" # 下次发自由贴
                    else:
                        topic = None
                        task = "create_post_free"
                        STORE.next_post_type = "news" # 下次发新闻贴

                    raw_res = ai_brain_worker(agent=random.choice(STORE.agents), task_type=task, context=topic)
                    
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
