import asyncio
from datetime import datetime
import nest_asyncio
from ibkr.ibTools import init_ib_connection
from xai.grok_call import run_call_grok

async def main():
    ib = None
    grok_reporting = None

    try:
        ib = await init_ib_connection(dry_run=True)

        while True:
            grok_reporting = await run_call_grok(grok_reporting)

            print(f"\n\nGrok Reporting ({datetime.now().strftime("%Y-%m-%d %H:%M:%S")}):")
            print(grok_reporting)

            print("\n⏳ Waiting 5 minutes before next run...")
            await asyncio.sleep(300)  # 5 minutes
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user")
    except Exception as e:
        print(f"Error in main: {e}")
    finally:
        print("🔌 Disconnecting IB...")
        if ib and ib.isConnected():
            ib.disconnect()

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())