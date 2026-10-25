"""Permanent protocol rejection fences original execution without dropping accounting."""
from threading import get_ident
from types import SimpleNamespace
from typing import Any, cast
import unittest

from agno.exceptions import ModelProviderError

from agent_factory.model_dispatch import DelegatingModel


class ModelProtocolFenceTests(unittest.IsolatedAsyncioTestCase):
    def model(self, code, *, ledger_failure=False, fence_failure=False):
        calls = []
        loop_thread = get_ident()
        error = ModelProviderError(message=code, status_code=400)
        def invoke(*args, **kwargs):
            calls.append('provider')
            raise error
        async def ainvoke(*args, **kwargs):
            return invoke()
        def stream(*args, **kwargs):
            invoke()
            yield
        async def astream(*args, **kwargs):
            invoke()
            yield
        def finish(identity, evidence):
            calls.append('accounting')
            if ledger_failure:
                raise RuntimeError('accounting failed')
        def fence():
            calls.append(('fence', get_ident() == loop_thread))
            if fence_failure:
                raise ValueError('fence failed')
        model = SimpleNamespace(invoke=invoke, ainvoke=ainvoke, invoke_stream=stream, ainvoke_stream=astream)
        ledger = SimpleNamespace(begin_attempt=lambda *args, **kwargs: 'original-attempt',
            evidence_for=lambda plan, value: None, finish_attempt=finish)
        DelegatingModel._guard_provider_calls(cast(Any, model), lambda: None,
            ledger=ledger, on_protocol_rejected=fence)
        return model, calls, error

    async def run_method(self, model, method):
        if method == 'invoke':
            return model.invoke()
        if method == 'invoke_stream':
            return list(model.invoke_stream())
        if method == 'ainvoke':
            return await model.ainvoke()
        return [item async for item in model.ainvoke_stream()]

    async def test_all_entrypoints_preserve_original_error_and_accounting_and_fence(self):
        for method in ('invoke', 'ainvoke', 'invoke_stream', 'ainvoke_stream'):
            with self.subTest(method=method):
                model, calls, original = self.model('PERSONAL_MODEL_TOOL_NOT_DECLARED')
                with self.assertRaises(ModelProviderError) as error:
                    await self.run_method(model, method)
                self.assertIs(error.exception, original)
                self.assertEqual(calls.count('provider'), 1)
                self.assertEqual(calls.count('accounting'), 1)
                self.assertEqual([item for item in calls if isinstance(item, tuple)],
                    [('fence', not method.startswith('a'))])

    async def test_ordinary_errors_are_not_permanent_fences(self):
        for method in ('invoke', 'ainvoke', 'invoke_stream', 'ainvoke_stream'):
            model, calls, _ = self.model('PERSONAL_MODEL_REQUEST_FAILED')
            with self.assertRaises(ModelProviderError):
                await self.run_method(model, method)
            self.assertEqual(calls, ['provider', 'accounting'])

    async def test_accounting_and_fence_are_both_attempted_even_if_either_fails(self):
        for method in ('invoke', 'ainvoke', 'invoke_stream', 'ainvoke_stream'):
            for ledger_failure, fence_failure in ((True, False), (False, True), (True, True)):
                with self.subTest(method=method, ledger=ledger_failure, fence=fence_failure):
                    model, calls, _ = self.model('PERSONAL_MODEL_TOOL_NOT_DECLARED',
                        ledger_failure=ledger_failure, fence_failure=fence_failure)
                    with self.assertRaises((ValueError, RuntimeError)) as error:
                        await self.run_method(model, method)
                    self.assertEqual(calls.count('accounting'), 1)
                    self.assertEqual(len([item for item in calls if isinstance(item, tuple)]), 1)
                    if ledger_failure and fence_failure:
                        chain = []
                        current = error.exception
                        while current is not None:
                            chain.append(str(current)); current = current.__context__
                        self.assertIn('accounting failed', chain)
                        self.assertIn('fence failed', chain)
