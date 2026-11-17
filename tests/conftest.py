import asyncio
import inspect
from typing import Any
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        funcargs = pyfuncitem.funcargs
        testargs = {
            arg: funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames
        }
        asyncio.run(pyfuncitem.obj(**testargs))
        return True
    return None
