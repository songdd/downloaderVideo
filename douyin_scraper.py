import json
import os
import re
from urllib.parse import unquote
from tqdm import tqdm
import requests
import sys
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [DOWNLOAD] %(message)s")
_log = logging.getLogger("dl")

sys.stdout.reconfigure(encoding="utf-8")  # 设置标准输出编码为utf-8


def sanitize_filename(title):
    # 将非法字符替换为 '_'
    sanitized_title = re.sub(r'[<>:"/\\|?*]', "_", title)
    # 去除两端的空格
    sanitized_title = sanitized_title.strip()
    # 限制标题长度，例如保留前20个字符
    sanitized_title = sanitized_title[:10]
    # return sanitized_title or "temp"
    return "tempdown"


def download_video(url, title):
    headers = {
        "Referer": "https://www.douyin.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    response = requests.get(url, headers=headers, stream=True)
    print(f"HTTP Status Code: {response.status_code}")

    # 使用相对路径
    # 获取当前脚本所在目录
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    video_dir = os.path.join(current_dir, "video")

    # 确保视频目录存在
    if not os.path.exists(video_dir):
        os.makedirs(video_dir)

    if response.status_code == 200:
        total_size = int(response.headers.get("Content-Length", 0))
        video_path = os.path.join(video_dir, f"{sanitize_filename(title)}.mp4")

        with open(video_path, "wb") as f:
            with tqdm(
                total=total_size, unit="B", unit_scale=True, desc="Downloading"
            ) as pbar:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

        print(video_path, file=sys.stdout)
    else:
        print("Failed to retrieve the video.")


def get_video_url(url):
    import json as _json, os as _os
    _acct = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "social-auto-upload-main", "cookies", "douyin_uploader", "account.json")
    with open(_acct, "r", encoding="utf-8") as _f:
        _cookies = _json.load(_f).get("cookies", [])
    _seen = set()
    _pairs = []
    for _c in _cookies:
        if _c["name"] not in _seen:
            _seen.add(_c["name"])
            _pairs.append("{}={}".format(_c["name"], _c["value"]))
    cookie_str = "; ".join(_pairs)

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "cookie": cookie_str,
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }
    response = requests.get(url, headers=headers)
    content = re.findall(
        '</div><script id="RENDER_DATA" type="application/json">(.*?)</script>',
        response.text,
    )
    content = unquote(content[0])
    content = json.loads(content)
    part_url = content["app"]["videoDetail"]["video"]["bitRateList"][0]["playAddr"][0][
        "src"
    ]
    title = content["app"]["videoDetail"]["desc"]
    try:
        print(f"{title}")
    except UnicodeEncodeError:
        # 如果遇到编码错误，尝试移除emoji
        title = re.sub(
            r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]",
            "",
            title,
        )
        print(f"处理后的标题: {title}")
    print("https://" + part_url)
    if not part_url.startswith("https://"):
        return "https://" + part_url
    return part_url


# def get_modalid_from_share_link(share_link):
    _log.info("[STEP1] get_modalid_from_share_link: %s", share_link)
#     pattern = r"https://v\.douyin\.com/[a-zA-Z0-9]+/?"
#     try:
#         url = re.findall(pattern, share_link)[0]
#     except Exception as e:
#         print("No link found")
#         return None
#
#     headers = {
#         "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
#         "cookie": "douyin.com; device_web_cpu_core=10; device_web_memory_size=8; __ac_nonce=06760391f00b9b51264ae; __ac_signature=_02B4Z6wo00f019a5ceAAAIDAhEZR-X3jjWfWmXVAAJLXd4; ttwid=1%7C7MTKBSMsP4eOv9h5NAh8p0E-NYIud09ftNmB0mjLpWc%7C1734359327%7C8794abeabbd47447e1f56e5abc726be089f2a0344d6343b5f75f23e7b0f0028f; UIFID_TEMP=0de8750d2b188f4235dbfd208e44abbb976428f0720eb983255afefa45d39c0c6532e1d4768dd8587bf919f866ff1396912bcb2af71efee56a14a2a9f37b74010d0a0413795262f6d4afe02a032ac7ab; s_v_web_id=verify_m4r4ribr_c7krmY1z_WoeI_43po_ATpO_I4o8U1bex2D7; hevc_supported=true; home_can_add_dy_2_desktop=%220%22; dy_swidth=2560; dy_sheight=1440; stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A2560%2C%5C%22screen_height%5C%22%3A1440%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A10%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A50%7D%22; strategyABtestKey=%221734359328.577%22; csrf_session_id=2f53aed9aa6974e83aa9a1014180c3a4; fpk1=U2FsdGVkX1/IpBh0qdmlKAVhGyYHgur4/VtL9AReZoeSxadXn4juKvsakahRGqjxOPytHWspYoBogyhS/V6QSw==; fpk2=0845b309c7b9b957afd9ecf775a4c21f; passport_csrf_token=d80e0c5b2fa2328219856be5ba7e671e; passport_csrf_token_default=d80e0c5b2fa2328219856be5ba7e671e; odin_tt=3c891091d2eb0f4718c1d5645bc4a0017032d4d5aa989decb729e9da2ad570918cbe5e9133dc6b145fa8c758de98efe32ff1f81aa0d611e838cc73ab08ef7d3f6adf66ab4d10e8372ddd628f94f16b8e; volume_info=%7B%22isUserMute%22%3Afalse%2C%22isMute%22%3Afalse%2C%22volume%22%3A0.5%7D; bd_ticket_guard_client_web_domain=2; FORCE_LOGIN=%7B%22videoConsumedRemainSeconds%22%3A180%7D; UIFID=0de8750d2b188f4235dbfd208e44abbb976428f0720eb983255afefa45d39c0c6532e1d4768dd8587bf919f866ff139655a3c2b735923234f371c699560c657923fd3d6c5b63ab7bb9b83423b6cb4787e2ce66a7fbc4ecb24c8570f520fe6de068bbb95115023c0c6c1b6ee31b49fb7e3996fb8349f43a3fd8b7a61cd9e18e8fe65eb6a7c13de4c0960d84e344b644725db3eb2fa6b7caf821de1b50527979f2; is_dash_user=1; biz_trace_id=b57a241f; bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCTEo2R0lDalVoWW1XcHpGOFdrN0Vrc0dXcCtaUzNKY1g4NGNGY2k0TTl1TEowNjdUb21mbFU5aDdvWVBGamhNRWNRQWtKdnN1MnM3RmpTWnlJQXpHMjA9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D; download_guide=%221%2F20241216%2F0%22; sdk_source_info=7e276470716a68645a606960273f276364697660272927676c715a6d6069756077273f276364697660272927666d776a68605a607d71606b766c6a6b5a7666776c7571273f275e58272927666a6b766a69605a696c6061273f27636469766027292762696a6764695a7364776c6467696076273f275e5827292771273f273d33323131333c3036313632342778; bit_env=RiOY4jzzpxZoVCl6zdVSVhVRjdwHRTxqcqWdqMBZLPGjMdB4Tax1kAELHNTVAAh72KuhumewE4Lq6f0-VJ2UpJrkrhSxoPw9LUb3zQrq1OSwbeSPHkRlRgRQvO89sItdGUyq1oFr0XyRCnMYG87KSeWyc4x0czGR0o50hTDoDLG5rJVoRcdQOLvjiAegsqyytKF59sPX_QM9qffK2SqYsg0hCggURc_AI6kguDDE5DvG0bnyz1utw4z1eEnIoLrkGDqzqBZj4dOAr0BVU6ofbsS-pOQ2u2PM1dLP9FlBVBlVaqYVgHJeSLsR5k76BRTddUjTb4zEilVIEwAMJWGN4I1BxVt6fC9B5tBQpuT0lj3n3eKXCKXZsd8FrEs5_pbfDsxV-e_WMiXI2ff4qxiTC0U73sfo9OpicKICtZjdq8qsHxJuu6wVR36zvXeL2Wch5C6MzprNvkivv0l8nbh2mSgy1nabZr3dmU6NcR-Bg3Q3xTWUlR9aAUmpopC-cNuXjgLpT-Lw1AYGilSUnCvosth1Gfypq-b0MpgmdSDgTrQ%3D; gulu_source_res=eyJwX2luIjoiMDhjOGQ3ZTJiODQyNjZkZWI5Y2VkMGJiODNlNmY1ZWY0ZjMyNTE2ZmYyZjAzNDMzZjI0OWU1Y2Q1NTczNTk5NyJ9; passport_auth_mix_state=hp9bc3dgb1tm5wd8p82zawus27g0e3ue; IsDouyinActive=false",
#         "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
#     }
#
#     response = requests.get(url, headers=headers, allow_redirects=True)
#     if response.url:
#         pattern = r"https://www\.douyin\.com/video/(\d+)"
#         match = re.search(pattern, response.url)
#         if match:
#             modal_id = match.group(1)
#             print(f"Extracted modal_id: {modal_id}")
#             return modal_id
#         else:
#             print("No modal_id found")
#             return None
#     else:
#         print("No valid response URL found")
#         return None

def get_modalid_from_share_link(share_link):
    # 更新正则表达式模式：允许包含 - _ 等特殊字符
    pattern = r"https://v\.douyin\.com/[\w\-]+/?"
    try:
        # 使用 search 替代 findall 更安全
        match = re.search(pattern, share_link)
        if not match:
            print("无效的分享链接格式")
            return None
        url = match.group()
    except Exception as e:
        print(f"链接解析异常: {str(e)}")
        return None

    headers = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    try:
        response = requests.get(url, headers=headers, allow_redirects=True)
        response.raise_for_status()  # 检查HTTP状态码

        if response.url:
            # 增强正则表达式匹配容错性
            modal_patterns = [
                r"https://www\.douyin\.com/video/(\d+)",  # 标准格式
            ]

            for pattern in modal_patterns:
                match = re.search(pattern, response.url)
                if match:
                    return match.group(1)

            print(f"未识别的跳转URL格式: {response.url}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"请求失败: {str(e)}")
        return None
    except Exception as e:
        print(f"解析异常: {str(e)}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <douyin_share_link>")
        sys.exit(1)

    share_link = sys.argv[1]
    modal_id = get_modalid_from_share_link(share_link)
    if not modal_id:
        print("Invalid share link")
    else:
        url = f"https://www.douyin.com/user/MS4wLjABAAAAf7i8sK5OxbSctQ45rmH2dDIFYNPmlqHRtnGucIQSRSGuQUiiYEoxdc2QpBIu5XmS?from_tab_name=main&modal_id={modal_id}"
        play_url = get_video_url(url)
        download_video(play_url, play_url.split("/")[-1])

    sys.exit(0)