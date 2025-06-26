import os
import re
import json
import asyncio
from datetime import datetime, timedelta
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger  # 使用 astrbot.api 提供的日志器喵♡～
import astrbot.api.message_components as Comp  # 包含 Plain、Image 等组件
from astrbot.core.platform.sources.dingtalk.dingtalk_event import DingtalkMessageEvent
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

# 使用 AstrBot 提供的标准数据路径
BASE_DIR = os.path.join(get_astrbot_data_path(), "plugins_data", "astrbot_plugin_timtip")
os.makedirs(BASE_DIR, exist_ok=True)

# 定义 JSON 文件路径，用于保存任务和发送内容数据
TIM_FILE = os.path.join(BASE_DIR, "tim.json")
INFO_FILE = os.path.join(BASE_DIR, "info.json")

@register("astrbot_plugin_timtip", "IGCrystal", "定时发送消息的插件喵~（发送内容由 info.json 管理，按会话分组，修改后即时生效）", "1.1.5",
          "https://github.com/IGCrystal/astrbot_plugin_timtip")
class TimPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 加载任务数据和信息数据
        self.tasks = self.__class__.load_json(TIM_FILE)
        self.infos = self.__class__.load_json(INFO_FILE)
        
        # 存储会话的 event 对象，用于发送消息
        self.session_events = {}
        
        # 全局任务编号从 1 开始（每个会话内任务编号唯一，整体递增便于管理）
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
        self.scheduler_task = asyncio.create_task(self.scheduler_loop())
        logger.debug("TimPlugin 初始化完成，定时任务调度器已启动")

    async def terminate(self):
        """
        插件卸载时调用，取消后台调度器任务，防止重载后产生多个调度器。
        """
        if hasattr(self, "scheduler_task"):
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                logger.debug("调度器任务已成功取消")

    @staticmethod
    def load_json(file_path: str) -> dict:
        if not os.path.exists(file_path):
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump({}, f, ensure_ascii=False, indent=4)
                logger.debug("文件 %s 不存在，已创建空文件。", file_path)
            except Exception as e:
                logger.error("创建 %s 失败：%s", file_path, e)
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("读取 %s 失败：%s", file_path, e)
            return {}

    @staticmethod
    def save_json(data: dict, file_path: str):
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.debug("保存 %s 成功。", file_path)
        except Exception as e:
            logger.error("保存 %s 失败：%s", file_path, e)

    @staticmethod
    def parse_time(time_str: str) -> tuple:
        """
        解析固定时间格式，支持以下格式：
          1. "HH时MM分"（例如 20时30分）
          2. "HHMM"（例如 2030）
          3. "HH:MM"（例如 20:30）
        返回 (hour, minute)
        """
        patterns = [
            r'^(\d{1,2})时(\d{1,2})分$',
            r'^(\d{2})(\d{2})$',
            r'^(\d{1,2}):(\d{1,2})$'
        ]
        for pattern in patterns:
            match = re.match(pattern, time_str)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2))
                if 0 <= hour < 24 and 0 <= minute < 60:
                    return hour, minute
                else:
                    raise ValueError("时间范围错误，小时应在 0-23 之间，分钟应在 0-59 之间。")
        raise ValueError("时间格式错误，请使用 'HH时MM分'、'HHMM' 或 'HH:MM' 格式，例如 20时30分, 2030, 或 20:30。")

    async def scheduler_loop(self):
        """
        后台调度器，每 1 秒检查一次所有会话中的任务条件。
        """
        while True:
            now = datetime.utcnow() + timedelta(hours=8)
            current_day = now.day
            logger.debug("调度器循环运行中，当前时间: %s", now.isoformat())
            if current_day != self.last_day:
                self.executed_tasks.clear()
                self.last_day = current_day
                logger.debug("新的一天，清空固定任务执行记录。")

            # 遍历每个会话的任务
            for umo, task_dict in self.tasks.items():
                logger.debug("检查会话 %s 下的任务: %s", umo, task_dict)
                for tid, task in list(task_dict.items()):
                    # 仅处理状态为 active 的任务
                    if task.get("status", "active") != "active":
                        continue
                    task_type = task.get("type")
                    last_run = task.get("last_run")
                    last_run_dt = datetime.fromisoformat(last_run) if last_run else None

                    if task_type == "interval":
                        try:
                            interval = float(task.get("time"))
                        except ValueError:
                            logger.error("任务 %s 时间参数解析失败。", tid)
                            continue
                        if last_run_dt is None or (now - last_run_dt).total_seconds() >= interval * 60:
                            logger.debug("任务 %s 满足条件，准备发送消息。", tid)
                            await self.send_task_message(umo, tid, task)
                            task["last_run"] = now.isoformat()
                    elif task_type == "once":
                        try:
                            delay = float(task.get("time"))
                        except ValueError:
                            logger.error("任务 %s 时间参数解析失败。", tid)
                            continue
                        create_time = datetime.fromisoformat(task.get("create_time"))
                        if now >= create_time + timedelta(minutes=delay):
                            logger.debug("一次性任务 %s 到达发送时间，准备发送消息。", tid)
                            await self.send_task_message(umo, tid, task)
                            logger.debug("一次性任务 %s 执行后将被删除。", tid)
                            del task_dict[tid]
                            # 同时删除对应会话下 info.json 中的发送内容
                            if umo in self.infos and tid in self.infos[umo]:
                                del self.infos[umo][tid]
                                self.save_json(self.infos, INFO_FILE)
                    elif task_type == "fixed":
                        try:
                            hour, minute = self.parse_time(task.get("time"))
                        except ValueError as e:
                            logger.error("任务 %s 时间格式错误: %s", tid, e)
                            continue
                        exec_id = f"{umo}_{tid}_{current_day}_{hour}_{minute}"
                        if now.hour == hour and now.minute == minute and exec_id not in self.executed_tasks:
                            logger.debug("固定任务 %s 满足条件，准备发送消息。", tid)
                            await self.send_task_message(umo, tid, task)
                            task["last_run"] = now.isoformat()
                            self.executed_tasks.add(exec_id)
            self.save_json(self.tasks, TIM_FILE)
            await asyncio.sleep(1)

    async def send_task_message(self, umo: str, tid: str, task: dict):
        """
        构造消息链并发送任务消息，每次发送前重新加载 info.json 确保最新修改生效。
        """
        # 每次发送前重新加载最新的发送内容数据
        latest_infos = self.load_json(INFO_FILE)
        content = ""
        if umo in latest_infos:
            content = latest_infos[umo].get(tid, "")
            
        if not content:
            logger.error("任务 %s 的发送内容为空，无法发送消息。", tid)
            return
            
        # 检查是否有该会话的 event 对象
        if umo not in self.session_events:
            logger.error("会话 %s 没有可用的 event 上下文，无法发送消息", umo)
            return
            
        try:
            event = self.session_events[umo]
            chain = MessageChain().message(content)
            logger.debug("准备发送任务消息到会话 %s，任务 %s 内容: %s", umo, tid, content)
            
            await event.send(chain)
            logger.debug("任务 %s 消息发送成功", tid)
        except Exception as e:
            logger.error("任务 %s 发送消息时出错: %s", tid, e)

    # 指令组 "tim"
    @filter.command_group("tim")
    def tim(self):
        pass

    @tim.command("设置定时", alias={'定时', '设置'})
    async def set_timing(self, event: AstrMessageEvent, task_type: str, time_value: str, content: str):
        """
        添加定时任务（发送内容由 info.json 管理，按会话分组）
        示例:
          tim 设置定时 interval 5 儿童节快乐
          tim 设置定时 fixed 20时30分 快到点了，该发送啦！
          tim 设置定时 once 10 临时提醒：快吃饭喵~
        任务类型：
          interval: 每隔指定分钟发送
          fixed: 每天在指定时间发送 (支持格式：HH时MM分、HHMM、HH:MM，UTC+8)
          once: 延迟指定分钟后发送一次

        注意：指令编辑发送内容无法包含空格、换行及 emoji，
        可在添加任务后直接编辑 info.json 中对应会话和任务编号的内容，修改后即时生效。
        """
        # 参数验证
        if not task_type.strip():
            yield event.plain_result("任务类型不能为空，请输入任务类型。")
            return
        if not time_value.strip():
            yield event.plain_result("时间参数不能为空，请输入时间参数。")
            return
        if task_type == "fixed":
            try:
                self.parse_time(time_value)
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
        
        # 保存当前会话的 event 对象，用于后续发送消息
        self.session_events[umo] = event
        
        if umo not in self.tasks:
            self.tasks[umo] = {}
        if umo not in self.infos:
            self.infos[umo] = {}

        # 任务数据中不直接保存发送内容，由 info.json 管理
        task_data = {
            "type": task_type,
            "time": time_value,
            "status": "active",
            "create_time": now.isoformat(),
            "last_run": None,
            "target": umo
        }
        task_id = str(self.next_id)
        self.next_id += 1
        self.tasks[umo][task_id] = task_data
        self.save_json(self.tasks, TIM_FILE)
        # 在 info.json 对应会话下初始化该任务的发送内容
        self.infos[umo][task_id] = content
        self.save_json(self.infos, INFO_FILE)
        msg = (f"任务 {task_id} 已添加（会话: {umo}），类型: {task_type}，时间参数: {time_value}。\n"
               "发送内容已存入 info.json，请根据需要编辑，支持换行、空格及 emoji，修改后即时生效。")
        yield event.plain_result(msg)

    @tim.command("编辑信息", alias={'编辑', 'edit'})
    async def edit_info(self, event: AstrMessageEvent, task_id: int, new_content: str):
        """
        编辑指定任务的发送内容（实际修改 info.json 中的内容）
        示例: tim 编辑信息 1 '新的发送信息'
        注意：指令编辑发送内容无法包含空格、换行及 emoji，
        可在添加任务后直接编辑 info.json 中对应会话和任务编号的内容，修改后即时生效。
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        
        # 更新会话的 event 对象
        self.session_events[umo] = event
        
        if umo in self.tasks and tid in self.tasks[umo]:
            if umo not in self.infos:
                self.infos[umo] = {}
            self.infos[umo][tid] = new_content
            self.save_json(self.infos, INFO_FILE)
            logger.debug("编辑任务 %s 的发送内容为: %s", tid, new_content)
            yield event.plain_result(f"任务 {tid} 的发送内容已更新为：\n{new_content}")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @tim.command("取消", alias={'取消任务'})
    async def cancel_task(self, event: AstrMessageEvent, task_id: int):
        """
        取消指定任务
        示例: tim 取消 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        
        # 更新会话的 event 对象
        self.session_events[umo] = event
        
        if umo in self.tasks and tid in self.tasks[umo]:
            del self.tasks[umo][tid]
            self.save_json(self.tasks, TIM_FILE)
            # 同时删除 info.json 中对应的发送内容
            if umo in self.infos and tid in self.infos[umo]:
                del self.infos[umo][tid]
                self.save_json(self.infos, INFO_FILE)
            logger.debug("取消任务 %s", tid)
            yield event.plain_result(f"任务 {tid} 已取消。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @tim.command("暂停", alias={'暂停任务'})
    async def pause_task(self, event: AstrMessageEvent, task_id: int):
        """
        暂停指定任务
        示例: tim 暂停 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        
        # 更新会话的 event 对象
        self.session_events[umo] = event
        
        if umo in self.tasks and tid in self.tasks[umo]:
            self.tasks[umo][tid]["status"] = "paused"
            self.save_json(self.tasks, TIM_FILE)
            logger.debug("暂停任务 %s", tid)
            yield event.plain_result(f"任务 {tid} 已暂停。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @tim.command("启用", alias={'启用任务'})
    async def enable_task(self, event: AstrMessageEvent, task_id: int):
        """
        启用被暂停的任务
        示例: tim 启用 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        
        # 更新会话的 event 对象
        self.session_events[umo] = event
        
        if umo in self.tasks and tid in self.tasks[umo]:
            self.tasks[umo][tid]["status"] = "active"
            self.save_json(self.tasks, TIM_FILE)
            logger.debug("启用任务 %s", tid)
            yield event.plain_result(f"任务 {tid} 已启用。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @tim.command("清空", alias={'清空信息'})
    async def clear_content(self, event: AstrMessageEvent, task_id: int):
        """
        清空指定任务的发送内容
        示例: tim 清空 1
        """
        umo = event.unified_msg_origin
        tid = str(task_id)
        
        # 更新会话的 event 对象
        self.session_events[umo] = event
        
        if umo in self.infos and tid in self.infos[umo]:
            self.infos[umo][tid] = ""
            self.save_json(self.infos, INFO_FILE)
            logger.debug("清空任务 %s 的发送内容", tid)
            yield event.plain_result(f"任务 {tid} 的发送内容已清空。")
        else:
            yield event.plain_result(f"任务 {tid} 在当前会话中不存在。")

    @tim.command("列出任务", alias={'列表', 'list', '队列', '当前任务', '任务', '任务列表'})
    async def list_tasks(self, event: AstrMessageEvent):
        """
        列出当前会话中所有已创建的任务
        示例: tim 列出任务
        """
        umo = event.unified_msg_origin
        
        # 更新会话的 event 对象
        self.session_events[umo] = event
        
        if umo not in self.tasks or not self.tasks[umo]:
            yield event.plain_result("当前会话中没有设置任何任务。")
            return
        msg = "当前会话任务列表：\n"
        for tid, task in self.tasks[umo].items():
            content_preview = ""
            if umo in self.infos and tid in self.infos[umo]:
                content_preview = self.infos[umo][tid]
            if len(content_preview) > 50:
                content_preview = content_preview[:50] + "..."
            msg += f"任务 {tid} - 类型: {task['type']}, 时间参数: {task['time']}, 状态: {task['status']}\n"
            msg += f"    发送内容预览: {content_preview}\n"
        logger.debug("列出任务：\n%s", msg)
        yield event.plain_result(msg)

    @tim.command("help", alias={'帮助', '帮助信息'})
    async def show_help(self, event: AstrMessageEvent):
        """
        显示定时任务插件的帮助信息
        示例: tim help
        """
        umo = event.unified_msg_origin
        
        # 更新会话的 event 对象
        self.session_events[umo] = event
        
        help_msg = (
            "定时任务插件帮助信息：\n"
            "1. tim 设置定时 <任务种类> <时间> <发送内容>\n"
            "   - interval: 每隔指定分钟发送 (示例: tim 设置定时 interval 5 儿童节快乐)\n"
            "   - fixed: 每天在指定时间发送，格式 HH时MM分 (示例: tim 设置定时 fixed 20时30分 快到点了，该发送啦！)\n"
            "   - once: 延迟指定分钟后发送一次 (示例: tim 设置定时 once 10 临时提醒：快吃饭喵~)\n"
            "2. tim 编辑信息 <任务编号> <新的发送内容>  -- 修改 info.json 中对应任务的发送内容（修改后即时生效）\n"
            "3. tim 取消 <任务编号>              -- 取消任务\n"
            "4. tim 暂停 <任务编号>              -- 暂停任务\n"
            "5. tim 启用 <任务编号>              -- 启用被暂停的任务\n"
            "6. tim 清空 <任务编号>              -- 清空任务发送内容\n"
            "7. tim 列出任务                   -- 列出当前会话中所有任务\n"
            "8. tim help                       -- 显示此帮助信息\n"
            "更多用法请访问 https://github.com/IGCrystal/astrbot_plugin_timtip \n"
        )
        yield event.plain_result(help_msg)
