PLUGIN_META = {
    "name": "SysInfo_plugin",  # 插件名称
    "commands": ["/运行状态", "/info", "/status"],  # 所有触发指令（对应系统状态查询功能）
    "handler": "handle_sysinfo_plugin",  # 核心处理函数名（插件入口函数）
    "chat_type": ["private", "group"],  # 支持私聊、群聊场景
    "permission": "all",  # 无权限限制
    "is_at_required": False,  
    "description": "系统状态查询插件，展示机器人运行信息、系统资源占用等详情",
    "version": "v1.0.0",
    "author": "GracyBot开发者"
}
