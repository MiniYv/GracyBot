"""
独立戳一戳功能模块 - 测试阶段独立实现
功能：监听戳一戳事件，调用OpenAI生成智能回复，实现回戳功能
注意：这是独立模块，不修改现有OpenAI插件结构
"""

import json
import requests
import os
import random
from core.config import ROBOT_QQ, NAPCAT_HTTP_URL
from core.utils import logger

# 配置文件路径（复用OpenAI插件的配置）
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
POKE_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "poke_config.json")

# 戳一戳功能配置（默认值）
POKE_CONFIG = {
    "enabled": True,  # 默认开启戳一戳功能
    "auto_reply": True,  # 自动回复
    "poke_back": True,  # 回戳功能
    "ai_response": True  # 使用AI智能回复
}

# 加载戳一戳配置
if os.path.exists(POKE_CONFIG_FILE):
    try:
        with open(POKE_CONFIG_FILE, "r", encoding="utf-8") as f:
            saved_config = json.load(f)
            POKE_CONFIG.update(saved_config)
        logger.info("✅ 戳一戳配置加载成功")
    except Exception as e:
        logger.error(f"加载戳一戳配置失败：{str(e)}")
else:
    # 创建默认配置
    try:
        with open(POKE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(POKE_CONFIG, f, ensure_ascii=False, indent=2)
        logger.info("✅ 创建默认戳一戳配置")
    except Exception as e:
        logger.error(f"创建戳一戳配置失败：{str(e)}")

# 戳一戳回复模板
POKE_REPLIES = [
    "哎呀，别戳我啦~",
    "戳我干嘛呀？",
    "再戳我就要生气了！",
    "嘿嘿，被你发现了~",
    "戳戳戳，就知道戳我！",
    "我戳回去！",
    "别闹了，我在工作呢~",
    "戳我有什么好玩的？",
    "你再戳我，我就...我就...不理你了！",
    "戳戳乐？我也来戳你！"
]

# 读取JSON文件
def read_json(file_path):
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"读取{file_path}失败：{str(e)}")
        return {}

# 加载OpenAI配置
def load_openai_config():
    loaded_config = read_json(CONFIG_FILE)
    return {
        "api_key": loaded_config.get("api_key", ""),
        "model": loaded_config.get("model", "deepseek-chat"),
        "api_base": loaded_config.get("api_base", "https://api.deepseek.com/v1")
    }

# 加载人设配置
def load_character_settings():
    loaded_data = read_json(DATA_FILE)
    return loaded_data.get("CHARACTER_SETTINGS", {
        "默认人设": "你是GracyBot的AI助手，负责守护用户，用户是真人，需尽可能准确称呼用户QQ昵称，回答严谨、简洁、精准。"
    })

def get_current_character():
    loaded_data = read_json(DATA_FILE)
    return loaded_data.get("CURRENT_CHARACTER", "默认人设")

# 调用OpenAI API生成智能回复
def generate_poke_reply(user_id: str, nickname: str, chat_type: str) -> str:
    """生成戳一戳的智能回复"""
    
    openai_config = load_openai_config()
    character_settings = load_character_settings()
    current_character = get_current_character()
    
    if not openai_config["api_key"]:
        return None  # 返回None表示使用默认回复
    
    # 确保当前人设存在
    if current_character not in character_settings:
        current_character = "默认人设"
    
    # 根据聊天类型生成不同的提示词
    if chat_type == "group":
        system_prompt = f"{character_settings[current_character]}\n" \
                        f"用户{user_id}({nickname})在群聊中戳了你一下，请用轻松幽默的语气回应，保持简洁（不超过20字）。"
    else:
        system_prompt = f"{character_settings[current_character]}\n" \
                        f"用户{user_id}({nickname})在私聊中戳了你一下，请用亲切友好的语气回应，保持简洁（不超过20字）。"
    
    user_prompt = f"用户{user_id}({nickname})戳了你一下，请生成一个简短有趣的回应。"
    
    headers = {
        "Authorization": f"Bearer {openai_config['api_key']}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": openai_config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.8,
        "max_tokens": 30,
        "timeout": 10
    }
    
    try:
        response = requests.post(
            f"{openai_config['api_base']}/chat/completions",
            headers=headers,
            json=data,
            timeout=10
        )
        response.raise_for_status()
        resp_json = response.json()
        
        if "choices" in resp_json and len(resp_json["choices"]) > 0:
            reply = resp_json["choices"][0]["message"]["content"].strip()
            # 清理回复内容，确保简洁
            if len(reply) > 30:
                reply = reply[:27] + "..."
            return reply
        else:
            return None
    except Exception as e:
        logger.error(f"OpenAI戳一戳回复生成失败：{str(e)}")
        return None

# 发送回戳消息
def send_poke_back(target_id: str, chat_type: str):
    """发送回戳消息"""
    
    poke_data = {
        "user_id": int(target_id) if chat_type == "private" else None,
        "group_id": int(target_id) if chat_type == "group" else None
    }
    
    # 移除None值
    poke_data = {k: v for k, v in poke_data.items() if v is not None}
    
    try:
        response = requests.post(
            f"{NAPCAT_HTTP_URL}/send_poke",
            json=poke_data,
            timeout=5
        )
        
        if response.status_code == 200:
            logger.info(f"回戳消息发送成功：{target_id} ({chat_type})")
            return True
        else:
            logger.warning(f"回戳消息发送失败：{response.status_code}")
            return False
    except Exception as e:
        logger.error(f"回戳消息发送异常：{str(e)}")
        return False

# 发送文本消息
def send_text_message(target_id: str, message: str, chat_type: str):
    """发送文本消息"""
    try:
        if chat_type == "private":
            response = requests.post(
                f"{NAPCAT_HTTP_URL}/send_private_msg",
                json={
                    "user_id": int(target_id),
                    "message": message
                },
                timeout=5
            )
        else:
            response = requests.post(
                f"{NAPCAT_HTTP_URL}/send_group_msg",
                json={
                    "group_id": int(target_id),
                    "message": message
                },
                timeout=5
            )
        
        if response.status_code == 200:
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"发送文本消息失败：{str(e)}")
        return False

# 主处理函数 - 戳一戳事件监听
def handle_poke_event(data):
    """处理戳一戳事件"""
    
    # 检查是否为戳一戳事件
    if data.get("post_type") != "notice" or data.get("notice_type") != "notify" or data.get("sub_type") != "poke":
        return False
    
    # 检查是否戳的是机器人
    target_id = str(data.get("target_id", ""))
    if target_id != str(ROBOT_QQ):
        return False
    
    # 获取发送者信息
    user_id = str(data.get("user_id", ""))
    group_id = str(data.get("group_id", ""))
    nickname = data.get("sender", {}).get("nickname", "用户")
    
    # 确定聊天类型
    chat_type = "group" if group_id else "private"
    target_id = group_id if group_id else user_id
    
    logger.info(f"收到戳一戳事件：用户{user_id}({nickname})在{chat_type}{target_id}戳了机器人")
    
    # 检查戳一戳功能是否启用
    if not POKE_CONFIG["enabled"]:
        logger.debug("戳一戳功能已关闭，忽略事件")
        return True
    
    # 生成回复内容
    reply_content = ""
    
    if POKE_CONFIG["ai_response"]:
        # 使用AI智能回复
        reply_content = generate_poke_reply(user_id, nickname, chat_type)
    
    if not reply_content and POKE_CONFIG["auto_reply"]:
        # 使用随机回复模板
        reply_content = random.choice(POKE_REPLIES)
    
    # 发送回复
    if reply_content:
        if send_text_message(target_id, reply_content, chat_type):
            logger.info(f"已发送戳一戳回复：{reply_content}")
    
    # 发送回戳
    if POKE_CONFIG["poke_back"] and random.random() < 0.7:  # 70%概率回戳
        send_poke_back(user_id, "private")
    
    return True

# 保存戳一戳配置到文件
def save_poke_config():
    """保存戳一戳配置到文件"""
    try:
        with open(POKE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(POKE_CONFIG, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存戳一戳配置失败：{str(e)}")
        return False

# 戳一戳功能控制函数
def set_poke_enabled(enabled):
    """设置戳一戳功能开关"""
    POKE_CONFIG["enabled"] = enabled
    status = "开启" if enabled else "关闭"
    save_poke_config()
    logger.info(f"戳一戳功能已{status}")
    return f"✅ 戳一戳功能已{status}"

def set_auto_reply(enabled):
    """设置自动回复开关"""
    POKE_CONFIG["auto_reply"] = enabled
    status = "开启" if enabled else "关闭"
    save_poke_config()
    logger.info(f"戳一戳自动回复已{status}")
    return f"✅ 戳一戳自动回复已{status}"

def set_poke_back(enabled):
    """设置回戳开关"""
    POKE_CONFIG["poke_back"] = enabled
    status = "开启" if enabled else "关闭"
    save_poke_config()
    logger.info(f"戳一戳回戳功能已{status}")
    return f"✅ 戳一戳回戳功能已{status}"

def set_ai_response(enabled):
    """设置AI回复开关"""
    POKE_CONFIG["ai_response"] = enabled
    status = "开启" if enabled else "关闭"
    save_poke_config()
    logger.info(f"戳一戳AI回复已{status}")
    return f"✅ 戳一戳AI回复已{status}"

def get_poke_status():
    """获取戳一戳功能状态"""
    status = "开启" if POKE_CONFIG["enabled"] else "关闭"
    auto_reply = "开启" if POKE_CONFIG["auto_reply"] else "关闭"
    poke_back = "开启" if POKE_CONFIG["poke_back"] else "关闭"
    ai_response = "开启" if POKE_CONFIG["ai_response"] else "关闭"
    
    return f"""📊 戳一戳功能状态：
• 总开关：{status}
• 自动回复：{auto_reply}
• 回戳功能：{poke_back}
• AI智能回复：{ai_response}"""

logger.info("✅ 独立戳一戳功能模块加载完成")