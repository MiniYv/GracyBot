from flask import Flask, request, jsonify
import threading
import time
import sys
import traceback
import logging

from core.config import ROBOT_QQ, CALLBACK_PORT, MASTER_QQ, BOT_VERSION
from core.handler import callback_base, dispatch_plugin_cmd
from core.plugin_manager import plugin_manager
from core.utils import send_http_msg, logger, logger_manager  # 复用utils全局日志和消息工具
from core.config_manager import config_manager
from core.monitor import monitor_manager, register_health_check_routes
# ========== Flask应用初始化 ==========
app = Flask(__name__)

# 回调接口（增强错误处理版本）
@app.route('/callback', methods=['POST'])
def callback():
    context = {
        'client_ip': request.remote_addr,
        'request_id': str(time.time())[-6:],  # 简单的请求ID生成
        'path': request.path
    }
    
    # 记录收到的消息
    monitor_manager.record_message_received()
    
    start_time = time.time()
    
    try:
        # 添加请求开始日志
        logger_manager.log_with_context(logger, logging.INFO, '请求开始处理', context)
        
        # 检查Content-Type
        if request.content_type != 'application/json':
            error_msg = f"不支持的Content-Type: {request.content_type}"
            logger_manager.log_with_context(logger, logging.WARNING, error_msg, context)
            monitor_manager.record_message_error()
            return jsonify({"retcode": 415, "msg": "仅支持application/json格式"}), 415
        
        # 获取并验证JSON数据
        try:
            json_data = request.get_json()
            if json_data is None:
                error_msg = "请求体无法解析为JSON格式"
                logger_manager.log_with_context(logger, logging.ERROR, error_msg, context)
                monitor_manager.record_message_error()
                return jsonify({"retcode": 400, "msg": "无效的JSON格式"}), 400
        except Exception as json_err:
            error_msg = f"JSON解析失败: {str(json_err)}"
            logger_manager.log_with_context(logger, logging.ERROR, error_msg, context)
            monitor_manager.record_message_error()
            return jsonify({"retcode": 400, "msg": "JSON解析错误"}), 400
        
        # 调用基础处理函数
        try:
            parsed_data = callback_base()
        except TimeoutError:
            error_msg = "处理超时"
            logger_manager.log_with_context(logger, logging.ERROR, error_msg, context, exc_info=True)
            monitor_manager.record_message_error()
            return jsonify({"retcode": 504, "msg": "请求处理超时"}), 504
        except ValueError as val_err:
            error_msg = f"数据验证失败: {str(val_err)}"
            logger_manager.log_with_context(logger, logging.ERROR, error_msg, context)
            monitor_manager.record_message_error()
            return jsonify({"retcode": 400, "msg": f"数据验证错误: {str(val_err)}"}), 400
        except PermissionError as perm_err:
            error_msg = f"权限验证失败: {str(perm_err)}"
            logger_manager.log_with_context(logger, logging.WARNING, error_msg, context)
            monitor_manager.record_message_error()
            return jsonify({"retcode": 403, "msg": "权限不足"}), 403
        except Exception as base_err:
            error_msg = f"基础处理函数异常: {str(base_err)}"
            logger_manager.log_with_context(logger, logging.ERROR, error_msg, context, exc_info=True)
            monitor_manager.record_message_error()
            return jsonify({"retcode": 500, "msg": "处理过程异常"}), 500
        
        # 分发命令处理
        if isinstance(parsed_data, dict):
            try:
                result = dispatch_plugin_cmd(parsed_data)
                processing_time = time.time() - start_time
                monitor_manager.record_message_processed(processing_time)
                logger_manager.log_with_context(logger, logging.INFO, '请求处理成功', context)
                return result
            except Exception as dispatch_err:
                error_msg = f"命令分发异常: {str(dispatch_err)}"
                logger_manager.log_with_context(logger, logging.ERROR, error_msg, context, exc_info=True)
                monitor_manager.record_message_error()
                # 优雅降级：返回通用错误，避免暴露内部细节
                return jsonify({"retcode": 500, "msg": "服务繁忙，请稍后再试"}), 500
        else:
            processing_time = time.time() - start_time
            monitor_manager.record_message_processed(processing_time)
            logger_manager.log_with_context(logger, logging.INFO, '非消息请求，已正常处理', context)
            return parsed_data
            
    except Exception as e:
        # 终极异常捕获，确保服务不崩溃
        error_msg = f"未预期的异常: {str(e)}"
        # 记录完整堆栈信息
        stack_trace = traceback.format_exc()
        logger_manager.log_with_context(logger, logging.CRITICAL, error_msg, context, extra={"stack_trace": stack_trace})
        
        # 向管理员发送错误通知
        try:
            error_notify = f"🚨 机器人异常警报 🚨\n"
            error_notify += f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            error_notify += f"错误: {str(e)}\n"
            error_notify += f"类型: {type(e).__name__}\n"
            send_http_msg(MASTER_QQ, error_notify, "private")
        except:
            # 确保通知失败不会影响响应
            pass
            
        # 返回安全的错误信息
        return jsonify({"retcode": 500, "msg": "系统维护中，请稍后再试"}), 500
# 主函数（极致精简，保留启动核心逻辑）
def setup_error_handlers():
    """设置全局错误处理器"""
    
    @app.errorhandler(404)
    def not_found(error):
        context = {
            'client_ip': request.remote_addr,
            'path': request.path,
            'method': request.method
        }
        logger_manager.log_with_context(logger, logging.WARNING, '404页面未找到', context)
        return jsonify({"retcode": 404, "msg": "接口不存在"}), 404
    
    @app.errorhandler(405)
    def method_not_allowed(error):
        context = {
            'client_ip': request.remote_addr,
            'path': request.path,
            'method': request.method
        }
        logger_manager.log_with_context(logger, logging.WARNING, f'方法不允许: {request.method}', context)
        return jsonify({"retcode": 405, "msg": "不支持的请求方法"}), 405
    
    @app.errorhandler(Exception)
    def handle_exception(error):
        """处理所有未捕获的异常"""
        context = {
            'client_ip': request.remote_addr,
            'path': request.path if hasattr(request, 'path') else 'unknown',
            'error_type': type(error).__name__
        }
        stack_trace = traceback.format_exc()
        logger_manager.log_with_context(logger, 
                                       logging.CRITICAL, 
                                       f'未处理的异常: {str(error)}', 
                                       context, 
                                       extra={"stack_trace": stack_trace})
        
        # 返回统一的错误响应
        return jsonify({"retcode": 500, "msg": "服务器内部错误"}), 500

def safe_shutdown(signum=None, frame=None):
    """安全关闭服务"""
    logger.info("🔄 正在安全关闭服务...")
    
    # 通知管理员
    try:
        shutdown_msg = f"🛑 GracyBot v{BOT_VERSION} 正在关闭\n"
        shutdown_msg += f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        send_http_msg(MASTER_QQ, shutdown_msg, "private")
    except:
        pass
    
    # 清理资源
    try:
        if 'plugin_manager' in globals():
            plugin_manager.shutdown()
            logger.info("✅ 插件管理器已关闭")
    except Exception as e:
        logger.error(f"❌ 关闭插件管理器异常: {str(e)}")
    
    # 关闭监控管理器
    try:
        if 'monitor_manager' in globals():
            monitor_manager.shutdown()
            logger.info("✅ 监控管理器已关闭")
    except Exception as e:
        logger.error(f"❌ 关闭监控管理器异常: {str(e)}")
    
    logger.info("✅ 服务已安全关闭")
    sys.exit(0)

if __name__ == "__main__":
    # 注册信号处理（优雅关闭）
    try:
        import signal
        signal.signal(signal.SIGINT, safe_shutdown)
        signal.signal(signal.SIGTERM, safe_shutdown)
    except (ImportError, AttributeError):
        # Windows可能不完全支持某些信号
        logger.warning("⚠️ 信号处理在当前环境可能不可用")
    
    # 1. 初始化配置
    try:
        config_manager.load()
        logger.info("✅ 配置加载完成")
    except Exception as e:
        logger.error(f"❌ 配置加载失败: {str(e)}")
        # 尝试使用默认配置继续
        logger.warning("⚠️ 尝试使用默认配置继续启动")
    
    # 2. 初始化插件管理器
    try:
        plugin_manager.init()
        logger.info("✅ 插件管理器初始化完成")
    except Exception as e:
        logger.error(f"❌ 插件管理器初始化失败: {str(e)}")
        # 记录详细错误但尝试继续运行（部分插件可能无法使用）
        logger.warning("⚠️ 部分插件可能无法正常工作")
    
    # 3. 设置错误处理器
    try:
        setup_error_handlers()
        logger.info("✅ 错误处理器设置完成")
    except Exception as e:
        logger.error(f"❌ 设置错误处理器失败: {str(e)}")
    
    # 4. 注册健康检查路由
    try:
        register_health_check_routes(app)
        logger.info("✅ 健康检查路由注册完成")
    except Exception as e:
        logger.error(f"❌ 注册健康检查路由失败: {str(e)}")
    
    # 4. 打印启动核心信息
    logger.info(f"\n====== GracyBot v{BOT_VERSION} 启动 ======")
    logger.info(f"📌 机器人QQ：{ROBOT_QQ} | 主人QQ:{MASTER_QQ}")
    logger.info(f"📡 回调地址：http://localhost:{CALLBACK_PORT}/callback")
    logger.info(f"✅ 所有初始化完成，等待消息...\n")
    
    # 5. 启动提醒消息（带优雅降级）
    try:
        welcome_msg = f"🎉 GracyBot v{BOT_VERSION} 启动成功！\n"
        welcome_msg += f"📌 功能说明：\n"
        welcome_msg += f"  • 私聊//+内容触发AI聊天\n"
        welcome_msg += f"  • 群聊@机器人+内容 或 //+内容触发回复\n"
        welcome_msg += f"  • 输入对应指令使用插件功能（如/运行状态）"
        threading.Timer(1, send_http_msg, args=(MASTER_QQ, welcome_msg, "private")).start()
    except Exception as e:
        logger.error(f"❌ 发送启动消息失败: {str(e)}")
    
    # 6. 启动Flask服务（带错误处理）
    try:
        # 配置Flask不捕获异常，让我们的错误处理器处理
        app.config['PROPAGATE_EXCEPTIONS'] = True
        app.run(host='0.0.0.0', port=CALLBACK_PORT, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        safe_shutdown()
    except Exception as e:
        logger.critical(f"❌ Flask服务启动失败: {str(e)}", exc_info=True)
        # 最后尝试通知管理员
        try:
            fail_msg = f"❌ GracyBot v{BOT_VERSION} 启动失败\n"
            fail_msg += f"错误: {str(e)}"
            send_http_msg(MASTER_QQ, fail_msg, "private")
        except:
            pass
        sys.exit(1)