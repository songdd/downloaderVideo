import os, json, re, sys, requests
from urllib.parse import unquote
from tqdm import tqdm

sys.stdout.reconfigure(encoding='utf-8')

def sanitize_filename(title):
    return 'tempdown'

def download_video(url, title):
    headers = {'Referer': 'https://www.douyin.com/', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    r = requests.get(url, headers=headers, stream=True)
    cl = r.headers.get('Content-Length', '?')
    print('[DOWNLOAD] HTTP %s, Content-Length: %s' % (r.status_code, cl))
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    video_dir = os.path.join(current_dir, 'output')
    os.makedirs(video_dir, exist_ok=True)
    if r.status_code == 200:
        total = int(r.headers.get('Content-Length', 0))
        import time; video_path = os.path.join(video_dir, f'douyin_{time.strftime("%Y%m%d_%H%M%S")}.mp4')
        with open(video_path, 'wb') as f:
            with tqdm(total=total, unit='B', unit_scale=True, desc='Download') as bar:
                for chunk in r.iter_content(1024):
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))
        print('[DOWNLOAD] Saved: %s (%d bytes)' % (video_path, os.path.getsize(video_path)))
    else:
        print('[DOWNLOAD] Failed')

def get_video_url(url):
    m = re.search(r'modal_id=(\d+)', url or '')
    if not m:
        print('[ERROR] Cannot extract modal_id')
        return None
    modal_id = m.group(1)
    cookie_str = ""
    try:
        from cookies import load_cookie
        cookie_str = load_cookie("douyin") or ""
    except Exception:
        pass
    if not cookie_str:
        print("[DOUYIN] No cookie. Try: python login.py douyin")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
               'Referer': 'https://www.douyin.com/', 'Cookie': cookie_str}
    apis = [
        ('iesdouyin', 'https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=%s' % modal_id),
        ('aweme', 'https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=%s' % modal_id),
    ]
    for name, api_url in apis:
        print('[API] Trying %s' % name)
        try:
            r = requests.get(api_url, headers=headers, timeout=15)
            print('[API] Status: %s' % r.status_code)
            if r.status_code != 200:
                continue
            data = r.json()
            items = data.get('item_list') or [data.get('aweme_detail')]
            for item in items:
                if not item:
                    continue
                video = item.get('video', {})
                for addr_key in ('play_addr', 'play_addr_h264', 'download_addr'):
                    addr = video.get(addr_key, {})
                    urls = addr.get('url_list', [])
                    if isinstance(urls, str):
                        urls = [urls]
                    for u in urls:
                        u = u.replace('playwm', 'play')
                        if u.startswith('http'):
                            print('[API] Got URL from %s: %s...' % (name, u[:80]))
                            return u
            print('[API] %s: no playable URL' % name)
        except Exception as e:
            print('[API] %s failed: %s' % (name, e))
    print('[FATAL] All APIs failed')
    return None

def get_modalid_from_share_link(share_link):
    m = re.search(r'https://v\.douyin\.com/[\w\-]+/?', share_link)
    if not m:
        print('[STEP1] Invalid share link format')
        return None, None
    url = m.group()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        r = requests.get(url, headers=headers, allow_redirects=True)
        mm = re.search(r'https://www\.douyin\.com/video/(\d+)', r.url)
        if mm:
            modal_id = mm.group(1)
            print('[STEP1] modal_id=%s' % modal_id)
            return modal_id, r.url
        print('[STEP1] Redirect failed: %s' % r.url)
        return None, None
    except Exception as e:
        print('[STEP1] Request failed: %s' % e)
        return None, None

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python script.py <douyin_share_link>')
        sys.exit(1)
    share_link = sys.argv[1]
    modal_id, video_url = get_modalid_from_share_link(share_link)
    if not modal_id:
        print('Invalid share link')
    else:
        url = 'https://www.douyin.com/user/self?showTab=post&modal_id=%s' % modal_id
        play_url = get_video_url(url)
        if play_url:
            download_video(play_url, play_url.split('/')[-1])
        else:
            print('Failed: could not extract play URL')
    sys.exit(0)
