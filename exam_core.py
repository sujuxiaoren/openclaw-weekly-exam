#!/usr/bin/env python3
"""周周考核心题库解析、匹配与考前估分引擎（供 CLI 与桌面 GUI 共用）"""

import difflib
import re

EXAM_URL = "https://kaoshi.wjx.top/vm/rimKLVu.aspx"

ENV_CONFIGS = {
    "wecom_iphone": {
        "name": "iPhone 企业微信",
        "gui_label": "企业微信 (苹果手机)",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 wxwork/4.1.10 MicroMessenger/7.0.1 Language/zh_CN",
        "viewport": {"width": 390, "height": 844},
    },
    "wecom_android": {
        "name": "Android 企业微信",
        "gui_label": "企业微信 (安卓手机)",
        "user_agent": "Mozilla/5.0 (Linux; Android 13; SM-G998B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 wxwork/4.1.10 MicroMessenger/7.0.1.2080 NetType/WIFI Language/zh_CN ABI/arm64",
        "viewport": {"width": 412, "height": 915},
    },
    "wechat_iphone": {
        "name": "iPhone 微信",
        "gui_label": "微信 (苹果手机)",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.42(0x18002a24) NetType/WIFI Language/zh_CN",
        "viewport": {"width": 390, "height": 844},
    },
    "wechat_android": {
        "name": "Android 微信",
        "gui_label": "微信 (安卓手机)",
        "user_agent": "Mozilla/5.0 (Linux; Android 13; SM-G998B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.41.2441(0x28002951) Process/appbrand0 WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
        "viewport": {"width": 412, "height": 915},
    },
    "pc": {
        "name": "电脑浏览器",
        "gui_label": "电脑浏览器 (Windows)",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
    },
}


def get_env_config(key_or_label, default_key="wecom_android"):
    """按 CLI key 或 GUI 中文名称获取模拟环境配置"""
    if key_or_label in ENV_CONFIGS:
        return ENV_CONFIGS[key_or_label]
    for cfg in ENV_CONFIGS.values():
        if cfg["gui_label"] in str(key_or_label):
            return cfg
    return ENV_CONFIGS[default_key]

# 默认题型配分（标准周周考：10单选30分 + 10多选50分 + 10判断20分 = 100分）
DEFAULT_TYPE_SCORES = {
    "单选题": 3.0,
    "多选题": 5.0,
    "判断题": 2.0,
}

# 综合相似度低于该阈值时判定为低置信度（仍填入最接近候选答案，但重点提示复核）
APPROX_MATCH_THRESHOLD = 0.55

_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_TYPE_TAG_RE = re.compile(r"[【\[（(]\s*(?:单选题|多选题|判断题)\s*[】\]）)]")
_LEADING_QNUM_RE = re.compile(r"^\s*\*?\s*\d+[\.\、\s]+")
_OPT_PREFIX_RE = re.compile(r"^\s*([A-Ha-h])[\.\、\):：\s]+(.*)$")
_OPT_STRIP_RE = re.compile(r"^\s*[A-Ha-h][\.\、\):：\s]+")
_NON_ALNUM_CN_RE = re.compile(r"[^\u4e00-\u9fa5a-zA-Z0-9]")


def strip_zero_width(text):
    """清除零宽字符等不可见字符"""
    if text is None:
        return ""
    return _ZERO_WIDTH_RE.sub("", str(text)).strip()


def normalize_text(text):
    """标准化题干：去零宽字符、题型标记、开头题号，保留中英文和数字小写"""
    text = strip_zero_width(text)
    if not text:
        return ""
    text = _TYPE_TAG_RE.sub("", text)
    text = _LEADING_QNUM_RE.sub("", text)
    return _NON_ALNUM_CN_RE.sub("", text).lower()


def normalize_option_variants(text):
    """返回选项的两种标准化形式（去字母前缀后 / 完整原文），防止字母开头名词被误截"""
    cleaned = strip_zero_width(text)
    if not cleaned:
        return "", ""
    stripped = _OPT_STRIP_RE.sub("", cleaned).strip()
    return (
        _NON_ALNUM_CN_RE.sub("", stripped).lower(),
        _NON_ALNUM_CN_RE.sub("", cleaned).lower(),
    )


def _normalize_qtype(raw_type, ans_raw="", options_map=None):
    """统一题型名称为 单选题 / 多选题 / 判断题"""
    t = strip_zero_width(raw_type)
    if "判断" in t:
        return "判断题"
    if "多选" in t:
        return "多选题"
    if "单选" in t:
        return "单选题"

    ans_s = strip_zero_width(ans_raw)
    if any(k in ans_s for k in ("正确", "错误", "对", "错", "√", "×")):
        return "判断题"
    letters = re.findall(r"[A-H]", ans_s.upper())
    if len(set(letters)) > 1:
        return "多选题"
    return "单选题"


def _detect_columns(header_row):
    """根据 Excel 第 1 行表头自动识别新版(6列)与旧版(10列)列映射"""
    headers = [strip_zero_width(c) for c in header_row]
    q_col = None
    ans_col = None
    type_col = None
    opt_col = None
    opt_cols = []

    for idx, h in enumerate(headers):
        if not h:
            continue
        if q_col is None and ("题目" in h or "题干" in h):
            q_col = idx
        elif ans_col is None and ("正确答案" in h or h == "答案"):
            ans_col = idx
        elif type_col is None and "题型" in h:
            type_col = idx
        elif h == "选项":
            opt_col = idx
        elif re.match(r"^选项\s*\d+$", h):
            opt_cols.append(idx)

    # 若未识别出表头关键字，按列数兜底推断
    if q_col is None or ans_col is None:
        if len(headers) >= 8:
            return {
                "type_col": 0,
                "q_col": 1,
                "opt_col": None,
                "opt_cols": [2, 3, 4, 5, 6],
                "ans_col": 7,
                "is_new": False,
            }
        return {
            "type_col": 1,
            "q_col": 2,
            "opt_col": 3,
            "opt_cols": [],
            "ans_col": 4,
            "is_new": True,
        }

    return {
        "type_col": type_col,
        "q_col": q_col,
        "opt_col": opt_col,
        "opt_cols": opt_cols,
        "ans_col": ans_col,
        "is_new": opt_col is not None,
    }


def _parse_options_from_row(row, col_map):
    """解析选项字典 {字母: 选项正文}，兼容单列多行与多列选项"""
    options_map = {}
    opt_col = col_map.get("opt_col")

    if opt_col is not None and opt_col < len(row) and row[opt_col]:
        raw_opts = strip_zero_width(row[opt_col])
        for line in raw_opts.splitlines():
            line = strip_zero_width(line)
            if not line:
                continue
            m = _OPT_PREFIX_RE.match(line)
            if m:
                options_map[m.group(1).upper()] = m.group(2).strip()
            else:
                letter = chr(ord("A") + len(options_map))
                options_map[letter] = line
        return options_map

    for idx, c_idx in enumerate(col_map.get("opt_cols", [])):
        if c_idx < len(row) and row[c_idx] is not None:
            val = strip_zero_width(row[c_idx])
            if not val:
                continue
            m = _OPT_PREFIX_RE.match(val)
            letter = chr(ord("A") + idx)
            options_map[letter] = m.group(2).strip() if m else val

    return options_map


def _parse_answer(ans_raw, qtype, options_map):
    """解析答案字段，返回 (ans_letters, judge_bool, ans_display, ans_opt_texts)"""
    ans_s = strip_zero_width(ans_raw)

    # 判断题优先识别语义
    is_true = any(k in ans_s for k in ("正确", "对", "√"))
    is_false = any(k in ans_s for k in ("错误", "错", "×"))
    if qtype == "判断题" or is_true or is_false:
        if is_true and not is_false:
            return ["A"], True, "正确 (√)", []
        if is_false and not is_true:
            return ["B"], False, "错误 (×)", []
        letters = list(dict.fromkeys(re.findall(r"[A-H]", ans_s.upper())))
        if letters == ["A"]:
            return ["A"], True, "正确 (√)", []
        if letters == ["B"]:
            return ["B"], False, "错误 (×)", []

    # 单选 / 多选：按顺序去重提取所有选项字母（兼容 A、B、C / ABC / A, B）
    letters = list(dict.fromkeys(re.findall(r"[A-H]", ans_s.upper())))
    ans_display = "、".join(letters) if letters else ans_s
    ans_opt_texts = [options_map[ch] for ch in letters if ch in options_map and options_map[ch]]
    return letters, None, ans_display, ans_opt_texts


def _build_unique_affix_index(entries, is_prefix=True):
    """仅收录答案完全无冲突的 15 字前缀/后缀索引，防止串题污染"""
    buckets = {}
    for e in entries:
        nq = e["norm_q"]
        if len(nq) < 15:
            continue
        key = nq[:15] if is_prefix else nq[-15:]
        buckets.setdefault(key, []).append(e)

    unique = {}
    for key, group in buckets.items():
        sigs = {(g["qtype"], g["ans_display"]) for g in group}
        if len(sigs) == 1:
            unique[key] = group[0]
    return unique


def load_question_bank(excel_path, log_fn=None):
    """加载题库，自动兼容新版 6 列（题库_2667道）与旧版 10 列模板"""
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Excel 文件为空，未读取到任何内容")

    col_map = _detect_columns(rows[0])
    entries = []
    exact_map = {}
    by_type = {"单选题": [], "多选题": [], "判断题": []}

    q_col = col_map["q_col"]
    ans_col = col_map["ans_col"]
    type_col = col_map["type_col"]

    for row in rows[1:]:
        if len(row) <= max(q_col, ans_col):
            continue
        q_val = row[q_col]
        ans_val = row[ans_col]
        if not q_val or not ans_val:
            continue

        raw_q = strip_zero_width(q_val)
        norm_q = normalize_text(raw_q)
        if len(norm_q) <= 2:
            continue

        raw_type = row[type_col] if (type_col is not None and type_col < len(row)) else ""
        options_map = _parse_options_from_row(row, col_map)
        qtype = _normalize_qtype(raw_type, ans_val, options_map)
        ans_letters, judge_bool, ans_display, ans_opt_texts = _parse_answer(ans_val, qtype, options_map)

        if not ans_letters and judge_bool is None:
            continue

        norm_all_opts = set()
        for v in options_map.values():
            v_strip, _ = normalize_option_variants(v)
            if v_strip:
                norm_all_opts.add(v_strip)

        norm_ans_opts = []
        for v in ans_opt_texts:
            v_strip, _ = normalize_option_variants(v)
            if v_strip:
                norm_ans_opts.append(v_strip)

        entry = {
            "qtype": qtype,
            "raw_q": raw_q,
            "norm_q": norm_q,
            "ans_letters": ans_letters,
            "judge_bool": judge_bool,
            "ans_display": ans_display,
            "options_map": options_map,
            "ans_opt_texts": ans_opt_texts,
            "norm_ans_opts": norm_ans_opts,
            "norm_all_opts": norm_all_opts,
        }
        entries.append(entry)
        exact_map.setdefault(norm_q, []).append(entry)
        by_type.setdefault(qtype, []).append(entry)

    bank = {
        "count": len(entries),
        "format": "新版6列格式" if col_map["is_new"] else "经典10列格式",
        "entries": entries,
        "exact_map": exact_map,
        "by_type": by_type,
        "prefix_unique": _build_unique_affix_index(entries, is_prefix=True),
        "suffix_unique": _build_unique_affix_index(entries, is_prefix=False),
    }

    if log_fn:
        log_fn(
            f"📚 题库加载完毕（{bank['format']}）：共 {len(entries)} 题"
            f"（单选 {len(by_type['单选题'])} / 多选 {len(by_type['多选题'])} / 判断 {len(by_type['判断题'])}）"
        )
    return bank


def infer_page_qtype(label_full_text, has_checkbox, page_opt_texts):
    """根据页面标签、输入控件类型与选项特征识别当前题型"""
    text = strip_zero_width(label_full_text)
    if has_checkbox or "多选题" in text:
        return "多选题"
    if "判断题" in text:
        return "判断题"

    if len(page_opt_texts) == 2:
        norm_opts = {normalize_option_variants(t)[0] for t in page_opt_texts}
        if norm_opts <= {"正确", "错误", "对", "错"} and len(norm_opts) == 2:
            return "判断题"

    return "单选题"


def _page_opts_norm_sets(page_opt_texts):
    """提取网页选项的标准化集合（兼容去前缀与原文）"""
    stripped_set = set()
    raw_set = set()
    for t in page_opt_texts:
        s_norm, r_norm = normalize_option_variants(t)
        if s_norm:
            stripped_set.add(s_norm)
        if r_norm:
            raw_set.add(r_norm)
    return stripped_set, raw_set


def _calc_option_overlap(stripped_set, raw_set, entry):
    """计算网页选项与题库选项的重合比例 (0.0 ~ 1.0)"""
    bank_opts = entry["norm_all_opts"]
    if not bank_opts or (not stripped_set and not raw_set):
        return 0.0
    combined_page = stripped_set | raw_set
    inter = len(bank_opts & combined_page)
    union = max(len(bank_opts), len(stripped_set))
    return (inter / union) if union > 0 else 0.0


def _pick_best_from_group(group, page_qtype, stripped_set, raw_set):
    """当同一题干对应多条题库记录时，按题型和选项重合度消歧"""
    def rank_key(e):
        type_match = 1 if e["qtype"] == page_qtype else 0
        opt_overlap = _calc_option_overlap(stripped_set, raw_set, e)
        return (type_match, opt_overlap)

    return max(group, key=rank_key)


def _calc_similarity(clean_q, stripped_set, raw_set, entry, has_opts):
    """计算题干与选项综合相似度"""
    nq = entry["norm_q"]
    if not clean_q or not nq:
        return 0.0

    # 用 quick_ratio 先过滤掉完全无关的题目以加速
    sm = difflib.SequenceMatcher(None, clean_q, nq)
    if sm.quick_ratio() < 0.25 and not entry["norm_all_opts"]:
        title_sim = sm.quick_ratio()
    else:
        title_sim = sm.ratio()

    # 若发生长短子串包含（如仅尾部缺失少数文字），给予合理参考分
    if len(clean_q) >= 8 and len(nq) >= 8 and (clean_q in nq or nq in clean_q):
        sub_ratio = min(len(clean_q), len(nq)) / max(len(clean_q), len(nq))
        title_sim = max(title_sim, 0.70 * sub_ratio + 0.30)

    if has_opts and entry["norm_all_opts"]:
        opt_sim = _calc_option_overlap(stripped_set, raw_set, entry)
        return 0.70 * title_sim + 0.30 * opt_sim
    return title_sim


def match_question(raw_text, page_opt_texts, page_qtype, bank):
    """
    三级准确度匹配：
    - 'exact': 完整题干精确命中（多条目按题型+选项消歧）
    - 'approx': 未精确命中，同题型下综合相似度 >= 55% 的最相似候选
    - 'none': 连近似阈值都未达到，仍给出相似度最高候选（极低置信度）并强告警
    返回: (entry_or_none, level, confidence_0_to_1)
    """
    clean_q = normalize_text(raw_text)
    stripped_set, raw_set = _page_opts_norm_sets(page_opt_texts)
    has_opts = page_qtype != "判断题" and len(page_opt_texts) > 0

    # Level 1: 完整题干精确匹配
    exact_hits = bank["exact_map"].get(clean_q)
    if exact_hits:
        best = _pick_best_from_group(exact_hits, page_qtype, stripped_set, raw_set)
        # 若唯一命中但题型明显不符（例如页面是多选而题库只有单选），降级检查同题型近似题
        if best["qtype"] == page_qtype:
            return best, "exact", 1.0

    # Level 2 / 3: 优先同题型下寻找最高相似度候选（若同题型为空则查全库）
    pool = bank["by_type"].get(page_qtype) or bank["entries"]
    if not pool:
        return None, "none", 0.0

    # 先快速筛出 Top-25 候选再精确计算，兼顾精度与速度
    scored_quick = []
    for e in pool:
        qr = difflib.SequenceMatcher(None, clean_q, e["norm_q"]).quick_ratio()
        # 如果无歧义前后缀直接命中，确保它必定进入精细打分候选集
        if len(clean_q) >= 15:
            if bank["prefix_unique"].get(clean_q[:15]) is e or bank["suffix_unique"].get(clean_q[-15:]) is e:
                qr = max(qr, 0.85)
        scored_quick.append((qr, e))

    scored_quick.sort(key=lambda x: x[0], reverse=True)
    top_candidates = [e for _, e in scored_quick[:30]]

    # 如果精确匹配里存在一个不同题型的条目，也放进备选比较
    if exact_hits:
        top_candidates.extend(exact_hits)

    best_entry = None
    best_score = -1.0
    for e in top_candidates:
        score = _calc_similarity(clean_q, stripped_set, raw_set, e, has_opts)
        if score > best_score:
            best_score = score
            best_entry = e

    best_score = max(0.0, min(1.0, best_score))
    if best_entry is not None and best_score >= APPROX_MATCH_THRESHOLD:
        return best_entry, "approx", best_score
    return best_entry, "none", best_score


def resolve_target_indices(page_opt_texts, entry):
    """
    解析应在页面上点击的选项下标列表（抗选项乱序 + 字母兜底）：
    返回: (indices_list, method_tag)
    """
    if not page_opt_texts:
        return [], "no_options"
    if entry is None:
        return [0], "fallback_first"

    # 1. 判断题：优先匹配文本“正确/对/√”或“错误/错/×”
    if entry["judge_bool"] is not None:
        keywords = ("正确", "对", "√") if entry["judge_bool"] else ("错误", "错", "×")
        for idx, opt_text in enumerate(page_opt_texts):
            s_norm, r_norm = normalize_option_variants(opt_text)
            if any(k in s_norm or k in r_norm for k in keywords):
                return [idx], "judge_text"
        fallback_idx = 0 if entry["judge_bool"] else 1
        if fallback_idx < len(page_opt_texts):
            return [fallback_idx], "judge_index"
        return [0], "fallback_first"

    # 2. 单选/多选：优先通过答案选项文本匹配（抗选项顺序打乱）
    norm_ans_opts = entry.get("norm_ans_opts") or []
    if norm_ans_opts and len(norm_ans_opts) == len(entry["ans_letters"]):
        page_norm_pairs = [normalize_option_variants(t) for t in page_opt_texts]
        matched_indices = []
        all_unique_matched = True
        for ans_norm in norm_ans_opts:
            hits = [
                idx for idx, (s_norm, r_norm) in enumerate(page_norm_pairs)
                if ans_norm == s_norm or ans_norm == r_norm
            ]
            if len(hits) == 1 and hits[0] not in matched_indices:
                matched_indices.append(hits[0])
            else:
                all_unique_matched = False
                break
        if all_unique_matched and matched_indices:
            return matched_indices, "option_text"

    # 3. 回退：按答案字母 A-H 下标点击
    letter_indices = []
    for ch in entry["ans_letters"]:
        if "A" <= ch <= "H":
            idx = ord(ch) - ord("A")
            if idx < len(page_opt_texts) and idx not in letter_indices:
                letter_indices.append(idx)
    if letter_indices:
        return letter_indices, "letter_index"

    return [0], "fallback_first"


def build_score_summary(question_records, type_scores=None):
    """
    汇总答题准确度与考前预估得分：
    默认按 10单选×3分 + 10多选×5分 + 10判断×2分 = 100分 计算
    """
    scores_cfg = type_scores or DEFAULT_TYPE_SCORES
    total_q = len(question_records)
    exact_count = 0
    approx_count = 0
    none_count = 0
    confirmed_score = 0.0
    estimated_score = 0.0
    potential_max_score = 0.0
    max_score = 0.0
    approx_details = []
    unmatched_details = []

    for rec in question_records:
        pts = scores_cfg.get(rec["qtype"], 3.0)
        max_score += pts
        level = rec["level"]
        conf = rec["confidence"]

        if level == "exact":
            exact_count += 1
            confirmed_score += pts
            estimated_score += pts
            potential_max_score += pts
        elif level == "approx":
            approx_count += 1
            estimated_score += pts * conf
            potential_max_score += pts
            approx_details.append(rec)
        else:
            none_count += 1
            approx_details.append(rec)
            unmatched_details.append(
                f"Q{rec['q_num']} [{rec['qtype']}] {rec['raw_q']}"
                f" (最高相似 {conf * 100:.0f}% -> 拟填: {rec['filled_ans']})"
            )

    confirmed_score = round(confirmed_score, 1)
    estimated_score = round(estimated_score, 1)
    potential_max_score = round(potential_max_score, 1)
    max_score = round(max_score, 1)

    if approx_count == 0 and none_count == 0 and total_q > 0:
        score_text = f"{estimated_score:g} / {max_score:g} 分（全部 {total_q} 题精确命中）"
    else:
        extra = f"，若近似题全对最高 {potential_max_score:g} 分" if approx_count > 0 else ""
        score_text = (
            f"{estimated_score:g} / {max_score:g} 分"
            f"（精确保底 {confirmed_score:g} 分 | 精确 {exact_count} / 近似 {approx_count} / 未命中 {none_count}{extra}）"
        )

    match_rate = (exact_count / total_q * 100) if total_q > 0 else 0.0

    return {
        "total_q": total_q,
        "exact_count": exact_count,
        "approx_count": approx_count,
        "none_count": none_count,
        "match_rate": round(match_rate, 1),
        "confirmed_score": confirmed_score,
        "estimated_score": estimated_score,
        "potential_max_score": potential_max_score,
        "max_score": max_score,
        "score_summary_text": score_text,
        "approx_details": approx_details,
        "unmatched_details": unmatched_details,
    }


async def fill_personal_info(page, name, phone, city, log_fn=print):
    """填写问卷星开头的姓名、手机号、地市"""
    log_fn("📝 填写个人信息...")
    await page.locator('.field:has-text("姓名") input').fill(name)
    await page.locator('.field:has-text("手机") input').fill(phone)

    await page.click('.select2-container')
    await page.wait_for_timeout(500)
    await page.click(f'.select2-results__option:has-text("{city}")')


async def solve_exam_questions(page, bank, log_fn=print):
    """遍历页面全部考题，执行分级匹配、近似兜底、选项点击与考前预估分统计"""
    log_fn("✍️ 开始答题...")
    questions = await page.locator('.field.ui-field-contain').all()
    records = []

    for q_el in questions:
        full_label_el = q_el.locator('.field-label')
        full_label_text = await full_label_el.inner_text() if await full_label_el.count() > 0 else ""
        if "姓名" in full_label_text or "手机" in full_label_text or "地市" in full_label_text:
            continue

        topic_el = q_el.locator('.field-label .topichtml')
        raw_text = await topic_el.inner_text() if await topic_el.count() > 0 else full_label_text

        options = await q_el.locator('div.label').all()
        if not options:
            options = await q_el.locator('.ui-radio, .ui-checkbox').all()

        page_opt_texts = []
        for opt in options:
            page_opt_texts.append((await opt.inner_text()).strip())

        has_checkbox = (await q_el.locator('.ui-checkbox, input[type="checkbox"]').count()) > 0
        page_qtype = infer_page_qtype(full_label_text, has_checkbox, page_opt_texts)

        q_num = len(records) + 1
        entry, level, confidence = match_question(raw_text, page_opt_texts, page_qtype, bank)
        target_indices, method = resolve_target_indices(page_opt_texts, entry)

        for idx in target_indices:
            if 0 <= idx < len(options):
                await options[idx].click()

        filled_letters = [chr(ord("A") + idx) for idx in target_indices]
        filled_ans = entry["ans_display"] if entry else "、".join(filled_letters)
        short_q = strip_zero_width(raw_text)[:18].replace("\n", " ")

        if level == "exact":
            log_fn(f"Q{q_num:02d}[{page_qtype[:2]}]: {short_q}... -> 🟢 精确 [{filled_ans}]")
        elif level == "approx":
            matched_q = entry["raw_q"] if entry else ""
            log_fn(
                f"Q{q_num:02d}[{page_qtype[:2]}]: {short_q}... -> 🟡 近似({confidence*100:.0f}%) "
                f"[{filled_ans}] | 匹配题库: {matched_q[:28]}..."
            )
        else:
            matched_q = entry["raw_q"] if entry else "无候选"
            log_fn(
                f"Q{q_num:02d}[{page_qtype[:2]}]: {short_q}... -> 🔴 未精确命中(最高{confidence*100:.0f}%) "
                f"已填近似 [{filled_ans}] | 请核对！"
            )

        records.append({
            "q_num": q_num,
            "qtype": page_qtype,
            "raw_q": strip_zero_width(raw_text).replace("\n", " "),
            "matched_q": entry["raw_q"] if entry else "",
            "level": level,
            "confidence": round(confidence, 3),
            "filled_ans": filled_ans,
            "filled_indices": target_indices,
            "method": method,
        })

    summary = build_score_summary(records)
    log_fn(
        f"📊 统计报告: 总题数 {summary['total_q']} | "
        f"精确命中 {summary['exact_count']} | "
        f"近似匹配 {summary['approx_count']} | "
        f"未命中(低置信兜底) {summary['none_count']}"
    )
    log_fn(f"🎯 考前预估分数: {summary['score_summary_text']}")

    if summary["approx_details"]:
        log_fn("⚠️ 以下题目非 100% 精确匹配，交卷前请结合预览图重点核对：")
        for rec in summary["approx_details"]:
            tag = "🟡 近似" if rec["level"] == "approx" else "🔴 未命中"
            log_fn(
                f"   - Q{rec['q_num']} ({tag} {rec['confidence']*100:.0f}%): {rec['raw_q']}\n"
                f"     匹配题库: {rec['matched_q']} | 拟选答案: [{rec['filled_ans']}]"
            )

    return summary


async def submit_exam_and_extract_score(page, log_fn=print):
    """提交答卷并尝试抓取成绩文本（若后台隐藏成绩则优雅提示以截图为准）"""
    await page.click('#ctlNext')
    try:
        await page.wait_for_selector('#divResult, #totalScore', timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)

    score_text = "网页未显示（请以成绩截图为准）"
    for selector in ('#divResult .score', '#totalScore'):
        score_el = page.locator(selector)
        if await score_el.count() > 0:
            txt = strip_zero_width(await score_el.inner_text())
            if txt:
                score_text = txt
                break
    return score_text
