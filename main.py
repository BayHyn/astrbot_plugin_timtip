import os
import re
import json
import asyncio
from datetime import datetime, timedelta
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp  # 包含 Plain、Image 等组件

# 设置 tim.json 的路径：假设当前工作目录为 AstrBot-master，
# 则文件路径为 AstrBot-master/data/plugins/astrbot_plugin_timtip/tim.json
BASE_DIR = os.getcwd()
TIM_FILE = os.path.join(BASE_DIR, "data", "plugins", "astrbot_plugin_timtip", "tim.json")

def load_tasks():
    if not os.path.exists(TIM_FILE):
        try:
            os.makedirs(os.path.dirname(TIM_FILE), exist_ok=True)
            with open(TIM_FILE, "w", encoding="utf-8") as f:
                # 初始化为空字典，用于按会话存储任务：{umo: {task_id: task_data, ...}, ...}
                json.dump({}, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print("创建 tim.json 文件失败：", e)
        return {}
    try:
        with open(TIM_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_tasks(tasks: dict):
    try:
        with open(TIM_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print("保存 tim.json 失败：", e)

def parse_time(time_str: str) -> tuple:
    """
    解析固定时间格式，要求格式为 "HH时MM分"
    返回 (hour, minute)
    """
    pattern = r'^(\d{1,2})时(\d{1,2})分$'
    match = re.match(pattern, time_str)
    if not match:
        raise ValueError("固定时间格式错误，请使用 'HH时MM分' 格式，例如 20时30分。")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("固定时间范围错误，小时应在 0-23 之间，分钟应在 0-59 之间。")
    return hour, minute

def parse_message(content: str):
    """
    将用户输入内容解析为消息链：
    - 文本中的换行符会被 Plain 消息段保留
    - 使用 [img]URL[/img] 标记表示图片
    """
    chain = []
    pattern = re.compile(r'\[img\](.*?)\[/img\]')
    pos = 0
    for m in pattern.finditer(content):
        start, end = m.span()
        if start > pos:
            text_part = content[pos:start]
            if text_part.strip():
                chain.append(Comp.Plain(text_part))
        img_url = m.group(1).strip()
        if img_url:
            chain.append(Comp.Image.fromURL(img_url))
        pos = end
    if pos < len(content):
        text_part = content[pos:]
        if text_part.strip():
            chain.append(Comp.Plain(text_part))
    return chain

@register("astrbot_plugin_timtip", "IGCrystal", "定时发送消息插件", "1.1.1", "https://github.com/IGCrystal/astrbot_plugin_timtip")
class TimPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 按会话存储任务，格式: { umo: { task_id(str): task_data(dict), ... }, ... }
        self.tasks = load_tasks()
        # 全局任务编号（跨会话唯一）
        self.next_id = 0
        for task_dict in self.tasks.values():
            for tid in task_dict.keys():
                try:
                    tid_int = int(tid)
                    if tid_int >= self.next_id:
                        self.next_id = tid_int + 1
                except Exception:
                    continue
        # 记录已执行 fixed 任务标识，格式: "{umo}_{task_id}_{day}_{hour}_{minute}"
        self.executed_tasks = set()
        self.last_day = (datetime.utcnow() + timedelta(hours=8)).day
        asyncio.create_task(self.scheduler_loop())

    async def scheduler_loop(self):
        """后台调度器，每 10 秒检查一次所有会话中的任务条件"""
        while True:
            now = datetime.utcnow() + timedelta(hours=8)
            current_day = now.day
            if current_day != self.last_day:
                self.executed_tasks.clear()
                self.last_day = current_day

            # 遍历每个会话
            for umo, task_dict in self.tasks.items():
                # 遍历该会话下所有任务
                for tid, task in list(task_dict.items()):
                    if task.get("status", "active") != "active" or not task.get("content"):
                        continue
                    task_type = task.get("type")
                    last_run = task.get("last_run")
                    last_run_dt = datetime.fromisoformat(last_run) if last_run else None

                    if task_type == "interval":
                        try:
                            interval = float(task.get("time"))
                        except ValueError:
                            continue
                        if last_run_dt is None or (now - last_run_dt).total_seconds() >= interval * 60:
                            await self.send_task_message(task)
                            task["last_run"] = now.isoformat()
                    elif task_type == "once":
                        try:
                            delay = float(task.get("time"))
                        except ValueError:
                            continue
                        create_time = datetime.fromisoformat(task.get("create_time"))
                        if now >= create_time + timedelta(minutes=delay):
                            await self.send_task_message(task)
                            del task_dict[tid]
                    elif task_type == "fixed":
                        try:
                            hour, minute = parse_time(task.get("time"))
                        except ValueError as e:
                            print(f"任务 {tid} 时间格式错误: {e}")
                            continue
                        exec_id = f"{umo}_{tid}_{current_day}_{hour}_{minute}"
                        if now.hour == hour and now.minute == minute and exec_id not in self.executed_tasks:
                            await self.send_task_message(task)
                            task["last_run"] = now.isoformat()
                            self.executed_tasks.add(exec_id)
            save_tasks(self.tasks)
            await asyncio.sleep(10)

    async def send_task_message(self, task: dict):
        """构造消息链并发送任务消息"""
        target = task.get("target")
        content = task.get("content")
        if target and content:
            chain = parse_message(content)
            await self.context.send_message(target, chain)

    # 定义指令组 "tim"
    @filter.command_group("tim")
    def tim(self):
        pass

    @tim.command("定时任务")
    async def add_task(self, event: AstrMessageEvent, task_type: str, time_value: str):
        """
        添加定时任务
        示例:
          tim 定时任务 interval 5
          tim 定时任务 fixed 20时30分
          tim 定时任务 once 10
        任务类型：
          interval: 每隔指定分钟发送
          fixed: 每天在指定时间发送 (格式: HH时MM分，UTC+8)
          once: 延迟指定分钟后发送一次
        """
        if task_type == "fixed":
            try:
                parse_time(time_value)
            except ValueError as e:
                yield event.plain_result(str(e))
                return
        elif task_type in ("interval", "once"):
            try:
                float(time_value)
            except ValueError:
                yield event.plain_result(f"{task_type} 类型任务的时间参数应为数字（单位：分钟）。")
                return
        else:
            yield event.plain_result("未知的任务类型，请使用 interval, fixed 或 once。")
            return

        now = datetime.utcnow() + timedelta(hours=8)
        umo = event.unified_msg_origin
        if umo not in self.tasks:
            self.tasks[umo] = {}
        task_data = {
            "type": task_type,
            "time": time_value,
            "content": "",  # 初始为空
            "status": "active",
            "create_time": now.isoformat(),
            "last_run": None,
            "target": umo
        }
        task_id = str(self.next_id)
        self.next_id += 1
        self.tasks[umo][task_id] = task_data
        save_tasks(self.tasks)
        msg = f"任务 {task_id} 已添加（会话: {umo}），类型: {task_type}，时间参数: {time_value}。\n"
        msg += "注意：您还未设置发送内容，请使用 'tim 设置内容 <任务编号> <内容>' 命令设置。"
        yield event.plain_result(msg)

    @tim.command("设置内容")
    async def set_content(self, event: AstrMessageEvent, task_id: int, *, content: str):
        """
        设置指定任务的发送内容
        示例: tim 设置内容 1 第一行\n第二行 [img]https://example.com/image.jpg[/img]
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        if umo not in self.tasks or tid not in self.tasks[umo]:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")
            return
        self.tasks[umo][tid]["content"] = content
        save_tasks(self.tasks)
        yield event.plain_result(f"任务 {tid} 的发送内容已设置。")

    @tim.command("取消")
    async def cancel_task(self, event: AstrMessageEvent, task_id: int):
        """
        取消指定任务
        示例: tim 取消 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        if umo in self.tasks and tid in self.tasks[umo]:
            del self.tasks[umo][tid]
            save_tasks(self.tasks)
            yield event.plain_result(f"任务 {tid} 已取消。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @tim.command("暂停")
    async def pause_task(self, event: AstrMessageEvent, task_id: int):
        """
        暂停指定任务
        示例: tim 暂停 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        if umo in self.tasks and tid in self.tasks[umo]:
            self.tasks[umo][tid]["status"] = "paused"
            save_tasks(self.tasks)
            yield event.plain_result(f"任务 {tid} 已暂停。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @tim.command("启用")
    async def enable_task(self, event: AstrMessageEvent, task_id: int):
        """
        启用被暂停的任务
        示例: tim 启用 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        if umo in self.tasks and tid in self.tasks[umo]:
            self.tasks[umo][tid]["status"] = "active"
            save_tasks(self.tasks)
            yield event.plain_result(f"任务 {tid} 已启用。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @tim.command("清空")
    async def clear_content(self, event: AstrMessageEvent, task_id: int):
        """
        清空指定任务的发送内容
        示例: tim 清空 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        if umo in self.tasks and tid in self.tasks[umo]:
            self.tasks[umo][tid]["content"] = ""
            save_tasks(self.tasks)
            yield event.plain_result(f"任务 {tid} 的发送内容已清空。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @tim.command("help")
    async def show_help(self, event: AstrMessageEvent):
        """
        显示定时任务插件的帮助信息
        示例: tim help
        """
        help_msg = (
            "定时任务插件帮助信息：\n"
            "1. tim 定时任务 <任务种类> <时间>\n"
            "   - interval: 每隔指定分钟发送 (示例: tim 定时任务 interval 5)\n"
            "   - fixed: 每天在指定时间发送，格式 HH时MM分 (示例: tim 定时任务 fixed 20时30分)\n"
            "   - once: 延迟指定分钟后发送一次 (示例: tim 定时任务 once 10)\n"
            "2. tim 设置内容 <任务编号> <内容>  -- 设置任务发送内容（支持换行和 [img]图片URL[/img] 标记）\n"
            "3. tim 取消 <任务编号>              -- 取消任务\n"
            "4. tim 暂停 <任务编号>              -- 暂停任务\n"
            "5. tim 启用 <任务编号>              -- 启用被暂停的任务\n"
            "6. tim 清空 <任务编号>              -- 清空任务发送内容\n"
            "7. tim help                       -- 显示此帮助信息"
        )
        yield event.plain_result(help_msg)
