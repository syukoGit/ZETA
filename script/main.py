import asyncio
from datetime import datetime, time as dt_time, timedelta
import json
import nest_asyncio
import sys
from ibkr.ibTools import init_ib_connection
from xai.grok_call import run_call_grok

def get_wait_time(timeBeforeNextRun):
    now = datetime.now()
    current_time = now.time()
    
    evening_cutoff = dt_time(22, 30)  # 22h30
    morning_start = dt_time(15, 0)     # 15h00
    
    if current_time >= evening_cutoff or current_time < morning_start:
        next_call = now + timedelta(seconds=3600)
        
        if current_time < morning_start:
            target_15h = datetime.combine(now.date(), morning_start)
            if next_call > target_15h:
                wait_seconds = (target_15h - now).total_seconds()
                return max(60, int(wait_seconds))
        
        return 3600
    else:
        next_call = now + timedelta(seconds=timeBeforeNextRun)
        target_22h30 = datetime.combine(now.date(), evening_cutoff)
        
        if next_call.time() > evening_cutoff:
            wait_seconds = (target_22h30 - now).total_seconds()
            return max(60, int(wait_seconds))
        
        return timeBeforeNextRun

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
                print(e.__traceback__)
                grok_reporting = {"timeBeforeNextRun": 600}  # Default wait time on error

            print(f"\n\nGrok Reporting ({datetime.now().strftime("%Y-%m-%d %H:%M:%S")}):")
            print(grok_reporting)

            base_wait_time = grok_reporting.get("timeBeforeNextRun", 600)
            timeBeforeNextRun = get_wait_time(base_wait_time)

            current_hour = datetime.now().strftime("%H:%M")
            
            remaining = timeBeforeNextRun
            while remaining > 0:
                mins, secs = divmod(remaining, 60)
                status_msg = f"\r⏳ {current_hour} - Prochain appel dans {int(mins):02d}:{int(secs):02d}  "
                sys.stdout.write(status_msg)
                sys.stdout.flush()
                
                # Dormir 1 seconde à la fois pour pouvoir mettre à jour l'affichage
                await asyncio.sleep(1)
                remaining -= 1
            
            # Nouvelle ligne avant le prochain appel
            print()
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