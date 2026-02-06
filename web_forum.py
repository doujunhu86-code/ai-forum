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
