
# AstrBot 定时发送消息插件喵~ 

<img src="https://raw.githubusercontent.com/IGCrystal/IGCrystal/refs/heads/main/test/img/%E6%8F%92%E7%94%BB.jpg" width="200" height="200"></img>
<img src="https://raw.githubusercontent.com/IGCrystal/IGCrystal/refs/heads/main/test/img/%E6%8F%92%E7%94%BB.png" width="200" height="200"></img>


版本：1.1.3

作者：IGCrystal  

仓库：[https://github.com/IGCrystal/astrbot_plugin_timtip](https://github.com/IGCrystal/astrbot_plugin_timtip)

## 简介

本插件基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 框架，提供定时发送消息的功能。  
插件支持多种任务类型：
- **interval**：每隔指定分钟发送一次消息。
- **fixed**：每天在指定时间发送消息（格式可以为：HH时MM分，HHMM，HH:MM）。
- **once**：延迟指定分钟后发送一次消息。

此外，还提供编辑、取消、暂停、启用、清空、列出任务等功能。



## 功能特点

- **定时任务调度**  
  后台调度器每 1 秒检查一次所有任务条件，满足条件时自动调用发送接口。

- **主动消息发送**  
  使用 AstrBot 提供的 `send_message()` 接口，将预先保存的统一会话 ID（unified_msg_origin）作为目标发送消息。

- **任务持久化**  
  任务数据存储在 `tim.json` 文件中，支持插件重启后自动加载任务。

- **日志记录**  
  日志同时输出到控制台和日志文件 `./data/plugins/astrbot_plugin_timtip/bot.log`，方便调试和排查问题。

- **多命令支持**  
  提供设置定时任务、编辑任务信息、取消任务、暂停任务、启用任务、清空任务发送内容、列出任务以及帮助命令。

>[!TIP]
> 自版本 `1.1.2`后，支持在发送信息里面加入**空格**和**换行**，意味着您可以编辑更复杂的信息，但**仅限于通过修改 `info.json` 实现**。
>
> 如果您是通过指令来编辑**包含了换行符、空格符**的发送内容的，那么可能会导致发送信息不完全。请通过修改插件目录里的 `info.json` 内容以加入换行、空格。

 ### 您在编辑 `info.json` 时需要遵循以下语法：
  
 - 您可以通过使用 `\n` 来换行，如编辑 `info.json`的内容为：
    
      ```
      {
        "aiocqhttp:GroupMessage:xxxxxxxxxx": {
            "2": "我 \n 喜欢 \n 吃苹果"
        }
      }
      ```
    
    那么发送的信息则是：
    
      ```
      我 
       喜欢 
       吃苹果
      ```
    
 - 您可以直接在 `" "` 内写入空格
   
   **注意**：这在指令中不支持，如果直接将空格符写入指令则会导致发送信息不全！

## 安装与部署

1. **获取插件代码**  
   在插件市场中安装喵~
   
3. **安装依赖**  
   本插件依赖 Python3 和 AstrBot 框架，无需额外依赖（如有需要请在 `requirements.txt` 中添加）。

4. **启动 AstrBot**  
   启动 AstrBot 主程序，插件将自动加载。


## 配置说明

- **任务数据文件**  
  任务数据存储在插件目录下的 `tim.json` 文件中，格式为 JSON。
  


## 命令使用示例

### 1. 设置定时/定时/设置

- **interval**（每隔指定分钟发送）
  ```
  tim 设置定时 interval 5 第一行
  ```
  该命令表示每隔 5 分钟发送一次消息，消息内容为 “第一行”。

- **fixed**（每天在指定时间发送）  
  ```
  tim 设置定时 fixed 20时30分 快到点了，该发送啦！
  ```
  该命令表示每天在 20时30分发送消息 “快到点了，该发送啦！”。

- **once**（延迟指定分钟后发送一次）
  ```
  tim 设置定时 once 10 临时提醒：快吃饭喵~
  ```
  该命令表示延迟 10 分钟后发送一次消息 “临时提醒：快吃饭喵~”。

### 2. 编辑信息/编辑/edit

```
tim 编辑信息 1 新的发送信息
```
编辑编号为 1 的任务，将发送内容更新为 “新的发送信息”。

### 3. 取消任务/取消

```
tim 取消 1
```
取消编号为 1 的任务。

### 4. 暂停任务/暂停

```
tim 暂停 1
```
暂停编号为 1 的任务。

### 5. 启用任务/启用

```
tim 启用 1
```
启用编号为 1 的任务。

### 6. 清空/清空信息

```
tim 清空 1
```
清空编号为 1 的任务发送内容。

### 7. 列出任务/列表/list/队列/当前任务/任务/任务列表

```
tim 列出任务
```
显示当前会话中所有已创建的任务。

### 8. 帮助信息/帮助/help

```
tim help
```
显示插件帮助信息及使用说明。

## 注意事项

- 注意，使用空格来分隔各个参数，目前暂不支持换行/图片等多媒体信息发送。但是你可以使用 emoji。
- 任务调度器采用 `asyncio.create_task()` 在后台异步运行，每 1 秒检查一次任务状态。    
- 任务数据保存在 JSON 文件中，确保插件所在目录有写入权限。



## 联系与反馈

如有任何问题或建议，请访问插件仓库：[https://github.com/IGCrystal/astrbot_plugin_timtip](https://github.com/IGCrystal/astrbot_plugin_timtip)  
欢迎提交 `PR` 或者 `Issues`，共同完善插件功能喵！


**Enjoy coding, 😻😻😻喵~！**


