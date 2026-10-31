# -*- coding: utf-8 -*-
"""
ScreenScan RPA 智能工作流状态机 (工业级健壮版)
特性：
1. 智能视窗自适应引擎 (根据分辨率自适应布局，支持动态滚动与折叠，零截断)
2. 多图模板匹配与局部 ROI 缩放扫描 (支持多图候选独立流转，动态缓存与全屏/局部 ROI 扫描支持)
3. 智能多变体文字 OCR (基于 Windows UWP 原生 WinOCR 引擎，四重预处理变体与精确字词边界计算)
4. 状态机心跳监控看门狗 (监控执行线程心跳状态并在假死/阻塞时及时告警保护)
5. 拟人化输入与前台激活 (SendInput 结合鼠标轻微扰动与窗体自卫防误点保护)
6. 多热键监控 (F7 即时暂停/恢复、F8 启动、F9 停止)
7. 多动作并发冲突仲裁系统 (依据 P1~P99 权重优先级决出唯一执行者，支持 Dry-Run 仿真演练与执行上限)
"""

import sys
import os
import time
import random
import threading
import ctypes
import json
import subprocess

# Windows 高 DPI 适配
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk, ImageGrab
import numpy as np
import cv2
import pyautogui

WINOCR_AVAILABLE = False
WINOCR_ERROR = ""
try:
    import winocr
    WINOCR_AVAILABLE = True
except Exception as e:
    WINOCR_AVAILABLE = False
    WINOCR_ERROR = str(e)

KEYBOARD_AVAILABLE = False
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except Exception:
    KEYBOARD_AVAILABLE = False

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.04

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p)
    ]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def activate_target_window(x, y):
    try:
        user32 = ctypes.windll.user32
        pt = POINT(int(x), int(y))
        hwnd = user32.WindowFromPoint(pt)
        if not hwnd:
            return None
        root_hwnd = user32.GetAncestor(hwnd, 2)
        target = root_hwnd if root_hwnd else hwnd
        user32.ShowWindow(target, 9)
        
        curr_tid = user32.GetCurrentThreadId()
        target_tid = user32.GetWindowThreadProcessId(target, None)
        if curr_tid != target_tid:
            user32.AttachThreadInput(curr_tid, target_tid, True)
            user32.SetForegroundWindow(target)
            user32.BringWindowToTop(target)
            user32.AttachThreadInput(curr_tid, target_tid, False)
        else:
            user32.SetForegroundWindow(target)
            user32.BringWindowToTop(target)
        return hwnd
    except Exception:
        return None

class ScreenSnipper:
    def __init__(self, parent, callback, return_bbox=False):
        self.callback = callback
        self.return_bbox = return_bbox
        self.top = tk.Toplevel(parent)
        self.top.attributes('-alpha', 0.3)
        self.top.attributes('-fullscreen', True)
        self.top.config(cursor="cross")

        self.canvas = tk.Canvas(self.top, cursor="cross", bg="grey")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Escape>", lambda e: self.top.destroy())

        self.start_x = None
        self.start_y = None
        self.rect = None

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='#10b981', width=2)

    def on_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        end_x = event.x
        end_y = event.y
        self.top.destroy()

        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        if (x2 - x1) > 5 and (y2 - y1) > 5:
            bbox = (x1, y1, x2, y2)
            if self.return_bbox:
                self.callback(bbox)
                return
            time.sleep(0.1)
            img = ImageGrab.grab(bbox=bbox)
            save_path = os.path.join(os.getcwd(), f"snip_{int(time.time())}.png")
            img.save(save_path)
            self.callback(save_path)


class RuleDialog(tk.Toplevel):
    """智能防裁剪可滚动步骤编辑对话框：支持多图候选缩略图预览、独立优先级与专属跳转”"""
    def __init__(self, parent, rule=None, all_rules=None, on_save=None):
        super().__init__(parent)
        self.title("配置智能工作流步骤 (自适应视窗 - 支持多图独立优先级与预览)")
        
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(880, int(sw * 0.90))
        h = min(720, int(sh * 0.90))
        self.geometry(f"{w}x{h}")
        self.minsize(620, 480)
        self.configure(bg="#0f172a")

        self.all_rules = all_rules or []
        self.rule = rule if rule else {
            "id": f"r_{int(time.time()*1000)}",
            "name": f"智能步骤-{len(self.all_rules)+1}",
            "priority": 1,
            "enabled": True,
            "type": "image",
            "target": "",
            "confidence": 0.70,
            "offset_x": 0,
            "offset_y": 0,
            "action": "click",
            "action_param": "",
            "cooldown": 0.0,
            "lock_exclusive": 0.0,
            "next_mode": "loop",
            "next_target_id": "",
            "timeout_target_id": "",
            "next_timeout": 20.0,
            "humanize": True,
            "candidates": []
        }
        self.candidates = list(self.rule.get("candidates") or [])
        self.img_tk_cache = [] # 缓存 ImageTk.PhotoImage 避免 GC 垃圾回收导致图片消失
        self.on_save = on_save
        self.create_widgets()

    def create_widgets(self):
        # 底部固定按钮条（永远在可视区域内，绝不受小窗影响）
        bottom_bar = tk.Frame(self, bg="#1e293b", padx=16, pady=10)
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        tk.Button(bottom_bar, text="✔ 保存当前步骤", command=self.save, bg="#10b981", fg="white", font=("Microsoft YaHei UI", 10, "bold"), padx=22, pady=6, relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(bottom_bar, text="取消", command=self.destroy, bg="#334155", fg="#cbd5e1", font=("Microsoft YaHei UI", 10), padx=16, pady=6, relief=tk.FLAT).pack(side=tk.LEFT)
        tk.Label(bottom_bar, text="💡 提示: 同动作可放入多图片并独立设置优先级 (最高优先胜出)", bg="#1e293b", fg="#94a3b8", font=("Microsoft YaHei UI", 8)).pack(side=tk.RIGHT)

        # 中部自适应可滚动容器
        canvas = tk.Canvas(self, bg="#0f172a", highlightthickness=0)
        v_scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#0f172a", padx=16, pady=12)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_frame_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind('<Configure>', lambda event: canvas.itemconfig(canvas_frame_id, width=event.width))
        canvas.configure(yscrollcommand=v_scrollbar.set)

        # 鼠标滚轮绑定支持
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        main_frame = scrollable_frame

        # 1. 触发检测
        sec_base = tk.LabelFrame(main_frame, text=" 1. 触发检测条件 (多候选图片与智能泛化) ", bg="#0f172a", fg="#38bdf8", font=("Microsoft YaHei UI", 10, "bold"), padx=12, pady=8)
        sec_base.pack(fill=tk.X, pady=(0, 8))

        r1 = tk.Frame(sec_base, bg="#0f172a")
        r1.pack(fill=tk.X, pady=3)
        tk.Label(r1, text="步骤名称:", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w").pack(side=tk.LEFT)
        self.name_entry = tk.Entry(r1, width=28, bg="#1e293b", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 9))
        self.name_entry.insert(0, self.rule["name"])
        self.name_entry.pack(side=tk.LEFT, padx=(0, 10))

        self.enabled_var = tk.BooleanVar(value=self.rule.get("enabled", True))
        tk.Checkbutton(r1, text="启用步骤", variable=self.enabled_var, bg="#0f172a", fg="#34d399", selectcolor="#1e293b", font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))

        self.humanize_var = tk.BooleanVar(value=self.rule.get("humanize", True))
        tk.Checkbutton(r1, text="拟人微操(±2px)", variable=self.humanize_var, bg="#0f172a", fg="#a78bfa", selectcolor="#1e293b", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)

        r2 = tk.Frame(sec_base, bg="#0f172a")
        r2.pack(fill=tk.X, pady=3)
        tk.Label(r2, text="检测类型:", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w").pack(side=tk.LEFT)
        self.type_var = tk.StringVar(value=self.rule["type"])
        type_combo = ttk.Combobox(r2, textvariable=self.type_var, values=[
            "image (屏幕出现目标图片截图 - 支持多图候选)",
            "text (屏幕出现指定文字关键词 OCR - 支持多词模糊)",
            "image_vanish (目标图片在屏幕消失时触发)",
            "color (指定坐标变为特定颜色)",
            "timer (定时无条件自动循环)"
        ], state="readonly", width=42, font=("Microsoft YaHei UI", 9))
        type_combo.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)
        type_combo.bind("<<ComboboxSelected>>", self.on_type_change)

        self.target_frame = tk.Frame(sec_base, bg="#0f172a")
        self.target_frame.pack(fill=tk.X, pady=3)
        self.lbl_target = tk.Label(self.target_frame, text="目标内容/图片:", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w")
        self.lbl_target.pack(side=tk.LEFT)

        self.target_entry = tk.Entry(self.target_frame, width=32, bg="#1e293b", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 9))
        self.target_entry.insert(0, str(self.rule["target"]))
        self.target_entry.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)

        self.btn_browse = tk.Button(self.target_frame, text="📁 批量选择图片", command=self.browse_image, bg="#3b82f6", fg="white", relief=tk.FLAT, padx=8, font=("Microsoft YaHei UI", 9, "bold"))
        self.btn_browse.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_snip = tk.Button(self.target_frame, text="📸 框选屏幕", command=self.start_snip, bg="#8b5cf6", fg="white", relief=tk.FLAT, padx=8, font=("Microsoft YaHei UI", 9, "bold"))
        self.btn_snip.pack(side=tk.LEFT)

        self.conf_frame = tk.Frame(sec_base, bg="#0f172a")
        self.conf_frame.pack(fill=tk.X, pady=3)
        tk.Label(self.conf_frame, text="相似度阈值:", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w").pack(side=tk.LEFT)
        self.conf_scale = tk.Scale(self.conf_frame, from_=0.40, to=0.98, resolution=0.01, orient=tk.HORIZONTAL, bg="#0f172a", fg="white", highlightbackground="#0f172a", length=220)
        self.conf_scale.set(float(self.rule.get("confidence", 0.70)))
        self.conf_scale.pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(self.conf_frame, text="(自适应0.85x~1.15x多尺度)", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT)

        r_prio = tk.Frame(sec_base, bg="#0f172a")
        r_prio.pack(fill=tk.X, pady=3)
        tk.Label(r_prio, text="并发仲裁优先级:", bg="#0f172a", fg="#f59e0b", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w").pack(side=tk.LEFT)
        self.priority_scale = tk.Scale(r_prio, from_=1, to=99, orient=tk.HORIZONTAL, bg="#0f172a", fg="#f59e0b", highlightbackground="#0f172a", length=140)
        self.priority_scale.set(int(self.rule.get("priority", 1)))
        self.priority_scale.pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(r_prio, text="P1(最高)", command=lambda: self.priority_scale.set(1), bg="#ef4444", fg="white", font=("Microsoft YaHei UI", 8, "bold"), relief=tk.FLAT, padx=3).pack(side=tk.LEFT, padx=1)
        tk.Button(r_prio, text="P2", command=lambda: self.priority_scale.set(2), bg="#f59e0b", fg="black", font=("Microsoft YaHei UI", 8, "bold"), relief=tk.FLAT, padx=3).pack(side=tk.LEFT, padx=1)
        tk.Button(r_prio, text="P3", command=lambda: self.priority_scale.set(3), bg="#3b82f6", fg="white", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=3).pack(side=tk.LEFT, padx=1)
        tk.Button(r_prio, text="P5", command=lambda: self.priority_scale.set(5), bg="#475569", fg="white", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=3).pack(side=tk.LEFT, padx=1)
        tk.Label(r_prio, text="(1最高, 同屏多步骤时数字小的优先)", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=4)

        # 1.5 多候选图片独立优先级与缩略图管理卡片
        self.sec_cands = tk.LabelFrame(main_frame, text=" 🖼️ 同动作多候选图片列表 (支持缩略图预览与独立优先级) ", bg="#0f172a", fg="#a78bfa", font=("Microsoft YaHei UI", 10, "bold"), padx=12, pady=8)
        self.sec_cands.pack(fill=tk.X, pady=(0, 8))

        cand_top_bar = tk.Frame(self.sec_cands, bg="#0f172a")
        cand_top_bar.pack(fill=tk.X, pady=(0, 6))
        tk.Label(cand_top_bar, text="💡 每张图片均独立识别与排序，优先级最高者优先执行：", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT)
        tk.Button(cand_top_bar, text="➕ 添加候选图片", command=self.add_candidate, bg="#8b5cf6", fg="white", font=("Microsoft YaHei UI", 8, "bold"), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.RIGHT, padx=2)
        tk.Button(cand_top_bar, text="📁 选择多张文件", command=self.browse_multiple_candidates, bg="#3b82f6", fg="white", font=("Microsoft YaHei UI", 8, "bold"), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.RIGHT, padx=2)

        self.cands_container = tk.Frame(self.sec_cands, bg="#0f172a")
        self.cands_container.pack(fill=tk.X)

        # 2. 响应动作
        sec_act = tk.LabelFrame(main_frame, text=" 2. 默认响应动作设置 (未独立设置动作的图片使用此配置) ", bg="#0f172a", fg="#10b981", font=("Microsoft YaHei UI", 10, "bold"), padx=12, pady=8)
        sec_act.pack(fill=tk.X, pady=(0, 8))

        a1 = tk.Frame(sec_act, bg="#0f172a")
        a1.pack(fill=tk.X, pady=3)
        tk.Label(a1, text="动作类型:", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w").pack(side=tk.LEFT)
        self.action_var = tk.StringVar(value=self.rule["action"])
        act_combo = ttk.Combobox(a1, textvariable=self.action_var, values=[
            "click (鼠标左键单击目标中心 - 真实穿透)",
            "double_click (鼠标左键双击)",
            "right_click (鼠标右键点击)",
            "hover (鼠标移动至目标悬停)",
            "scroll_down (向下滚动鼠标滚轮)",
            "scroll_up (向上滚动鼠标滚轮)",
            "press_enter (点击后按 Enter 回车)",
            "hotkey (执行组合快捷键)",
            "type_text (点击目标并输入文本)",
            "sound_alarm (播放蜂鸣警报音)",
            "take_screenshot (自动截图留存证据)"
        ], state="readonly", width=40, font=("Microsoft YaHei UI", 9))
        act_combo.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)
        act_combo.bind("<<ComboboxSelected>>", self.on_action_change)

        self.act_param_frame = tk.Frame(sec_act, bg="#0f172a")
        self.act_param_frame.pack(fill=tk.X, pady=3)
        self.lbl_act_param = tk.Label(self.act_param_frame, text="参数内容:", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w")
        self.lbl_act_param.pack(side=tk.LEFT)
        self.act_param_entry = tk.Entry(self.act_param_frame, width=32, bg="#1e293b", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 9))
        self.act_param_entry.insert(0, str(self.rule.get("action_param", "")))
        self.act_param_entry.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        self.lbl_param_hint = tk.Label(self.act_param_frame, text="", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 8))
        self.lbl_param_hint.pack(side=tk.LEFT)

        a2 = tk.Frame(sec_act, bg="#0f172a")
        a2.pack(fill=tk.X, pady=3)
        tk.Label(a2, text="点击坐标偏移:", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w").pack(side=tk.LEFT)
        tk.Label(a2, text="X:", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.ox_entry = tk.Entry(a2, width=5, bg="#1e293b", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 9))
        self.ox_entry.insert(0, str(self.rule.get("offset_x", 0)))
        self.ox_entry.pack(side=tk.LEFT, padx=(2, 8))

        tk.Label(a2, text="Y:", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.oy_entry = tk.Entry(a2, width=5, bg="#1e293b", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 9))
        self.oy_entry.insert(0, str(self.rule.get("offset_y", 0)))
        self.oy_entry.pack(side=tk.LEFT, padx=(2, 8))

        # 3. 智能流转
        sec_flow = tk.LabelFrame(main_frame, text=" 3. 智能工作流转与决策树 (成功跳转 / 超时自愈) ", bg="#0f172a", fg="#a855f7", font=("Microsoft YaHei UI", 10, "bold"), padx=12, pady=8)
        sec_flow.pack(fill=tk.X, pady=(0, 8))

        fl1 = tk.Frame(sec_flow, bg="#0f172a")
        fl1.pack(fill=tk.X, pady=3)
        tk.Label(fl1, text="流转去向:", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w").pack(side=tk.LEFT)
        
        self.next_mode_var = tk.StringVar(value=self.rule.get("next_mode", "loop"))
        flow_combo = ttk.Combobox(fl1, textvariable=self.next_mode_var, values=[
            "loop (默认自由全规则循环)",
            "sequence (顺序流转到下一步)",
            "jump (成功命中后：指定跳转到下一个特定步骤)",
            "stop (流程终点：执行完本动作后自动终止脚本)"
        ], state="readonly", width=38, font=("Microsoft YaHei UI", 9))
        flow_combo.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)
        flow_combo.bind("<<ComboboxSelected>>", self.on_flow_mode_change)

        self.jump_target_frame = tk.Frame(sec_flow, bg="#0f172a")
        self.jump_target_frame.pack(fill=tk.X, pady=3)
        tk.Label(self.jump_target_frame, text="命中后下一步:", bg="#0f172a", fg="#f59e0b", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w").pack(side=tk.LEFT)
        
        target_options = ["(不跳转/顺延下一步)"]
        self.target_id_map = {"(不跳转/顺延下一步)": ""}
        for r in self.all_rules:
            if r["id"] != self.rule["id"]:
                label = f"{r['name']} ({r.get('type')})"
                target_options.append(label)
                self.target_id_map[label] = r["id"]

        current_selected_label = "(不跳转/顺延下一步)"
        for lbl_name, r_id in self.target_id_map.items():
            if r_id == self.rule.get("next_target_id"):
                current_selected_label = lbl_name
                break

        self.jump_combo_var = tk.StringVar(value=current_selected_label)
        self.jump_combo = ttk.Combobox(self.jump_target_frame, textvariable=self.jump_combo_var, values=target_options, state="readonly", width=30, font=("Microsoft YaHei UI", 9))
        self.jump_combo.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)

        self.timeout_target_frame = tk.Frame(sec_flow, bg="#0f172a")
        self.timeout_target_frame.pack(fill=tk.X, pady=3)
        tk.Label(self.timeout_target_frame, text="超时兜底动作:", bg="#0f172a", fg="#f43f5e", font=("Microsoft YaHei UI", 9, "bold"), width=11, anchor="w").pack(side=tk.LEFT)
        
        timeout_options = ["(不处理/继续等待)"]
        self.timeout_id_map = {"(不处理/继续等待)": ""}
        for r in self.all_rules:
            if r["id"] != self.rule["id"]:
                label = f"{r['name']} ({r.get('type')})"
                timeout_options.append(label)
                self.timeout_id_map[label] = r["id"]

        current_timeout_label = "(不处理/继续等待)"
        for lbl_name, r_id in self.timeout_id_map.items():
            if r_id == self.rule.get("timeout_target_id"):
                current_timeout_label = lbl_name
                break

        self.timeout_combo_var = tk.StringVar(value=current_timeout_label)
        self.timeout_combo = ttk.Combobox(self.timeout_target_frame, textvariable=self.timeout_combo_var, values=timeout_options, state="readonly", width=22, font=("Microsoft YaHei UI", 9))
        self.timeout_combo.pack(side=tk.LEFT, padx=(0, 6))

        tk.Label(self.timeout_target_frame, text="超时(秒):", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.timeout_entry = tk.Entry(self.timeout_target_frame, width=5, bg="#1e293b", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 9))
        self.timeout_entry.insert(0, str(self.rule.get("next_timeout", 20.0)))
        self.timeout_entry.pack(side=tk.LEFT, padx=(2, 4))

        # 4. 时序与冷却
        sec_ctrl = tk.LabelFrame(main_frame, text=" 4. 动作时序与冷却 ", bg="#0f172a", fg="#f59e0b", font=("Microsoft YaHei UI", 10, "bold"), padx=12, pady=8)
        sec_ctrl.pack(fill=tk.X, pady=(0, 8))

        c1 = tk.Frame(sec_ctrl, bg="#0f172a")
        c1.pack(fill=tk.X, pady=3)
        tk.Label(c1, text="动作冷却(秒):", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.cooldown_entry = tk.Entry(c1, width=6, bg="#1e293b", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 9))
        self.cooldown_entry.insert(0, str(self.rule.get("cooldown", 0.0)))
        self.cooldown_entry.pack(side=tk.LEFT, padx=(4, 15))

        tk.Label(c1, text="独占锁定(秒):", bg="#0f172a", fg="#f59e0b", font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT)
        self.lock_entry = tk.Entry(c1, width=6, bg="#1e293b", fg="#f59e0b", insertbackground="white", font=("Microsoft YaHei UI", 9, "bold"))
        self.lock_entry.insert(0, str(self.rule.get("lock_exclusive", 0.0)))
        self.lock_entry.pack(side=tk.LEFT, padx=(4, 15))

        tk.Label(c1, text="定时周期(秒):", bg="#0f172a", fg="#38bdf8", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.timer_interval_entry = tk.Entry(c1, width=6, bg="#1e293b", fg="#38bdf8", insertbackground="white", font=("Microsoft YaHei UI", 9))
        self.timer_interval_entry.insert(0, str(self.rule.get("timer_interval", 15.0)))
        self.timer_interval_entry.pack(side=tk.LEFT, padx=(4, 6))

        self.on_type_change()
        self.on_action_change()
        self.on_flow_mode_change()
        self.render_candidates_ui()

    def render_candidates_ui(self):
        for w in self.cands_container.winfo_children():
            w.destroy()
        self.img_tk_cache.clear()

        # 同步更新主输入框中的路径列表
        target_paths = [c.get("image_path", "").strip() for c in self.candidates if c.get("image_path", "").strip()]
        if target_paths:
            self.target_entry.delete(0, tk.END)
            self.target_entry.insert(0, ";".join(target_paths))

        if not self.candidates:
            no_lbl = tk.Label(self.cands_container, text="暂无候选图片。点击上方“📁 选择多张文件”或“➕ 添加图片”添加本地图片文件。", bg="#0f172a", fg="#64748b", font=("Microsoft YaHei UI", 8), pady=12)
            no_lbl.pack()
            return

        # 按照优先级数字从小到大排序显示 (数字1为最高优先级)
        sorted_cands = sorted(enumerate(self.candidates), key=lambda x: int(x[1].get("priority", 1)))

        # 构建跳转目标下拉选项列表
        jump_options = ["(自由全功能循环)", "⏹️ 终止脚本"]
        jump_id_map = {"(自由全功能循环)": ("", "loop"), "⏹️ 终止脚本": ("", "stop")}
        for r in self.all_rules:
            if r["id"] != self.rule["id"]:
                lbl = f"➡️ 跳转到: {r['name']}"
                jump_options.append(lbl)
                jump_id_map[lbl] = (r["id"], "jump")

        for rank, (orig_idx, cand) in enumerate(sorted_cands):
            card = tk.Frame(self.cands_container, bg="#1e293b", highlightbackground="#334155", highlightthickness=1, padx=8, pady=6)
            card.pack(fill=tk.X, pady=4)

            # 左侧：缩略图预览
            img_frame = tk.Frame(card, bg="#0f172a", width=52, height=52)
            img_frame.pack_propagate(False)
            img_frame.pack(side=tk.LEFT, padx=(0, 8))

            p_raw = cand.get("image_path", "").strip()
            loaded_img = False
            if p_raw and os.path.exists(p_raw):
                try:
                    pil_im = Image.open(p_raw)
                    pil_im.thumbnail((48, 48))
                    photo = ImageTk.PhotoImage(pil_im)
                    self.img_tk_cache.append(photo)
                    lbl_img = tk.Label(img_frame, image=photo, bg="#0f172a")
                    lbl_img.pack(expand=True)
                    loaded_img = True
                except Exception:
                    loaded_img = False

            if not loaded_img:
                tk.Label(img_frame, text="🖼️\n无预览", bg="#0f172a", fg="#64748b", font=("Microsoft YaHei UI", 7)).pack(expand=True)

            # 中部：2行独立配置栏
            mid = tk.Frame(card, bg="#1e293b")
            mid.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # 行1：优先级徽章 + 路径与浏览 + 优先级数字设置
            row_top = tk.Frame(mid, bg="#1e293b")
            row_top.pack(fill=tk.X, pady=1)

            prio_val = int(cand.get("priority", 1))
            p_badge = f"🥇 P1(最高)" if rank == 0 else (f"🥈 P2" if rank == 1 else f"P{prio_val}")
            tk.Label(row_top, text=p_badge, bg="#f59e0b", fg="#000", font=("Microsoft YaHei UI", 8, "bold"), padx=4).pack(side=tk.LEFT, padx=(0, 6))

            tk.Label(row_top, text="图片路径/名称:", bg="#1e293b", fg="#cbd5e1", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT)
            path_entry = tk.Entry(row_top, width=22, bg="#0f172a", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 8))
            path_entry.insert(0, p_raw)
            path_entry.pack(side=tk.LEFT, padx=(2, 6), fill=tk.X, expand=True)
            path_entry.bind("<FocusOut>", lambda e, idx=orig_idx, entry=path_entry: self.update_cand_path(idx, entry.get()))

            tk.Button(row_top, text="📁 浏览", command=lambda idx=orig_idx: self.browse_single_cand_image(idx), bg="#3b82f6", fg="white", relief=tk.FLAT, font=("Microsoft YaHei UI", 8), padx=4).pack(side=tk.LEFT, padx=(0, 6))

            tk.Label(row_top, text="优先级(1最高):", bg="#1e293b", fg="#f59e0b", font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
            prio_sp = tk.Spinbox(row_top, from_=1, to=99, width=3, bg="#0f172a", fg="#f59e0b", font=("Microsoft YaHei UI", 8, "bold"))
            prio_sp.delete(0, tk.END)
            prio_sp.insert(0, str(prio_val))
            prio_sp.pack(side=tk.LEFT, padx=(2, 6))
            prio_sp.bind("<FocusOut>", lambda e, idx=orig_idx, sp=prio_sp: self.update_cand_prio(idx, sp.get()))

            # 行2：独立动作 + 独立命中跳转到指定步骤 (解决用户需求：每个图片各自独立跳转)
            row_bottom = tk.Frame(mid, bg="#1e293b")
            row_bottom.pack(fill=tk.X, pady=(2, 1))

            tk.Label(row_bottom, text="🎯 命中动作:", bg="#1e293b", fg="#94a3b8", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT)
            c_act = cand.get("action", self.rule.get("action", "click"))
            act_map = {"click": "click (物理单击)", "double_click": "double_click (双击)", "right_click": "right_click (右键)", "hover": "hover (悬停)", "press_enter": "press_enter (回车)", "sound_alarm": "sound_alarm (警报)"}
            
            act_sp = ttk.Combobox(row_bottom, values=["click (物理单击)", "double_click (双击)", "right_click (右键)", "hover (悬停)", "press_enter (回车)", "sound_alarm (警报)"], state="readonly", width=14, font=("Microsoft YaHei UI", 8))
            act_sp.set(act_map.get(c_act, "click (物理单击)"))
            act_sp.pack(side=tk.LEFT, padx=(2, 8))
            act_sp.bind("<<ComboboxSelected>>", lambda e, idx=orig_idx, combo=act_sp: self.update_cand_action(idx, combo.get()))

            tk.Label(row_bottom, text="🔀 命中后跳转到:", bg="#1e293b", fg="#a855f7", font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
            c_jump_id = cand.get("next_target_id", "")
            c_jump_mode = cand.get("next_mode", "loop")

            curr_jump_lbl = "(自由全功能循环)"
            if c_jump_mode == "stop":
                curr_jump_lbl = "⏹️ 终止脚本"
            else:
                for label, (r_id, _) in jump_id_map.items():
                    if r_id and r_id == c_jump_id:
                        curr_jump_lbl = label
                        break

            jump_combo = ttk.Combobox(row_bottom, values=jump_options, state="readonly", width=20, font=("Microsoft YaHei UI", 8))
            jump_combo.set(curr_jump_lbl)
            jump_combo.pack(side=tk.LEFT, padx=(2, 4))
            jump_combo.bind("<<ComboboxSelected>>", lambda e, idx=orig_idx, combo=jump_combo, jmap=jump_id_map: self.update_cand_jump(idx, combo.get(), jmap))

            # 排序微调与删除按钮
            btn_box = tk.Frame(card, bg="#1e293b")
            btn_box.pack(side=tk.RIGHT, padx=(4, 0))
            
            tk.Button(btn_box, text="⬆️", command=lambda idx=orig_idx: self.adjust_cand_prio(idx, 1), bg="#334155", fg="#fff", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=4).pack(side=tk.LEFT, padx=1)
            tk.Button(btn_box, text="⬇️", command=lambda idx=orig_idx: self.adjust_cand_prio(idx, -1), bg="#334155", fg="#fff", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=4).pack(side=tk.LEFT, padx=1)
            tk.Button(btn_box, text="🗑️", command=lambda idx=orig_idx: self.delete_candidate(idx), bg="#ef4444", fg="#fff", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=4).pack(side=tk.LEFT, padx=(4, 0))

    def update_cand_action(self, idx, val):
        if 0 <= idx < len(self.candidates):
            raw_act = val.split(" ")[0]
            self.candidates[idx]["action"] = raw_act

    def update_cand_jump(self, idx, val, jmap):
        if 0 <= idx < len(self.candidates):
            info = jmap.get(val, ("", "loop"))
            target_id, mode = info
            self.candidates[idx]["next_mode"] = mode
            self.candidates[idx]["next_target_id"] = target_id

    def update_cand_path(self, idx, val):
        if 0 <= idx < len(self.candidates):
            self.candidates[idx]["image_path"] = val.strip()
            self.render_candidates_ui()

    def update_cand_prio(self, idx, val):
        if 0 <= idx < len(self.candidates):
            try:
                self.candidates[idx]["priority"] = max(1, min(99, int(val)))
            except ValueError:
                pass
            self.render_candidates_ui()

    def adjust_cand_prio(self, idx, delta):
        # delta > 0 表示提升优先级（数值变小，例如 2 -> 1）
        if 0 <= idx < len(self.candidates):
            curr = int(self.candidates[idx].get("priority", 1))
            self.candidates[idx]["priority"] = max(1, min(99, curr - delta))
            self.render_candidates_ui()

    def delete_candidate(self, idx):
        if 0 <= idx < len(self.candidates):
            del self.candidates[idx]
            self.render_candidates_ui()

    def add_candidate(self):
        new_idx = len(self.candidates) + 1
        new_prio = 2  # 添加后默认均是第二优先级 (P2)
        self.candidates.append({
            "id": f"cand_{int(time.time()*1000)}_{new_idx}",
            "name": f"候选图-{new_idx}",
            "image_path": "",
            "priority": new_prio,
            "action": "click"
        })
        self.render_candidates_ui()

    def browse_single_cand_image(self, idx):
        path = filedialog.askopenfilename(title="选择图片文件", filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp")])
        if path and 0 <= idx < len(self.candidates):
            self.candidates[idx]["image_path"] = path
            self.render_candidates_ui()

    def browse_multiple_candidates(self):
        paths = filedialog.askopenfilenames(title="批量选择多张候选图片", filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp")])
        if paths:
            for p in paths:
                new_idx = len(self.candidates) + 1
                new_prio = 2  # 添加后默认均是第二优先级 (P2)
                self.candidates.append({
                    "id": f"cand_{int(time.time()*1000)}_{new_idx}",
                    "name": os.path.basename(p),
                    "image_path": p,
                    "priority": new_prio,
                    "action": "click"
                })
            self.render_candidates_ui()

    def on_flow_mode_change(self, event=None):
        mode = self.next_mode_var.get().split(" ")[0]
        if mode == "jump":
            self.jump_target_frame.pack(fill=tk.X, pady=3)
        else:
            self.jump_target_frame.pack_forget()

    def on_type_change(self, event=None):
        t_raw = self.type_var.get()
        t = t_raw.split(" ")[0]
        if t == "image":
            self.target_frame.pack_forget()  # 隐去顶部杂乱的原始路径字符串框，由下方的多图管理池全权收纳
            self.conf_frame.pack(fill=tk.X, pady=3)
            self.sec_cands.pack(fill=tk.X, pady=(0, 8))
        elif t == "image_vanish":
            self.lbl_target.config(text="消失检测图片:")
            self.target_frame.pack(fill=tk.X, pady=3)
            self.btn_browse.pack(side=tk.LEFT, padx=(0, 4))
            self.btn_snip.pack(side=tk.LEFT)
            self.conf_frame.pack(fill=tk.X, pady=3)
            self.sec_cands.pack(fill=tk.X, pady=(0, 8))
        elif t == "text":
            self.lbl_target.config(text="文字关键词(可多个;):")
            self.target_frame.pack(fill=tk.X, pady=3)
            self.btn_browse.pack_forget()
            self.btn_snip.pack_forget()
            self.conf_frame.pack_forget()
            self.sec_cands.pack_forget()
        elif t == "color":
            self.lbl_target.config(text="坐标与HEX颜色:")
            self.target_frame.pack(fill=tk.X, pady=3)
            self.btn_browse.pack_forget()
            self.btn_snip.pack_forget()
            self.conf_frame.pack_forget()
            self.sec_cands.pack_forget()
        elif t == "timer":
            self.lbl_target.config(text="定时说明:")
            self.target_frame.pack(fill=tk.X, pady=3)
            self.btn_browse.pack_forget()
            self.btn_snip.pack_forget()
            self.conf_frame.pack_forget()
            self.sec_cands.pack_forget()
        elif t == "color":
            self.lbl_target.config(text="坐标与HEX颜色:")
            self.btn_browse.pack_forget()
            self.btn_snip.pack_forget()
            self.conf_frame.pack_forget()
            self.sec_cands.pack_forget()
        elif t == "timer":
            self.lbl_target.config(text="定时备注说明:")
            self.btn_browse.pack_forget()
            self.btn_snip.pack_forget()
            self.conf_frame.pack_forget()
            self.sec_cands.pack_forget()

    def on_action_change(self, event=None):
        act_raw = self.action_var.get()
        act = act_raw.split(" ")[0]
        if act == "hotkey":
            self.lbl_act_param.config(text="组合快捷键:")
            self.lbl_param_hint.config(text="如: ctrl+c, alt+f4")
            self.act_param_frame.pack(fill=tk.X, pady=3)
        elif act == "type_text":
            self.lbl_act_param.config(text="输入文本内容:")
            self.lbl_param_hint.config(text="输入自动打出的字符串")
            self.act_param_frame.pack(fill=tk.X, pady=3)
        elif "scroll" in act:
            self.lbl_act_param.config(text="滚动行数幅度:")
            self.lbl_param_hint.config(text="如: 300")
            self.act_param_frame.pack(fill=tk.X, pady=3)
        else:
            self.act_param_frame.pack_forget()

    def browse_image(self):
        paths = filedialog.askopenfilenames(title="选择多张候选图片", filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp")])
        if paths:
            for p in paths:
                new_idx = len(self.candidates) + 1
                new_prio = min(99, new_idx + 1)
                self.candidates.append({
                    "id": f"cand_{int(time.time()*1000)}_{new_idx}",
                    "name": os.path.basename(p),
                    "image_path": p,
                    "priority": new_prio,
                    "action": "click"
                })
            self.render_candidates_ui()

    def start_snip(self):
        self.iconify()
        time.sleep(0.3)
        ScreenSnipper(self, self.on_snip_done)

    def on_snip_done(self, path):
        self.deiconify()
        new_idx = len(self.candidates) + 1
        new_prio = 2  # 添加后默认均是第二优先级 (P2)
        self.candidates.append({
            "id": f"cand_{int(time.time()*1000)}_{new_idx}",
            "name": f"截图_{os.path.basename(path)}",
            "image_path": path,
            "priority": new_prio,
            "action": "click"
        })
        self.render_candidates_ui()

    def save(self):
        name = self.name_entry.get().strip() or "未命名步骤"
        t_raw = self.type_var.get().split(" ")[0]
        act_raw = self.action_var.get().split(" ")[0]
        flow_raw = self.next_mode_var.get().split(" ")[0]
        target = self.target_entry.get().strip()

        if t_raw != "timer" and not target and not self.candidates:
            messagebox.showerror("错误", "目标内容或候选图片不能为空！")
            return

        try:
            ox = int(self.ox_entry.get())
        except ValueError:
            ox = 0
        try:
            oy = int(self.oy_entry.get())
        except ValueError:
            oy = 0
        try:
            cooldown = float(self.cooldown_entry.get())
        except ValueError:
            cooldown = 0.0
        try:
            lock_time = float(self.lock_entry.get())
        except ValueError:
            lock_time = 0.0
        try:
            timeout_val = float(self.timeout_entry.get())
        except ValueError:
            timeout_val = 20.0
        try:
            timer_int_val = float(self.timer_interval_entry.get())
        except Exception:
            timer_int_val = 15.0

        target_rule_id = self.target_id_map.get(self.jump_combo_var.get(), "")
        timeout_target_id = self.timeout_id_map.get(self.timeout_combo_var.get(), "")

        self.rule.update({
            "name": name,
            "enabled": self.enabled_var.get(),
            "priority": int(self.priority_scale.get()),
            "type": t_raw,
            "target": target,
            "confidence": float(self.conf_scale.get()),
            "offset_x": ox,
            "offset_y": oy,
            "action": act_raw,
            "action_param": self.act_param_entry.get().strip(),
            "cooldown": cooldown,
            "lock_exclusive": lock_time,
            "next_mode": flow_raw,
            "next_target_id": target_rule_id,
            "timeout_target_id": timeout_target_id,
            "next_timeout": timeout_val,
            "timer_interval": timer_int_val,
            "humanize": self.humanize_var.get(),
            "candidates": self.candidates
        })

        if self.on_save:
            self.on_save(self.rule)
        self.destroy()

    def destroy(self):
        try:
            self.unbind_all("<MouseWheel>")
        except Exception:
            pass
        super().destroy()



class RealScreenScanBot:
    """智能视窗自适应 Desktop RPA 控制台：支持窗口智能伸缩、平滑滚动、无惧小屏和分辨率限制"""
    def __init__(self, root):
        self.root = root
        self.root.title("ScreenScan RPA 智能工作台 (小屏防裁剪自适应版)")
        
        # 智能动态检测屏幕分辨率并适配初始大小，确保在 1366x768 或小笔记本上完整显示
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(1120, max(760, int(sw * 0.88)))
        h = min(780, max(520, int(sh * 0.84)))
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(720, 480)
        self.root.configure(bg="#0f172a")
        self.root.resizable(True, True)

        self.rules = []
        self.load_rules_from_file()

        self.running = False
        self.workflow_target_id = None
        self.workflow_target_deadline = 0
        self.locked_rule_id = None
        self.lock_expire_time = 0
        self.last_action_timestamp = time.time()
        self.heartbeat = time.time()
        self.template_cache = {}
        self.target_region = None
        self.bot_interval = 0.8
        self.anti_stuck_threshold = 45.0 # 45秒防卡死看门狗
        
        # 🛡️ 安全护栏核心状态
        self.dry_run = False           # 仿真演练模式 (只记录不真实点击)
        self.paused = False            # 暂停标志 (F7 即时暂停)
        self.action_counter = 0        # 执行动作计数器
        self.max_actions = 0           # 最大执行次数上限 (0=不限)
        self.bot_start_time = 0        # 启动时间戳
        self.max_duration_seconds = 0  # 最长运行时长上限 (0=不限)
        self.timer_records = {}        # 定时器规则的时间戳记忆
        self.rule_last_fire = {}       # 每条规则最后触发时间戳 (精确冷却管理)

        self.compact_mode = False
        self.create_widgets()
        self.start_global_hotkey_listener()
        self.start_watchdog_thread()

    def load_rules_from_file(self):
        file_path = os.path.join(os.getcwd(), "rpa_rules.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.rules = json.load(f)
            except Exception:
                self.rules = []
        if not self.rules:
            self.rules = json.loads('''[
  {
    "id": "r_snatch_1",
    "name": "步骤1: 监控并点击抢单/立即购买按钮",
    "enabled": true,
    "priority": 1,
    "type": "image",
    "target": "snatch_btn.png;buy_now.png;立即抢购;抢单",
    "confidence": 0.72,
    "offset_x": 0,
    "offset_y": 0,
    "action": "click",
    "action_param": "",
    "cooldown": 0,
    "lock_exclusive": 0,
    "next_mode": "jump",
    "next_target_id": "r_snatch_2",
    "timeout_target_id": "",
    "next_timeout": 10,
    "humanize": true,
    "candidates": [
      {
        "id": "c_snatch_1",
        "name": "极速红色秒杀按钮 (P1最高优先)",
        "image_path": "fast_snatch.png",
        "template": "data:image/svg+xml;utf8,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"140\" height=\"48\" viewBox=\"0 0 140 48\"><rect width=\"140\" height=\"48\" rx=\"8\" fill=\"%23dc2626\"/><text x=\"70\" y=\"30\" fill=\"%23ffffff\" font-size=\"14\" font-weight=\"bold\" font-family=\"sans-serif\" text-anchor=\"middle\">⚡ 极速秒杀</text></svg>",
        "priority": 1,
        "confidence": 0.75,
        "action": "double_click",
        "action_param": "",
        "offset_x": 0,
        "offset_y": 0,
        "next_target_id": "r_snatch_2"
      },
      {
        "id": "c_snatch_2",
        "name": "常规立即购买按钮 (P2第二优先)",
        "image_path": "buy_now.png",
        "template": "data:image/svg+xml;utf8,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"140\" height=\"48\" viewBox=\"0 0 140 48\"><rect width=\"140\" height=\"48\" rx=\"8\" fill=\"%23ea580c\"/><text x=\"70\" y=\"30\" fill=\"%23ffffff\" font-size=\"14\" font-weight=\"bold\" font-family=\"sans-serif\" text-anchor=\"middle\">🛒 立即购买</text></svg>",
        "priority": 2,
        "confidence": 0.72,
        "action": "click",
        "action_param": "",
        "offset_x": 0,
        "offset_y": 0,
        "next_target_id": "r_snatch_2"
      },
      {
        "id": "c_snatch_3",
        "name": "重新排队/刷新抢购 (P3第三优先)",
        "image_path": "retry_queue.png",
        "template": "data:image/svg+xml;utf8,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"140\" height=\"48\" viewBox=\"0 0 140 48\"><rect width=\"140\" height=\"48\" rx=\"8\" fill=\"%234f46e5\"/><text x=\"70\" y=\"30\" fill=\"%23ffffff\" font-size=\"14\" font-weight=\"bold\" font-family=\"sans-serif\" text-anchor=\"middle\">🔄 刷新排队</text></svg>",
        "priority": 3,
        "confidence": 0.7,
        "action": "click",
        "action_param": "",
        "offset_x": 0,
        "offset_y": 0
      }
    ]
  },
  {
    "id": "r_snatch_2",
    "name": "步骤2: 监控确认提交/结算弹窗",
    "enabled": true,
    "priority": 2,
    "type": "text",
    "target": "确定;提交订单;去结算;确认",
    "confidence": 0.7,
    "offset_x": 0,
    "offset_y": 0,
    "action": "click",
    "action_param": "",
    "cooldown": 1,
    "lock_exclusive": 0,
    "next_mode": "jump",
    "next_target_id": "r_snatch_3",
    "timeout_target_id": "r_snatch_1",
    "next_timeout": 8,
    "humanize": true
  },
  {
    "id": "r_snatch_3",
    "name": "步骤3: 抢购成功提示并终结",
    "enabled": true,
    "priority": 3,
    "type": "text",
    "target": "购买成功;下单成功;恭喜;支付成功",
    "confidence": 0.7,
    "offset_x": 0,
    "offset_y": 0,
    "action": "sound_alarm",
    "action_param": "",
    "cooldown": 2,
    "lock_exclusive": 0,
    "next_mode": "stop",
    "next_target_id": "",
    "timeout_target_id": "r_snatch_1",
    "next_timeout": 15,
    "humanize": false
  }
]''')

    def save_rules_to_file(self):
        file_path = os.path.join(os.getcwd(), "rpa_rules.json")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.rules, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def create_widgets(self):
        # 1. 顶部自适应标题与热键栏
        title_frame = tk.Frame(self.root, bg="#1e293b", padx=14, pady=8)
        title_frame.pack(fill=tk.X, padx=8, pady=(8, 4))
        
        lbl = tk.Label(title_frame, text="🤖 ScreenScan RPA 智能工作台", bg="#1e293b", fg="#f8fafc", font=("Microsoft YaHei UI", 12, "bold"))
        lbl.pack(side=tk.LEFT)

        if is_admin():
            tk.Label(title_frame, text="🛡️ 管理员特权", bg="#1e293b", fg="#10b981", font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT, padx=10)
        else:
            tk.Button(title_frame, text="🛡️ 提权重启", command=self.restart_as_admin, bg="#f59e0b", fg="black", font=("Microsoft YaHei UI", 8, "bold"), relief=tk.FLAT, padx=6, pady=1).pack(side=tk.LEFT, padx=8)

        hotkey_box = tk.Frame(title_frame, bg="#1e293b")
        hotkey_box.pack(side=tk.RIGHT)
        tk.Label(hotkey_box, text="[F7 暂停/恢复]", bg="#f59e0b", fg="black", font=("Microsoft YaHei UI", 8, "bold"), padx=6, pady=2).pack(side=tk.LEFT, padx=2)
        tk.Label(hotkey_box, text="[F8 启动]", bg="#10b981", fg="white", font=("Microsoft YaHei UI", 8, "bold"), padx=6, pady=2).pack(side=tk.LEFT, padx=2)
        tk.Label(hotkey_box, text="[F9 停止]", bg="#ef4444", fg="white", font=("Microsoft YaHei UI", 8, "bold"), padx=6, pady=2).pack(side=tk.LEFT, padx=2)

        # 2. 场景预设快捷栏
        preset_bar = tk.Frame(self.root, bg="#0f172a", padx=10, pady=3)
        preset_bar.pack(fill=tk.X)
        tk.Label(preset_bar, text="💡 快速预设: ", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)
        tk.Button(preset_bar, text="⚡ 抢单秒杀", command=lambda: self.apply_preset("snatch"), bg="#3b82f6", fg="white", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=6, pady=1).pack(side=tk.LEFT, padx=2)
        tk.Button(preset_bar, text="🔄 挂机防掉线", command=lambda: self.apply_preset("afk"), bg="#8b5cf6", fg="white", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=6, pady=1).pack(side=tk.LEFT, padx=2)
        tk.Button(preset_bar, text="🛡️ 弹窗拦截", command=lambda: self.apply_preset("popup"), bg="#059669", fg="white", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=6, pady=1).pack(side=tk.LEFT, padx=2)

        # 3. 步骤列表容器 (支持垂直与水平双向滚动条，窗口再窄也不截断列)
        rules_frame = tk.LabelFrame(self.root, text=" 智能工作流步骤状态机 (自适应双向滚动) ", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 10, "bold"), padx=8, pady=6)
        rules_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        tree_container = tk.Frame(rules_frame, bg="#0f172a")
        tree_container.pack(fill=tk.BOTH, expand=True)

        columns = ("priority", "enabled", "name", "type", "target", "action", "next_step", "timeout_fb")
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", height=5)
        self.tree.heading("priority", text="优先级")
        self.tree.heading("enabled", text="状态")
        self.tree.heading("name", text="步骤名称")
        self.tree.heading("type", text="触发模式")
        self.tree.heading("target", text="目标检索 (多图/多词)")
        self.tree.heading("action", text="执行动作")
        self.tree.heading("next_step", text="成功下一步")
        self.tree.heading("timeout_fb", text="超时兜底")

        self.tree.column("priority", width=65, anchor="center")
        self.tree.column("enabled", width=55, anchor="center")
        self.tree.column("name", width=130)
        self.tree.column("type", width=90)
        self.tree.column("target", width=220)
        self.tree.column("action", width=120)
        self.tree.column("next_step", width=150)
        self.tree.column("timeout_fb", width=140)

        # 滚动条支持
        tree_scroll_y = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        # 4. 操作按钮条（拆分为自适应双排，防止窄窗口时右侧测试按钮溢出）
        btn_bar = tk.Frame(rules_frame, bg="#0f172a", pady=4)
        btn_bar.pack(fill=tk.X)

        row1 = tk.Frame(btn_bar, bg="#0f172a")
        row1.pack(fill=tk.X, pady=1)
        tk.Button(row1, text="➕ 新增步骤", command=self.add_rule, bg="#10b981", fg="white", font=("Microsoft YaHei UI", 8, "bold"), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(row1, text="✏️ 修改步骤", command=self.edit_rule, bg="#3b82f6", fg="white", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(row1, text="🗑️ 删除步骤", command=self.delete_rule, bg="#ef4444", fg="white", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(row1, text="⬆️ 上移", command=self.move_up, bg="#334155", fg="#cbd5e1", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=6, pady=2).pack(side=tk.LEFT, padx=(0, 3))
        tk.Button(row1, text="⬇️ 下移", command=self.move_down, bg="#334155", fg="#cbd5e1", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=6, pady=2).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(row1, text="🎯 框选监控区域(ROI)", command=self.start_roi_selection, bg="#0d9488", fg="white", font=("Microsoft YaHei UI", 8, "bold"), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(row1, text="🌐 重置全屏", command=self.reset_roi_fullscreen, bg="#334155", fg="#cbd5e1", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=6, pady=2).pack(side=tk.LEFT, padx=(0, 6))
        self.lbl_roi_status = tk.Label(row1, text="🌐 全屏监控", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 8))
        self.lbl_roi_status.pack(side=tk.LEFT)

        row2 = tk.Frame(btn_bar, bg="#0f172a")
        row2.pack(fill=tk.X, pady=1)
        tk.Button(row2, text="🔍 仅测试匹配", command=self.test_single_rule_detection, bg="#8b5cf6", fg="white", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(row2, text="🖱️ 真实点击测试(2s后)", command=self.test_real_click_selected_rule, bg="#0ea5e9", fg="white", font=("Microsoft YaHei UI", 8, "bold"), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(row2, text="🎨 屏幕吸管取色", command=self.start_color_picker, bg="#0284c7", fg="white", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(row2, text="⏱️ 3秒物理点击", command=self.test_physical_click_at_cursor, bg="#475569", fg="#f8fafc", font=("Microsoft YaHei UI", 8), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(row2, text="🩺 规则健康体检", command=self.run_preflight_health_check, bg="#6366f1", fg="white", font=("Microsoft YaHei UI", 8, "bold"), relief=tk.FLAT, padx=8, pady=2).pack(side=tk.LEFT)

        # 5. 控制面板（全功能展示）
        ctrl_frame = tk.Frame(self.root, bg="#0f172a", padx=10, pady=4)
        ctrl_frame.pack(fill=tk.X, padx=8, pady=2)

        tk.Label(ctrl_frame, text="巡检周期(s):", bg="#0f172a", fg="#cbd5e1", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 2))
        self.interval_entry = tk.Entry(ctrl_frame, width=4, bg="#1e293b", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 9))
        self.interval_entry.insert(0, "0.8")
        self.interval_entry.pack(side=tk.LEFT, padx=(0, 8))

        tk.Label(ctrl_frame, text="并发仲裁:", bg="#0f172a", fg="#f59e0b", font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 2))
        self.arbitration_mode_var = tk.StringVar(value="priority")
        self.arb_combo = ttk.Combobox(ctrl_frame, textvariable=self.arbitration_mode_var, values=[
            "priority (最高权重 P1~P99 优先 - 推荐)",
            "confidence (检测置信度最高优先)",
            "order (列表顺序优先)"
        ], state="readonly", width=26, font=("Microsoft YaHei UI", 8))
        self.arb_combo.pack(side=tk.LEFT, padx=(0, 10))

        self.dry_run_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ctrl_frame, text="🛡️ Dry-Run 试运行 (只记录不点击)", variable=self.dry_run_var, bg="#0f172a", fg="#38bdf8", selectcolor="#1e293b", font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(ctrl_frame, text="执行上限:", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT)
        self.max_runs_entry = tk.Entry(ctrl_frame, width=4, bg="#1e293b", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 8))
        self.max_runs_entry.insert(0, "0")
        self.max_runs_entry.pack(side=tk.LEFT, padx=(2, 6))

        tk.Label(ctrl_frame, text="限时(分):", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT)
        self.max_duration_entry = tk.Entry(ctrl_frame, width=4, bg="#1e293b", fg="#fff", insertbackground="white", font=("Microsoft YaHei UI", 8))
        self.max_duration_entry.insert(0, "0")
        self.max_duration_entry.pack(side=tk.LEFT, padx=(2, 10))

        self.btn_start = tk.Button(ctrl_frame, text="▶ 启动 (F8)", command=self.start_bot, bg="#10b981", fg="white", font=("Microsoft YaHei UI", 10, "bold"), padx=12, pady=4, relief=tk.FLAT)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_pause = tk.Button(ctrl_frame, text="⏸ 暂停 (F7)", command=self.toggle_pause, bg="#f59e0b", fg="black", font=("Microsoft YaHei UI", 10, "bold"), padx=10, pady=4, relief=tk.FLAT, state=tk.DISABLED)
        self.btn_pause.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_stop = tk.Button(ctrl_frame, text="⏹ 停止 (F9)", command=self.stop_bot, bg="#ef4444", fg="white", font=("Microsoft YaHei UI", 10, "bold"), padx=12, pady=4, relief=tk.FLAT, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT)

        # 6. 日志面板
        log_frame = tk.LabelFrame(self.root, text=" 智能工作流运转日志 (含看门狗守护与并发仲裁记录) ", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei UI", 9, "bold"), padx=6, pady=4)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 6))

        log_container = tk.Frame(log_frame, bg="#020617")
        log_container.pack(fill=tk.BOTH, expand=True)

        self.log_box = tk.Text(log_container, bg="#020617", fg="#38ef7d", font=("Consolas", 9), state=tk.DISABLED, height=6)
        log_scroll = ttk.Scrollbar(log_container, orient=tk.VERTICAL, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=log_scroll.set)

        self.log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.refresh_rules_tree()
        self.log("ScreenScan RPA 智能工作台就绪！自适应视窗防裁剪已就绪，看门狗自愈守护已激活。")

    def apply_preset(self, key):
        presets = {
            "snatch": [
                {"id": "r_1", "name": "步骤1: 监控抢单/购买按钮", "enabled": True, "priority": 1, "type": "image", "target": "btn.png;力即抢购;抢单", "confidence": 0.72, "offset_x": 0, "offset_y": 0, "action": "click", "action_param": "", "cooldown": 0.0, "lock_exclusive": 0.0, "next_mode": "jump", "next_target_id": "r_2", "timeout_target_id": "", "next_timeout": 10.0, "humanize": True},
                {"id": "r_2", "name": "步骤2: 监控确认提交/结算弹窗", "enabled": True, "priority": 2, "type": "text", "target": "确定;提交订单;去结算;确认", "confidence": 0.70, "offset_x": 0, "offset_y": 0, "action": "click", "action_param": "", "cooldown": 1.0, "lock_exclusive": 0.0, "next_mode": "jump", "next_target_id": "r_3", "timeout_target_id": "r_1", "next_timeout": 8.0, "humanize": True},
                {"id": "r_3", "name": "步骤3: 抢购成功提示并终结", "enabled": True, "priority": 3, "type": "text", "target": "购买成功;下单成功;恭喜;支付成功", "confidence": 0.70, "offset_x": 0, "offset_y": 0, "action": "sound_alarm", "action_param": "", "cooldown": 2.0, "lock_exclusive": 0.0, "next_mode": "stop", "next_target_id": "", "timeout_target_id": "r_1", "next_timeout": 15.0, "humanize": False}
            ],
            "afk": [
                {"id": "r_1", "name": "步骤1: 检测主界面活跃状态", "enabled": True, "priority": 1, "type": "text", "target": "主城;大厅;在线;挂机中;背包", "confidence": 0.70, "offset_x": 0, "offset_y": 0, "action": "hover", "action_param": "", "cooldown": 5.0, "lock_exclusive": 0.0, "next_mode": "loop", "next_target_id": "", "timeout_target_id": "r_2", "next_timeout": 20.0, "humanize": True},
                {"id": "r_2", "name": "步骤2: 检测并点击重连/继续", "enabled": True, "priority": 2, "type": "text", "target": "重新连接;点击重试;继续;确认", "confidence": 0.68, "offset_x": 0, "offset_y": 0, "action": "click", "action_param": "", "cooldown": 3.0, "lock_exclusive": 0.0, "next_mode": "jump", "next_target_id": "r_1", "timeout_target_id": "r_3", "next_timeout": 15.0, "humanize": True},
                {"id": "r_3", "name": "步骤3: 防卡死按 ESC 唤醒窗口", "enabled": True, "priority": 3, "type": "timer", "target": "定时防卡死按键", "confidence": 0.70, "offset_x": 0, "offset_y": 0, "action": "hotkey", "action_param": "esc", "cooldown": 3.0, "lock_exclusive": 0.0, "next_mode": "loop", "next_target_id": "", "timeout_target_id": "", "next_timeout": 10.0, "humanize": False}
            ],
            "popup": [
                {"id": "r_1", "name": "自动点击关闭/跳过文字按钮", "enabled": True, "priority": 1, "type": "text", "target": "跳过;关闭;暂不更新;我知道了;稍后提醒;取消", "confidence": 0.70, "offset_x": 0, "offset_y": 0, "action": "click", "action_param": "", "cooldown": 1.5, "lock_exclusive": 0.0, "next_mode": "loop", "next_target_id": "", "timeout_target_id": "", "next_timeout": 30.0, "humanize": True},
                {"id": "r_2", "name": "图标叉号弹窗关闭", "enabled": True, "priority": 2, "type": "image", "target": "close_x.png;icon_close.png", "confidence": 0.75, "offset_x": 0, "offset_y": 0, "action": "click", "action_param": "", "cooldown": 1.5, "lock_exclusive": 0.0, "next_mode": "loop", "next_target_id": "", "timeout_target_id": "", "next_timeout": 30.0, "humanize": True}
            ]
        }
        if key in presets:
            self.rules = presets[key]
            self.save_rules_to_file()
            self.refresh_rules_tree()
            self.log(f"已成功加载【{key}】场景智能预设！")

    def start_watchdog_thread(self):
        def _watchdog_loop():
            while True:
                time.sleep(3.0)
                if self.running:
                    elapsed = time.time() - getattr(self, "heartbeat", time.time())
                    if elapsed > self.anti_stuck_threshold:
                        self.log(f"⚠️ 【看门狗心跳超时】状态机主线程心跳已超时 ({int(elapsed)}s > {self.anti_stuck_threshold}s)！请检查是否存在阻塞。")
                        self.heartbeat = time.time()
        threading.Thread(target=_watchdog_loop, daemon=True).start()

    def restart_as_admin(self):
        try:
            script_path = os.path.abspath(__file__)
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script_path}"', None, 1)
            self.root.after(400, self.root.destroy)
        except Exception as e:
            messagebox.showerror("提权失败", f"无法以管理员身份重启: {e}")

    def test_physical_click_at_cursor(self):
        def _test():
            self.log("⏳ 【3秒物理点击测试】请把鼠标移动到目标按钮上，3 秒后触发穿透物理点击...")
            for i in range(3, 0, -1):
                self.log(f"倒计时 {i} 秒...")
                time.sleep(1.0)
            x, y = pyautogui.position()
            self.log(f"🎯 正在向当前光标坐标 ({x}, {y}) 注入 150ms 真实物理点击信号...")
            self.hardware_click(x, y)
            self.log("✅ 物理点击已触发！请观察目标窗口是否受击响应。")
            try:
                import winsound
                winsound.Beep(1200, 100)
            except Exception:
                pass
        threading.Thread(target=_test, daemon=True).start()

    def test_real_click_selected_rule(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在上方列表中选中一条步骤规则！")
            return
        r_id = sel[0]
        rule = next((r for r in self.rules if r["id"] == r_id), None)
        if not rule:
            return

        def _do_test():
            self.log(f"⏳ 【单步真实点击测试】将在 2 秒后对步骤【{rule['name']}】执行真实物理点击！请切换至目标窗口...")
            time.sleep(2.0)
            
            screenshot = ImageGrab.grab()
            screen_np = np.array(screenshot)
            screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
            ret = self.detect_single_rule(rule, screenshot, screen_gray)
            matched, info, coord, score = ret[:4]
            cand = ret[4] if len(ret) == 5 else None
            
            if matched and coord:
                rx = region[0] if region else 0
                ry = region[1] if region else 0
                ox = cand.get("offset_x", rule.get("offset_x", 0)) if cand else rule.get("offset_x", 0)
                oy = cand.get("offset_y", rule.get("offset_y", 0)) if cand else rule.get("offset_y", 0)
                tx, ty = coord[0] + rx + ox, coord[1] + ry + oy
                self.log(f"🎯 命中目标坐标: ({coord[0]}, {coord[1]}) | 全屏坐标(含偏移): ({tx}, {ty})")

                # Dry-Run 仿真与自身窗口自卫拦截
                if self.is_self_window(tx, ty):
                    self.log(f"🛑 【安全拦截】测试点击坐标 ({tx}, {ty}) 落在控制台窗口内，已拒绝点击！")
                    return
                if getattr(self, "dry_run", False):
                    self.log(f"🛡️ 【DRY-RUN 试运行】已命中目标坐标 ({tx}, {ty})，仿真模式下已拦截物理点击！")
                    return

                self.hardware_click(tx, ty, button="left", hold_time=0.15, humanize=rule.get("humanize", True))
                self.log("🎉 真实物理点击已执行！请查看目标软件是否已被点中。")
                try:
                    import winsound
                    winsound.Beep(1200, 120)
                except Exception:
                    pass
            else:
                self.log(f"❌ 未检测到目标，无法执行真实点击: {info}")
                messagebox.showwarning("测试未命中", f"未找到目标位置，无法执行点击：\n{info}")

        threading.Thread(target=_do_test, daemon=True).start()

    def refresh_rules_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        id_to_name = {r["id"]: r["name"] for r in self.rules}

        for r in self.rules:
            prio = r.get("priority", 1)
            prio_str = f"P{prio}"
            en_str = "✅ 开启" if r.get("enabled", True) else "❌ 停用"
            t_map = {"image": "🖼️ 多图", "text": "🔤 智能OCR", "image_vanish": "🚫 消失", "color": "🎨 颜色", "timer": "⏰ 定时"}
            t_name = t_map.get(r["type"], r["type"])

            flow_mode = r.get("next_mode", "loop")
            if flow_mode == "jump":
                tgt_name = id_to_name.get(r.get("next_target_id"), "指定步骤")
                next_str = f"➡️ 跳转: {tgt_name} (限{r.get('next_timeout', 20)}s)"
            elif flow_mode == "sequence":
                next_str = "🔄 顺序流转下一步"
            elif flow_mode == "stop":
                next_str = "⏹️ 终止脚本"
            else:
                next_str = "🔄 自由循环"

            timeout_tgt = id_to_name.get(r.get("timeout_target_id"), "")
            timeout_str = f"🛡️ 兜底-> {timeout_tgt}" if timeout_tgt else "无(等待)"

            self.tree.insert("", tk.END, iid=r["id"], values=(
                prio_str, en_str, r["name"], t_name, r["target"], r["action"], next_str, timeout_str
            ))

    def add_rule(self):
        RuleDialog(self.root, rule=None, all_rules=self.rules, on_save=self.on_rule_saved)

    def edit_rule(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在上方列表中点击选中一条规则！")
            return
        r_id = sel[0]
        rule = next((r for r in self.rules if r["id"] == r_id), None)
        if rule:
            RuleDialog(self.root, rule=dict(rule), all_rules=self.rules, on_save=self.on_rule_saved)

    def delete_rule(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中点击选择一条规则！")
            return
        r_id = sel[0]
        self.rules = [r for r in self.rules if r["id"] != r_id]
        self.save_rules_to_file()
        self.refresh_rules_tree()

    def move_up(self):
        sel = self.tree.selection()
        if not sel:
            return
        r_id = sel[0]
        idx = next((i for i, r in enumerate(self.rules) if r["id"] == r_id), -1)
        if idx > 0:
            self.rules[idx], self.rules[idx - 1] = self.rules[idx - 1], self.rules[idx]
            self.save_rules_to_file()
            self.refresh_rules_tree()
            self.tree.selection_set(r_id)

    def move_down(self):
        sel = self.tree.selection()
        if not sel:
            return
        r_id = sel[0]
        idx = next((i for i, r in enumerate(self.rules) if r["id"] == r_id), -1)
        if idx >= 0 and idx < len(self.rules) - 1:
            self.rules[idx], self.rules[idx + 1] = self.rules[idx + 1], self.rules[idx]
            self.save_rules_to_file()
            self.refresh_rules_tree()
            self.tree.selection_set(r_id)

    def on_rule_saved(self, saved_rule):
        idx = next((i for i, r in enumerate(self.rules) if r["id"] == saved_rule["id"]), -1)
        if idx >= 0:
            self.rules[idx] = saved_rule
        else:
            self.rules.append(saved_rule)
        self.save_rules_to_file()
        self.refresh_rules_tree()
        self.log(f"已保存智能步骤: {saved_rule['name']}")

    def start_color_picker(self):
        def _picker_thread():
            self.log("🎨 【吸管工具已激活】请将鼠标移至目标颜色位置，5 秒后自动读取坐标与 RGB/HEX 颜色值...")
            for i in range(5, 0, -1):
                self.log(f"倒计时 {i} 秒...")
                time.sleep(1.0)
            x, y = pyautogui.position()
            screenshot = ImageGrab.grab()
            rgb = screenshot.getpixel((x, y))
            hex_color = "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])
            val_str = f"{x},{y},{hex_color}"
            self.log(f"🎯 吸管采集成功！坐标: ({x}, {y}) | RGB: {rgb} | HEX: {hex_color}")
            messagebox.showinfo("吸管取色结果", f"坐标与颜色参数：\n{val_str}\n\n已自动复制到剪贴板！")
            self.root.clipboard_clear()
            self.root.clipboard_append(val_str)

        threading.Thread(target=_picker_thread, daemon=True).start()

    def safe_start_bot(self):
        if not self.running:
            try:
                import winsound
                winsound.Beep(1000, 150)
            except Exception:
                pass
            self.root.after(0, self.start_bot)

    def safe_stop_bot(self):
        if self.running:
            try:
                import winsound
                winsound.Beep(500, 200)
            except Exception:
                pass
            self.root.after(0, self.stop_bot)

    def toggle_pause(self):
        if not self.running:
            return
        now = time.time()
        if hasattr(self, "_last_pause_toggle") and now - self._last_pause_toggle < 0.4:
            return
        self._last_pause_toggle = now
        self.paused = not self.paused
        if self.paused:
            def _ui_pause():
                self.btn_pause.config(text="▶ 恢复 (F7)", bg="#10b981", fg="white")
            self.root.after(0, _ui_pause)
            self.log("⏸️ 【状态机已暂停】按 [F7] 随时恢复执行。")
        else:
            def _ui_resume():
                self.btn_pause.config(text="⏸ 暂停 (F7)", bg="#f59e0b", fg="black")
            self.root.after(0, _ui_resume)
            self.log("▶️ 【状态机已恢复】继续监控。")

    def start_roi_selection(self):
        self.root.iconify()
        time.sleep(0.3)
        ScreenSnipper(self.root, self.on_roi_selected, return_bbox=True)

    def on_roi_selected(self, bbox):
        self.root.deiconify()
        if bbox:
            self.target_region = bbox
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            self.lbl_roi_status.config(text=f"🎯 ROI: ({bbox[0]},{bbox[1]})-({bbox[2]},{bbox[3]}) [{w}x{h}]", fg="#10b981")
            self.log(f"🎯 已限定识别监控区域 (ROI): ({bbox[0]}, {bbox[1]}) 到 ({bbox[2]}, {bbox[3]}) [{w}x{h}]，大幅降低全屏扫描开销！")

    def reset_roi_fullscreen(self):
        self.target_region = None
        self.lbl_roi_status.config(text="🌐 全屏监控", fg="#94a3b8")
        self.log("🌐 已恢复为全屏扫描监控模式。")

    def run_preflight_health_check(self):
        self.log("🩺 正在进行规则健康体检 (路径完整性、悬空跳转、死循环)...")
        issues = []
        rule_ids = {r["id"] for r in self.rules}
        
        for idx, r in enumerate(self.rules):
            r_name = r.get("name", f"规则{idx+1}")
            if r.get("type") in ("image", "image_vanish"):
                cands = r.get("candidates") or []
                if cands:
                    for c in cands:
                        p = c.get("image_path", "").strip()
                        if p and not os.path.exists(p):
                            issues.append(f"❌ 步骤【{r_name}】候选图路径不存在: {p}")
                else:
                    paths = [p.strip() for p in r.get("target", "").replace("|", ";").split(";") if p.strip()]
                    for p in paths:
                        if not os.path.exists(p):
                            issues.append(f"❌ 步骤【{r_name}】目标图片不存在: {p}")
            
            if r.get("next_mode") == "jump":
                tgt = r.get("next_target_id")
                if tgt and tgt not in rule_ids:
                    issues.append(f"⚠️ 步骤【{r_name}】跳转目标 ID 悬空 (不存在): {tgt}")
            
            fb = r.get("timeout_target_id")
            if fb and fb not in rule_ids:
                issues.append(f"⚠️ 步骤【{r_name}】超时兜底 ID 悬空 (不存在): {fb}")

        if not issues:
            self.log("✅ 【规则健康体检通过】所有图片路径真实有效，流转跳转关系完整，无悬空死链！")
            messagebox.showinfo("自检合格", "🎉 所有规则健康体检通过！\n\n• 所有图片路径均真实有效\n• 跳转关系完整无死链\n• 准备就绪，可安全运行。")
        else:
            self.log(f"⚠️ 【规则体检发现 {len(issues)} 处潜在隐患】:")
            for issue in issues[:8]:
                self.log(f"   {issue}")
            msg = "\n".join(issues[:6])
            if len(issues) > 6:
                msg += f"\n...及另外 {len(issues)-6} 处问题"
            messagebox.showwarning("规则健康告警", f"发现以下潜在问题，建议排查：\n\n{msg}")

    def start_global_hotkey_listener(self):
        # 移除窗口焦点下的重复 F7 绑定，由底层全局钩子统一响应并防抖，避免暂停即刻恢复
        self.root.bind_all("<F8>", lambda e: self.safe_start_bot())
        self.root.bind_all("<F9>", lambda e: self.safe_stop_bot())

        if KEYBOARD_AVAILABLE:
            try:
                keyboard.add_hotkey('f7', self.toggle_pause, suppress=False)
                keyboard.add_hotkey('f8', self.safe_start_bot, suppress=False)
                keyboard.add_hotkey('f9', self.safe_stop_bot, suppress=False)
                self.log("⚡ [全局热键就绪] 驱动级键盘钩子已加载！按 [F7] 暂停、[F8] 启动、[F9] 停止！")
                return
            except Exception as e:
                self.log(f"⚠️ keyboard 钩子注册提示: {e}，启用底层监听。")

        def _global_poller():
            user32 = ctypes.windll.user32
            VK_F7 = 0x76
            VK_F8 = 0x77
            VK_F9 = 0x78
            while True:
                time.sleep(0.025)
                try:
                    if user32.GetAsyncKeyState(VK_F7) & 0x8000:
                        self.toggle_pause()
                        time.sleep(0.4)
                    if user32.GetAsyncKeyState(VK_F8) & 0x8000:
                        self.safe_start_bot()
                        time.sleep(0.4)
                    if user32.GetAsyncKeyState(VK_F9) & 0x8000:
                        self.safe_stop_bot()
                        time.sleep(0.4)
                except Exception:
                    pass

        threading.Thread(target=_global_poller, daemon=True).start()
        self.log("💡 [全局热键就绪] Win32 底层全局监听已激活 (F8 启动 / F9 停止)！")

    def log(self, message):
        try:
            self.root.after(0, self._log_ui, message)
        except Exception:
            print(f"[{time.strftime('%H:%M:%S')}] {message}")

    def _log_ui(self, message):
        try:
            self.log_box.config(state=tk.NORMAL)
            line_count = int(float(self.log_box.index('end-1c').split('.')[0]))
            if line_count > 2000:
                delete_lines = line_count - 1800
                if delete_lines > 0:
                    self.log_box.delete("1.0", f"{delete_lines + 1}.0")
            self.log_box.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.log_box.see(tk.END)
            self.log_box.config(state=tk.DISABLED)
            
            # 安全留证：同步持久化落盘至 screenscan_rpa.log (带 5MB 自动轮转)
            try:
                log_p = "screenscan_rpa.log"
                if os.path.exists(log_p) and os.path.getsize(log_p) > 5 * 1024 * 1024:
                    backup_p = "screenscan_rpa.log.1"
                    if os.path.exists(backup_p):
                        try: os.remove(backup_p)
                        except Exception: pass
                    os.rename(log_p, backup_p)
                with open(log_p, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
            except Exception:
                pass
        except Exception:
            pass

    def test_single_rule_detection(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选中一条规则，然后点击测试！")
            return
        r_id = sel[0]
        rule = next((r for r in self.rules if r["id"] == r_id), None)
        if not rule:
            return

        def _worker():
            self.log(f"🔍 正在测试步骤【{rule['name']}】...")
            region = getattr(self, "target_region", None)
            screenshot = ImageGrab.grab(bbox=region)
            screen_np = np.array(screenshot)
            screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)

            ret = self.detect_single_rule(rule, screenshot, screen_gray)
            matched, info, coord, score = ret[:4]
            cand = ret[4] if len(ret) == 5 else None

            if matched:
                self.log(f"🎉 【测试成功！】{info} (得分: {int(score * 100)}%)")
                if coord:
                    ox = cand.get("offset_x", rule.get("offset_x", 0)) if cand else rule.get("offset_x", 0)
                    oy = cand.get("offset_y", rule.get("offset_y", 0)) if cand else rule.get("offset_y", 0)
                    rx = region[0] if region else 0
                    ry = region[1] if region else 0
                    tx, ty = coord[0] + rx + ox, coord[1] + ry + oy
                    try:
                        pyautogui.moveTo(tx, ty, duration=0.25)
                    except Exception:
                        pass
                    cand_info = f"\n命中胜出候选图: 【{cand.get('name')}】(优先级 P{cand.get('priority')})" if cand else ""
                    self.root.after(0, lambda: messagebox.showinfo("检测成功", f"🎉 成功找到目标！{cand_info}\n{info}\n物理中心: ({coord[0] + rx}, {coord[1] + ry})\n含偏移: ({tx}, {ty})\n相似得分: {int(score * 100)}%\n光标已平滑移动到该位置！"))
                else:
                    self.root.after(0, lambda: messagebox.showinfo("检测成功", f"🎉 规则条件满足！\n{info}"))
            else:
                self.log(f"❌ 【测试未命中】{info}")
                self.root.after(0, lambda: messagebox.showwarning("检测未命中", f"未找到目标！原因分析：\n{info}"))

        threading.Thread(target=_worker, daemon=True).start()

    def detect_single_rule(self, rule, screenshot_pil, screen_gray):
        r_type = rule.get("type", "image")
        target = rule.get("target", "")

        if r_type == "image":
            candidates = rule.get("candidates") or []
            if candidates:
                # 同一个动作放入多张图片，全部识别一次，按优先级执行
                matched_cands = []
                for c in candidates:
                    if not c.get("enabled", True):
                        continue
                    p_raw = c.get("image_path", "").strip()
                    if not p_raw:
                        continue
                    paths = [p.strip() for p in p_raw.replace("|", ";").split(";") if p.strip()]
                    c_conf = float(c.get("confidence", rule.get("confidence", 0.70)))
                    c_matched = False
                    c_best_score = 0.0
                    c_best_coord = None
                    c_best_info = ""
                    missing_paths = [p for p in paths if not os.path.exists(p)]
                    valid_paths = [p for p in paths if os.path.exists(p)]
                    if missing_paths and not valid_paths:
                        self.log(f"⚠️ 【候选图文件缺失】步骤【{rule.get('name')}】候选[{c.get('name') or '图'}]文件缺失: {', '.join(missing_paths)}")

                    for p in valid_paths:
                        matched, info, coord, sc = self._match_template(p, screen_gray, c_conf)
                        if matched and sc > c_best_score:
                            c_matched = True
                            c_best_score = sc
                            c_best_coord = coord
                            c_best_info = f"图片[{c.get('name') or os.path.basename(p)}]: {info}"
                    if c_matched:
                        matched_cands.append({
                            "candidate": c,
                            "coord": c_best_coord,
                            "score": c_best_score,
                            "info": c_best_info,
                            "priority": int(c.get("priority", 1))
                        })

                if matched_cands:
                    # 严格按优先级从高到低 (数字 1 为最高优先级，相同优先级按相似得分降序)
                    matched_cands.sort(key=lambda x: (x["priority"], -x["score"]))
                    win = matched_cands[0]
                    win_c = win["candidate"]
                    c_name = win_c.get("name") or os.path.basename(win_c.get("image_path", "候选图"))
                    c_act = win_c.get("action", rule.get("action", "click"))
                    summary = f"【同动作多图识别】在 {len(candidates)} 张图片中识别到 {len(matched_cands)} 张，按优先级 P{win['priority']} 胜出: [{c_name}] -> 触发专属动作: {c_act}"
                    return True, summary, win["coord"], win["score"], win_c
                else:
                    return False, f"同动作内 {len(candidates)} 张候选图片本次扫描均未命中", None, 0.0, None

            # 普通单图或分号多图
            paths = [p.strip() for p in target.replace("|", ";").split(";") if p.strip()]
            if not paths:
                return False, "未填写目标图片路径", None, 0.0, None
            missing_paths = [p for p in paths if not os.path.exists(p)]
            valid_paths = [p for p in paths if os.path.exists(p)]
            if missing_paths and not valid_paths:
                return False, f"目标图片文件缺失: {', '.join(missing_paths)}", None, 0.0, None

            best_score = 0.0
            best_res = (False, f"候选图片未命中(共{len(paths)}张)", None, 0.0, None)
            for p in valid_paths:
                matched, info, coord, sc = self._match_template(p, screen_gray, float(rule.get("confidence", 0.70)))
                if matched and sc > best_score:
                    best_score = sc
                    best_res = (True, f"多图匹配成功[{os.path.basename(p)}]: {info}", coord, sc, None)
            return best_res

        elif r_type == "image_vanish":
            paths = [p.strip() for p in target.replace("|", ";").split(";") if p.strip()]
            if not paths:
                return False, "未填写目标图片路径", None, 0.0, None
            missing_paths = [p for p in paths if not os.path.exists(p)]
            valid_paths = [p for p in paths if os.path.exists(p)]
            if missing_paths and not valid_paths:
                return False, f"目标图片文件缺失: {', '.join(missing_paths)}", None, 0.0, None
            any_exists = False
            last_info = ""
            for p in valid_paths:
                matched, info, coord, sc = self._match_template(p, screen_gray, float(rule.get("confidence", 0.70)))
                if matched:
                    any_exists = True
                    last_info = info
                    break
            if not any_exists:
                return True, "目标图片均已在屏幕上消失！(反向消失触发满足)", None, 0.85, None
            else:
                return False, f"目标图片仍在屏幕上 ({last_info})", None, 0.0, None

        elif r_type == "text":
            kws = [k.strip() for k in target.replace("|", ";").split(";") if k.strip()]
            if not kws:
                return False, "未填写要识别的文字关键词", None, 0.0, None
            if not WINOCR_AVAILABLE:
                return False, "系统未加载 winocr 模块", None, 0.0, None

            def fuzzy_match(kw, txt):
                kw = kw.strip().lower().replace(" ", "")
                txt = txt.strip().lower().replace(" ", "")
                if not kw or not txt:
                    return False
                if kw in txt or txt in kw:
                    return True
                sub_pairs = [("确走", "确定"), ("确让", "确认"), ("0", "o"), ("l", "1"), ("已", "己"), ("日", "曰")]
                for p1, p2 in sub_pairs:
                    txt = txt.replace(p1, p2)
                    kw = kw.replace(p1, p2)
                if kw in txt:
                    return True
                common = sum(1 for c in kw if c in txt)
                if len(kw) <= 2:
                    return common >= len(kw)
                else:
                    return (common / len(kw)) >= 0.65

            try:
                pil_images = [screenshot_pil]
                try:
                    np_img = np.array(screenshot_pil)
                    gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)
                    
                    resized = cv2.resize(gray, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8,8))
                    enhanced = clahe.apply(resized)
                    pil_images.append(Image.fromarray(enhanced))

                    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                    otsu_res = cv2.resize(otsu, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                    pil_images.append(Image.fromarray(otsu_res))

                    inv_otsu = cv2.bitwise_not(otsu)
                    inv_res = cv2.resize(inv_otsu, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                    pil_images.append(Image.fromarray(inv_res))
                except Exception:
                    pass

                found_all = []
                for idx, p_img in enumerate(pil_images):
                    result = winocr.recognize_pil_sync(p_img, 'zh-Hans-CN')
                    res_lines = result.get('lines') if hasattr(result, 'get') else getattr(result, 'lines', None)
                    if result and res_lines:
                        for line in res_lines:
                            txt = (line.get('text') if hasattr(line, 'get') else getattr(line, 'text', '')).strip()
                            found_all.append(txt)
                            for kw in kws:
                                if fuzzy_match(kw, txt):
                                    words = line.get('words') if hasattr(line, 'get') else getattr(line, 'words', [])
                                    if words:
                                        w0 = getattr(words[0], 'bounding_rect', None) or (words[0].get('bounding_rect') if hasattr(words[0], 'get') else None)
                                        w1 = getattr(words[-1], 'bounding_rect', None) or (words[-1].get('bounding_rect') if hasattr(words[-1], 'get') else None)
                                        w0_x = getattr(w0, 'x', 0) if hasattr(w0, 'x') else (w0.get('x', 0) if w0 else 0)
                                        w0_y = getattr(w0, 'y', 0) if hasattr(w0, 'y') else (w0.get('y', 0) if w0 else 0)
                                        w1_x = getattr(w1, 'x', 0) if hasattr(w1, 'x') else (w1.get('x', 0) if w1 else 0)
                                        w1_y = getattr(w1, 'y', 0) if hasattr(w1, 'y') else (w1.get('y', 0) if w1 else 0)
                                        w1_w = getattr(w1, 'width', 0) if hasattr(w1, 'width') else (w1.get('width', 0) if w1 else 0)
                                        w1_h = getattr(w1, 'height', 0) if hasattr(w1, 'height') else (w1.get('height', 0) if w1 else 0)
                                        cx = (w0_x + w1_x + w1_w) // 2
                                        cy = (w0_y + w1_y + w1_h) // 2
                                        scale = 1.0 if idx == 0 else 2.0
                                        cx, cy = int(cx / scale), int(cy / scale)
                                    else:
                                        cx, cy = 0, 0
                                    variant_name = ["原图", "CLAHE增强", "Otsu二值", "反色二值"][idx] if idx < 4 else "预处理"
                                    sc = 1.0 if kw == txt else (0.95 if kw in txt else 0.82)
                                    return True, f"智能OCR({variant_name})识别 '{kw}' (文本: '{txt}')", (cx, cy), sc, None
                sample = " | ".join(list(set(found_all))[:8]) if found_all else "无"
                return False, f"未匹配关键词 {kws}。OCR识别到: [{sample}]", None, 0.0, None
            except Exception as e:
                return False, f"智能OCR异常: {e}", None, 0.0, None

        elif r_type == "color":
            try:
                parts = [p.strip() for p in target.split(",")]
                if len(parts) >= 3:
                    cx, cy = int(parts[0]), int(parts[1])
                    hex_expect = parts[2].lower()
                    rgb_actual = screenshot_pil.getpixel((cx, cy))
                    hex_actual = "#{:02x}{:02x}{:02x}".format(rgb_actual[0], rgb_actual[1], rgb_actual[2])
                    if hex_expect == hex_actual:
                        return True, f"坐标 ({cx}, {cy}) 颜色完全匹配: {hex_actual}", (cx, cy), 1.0, None
                    else:
                        return False, f"坐标 ({cx}, {cy}) 实际颜色 {hex_actual} != 预期 {hex_expect}", None, 0.0, None
            except Exception as e:
                return False, f"颜色解析失败(需为 X,Y,#HEX): {e}", None, 0.0, None

        elif r_type == "timer":
            t_interval = float(rule.get("timer_interval", 15.0))
            rule_id = rule.get("id", "timer_default")
            last_t = getattr(self, "timer_records", {}).get(rule_id, 0.0)
            now = time.time()
            if now - last_t >= t_interval:
                self.timer_records[rule_id] = now
                return True, f"定时周期触发到达 (每 {t_interval}s 触发一次)", None, 0.5, None
            else:
                remain = round(t_interval - (now - last_t), 1)
                return False, f"定时周期未到达 (倒计时 {remain}s)", None, 0.0, None

        return False, "未知识别类型", None, 0.0, None

    def _match_template(self, target_path, screen_gray, threshold):
        try:
            if not hasattr(self, 'template_cache'):
                self.template_cache = {}

            mtime = os.path.getmtime(target_path) if os.path.exists(target_path) else 0
            cached = self.template_cache.get(target_path)
            if cached and cached.get("mtime") == mtime:
                t_gray = cached["gray"]
                th_h, th_w = cached["size"]
            else:
                with open(target_path, "rb") as f:
                    t_bytes = bytearray(f.read())
                t_np = np.asarray(t_bytes, dtype=np.uint8)
                t_cv = cv2.imdecode(t_np, cv2.IMREAD_COLOR)
                if t_cv is None:
                    return False, "图片文件解码失败", None, 0.0

                t_gray = cv2.cvtColor(t_cv, cv2.COLOR_BGR2GRAY)
                th_h, th_w = t_gray.shape
                self.template_cache[target_path] = {
                    "img": t_cv,
                    "gray": t_gray,
                    "size": (th_h, th_w),
                    "mtime": mtime
                }
            scr_h, scr_w = screen_gray.shape

            if th_w >= scr_w or th_h >= scr_h:
                return False, "模板尺寸超过全屏尺寸，请框选局部小图标！", None, 0.0

            best_val = -1
            best_loc = None
            best_w, best_h = th_w, th_h

            scales = [1.0, 0.92, 1.08, 0.85, 1.15]
            for scale in scales:
                if scale == 1.0:
                    scaled_t = t_gray
                else:
                    nw, nh = int(th_w * scale), int(th_h * scale)
                    if nw >= scr_w or nh >= scr_h or nw < 5 or nh < 5:
                        continue
                    scaled_t = cv2.resize(t_gray, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)

                res = cv2.matchTemplate(screen_gray, scaled_t, cv2.TM_CCOEFF_NORMED)
                min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
                if max_v > best_val:
                    best_val = max_v
                    best_loc = max_l
                    best_w, best_h = scaled_t.shape[1], scaled_t.shape[0]

            best_pct = round(best_val * 100, 1)
            th_pct = round(threshold * 100, 1)

            if best_val >= threshold:
                cx = best_loc[0] + best_w // 2
                cy = best_loc[1] + best_h // 2
                return True, f"多尺度匹配达到 {best_pct}% (>= 阈值 {th_pct}%)", (cx, cy), float(best_val)
            else:
                return False, f"最高相似度 {best_pct}% (阈值需达到 {th_pct}%)", None, float(max(0.0, best_val))

        except Exception as e:
            return False, f"模板匹配异常: {e}", None, 0.0

    def start_bot(self):
        if not self.rules:
            messagebox.showerror("提示", "请至少添加一条规则！")
            return
        if self.running:
            return

        self.running = True
        self.paused = False
        self.workflow_target_id = None
        self.workflow_target_deadline = 0
        self.locked_rule_id = None
        self.lock_expire_time = 0
        self.action_counter = 0
        self.bot_start_time = time.time()
        self.last_action_timestamp = time.time()
        self.heartbeat = time.time()
        
        self.dry_run = bool(self.dry_run_var.get())
        try:
            self.bot_interval = float(self.interval_entry.get())
        except Exception:
            self.bot_interval = 0.8
            
        try:
            self.max_actions = int(self.max_runs_entry.get())
        except Exception:
            self.max_actions = 0
            
        try:
            dur_m = float(self.max_duration_entry.get())
            self.max_duration_seconds = dur_m * 60.0 if dur_m > 0 else 0
        except Exception:
            self.max_duration_seconds = 0

        self.btn_start.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.NORMAL, text="⏸ 暂停 (F7)", bg="#f59e0b", fg="black")
        self.btn_stop.config(state=tk.NORMAL)
        
        mode_str = "【🛡️ Dry-Run 仿真试运行模式 - 绝不真实点击】" if self.dry_run else "【⚡ 物理驱动模式】"
        cap_str = f" | 执行上限: {self.max_actions} 次" if self.max_actions > 0 else ""
        if self.max_duration_seconds > 0:
            cap_str += f" | 时长上限: {round(self.max_duration_seconds/60, 1)}分钟"
        self.rule_last_fire = {}
        self.log(f"🚀 [状态机已启动] {mode_str}{cap_str} 正在监控工作流... 按 [F7] 暂停 / [F9] 停止。")

        threading.Thread(target=self.run_state_machine_loop, daemon=True).start()

    def stop_bot(self):
        if not self.running:
            return
        self.running = False
        self.paused = False
        self.workflow_target_id = None
        self.locked_rule_id = None
        def _ui_stop():
            try:
                self.btn_start.config(state=tk.NORMAL)
                self.btn_pause.config(state=tk.DISABLED, text="⏸ 暂停 (F7)")
                self.btn_stop.config(state=tk.DISABLED)
            except Exception:
                pass
        self.root.after(0, _ui_stop)
        self.log(f"⏹ [已停止] 监控已停止 (本次共触发 {self.action_counter} 次动作)。随时按 [F8] 恢复。")

    def run_state_machine_loop(self):
        interval = getattr(self, "bot_interval", 0.8)

        id_to_rule = {r["id"]: r for r in self.rules}

        while self.running:
            self.heartbeat = time.time()
            if self.paused:
                time.sleep(0.25)
                continue
            try:
                now = time.time()

                if self.max_duration_seconds > 0 and (now - self.bot_start_time) >= self.max_duration_seconds:
                    self.log(f"⏰ 【已达运行时长上限】已运行 {round((now - self.bot_start_time)/60.0, 1)} 分钟，安全终止脚本！")
                    self.stop_bot()
                    break

                if self.workflow_target_id:
                    if self.workflow_target_deadline > 0 and now > self.workflow_target_deadline:
                        target_r = id_to_rule.get(self.workflow_target_id)
                        t_name = target_r["name"] if target_r else self.workflow_target_id
                        
                        timeout_fallback_id = target_r.get("timeout_target_id") if target_r else None
                        if timeout_fallback_id:
                            fallback_r = id_to_rule.get(timeout_fallback_id)
                            if fallback_r and fallback_r.get("enabled", True):
                                self.log(f"⏱️ 【限时未命中】等待步骤【{t_name}】超时！触发备用动作 -> 立即执行【{fallback_r['name']}】")
                                region = getattr(self, "target_region", None)
                                screenshot = ImageGrab.grab(bbox=region)
                                screen_np = np.array(screenshot)
                                screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
                                ret = self.detect_single_rule(fallback_r, screenshot, screen_gray)
                                matched, info, coord, score = ret[:4]
                                cand = ret[4] if len(ret) == 5 else None
                                rx = region[0] if region else 0
                                ry = region[1] if region else 0
                                ox = cand.get("offset_x", fallback_r.get("offset_x", 0)) if cand else fallback_r.get("offset_x", 0)
                                oy = cand.get("offset_y", fallback_r.get("offset_y", 0)) if cand else fallback_r.get("offset_y", 0)
                                final_coord = (coord[0] + rx + ox, coord[1] + ry + oy) if coord else None
                                if matched or fallback_r.get("action") in ("sound_alarm",):
                                    self.execute_smart_action(final_coord, fallback_r, candidate=cand)
                                    self.last_action_timestamp = time.time()
                                else:
                                    self.log(f"⚠️ 【兜底未命中】超时兜底规则【{fallback_r['name']}】目标未在画面中出现，放弃触发以防误动作。")
                                self.workflow_target_id = None
                                self.workflow_target_deadline = 0
                            else:
                                self.workflow_target_id = None
                                active_rules = [r for r in self.rules if r.get("enabled", True)]
                        else:
                            self.log(f"⚠️ 【流转超时】指定等待步骤【{t_name}】超时！自动重置为全局自由循环。")
                            self.workflow_target_id = None
                            active_rules = [r for r in self.rules if r.get("enabled", True)]
                    else:
                        target_r = id_to_rule.get(self.workflow_target_id)
                        if target_r and target_r.get("enabled", True):
                            remain_s = round(self.workflow_target_deadline - now, 1) if self.workflow_target_deadline > 0 else "无限"
                            active_rules = [target_r]
                            if now - getattr(self, "_last_chain_wait_log", 0) > 4.0:
                                self.log(f"🔀 【链式等待中】仅等待指定下一步【{target_r['name']}】(超时倒计时: {remain_s}s)")
                                self._last_chain_wait_log = now
                        else:
                            self.workflow_target_id = None
                            active_rules = [r for r in self.rules if r.get("enabled", True)]
                else:
                    if self.locked_rule_id and now < self.lock_expire_time:
                        remaining = round(self.lock_expire_time - now, 1)
                        active_rules = [r for r in self.rules if r["id"] == self.locked_rule_id and r.get("enabled", True)]
                        if now - getattr(self, "_last_lock_log", 0) > 4.0:
                            self.log(f"🔒 【独占锁定中】当前仅执行独占步骤【{active_rules[0]['name']}】(剩余 {remaining} 秒)")
                            self._last_lock_log = now
                    else:
                        self.locked_rule_id = None
                        active_rules = [r for r in self.rules if r.get("enabled", True)]

                region = getattr(self, "target_region", None)
                screenshot = ImageGrab.grab(bbox=region)
                screen_np = np.array(screenshot)
                screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)

                matched_any = False
                candidates = []

                for r in active_rules:
                    if not self.running:
                        break

                    r_cd = float(r.get("cooldown", 0.0))
                    if r_cd > 0 and (now - self.rule_last_fire.get(r["id"], 0.0)) < r_cd:
                        continue

                    ret = self.detect_single_rule(r, screenshot, screen_gray)
                    is_match, info, coord, score = ret[:4]
                    cand = ret[4] if len(ret) == 5 else None

                    if is_match:
                        candidates.append({
                            "rule": r,
                            "info": info,
                            "coord": coord,
                            "score": float(score),
                            "priority": int(r.get("priority", 1)),
                            "candidate": cand
                        })

                if candidates and self.running:
                    matched_any = True
                    self.last_action_timestamp = time.time()

                    # 智能并发冲突仲裁
                    arb_mode = self.arbitration_mode_var.get().split(" ")[0]
                    if len(candidates) > 1:
                        if arb_mode == "confidence":
                            candidates.sort(key=lambda x: (-x["score"], x["priority"]))
                            strat_desc = "【置信度最高】"
                        elif arb_mode == "order":
                            strat_desc = "【列表顺序】"
                        else:
                            candidates.sort(key=lambda x: (x["priority"], -x["score"]))
                            strat_desc = "【权重优先级最高 (数字1最高)】"

                        winner = candidates[0]
                        self.log(f"⚡ 【多动作并发冲突仲裁】同屏检测到 {len(candidates)} 个满足条件的动作：")
                        for idx, c in enumerate(candidates):
                            status_tag = "🏆【胜出执行】" if idx == 0 else "🛡️【智能抑制】"
                            self.log(f"   {status_tag} 步骤:【{c['rule']['name']}】| P{c['priority']} | 得分: {int(c['score']*100)}%")
                        self.log(f"🎯 仲裁结果: 依据{strat_desc}策略，采纳【{winner['rule']['name']}】(P{winner['priority']}) 优先执行！其余动作安全避让。")
                    else:
                        winner = candidates[0]

                    r = winner["rule"]
                    coord = winner["coord"]
                    info = winner["info"]
                    cand = winner.get("candidate")
                    ox = cand.get("offset_x", r.get("offset_x", 0)) if cand else r.get("offset_x", 0)
                    oy = cand.get("offset_y", r.get("offset_y", 0)) if cand else r.get("offset_y", 0)
                    rx = region[0] if region else 0
                    ry = region[1] if region else 0
                    final_coord = (coord[0] + rx + ox, coord[1] + ry + oy) if coord else None

                    self.log(f"🎯 触发步骤【{r['name']}】(P{winner['priority']})! {info} | 坐标: {final_coord}")
                    self.rule_last_fire[r["id"]] = time.time()
                    self.execute_smart_action(final_coord, r, candidate=cand)

                    # 候选级「终止脚本」优先判断
                    if cand and cand.get("next_mode") == "stop":
                        self.log("🏁 【候选终结】命中候选图专属终止设置 -> 自动终止脚本！")
                        self.stop_bot()
                        return

                    # 若该候选图片配置了专属跳转步骤，优先使用
                    cand_jump = cand.get("next_target_id") if cand else None
                    if cand_jump:
                        next_r = id_to_rule.get(cand_jump)
                        timeout_s = float(r.get("next_timeout", 20.0))
                        self.workflow_target_id = cand_jump
                        self.workflow_target_deadline = time.time() + timeout_s if timeout_s > 0 else 0
                        next_name = next_r["name"] if next_r else cand_jump
                        self.log(f"🔀 【图片专属流转】命中候选图专属跳转 -> 进入下一步【{next_name}】(限时: {timeout_s}秒)！")
                    else:
                        flow_mode = r.get("next_mode", "loop")
                        if flow_mode == "stop":
                            self.log("🏁 【工作流完成】步骤设定执行后终止脚本。已自动停止！")
                            self.stop_bot()
                            return

                        elif flow_mode == "jump" and r.get("next_target_id"):
                            next_id = r["next_target_id"]
                            next_r = id_to_rule.get(next_id)
                            timeout_s = float(r.get("next_timeout", 20.0))
                            
                            self.workflow_target_id = next_id
                            self.workflow_target_deadline = time.time() + timeout_s if timeout_s > 0 else 0
                            
                            next_name = next_r["name"] if next_r else next_id
                            self.log(f"🔀 【步骤链式流转】完成【{r['name']}】-> 进入下一步【{next_name}】(限时: {timeout_s}秒)！")

                        elif flow_mode == "sequence":
                            all_enabled = [ru for ru in self.rules if ru.get("enabled", True)]
                            if all_enabled:
                                try:
                                    curr_idx = next(i for i, ru in enumerate(all_enabled) if ru["id"] == r["id"])
                                    next_idx = (curr_idx + 1) % len(all_enabled)
                                    next_rule = all_enabled[next_idx]
                                    self.workflow_target_id = next_rule["id"]
                                    self.workflow_target_deadline = time.time() + 15.0
                                    self.log(f"🔄 【顺序流转】完成【{r['name']}】-> 顺延至【{next_rule['name']}】")
                                except Exception:
                                    self.workflow_target_id = None
                                    self.workflow_target_deadline = 0
                            else:
                                self.workflow_target_id = None
                                self.workflow_target_deadline = 0

                        else:  # loop 语义：重置为自由全规则循环
                            self.workflow_target_id = None
                            self.workflow_target_deadline = 0

                    lock_duration = float(r.get("lock_exclusive", 0.0))
                    if lock_duration > 0:
                        self.locked_rule_id = r["id"]
                        self.lock_expire_time = time.time() + lock_duration
                        self.log(f"🔒 【独占锁定】接下来的 {lock_duration} 秒内独占此动作！")

                    cooldown = float(r.get("cooldown", 0.0))
                    if cooldown > 0:
                        time.sleep(cooldown)
                    else:
                        time.sleep(0.08)  # 即使无冷却也微休眠，防止0秒规则连点打死CPU

                if not matched_any:
                    time.sleep(interval)

            except Exception as e:
                self.log(f"状态机巡检异常: {e}")
                time.sleep(interval)

    def hardware_click(self, x, y, button="left", hold_time=0.15, humanize=True):
        ix, iy = int(x), int(y)
        if humanize:
            ix += random.randint(-2, 2)
            iy += random.randint(-2, 2)
            hold_time = random.uniform(0.12, 0.18)

        user32 = ctypes.windll.user32
        user32.SetCursorPos(ix, iy)
        try:
            pyautogui.moveTo(ix, iy, duration=0.06)
        except Exception:
            pass
        time.sleep(0.04)

        hwnd = activate_target_window(ix, iy)
        time.sleep(0.04)

        down_flag = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
        up_flag = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
        
        inp_down = INPUT()
        inp_down.type = INPUT_MOUSE
        inp_down.mi.dwFlags = down_flag
        user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
        
        time.sleep(hold_time)

        inp_up = INPUT()
        inp_up.type = INPUT_MOUSE
        inp_up.mi.dwFlags = up_flag
        user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))

    def execute_smart_action(self, coord, rule, candidate=None):
        action = (candidate.get("action") if candidate else None) or rule.get("action", "click")
        param = (candidate.get("action_param") if candidate else None) if (candidate and candidate.get("action_param")) else rule.get("action_param", "")
        humanize = rule.get("humanize", True)

        ix, iy = coord if coord else (0, 0)

        # 护栏1: 排除工具自身窗口，防止点到自己的 UI 导致混乱
        if coord:
            try:
                rx = self.root.winfo_rootx()
                ry = self.root.winfo_rooty()
                rw = self.root.winfo_width()
                rh = self.root.winfo_height()
                if (rx <= ix <= rx + rw) and (ry <= iy <= ry + rh):
                    self.log(f"🛑 【安全熔断】目标坐标 ({ix}, {iy}) 位于本软件自身窗口内！已自动拦截，防止点到自己。")
                    return
            except Exception:
                pass

        # 护栏2: Dry-Run 仿真演练拦截
        if getattr(self, "dry_run", False):
            self.log(f"🛡️ 【DRY-RUN 试运行】模拟执行动作【{action}】坐标: ({ix}, {iy})，已拦截物理动作！")
            return

        # 护栏3: 执行次数计数与上限熔断
        self.action_counter += 1
        if self.max_actions > 0 and self.action_counter >= self.max_actions:
            self.log(f"🏁 【达到保护上限】已完成 {self.action_counter} 次操作，触发安全保护自动停机！")
            self.stop_bot()

        try:
            if action == "click" and coord:
                self.hardware_click(ix, iy, button="left", humanize=humanize)
                self.log(f"🖱️ 【四重穿透物理单击完成】: ({ix}, {iy})")

            elif action == "double_click" and coord:
                self.hardware_click(ix, iy, button="left", humanize=humanize)
                time.sleep(0.08)
                self.hardware_click(ix, iy, button="left", humanize=humanize)
                self.log(f"🖱️ 【四重穿透物理双击完成】: ({ix}, {iy})")

            elif action == "right_click" and coord:
                self.hardware_click(ix, iy, button="right", humanize=humanize)
                self.log(f"🖱️ 【四重穿透物理右键完成】: ({ix}, {iy})")

            elif action == "hover" and coord:
                pyautogui.moveTo(ix, iy, duration=0.2)
                self.log(f"🖱️ 【已执行】鼠标平滑悬停: ({ix}, {iy})")

            elif action == "scroll_down":
                amt = int(param) if param.isdigit() else 300
                pyautogui.scroll(-amt)
                self.log(f"🖱️ 【已执行】向下滚动滚轮 {amt} 行")

            elif action == "scroll_up":
                amt = int(param) if param.isdigit() else 300
                pyautogui.scroll(amt)
                self.log(f"🖱️ 【已执行】向上滚动滚轮 {amt} 行")

            elif action == "press_enter":
                if coord:
                    self.hardware_click(ix, iy, humanize=humanize)
                    time.sleep(0.1)
                pyautogui.press('enter')
                self.log("⌨️ 【已执行】按下 Enter 回车键")

            elif action == "hotkey" and param:
                keys = [k.strip().lower() for k in param.split("+")]
                pyautogui.hotkey(*keys)
                self.log(f"⌨️ 【已执行】触发快捷键: {' + '.join(keys)}")

            elif action == "type_text" and param:
                if coord:
                    self.hardware_click(ix, iy, humanize=humanize)
                    time.sleep(0.1)
                pyautogui.write(param)
                self.log(f"⌨️ 【已执行】模拟输入: '{param}'")

            elif action == "sound_alarm":
                try:
                    import winsound
                    winsound.Beep(1000, 300)
                except Exception:
                    pass
                self.log("🔊 【已触发】蜂鸣警报音！")

            elif action == "take_screenshot":
                p = os.path.join(os.getcwd(), f"evidence_{int(time.time())}.png")
                ImageGrab.grab().save(p)
                self.log(f"📷 【已存盘】截图证据: {os.path.basename(p)}")

        except Exception as e:
            self.log(f"❌ 动作执行异常: {e}")

if __name__ == "__main__":
    # 单实例运行互斥保护 (避免双开互抢鼠标和覆盖 JSON)
    _mutex = None
    if sys.platform == "win32":
        try:
            import ctypes
            _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "ScreenScanRPA_SingleInstance_Mutex")
            if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                import tkinter.messagebox as mb
                mb.showerror("重复运行", "⚠️ ScreenScan RPA 已有一个实例在运行中！\n请勿同时启动多个实例，以防按键和鼠标冲突。")
                sys.exit(0)
        except Exception:
            pass

    root = tk.Tk()
    app = RealScreenScanBot(root)
    root.mainloop()
