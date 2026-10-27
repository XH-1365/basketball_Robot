# -*- coding: utf-8 -*-
# ============================================================
#  K210 CanMV —— 人体检测 / 多人跟踪 / 区域告警 / 按键拍照存 TF 卡
#  （Yahboom K210 + CanMV_Yahboom V2.1.1  实测可用）
#
#  基础来源: 嘉楠官方 canmv_examples -> head_body_detect
#            模型: uint8_person_detect_v1_old.kmodel (1.4MB)
#
#  相比官方原版例程多出来的东西（全是实测踩坑后的产物）:
#   1. 自动适配旧版 KPU API —— 本板固件没有 load()/Yolo2()，
#      官方 IDE 自带的 98-KPU_NEW 例程在这块板子上直接跑不了
#   2. 【先加载模型、后开 lcd】—— 开机自启的 main.py 会 lcd.init()
#      吃掉系统堆，导致 KPU 的 1.4MB 模型缓冲分配失败
#   3. 多人跟踪 + 稳定 ID（官方例程每帧重新编号，框会跳号）
#   4. 区域入侵告警（人进入指定区域 -> 串口 ALARM）
#   5. 累计进入人次统计
#   6. 按键拍照直存 TF 卡（三种触发: 按键 / 定时 / 告警联动）
#
#  【TF 卡的启动脚本位置 —— 实测大坑, 必须知道】
#  固件一旦挂上 SD 卡, 就会去执行 /sd/main.py, 而且【不会回落】到
#  /flash/main.py。所以本文件要同时存在这两个位置:
#      /flash/main.py   （卡不在时用）
#      /sd/main.py      （卡插着时用，固件优先）
#  部署: python tools/deploy.py   会一次推两处
#
#  运行: CanMV IDE 连接板子 -> 打开本文件 -> 点运行
# ============================================================

import gc
import machine
import math
import os
import time

import image
import lcd
import sensor

from fpioa_manager import fm
from maix import GPIO, KPU

import follow_link

# ============================================================
#  配置区 —— 想改什么改这里
# ============================================================

MODE = "BODY"          # BODY = 识别人体    HEAD = 识别人头

# --- 模型路径（按顺序找第一个存在的；找不到就试下一个）---
# 【重要】/sd 放前面。/flash 只有 2.63MB 且实测 >1MiB 的文件顺序读会
# OSError(5) EIO —— 文件"在"但 load_kmodel() 读不动, 会把启动流程整挂。
# SD 是 FAT32, 大文件读写正常, 所以模型一律优先从 /sd 拿。
BODY_MODEL_PATHS = (
    "/sd/person_v1.kmodel",
    "/sd/person_detect.kmodel",
    "/sd/KPU/head_body_detect/uint8_person_detect_v1_old.kmodel",
    "/flash/person_v1.kmodel",     # 兜底: /flash 小文件尚可, 大文件会 EIO
)
HEAD_MODEL_PATHS = (
    "/sd/head_v1.kmodel",
    "/sd/KPU/head_body_detect/uint8_head_detect_v1_old.kmodel",
    "/flash/head_v1.kmodel",
)

# --- 检测参数 ---
THRESHOLD = 0.70       # 置信度阈值: 调低更灵敏但误检多 (0.5 起步试)
NMS       = 0.20       # 重叠框抑制: 多人重叠多就调大

# --- 摄像头型号 & 每颗镜头独立的画面方向 / 标定参数（双镜头支持）---
#  插哪颗摄像头就自动套哪套参数，**不用改代码**:
#    CAM_KIND = "AUTO"            -> 开机读 sensor.get_id() 自动匹配
#    CAM_KIND = "GC2145"/"OV5640" -> 强制指定（排障时用）
#  新增一颗镜头: 往 CAM_PROFILES 里加一条即可（ids/hmirror/vflip/focal_px/cam_cy）
#
#  注意: focal_px / cam_cy 是**每颗镜头各自**的标定值，换镜头必须重标
#        （棋盘格链路: tools/shot_chess.py -> tools/chess_collect.py）
CAM_KIND = "AUTO"

CAM_PROFILES = {
    # 板载原装 2MP / 68°视场 / f=2.4
    "GC2145": {
        "label":    "GC2145 2MP 68deg (onboard)",
        "ids":      (45,),        # get_id() 实测值
        "hmirror":  False,        # 2026-10 实测: 非镜像安装
        "vflip":    False,
        "focal_px": 408.9,        # 棋盘格标定 2026-10-10 (fy, RMS 0.17px)
        "cam_cy":   102,
    },
    # DC-5M21-OV5640-8-03-V1 / 5MP / 68°视场 / f=2.8
    "OV5640": {
        "label":    "OV5640 5MP (DC-5M21)",
        "ids":      (0x5640,),    # get_id() 实测 22080 = 0x5640
        "hmirror":  False,        # 左右方向待实测（抬手验证）
        "vflip":    True,         # 2026-10-26 用户实测: 画面上下颠倒
        "focal_px": 0,            # 待标定: 0 = 关闭测距，只做检测/跟随
        "cam_cy":   120,          # 待标定
    },
}

# 下面这几个是"当前生效值"，apply_cam_profile() 开机时按型号覆盖
CAM_NAME = ""
HMIRROR  = False
VFLIP    = False

# --- 多人跟踪 ---
TRACK_ENABLE   = True
TRACK_MAX_DIST = 70    # 前后帧同一目标的中心点最大位移(像素), 人走得快就调大
TRACK_LOST     = 8     # 连续丢失多少帧才注销 ID（防止晃一下换号）

# --- 区域告警 ---
ALERT_ENABLE   = True
ALERT_X        = 107   # 告警区左上角（默认画面中间 1/3 竖条）
ALERT_Y        = 0
ALERT_W        = 106
ALERT_H        = 240
ALERT_FRAMES   = 5     # 连续多少帧有人在区内才报警（滤抖）
ALERT_COOLDOWN = 80    # 报警后冷却帧数（防刷屏）

# --- 距离估算（单目针孔模型，粗略估计）---
# 原理: 距离 = 人的真实身高 x 焦距(像素) / 画面里的框高(像素)
# 精度: 只在"整个人完整在画面里"时可信。头顶被切/画面底部裁掉都会失真，
#       所以对贴到画面顶部的框会显示 '>' 表示实际比显示值更近。
#
# 【怎么标定 FOCAL_PX —— 两种方法，任选】
#
#  方法一（推荐，一步搞定）: 比例修正
#    1. 拿卷尺量好，站在离镜头 D 米的正面位置，站直不动
#    2. 看屏幕上那个框旁边显示的距离，记下来叫 D_show
#    3. FOCAL_PX_新 = FOCAL_PX_旧 * D / D_show
#    例: 站在真实 2.0 米处，屏幕显示 4.9m
#        -> 新 FOCAL_PX = 277 * 2.0 / 4.9 = 113
#
#  方法二: 用框高像素数
#    1. 同上站位，看串口报的 h 值: DET n=1 ... #1 x125,y12,w58,h191,0.88,C
#    2. FOCAL_PX = D * h / PERSON_H_M
#    例: D=2.0, h=191, PERSON_H_M=1.70 -> FOCAL_PX = 224.7
#
#  不标定也能用: 下面的 277.0 是按 320x240 画面、水平视场角约 60 度算的
#  理论值 ((320/2)/tan(30度) = 277)，实测通常有 20%~30% 偏差。
#  注意 h 和 D 一定要在"人站着不动、全身完整在画面里"时读。
DIST_ENABLE = True

# --- 用哪套算法算距离 ---
#  HEIGHT = 用【框高】反算(针孔模型)。要知道人的身高; 个体差异 -> 约 ±6% 误差。
#  GROUND = 用【脚尖】反算(地面法)。要知道相机离地高度; 与人的身高完全无关。
#           代价: 相机俯角要稳、脚不能被画面底边切掉、地面基本平整。
#  AUTO   = 优先 GROUND, 脚尖不可用时(被切掉/太贴近水平)自动退回 HEIGHT。
#  取舍: GROUND 不受'这个人多高'影响, 对陌生人不失控;
#        HEIGHT 在身高已知的人身上更稳(用了更多像素做平均)。
DIST_MODE   = "HEIGHT"

PERSON_H_M  = 1.70     # 被检测者的真实身高(米)，多人身高差大会有偏差
                       # 1.70 = 对拍主体实测身高(用户确认 170cm)；多人场景想通用
                       # 就填人群均值(如 1.70)，别按个别人调
FOCAL_PX    = 408.9    # 焦距(像素), 棋盘格标定实测

# --- 地面法(GROUND / AUTO)专用参数 ---
CAM_H_M       = 1.20   # 相机镜头离地面的高度(米)。GROUND 下这是唯一的真值,
                       # 必须拿卷尺量准 —— 它线性影响结果。
CAM_PITCH_DEG = 0.0    # 相机俯角(度), 正数 = 镜头朝下。水平安装填 0。
                       # 拿不准就用 tools/fit_pitch.py 反算, 别硬猜:
                       # 俯角差 3 度, 近距离能差出好几十厘米。
CAM_CY        = 102    # 主点所在行, 棋盘格标定实测
CAM_FEET_MARGIN = 2    # 脚尖离画面底边不足这么多像素 -> 认为脚被切掉, GROUND 不可信
DIST_SMOOTH = 0.35     # 每帧向新值靠拢的比例(0~1)，越小越稳、越大越跟手
DIST_MIN_M  = 0.3      # 超出这个范围直接判为不可信
DIST_MAX_M  = 15.0

# --- 显示与上报 ---
SHOW_FPS      = True
SERIAL_REPORT = True
REPORT_EVERY  = 15     # 每 N 帧上报一次状态

# --- 底盘跟随链路（扩展口 UART, 板载丝印 TXD=IO8 / RXD=IO6, 3.3V TTL）---
# 协议/接线/调参见 docs/底盘跟随串口协议.md。IO4/5 是 USB 串口, IO13/14 是
# WiFi 模块(有跳线帽), 都不能用; IO17 是 BOOT 键。
FOLLOW_ENABLE    = True
FOLLOW_UART_ID   = 2
FOLLOW_TX_IO     = 8
FOLLOW_RX_IO     = 6
FOLLOW_BAUD      = 115200
FOLLOW_PERIOD_MS = 120      # 发帧周期, 约 8Hz
FOLLOW_LOST_FRAMES = 5      # 锁定目标连续丢 N 帧后放弃 id, 重新按"最居中"选人
FOLLOW_MIRROR_REPL = True   # 每帧同时打印到 USB 串口(调试用, 上线可关 False)
CAM_FX = 410.6              # 横向焦距(棋盘格标定 fx), 像素偏差->偏角用

# --- 心跳文件（无人值守时用来确认程序还活着 / 定位卡死时刻）---
# 0 = 关闭。设成 30 就是每 30 秒往 /flash/hb.txt 追加一行:
#     <帧号> <运行秒数> <累计人次>
# 注意: 频繁写 flash 有磨损，长期跑建议关掉(0)。
HEARTBEAT_SEC = 0
HB_PATH       = "/flash/hb.txt"

# --- 看门狗（保命设施，强烈建议开着）---
# 本板固件跑久了会偶发 core dump / 卡死在 C 层（实测遇到过），
# MicroPython 层 try/except 救不回来。所以武装硬件看门狗:
# 主循环每帧喂狗，一旦卡住超过 WDT_TIMEOUT_MS 没喂，硬件直接复位板子，
# main.py 会自动重跑，LCD 画面自动恢复。
# 想调试时按 Ctrl-C 停止会顺手关掉看门狗，板子就老实停在 REPL。
WDT_ENABLE     = True
WDT_TIMEOUT_MS = 30000   # 30 秒没喂狗就复位。别设太小，模型加载要几秒

# --- 模型加载失败怎么办（实测踩坑：别让它把板子拖进重启死循环）---
# False(推荐) = 回退到"纯预览模式": 画面照常上屏, 只是不画框, 串口报 PREVIEW。
#               这样模型文件损坏/传一半时, LCD 依然有画面, 你能一眼看出
#               是"没模型"而不是"板子死了"; 模型修好后重上电自动恢复。
# True         = 直接抛异常, 不重试也不回退(老行为, 会配合看门狗变成无限重启)。
# 注: False 时现在的流程是 "重试 -> 有限次自动重启 -> 才回退预览", 见下面的 MODEL_* 配置。
MODEL_MISSING_FATAL = False

# --- 模型加载失败时的自愈（2026-10-10 加）---
# 动机: 卡偶尔挂不上 -> 模型加载失败 -> 会静默退化成"只出画面不检测"。
#       无人值守时这是最危险的失败模式: 板子看着一切正常, 其实一个人都不检测。
# 做法(有限次, 绝不无限重启):
#   1. 原地重试 MODEL_RETRY 次(卡挂载慢 / 模型刚传到一半)
#   2. 还失败 -> 自动重启板子重来(重启会重跑固件的 SD 初始化, 实测常能自愈)
#   3. 连续 MODEL_MAX_REBOOTS 次开机都没拿到模型 -> 放弃重启, 老实停在预览模式
# 计数器放 /flash 而不是 /sd —— 卡没挂上时 /flash 照样可读写。
MODEL_RETRY         = 3      # 加载失败先原地重试几次
MODEL_RETRY_DELAY_S = 2.0    # 每次重试之间等多久
MODEL_AUTO_REBOOT   = True   # 重试还失败就自动重启重来
MODEL_MAX_REBOOTS   = 3      # 连续几次开机都失败就放弃重启(防无限重启)
BOOTFAIL_PATH       = "/flash/bootfail.txt"

# ============================================================
#  拍照存图配置
# ============================================================

# 开关总闸
SHOT_ENABLE     = True

# 存储位置（按顺序找第一个能挂上的）: 优先 TF 卡, 卡不在就退到板载 flash。
# 注意 /flash 只有 2.6MB 且剩几个块, 只能临时顶一下, 别长期用。
SHOT_DIRS       = ("/sd", "/flash")

# 文件名前缀 + 起始编号。
# SHOT_START_ID = 0 表示"自动续号": 启动时扫目录里已有的 cap_NNN.jpg,
# 取最大编号 +1 接着往下数（0 字节的坏文件会被跳过, 不计入）。
SHOT_PREFIX     = "cap_"
SHOT_START_ID   = 0
SHOT_QUALITY    = 90     # JPEG 质量 1~100, 越高越清楚越占地方

# 按键（BOOT 键 = IO17, 见 /flash/config.json 的 board_info.BOOT_KEY）
SHOT_KEY_IO     = 17
SHOT_KEY_ENABLE = True
SHOT_DEBOUNCE_MS = 500   # 防抖: 两次拍照至少间隔多少毫秒

# 定时连拍: 每隔多少秒自动存一张。0 = 关闭。
# 想拍延时摄影就设成 5 / 10 / 60 之类。跟按键互不干扰。
SHOT_EVERY_SEC  = 0

# 告警联动: 检测到有人进入告警区时自动存一张（跟告警冷却同步, 不会刷爆卡）
SHOT_ON_ALARM   = False

# 存下来的照片要不要带画面上的框和文字?
#   True  = 存"带框带字"的（当前帧画完再存, 一眼能看出检测结果）
#   False = 存"干净原图"（在画框之前存, 只有摄像头原画面）
SHOT_WITH_HUD   = True

# 剩余空间低于这个值(MB)就在屏幕和串口上报警, 别把卡写满
SHOT_LOW_MB     = 50

# 每拍一张往这个文件追加一行流水: <秒> <文件名> <触发原因> <结果>
# 触发原因: KEY=按键 / TIMER=定时 / ALARM=告警联动 / SYNTH=自测
# 无人值守时用来回溯"到底拍没拍到、是什么触发的、失败在哪"。空字符串 = 关闭。
SHOT_LOG        = "/sd/_shot.log"

# 屏幕反馈: 拍完放大显示结果文字, 并在最初 250ms 闪一圈亮青边。
# 只在屏幕上出现, 不进照片（画在存盘之后）。
SHOT_FLASH      = True
SHOT_TOAST_MS   = 2000   # 结果文字在屏幕上停留多久

# ============================================================
#  以下是实现，一般不用动
# ============================================================

ANCHOR_BODY = (0.0978, 0.1758, 0.1842, 0.3834, 0.3532, 0.5982,
               0.4855, 1.1146, 0.8869, 1.6407, 1.2388, 3.4157,
               2.0942, 2.1114, 2.7138, 5.0008, 6.0293, 6.4540)

ANCHOR_HEAD = (0.1074, 0.1458, 0.1367, 0.2137, 0.1758, 0.2824,
               0.2441, 0.3333, 0.2188, 0.4167, 0.2969, 0.5000,
               0.4102, 0.6667, 0.6094, 0.9722, 1.2364, 1.6915)

NET_W, NET_H = 320, 256
FRAME_W, FRAME_H = 320, 240

COLOR_BODY  = (255, 0, 0)      # 人体框 红
COLOR_HEAD  = (0, 255, 0)      # 人头框 绿
COLOR_ALERT = (255, 160, 0)    # 告警中的目标 橙
COLOR_TEXT  = (255, 255, 0)    # HUD 文字 亮黄(用户指定, 深蓝在实拍画面上看不见)
COLOR_ZONE  = (255, 255, 0)    # 告警区边框
COLOR_SHOT  = (0, 255, 255)    # 拍照提示 亮青
COLOR_FAIL  = (255, 40, 40)    # 拍照失败 亮红


def hud_text(img, x, y, s, color, scale):
    """HUD 文字: 先用黑描边勾一圈再画亮色, 任何背景下都看得清。
    (深蓝小字在实拍画面上几乎隐形, 用户要求改成醒目的黄字)"""
    img.draw_string(x + 1, y, s, color=(0, 0, 0), scale=scale)
    img.draw_string(x - 1, y, s, color=(0, 0, 0), scale=scale)
    img.draw_string(x, y + 1, s, color=(0, 0, 0), scale=scale)
    img.draw_string(x, y - 1, s, color=(0, 0, 0), scale=scale)
    img.draw_string(x, y, s, color=color, scale=scale)


def file_exists(path):
    try:
        d, name = path.rsplit("/", 1)
        return name in os.listdir(d if d else "/")
    except Exception:
        return False


def load_model(kpu, paths, label):
    """按顺序试每条路径。

    某个文件"存在但读不动"（/flash 的 >1MiB EIO 就是这么回事）不能直接崩，
    要打条警告继续试下一个，否则 SD 明明有份好模型也用不上。
    """
    tried = []
    for p in paths:
        if not file_exists(p):
            continue
        try:
            print("[%s] 加载模型: %s" % (label, p))
            kpu.load_kmodel(p)
            print("[%s] 模型加载成功: %s" % (label, p))
            return p
        except Exception as e:
            print("[%s] !! 这份读不了, 换下一个: %s -> %s" % (label, p, repr(e)))
            tried.append(p)
    if tried:
        raise OSError("[%s] 有文件但都读不动: %s" % (label, tried))
    raise OSError("[%s] 找不到模型文件（BODY 需 /sd/person_v1.kmodel，"
                  "用 tools/deploy.py 或串口上传）" % label)


class ShotStore(object):
    """
    拍照存储: 自动挑目录、自动续号、写完立刻验大小。

    实测踩过的坑:
      - SPIFFS 崩溃瞬间会留下 0 字节的 jpg, 续号扫描必须跳过它们,
        否则编号会被坏文件占掉, 看着像"漏拍"。
      - 写完不 stat 校验, 你根本不知道这张到底存进去没有。
    """

    def __init__(self, cands, prefix, start_id=0, quality=90):
        self.prefix = prefix
        self.quality = quality
        self.dir = None
        self.reason = "无可用存储"
        for d in cands:
            try:
                os.listdir(d)
                self.dir = d
                break
            except Exception as e:
                self.reason = "%s 不可用(%r)" % (d, e)
        self.saved = 0            # 本次开机后成功存了几张
        self.errors = 0           # 失败次数
        self.next_id = start_id if start_id > 0 else 1
        if self.dir and start_id <= 0:
            self._scan()
        self._free_mb = -1.0
        self.refresh_free()

    # ---------- 内部 ----------
    def _scan(self):
        """扫已有文件的最大编号, 跳过 0 字节坏文件。"""
        mx = 0
        try:
            names = os.listdir(self.dir)
        except Exception:
            return
        plen = len(self.prefix)
        for n in names:
            if not n.startswith(self.prefix) or not n.endswith(".jpg"):
                continue
            try:
                v = int(n[plen:-4])
            except Exception:
                continue
            try:
                if os.stat(self.dir + "/" + n)[6] <= 0:
                    continue          # 坏文件, 不占号
            except Exception:
                continue
            if v > mx:
                mx = v
        self.next_id = mx + 1
        self.saved = mx               # 让屏幕上的计数是个有意义的累计值

    def refresh_free(self):
        if not self.dir:
            self._free_mb = -1.0
            return
        try:
            st = os.statvfs(self.dir)
            self._free_mb = st[0] * st[3] / 1048576.0
        except Exception:
            self._free_mb = -1.0

    # ---------- 对外 ----------
    def log(self, line):
        """往流水文件追加一行。失败绝不抛异常——日志不能影响拍照。"""
        if not SHOT_LOG:
            return
        try:
            f = open(SHOT_LOG, "a")
            f.write(line + "\n")
            f.close()
        except Exception:
            pass

    def free_mb(self):
        return self._free_mb

    def free_gb(self):
        return self._free_mb / 1024.0

    def label(self):
        if not self.dir:
            return "NONE"
        return "SD" if self.dir == "/sd" else "FL"

    def low(self):
        return 0 <= self._free_mb < SHOT_LOW_MB

    def path_for(self, idx):
        return "%s/%s%03d.jpg" % (self.dir, self.prefix, idx)

    def save(self, img):
        """存一张。返回 (路径, None) 或 (None, 错误说明)。"""
        if not self.dir:
            self.errors += 1
            return None, self.reason
        p = self.path_for(self.next_id)
        try:
            img.save(p, quality=self.quality)
        except Exception as e:
            self.errors += 1
            return None, "save异常 %r" % (e,)
        # 立刻验大小 —— 0 字节说明没真写进去, 当场删掉别留垃圾
        try:
            sz = os.stat(p)[6]
        except Exception:
            sz = -1
        if sz <= 0:
            self.errors += 1
            try:
                os.remove(p)
            except Exception:
                pass
            return None, "写入0字节"
        self.next_id += 1
        self.saved += 1
        self.refresh_free()
        return p, None


class Detector(object):
    """自动适配新版 (load/Yolo2) 和旧版 (load_kmodel/init_yolo2) KPU API。"""

    def __init__(self, name, anchor, paths, color):
        self.name = name
        self.color = color
        self.ok = True          # 真检测器
        self.kpu = KPU()
        self.source = load_model(self.kpu, paths, name)
        self.new_api = hasattr(self.kpu, "Yolo2")
        if self.new_api:
            self.yolo = self.kpu.Yolo2()
            self.yolo.init(anchor, THRESHOLD, NMS)
        else:
            self.kpu.init_yolo2(anchor, anchor_num=len(anchor) // 2,
                                img_w=FRAME_W, img_h=FRAME_H,
                                net_w=NET_W, net_h=NET_H,
                                layer_w=10, layer_h=8,
                                threshold=THRESHOLD, nms_value=NMS,
                                classes=1)
        print("[%s] 就绪 (%s API)" % (name, "新版" if self.new_api else "旧版"))

    def run(self, od_img):
        if self.new_api:
            self.kpu.run(od_img)
            boxes = self.yolo.run()
        else:
            self.kpu.run_with_output(od_img)
            boxes = self.kpu.regionlayer_yolo2()
        out = []
        if boxes:
            for b in boxes:
                try:
                    prob = b[5] if len(b) > 5 else 1.0
                except Exception:
                    prob = 1.0
                out.append((b[0], b[1], b[2], b[3], prob))
        return out

    def deinit(self):
        try:
            self.kpu.deinit()
        except Exception:
            pass


class NullDetector(object):
    """
    模型不可用时的替身检测器: 不检测, 只让摄像头画面继续上屏。
    存在的意义是"别把板子弄死"—— 模型坏了也要有画面, 方便判断故障点。
    """

    def __init__(self, name, color):
        self.name = name
        self.color = color
        self.ok = False

    def run(self, od_img):
        return []

    def deinit(self):
        pass


def read_bootfail():
    """读"连续几次开机都没拿到模型"的计数器。文件不存在/内容坏都当 0。"""
    try:
        f = open(BOOTFAIL_PATH, "r")
        try:
            s = f.read().strip()
        finally:
            f.close()
        return int(s) if s else 0
    except Exception:
        return 0


def write_bootfail(n):
    """写计数器。值没变就不写 —— 少擦一次 flash。"""
    if read_bootfail() == n:
        return
    try:
        f = open(BOOTFAIL_PATH, "w")
        try:
            f.write("%d" % n)
        finally:
            f.close()
    except Exception as e:
        print("[自愈] 计数器写入失败(忽略):", repr(e))


def reboot_board():
    """自动重启。machine.reset() 不行就让看门狗超时兜底。

    正常情况【不返回】(复位了); 只有复位发不出去、看门狗也关着时才返回 False。
    """
    try:
        print("[自愈] 调 machine.reset() 重启")
        time.sleep(0.2)
        machine.reset()
        print("[自愈] !! machine.reset() 返回了, 没生效")
    except Exception as e:
        print("[自愈] reset 异常(可能已复位): %r" % (e,))
    if WDT_ENABLE:
        print("[自愈] 交给看门狗超时复位(不再喂狗, 最多 %d ms) ..."
              % WDT_TIMEOUT_MS)
        while True:
            time.sleep(1)
    print("[自愈] 看门狗也关着, 没法自动重启")
    return False


def build_detector():
    """按 MODE 建检测器。

    失败时: 先原地重试 -> 再有限次自动重启 -> 最后才回退预览
    (或按 MODEL_MISSING_FATAL 直接抛错)。
    """
    if MODE == "PREVIEW":
        print("[PREVIEW] 预览模式: 不加载模型, 只出画面")
        return NullDetector("PRE", COLOR_BODY)

    last = None
    for k in range(MODEL_RETRY):
        try:
            if MODE == "BODY":
                det = Detector("BODY", ANCHOR_BODY, BODY_MODEL_PATHS, COLOR_BODY)
            else:
                det = Detector("HEAD", ANCHOR_HEAD, HEAD_MODEL_PATHS, COLOR_HEAD)
            write_bootfail(0)          # 成功 -> 计数器清零, 下次开机从零开始
            return det
        except Exception as e:
            last = e
            print("[模型] 第 %d/%d 次加载失败: %r" % (k + 1, MODEL_RETRY, e))
            gc.collect()               # 失败留下的 KPU 对象要回收, 否则重试几次就没内存
            if k + 1 < MODEL_RETRY:
                time.sleep(MODEL_RETRY_DELAY_S)

    print("[模型] 加载失败(试了 %d 次): %r" % (MODEL_RETRY, last))
    if MODEL_MISSING_FATAL:
        raise last

    if MODEL_AUTO_REBOOT:
        n = read_bootfail() + 1
        if n <= MODEL_MAX_REBOOTS:
            write_bootfail(n)
            print("[自愈] 连续第 %d/%d 次开机没拿到模型, 重启重来 ..."
                  % (n, MODEL_MAX_REBOOTS))
            reboot_board()             # 正常不返回
        else:
            print("[自愈] 已连续 %d 次失败, 放弃重启(防止无限重启), 停在预览模式"
                  % MODEL_MAX_REBOOTS)

    print("[模型] 已回退到预览模式(画面照上, 只是不检测)。"
          "把模型传好再上电即自动恢复。")
    return NullDetector("PRE", COLOR_BODY)


def estimate_dist(h_px):
    """框高(像素) -> 距离(米)。返回 (距离 或 None, 是否可信)。

    针孔模型: D = f * H / h_px。前提是'框高就等于人的真实身高', 所以只对
    标定过身高的人准; 陌生人只能给粗估(成人身高 ±10% 直接变成 ±6% 距离)。
    """
    if not DIST_ENABLE or h_px < 6:
        return None, False
    d = PERSON_H_M * FOCAL_PX / h_px
    if d < DIST_MIN_M or d > DIST_MAX_M:
        return None, False
    return d, True


def est_dist_ground(y_feet):
    """地面法: 用【脚尖所在的像素行】反算地面距离。返回 (距离 或 None, 是否可信)。

    原理: 相机架在已知高度 CAM_H_M, 水平向前是'光轴'。脚尖落在画面第 y_feet 行,
    说明该方向相对光轴往下压了
              beta  = atan((y_feet - CAM_CY) / FOCAL_PX)
    再叠上相机安装俯角
              alpha = CAM_PITCH_DEG + beta
    地面距离就是
              D = CAM_H_M / tan(alpha)

    **全程不需要知道人有多高**, 所以对陌生人一样准。代价:
      - CAM_H_M 必须量准(线性影响结果)
      - 俯角必须准(tools/fit_pitch.py 反算)
      - 脚被画面底边切掉时, '脚尖行'是假的 -> 直接判不可信
      - 人越远 alpha 越小, tan 越敏感 -> 远处误差被放大
    """
    if (not DIST_ENABLE) or CAM_H_M <= 0 or FOCAL_PX <= 0:
        return None, False
    if y_feet >= FRAME_H - CAM_FEET_MARGIN:
        return None, False        # 脚被底边切掉, 这不是真脚尖
    beta = math.atan((y_feet - CAM_CY) / FOCAL_PX)
    alpha = math.radians(CAM_PITCH_DEG) + beta
    if alpha <= 0.03:             # 视线几乎水平 -> 距离趋近无穷, 没意义
        return None, False
    d = CAM_H_M / math.tan(alpha)
    if d < DIST_MIN_M or d > DIST_MAX_M:
        return None, False
    return d, True


def est_dist(b):
    """按 DIST_MODE 选算法。返回 (距离 或 None, 是否可信, 方法代号 G/H)。

    b = (x, y, w, h, prob)。底边 y+h 就是脚尖所在行。
    """
    if DIST_MODE != "HEIGHT":
        d, ok = est_dist_ground(b[1] + b[3])
        if ok or DIST_MODE == "GROUND":
            return d, ok, "G"
    d, ok = estimate_dist(b[3])
    return d, ok, "H"


class Tracker(object):
    """
    最简贪心跟踪：新框与上一帧轨迹按中心点距离配对，配上就沿用 ID。
    K210 上别搞卡尔曼/匈牙利，这个够用且几乎不占内存。
    """

    def __init__(self):
        self.tracks = []
        self.next_id = 1
        self.total_in = 0          # 累计进入人次

    def update(self, boxes):
        old = self.tracks
        used = [False] * len(old)
        new_tracks = []
        results = []

        for b in boxes:
            cx = b[0] + b[2] // 2
            cy = b[1] + b[3] // 2
            best = -1
            best_d2 = TRACK_MAX_DIST * TRACK_MAX_DIST
            for i in range(len(old)):
                if used[i]:
                    continue
                dx = old[i]["cx"] - cx
                dy = old[i]["cy"] - cy
                d2 = dx * dx + dy * dy
                if d2 < best_d2:
                    best_d2 = d2
                    best = i
            if best >= 0:
                used[best] = True
                tid = old[best]["id"]
                hits = old[best]["hits"] + 1
                is_new = False
            else:
                tid = self.next_id
                self.next_id += 1
                hits = 1
                is_new = True
                self.total_in += 1
            # 距离估算 + 跨帧指数平滑（同一个 ID 的距离别跳）
            # 注意: 换了算法(G/H)就别拿旧值平滑, 两套尺子混着会互相拖
            d_new, ok, dmode = est_dist(b)
            d_prev = None
            if best >= 0 and old[best].get("dmode") == dmode:
                d_prev = old[best].get("dist")
            if ok and d_prev:
                dist = d_prev + (d_new - d_prev) * DIST_SMOOTH
            else:
                dist = d_new if ok else None
            new_tracks.append({"id": tid, "cx": cx, "cy": cy, "hits": hits,
                               "lost": 0, "dist": dist, "dmode": dmode})
            results.append((tid, b, is_new, hits, dist, dmode))

        # 短暂丢失的轨迹先留着，别急着发新 ID
        for i in range(len(old)):
            if not used[i]:
                t = old[i]
                t["lost"] += 1
                if t["lost"] <= TRACK_LOST:
                    new_tracks.append(t)

        self.tracks = new_tracks
        return results


def in_zone(b):
    cx = b[0] + b[2] // 2
    cy = b[1] + b[3] // 2
    return (ALERT_X <= cx <= ALERT_X + ALERT_W and
            ALERT_Y <= cy <= ALERT_Y + ALERT_H)


def do_shot(store, img, why):
    """存一张并统一报告 + 记流水。返回 (屏幕提示文字, 是否成功)。"""
    p, err = store.save(img)
    if p:
        name = p.rsplit("/", 1)[-1]
        store.log("%d %s %s ok" % (time.ticks_ms() // 1000, name, why))
        return "SAVED " + name + " [" + why + "]", True
    store.log("%d - %s FAIL %s" % (time.ticks_ms() // 1000, why, err))
    return "SHOT FAIL " + err, False


def setup_shot_key():
    """注册 BOOT 键。照官方 demo 抄: GPIOHS1, 【不要】加 force=True。
    实测加了 force=True 会在 ~20s 后整板硬复位。"""
    if not (SHOT_ENABLE and SHOT_KEY_ENABLE):
        return None
    try:
        fm.register(SHOT_KEY_IO, fm.fpioa.GPIOHS1)
        k = GPIO(GPIO.GPIOHS1, GPIO.IN, GPIO.PULL_UP)
        print("[SHOT] 按键就绪: IO%d (按下=0)" % SHOT_KEY_IO)
        return k
    except Exception as e:
        print("[SHOT] 按键初始化失败(忽略, 定时/告警拍照仍可用):", repr(e))
        return None


def apply_cam_profile():
    """按 CAM_KIND / sensor.get_id() 选定镜头参数，覆盖方向与标定全局量。

    必须在 sensor.reset() 之后、set_hmirror/set_vflip 之前调用。
    返回实际选中的型号名。
    """
    global CAM_NAME, HMIRROR, VFLIP, FOCAL_PX, CAM_CY
    sid = None
    kind = CAM_KIND
    if kind == "AUTO":
        try:
            sid = sensor.get_id()
        except Exception as e:
            print("[CAM] !! get_id 失败(按未知处理): %r" % (e,))
        kind = None
        for name, p in CAM_PROFILES.items():
            if sid in p["ids"]:
                kind = name
                break
        if kind is None:
            kind = "GC2145"
            print("[CAM] !! 未登记的 sensor id=%r, 暂用 GC2145 参数" % (sid,))
    elif kind not in CAM_PROFILES:
        print("[CAM] !! CAM_KIND=%r 不存在, 回退 GC2145" % (kind,))
        kind = "GC2145"

    p = CAM_PROFILES[kind]
    CAM_NAME = p["label"]
    HMIRROR  = bool(p["hmirror"])
    VFLIP    = bool(p["vflip"])
    FOCAL_PX = p["focal_px"]
    CAM_CY   = p["cam_cy"]
    print("[CAM] %s | id=%r mirror=%d vflip=%d f=%.1f cy=%d"
          % (CAM_NAME, sid, HMIRROR, VFLIP, FOCAL_PX, CAM_CY))
    if FOCAL_PX <= 0:
        print("[CAM] !! 该镜头未标定(focal_px=0): 只做检测/跟随, 不出距离")
        print("[CAM]    标好后填 CAM_PROFILES['%s'] 的 focal_px / cam_cy" % kind)
    return kind


def main():
    # ---------- 第 0 步: 先武装看门狗（越早越好）----------
    wdt = None
    if WDT_ENABLE:
        try:
            wdt = machine.WDT(0, WDT_TIMEOUT_MS)
            print("[WDT] 已武装 %d ms" % WDT_TIMEOUT_MS)
        except Exception as e:
            print("[WDT] 武装失败(忽略继续):", repr(e))
            wdt = None

    # ---------- 第 0 步: 释放 main.py 留下的显示资源 ----------
    # 顺序关键: 模型要 1.4MB 连续系统堆, 必须在 lcd/sensor 分配显存之前加载
    try:
        lcd.deinit()
    except Exception:
        pass
    try:
        sensor.run(0)
    except Exception:
        pass
    gc.collect()

    # ---------- 第 1 步: 加载模型（内存最充裕时）----------
    print("=" * 48)
    print(" 模式:%s 跟踪:%s 告警:%s 内存:%d"
          % (MODE, TRACK_ENABLE, ALERT_ENABLE, gc.mem_free()))
    print("=" * 48)

    det = build_detector()
    if wdt:
        wdt.feed()
    gc.collect()

    # ---------- 第 1.5 步: 存储 + 按键（模型就位后, 开屏之前）----------
    store = None
    key = None
    if SHOT_ENABLE:
        store = ShotStore(SHOT_DIRS, SHOT_PREFIX,
                          SHOT_START_ID, SHOT_QUALITY)
        if store.dir:
            print("[SHOT] 存储: %s  起始编号 %d  可用 %.1f MB  前缀 %s"
                  % (store.dir, store.next_id, store.free_mb(), SHOT_PREFIX))
            store.log("# boot dir=%s next=%d free=%.1fMB"
                      % (store.dir, store.next_id, store.free_mb()))
            if store.low():
                print("[SHOT] !! 剩余空间不足 %dMB, 请清理卡" % SHOT_LOW_MB)
        else:
            print("[SHOT] !! 没有可用存储, 拍照功能关闭:", store.reason)
        key = setup_shot_key()
    if wdt:
        wdt.feed()
    gc.collect()

    # ---------- 第 1.6 步: 底盘跟随串口（扩展口, TXD=IO8 / RXD=IO6）----------
    fol = None
    fol_st = None
    if FOLLOW_ENABLE:
        try:
            fol = follow_link.FollowLink(FOLLOW_UART_ID, FOLLOW_TX_IO,
                                         FOLLOW_RX_IO, FOLLOW_BAUD,
                                         FOLLOW_MIRROR_REPL)
            fol_st = follow_link.FollowState(FOLLOW_LOST_FRAMES)
            print("[FOL] 跟随串口已开: UART%d TX=IO%d RX=IO%d @%d"
                  % (FOLLOW_UART_ID, FOLLOW_TX_IO, FOLLOW_RX_IO, FOLLOW_BAUD))
        except Exception as e:
            print("[FOL] !! 串口初始化失败, 跟随功能关闭:", repr(e))
            fol = None
    if wdt:
        wdt.feed()
    gc.collect()

    # ---------- 第 2 步: 模型就位后再开摄像头和屏幕 ----------
    lcd.init()
    sensor.reset()
    apply_cam_profile()          # 双镜头: 按 sensor.get_id() 套方向/标定
    if HMIRROR:
        sensor.set_hmirror(1)
    if VFLIP:
        sensor.set_vflip(1)
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)
    sensor.skip_frames(time=1000)
    clock = time.clock()

    od_img = image.Image(size=(NET_W, NET_H))
    tracker = Tracker() if TRACK_ENABLE else None

    print("开始实时检测，Ctrl-C / 停止键退出")
    frame = 0
    zone_hits = 0
    cooldown = 0
    hb_t0 = time.ticks_ms()
    hb_last = hb_t0
    boot_ms = hb_t0          # 开机头几秒在屏幕上提示一下怎么拍照
    key_down = False
    # 注意: 必须初始化成"当前时刻"而不是 0。
    # 设 0 的话 ticks_diff(now, 0) = now 必然大于间隔, 定时连拍会【第一帧就抢拍一张】。
    last_shot_ms = time.ticks_ms()
    pend_alarm_shot = False
    shot_msg = ""
    shot_msg_ms = 0
    fol_seq = 0
    fol_last = time.ticks_ms()
    fol_hud = ""
    if HEARTBEAT_SEC > 0:
        try:
            os.remove(HB_PATH)
        except Exception:
            pass

    try:
        while True:
            frame += 1
            clock.tick()
            img = sensor.snapshot()

            # ---------- 判定本帧要不要拍照 ----------
            # 必须在"画框之前"定下来: 这样才能决定是存干净帧还是存带框帧。
            snap_req = False
            snap_why = ""
            if store is not None and store.dir:
                if pend_alarm_shot:
                    pend_alarm_shot = False
                    snap_req = True
                    snap_why = "ALARM"
                if not snap_req and key is not None:
                    v = key.value()
                    if v == 0:
                        if (not key_down and
                                time.ticks_diff(time.ticks_ms(),
                                                last_shot_ms) > SHOT_DEBOUNCE_MS):
                            snap_req = True
                            snap_why = "KEY"
                        key_down = True
                    else:
                        key_down = False
                if (not snap_req and SHOT_EVERY_SEC > 0 and
                        time.ticks_diff(time.ticks_ms(),
                                        last_shot_ms) >= SHOT_EVERY_SEC * 1000):
                    snap_req = True
                    snap_why = "TIMER"

            # 要存干净原图的话, 趁现在还没画东西, 先存
            if snap_req and not SHOT_WITH_HUD:
                shot_msg, ok_shot = do_shot(store, img, snap_why)
                last_shot_ms = time.ticks_ms()
                shot_msg_ms = last_shot_ms
                print("[SHOT] %s" % shot_msg)
                if not ok_shot:
                    snap_req = False

            od_img.draw_image(img, 0, 0)
            od_img.pix_to_ai()
            boxes = det.run(od_img)

            # ---------- 跟踪 ----------
            if tracker is not None:
                items = tracker.update(boxes)
            else:
                items = []
                for i, b in enumerate(boxes):
                    d_, ok_, dm_ = est_dist(b)
                    items.append((i + 1, b, True, 0,
                                  d_ if ok_ else None, dm_))

            # ---------- 告警区框 ----------
            if ALERT_ENABLE:
                img.draw_rectangle(ALERT_X, ALERT_Y, ALERT_W, ALERT_H,
                                   color=COLOR_ZONE, thickness=1)

            # ---------- 画框 & 判定区内 ----------
            zone_now = 0
            for tid, b, is_new, hits, dist, dmode in items:
                hot = ALERT_ENABLE and in_zone(b)
                if hot:
                    zone_now += 1
                color = COLOR_ALERT if hot else det.color
                img.draw_rectangle(b[0], b[1], b[2], b[3],
                                   color=color, thickness=2)
                ly = b[1] - 14 if b[1] > 16 else b[1] + 2
                lbl = "#%d %s%d%%" % (tid, det.name[0], b[4] * 100)
                if dist:
                    if dmode == "G":
                        lbl += " %.1fG" % dist     # G = 地面法, 看脚尖
                    elif b[1] <= 1:
                        # 框顶贴画面边 -> 头顶被切掉, 框高偏小, 距离被高估
                        lbl += ">%.1fm" % dist
                    else:
                        lbl += " %.1fm" % dist
                img.draw_string(b[0], ly, lbl, color=color, scale=1.0)
                img.draw_cross(b[0] + b[2] // 2, b[1] + b[3] // 2,
                               color=color, size=5, thickness=1)

            # ---------- 告警逻辑 ----------
            if ALERT_ENABLE:
                if zone_now > 0:
                    zone_hits += 1
                else:
                    zone_hits = 0
                if cooldown > 0:
                    cooldown -= 1
                if zone_hits >= ALERT_FRAMES and cooldown == 0:
                    print("ALARM person_in_zone n=%d frame=%d" % (zone_now, frame))
                    img.draw_string(ALERT_X, ALERT_H - 16, "ALARM",
                                    color=COLOR_ALERT, scale=1.5)
                    cooldown = ALERT_COOLDOWN
                    if SHOT_ON_ALARM:
                        # 推迟到下一帧开头拍, 那时还没画东西, 逻辑更干净
                        pend_alarm_shot = True

            # ---------- HUD ----------
            now = len(items)
            total = tracker.total_in if tracker else now
            if SHOW_FPS:
                hud_text(img, 0, 0, "%2.1ffps" % clock.fps(),
                         COLOR_TEXT, 2.0)
            hud_text(img, 148, 0, "N=%d T=%d" % (now, total),
                     COLOR_TEXT, 2.0)

            # 拍照状态行
            if store is not None:
                if store.dir:
                    if store.low():
                        hud_text(img, 0, 18, "%s LOW %.0fMB"
                                 % (store.label(), store.free_mb()),
                                 COLOR_FAIL, 1.5)
                    else:
                        hud_text(img, 0, 18, "%s SHOT %d  %.1fG"
                                 % (store.label(), store.next_id - 1,
                                    store.free_gb()),
                                 COLOR_TEXT, 1.5)
                else:
                    hud_text(img, 0, 18, "NO STORAGE", COLOR_FAIL, 1.5)

            # ---------- 串口上报 ----------
            if SERIAL_REPORT and (frame % REPORT_EVERY == 0):
                if not det.ok:
                    print("PREVIEW no_model frame=%d" % frame)
                elif not items:
                    print("DET none | total=%d" % total)
                else:
                    parts = []
                    for tid, b, is_new, hits, dist, dmode in items:
                        cx = b[0] + b[2] // 2
                        side = "L" if cx < 107 else ("R" if cx > 213 else "C")
                        parts.append("#%d x%d,y%d,w%d,h%d,%.2f,%s%s%s"
                                     % (tid, b[0], b[1], b[2], b[3], b[4], side,
                                        ",HOT" if (ALERT_ENABLE and in_zone(b)) else "",
                                        (",d%.1f%s" % (dist, dmode))
                                        if dist else ",d?"))
                    print("DET n=%d total=%d | %s"
                          % (len(items), total, " ; ".join(parts)))

            # ---------- 底盘跟随链路（扩展口 UART, 协议见 docs/）----------
            if fol is not None:
                fol.poll()          # 收底盘回传, 非阻塞, 有行会限速打印 [CHAS]
                if time.ticks_diff(time.ticks_ms(), fol_last) >= FOLLOW_PERIOD_MS:
                    fol_last = time.ticks_ms()
                    st, tid_f, err_px, dist_f = fol_st.update(
                        items, img.width() // 2, det.ok)
                    if st == "L":
                        err_deg = math.degrees(math.atan2(err_px, CAM_FX))
                    else:
                        err_deg = 0.0
                    frm = follow_link.build_frame(fol_seq, st, tid_f,
                                                  err_deg, dist_f)
                    fol_seq = (fol_seq + 1) % 10000
                    n = fol.send(frm)
                    if n <= 0 and frame % 100 == 0:
                        print("[FOL] !! UART write 返回 %d (连续异常 %d)"
                              % (n, fol.wr_errs))
                    if FOLLOW_MIRROR_REPL:
                        print("[FOL>]", frm.strip())
                    fol_hud = "FOL:%s id%s %+.1fd" % (st, tid_f, err_deg)
            if fol is not None and fol_hud:
                # 每帧都要画, img 是新帧, 上一帧画的不保留
                img.draw_string(0, 224, fol_hud, color=COLOR_TEXT, scale=1.0)

            # ---------- 心跳 ----------
            if HEARTBEAT_SEC > 0 and time.ticks_diff(
                    time.ticks_ms(), hb_last) >= HEARTBEAT_SEC * 1000:
                hb_last = time.ticks_ms()
                try:
                    hf = open(HB_PATH, "a")
                    hf.write("%d %d %d\n" % (frame,
                            time.ticks_diff(time.ticks_ms(), hb_t0) // 1000,
                            total))
                    hf.close()
                except Exception:
                    pass

            # ---------- 真正落盘（存带框带字的这一帧）----------
            if snap_req and SHOT_WITH_HUD:
                shot_msg, ok_shot = do_shot(store, img, snap_why)
                last_shot_ms = time.ticks_ms()
                shot_msg_ms = last_shot_ms
                print("[SHOT] %s" % shot_msg)

            # 没有可用模型时, 画面正中打个横幅, 别让人以为是板子挂了
            if not det.ok:
                img.draw_string(20, 108, "NO MODEL",
                                color=COLOR_ALERT, scale=2.0)

            # 开机头 10 秒提示一下: 按 BOOT 键就是拍一张
            if (store is not None and store.dir and
                    time.ticks_diff(time.ticks_ms(), boot_ms) < 10000):
                hud_text(img, 0, 34, "KEY=SHOT", COLOR_SHOT, 1.0)

            # 拍照结果提示 —— 故意放在存盘之后画, 所以它只出现在屏幕上, 不进照片
            if shot_msg:
                age = time.ticks_diff(time.ticks_ms(), shot_msg_ms)
                if age < SHOT_TOAST_MS:
                    hud_text(img, 2, 206, shot_msg,
                             COLOR_SHOT if shot_msg.startswith("SAVED")
                             else COLOR_FAIL, 1.5)
                    if SHOT_FLASH and age < 250:
                        img.draw_rectangle(0, 0, FRAME_W, FRAME_H,
                                           color=COLOR_SHOT, thickness=3)

            if wdt:
                wdt.feed()
            lcd.display(img)
            if frame % 4 == 0:
                gc.collect()

    except KeyboardInterrupt:
        print("用户停止")
        if wdt:
            try:
                wdt.stop()
                print("[WDT] 已关闭，板子停在 REPL")
            except Exception:
                pass
    except Exception as e:
        # 循环里任何 Python 层异常都不许静默死掉:
        # 直接重启板子，main.py 重跑，LCD 自动恢复。
        print("主循环异常，重启板子:", repr(e))
        try:
            det.deinit()
        except Exception:
            pass
        time.sleep_ms(300)
        machine.reset()
    finally:
        det.deinit()
        gc.collect()
        if store is not None:
            print("[SHOT] 本次共存 %d 张, 失败 %d 次"
                  % (store.saved, store.errors))


# 板上执行 /sd/main.py 或 /flash/main.py 时 __name__ == "__main__"，行为不变。
# 加守卫是为了让 PC 端（单元测试/静态检查）可以 import 本文件而不触发整机启动。
if __name__ == "__main__":
    main()
