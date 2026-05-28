"""
角色扮演反馈帖抽奖程序（第二轮：20张贴纸）
数据来源：小红书帖子 6a0ac4ce000000003601e8f6 评论区
抽奖时间：2026-05-28

规则：
- 同第一轮权重公式: sqrt(总字数) × log₂(条数+1)
- 排除帖主「陈小礼」
- 排除第一轮中奖者「星屿间」(user_id: 64a136a8000000001f005dd1)
- 抽取 20 位不重复中奖用户
- 随机种子：当前时间确定性种子
"""

import json
import math
import random
import hashlib
from collections import defaultdict, Counter

DB_CONFIG = {
    "host": "<DB_HOST>",
    "port": 5432,
    "dbname": "<DB_NAME>",
    "user": "<DB_USER>",
    "password": "<DB_PASSWORD>",
    "connect_timeout": 10,
}

NOTE_ID = "6a0ac4ce000000003601e8f6"
EXCLUDE_USER_IDS = {
    "639931c70000000026007c49",  # 帖主陈小礼
    "64a136a8000000001f005dd1",  # 第一轮中奖者：星屿间
}
LOTTERY_TIME = "2026-05-28 15:26:26"
NUM_WINNERS = 20


def extract_comments_from_db():
    """从数据库提取所有评论（含子评论），保留 user_id"""
    import psycopg2
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


def aggregate_users(comments):
    """按 user_id 聚合评论数据，排除帖主和第一轮中奖者"""
    user_data = defaultdict(lambda: {"count": 0, "total_length": 0, "comments": [], "nickname": ""})

    for c in comments:
        uid = c["user_id"]
        content = c["content"].strip()
        if len(content) < 5:
            continue
        if uid in EXCLUDE_USER_IDS:
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
    """
    weights = {}
    for uid, data in user_data.items():
        length_score = math.sqrt(data["total_length"])
        count_score = math.log2(data["count"] + 1)
        weights[uid] = length_score * count_score
    return weights


def generate_seed(lottery_time):
    """生成确定性随机种子"""
    seed_str = f"deepseek_roleplay_lottery_round2_{lottery_time}_xhs_{NOTE_ID}"
    seed_hash = hashlib.sha256(seed_str.encode()).hexdigest()
    seed_int = int(seed_hash[:16], 16)
    return seed_str, seed_hash, seed_int


def run_lottery(weights, seed_int, num_winners):
    """执行加权随机抽奖，抽取 num_winners 位不重复中奖者"""
    random.seed(seed_int)
    users_list = sorted(weights.keys())
    weights_list = [weights[u] for u in users_list]

    winners = []
    remaining_users = list(users_list)
    remaining_weights = list(weights_list)

    for _ in range(num_winners):
        if not remaining_users:
            break
        chosen = random.choices(remaining_users, weights=remaining_weights, k=1)[0]
        winners.append(chosen)
        idx = remaining_users.index(chosen)
        remaining_users.pop(idx)
        remaining_weights.pop(idx)

    return winners


def main():
    print("=" * 60)
    print("  DeepSeek 角色扮演反馈帖 第二轮抽奖（20张贴纸）")
    print("=" * 60)

    # Step 1: 数据提取
    print("\n[1/5] 提取评论数据...")
    try:
        comments = extract_comments_from_db()
        print(f"      （来源：数据库直连）")
    except Exception as e:
        print(f"      数据库连接失败({e})，使用缓存文件...")
        with open("roleplay_comments_with_uid.json") as f:
            comments = json.load(f)
        print(f"      （来源：缓存文件）")
    print(f"      共 {len(comments)} 条评论")

    # Step 2: 用户聚合
    print("\n[2/5] 按 user_id 聚合（排除帖主+第一轮中奖者）...")
    user_data = aggregate_users(comments)
    display_names = get_display_name(user_data)
    print(f"      合格参与者: {len(user_data)} 人")
    print(f"      有效评论: {sum(u['count'] for u in user_data.values())} 条")
    print(f"      排除用户: 帖主(陈小礼) + 第一轮中奖者(星屿间)")

    nick_counter = Counter(d["nickname"] for d in user_data.values())
    dup_nicks = {k: v for k, v in nick_counter.items() if v > 1}
    if dup_nicks:
        print(f"      同昵称用户（按 user_id 区分）: {sum(dup_nicks.values())} 人涉及 {len(dup_nicks)} 个昵称")

    # Step 3: 权重计算
    print("\n[3/5] 计算权重: sqrt(总字数) × log₂(条数+1)")
    weights = calculate_weights(user_data)
    total_weight = sum(weights.values())

    sorted_users = sorted(weights.items(), key=lambda x: -x[1])
    print(f"\n      权重 Top 20:")
    print(f"      {'排名':<4} {'用户':<28} {'user_id':<28} {'评论数':<6} {'总字数':<7} {'概率'}")
    print(f"      {'-' * 85}")
    for i, (uid, w) in enumerate(sorted_users[:20], 1):
        d = user_data[uid]
        name = display_names[uid]
        prob = w / total_weight * 100
        print(f"      {i:<4} {name:<28} {uid:<28} {d['count']:<6} {d['total_length']:<7} {prob:.3f}%")

    # Step 4: 生成种子
    print(f"\n[4/5] 生成随机种子...")
    seed_str, seed_hash, seed_int = generate_seed(LOTTERY_TIME)
    print(f"      抽奖时间: {LOTTERY_TIME}")
    print(f"      种子字符串: {seed_str}")
    print(f"      SHA-256: {seed_hash}")
    print(f"      种子数值: {seed_int}")

    # Step 5: 抽奖
    print(f"\n[5/5] 执行抽奖（抽取 {NUM_WINNERS} 位）...")
    winners = run_lottery(weights, seed_int, NUM_WINNERS)

    print(f"\n{'=' * 60}")
    print(f"  🎉 第二轮中奖名单（共 {len(winners)} 位）")
    print(f"{'=' * 60}")
    print(f"\n  {'序号':<4} {'用户':<28} {'user_id':<28} {'评论数':<6} {'总字数':<7} {'概率'}")
    print(f"  {'-' * 85}")

    for i, uid in enumerate(winners, 1):
        d = user_data[uid]
        name = display_names[uid]
        prob = weights[uid] / total_weight * 100
        print(f"  {i:<4} {name:<28} {uid:<28} {d['count']:<6} {d['total_length']:<7} {prob:.3f}%")

    print(f"\n{'=' * 60}")
    print(f"\n  抽奖参数汇总:")
    print(f"  - 参与用户: {len(user_data)} 人")
    print(f"  - 中奖人数: {len(winners)} 人")
    print(f"  - 随机种子时间: {LOTTERY_TIME}")
    print(f"  - 种子SHA-256: {seed_hash}")
    print(f"  - 权重公式: sqrt(总字数) × log₂(条数+1)")
    print(f"  - 排除: 帖主 + 第一轮中奖者")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
