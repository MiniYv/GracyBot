"""监控面板插件元信息
提供系统状态和性能指标查看功能
"""

PLUGIN_META = {
    "name": "MonitorPlugin",
    "version": "1.0.0",
    "description": "查看系统状态和性能指标的监控插件",
    "commands": ["系统状态", "监控", "性能", "health", "status"],
    "handler": "handle_monitor",
    "chat_type": ["private", "group"],
    "permission": "all",  # 所有用户可使用
    "is_at_required": False
}
