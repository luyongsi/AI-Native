import asyncio
import sys
import inspect
sys.path.insert(0, ".")

from a1_requirement_intake import A1RequirementIntake

async def test():
    a1 = A1RequirementIntake()
    await a1.init()

    fn = a1._mock_llm
    print(f"Function: {fn}")
    print(f"Has __wrapped__: {hasattr(fn, '__wrapped__')}")
    print(f"Is coroutine: {inspect.iscoroutinefunction(fn)}")
    print(f"Name: {getattr(fn, '__name__', '?')}")

    if hasattr(fn, '__wrapped__'):
        print(f"__wrapped__ name: {fn.__wrapped__.__name__}")
        print("WRAPPED OK")
    else:
        print("WARNING: _mock_llm is NOT wrapped!")
        for m in dir(a1):
            if 'llm' in m.lower() or 'mock' in m.lower():
                print(f"  {m}: {type(getattr(a1, m, None))}")

    await a1.close()
asyncio.run(test())
