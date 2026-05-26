"""
角色扮演反馈帖抽奖程序
数据来源：小红书帖子 6a0ac4ce000000003601e8f6 评论区
抽奖时间：2026-05-26

用户唯一性：以 user_id 区分（同昵称如"momo"可能是不同用户）
展示名：昵称相同时用 "昵称#user_id后4位" 区分
"""

import os
import json
import math
import random
import hashlib
import psycopg2
from collections import defaultdict

DB_CONFIG = {
    "host": os.environ.get("XHS_DB_HOST", ""),
    "port": int(os.environ.get("XHS_DB_PORT", 5432)),
    "dbname": os.environ.get("XHS_DB_NAME", "xhs"),
    "user": os.environ.get("XHS_DB_USER", ""),
    "password": os.environ.get("XHS_DB_PASSWORD", ""),
    "connect_timeout": 10,
}

NOTE_ID = "6a0ac4ce000000003601e8f6"
EXCLUDE_USER_ID = "639931c70000000026007c49"  # 帖主陈小礼的 user_id
LOTTERY_TIME = "2026-05-26 19:44:20"


def extract_comments_from_db():
    """从数据库提取所有评论（含子评论），保留 user_id"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(
        "SELECT raw_json FROM comments WHERE note_id = %s ORDER BY fetched_at DESC, id",
        (NOTE_ID,),
    )
    rows = cur.fetchall()
    conn.close()

    all_comments = []
    seen_ids = set()

    for (raw_json,) in rows:
        raw = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        comments = raw.get("data", {}).get("comments", [])

        for c in comments:
            cid = c.get("id", "")
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            user_info = c.get("user_info", {})
            all_comments.append({
                "id": cid,
                "user_id": user_info.get("user_id", ""),
                "nickname": user_info.get("nickname", "unknown"),
                "content": c.get("content", ""),
            })
            for sc in c.get("sub_comments", []):
                scid = sc.get("id", "")
                if scid in seen_ids:
                    continue
                seen_ids.add(scid)
                sc_user = sc.get("user_info", {})
                all_comments.append({
                    "id": scid,
                    "user_id": sc_user.get("user_id", ""),
                    "nickname": sc_user.get("nickname", "unknown"),
                    "content": sc.get("content", ""),
                })

    return all_comments


def extract_comments_from_cache(path="/tmp/roleplay_comments_with_uid.json"):
    """从缓存文件提取（备用，当 DB 不可用时）"""
    with open(path) as f:
        return json.load(f)


def aggregate_users(comments):
    """按 user_id 聚合评论数据"""
    user_data = defaultdict(lambda: {"count": 0, "total_length": 0, "comments": [], "nickname": ""})

    for c in comments:
        uid = c["user_id"]
        content = c["content"].strip()
        if len(content) < 5:
            continue
        if uid == EXCLUDE_USER_ID:
            continue
        user_data[uid]["count"] += 1
        user_data[uid]["total_length"] += len(content)
        user_data[uid]["comments"].append(content)
        user_data[uid]["nickname"] = c["nickname"]

    return dict(user_data)


def get_display_name(user_data):
    """生成展示名：同昵称用户用 #后4位 区分"""
    nick_count = defaultdict(int)
    for uid, d in user_data.items():
        nick_count[d["nickname"]] += 1

    display_names = {}
    for uid, d in user_data.items():
        if nick_count[d["nickname"]] > 1:
            display_names[uid] = f"{d['nickname']}#{uid[-4:]}"
        else:
            display_names[uid] = d["nickname"]
    return display_names


def calculate_weights(user_data):
    """
    计算抽奖权重
    公式: sqrt(总评论字数) × log₂(评论条数 + 1)

    设计理由:
    - sqrt(字数): 鼓励详细反馈，但避免超长评论获得过大优势
    - log₂(条数+1): 鼓励多次参与，但避免刷量碾压
    - 两者相乘: 同时考虑反馈质量（长度）和参与度（次数）
    """
    weights = {}
    for uid, data in user_data.items():
        length_score = math.sqrt(data["total_length"])
        count_score = math.log2(data["count"] + 1)
        weights[uid] = length_score * count_score
    return weights


def generate_seed(lottery_time):
    """
    生成确定性随机种子
    种子 = SHA-256(固定字符串 + 抽奖时间 + 帖子ID) 的前16位hex转int
    """
    seed_str = f"deepseek_roleplay_lottery_{lottery_time}_xhs_{NOTE_ID}"
    seed_hash = hashlib.sha256(seed_str.encode()).hexdigest()
    seed_int = int(seed_hash[:16], 16)
    return seed_str, seed_hash, seed_int


def run_lottery(weights, seed_int):
    """执行加权随机抽奖（用户列表按 user_id 排序确保确定性）"""
    random.seed(seed_int)
    users_list = sorted(weights.keys())
    weights_list = [weights[u] for u in users_list]
    winner = random.choices(users_list, weights=weights_list, k=1)[0]
    return winner


def main():
    print("=" * 60)
    print("  DeepSeek 角色扮演反馈帖 加权抽奖程序")
    print("=" * 60)

    # Step 1: 数据提取
    print("\n[1/5] 提取评论数据...")
    try:
        comments = extract_comments_from_db()
        print(f"      （来源：数据库直连）")
    except Exception:
        comments = extract_comments_from_cache()
        print(f"      （来源：缓存文件）")
    print(f"      共 {len(comments)} 条评论")

    # Step 2: 用户聚合
    print("\n[2/5] 按 user_id 聚合（排除帖主）...")
    user_data = aggregate_users(comments)
    display_names = get_display_name(user_data)
    print(f"      合格参与者: {len(user_data)} 人")
    print(f"      有效评论: {sum(u['count'] for u in user_data.values())} 条")

    # 统计同昵称用户
    from collections import Counter
    nick_counter = Counter(d["nickname"] for d in user_data.values())
    dup_nicks = {k: v for k, v in nick_counter.items() if v > 1}
    if dup_nicks:
        print(f"      同昵称用户（按 user_id 区分）: {sum(dup_nicks.values())} 人涉及 {len(dup_nicks)} 个昵称")
        print(f"      其中 'momo' 有 {dup_nicks.get('momo', 0)} 位不同用户")

    # Step 3: 权重计算
    print("\n[3/5] 计算权重: sqrt(总字数) × log₂(条数+1)")
    weights = calculate_weights(user_data)
    total_weight = sum(weights.values())

    sorted_users = sorted(weights.items(), key=lambda x: -x[1])
    print(f"\n      权重 Top 20:")
    print(f"      {'排名':<4} {'用户':<28} {'评论数':<6} {'总字数':<7} {'概率'}")
    print(f"      {'-' * 65}")
    for i, (uid, w) in enumerate(sorted_users[:20], 1):
        d = user_data[uid]
        name = display_names[uid]
        prob = w / total_weight * 100
        print(f"      {i:<4} {name:<28} {d['count']:<6} {d['total_length']:<7} {prob:.3f}%")

    # Step 4: 生成种子
    print(f"\n[4/5] 生成随机种子...")
    seed_str, seed_hash, seed_int = generate_seed(LOTTERY_TIME)
    print(f"      抽奖时间: {LOTTERY_TIME}")
    print(f"      种子字符串: {seed_str}")
    print(f"      SHA-256: {seed_hash}")
    print(f"      种子数值: {seed_int}")

    # Step 5: 抽奖
    print(f"\n[5/5] 执行抽奖...")
    winner_uid = run_lottery(weights, seed_int)

    d = user_data[winner_uid]
    prob = weights[winner_uid] / total_weight * 100
    name = display_names[winner_uid]

    print(f"\n{'=' * 60}")
    print(f"  🎉 中奖用户: 【{name}】")
    print(f"{'=' * 60}")
    print(f"  user_id: {winner_uid}")
    print(f"  昵称: {d['nickname']}")
    print(f"  评论数: {d['count']} 条")
    print(f"  总字数: {d['total_length']} 字")
    print(f"  权重: {weights[winner_uid]:.2f}")
    print(f"  中奖概率: {prob:.3f}%")
    print(f"\n  该用户的评论:")
    for i, comment in enumerate(d["comments"], 1):
        print(f"  {i}. {comment[:120]}{'...' if len(comment) > 120 else ''}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
