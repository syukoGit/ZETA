"""Entry point for OMEGA - runs script.main"""
from script.main import main
import asyncio
import nest_asyncio

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
