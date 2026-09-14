"""下载资源清单中每个链接的首个视频，不展开课程全集。可重复运行续传。"""
from pathlib import Path
import re
import subprocess
import json
from datetime import datetime

ROOT = Path(__file__).resolve().parent
DEST = ROOT / '视频资源'
DEST.mkdir(exist_ok=True)
urls = list(dict.fromkeys(re.findall(r'https://www\.bilibili\.com/video/BV\w+/', (ROOT / 'AI漫剧视频教学资源.md').read_text())))
results = []
for i, url in enumerate(urls, 1):
    print(f'[{i}/{len(urls)}] {url}', flush=True)
    bv = url.rstrip('/').split('/')[-1]
    command = [str(ROOT / '.download-tools/bin/yt-dlp'), '--no-playlist', '--playlist-items', '1',
               '--socket-timeout', '20', '--retries', '2', '--fragment-retries', '2',
               '--no-progress', '--continue', '--download-archive', str(DEST / '已下载.txt'),
               '-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
               '--merge-output-format', 'mp4', '--write-info-json',
               '-o', str(DEST / '%(id)s.%(ext)s'), url]
    log = DEST / f'{bv}.log'
    with log.open('w') as f:
        try:
            p = subprocess.run(command, stdout=f, stderr=subprocess.STDOUT, timeout=900)
            status = '成功' if p.returncode == 0 else '失败（见日志）'
        except subprocess.TimeoutExpired:
            status = '超时（可重跑续传）'
    results.append({'url': url, 'status': status, 'log': log.name})
    (DEST / '下载结果.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(status, flush=True)

lines = ['# 视频下载结果', '', f'更新时间：{datetime.now().isoformat(timespec="seconds")}', '',
         '仅下载各链接的首个视频（多集课程不展开），最高选择720p；实际清晰度受匿名访问权限限制。', '',
         '| 视频链接 | 结果 | 日志 |', '|---|---|---|']
lines += [f'| {r["url"]} | {r["status"]} | {r["log"]} |' for r in results]
(DEST / '下载结果.md').write_text('\n'.join(lines) + '\n')
print('下载任务结束', flush=True)
