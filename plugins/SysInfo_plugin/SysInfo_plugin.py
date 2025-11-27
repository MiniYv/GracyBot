import subprocess
import platform
import time
import logging
from typing import Dict
import requests
import json
from core.config import (
    ROBOT_START_TIME,
    BOT_VERSION,
    MASTER_QQ,
    NAPCAT_HTTP_URL,
    LOG_ENCODING,
    ROBOT_QQ  # 新增导入，用于过滤@符号
)
logger = logging.getLogger("GracyBot-HTTP-Pure")

def send_http_msg(target: str, content: str, chat_type: str = "private") -> bool:
    try:
        url = f"{NAPCAT_HTTP_URL}/send_{chat_type}_msg"
        params = {"group_id" if chat_type == "group" else "user_id": int(target), "message": content}
        headers = {"Content-Type": "application/json; charset=utf-8"}
        response = requests.post(url, data=json.dumps(params, ensure_ascii=False).encode("utf-8"), headers=headers, timeout=10)
        if response.json().get("retcode") == 0:
            logger.info(f"✅ 发送{chat_type}消息到{target}：{content[:50]}...")
            return True
        else:
            logger.error(f"❌ {chat_type}消息发送失败：{response.json().get('msg')}")
            return False
    except Exception as e:
        logger.error(f"❌ {chat_type}消息发送异常：{str(e)}")
        return False

def get_system_info() -> Dict[str, str]:
    # 主机名称
    host_name = platform.node() or subprocess.getoutput("hostname")
    # 系统版本
    system_version = subprocess.getoutput("cat /etc/os-release | grep PRETTY_NAME | cut -d'=' -f2 | tr -d '\"'") or platform.platform()
    # 内核版本
    kernel_version = platform.release()
    # CPU信息
    cpu_info = subprocess.getoutput("lscpu | grep 'Model name' | cut -d: -f2 | sed 's/^ *//'")
    cpu_cores = subprocess.getoutput("lscpu | grep 'CPU(s):' | head -n1 | cut -d: -f2 | sed 's/^ *//'")
    cpu_final = f"{cpu_info}（{cpu_cores}核）" if cpu_info else "未知CPU"
    # 内存信息
    mem_info = subprocess.getoutput("free -m | grep Mem | awk '{print $2, $3}'")
    mem_final = "内存信息获取失败"
    if mem_info:
        total, used = mem_info.split()
        mem_final = f"总内存：{round(int(total)/1024,1)}GB，已用：{round(int(used)/1024,1)}GB"
    # 磁盘信息
    disk_output = subprocess.getoutput("df -h / | grep / | awk '{print $2, $3, $5}'")
    disk_final = "磁盘信息获取失败"
    if disk_output:
        total, used, rate = disk_output.split()
        disk_final = f"总容量：{total}，已用：{used}，使用率：{rate}"
    # 系统运行时长
    uptime = subprocess.getoutput("cat /proc/uptime | awk '{print $1}'")
    system_uptime = "获取失败"
    if uptime:
        sec = float(uptime)
        system_uptime = f"{int(sec//86400)}天{int((sec%86400)//3600)}小时{int((sec%3600)//60)}分钟"
    # 机器人启动时长
    robot_uptime = "获取失败"
    try:
        if ROBOT_START_TIME and isinstance(ROBOT_START_TIME, (int, float)) and ROBOT_START_TIME > 0:
            sec = time.time() - ROBOT_START_TIME
            robot_uptime = f"{int(sec//86400)}天{int((sec%86400)//3600)}小时{int((sec%3600)//60)}分钟"
    except Exception as e:
        logger.error(f"机器人时长计算异常：{str(e)}")
    # 运行状态
    bot_status = subprocess.getoutput("systemctl is-active bot.service")
    status_final = "✅ 运行中" if bot_status == "active" else "❌ 已停止"
    return {
        "主机名称": host_name,
        "系统版本": system_version,
        "内核版本": kernel_version,
        "CPU信息": cpu_final,
        "内存信息": mem_final,
        "磁盘信息": disk_final,
        "系统运行时长": system_uptime,
        "机器人启动时长": robot_uptime,
        "机器人版本": BOT_VERSION,
        "作者QQ": MASTER_QQ,
        "运行状态": status_final
    }

def handle_status_cmd(target: str, chat_type: str):
    info = get_system_info()
    msg = (
        "📊 【GracyBot状态信息】\n"
        f"🏠  主机名称：{info['主机名称']}\n"
        f"🖥️  系统版本：{info['系统版本']}\n"
        f"🔧  内核版本：{info['内核版本']}\n"
        f"⚡  CPU信息：{info['CPU信息']}\n"
        f"🧠  内存信息：{info['内存信息']}\n"
        f"💾  磁盘信息：{info['磁盘信息']}\n"
        f"⏳  系统运行时长：{info['系统运行时长']}\n"
        f"🤖  机器人启动时长：{info['机器人启动时长']}\n"
        f"📌  GracyBot版本：{info['机器人版本']}\n"
        f"👨‍💻  作者QQ：{info['作者QQ']}\n"
        f"📈  运行状态：{info['运行状态']}"
    )
    send_http_msg(target, msg, chat_type)

# ========== 核心修改：改为7个标准参数（顺序固定，不可修改） ==========
def handle_sysinfo_plugin(self_bot, bot, message, user_id, chat_type, permission, logger):
    # 1. 提取并清理消息内容（过滤空格、@机器人符号，兼容群聊格式）
    raw_msg = message.get("raw_message", "").strip()
    msg_content = raw_msg.replace(" ", "").replace("　", "").replace(f"@1972693082", "").replace(f"@机器人", "").strip()
    
    # 2. 确定目标ID（群聊=群ID，私聊=用户ID，避免发送失败）
    if chat_type == "group":
        target_id = message.get("group_id")
    else:
        target_id = user_id
    target_id = str(target_id) if target_id else user_id  # 容错处理，防止空值
    
    # 3. 指令匹配（保持原有功能逻辑不变）
    if msg_content in ["/运行状态", "/info", "/status"]:
        handle_status_cmd(target_id, chat_type)
        logger.info(f"用户{user_id}（{chat_type}）查询系统状态，目标ID：{target_id}")
        return True
    
    # 4. 无效指令处理（放过其他插件指令，避免冲突）
    if msg_content.startswith("/") and msg_content not in ["/运行状态", "/info", "/status"]:
        bot(target_id, "❌ 无效指令！本插件仅支持：/运行状态、/info、/status", chat_type)
        logger.warning(f"用户{user_id}（{chat_type}）发送无效系统指令：{msg_content}")
    else:
        return  # 放行其他插件的指令，交给对应插件处理

# ========== 插件实例化+函数暴露（固定写法，必须保留） ==========
# 注意：此类写法仅用于非类封装的插件，保持与插件管理器适配
# 若后续改为类封装，可参考猜数字插件格式，此处暂保持兼容
