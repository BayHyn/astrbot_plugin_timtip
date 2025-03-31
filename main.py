import os
import re
import json
import asyncio
import logging
import sys
from datetime import datetime, timedelta
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp  # 包含 Plain、Image 等组件


# 日志文件路径
log_file = "./data/plugins/astrbot_plugin_timtip/bot.log"

# 配置日志：同时写入文件和输出到控制台
logging.basicConfig(
    level=logging.DEBUG,  # 记录 DEBUG 及以上级别的日志
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)  # 输出到控制台
    ]
)

logging.info("日志系统初始化完成，日志文件路径: %s", log_file)


@register("astrbot_plugin_timtip", "IGCrystal", "定时发送消息插件", "1.1.1",
          "https://github.com/IGCrystal/astrbot_plugin_timtip")
class TimPlugin(Star):
    # 使用 __file__ 的目录作为基准路径，并转换为绝对路径
    TIM_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "tim.json"))

    def __init__(self, context: Context):
        super().__init__(context)
        # 按会话存储任务：{umo: {task_id(str): task_data(dict), ...}, ...}
        self.tasks = self.__class__.load_tasks()
        # 全局任务编号从 1 开始
        self.next_id = 1
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
        # 启动后台调度器
        asyncio.create_task(self.scheduler_loop())
        logging.debug("TimPlugin 初始化完成，定时任务调度器已启动")

    @staticmethod
    def load_tasks() -> dict:
        if not os.path.exists(TimPlugin.TIM_FILE):
            try:
                os.makedirs(os.path.dirname(TimPlugin.TIM_FILE), exist_ok=True)
                with open(TimPlugin.TIM_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f, ensure_ascii=False, indent=4)
                logging.debug("tim.json 文件不存在，已创建空任务文件。")
            except Exception as e:
                logging.error("创建 tim.json 文件失败：%s", e)
            return {}
        try:
            with open(TimPlugin.TIM_FILE, "r", encoding="utf-8") as f:
                tasks = json.load(f)
                logging.debug("加载任务成功，任务数：%d", sum(len(v) for v in tasks.values()))
                return tasks
        except Exception as e:
            logging.error("读取 tim.json 文件失败：%s", e)
            return {}

    @staticmethod
    def save_tasks(tasks: dict):
        try:
            with open(TimPlugin.TIM_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=4)
            logging.debug("任务保存成功。")
        except Exception as e:
            logging.error("保存 tim.json 失败：%s", e)

    @staticmethod
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

    @staticmethod
    def parse_message(content: str):
        """
        将用户输入内容解析为消息链，只发送纯文本消息，不处理 [img] 标签。
        """
        return [Comp.Plain(content)]

    async def scheduler_loop(self):
        """后台调度器，每 1 秒检查一次所有会话中的任务条件"""
        while True:
            now = datetime.utcnow() + timedelta(hours=8)
            current_day = now.day
            logging.debug("调度器循环运行中，当前时间: %s", now.isoformat())
            if current_day != self.last_day:
                self.executed_tasks.clear()
                self.last_day = current_day
                logging.debug("新的一天，清空固定任务执行记录。")

            # 遍历每个会话的任务
            for umo, task_dict in self.tasks.items():
                logging.debug("检查会话 %s 下的任务: %s", umo, task_dict)
                for tid, task in list(task_dict.items()):
                    if task.get("status", "active") != "active" or not task.get("content", "").strip():
                        continue

                    task_type = task.get("type")
                    last_run = task.get("last_run")
                    last_run_dt = datetime.fromisoformat(last_run) if last_run else None

                    if task_type == "interval":
                        try:
                            interval = float(task.get("time"))
                        except ValueError:
                            logging.error("任务 %s 时间参数解析失败。", tid)
                            continue
                        diff = (now - last_run_dt).total_seconds() if last_run_dt else None
                        logging.debug("检查任务 %s: 当前时间差 = %s秒, 要求 %s秒", tid, diff, interval * 60)
                        if last_run_dt is None or (now - last_run_dt).total_seconds() >= interval * 60:
                            logging.debug("任务 %s 满足条件，准备发送消息。", tid)
                            await self.send_task_message(task)
                            task["last_run"] = now.isoformat()
                    elif task_type == "once":
                        try:
                            delay = float(task.get("time"))
                        except ValueError:
                            logging.error("任务 %s 时间参数解析失败。", tid)
                            continue
                        create_time = datetime.fromisoformat(task.get("create_time"))
                        if now >= create_time + timedelta(minutes=delay):
                            logging.debug("一次性任务 %s 到达发送时间，准备发送消息。", tid)
                            await self.send_task_message(task)
                            logging.debug("一次性任务 %s 执行后将被删除。", tid)
                            del task_dict[tid]
                    elif task_type == "fixed":
                        try:
                            hour, minute = self.__class__.parse_time(task.get("time"))
                        except ValueError as e:
                            logging.error("任务 %s 时间格式错误: %s", tid, e)
                            continue
                        exec_id = f"{umo}_{tid}_{current_day}_{hour}_{minute}"
                        if now.hour == hour and now.minute == minute and exec_id not in self.executed_tasks:
                            logging.debug("固定任务 %s 满足条件，准备发送消息。", tid)
                            await self.send_task_message(task)
                            task["last_run"] = now.isoformat()
                            self.executed_tasks.add(exec_id)
            self.__class__.save_tasks(self.tasks)
            await asyncio.sleep(1)

    async def send_task_message(self, task: dict):
    """构造消息链并发送任务消息"""
    target = task.get("target")
    content = task.get("content")
    if target and content:
        # 先生成一个组件列表（这里只生成纯文本消息）
        components = self.__class__.parse_message(content)
        # 用 MessageChain 包装这些组件
        chain = MessageChain(components)
        logging.debug("准备发送任务消息到目标 %s，内容: %s", target, content)
        try:
            await self.context.send_message(target, chain)
            logging.debug("消息发送成功")
        except Exception as e:
            logging.error("发送消息时出错: %s", e)
    else:
        logging.error("任务内容或目标为空，无法发送消息。")

    # 指令组 "tim"
    @filter.command_group("tim")
    def tim(self):
        pass

    @filter.command("tim 设置定时")
    async def set_timing(self, event: AstrMessageEvent, task_type: str, time_value: str, content: str = ""):
        """
        添加定时任务并设置发送内容（一步到位）
        示例:
        tim 设置定时 interval 5 第一行\n第二行
        tim 设置定时 fixed 20时30分 快到点了，该发送啦！
        tim 设置定时 once 10 临时提醒：快吃饭喵~
        任务类型：
        interval: 每隔指定分钟发送
        fixed: 每天在指定时间发送 (格式: HH时MM分，UTC+8)
        once: 延迟指定分钟后发送一次
        """
        logging.debug("set_timing 参数：task_type=%s, time_value=%s, content=%s", task_type, time_value, content)

        # 校验任务类型及时间参数
        if task_type == "fixed":
            try:
                self.__class__.parse_time(time_value)
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
            "content": content,  # 发送内容
            "status": "active",
            "create_time": now.isoformat(),
            "last_run": None,
            "target": umo
        }
        task_id = str(self.next_id)
        self.next_id += 1
        self.tasks[umo][task_id] = task_data
        self.__class__.save_tasks(self.tasks)
        logging.debug("添加任务 %s: %s", task_id, task_data)
        msg = (f"任务 {task_id} 已添加（会话: {umo}），类型: {task_type}，时间参数: {time_value}。\n"
               "发送内容已设定，无需再单独设置。")
        yield event.plain_result(msg)

    @filter.command("tim 取消")
    async def cancel_task(self, event: AstrMessageEvent, task_id: int):
        """
        取消指定任务
        示例: tim 取消 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        if umo in self.tasks and tid in self.tasks[umo]:
            del self.tasks[umo][tid]
            self.__class__.save_tasks(self.tasks)
            logging.debug("取消任务 %s", tid)
            yield event.plain_result(f"任务 {tid} 已取消。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @filter.command("tim 暂停")
    async def pause_task(self, event: AstrMessageEvent, task_id: int):
        """
        暂停指定任务
        示例: tim 暂停 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        if umo in self.tasks and tid in self.tasks[umo]:
            self.tasks[umo][tid]["status"] = "paused"
            self.__class__.save_tasks(self.tasks)
            logging.debug("暂停任务 %s", tid)
            yield event.plain_result(f"任务 {tid} 已暂停。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @filter.command("tim 启用")
    async def enable_task(self, event: AstrMessageEvent, task_id: int):
        """
        启用被暂停的任务
        示例: tim 启用 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        if umo in self.tasks and tid in self.tasks[umo]:
            self.tasks[umo][tid]["status"] = "active"
            self.__class__.save_tasks(self.tasks)
            logging.debug("启用任务 %s", tid)
            yield event.plain_result(f"任务 {tid} 已启用。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @filter.command("tim 清空")
    async def clear_content(self, event: AstrMessageEvent, task_id: int):
        """
        清空指定任务的发送内容
        示例: tim 清空 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        if umo in self.tasks and tid in self.tasks[umo]:
            self.tasks[umo][tid]["content"] = ""
            self.__class__.save_tasks(self.tasks)
            logging.debug("清空任务 %s 的内容", tid)
            yield event.plain_result(f"任务 {tid} 的发送内容已清空。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @filter.command("tim 列出任务")
    async def list_tasks(self, event: AstrMessageEvent):
        """
        列出当前会话中所有已创建的任务
        示例: tim 列出任务
        """
        umo = event.unified_msg_origin
        if umo not in self.tasks or not self.tasks[umo]:
            yield event.plain_result("当前会话中没有设置任何任务。")
            return
        msg = "当前会话任务列表：\n"
        for tid, task in self.tasks[umo].items():
            msg += f"任务 {tid} - 类型: {task['type']}, 时间参数: {task['time']}, 状态: {task['status']}\n"
            if task["content"]:
                msg += f"    内容: {task['content']}\n"
        logging.debug("列出任务：\n%s", msg)
        yield event.plain_result(msg)

    @filter.command("tim help")
    async def show_help(self, event: AstrMessageEvent):
        """
        显示定时任务插件的帮助信息
        示例: tim help
        """
        help_msg = (
            "定时任务插件帮助信息：\n"
            "1. tim 设置定时 <任务种类> <时间> <发送内容>\n"
            "   - interval: 每隔指定分钟发送 (示例: tim 设置定时 interval 5 第一行\\n第二行)\n"
            "   - fixed: 每天在指定时间发送，格式 HH时MM分 (示例: tim 设置定时 fixed 20时30分 快到点了，该发送啦！)\n"
            "   - once: 延迟指定分钟后发送一次 (示例: tim 设置定时 once 10 临时提醒：快吃饭喵~)\n"
            "2. tim 取消 <任务编号>              -- 取消任务\n"
            "3. tim 暂停 <任务编号>              -- 暂停任务\n"
            "4. tim 启用 <任务编号>              -- 启用被暂停的任务\n"
            "5. tim 清空 <任务编号>              -- 清空任务发送内容\n"
            "6. tim 列出任务                   -- 列出当前会话中所有任务\n"
            "7. tim help                       -- 显示此帮助信息"
        )
        yield event.plain_result(help_msg)
