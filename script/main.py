import asyncio
from datetime import datetime
import json
import nest_asyncio
from ibkr.ibTools import init_ib_connection
from xai.grok_call import run_call_grok
from utils.timing import get_wait_time, countdown_display, DEFAULT_WAIT_TIME


async def main():
    ib = None
    grok_reporting = None

    try:
        ib = await init_ib_connection(dry_run=False)

        while True:
            try:
                print(f"\n🔄 Appel de Grok... ({datetime.now().strftime("%Y-%m-%d %H:%M:%S")}) :")

                grok_reporting = await run_call_grok(grok_reporting)
                grok_reporting = json.loads(grok_reporting)
                grok_reporting["as_of"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                print(f"Error during Grok call: {e}")
                grok_reporting = {"timeBeforeNextRun": DEFAULT_WAIT_TIME}

            print(f"\n\nGrok Reporting ({datetime.now().strftime("%Y-%m-%d %H:%M:%S")}):")
            print(grok_reporting)

            base_wait_time = grok_reporting.get("timeBeforeNextRun", DEFAULT_WAIT_TIME)
            time_before_next_run = get_wait_time(base_wait_time)

            await countdown_display(time_before_next_run)
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