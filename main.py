import os
import json
import asyncio
from datetime import datetime, timedelta
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain

# 设置 tim.json 的路径：假设当前工作目录为 AstrBot-master，
# 则文件路径为 AstrBot-master/data/plugins/astrbot_plugin_timtip/tim.json
BASE_DIR = os.getcwd()
TIM_FILE = os.path.join(BASE_DIR, "data", "plugins", "astrbot_plugin_timtip", "tim.json")

def load_tasks():
    if not os.path.exists(TIM_FILE):
        # 自动创建一个空的 tim.json 文件所在目录
        try:
            os.makedirs(os.path.dirname(TIM_FILE), exist_ok=True)
            with open(TIM_FILE, "w", encoding="utf-8") as f:
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

@register("astrbot_plugin_timtip", "IGCrystal", "定时发送消息插件", "1.1.1", "https://github.com/IGCrystal/astrbot_plugin_timtip")
class TimPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 加载已有任务（若文件不存在会自动创建）
        self.tasks = load_tasks()  # {任务编号(str): 任务数据(dict)}
        # 自增任务编号，取所有编号的最大值+1
        self.next_id = max([int(k) for k in self.tasks.keys()], default=0) + 1
        # 开启后台任务调度器
        asyncio.create_task(self.scheduler_loop())

    async def scheduler_loop(self):
        """后台调度器，每分钟检查一次任务发送条件"""
        while True:
            now = datetime.utcnow() + timedelta(hours=8)  # 转为UTC+8时间
            for tid, task in list(self.tasks.items()):
                # 仅对 active 状态的任务且设置了内容的任务生效
                if task.get("status", "active") != "active" or not task.get("content"):
                    continue

                task_type = task.get("type")
                last_run = task.get("last_run")  # 字符串格式的时间
                last_run_dt = datetime.fromisoformat(last_run) if last_run else None

                if task_type == "interval":
                    # 每隔 task["time"] 分钟发送一次
                    interval = float(task.get("time"))
                    if last_run_dt is None or (now - last_run_dt).total_seconds() >= interval * 60:
                        await self.send_task_message(task)
                        task["last_run"] = now.isoformat()
                elif task_type == "once":
                    # 只发送一次：如果任务创建后达到指定时间则发送，发送后删除任务
                    create_time = datetime.fromisoformat(task.get("create_time"))
                    delay = float(task.get("time"))
                    if now >= create_time + timedelta(minutes=delay):
                        await self.send_task_message(task)
                        # 删除任务
                        del self.tasks[tid]
                elif task_type == "fixed":
                    # 每天在固定时间发送一次，task["time"] 格式为 "HH:MM"
                    fixed_time = task.get("time")
                    try:
                        hour, minute = map(int, fixed_time.split(":"))
                    except Exception:
                        continue
                    send_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    # 如果当前时间超过设定时间且今日未发送，则发送
                    if now >= send_dt:
                        if last_run_dt is None or last_run_dt.date() < now.date():
                            await self.send_task_message(task)
                            task["last_run"] = now.isoformat()
            save_tasks(self.tasks)
            await asyncio.sleep(60)

    async def send_task_message(self, task: dict):
        """发送任务消息到目标会话"""
        target = task.get("target")
        content = task.get("content")
        if target and content:
            chain = [Plain(content)]
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
          tim 定时任务 fixed 20:30
          tim 定时任务 once 10
        任务类型：
          interval: 间隔任务，每隔指定分钟发送
          fixed: 固定每天在某个时间发送 (格式 HH:MM，UTC+8)
          once: 只发一次，延迟指定分钟后发送
        """
        now = datetime.utcnow() + timedelta(hours=8)
        task_data = {
            "type": task_type,
            "time": time_value,
            "content": "",  # 还未设置发送内容
            "status": "active",  # 默认 active
            "create_time": now.isoformat(),
            "last_run": None,
            "target": event.unified_msg_origin  # 存储当前会话ID，用于主动发送消息
        }
        task_id = str(self.next_id)
        self.next_id += 1
        self.tasks[task_id] = task_data
        save_tasks(self.tasks)
        msg = f"任务 {task_id} 已添加，任务类型: {task_type}，时间参数: {time_value}。\n"
        msg += "注意：您还未设置发送内容，请使用 'tim 设置内容 <任务编号> <内容>' 命令设置。"
        yield event.plain_result(msg)

    @tim.command("设置内容")
    async def set_content(self, event: AstrMessageEvent, task_id: int, *, content: str):
        """
        设置指定任务的发送内容
        示例: tim 设置内容 1 今天天气不错
        """
        tid = str(task_id)
        if tid not in self.tasks:
            yield event.plain_result(f"任务 {tid} 不存在。")
            return
        self.tasks[tid]["content"] = content
        save_tasks(self.tasks)
        yield event.plain_result(f"任务 {tid} 的发送内容已设置。")

    @tim.command("取消")
    async def cancel_task(self, event: AstrMessageEvent, task_id: int):
        """
        取消指定任务
        示例: tim 取消 1
        """
        tid = str(task_id)
        if tid in self.tasks:
            del self.tasks[tid]
            save_tasks(self.tasks)
            yield event.plain_result(f"任务 {tid} 已取消。")
        else:
            yield event.plain_result(f"任务 {tid} 不存在。")

    @tim.command("暂停")
    async def pause_task(self, event: AstrMessageEvent, task_id: int):
        """
        暂停指定任务
        示例: tim 暂停 1
        """
        tid = str(task_id)
        if tid in self.tasks:
            self.tasks[tid]["status"] = "paused"
            save_tasks(self.tasks)
            yield event.plain_result(f"任务 {tid} 已暂停。")
        else:
            yield event.plain_result(f"任务 {tid} 不存在。")

    @tim.command("清空")
    async def clear_content(self, event: AstrMessageEvent, task_id: int):
        """
        清空指定任务的发送内容
        示例: tim 清空 1
        """
        tid = str(task_id)
        if tid in self.tasks:
            self.tasks[tid]["content"] = ""
            save_tasks(self.tasks)
            yield event.plain_result(f"任务 {tid} 的发送内容已清空。")
        else:
            yield event.plain_result(f"任务 {tid} 不存在。")

    @tim.command("help")
    async def show_help(self, event: AstrMessageEvent):
        """
        显示定时任务插件的帮助信息
        示例: tim help
        可用指令：
          tim 定时任务 <任务种类> <时间>  -- 添加任务
          tim 设置内容 <任务编号> <内容>    -- 设置任务发送内容
          tim 取消 <任务编号>              -- 取消任务
          tim 暂停 <任务编号>              -- 暂停任务
          tim 清空 <任务编号>              -- 清空任务发送内容
          tim help                      -- 显示帮助信息
        """
        help_msg = (
            "定时任务插件帮助信息：\n"
            "1. tim 定时任务 <任务种类> <时间>\n"
            "   - interval: 每隔指定分钟发送 (示例: tim 定时任务 interval 5)\n"
            "   - fixed: 每天在指定时间发送，格式 HH:MM (示例: tim 定时任务 fixed 20:30)\n"
            "   - once: 延迟指定分钟后发送一次 (示例: tim 定时任务 once 10)\n"
            "2. tim 设置内容 <任务编号> <内容>  -- 为任务设置发送的内容\n"
            "3. tim 取消 <任务编号>             -- 取消指定任务\n"
            "4. tim 暂停 <任务编号>             -- 暂停指定任务\n"
            "5. tim 清空 <任务编号>             -- 清空指定任务的发送内容\n"
            "6. tim help                      -- 显示本帮助信息"
        )
        yield event.plain_result(help_msg)
