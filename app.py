#!/usr/bin/env python3
"""
Video2Text - 视频课程转文字工具
将 m3u8/mp4 在线视频自动转为文字逐字稿

功能：
  - 下载 m3u8/mp4 视频并提取音频
  - Whisper AI 语音转文字（支持中文/英文/多语言）
  - 输出 Markdown 逐字稿、SRT 字幕、纯文本
  - Web 界面，实时进度显示

作者：liman
开源协议：MIT
"""

import os
import re
import uuid
import json
import subprocess
import threading
import time
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__, static_folder='web')
CORS(app)

# ============================================================
# 配置
# ============================================================

# Whisper 模型：tiny / base / small / medium / large
# 越大越准但越慢，推荐中文用 medium
WHISPER_MODEL = os.environ.get('WHISPER_MODEL', 'medium')

# 默认语言（zh=中文, en=英文, None=自动检测）
DEFAULT_LANGUAGE = os.environ.get('DEFAULT_LANGUAGE', 'zh')

# ASR 引擎：local / groq
# local = 本地 Whisper（免费但慢）
# groq = Groq 云端 API（快60倍，需注册免费 API Key）
ASR_ENGINE = os.environ.get('ASR_ENGINE', 'local')

# Groq API Key（免费注册：https://console.groq.com）
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')

# 服务端口
PORT = int(os.environ.get('PORT', 8899))

# 输出目录
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 任务状态存储（生产环境建议换 Redis）
tasks = {}

# 历史记录文件
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'history.json')
history_lock = threading.Lock()


def load_history():
    """从文件加载历史记录"""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return []


def save_history(history):
    """保存历史记录到文件"""
    try:
        with history_lock:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def add_history_record(task_id, url, status, message='', audio_file=None,
                       video_file=None, duration=0, result=None, referer=None):
    """添加或更新历史记录"""
    history = load_history()

    # 查找已有的记录
    existing = None
    for h in history:
        if h.get('task_id') == task_id:
            existing = h
            break

    record = {
        'task_id': task_id,
        'url': url,
        'status': status,
        'message': message,
        'created_at': existing['created_at'] if existing else time.strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'audio_file': audio_file or (existing.get('audio_file') if existing else None),
        'video_file': video_file or (existing.get('video_file') if existing else None),
        'duration': duration or (existing.get('duration', 0) if existing else 0),
        'referer': referer or (existing.get('referer') if existing else None),
        'note': existing.get('note', '') if existing else '',
    }

    # 保存文件信息
    if result and 'files' in result:
        record['files'] = result['files']
        record['segments_count'] = result.get('segments_count', 0)
    elif existing:
        if 'files' in existing:
            record['files'] = existing['files']
        if 'segments_count' in existing:
            record['segments_count'] = existing['segments_count']

    if existing:
        history = [h for h in history if h.get('task_id') != task_id]
    history.append(record)

    # 按时间倒序，最多保留 100 条
    history.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    history = history[:100]

    save_history(history)


# ============================================================
# 工具函数
# ============================================================

def format_timestamp(seconds):
    """格式化时间戳为 SRT 格式：00:05:23,456"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    if h > 0:
        return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
    return f'{m:02d}:{s:02d},{ms:03d}'


def format_timestamp_short(seconds):
    """格式化简短时间戳：05:23"""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f'{m:02d}:{s:02d}'


def update_task(task_id, **kwargs):
    """更新任务状态"""
    if task_id in tasks:
        tasks[task_id].update(kwargs)


def sanitize_filename(name):
    """清理文件名中的非法字符"""
    return re.sub(r'[^\w\-_.]', '_', name)


# ============================================================
# 核心处理流程
# ============================================================

def download_audio(url, output_path, task_id, referer=None):
    """
    用 ffmpeg 下载 m3u8/mp4 并提取为 MP3 音频
    支持自定义 Referer 头（部分平台需要）
    """
    cmd = ['ffmpeg', '-i', url]

    # 如果指定了 referer，添加请求头
    if referer:
        cmd += ['-headers', f'Referer: {referer}']
        # 从 referer 提取 origin
        origin = re.match(r'(https?://[^/]+)', referer)
        if origin:
            cmd += ['-headers', f'Origin: {origin.group(1)}']
    else:
        # 默认不添加特殊 header，让 ffmpeg 自动处理
        pass

    cmd += [
        '-vn',               # 不要视频
        '-acodec', 'libmp3lame',  # MP3 编码
        '-ab', '128k',       # 128kbps
        '-y',                # 覆盖输出
        output_path
    ]

    update_task(task_id, status='downloading', message='正在下载音频...')

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )

    # 解析 ffmpeg 进度输出
    duration_pattern = re.compile(r'Duration: (\d{2}):(\d{2}):(\d{2})')
    time_pattern = re.compile(r'time=(\d{2}):(\d{2}):(\d{2})')
    total_duration = None

    for line in process.stdout:
        if total_duration is None:
            m = duration_pattern.search(line)
            if m:
                total_duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                update_task(task_id, total_duration=total_duration)

        m = time_pattern.search(line)
        if m and total_duration:
            current = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            progress = min(int(current / total_duration * 100), 99)
            update_task(task_id, progress=progress,
                       message=f'正在下载音频... {progress}%')

    process.wait()
    return process.returncode == 0


def download_video(url, output_path, task_id, referer=None):
    """
    用 ffmpeg 下载 m3u8/mp4 并保存为 MP4 视频
    支持自定义 Referer 头（部分平台需要）
    """
    cmd = ['ffmpeg', '-i', url]

    if referer:
        cmd += ['-headers', f'Referer: {referer}']
        origin = re.match(r'(https?://[^/]+)', referer)
        if origin:
            cmd += ['-headers', f'Origin: {origin.group(1)}']

    cmd += [
        '-c', 'copy',           # 直接复制流，不重新编码（快）
        '-y',                    # 覆盖输出
        output_path
    ]

    update_task(task_id, status='downloading', message='正在下载视频...')

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )

    duration_pattern = re.compile(r'Duration: (\d{2}):(\d{2}):(\d{2})')
    time_pattern = re.compile(r'time=(\d{2}):(\d{2}):(\d{2})')
    total_duration = None

    for line in process.stdout:
        if total_duration is None:
            m = duration_pattern.search(line)
            if m:
                total_duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                update_task(task_id, total_duration=total_duration)

        m = time_pattern.search(line)
        if m and total_duration:
            current = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            progress = min(int(current / total_duration * 100), 99)
            update_task(task_id, progress=progress,
                       message=f'正在下载视频... {progress}%')

    process.wait()
    return process.returncode == 0


def transcribe_audio(mp3_path, task_id, language=None):
    """
    将音频转写为文字，生成多种格式文件
    根据 ASR_ENGINE 配置选择本地 Whisper 或 Groq 云端
    """
    if ASR_ENGINE == 'groq' and GROQ_API_KEY:
        return transcribe_with_groq(mp3_path, task_id, language)
    else:
        return transcribe_with_whisper(mp3_path, task_id, language)


def transcribe_with_whisper(mp3_path, task_id, language=None):
    """用本地 Whisper 转写（免费但较慢）"""
    import whisper

    model_name = WHISPER_MODEL
    update_task(task_id, message=f'正在加载本地 Whisper {model_name} 模型（首次需下载约1.5GB）...')
    model = whisper.load_model(model_name)

    update_task(task_id, message='正在转写语音（本地模式，较慢）...', progress=5)

    lang = language or DEFAULT_LANGUAGE or None
    result = model.transcribe(mp3_path, language=lang, verbose=False)

    segments = result.get('segments', [])
    full_text = result.get('text', '').strip()
    base_name = os.path.splitext(os.path.basename(mp3_path))[0]

    return save_results(base_name, segments, full_text, task_id, engine='Whisper')


def transcribe_with_groq(mp3_path, task_id, language=None):
    """
    用 Groq 云端 API 转写（快60倍，免费额度）
    注册地址：https://console.groq.com
    """
    try:
        from groq import Groq
    except ImportError:
        # 自动安装
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'groq', '--user', '-q'])
        from groq import Groq

    update_task(task_id, message='正在连接 Groq 云端（极速模式）...', progress=5)

    client = Groq(api_key=GROQ_API_KEY)

    lang = language or DEFAULT_LANGUAGE or 'zh'
    update_task(task_id, message='正在上传音频并转写...', progress=10)

    with open(mp3_path, 'rb') as f:
        # Groq 支持的格式：mp3, mp4, wav, flac, etc.
        transcription = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=f,
            language=lang,
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )

    update_task(task_id, progress=90)

    # 解析 Groq 返回的 segments
    segments = []
    full_text = transcription.text.strip()

    if hasattr(transcription, 'segments') and transcription.segments:
        for seg in transcription.segments:
            segments.append({
                'start': seg.get('start', 0),
                'end': seg.get('end', 0),
                'text': seg.get('text', '').strip()
            })
    else:
        # 如果没有分段信息，整个作为一段
        segments.append({
            'start': 0,
            'end': 0,
            'text': full_text
        })

    base_name = os.path.splitext(os.path.basename(mp3_path))[0]
    return save_results(base_name, segments, full_text, task_id, engine='Groq')


def save_results(base_name, segments, full_text, task_id, engine='Whisper'):
    """保存转写结果为多种格式文件"""
    safe_name = sanitize_filename(base_name)

    # --- 1. 纯文本 ---
    txt_path = os.path.join(OUTPUT_DIR, f'{safe_name}.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(full_text)

    # --- 2. SRT 字幕 ---
    srt_path = os.path.join(OUTPUT_DIR, f'{safe_name}.srt')
    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            start = format_timestamp(seg['start'])
            end = format_timestamp(seg['end'])
            f.write(f'{i}\n{start} --> {end}\n{seg["text"].strip()}\n\n')

    # --- 3. Markdown 逐字稿 ---
    md_path = os.path.join(OUTPUT_DIR, f'{safe_name}.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('# 课程逐字稿\n\n')
        f.write(f'> 由 Video2Text ({engine} AI) 自动转写\n\n')
        f.write('---\n\n')

        for seg in segments:
            ts = format_timestamp_short(seg['start'])
            f.write(f'**[{ts}]** {seg["text"].strip()}\n\n')

        f.write('\n---\n\n*转写完成*\n')

    # --- 4. 摘要 ---
    summary = generate_summary(segments)
    summary_path = os.path.join(OUTPUT_DIR, f'{safe_name}_summary.md')
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary)

    update_task(task_id, progress=100)

    return {
        'text': full_text,
        'segments_count': len(segments),
        'files': {
            'mp3': f'{safe_name}.mp3',
            'txt': f'{safe_name}.txt',
            'srt': f'{safe_name}.srt',
            'markdown': f'{safe_name}.md',
            'summary': f'{safe_name}_summary.md',
        }
    }


def generate_summary(segments):
    """按时间段生成课程笔记摘要"""
    if not segments:
        return '# 课程笔记摘要\n\n未检测到语音内容。\n'

    total_duration = segments[-1]['end']
    total_minutes = int(total_duration / 60)

    summary = f'# 课程笔记摘要\n\n'
    summary += f'**课程时长：** {total_minutes} 分钟\n'
    summary += f'**总段落数：** {len(segments)} 段\n\n'
    summary += '---\n\n'

    # 按 10 分钟分段
    section_duration = 600
    num_sections = max(1, int(total_duration / section_duration) + 1)

    for i in range(num_sections):
        start_time = i * section_duration
        end_time = min((i + 1) * section_duration, total_duration)

        section_segments = [seg for seg in segments
                          if seg['start'] >= start_time and seg['start'] < end_time]
        if not section_segments:
            continue

        start_ts = format_timestamp_short(start_time)
        end_ts = format_timestamp_short(end_time)

        summary += f'## {start_ts} - {end_ts}\n\n'
        section_text = ' '.join([seg['text'].strip() for seg in section_segments])

        # 取前 300 字作为摘要预览
        if len(section_text) > 300:
            summary += f'{section_text[:300]}...\n\n'
        else:
            summary += f'{section_text}\n\n'

    summary += '---\n\n### 完整逐字稿\n\n'
    for seg in segments:
        ts = format_timestamp_short(seg['start'])
        summary += f'**[{ts}]** {seg["text"].strip()}\n\n'

    summary += '\n---\n\n*由 Video2Text (Whisper AI) 自动生成，仅供参考*\n'
    return summary


def process_video(task_id, url, referer=None, language=None, mode='audio'):
    """步骤1：下载视频或提取音频"""
    try:
        file_id = task_id[:8]
        mp3_path = os.path.join(OUTPUT_DIR, f'{file_id}.mp3')
        mp4_path = os.path.join(OUTPUT_DIR, f'{file_id}.mp4')

        update_task(task_id, status='downloading',
                   message=f'正在下载{"视频" if mode == "video" else "音频"}...')

        if mode == 'video':
            success = download_video(url, mp4_path, task_id, referer=referer)
            if not success:
                update_task(task_id, status='error', message='视频下载失败，请检查 URL 是否正确或是否需要登录')
                return
            if not os.path.exists(mp4_path) or os.path.getsize(mp4_path) < 1000:
                update_task(task_id, status='error', message='视频文件异常，可能 URL 需要登录/已过期/格式不支持')
                return
            duration = 0
            # 尝试获取时长
            try:
                probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                             '-of', 'csv=p=0', mp4_path]
                result = subprocess.run(probe_cmd, capture_output=True, text=True)
                duration = float(result.stdout.strip()) if result.stdout.strip() else 0
            except Exception:
                pass
            update_task(task_id, status='video_ready',
                       message=f'视频下载完成',
                       duration=int(duration), progress=100,
                       video_file=f'{file_id}.mp4')
            add_history_record(task_id, url, 'video_ready',
                              message='视频下载完成',
                              video_file=f'{file_id}.mp4', duration=int(duration),
                              referer=referer)
        else:
            success = download_audio(url, mp3_path, task_id, referer=referer)
            if not success:
                update_task(task_id, status='error', message='音频下载失败，请检查 URL 是否正确或是否需要登录')
                return
            if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) < 1000:
                update_task(task_id, status='error', message='音频文件异常，可能 URL 需要登录/已过期/格式不支持')
                return
            probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                         '-of', 'csv=p=0', mp3_path]
            result = subprocess.run(probe_cmd, capture_output=True, text=True)
            duration = float(result.stdout.strip()) if result.stdout.strip() else 0
            update_task(task_id, status='audio_ready',
                       message=f'音频下载完成 ({int(duration/60)}分钟)',
                       duration=int(duration), progress=100,
                       audio_file=f'{file_id}.mp3')
            add_history_record(task_id, url, 'audio_ready',
                              message=f'音频下载完成 ({int(duration/60)}分钟)',
                              audio_file=f'{file_id}.mp3', duration=int(duration),
                              referer=referer)

    except Exception as e:
        update_task(task_id, status='error', message=f'下载出错: {str(e)}')
        add_history_record(task_id, url, 'error', message=f'下载出错: {str(e)}', referer=referer)


def process_transcribe(task_id, language=None):
    """步骤2：对已下载的音频进行语音转文字"""
    try:
        task = tasks.get(task_id)
        if not task:
            return

        audio_file = task.get('audio_file', '')
        mp3_path = os.path.join(OUTPUT_DIR, audio_file)

        if not audio_file or not os.path.exists(mp3_path):
            update_task(task_id, status='error', message='音频文件不存在，请重新下载')
            return

        update_task(task_id, status='transcribing', message='准备转写...', progress=0)

        result = transcribe_audio(mp3_path, task_id, language=language)

        update_task(task_id, status='completed',
                   message=f'转写完成！共 {result["segments_count"]} 段',
                   result=result)
        add_history_record(task_id, task.get('url', ''), 'completed',
                          message=f'转写完成！共 {result["segments_count"]} 段',
                          audio_file=audio_file,
                          duration=task.get('duration', 0),
                          result=result)

    except Exception as e:
        update_task(task_id, status='error', message=f'转写出错: {str(e)}')
        task = tasks.get(task_id)
        add_history_record(task_id, task.get('url', '') if task else '', 'error',
                          message=f'转写出错: {str(e)}',
                          audio_file=task.get('audio_file') if task else None)


# ============================================================
# API 路由
# ============================================================

@app.route('/')
def index():
    """前端页面"""
    return send_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'index.html'))


@app.route('/api/task', methods=['POST'])
def create_task():
    """步骤1：创建任务并开始下载视频/音频"""
    data = request.json or {}
    url = data.get('url', '').strip()
    referer = data.get('referer', '').strip() or None
    language = data.get('language', '').strip() or None
    mode = data.get('mode', 'audio').strip()  # audio / video

    if not url:
        return jsonify({'error': '请输入视频 URL'}), 400
    if not url.startswith('http'):
        return jsonify({'error': '请输入有效的 URL 地址'}), 400

    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        'id': task_id,
        'url': url,
        'status': 'created',
        'message': '任务已创建',
        'progress': 0,
        'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'referer': referer,
        'language': language,
    }

    thread = threading.Thread(target=process_video, args=(task_id, url, referer, language, mode))
    thread.daemon = True
    thread.start()

    return jsonify({'task_id': task_id})


@app.route('/api/task/<task_id>/transcribe', methods=['POST'])
def start_transcribe(task_id):
    """步骤2：对已下载的音频开始语音转文字"""
    task = tasks.get(task_id)

    # 如果内存中没有任务（如服务重启后），尝试从历史记录恢复
    if not task:
        history = load_history()
        for h in history:
            if h.get('task_id') == task_id:
                task = {
                    'id': task_id,
                    'url': h.get('url', ''),
                    'status': h.get('status', 'audio_ready'),
                    'audio_file': h.get('audio_file'),
                    'duration': h.get('duration', 0),
                    'referer': h.get('referer'),
                    'language': h.get('language'),
                }
                tasks[task_id] = task
                break

    if not task:
        return jsonify({'error': '任务不存在'}), 404
    if task.get('status') not in ('audio_ready', 'transcribing'):
        return jsonify({'error': f'当前状态不可转写：{task.get("message", "")}'}), 400

    data = request.json or {}
    language = data.get('language', '').strip() or task.get('language') or None

    thread = threading.Thread(target=process_transcribe, args=(task_id, language))
    thread.daemon = True
    thread.start()

    return jsonify({'message': '转写已开始'})


@app.route('/api/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """查询任务状态和进度"""
    task = tasks.get(task_id)

    # 如果内存中没有任务，尝试从历史记录恢复
    if not task:
        history = load_history()
        for h in history:
            if h.get('task_id') == task_id:
                task = {
                    'id': task_id,
                    'url': h.get('url', ''),
                    'status': h.get('status', 'unknown'),
                    'message': h.get('message', ''),
                    'progress': h.get('progress', 0),
                    'created_at': h.get('created_at', ''),
                    'audio_file': h.get('audio_file'),
                    'video_file': h.get('video_file'),
                    'duration': h.get('duration', 0),
                    'referer': h.get('referer'),
                    'language': h.get('language'),
                    'note': h.get('note', ''),
                }
                if h.get('files'):
                    task['result'] = {'files': h['files'], 'segments_count': h.get('segments_count', 0)}
                tasks[task_id] = task
                break

    if not task:
        return jsonify({'error': '任务不存在'}), 404

    response = {
        'id': task['id'],
        'status': task['status'],
        'message': task['message'],
        'progress': task.get('progress', 0),
        'created_at': task.get('created_at', ''),
    }
    if 'duration' in task:
        response['duration'] = task['duration']
    if 'audio_file' in task:
        response['audio_file'] = task['audio_file']
    if 'video_file' in task:
        response['video_file'] = task['video_file']
    if 'result' in task:
        response['result'] = task['result']

    return jsonify(response)


@app.route('/api/files/<filename>')
def download_file(filename):
    """下载生成的文件"""
    # 安全检查：防止路径遍历
    safe_name = os.path.basename(filename)
    filepath = os.path.join(OUTPUT_DIR, safe_name)
    if not os.path.exists(filepath):
        return jsonify({'error': '文件不存在'}), 404
    return send_file(filepath, as_attachment=True)


@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    """列出所有任务"""
    task_list = []
    for tid, task in tasks.items():
        task_list.append({
            'id': task['id'],
            'url': task['url'],
            'status': task['status'],
            'message': task['message'],
            'progress': task.get('progress', 0),
            'created_at': task.get('created_at', ''),
        })
    task_list.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return jsonify({'tasks': task_list})


@app.route('/api/history', methods=['GET'])
def get_history():
    """获取历史记录"""
    history = load_history()
    return jsonify({'history': history})


@app.route('/api/history/<task_id>/note', methods=['POST'])
def update_note(task_id):
    """更新历史记录备注"""
    data = request.json or {}
    note = data.get('note', '')
    history = load_history()
    for h in history:
        if h.get('task_id') == task_id:
            h['note'] = note
            h['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            save_history(history)
            return jsonify({'message': '备注已更新'})
    return jsonify({'error': '记录不存在'}), 404


@app.route('/api/history/<task_id>', methods=['DELETE'])
def delete_history(task_id):
    """删除历史记录"""
    history = load_history()
    new_history = [h for h in history if h.get('task_id') != task_id]
    if len(new_history) == len(history):
        return jsonify({'error': '记录不存在'}), 404
    save_history(new_history)
    return jsonify({'message': '已删除'})


# ============================================================
# 启动
# ============================================================

if __name__ == '__main__':
    print()
    print('  ╔══════════════════════════════════════╗')
    print('  ║     Video2Text 视频转文字服务        ║')
    print('  ╠══════════════════════════════════════╣')
    print(f'  ║  地址: http://localhost:{PORT}          ║')
    if ASR_ENGINE == 'groq' and GROQ_API_KEY:
        print(f'  ║  引擎: Groq (云端极速)            ║')
    else:
        print(f'  ║  引擎: Whisper {WHISPER_MODEL:<18s}  ║')
    print(f'  ║  语言: {DEFAULT_LANGUAGE or "自动检测":<26s}  ║')
    if ASR_ENGINE == 'groq' and GROQ_API_KEY:
        print('  ║  状态: 已启用 Groq (快60倍)       ║')
    else:
        print('  ║  提示: 设置 GROQ_API_KEY 可提速60x ║')
    print('  ╚══════════════════════════════════════╝')
    print()
    app.run(host='0.0.0.0', port=PORT, debug=False)
