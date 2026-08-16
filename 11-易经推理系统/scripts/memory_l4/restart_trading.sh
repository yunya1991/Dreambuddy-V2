#!/bin/bash
# 重启易经推理交易进程（setsid daemon 方式，脱离工具会话）
# 用 start_new_session=True (setsid) 启动，避免父 shell 退出导致进程被终止
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统

/opt/anaconda3/bin/python3 /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/start_daemon.py
