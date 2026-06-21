import os
import json
from pathlib import Path

def test_keys():
    # Print environment vars
    print("COINGLASS_API_KEY in env:", "COINGLASS_API_KEY" in os.environ)
    print("CG_API_KEY in env:", "CG_API_KEY" in os.environ)

    # Check nanoclaw mcp config
    mcp_path = Path("/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/agent_repo/nanoclaw/.mcp.json")
    if mcp_path.exists():
        with open(mcp_path) as f:
            mcp = json.load(f)
            cg_key = mcp.get("mcpServers", {}).get("gate_info_coinanalysis", {}).get("env", {}).get("CG_API_KEY")
            print("CG_API_KEY in mcp.json:", bool(cg_key))
            
    # Check .env in core_task1
    env_path = Path("ops/nanoclaw/core_task1/.env")
    if env_path.exists():
        print(".env in core_task1 exists")
        with open(env_path) as f:
            for line in f:
                if "COINGLASS" in line or "CG_" in line:
                    print("Found in .env:", line.split("=")[0])

test_keys()
