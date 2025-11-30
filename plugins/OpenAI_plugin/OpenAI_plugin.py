import json
import requests
import os
from core.config import ROBOT_QQ, MASTER_QQ, NAPCAT_HTTP_URL
from core.utils import logger, send_http_msg, handle_auto_reply as core_auto_reply

# 导入戳一戳功能模块
from .poke_handler import handle_poke_event

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")

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

# 写入JSON文件
def write_json(file_path, data):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"写入{file_path}失败：{str(e)}")
        return False

# 加载配置
loaded_config = read_json(CONFIG_FILE)
OPENAI_CONFIG = {
    "api_key": loaded_config.get("api_key", ""),
    "model": loaded_config.get("model", "deepseek-chat"),
    "api_base": loaded_config.get("api_base", "https://api.deepseek.com/v1")
}

loaded_data = read_json(DATA_FILE)
CHARACTER_SETTINGS = loaded_data.get("CHARACTER_SETTINGS", {
    "默认人设": "你是GracyBot的AI助手，负责守护用户，用户是真人，需尽可能准确称呼用户QQ昵称，回答严谨、简洁、精准。"
})
CURRENT_CHARACTER = loaded_data.get("CURRENT_CHARACTER", "默认人设")
CONVERSATION_HISTORY = loaded_data.get("CONVERSATION_HISTORY", {})
MAX_HISTORY_COUNT = loaded_data.get("MAX_HISTORY_COUNT", 50)

# 工具函数
def is_master(user_id: str) -> bool:
    return user_id == str(MASTER_QQ)

def get_user_conversation(user_id: str) -> list:
    return CONVERSATION_HISTORY.get(user_id, [])

def add_conversation_msg(user_id: str, role: str, content: str):
    history = get_user_conversation(user_id)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY_COUNT:
        history = history[-MAX_HISTORY_COUNT:]
    CONVERSATION_HISTORY[user_id] = history
    write_json(DATA_FILE, {
        "CHARACTER_SETTINGS": CHARACTER_SETTINGS,
        "CURRENT_CHARACTER": CURRENT_CHARACTER,
        "CONVERSATION_HISTORY": CONVERSATION_HISTORY,
        "MAX_HISTORY_COUNT": MAX_HISTORY_COUNT
    })

def clear_conversation(user_id: str):
    CONVERSATION_HISTORY[user_id] = []
    write_json(DATA_FILE, {
        "CHARACTER_SETTINGS": CHARACTER_SETTINGS,
        "CURRENT_CHARACTER": CURRENT_CHARACTER,
        "CONVERSATION_HISTORY": CONVERSATION_HISTORY,
        "MAX_HISTORY_COUNT": MAX_HISTORY_COUNT
    })

# 主处理函数
def handle_openai_plugin(self_bot, bot, message, user_id, chat_type, permission, log_func):
    raw_msg = message.get("raw_message", "").strip()
    nickname = message.get("sender", {}).get("card", "") or message.get("sender", {}).get("nickname", "") or user_id
    
    # 确保使用最新配置
    global CURRENT_CHARACTER, CHARACTER_SETTINGS, CONVERSATION_HISTORY
    loaded_data = read_json(DATA_FILE)
    if loaded_data:
        CURRENT_CHARACTER = loaded_data.get("CURRENT_CHARACTER", CURRENT_CHARACTER)
        CHARACTER_SETTINGS = loaded_data.get("CHARACTER_SETTINGS", CHARACTER_SETTINGS)
        CONVERSATION_HISTORY = loaded_data.get("CONVERSATION_HISTORY", CONVERSATION_HISTORY)
    
    target_id = message.get("group_id") if chat_type == "group" else user_id
    target_id = str(target_id) if target_id else user_id
    
    # 帮助命令
    if raw_msg == "/chat帮助":
        help_msg = "🌟 OpenAI帮助\n" \
                   "//+内容 触发AI聊天（支持上下文）\n" \
                   "群聊：@机器人QQ号 +内容 可触发AI聊天\n" \
                   "主人专属（仅私聊）：\n" \
                   "/设置OpenAI API_KEY 模型 地址\n" \
                   "/新增人设 名称 内容\n" \
                   "/删除人设 名称\n" \
                   "/查看人设列表\n" \
                   "/切换人设 名称\n" \
                   "/清除记忆\n" \
                   "/戳一戳开关 开启/关闭 - 控制戳一戳功能\n" \
                   "/戳一戳状态 - 查看戳一戳功能状态\n" \
                   "英文指令（功能相同）：\n" \
                   "/persona 名称 - 切换人设\n" \
                   "/+persona 名称 内容 - 新增人设\n" \
                   "/-persona 名称 - 删除人设\n" \
                   "/persona= - 查看人设列表"
        bot(target_id, help_msg, chat_type)
        log_func(f"用户{user_id}查询/chat帮助")
        return True
    
    # AI聊天触发
    chat_content = ""
    if raw_msg.startswith("//"):
        if chat_type == "group" or chat_type == "private":
            chat_content = raw_msg.lstrip("//").strip()
    # 私聊中普通消息也触发AI回复
    elif chat_type == "private" and raw_msg.strip() and not raw_msg.startswith("/"):
        chat_content = raw_msg.strip()
    
    if chat_content:
        reply = call_openai_api(chat_content, user_id, nickname)
        bot(target_id, reply, chat_type)
        return True
    
    # 主人专属命令
    if is_master(user_id):
        # 允许主人在群聊中执行插件管理指令
        if chat_type != "private":
            # 群聊中只允许执行人设管理相关指令，不允许设置OpenAI配置
            if raw_msg.startswith("/设置OpenAI"):
                bot(target_id, "❌ 出于安全考虑，OpenAI配置仅支持主人私聊使用", chat_type)
                return True
            # 群聊中允许执行人设管理指令
            elif raw_msg.startswith(("/新增人设", "/删除人设", "/查看人设列表", "/切换人设", "/清除记忆", "/persona", "/+persona", "/-persona", "/persona=")):
                # 继续执行后续的人设管理逻辑
                pass
            else:
                return True
        
        if raw_msg.startswith("/设置OpenAI"):
            parts = raw_msg.split(maxsplit=3)
            if len(parts) == 4:
                _, api_key, model, api_base = parts
                OPENAI_CONFIG.update({"api_key": api_key, "model": model, "api_base": api_base})
                write_json(CONFIG_FILE, OPENAI_CONFIG)
                bot(target_id, "✅ OpenAI配置成功", chat_type)
            else:
                bot(target_id, "❌ 格式错误：/设置OpenAI API_KEY 模型 地址", chat_type)
            return True
        
        elif raw_msg.startswith("/新增人设"):
            parts = raw_msg.split(maxsplit=2)
            if len(parts) == 3:
                _, char_name, char_content = parts
                CHARACTER_SETTINGS[char_name] = char_content
                write_json(DATA_FILE, {
                    "CHARACTER_SETTINGS": CHARACTER_SETTINGS,
                    "CURRENT_CHARACTER": CURRENT_CHARACTER,
                    "CONVERSATION_HISTORY": CONVERSATION_HISTORY,
                    "MAX_HISTORY_COUNT": MAX_HISTORY_COUNT
                })
                bot(target_id, f"✅ 新增人设「{char_name}」成功", chat_type)
            else:
                bot(target_id, "❌ 格式错误：/新增人设 名称 内容", chat_type)
            return True
        
        elif raw_msg.startswith("/删除人设"):
            parts = raw_msg.split(maxsplit=1)
            if len(parts) == 2:
                char_name = parts[1]
                if char_name in CHARACTER_SETTINGS and char_name != "默认人设":
                    del CHARACTER_SETTINGS[char_name]
                    if CURRENT_CHARACTER == char_name:
                        CURRENT_CHARACTER = "默认人设"
                        clear_conversation(user_id)
                    write_json(DATA_FILE, {
                        "CHARACTER_SETTINGS": CHARACTER_SETTINGS,
                        "CURRENT_CHARACTER": CURRENT_CHARACTER,
                        "CONVERSATION_HISTORY": CONVERSATION_HISTORY,
                        "MAX_HISTORY_COUNT": MAX_HISTORY_COUNT
                    })
                    bot(target_id, f"✅ 删除人设「{char_name}」成功", chat_type)
                else:
                    bot(target_id, "❌ 错误：人设不存在或无法删除默认人设", chat_type)
            else:
                bot(target_id, "❌ 格式错误：/删除人设 名称", chat_type)
            return True
        
        elif raw_msg == "/查看人设列表":
            char_list = []
            for name in CHARACTER_SETTINGS.keys():
                if name == CURRENT_CHARACTER:
                    char_list.append(f"• {name}（当前使用）")
                else:
                    char_list.append(f"• {name}")
            final_char_list = "\n".join(char_list)
            bot(target_id, f"📋 可用人设列表：\n{final_char_list}", chat_type)
            return True
        
        elif raw_msg.startswith("/切换人设"):
            parts = raw_msg.split(maxsplit=1)
            if len(parts) == 2:
                char_name = parts[1]
                if char_name in CHARACTER_SETTINGS:
                    CURRENT_CHARACTER = char_name
                    # 只清除当前用户的对话历史，确保人设切换生效
                    CONVERSATION_HISTORY[user_id] = []
                    write_json(DATA_FILE, {
                        "CHARACTER_SETTINGS": CHARACTER_SETTINGS,
                        "CURRENT_CHARACTER": CURRENT_CHARACTER,
                        "CONVERSATION_HISTORY": CONVERSATION_HISTORY,
                        "MAX_HISTORY_COUNT": MAX_HISTORY_COUNT
                    })
                    bot(target_id, f"✅ 已切换至人设「{CURRENT_CHARACTER}", chat_type)
                else:
                    bot(target_id, "❌ 错误：人设不存在", chat_type)
            else:
                bot(target_id, "❌ 格式错误：/切换人设 名称", chat_type)
            return True
        
        elif raw_msg == "/清除记忆":
            # 清除所有用户的对话历史
            CONVERSATION_HISTORY.clear()
            write_json(DATA_FILE, {
                "CHARACTER_SETTINGS": CHARACTER_SETTINGS,
                "CURRENT_CHARACTER": CURRENT_CHARACTER,
                "CONVERSATION_HISTORY": CONVERSATION_HISTORY,
                "MAX_HISTORY_COUNT": MAX_HISTORY_COUNT
            })
            bot(target_id, "✅ 已清空所有用户对话历史记忆", chat_type)
            return True
        
        # 英文版人设管理指令（映射到中文功能）
        elif raw_msg == "/persona=":
            # 映射到/查看人设列表功能
            char_list = []
            for name in CHARACTER_SETTINGS.keys():
                if name == CURRENT_CHARACTER:
                    char_list.append(f"• {name}（当前使用）")
                else:
                    char_list.append(f"• {name}")
            final_char_list = "\n".join(char_list)
            bot(target_id, f"📋 可用人设列表：\n{final_char_list}", chat_type)
            return True
        
        elif raw_msg == "/persona":
            # 单独输入/persona时显示当前人设
            bot(target_id, f"📋 当前使用人设：{CURRENT_CHARACTER}\n💡 使用 /persona= 查看所有人设列表\n💡 使用 /persona 名称 切换人设", chat_type)
            return True
        
        elif raw_msg.startswith("/persona ") and not raw_msg.startswith("/persona="):
            # 映射到/切换人设功能
            parts = raw_msg.split(maxsplit=1)
            if len(parts) == 2:
                char_name = parts[1]
                if char_name in CHARACTER_SETTINGS:
                    CURRENT_CHARACTER = char_name
                    # 只清除当前用户的对话历史，确保人设切换生效
                    CONVERSATION_HISTORY[user_id] = []
                    write_json(DATA_FILE, {
                        "CHARACTER_SETTINGS": CHARACTER_SETTINGS,
                        "CURRENT_CHARACTER": CURRENT_CHARACTER,
                        "CONVERSATION_HISTORY": CONVERSATION_HISTORY,
                        "MAX_HISTORY_COUNT": MAX_HISTORY_COUNT
                    })
                    bot(target_id, f"✅ 已切换至人设「{CURRENT_CHARACTER}", chat_type)
                else:
                    bot(target_id, "❌ 错误：人设不存在", chat_type)
            else:
                bot(target_id, "❌ 格式错误：/persona 名称", chat_type)
            return True
        
        elif raw_msg.startswith("/+persona"):
            # 映射到/新增人设功能
            parts = raw_msg.split(maxsplit=2)
            if len(parts) == 3:
                _, char_name, char_content = parts
                CHARACTER_SETTINGS[char_name] = char_content
                write_json(DATA_FILE, {
                    "CHARACTER_SETTINGS": CHARACTER_SETTINGS,
                    "CURRENT_CHARACTER": CURRENT_CHARACTER,
                    "CONVERSATION_HISTORY": CONVERSATION_HISTORY,
                    "MAX_HISTORY_COUNT": MAX_HISTORY_COUNT
                })
                bot(target_id, f"✅ 已新增人设「{char_name}」", chat_type)
            else:
                bot(target_id, "❌ 格式错误：/+persona 名称 内容", chat_type)
            return True
        
        elif raw_msg.startswith("/-persona"):
            # 映射到/删除人设功能
            parts = raw_msg.split(maxsplit=1)
            if len(parts) == 2:
                char_name = parts[1]
                if char_name in CHARACTER_SETTINGS and char_name != "默认人设":
                    del CHARACTER_SETTINGS[char_name]
                    if CURRENT_CHARACTER == char_name:
                        CURRENT_CHARACTER = "默认人设"
                        clear_conversation(user_id)
                    write_json(DATA_FILE, {
                        "CHARACTER_SETTINGS": CHARACTER_SETTINGS,
                        "CURRENT_CHARACTER": CURRENT_CHARACTER,
                        "CONVERSATION_HISTORY": CONVERSATION_HISTORY,
                        "MAX_HISTORY_COUNT": MAX_HISTORY_COUNT
                    })
                    bot(target_id, f"✅ 已删除人设「{char_name}」", chat_type)
                else:
                    bot(target_id, "❌ 错误：人设不存在或无法删除默认人设", chat_type)
            else:
                bot(target_id, "❌ 格式错误：/-persona 名称", chat_type)
            return True
        
        # 戳一戳功能控制命令
        elif raw_msg.startswith("/戳一戳开关"):
            parts = raw_msg.split(maxsplit=1)
            if len(parts) == 2:
                action = parts[1].strip()
                if action in ["开启", "打开", "on", "enable"]:
                    from .poke_handler import set_poke_enabled
                    result = set_poke_enabled(True)
                    bot(target_id, result, chat_type)
                elif action in ["关闭", "关掉", "off", "disable"]:
                    from .poke_handler import set_poke_enabled
                    result = set_poke_enabled(False)
                    bot(target_id, result, chat_type)
                else:
                    bot(target_id, "❌ 格式错误：/戳一戳开关 开启/关闭", chat_type)
            else:
                bot(target_id, "❌ 格式错误：/戳一戳开关 开启/关闭", chat_type)
            return True
        
        elif raw_msg == "/戳一戳状态":
            from .poke_handler import get_poke_status
            result = get_poke_status()
            bot(target_id, result, chat_type)
            return True
    
    return False

# API调用函数
def call_openai_api(message: str, user_id: str, nickname: str) -> str:
    if not OPENAI_CONFIG["api_key"]:
        return "❌ 未配置OpenAI API密钥，请主人执行/设置OpenAI命令完成配置"
    
    # 使用和handle_openai_plugin完全相同的逻辑
    global CURRENT_CHARACTER, CHARACTER_SETTINGS, CONVERSATION_HISTORY
    loaded_data = read_json(DATA_FILE)
    if loaded_data:
        CURRENT_CHARACTER = loaded_data.get("CURRENT_CHARACTER", CURRENT_CHARACTER)
        CHARACTER_SETTINGS = loaded_data.get("CHARACTER_SETTINGS", CHARACTER_SETTINGS)
        CONVERSATION_HISTORY = loaded_data.get("CONVERSATION_HISTORY", CONVERSATION_HISTORY)
    
    # 使用全局变量
    current_character = CURRENT_CHARACTER
    character_settings = CHARACTER_SETTINGS
    history = CONVERSATION_HISTORY.get(user_id, [])
    
    # 确保当前人设存在
    if current_character not in character_settings:
        current_character = "默认人设"
        print(f"⚠️ 当前人设{current_character}不存在，已切换到默认人设")
    
    # 极强化的系统提示，强制使用当前人设
    system_prompt = f"【当前人设：{current_character}】\n\n{character_settings[current_character]}\n\n！！！警告：你必须完全且严格地扮演【{current_character}】这个角色，无论之前的对话历史如何，都要使用该角色的性格、语气和说话方式。绝对不能使用其他角色的语气或风格。忘记之前的一切，只专注于当前人设。\n\n注意：用户昵称是「{nickname}」。"
    
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})
    
    headers = {
        "Authorization": f"Bearer {OPENAI_CONFIG['api_key']}",
        "Content-Type": "application/json"
    }
    data = {
        "model": OPENAI_CONFIG["model"],
        "messages": messages,
        "temperature": 0.1,  # 降低随机性，更严格按照系统提示
        "timeout": 30
    }
    
    try:
        response = requests.post(
            f"{OPENAI_CONFIG['api_base']}/chat/completions",
            headers=headers,
            data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            timeout=30
        )
        response.raise_for_status()
        resp_json = response.json()
        if "choices" in resp_json and len(resp_json["choices"]) > 0:
            reply = resp_json["choices"][0]["message"]["content"].strip()
            add_conversation_msg(user_id, "user", message)
            add_conversation_msg(user_id, "assistant", reply)
            return reply
        else:
            return "⚠️ AI回复格式异常，暂无有效内容"
    except requests.exceptions.RequestException as e:
        print(f"OpenAI调用失败：{str(e)}")
        return f"⚠️ AI回复失败：{str(e)[:30]}"
    except Exception as e:
        print(f"AI回复处理失败：{str(e)}")
        return f"⚠️ AI回复失败：{str(e)[:30]}"

# 自动回复函数
def handle_auto_reply(msg: str, user_id: str = "auto_reply", nickname: str = "用户") -> str:
    from core.config import AUTO_REPLIES
    # 优先使用自动回复配置
    if msg in AUTO_REPLIES:
        return AUTO_REPLIES[msg]
    # 只有在API密钥存在时才调用OpenAI
    if OPENAI_CONFIG["api_key"]:
        return call_openai_api(msg, user_id, nickname)
    # 没有API密钥时，返回空字符串
    return ""

# 插件注册
__all__ = ["handle_openai_plugin", "handle_auto_reply", "handle_poke_event"]