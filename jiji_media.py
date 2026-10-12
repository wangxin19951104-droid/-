"""Normalize incompatible clip streams before assembling a film."""
import re
import shutil
import subprocess
from pathlib import Path

from jiji_core import atomic_write


def stream_signature(path):
    probe = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(path)], capture_output=True, timeout=20)
    text = probe.stderr.decode('utf-8', 'replace')
    video = next((line.strip() for line in text.splitlines() if 'Video:' in line), '')
    audio = next((line.strip() for line in text.splitlines() if 'Audio:' in line), '')
    video = re.sub(r'Stream #[^:]+:[^:]+:', '', video)
    audio = re.sub(r'Stream #[^:]+:[^:]+:', '', audio)
    return video, audio


def concatenate(files, destination, folder):
    if not shutil.which('ffmpeg'):
        raise RuntimeError('片段已保存，但缺少ffmpeg，无法合片。')
    files = [Path(path).resolve() for path in files]
    if not files or any(not path.is_file() for path in files):
        raise RuntimeError('有片段文件缺失，不能合片。')
    destination, folder = Path(destination), Path(folder)
    destination.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir(parents=True, exist_ok=True)
    signatures = [stream_signature(path) for path in files]
    usable = files
    if not signatures[0][0] or any(signature != signatures[0] for signature in signatures[1:]):
        match = re.search(r'\b(\d{2,5})x(\d{2,5})\b', signatures[0][0])
        width, height = (int(match.group(1)), int(match.group(2))) if match else (1280, 720)
        width, height = width + width % 2, height + height % 2
        usable = []
        for index, path in enumerate(files):
            normalized = folder / f'normalized_{index}.mp4'
            command = ['ffmpeg', '-v', 'error', '-y', '-i', str(path)]
            if not signatures[index][1]:
                command += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']
            command += ['-map', '0:v:0', '-map', '0:a:0' if signatures[index][1] else '1:a:0',
                        '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24',
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-shortest', str(normalized)]
            subprocess.run(command, check=True, capture_output=True, timeout=900)
            usable.append(normalized)
    listing = folder / 'concat.txt'
    atomic_write(listing, ''.join("file '" + path.as_posix().replace("'", "'\\''") + "'\n" for path in usable))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing),
                    '-c', 'copy', '-movflags', '+faststart', str(destination)], check=True, capture_output=True, timeout=900)
    return str(destination)
