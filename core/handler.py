import json
import requests
import time
import threading
import sys
from flask import request, jsonify
from typing import Dict
from core.config import (
    MASTER_QQ,
    NAPCAT_HTTP_URL,
    AUTO_REPLIES,
    ROBOT_QQ
)
from core.utils import send_http_msg, logger
from core.security import sanitize_log
from core.plugin_manager import plugin_manager, PLUGIN_REGISTRY
from core.security_manager import security_manager
from core.monitor import monitor_manager
from core.logger_manager import logger_manager


def register_plugin(plugin_meta: Dict):
    PLUGIN_REGISTRY.append(plugin_meta)


def callback_base():
    try:
        # 获取客户端IP进行频率限制检查
        client_ip = request.remote_addr
        if not security_manager.check_rate_limit(client_ip):
            logger.warning(f"[安全防护] 客户端IP {client_ip} 频率超限")
            return jsonify({"retcode": 429, "msg": "请求频率过高，请稍后再试"}), 429

        data = request.get_json()
        if not data:
            logger.error(sanitize_log(f"[回调基础] 接收消息为空，请求体：{request.data[:50]}..."))
            return jsonify({"retcode": 1, "msg": "消息为空"}), 400

        # 输入验证
        if not security_manager.validate_input(data):
            logger.warning(f"[安全防护] 输入数据验证失败，可能包含恶意内容")
            return jsonify({"retcode": 403, "msg": "输入内容不合法"}), 403

        # 只传递必要的信息，避免日志过于冗长
        simplified_context = {
            'self_id': data.get('self_id'),
            'user_id': data.get('user_id'),
            'message_type': data.get('message_type'),
            'raw_message': data.get('raw_message', ''),  # 不限制消息长度
            'group_id': data.get('group_id'),
            'group_name': data.get('group_name', '')
        }
        logger_manager.log_with_context(
            logger,
            'INFO',
            "[回调基础] 收到消息",
            context=simplified_context
        )

        try:
            from plugins.XiaoYu_plugin.XiaoYu_plugin import FUNCTION_SWITCHES, send_welcome_msg
        except ImportError:
            logger.warning("⚠️ 小禹插件未加载，自动同意好友/群邀请、欢迎消息功能失效")
            FUNCTION_SWITCHES = {"auto_accept_friend": False, "auto_join_group": False}
            send_welcome_msg = lambda x, y, z: None

        if data.get("post_type") == "request" and data.get("request_type") == "friend":
            if FUNCTION_SWITCHES.get("auto_accept_friend", False):
                try:
                    requests.post(
                        f"{NAPCAT_HTTP_URL}/set_friend_add_request",
                        json={"flag": data.get("flag"), "approve": True},
                        timeout=10
                    )
                    logger.info(sanitize_log(f"[好友事件] 自动同意好友请求（用户ID：{data.get('user_id')}）"))
                except Exception as e:
                    logger.error(sanitize_log(f"[好友事件] 自动同意失败：{str(e)}"))

        if data.get("post_type") == "request" and data.get("request_type") == "group":
            if FUNCTION_SWITCHES.get("auto_join_group", False):
                try:
                    requests.post(
                        f"{NAPCAT_HTTP_URL}/set_group_add_request",
                        json={"flag": data.get("flag"), "sub_type": data.get("sub_type"), "approve": True},
                        timeout=10
                    )
                    logger.info(sanitize_log(f"[群事件] 自动同意群邀请（群ID：{data.get('group_id')}）"))
                except Exception as e:
                    logger.error(sanitize_log(f"[群事件] 自动同意失败：{str(e)}"))

        if data.get("post_type") == "notice" and data.get("notice_type") == "group_increase":
            try:
                group_id = str(data.get("group_id"))
                user_id = str(data.get("user_id"))
                nickname = data.get("user_info", {}).get("nickname", "未知用户")
                send_welcome_msg(group_id, user_id, nickname)
                logger.info(sanitize_log(f"[群事件] 新人入群（群ID：{group_id}，用户：{nickname}）"))
            except Exception as e:
                logger.error(sanitize_log(f"[群事件] 欢迎消息发送失败：{str(e)}"))

        # 处理戳一戳事件（notify类型）
        if data.get("post_type") == "notice" and data.get("notice_type") == "notify":
            sub_type = data.get("sub_type", "")
            # 检查是否是戳一戳事件
            if sub_type in ["poke", "lucky_king"]:
                try:
                    from plugins.OpenAI_plugin.poke_handler import handle_poke_event
                    # 调用戳一戳事件处理函数
                    handle_poke_event(data)
                    logger.info(sanitize_log(
                        f"[戳一戳事件] 处理戳一戳事件（用户ID：{data.get('user_id')}，目标ID：{data.get('target_id')}）"))
                except ImportError:
                    logger.warning("[戳一戳事件] OpenAI插件错误，戳一戳功能不可用")
                except Exception as e:
                    logger.error(sanitize_log(f"[戳一戳事件] 处理失败：{str(e)}"))
            return jsonify({"retcode": 0})

        if data.get("post_type") != "message":
            # 记录非消息类型操作的审计日志
            security_manager.log_audit_event(
                user_id="system",
                action=data.get("post_type"),
                resource=None,
                success=True,
                event_type="system",
                details={"request_type": data.get("request_type"), "notice_type": data.get("notice_type")}
            )
            logger.debug(sanitize_log(f"[回调基础] 非消息类型（类型：{data.get('post_type')}），忽略处理"))
            return jsonify({"retcode": 0})

        chat_type = data.get("message_type")
        sender_id = str(data.get("user_id", ""))
        target_id = str(data.get("user_id" if chat_type == "private" else "group_id", ""))
        raw_msg = data.get("raw_message", "").strip()
        nickname = data.get("sender", {}).get("nickname", "未知用户")

        # 对用户消息进行频率限制检查
        if not security_manager.check_rate_limit(f"user_{sender_id}"):
            logger.warning(f"[安全防护] 用户 {sender_id} 消息频率超限")
            if chat_type == "private":
                send_http_msg(sender_id, "您的消息发送频率过高，请稍后再试", "private")
            return jsonify({"retcode": 0})

        is_at_bot = False
        # 关键修改：删除纳西妲昵称，统一用机器人QQ号触发
        ROBOT_NICKNAME = ""

        if chat_type == "group":
            if isinstance(data.get("message"), list):
                is_at_bot = any(
                    item.get("type") == "at" and (
                            str(item.get("data", {}).get("qq")) == ROBOT_QQ
                    )
                    for item in data["message"]
                )
            else:
                is_at_bot = f"@{ROBOT_QQ}" in raw_msg
            if is_at_bot:
                raw_msg = raw_msg.replace(f"@{ROBOT_QQ}", "").strip()

        if sender_id == str(ROBOT_QQ):
            logger.debug(sanitize_log(f"[过滤] 机器人自身消息（{ROBOT_QQ}），跳过处理"))
            return jsonify({"retcode": 0})

        return {
            "chat_type": chat_type,
            "sender_id": sender_id,
            "target_id": target_id,
            "raw_msg": raw_msg,
            "nickname": nickname,
            "is_at_bot": is_at_bot,
            "data": data
        }
    except Exception as e:
        logger.error(sanitize_log(f"[回调基础] 处理异常：{type(e).__name__}，原因：{str(e)}"))
        return jsonify({"retcode": 1, "msg": f"回调处理异常：{str(e)}"}), 500


def dispatch_plugin_cmd(parsed_data):
    try:
        chat_type = parsed_data["chat_type"]
        sender_id = parsed_data["sender_id"]
        target_id = parsed_data["target_id"]
        raw_msg = parsed_data["raw_msg"]
        is_at_bot = parsed_data["is_at_bot"]
        nickname = parsed_data.get("nickname", "用户")
        handled = False

        # 记录消息审计日志
        security_manager.log_audit_event(
            user_id=sender_id,
            action="message_received",
            resource=None,
            success=True,
            event_type="message",
            details={"chat_type": chat_type, "target_id": target_id, "command": raw_msg[:50]}
        )

        if raw_msg == "/关机":
            # 检查是否是主人权限
            is_master, msg = security_manager.check_master_permission(sender_id)
            if is_master:
                send_http_msg(target_id, "🛑 正在执行关机操作...机器人将在3秒后关闭", chat_type)
                handled = True
                logger.info(sanitize_log(f"[内置命令] 主人{sender_id}执行/关机命令，即将关闭机器人"))

                # 延迟执行关机，给消息发送留出时间
                def delayed_shutdown():
                    time.sleep(3)
                    try:
                        from bot import safe_shutdown
                        safe_shutdown()
                    except ImportError:
                        logger.error("[关机指令] 无法导入safe_shutdown函数")
                        sys.exit(0)

                threading.Thread(target=delayed_shutdown, daemon=True).start()
            else:
                send_http_msg(target_id, "⚠️ 权限不足！只有机器人主人才可以执行关机操作", chat_type)
                logger.warning(f"[安全防护] 用户{sender_id}尝试执行关机指令，权限不足")
                handled = True

        elif raw_msg == "/重启":
            # 检查是否是主人权限
            is_master, msg = security_manager.check_master_permission(sender_id)
            if is_master:
                send_http_msg(target_id, "🔄 正在执行重启操作...机器人将在5秒后重启", chat_type)
                handled = True
                logger.info(sanitize_log(f"[内置命令] 主人{sender_id}执行/重启命令，即将重启机器人"))

                # 延迟执行重启，给消息发送留出时间
                def delayed_restart():
                    time.sleep(5)
                    try:
                        # 使用系统命令重启服务
                        import subprocess
                        # 假设机器人是通过systemctl管理的服务
                        subprocess.Popen(["systemctl", "restart", "bot"])
                    except Exception as e:
                        logger.error(f"[重启指令] 执行重启失败: {str(e)}")

                threading.Thread(target=delayed_restart, daemon=True).start()
            else:
                send_http_msg(target_id, "⚠️ 权限不足！只有机器人主人才可以执行重启操作", chat_type)
                logger.warning(f"[安全防护] 用户{sender_id}尝试执行重启指令，权限不足")
                handled = True

        elif raw_msg == "/关于":
            # 使用安全管理器验证命令执行
            if security_manager.validate_command(raw_msg):
                about_content = """🏷️ 机器人基础信息
• 机器人框架：GracyBot
• 当前版本：v1.8.0
• 核心定位：基于Python3.10编写的企业级安全QQ机器人框架，可对接NapCat，欢迎大佬来开发插件
• 开发模式：插件独立运行的特定开发模式，每个插件编写导入文件，通过插件注册器注册所有插件，可独立开发插件，无需增减其它文件
🛠️ 框架产品特征
• 核心开发语言：Python 3.10+
• 安全防护：全局日志脱敏、危险命令拦截、权限分级校验、频率限制、企业级安全管理
• 插件管理：动态插件加载、指令自动分发、插件隔离运行
• 基础工具：结构化日志系统、统一消息发送接口、自动回复匹配
• 兼容环境：Linux（Debian 11+）、Windows 10+（UTF-8编码适配）
• 依赖组件版本：Flask 2.3.3、Requests 2.31.0、cryptography 41.0.7
📋 核心特性
1. 企业级安全：敏感信息自动脱敏、系统命令风险拦截、输入验证、频率限制、审计日志
2. 配置管理：集中化配置、环境变量支持、多级配置优先级
3. 插件生态：支持插件独立目录管理，无需修改核心即可扩展功能
4. 稳定可靠：超时请求保护、异常精准捕获、跨平台编码适配
5. 监控与可观测性：结构化日志、性能监控、健康检查
📞 维护信息
• 开发作者：QQ:192004908
• 版本更新记录：v1.8.0 升级为企业级架构，新增安全管理器、配置管理器和日志管理器"""
                send_http_msg(target_id, about_content, chat_type)
                handled = True
                logger.info(sanitize_log(f"[内置命令] 用户{sender_id}执行/关于命令，已返回框架信息"))
            else:
                logger.warning(f"[安全防护] 命令验证失败，拒绝执行：{raw_msg}")

        if not handled:
            # 插件执行前的安全检查 - 支持basic_query和use_plugins权限
            has_basic_perm, _ = security_manager.check_permission(sender_id, "basic_query")
            has_plugin_perm, _ = security_manager.check_permission(sender_id, "use_plugins")
            has_permission = has_basic_perm or has_plugin_perm
            if has_permission:
                matched_plugin = plugin_manager.get_matched_plugin(raw_msg, chat_type, sender_id, is_at_bot)
                if matched_plugin:
                    # 验证插件命令安全性
                    plugin_name = matched_plugin.get("name", "unknown")
                    if security_manager.validate_plugin_access(plugin_name, sender_id):
                        handler_func = matched_plugin["handler_func"]
                        try:
                            plugin_start_time = time.time()
                            handler_func(
                                plugin_manager,
                                send_http_msg,
                                parsed_data["data"],
                                sender_id,
                                chat_type,
                                "all",
                                logger
                            )
                            plugin_execution_time = time.time() - plugin_start_time
                            monitor_manager.record_plugin_execution(plugin_name, plugin_execution_time, True)
                            handled = True
                            # 记录插件执行审计日志
                            security_manager.log_audit_event(
                                user_id=sender_id,
                                action="plugin_executed",
                                resource=plugin_name,
                                success=True,
                                event_type="plugin",
                                details={"plugin_name": plugin_name, "command": raw_msg,
                                         "execution_time": plugin_execution_time}
                            )
                            logger.info(sanitize_log(
                                f"[插件执行] 插件 {plugin_name} 执行成功，耗时: {plugin_execution_time:.3f}s"))
                        except Exception as e:
                            plugin_execution_time = time.time() - plugin_start_time
                            monitor_manager.record_plugin_execution(plugin_name, plugin_execution_time, False)
                            logger.error(sanitize_log(
                                f"[插件执行] 插件 {plugin_name} 执行异常：{str(e)}，耗时: {plugin_execution_time:.3f}s"))
                            security_manager.log_audit_event(
                                user_id=sender_id,
                                action="plugin_executed",
                                resource=plugin_name,
                                success=False,
                                event_type="plugin",
                                details={"plugin_name": plugin_name, "command": raw_msg, "error": str(e),
                                         "execution_time": plugin_execution_time}
                            )
                    else:
                        logger.warning(f"[安全防护] 用户 {sender_id} 无权访问插件 {plugin_name}")
                        security_manager.log_audit_event(
                            user_id=sender_id,
                            action="permission_denied",
                            resource="plugin",
                            success=False,
                            event_type="security",
                            details={"resource": "plugin", "plugin_name": plugin_name}
                        )
            else:
                logger.warning(f"[安全防护] 用户 {sender_id} 无插件访问权限")

        if not handled:
            try:
                from plugins.OpenAI_plugin.OpenAI_plugin import handle_auto_reply as openai_auto_reply
                from core.config import AUTO_REPLIES

                # 实现正确的优先级逻辑
                # 1. 检查是否是特殊命令（如小禹帮助），排除调用AI
                is_special_command = any(cmd in raw_msg for cmd in ["小禹帮助"])

                # 2. 检查是否触发了自动回复配置，优先使用自动回复
                is_auto_reply_match = raw_msg in AUTO_REPLIES

                # 3. 检查是否是私信且没有特殊前缀，允许直接对话
                is_private_direct_chat = chat_type == "private" and not (
                            raw_msg.startswith("/") or raw_msg.startswith("//")) and not is_special_command

                # 4. 群聊@机器人触发
                is_group_at_reply = chat_type == "group" and is_at_bot

                # 根据规则决定是否调用自动回复
                if is_auto_reply_match or is_private_direct_chat or is_group_at_reply:
                    # 确保nickname始终有值
                    if not nickname:
                        nickname = "用户"
                    # 传递正确的user_id和nickname
                    auto_reply = openai_auto_reply(raw_msg, sender_id, nickname)
                    if auto_reply:
                        if chat_type == "group":
                            send_http_msg(target_id, auto_reply, "group")
                        else:
                            send_http_msg(sender_id, auto_reply, "private")
            except ImportError:
                logger.warning("⚠️ OpenAI插件未加载，自动回复功能失效")

        logger.info(sanitize_log(f"[指令分发] 指令「{raw_msg[:20]}...」处理完成（handled：{handled}）"))
        return jsonify({"retcode": 0})
    except Exception as e:
        # 安全处理raw_msg，避免日志记录异常
        safe_msg = str(raw_msg)[:20] if raw_msg else ""
        logger.error(sanitize_log(f"[指令分发] 异常（指令：{safe_msg}...）：{type(e).__name__}，原因：{str(e)}"))
        return jsonify({"retcode": 1, "msg": f"指令处理异常：{str(e)}"}), 500


logger.info("✅ core/handler.py 加载完成")