import asyncio
import nest_asyncio
from ibkr.ibTools import init_ib_connection
from ibkr.tools.getTools import get_tools


async def main():
    ib = await init_ib_connection(dry_run=True)
    await asyncio.sleep(2)  # Wait for connection to stabilize
    tools = get_tools()
    tools_to_test = ["get_quote"]
    print(f"Available tools: {list(tools.keys())}")

    for tool_name in tools_to_test:
        tool = tools.get(tool_name)
        if tool:
            print(f"\nTesting tool: {tool_name}")
            res = await tool.handler({"symbol": "TXN"})
            print(f"Result: {res}")
    ib.disconnect()

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())