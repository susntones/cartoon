#!/usr/bin/env python3
"""Local, no-network motion-comic assembly. Requires Pillow, ffmpeg and ffprobe.
Input: production.json, assets/images/NN.png, assets/audio/NN.wav.
Does NOT generate illustrations, synthesize speech, or publish anything.
"""
import argparse
import json
import math
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def run(args):
    return subprocess.run([str(x) for x in args], check=True, capture_output=True, text=True)


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path]).stdout)


def stamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}'


def wrap(text, draw, font, max_width):
    lines, line = [], ''
    for char in text:
        if draw.textlength(line + char, font=font) > max_width and line:
            lines.append(line)
            line = char
        else:
            line += char
    if line:
        lines.append(line)
    return lines


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', default='production.json')
    p.add_argument('--assets', default='assets')
    p.add_argument('--out', default='output')
    p.add_argument('--font', required=True, help='Path to a licensed Chinese TTF/OTF/TTC font')
    p.add_argument('--check-only', action='store_true')
    p.add_argument('--force', action='store_true', help='Allow overwriting generated output files')
    a = p.parse_args()
    for exe in ['ffmpeg', 'ffprobe']:
        if not shutil.which(exe):
            raise ValueError(f'Missing dependency: {exe}')
    font_path = Path(a.font).resolve()
    if not font_path.is_file():
        raise ValueError(f'Font not found: {font_path}')
    project = json.loads(Path(a.project).read_text(encoding='utf-8'))
    w, h, fps = (project[k] for k in ['width', 'height', 'fps'])
    if not all(isinstance(v, int) and v > 0 for v in (w, h, fps)) or w % 2 or h % 2:
        raise ValueError('Resolution must contain positive even integers; fps must be positive')
    assets, out = Path(a.assets).resolve(), Path(a.out).resolve()
    font = ImageFont.truetype(str(font_path), max(16, round(w * 0.044)))
    small = ImageFont.truetype(str(font_path), max(12, round(w * 0.024)))
    shots, ids = [], set()
    for s in project['shots']:
        sid = s['id']
        if not isinstance(sid, str) or not sid.isdigit() or sid in ids:
            raise ValueError('Shot IDs must be unique digit strings')
        ids.add(sid)
        if not isinstance(s.get('text'), str) or not s['text'].strip():
            raise ValueError(f'{sid}: missing dialogue')
        nominal = float(s['duration'])
        if not math.isfinite(nominal) or not 0 < nominal <= 12:
            raise ValueError(f'{sid}: invalid nominal duration')
        image, audio = assets / 'images' / f'{sid}.png', assets / 'audio' / f'{sid}.wav'
        with Image.open(image) as im:
            im.verify()
        info = probe(audio)
        if not any(t['codec_type'] == 'audio' for t in info['streams']):
            raise ValueError(f'{sid}: no audio stream')
        audio_dur = float(info['format']['duration'])
        if not math.isfinite(audio_dur) or audio_dur <= 0:
            raise ValueError(f'{sid}: invalid audio duration')
        duration = math.ceil(max(nominal, audio_dur + 0.6) * fps) / fps
        if duration > 12:
            raise ValueError(f'{sid}: audio too long; resynthesize/split it, do not truncate')
        shots.append(dict(s, image=image, audio=audio, audio_duration=audio_dur, actual_duration=duration))
    if not shots:
        raise ValueError('Empty shot list')
    print(f'Validated {len(shots)} shots; planned runtime {sum(s["actual_duration"] for s in shots):.2f}s')
    if a.check_only:
        print('Technical input check only: does not verify illustration quality, speech content or font licensing.')
        return
    if out.exists() and any(out.iterdir()) and not a.force:
        raise ValueError('Output directory is not empty; select another --out or explicitly use --force')
    out.mkdir(parents=True, exist_ok=True)
    build = out / 'build'
    build.mkdir(exist_ok=True)
    timeline, srt, elapsed = [], [], 0.0
    for i, s in enumerate(shots):
        sid, d = s['id'], s['actual_duration']
        frames = round(d * fps)
        layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        lines = wrap(s['text'], draw, font, w * 0.78)
        if len(lines) > 3:
            raise ValueError(f'{sid}: subtitle exceeds 3 lines; shorten/split dialogue')
        line_h = round(w * 0.066)
        y = round(h * 0.80) - (len(lines) - 1) * line_h
        for line in lines:
            x = (w - draw.textlength(line, font=font)) / 2
            draw.text((x, y), line, font=font, fill='white', stroke_width=max(1, w // 350), stroke_fill='black')
            y += line_h
        draw.text((round(w * 0.075), round(h * 0.055)), 'AI辅助生成', font=small, fill='white', stroke_width=1, stroke_fill='black')
        overlay = build / f'{sid}_overlay.png'
        layer.save(overlay)
        z = f'1.04-0.04*on/{max(frames-1, 1)}' if s.get('motion') == '缓慢拉远' else f'1+0.04*on/{max(frames-1, 1)}'
        filt = (f'[0:v]scale={w*2}:{h*2}:force_original_aspect_ratio=increase,'
                f'crop={w*2}:{h*2},setsar=1,zoompan=z=\'{z}\':x=\'iw/2-iw/zoom/2\':'
                f'y=\'ih/2-ih/zoom/2\':d={frames}:s={w}x{h}:fps={fps}[bg];'
                '[bg][2:v]overlay=0:0:format=auto,format=yuv420p[v];'
                f'[1:a]aresample=48000,adelay=200:all=1,apad,atrim=duration={d},asetpts=PTS-STARTPTS[a]')
        segment = build / f'{sid}.mp4'
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', s['image'], '-i', s['audio'],
             '-i', overlay, '-filter_complex', filt, '-map', '[v]', '-map', '[a]', '-t', d,
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-c:a', 'aac', '-b:a', '192k',
             '-ar', '48000', '-ac', '2', '-movflags', '+faststart', segment])
        srt.append(f'{i+1}\n{stamp(elapsed)} --> {stamp(elapsed+d)}\n{s["text"]}\n')
        timeline.append({'id': sid, 'start': round(elapsed, 3), 'end': round(elapsed+d, 3),
                         'audio_duration': s['audio_duration'], 'text': s['text']})
        elapsed += d
        print(f'Rendered shot {sid}')
    listing = build / 'concat.txt'
    listing.write_text(''.join(f"file '{s['id']}.mp4'\n" for s in shots), encoding='utf-8')
    final = out / 'final.mp4'
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '1', '-i', listing,
         '-c:v', 'copy', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-c:a', 'aac', '-b:a', '192k',
         '-ar', '48000', '-ac', '2', '-movflags', '+faststart', final])
    (out / 'subtitles.srt').write_text('\n'.join(srt), encoding='utf-8')
    (out / 'timeline.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding='utf-8')
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', '1', '-i', final, '-frames:v', '1', out / 'cover.png'])
    info = probe(final)
    video = next(x for x in info['streams'] if x['codec_type'] == 'video')
    audio = next(x for x in info['streams'] if x['codec_type'] == 'audio')
    actual = float(info['format']['duration'])
    checks = {'h264': video['codec_name'] == 'h264', 'resolution': (video['width'], video['height']) == (w, h),
              'aac': audio['codec_name'] == 'aac', 'duration': abs(actual-elapsed) < 0.5,
              'pixel_format': video['pix_fmt'] == 'yuv420p',
              'fps': Fraction(video['avg_frame_rate']) == fps,
              'sample_rate': int(audio['sample_rate']) == 48000,
              'channels': audio['channels'] == 2}
    # Decode the complete result; metadata alone does not prove playable media.
    run(['ffmpeg', '-v', 'error', '-xerror', '-i', final, '-f', 'null', '-'])
    report = {'technical_checks': checks, 'planned_seconds': elapsed, 'actual_seconds': actual,
              'shot_count': len(shots), 'full_decode': 'passed',
              'human_review_required': ['character consistency', 'correct spoken words', 'subtitle glyphs and readability',
                                        'story continuity', 'audio loudness by listening/measurement', 'rights and platform disclosure'],
              'note': 'No images or speech were generated by this script. No publication performed. SRT is shot-level, not word-aligned.'}
    (out / 'qa.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not all(checks.values()):
        raise ValueError('Output QA failed; inspect qa.json')
    print(f'Local composition complete: {final}; human editorial review still required.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stderr[-4000:])
        raise SystemExit(str(exc))
