#!/usr/bin/env python3
"""周周考自动答题 CLI 脚本 - 供 OpenClaw Skill 调用"""

import argparse
import asyncio
import os
import sys
import re
import time
from datetime import datetime

# 国内镜像
PLAYWRIGHT_CDN_MIRROR = "https://npmmirror.com/mirrors/playwright"
EXAM_URL = 'https://kaoshi.wjx.top/vm/rimKLVu.aspx'

# 模拟环境配置
ENV_CONFIGS = {
    "wecom_iphone": {
        "name": "iPhone 企业微信",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 wxwork/4.1.10 MicroMessenger/7.0.1 Language/zh_CN",
        "viewport": {"width": 390, "height": 844},
    },
    "wecom_android": {
        "name": "Android 企业微信",
        "user_agent": "Mozilla/5.0 (Linux; Android 13; SM-G998B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 wxwork/4.1.10 MicroMessenger/7.0.1.2080 NetType/WIFI Language/zh_CN ABI/arm64",
        "viewport": {"width": 412, "height": 915},
    },
    "wechat_iphone": {
        "name": "iPhone 微信",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.42(0x18002a24) NetType/WIFI Language/zh_CN",
        "viewport": {"width": 390, "height": 844},
    },
    "wechat_android": {
        "name": "Android 微信",
        "user_agent": "Mozilla/5.0 (Linux; Android 13; SM-G998B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.41.2441(0x28002951) Process/appbrand0 WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
        "viewport": {"width": 412, "height": 915},
    },
    "pc": {
        "name": "电脑浏览器",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
    },
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def normalize_text(text):
    if not text:
        return ""
    text = str(text).replace("【多选题】", "").replace("【单选题】", "")
    return re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text).lower()


def ensure_dependencies():
    """检查并安装依赖"""
    # 检查 openpyxl
    try:
        import openpyxl
        log("✅ openpyxl 已安装")
    except ImportError:
        log("📥 正在安装 openpyxl...")
        os.system(f"{sys.executable} -m pip install openpyxl -q")
        import openpyxl

    # 检查 playwright
    try:
        import playwright
        log("✅ playwright 已安装")
    except ImportError:
        log("📥 正在安装 playwright...")
        os.system(f"{sys.executable} -m pip install playwright -q")

    # 检查 chromium
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    driver_executable = compute_driver_executable()
    env = get_driver_env()
    env["PLAYWRIGHT_DOWNLOAD_HOST"] = PLAYWRIGHT_CDN_MIRROR

    # 尝试检测 chromium 是否已安装
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    chromium_found = False
    if browsers_path and os.path.isdir(browsers_path):
        for item in os.listdir(browsers_path):
            if "chromium" in item and os.path.isdir(os.path.join(browsers_path, item)):
                chromium_found = True
                break

    if not chromium_found:
        log("📥 正在使用国内镜像下载 Chromium（约 150MB）...")
        log(f"📡 下载源: {PLAYWRIGHT_CDN_MIRROR}")
        import subprocess
        result = subprocess.run(
            [str(driver_executable), "install", "chromium"],
            env=env, capture_output=True, text=True
        )
        if result.returncode == 0:
            log("✅ Chromium 安装成功")
        else:
            log(f"❌ Chromium 安装失败: {result.stderr}")
            log("尝试安装系统依赖: playwright install-deps chromium")
            subprocess.run([str(driver_executable), "install-deps", "chromium"], env=env)
            # 重试
            subprocess.run([str(driver_executable), "install", "chromium"], env=env)
    else:
        log("✅ Chromium 已就绪")


def load_question_bank(excel_path):
    """加载题库"""
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    sheet = wb.active
    question_db = {}
    rows = list(sheet.iter_rows(values_only=True))

    count = 0
    for row in rows[1:]:
        if len(row) > 7 and row[1] and row[7]:
            q_raw = str(row[1])
            a_raw = str(row[7]).strip().upper()
            match = re.search(r'^([A-H]+)', a_raw)
            clean_ans = match.group(1) if match else a_raw
            norm_q = normalize_text(q_raw)

            if len(norm_q) > 3:
                question_db[norm_q] = clean_ans
                question_db[norm_q[:15]] = clean_ans
                question_db[norm_q[-15:]] = clean_ans
                if "pci" in norm_q and "300" in norm_q:
                    question_db["pci300"] = clean_ans
                count += 1

    question_db["切换准备失败的可能原因有"] = "ABCD"
    question_db["以下事件中可用于频间切换的有"] = "ABC"

    log(f"📚 题库加载完毕，共 {count} 条索引")
    return question_db


async def run_exam(name, phone, city, env_key, wait_seconds, excel_path):
    """执行考试主流程"""
    from playwright.async_api import async_playwright

    question_db = load_question_bank(excel_path)
    env_config = ENV_CONFIGS.get(env_key, ENV_CONFIGS["wecom_android"])

    log(f"🚀 开始考试: {name} | {city} | 模拟: {env_config['name']}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=env_config["viewport"],
            user_agent=env_config["user_agent"]
        )
        page = await context.new_page()

        log(f"🌐 打开考试页面: {EXAM_URL}")
        await page.goto(EXAM_URL, timeout=60000)
        await page.wait_for_load_state('networkidle')

        # 填写信息
        log("📝 填写个人信息...")
        await page.locator('.field:has-text("姓名") input').fill(name)
        await page.locator('.field:has-text("手机") input').fill(phone)

        # 地市
        await page.click('.select2-container')
        await page.wait_for_timeout(500)
        await page.click(f'.select2-results__option:has-text("{city}")')

        # 答题
        log("✍️ 开始答题...")
        questions = await page.locator('.field.ui-field-contain').all()

        total_q = 0
        matched_q = 0
        unmatched_details = []

        for i, q_el in enumerate(questions):
            label_el = q_el.locator('.field-label .topichtml')
            if await label_el.count() == 0:
                label_el = q_el.locator('.field-label')

            raw_text = await label_el.inner_text()
            if "姓名" in raw_text or "手机" in raw_text or "地市" in raw_text:
                continue

            total_q += 1
            clean_q = normalize_text(raw_text)

            ans = question_db.get(clean_q)
            if not ans: ans = question_db.get(clean_q[:15])
            if not ans: ans = question_db.get(clean_q[-15:])
            if not ans and "pci" in clean_q and "300" in clean_q: ans = "902"
            if not ans and "切换准备失败" in raw_text: ans = "ABCD"
            if not ans and "以下事件中" in raw_text and "频间切换" in raw_text: ans = "ABC"

            short_q = raw_text[:15].replace('\n', ' ')

            if ans:
                matched_q += 1
                log(f"Q{total_q}: {short_q}... -> 🟢 [{ans}]")
            else:
                unmatched_details.append(f"Q{total_q}: {raw_text}")
                log(f"Q{total_q}: {short_q}... -> 🔴 未找到答案")

            options = await q_el.locator('div.label').all()
            if not options:
                options = await q_el.locator('.ui-radio, .ui-checkbox').all()

            if ans:
                clicked = False
                if ans in ["正确", "错误", "对", "错", "902"]:
                    target_text = ans.replace("对", "正确").replace("错", "错误")
                    for opt in options:
                        if target_text in await opt.inner_text():
                            await opt.click()
                            clicked = True
                            break
                if not clicked:
                    for char in ans:
                        if 'A' <= char <= 'H':
                            idx = ord(char) - ord('A')
                            if idx < len(options):
                                await options[idx].click()
                                clicked = True
                if not clicked and options:
                    await options[0].click()
            elif options:
                await options[0].click()

        # 报告
        log(f"📊 答题完成: 总题数 {total_q} | 匹配 {matched_q} | 未匹配 {len(unmatched_details)}")

        # 等待
        log(f"⏳ 开始挂机等待 {wait_seconds} 秒（防作弊检测）...")
        for remaining in range(wait_seconds, 0, -30):
            mins, secs = divmod(remaining, 60)
            log(f"   剩余等待: {mins}分{secs}秒...")
            await asyncio.sleep(min(30, remaining))
        log("✅ 等待完毕，开始提交...")

        # 提交
        await page.click('#ctlNext')
        try:
            await page.wait_for_selector('#divResult, #totalScore', timeout=10000)
        except:
            pass
        await page.wait_for_timeout(2000)

        score_text = "未知"
        score_el = page.locator('#divResult .score')
        if await score_el.count() > 0:
            score_text = await score_el.inner_text()
        else:
            score_el = page.locator('#totalScore')
            if await score_el.count() > 0:
                score_text = await score_el.inner_text()

        log(f"🎉 提交完成！最终成绩: {score_text}")
        log(f"📊 统计: 总题 {total_q} | 匹配 {matched_q} | 未匹配 {len(unmatched_details)}")

        await browser.close()
        return score_text


def main():
    parser = argparse.ArgumentParser(description="周周考自动答题 CLI")
    parser.add_argument("--name", required=True, help="考试姓名")
    parser.add_argument("--phone", required=True, help="手机号")
    parser.add_argument("--city", default="南宁", help="地市（默认南宁）")
    parser.add_argument("--env", default="wecom_android",
                        choices=list(ENV_CONFIGS.keys()),
                        help="模拟环境（默认wecom_android）")
    parser.add_argument("--wait", type=int, default=600,
                        help="答完等待秒数（默认600）")
    parser.add_argument("--excel", default=None,
                        help="题库路径（默认使用同目录下 question_bank.xlsx）")
    args = parser.parse_args()

    # 题库路径
    if args.excel:
        excel_path = args.excel
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        excel_path = os.path.join(script_dir, "question_bank.xlsx")

    if not os.path.exists(excel_path):
        log(f"❌ 题库文件不存在: {excel_path}")
        sys.exit(1)

    # 确保依赖
    ensure_dependencies()

    # 运行考试
    try:
        score = asyncio.run(run_exam(
            name=args.name,
            phone=args.phone,
            city=args.city,
            env_key=args.env,
            wait_seconds=args.wait,
            excel_path=excel_path
        ))
        print(f"\n{'='*40}")
        print(f"  考试完成！成绩: {score}")
        print(f"{'='*40}")
    except Exception as e:
        log(f"❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
