<div align="center">

# 空间大师 · Jellyfin 版 / SpaceMaster for Jellyfin

**给已有的 Jellyfin 加装空间大师 · 免费 · 不动您的 Jellyfin**

[中文](#中文) · [English](#english) · [📖 安装指南](安装指南.md)

</div>

> 空间大师只做转码音频工作，Jellyfin 字幕 / 刮削 / 元数据 / 媒体库 / 用户记录等其它功能均不受影响。

---

<a name="中文"></a>

## 中文

### 这是什么

空间大师是 **Jellyfin 的音频校正工具**。填一次房间尺寸，往后所有转码播放的声音都按您这间屋子的声学特性做过校正。

在网页控制台里填房间长宽高、喇叭距离等参数，会自动给出优化推荐数值：优化后的参量均衡（PEQ），可自行手动微调到符合自己的听感。针对不同的喇叭功率、摆位和角度手动调整声道延迟补偿，消除声波反相效果导致的空洞感，获得更清晰定位更准确的声像结像。目前仅提供2.0/2.1音箱延迟补偿功能，5.1系统正在开发优化中

支持电视机/电脑自带音箱、立体声 2.0/2.1、家庭影院 5.1 三种系统类型。

### 它怎么接进去

空间大师不改装 Jellyfin，只是在它外面套一层：

```
播放器 ──► :8097 代理 ──► :8096 Jellyfin ──► ffmpeg ──► 空间大师
```

- 播放时您连的是空间大师代理 `:8097`（不是 Jellyfin 的 `:8096`），代理再把流量转给 Jellyfin；
- 空间大师在 Jellyfin 转码那一刻，把按您房间算好的声音校正滤镜加进音频。

您的 Jellyfin 镜像、媒体库、配置一律不动；空间大师是独立叠加层，卸掉它 Jellyfin 立刻回到原版。怎么卸见 [安装指南.md](安装指南.md)。

👉 安装步骤见 [安装指南.md](安装指南.md)。

### 会不会影响 Jellyfin 的其它功能

不会。空间大师只拦截转码时的音频这一条线，Jellyfin 的其它功能都照常工作：

| Jellyfin 功能 | 是否受影响 | 原因 |
|---|---|---|
| 字幕烧录（硬字幕，转码时烤进画面） | 不受影响 | 走视频滤镜 `-vf subtitles=...`，wrapper 只动音频滤镜 `-af`，视频参数原样保留 |
| 外挂 / 挂载字幕（软字幕流） | 不受影响 | 由客户端直读字幕流或 Jellyfin 直流传送，不经过 ffmpeg 音频通道；wrapper 只 probe 音频流 a:0 |
| 刮削 / 元数据 / NFO / 识图 | 不受影响 | 纯 Jellyfin 核心（数据库 + API），从不经过 ffmpeg；代理也只改 PlaybackInfo 一个接口 |
| 媒体库 / 用户 / 播放记录 | 不受影响 | 空间大师不读写 Jellyfin 数据库与配置 |

### 开源边界

| 部分 | 状态 |
|---|---|
| 集成层（控制台、转码壳、代理、Docker 文件、文档） | ✅ 全部开源，可审计 |
| 声学引擎 | 引擎程序 `sm_dsp_engine`（随仓库分发） |

本项目完全免费。详见 [开源说明.md](开源说明.md)。

### 法律与开源声明

本项目是 Jellyfin 的第三方附加层，并非 Jellyfin 官方产品、也非其修改发行版：

- **我们不分发 Jellyfin**：终端用户使用的 Jellyfin 来自官方 Docker Hub 镜像 `jellyfin/jellyfin`，其 GPL 分发与对应源码由 Jellyfin 项目负责。我们既不修改也不托管 Jellyfin。
- **我们不做基于 `jellyfin/jellyfin` 的公开派生镜像。**
- **集成层全开源**：转码壳、控制台、代理、Docker 文件、文档均在本公开仓可审计；声学算法由引擎程序 `sm_dsp_engine` 提供（随仓库分发）。
- **商标**："Jellyfin" 为 Jellyfin 项目商标；本项目非官方关联 / 背书 / 赞助。

完整条款见仓库根 [`NOTICE`](NOTICE)。

---

<a name="english"></a>

## English

### What is this

SpaceMaster is a **room-acoustics correction layer for an existing Jellyfin server**. Enter your room dimensions once, and every transcoded playback gets corrected for your room.

From the web console you enter your room length/width/height and speaker distances, and it produces optimized recommended values: tuned parametric EQ (PEQ), which you can fine-tune by hand to match your own listening preference. You can also manually adjust per-channel delay compensation for different speaker power, placement and angle, eliminating the hollowness caused by out-of-phase waves and achieving a clearer, better-localized sound image. Channel delay compensation is currently available for 2.0 / 2.1 speakers; the 5.1 system is under development.

Supports TV/computer built-in speakers, stereo 2.0/2.1, and home-theater 5.1.

### How it hooks in

SpaceMaster does not modify Jellyfin — it wraps around it:

```
player ──► :8097 proxy ──► :8096 Jellyfin ──► ffmpeg ──► SpaceMaster
```

- At playback you connect to the SpaceMaster proxy `:8097` (not Jellyfin's `:8096`); the proxy forwards traffic to Jellyfin;
- At the moment Jellyfin transcodes, SpaceMaster injects an audio correction filter computed for your room.

Your Jellyfin image, media library and config are untouched. To uninstall: drop the overlay (remove the entrypoint) and restart — stock Jellyfin is back.

👉 Install: see [安装指南.md](安装指南.md) (Chinese).

### Does it affect any other Jellyfin feature

No. SpaceMaster only intercepts the audio stream at transcode time; every other Jellyfin feature works as before:

| Jellyfin feature | Affected? | Why |
|---|---|---|
| Subtitle burn-in (hard subs, baked into the picture during transcode) | No | Goes through the video filter `-vf subtitles=...`; the wrapper only touches the audio filter `-af`, video params are passed through unchanged |
| External / sidecar subtitles (soft subtitle stream) | No | Read directly by the client or streamed by Jellyfin; never goes through the ffmpeg audio channel; the wrapper only probes audio stream a:0 |
| Scraping / metadata / NFO / image recognition | No | Pure Jellyfin core (database + API), never goes through ffmpeg; the proxy only modifies the single PlaybackInfo endpoint |
| Library / users / playback history | No | SpaceMaster never reads or writes the Jellyfin database or config |

### Open-source boundary

| Component | Status |
|---|---|
| Integration layer (console, wrapper, proxy, Docker files, docs) | ✅ Fully open source, auditable |
| Room-acoustics algorithm | Shipped as the compiled binary `sm_dsp_engine` |

This project is completely free.

### Legal & open-source statement

This project is a third-party add-on layer for Jellyfin — not an official Jellyfin product, nor a modified distribution of it:

- **We do not distribute Jellyfin**: the Jellyfin used by end users comes from the official Docker Hub image `jellyfin/jellyfin`; its GPL distribution and corresponding source are the responsibility of the Jellyfin project. We neither modify nor host Jellyfin.
- **We do not publish a public derived image based on `jellyfin/jellyfin`.**
- **The integration layer is fully open source**: the wrapper, console, proxy, Docker files, and docs are all auditable in this public repo; the acoustics algorithm is distributed as a compiled binary.
- **Trademark**: "Jellyfin" is a trademark of the Jellyfin project; this project is not officially affiliated / endorsed / sponsored.

Full terms are in the root [`NOTICE`](NOTICE).

---

<div align="center">

完整的法律条款与开源边界见仓库根 [`NOTICE`](NOTICE)。
Full legal terms and open-source boundaries are in the root [`NOTICE`](NOTICE).

</div>
