# 🎬 Video2Text - 视频课程转文字工具

> 粘贴视频链接 → 下载视频/音频 → 语音转文字 → Markdown 逐字稿

**适用场景：** 在线课程学习、讲座记录、会议纪要、视频内容整理

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ 功能特性

- 📥 **视频下载** — 支持 m3u8 (HLS) / mp4 格式，下载 MP3 音频或 MP4 视频
- 🤖 **AI 转写** — 支持 OpenAI Whisper（本地免费）和 Groq（云端极速）
- ⚡ **极速模式** — Groq 云端转写，1小时音频仅需1分钟（免费额度）
- 📝 **多种输出** — Markdown 逐字稿、SRT 字幕、纯文本、课程摘要
- 🌐 **Web 界面** — 简洁暗色主题，三步流程，每步可查看结果
- 📂 **历史记录** — 自动保存处理记录，支持备注，随时查看和下载
- 🐳 **Docker 部署** — 一行命令启动，零配置

## 📸 效果预览

```
步骤1：粘贴 m3u8 地址 → 📥 下载 MP3/MP4 → ✅ 音频就绪（可播放/下载）
步骤2：🤖 开始转写 → [加载模型] → [转写中 60%] → ✅ 完成
步骤3：查看结果 → 📋摘要 / 📝逐字稿 / 📄纯文本 → 下载

输出文件：
  📋 class02_01_summary.md   — 课程摘要（按时间段）
  📝 class02_01.md            — 完整逐字稿（带时间轴）
  💬 class02_01.srt           — SRT 字幕文件
  📄 class02_01.txt           — 纯文本
  🎵 class02_01.mp3           — 提取的音频
```

## 🚀 快速开始

### 前置要求

- Python 3.9+
- ffmpeg（音频/视频处理）

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/yourname/video2text.git
cd video2text

# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装 ffmpeg
# macOS:
brew install ffmpeg
# Ubuntu/Debian:
sudo apt install ffmpeg
# Windows: 下载 https://ffmpeg.org/download.html
```

### 启动

```bash
python3 app.py
```

打开浏览器访问 **http://localhost:8899**

## 🐳 Docker 部署（推荐）

```bash
# 一键启动
docker-compose up -d

# 访问
open http://localhost:8899
```

## 📖 使用教程

### 1. 获取视频 m3u8 地址

大多数在线课程平台使用 HLS (m3u8) 流媒体，获取方法：

**Safari / Chrome：**
1. 打开课程页面，播放视频
2. 按 `⌘ + Option + I`（Mac）或 `F12`（Windows）打开开发者工具
3. 点击 **Network（网络）** 标签
4. 在过滤框输入 `m3u8`
5. 刷新页面并重新播放视频
6. 右键 `.m3u8` 请求 → **Copy → Copy as cURL**
7. 从 cURL 命令中复制 URL 地址

### 2. 粘贴地址并转换

在 Video2Text 网页中粘贴 m3u8 URL，选择下载 MP3 或 MP4。

> 💡 部分平台需要设置 Referer 地址（高级选项），防止下载被拒绝。

### 3. 查看和下载结果

转换完成后，可以：
- 在线查看课程摘要、完整逐字稿、纯文本
- 下载 Markdown、SRT 字幕、纯文本、MP3 音频
- 在左侧历史记录中查看所有处理过的任务

## ⚙️ 配置

通过环境变量自定义配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `8899` | 服务端口 |
| `ASR_ENGINE` | `local` | ASR 引擎（`local`=本地Whisper / `groq`=云端极速） |
| `WHISPER_MODEL` | `medium` | Whisper 模型（tiny/base/small/medium/large） |
| `DEFAULT_LANGUAGE` | `zh` | 默认语言（zh/en/None=自动检测） |
| `GROQ_API_KEY` | 无 | Groq API Key（免费注册：https://console.groq.com） |

### 🚀 启用 Groq 极速模式（推荐！）

Groq 提供**免费额度**，速度比本地 Whisper 快 60 倍：

```bash
# 1. 注册 Groq 账号（免费）：https://console.groq.com
# 2. 获取 API Key
# 3. 启动时设置环境变量：
ASR_ENGINE=groq GROQ_API_KEY=你的key python3 app.py
```

**速度对比：**

| 引擎 | 1小时音频耗时 | 费用 |
|------|-------------|------|
| 本地 Whisper (medium) | ~60 分钟 | 免费 |
| **Groq 云端** | **~1 分钟** | **免费额度** |

**Whisper 模型对比：**

| 模型 | 大小 | 速度 | 中文准确度 | 推荐场景 |
|------|------|------|-----------|----------|
| tiny | 75MB | ⚡ 极快 | ⭐⭐ | 快速测试 |
| base | 150MB | 🚀 快 | ⭐⭐⭐ | 日常使用 |
| small | 500MB | 🏃 中等 | ⭐⭐⭐⭐ | 较好效果 |
| **medium** | **1.5GB** | **🚶 较慢** | **⭐⭐⭐⭐⭐** | **推荐！中文效果最好** |
| large | 3GB | 🐢 慢 | ⭐⭐⭐⭐⭐ | 最高精度 |

> 💡 **性能提示：** CPU 模式下 1 小时音频约需 60 分钟转写。有 GPU 可提速 10 倍以上。

## 🛠 技术栈

- **后端：** Python + Flask
- **语音识别：** OpenAI Whisper / Groq
- **音频/视频处理：** FFmpeg
- **前端：** 原生 HTML/CSS/JS（暗色主题）

## 📁 项目结构

```
video2text/
├── app.py              # Flask 后端（核心）
├── web/
│   └── index.html      # 前端界面
├── requirements.txt    # Python 依赖
├── Dockerfile          # Docker 镜像
├── docker-compose.yml  # Docker 编排
├── output/             # 输出文件（自动创建）
│   ├── history.json    # 历史记录
│   └── *.md/*.txt/...  # 转写结果
├── LICENSE             # MIT 开源协议
└── README.md           # 本文件
```

## 📄 开源协议

MIT License - 可自由使用、修改和分发

## 🙏 致谢

- [OpenAI Whisper](https://github.com/openai/whisper) - 语音识别引擎
- [Groq](https://console.groq.com) - 云端极速推理
- [FFmpeg](https://ffmpeg.org/) - 音频/视频处理
- [Flask](https://flask.palletsprojects.com/) - Web 框架
