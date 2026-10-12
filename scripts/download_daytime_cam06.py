#!/usr/bin/env python3
"""
Downloads and decrypts daytime segments from CCTV CDN for cam06 (Madhuram Bypass Road).
Assembles them into cam06_daytime.mp4.
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import requests
from Crypto.Cipher import AES

COOKIE_FILE = "/tmp/sentinel_cookie.txt"
KEY_HEX = "a59c70f080134543ffade38733d40d4a"
KEY_BYTES = bytes.fromhex(KEY_HEX)
IV_BYTES = bytes(16)  # 16 zeros
BASE_URL = "https://cctv.corp8.cloud/cam06"
OUT_DIR = "/Users/divijpatel/Desktop/hackathon/sentinal-fresh/cam06_daytime_segs"
OUT_MP4 = "/Users/divijpatel/Desktop/hackathon/sentinal-fresh/cam06_daytime.mp4"

os.makedirs(OUT_DIR, exist_ok=True)

# Parse cookie
cookie_val = ""
with open(COOKIE_FILE, "r") as f:
    for line in f:
        if "sentinel" in line and not line.startswith("# "):
            parts = line.strip().split()
            for i, p in enumerate(parts):
                if p == "sentinel" and i + 1 < len(parts):
                    cookie_val = parts[i + 1]
                    break

if not cookie_val:
    print("Error: sentinel cookie not found in", COOKIE_FILE)
    sys.exit(1)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Cookie": f"sentinel={cookie_val}"
})

def download_and_decrypt(seg_num):
    fname = f"seg{seg_num:05d}.ts"
    dec_path = os.path.join(OUT_DIR, f"dec_{seg_num:05d}.ts")
    if os.path.exists(dec_path) and os.path.getsize(dec_path) > 10000:
        return seg_num, True
    
    url = f"{BASE_URL}/{fname}"
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 10000:
                cipher = AES.new(KEY_BYTES, AES.MODE_CBC, IV_BYTES)
                decrypted = cipher.decrypt(resp.content)
                # Unpad PKCS7 if applicable or write raw (TS packets are 188 bytes)
                with open(dec_path, "wb") as f_out:
                    f_out.write(decrypted)
                return seg_num, True
            else:
                print(f"[{fname}] status {resp.status_code}, len {len(resp.content)}")
        except Exception as e:
            print(f"[{fname}] attempt {attempt} error: {e}")
            time.sleep(1)
    return seg_num, False

def main():
    # 10490 to 10515 = 26 segments (2.6 minutes = 156 seconds) of daylight traffic around 11:15 AM
    seg_start = 10490
    seg_end = 10515
    segments = list(range(seg_start, seg_end + 1))
    print(f"Downloading {len(segments)} daytime segments ({seg_start}..{seg_end}) with 6 parallel threads...")
    
    success = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {executor.submit(download_and_decrypt, s): s for s in segments}
        for future in as_completed(future_map):
            s_num, ok = future.result()
            if ok:
                success.append(s_num)
                print(f"✓ seg{s_num:05d}.ts decrypted ({len(success)}/{len(segments)})")
            else:
                print(f"✗ seg{s_num:05d}.ts failed")

    success.sort()
    if len(success) < 5:
        print("Too few segments downloaded successfully.")
        sys.exit(1)

    print(f"Assembling {len(success)} segments into {OUT_MP4}...")
    concat_list = os.path.join(OUT_DIR, "concat.txt")
    with open(concat_list, "w") as f:
        for s_num in success:
            dec_path = os.path.join(OUT_DIR, f"dec_{s_num:05d}.ts")
            f.write(f"file '{dec_path}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list,
        "-c", "copy",
        OUT_MP4
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"✓ Successfully generated {OUT_MP4} ({os.path.getsize(OUT_MP4)} bytes)")
    else:
        print(f"FFmpeg concat failed: {res.stderr}")
        sys.exit(1)

if __name__ == "__main__":
    main()
