# -*- coding: utf-8 -*-
"""Login helper - interactive Chrome login for all platforms."""

import os, sys, json, sqlite3, shutil, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cookies import save_cookie, status, PLATFORMS

CHROME_USER_DATA = os.path.join(os.environ.get("LOCALAPPDATA",""), "Google","Chrome","User Data")
ROOT = os.path.dirname(os.path.abspath(__file__))

PLATFORM_DOMAINS = {"douyin":"douyin.com","xhs":"xiaohongshu.com","kuaishou":"kuaishou.com","bilibili":"bilibili.com","youku":"youku.com","tencent":"v.qq.com"}

PLATFORM_URLS = {"douyin":"https://creator.douyin.com","xhs":"https://www.xiaohongshu.com/explore",
                 "kuaishou":"https://www.kuaishou.com","bilibili":"https://www.bilibili.com","youku":"https://www.youku.com","tencent":"https://v.qq.com"}

LOGIN_KEYS = {"bilibili":("SESSDATA",20),"douyin":("sessionid",10),"xhs":("web_session",10),"kuaishou":("kuaishou.server.web_st",10),"youku":("P_pck_rm",10),"tencent":("v_vuserid",5)}

def extract_chrome_cookies(domain):
    cookie_db = os.path.join(CHROME_USER_DATA,"Default","Network","Cookies")
    if not os.path.exists(cookie_db):
        cookie_db = os.path.join(CHROME_USER_DATA,"Default","Cookies")
    if not os.path.exists(cookie_db): return None
    tmp = cookie_db + ".tmp"; shutil.copy2(cookie_db, tmp)
    try:
        conn = sqlite3.connect(tmp)
        rows = conn.execute("SELECT name,value FROM cookies WHERE host_key LIKE ?",(f"%{domain}%",)).fetchall()
        conn.close()
        if rows:
            pairs = [f"{n}={v}" for n,v in rows if v and len(v) > 2]
            if not pairs:
                print("[LOGIN] Chrome DB has cookies but all values are encrypted/empty")
                return None
            return "; ".join(pairs)
    except Exception as e:
        print(f"[LOGIN] DB error: {e}"); return None
    finally:
        try: os.remove(tmp)
        except: pass

def extract_playwright(platform, domain):
    try: from playwright.sync_api import sync_playwright
    except ImportError:
        print("[LOGIN] Playwright not installed. pip install playwright"); return None

    tmp_profile = os.path.join(ROOT,"tmp","chrome_login"); os.makedirs(tmp_profile, exist_ok=True)
    site_url = PLATFORM_URLS.get(platform, f"https://{domain}")
    key_name, key_min_len = LOGIN_KEYS.get(platform, ("session",10))

    print(f"[LOGIN] Opening Chrome -> {site_url}")
    print("[LOGIN] Please log in (scan QR or password). Auto-closes after login detected.")
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=tmp_profile, headless=False, channel="chrome",
                args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
                "--disable-gpu",
            ],
            ignore_default_args=["--enable-automation"],
        )
            page = ctx.new_page()
            page.goto(site_url, timeout=30000, wait_until="domcontentloaded")
            # Hide automation traces
            page.evaluate("""() => {
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
            }""")
            for _ in range(300):
                time.sleep(1)
                for c in ctx.cookies():
                    if c.get("name") == key_name and len(c.get("value","")) >= key_min_len:
                        pairs = [f"{x['name']}={x['value']}" for x in ctx.cookies() if domain in x.get("domain","")]
                        cookie_str = "; ".join(pairs)
                        ctx.close()
                        # Keep profile for reuse (avoids Youku anti-frequent-login detection)
                        print(f"\n[LOGIN] Detected! {len(pairs)} cookies saved.")
                        print(f"[LOGIN] Profile kept at: {tmp_profile}")
                        return cookie_str
            ctx.close()
    except Exception as e:
        if "Target page" not in str(e): print(f"[LOGIN] Error: {e}")
    return None

def login_platform(platform, force_interactive=False):
    domain = PLATFORM_DOMAINS.get(platform)
    if not domain: print(f"[LOGIN] Unknown: {platform}"); return

    if not force_interactive:
        print(f"[LOGIN] Trying Chrome DB...")
        cookie = extract_chrome_cookies(domain)
        if cookie:
            save_cookie(platform, cookie)
            print(f"[LOGIN] OK ({len(cookie)} chars)"); return
        print(f"[LOGIN] Chrome DB failed (cookies encrypted by Chrome).")

    print(f"[LOGIN] Opening interactive Chrome login...")
    cookie = extract_playwright(platform, domain)
    if cookie:
        save_cookie(platform, cookie)
        print(f"[LOGIN] OK ({len(cookie)} chars)"); return

    print(f"[LOGIN] Failed. Use: python login.py {platform} --cookie 'key=value'")

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("status","-s","--status"):
        status(); return
    if sys.argv[1] == "--all":
        for p in PLATFORM_DOMAINS: login_platform(p)
        return
    platform = sys.argv[1]
    if platform not in PLATFORM_DOMAINS:
        print(f"Unknown: {platform}. Available: {list(PLATFORM_DOMAINS.keys())}"); return
    force_interactive = "--new" in sys.argv or "-n" in sys.argv
    if "--cookie" in sys.argv:
        idx = sys.argv.index("--cookie")
        if idx + 1 < len(sys.argv): save_cookie(platform, sys.argv[idx+1])
        else: c = input("Cookie: ").strip(); save_cookie(platform, c) if c else None
    else:
        login_platform(platform, force_interactive=force_interactive)

if __name__ == "__main__": main()